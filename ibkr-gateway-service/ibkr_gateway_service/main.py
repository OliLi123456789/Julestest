import logging
import os
import signal
import sys
import time
import threading
import json # New import for health check
import http.server # New import for health check
import socketserver # New import for health check

from python_json_logger import jsonlogger

from .config import load_config, Config
from .connection_manager import ConnectionManager
from .ib_wrapper import IBWrapperImpl
from .ib_client_wrapper import IBClientWrapper
from .request_handler import RequestHandler
from .response_processor import ResponseProcessor
from .kafka_producer import BrokerEventProducer
from .order_id_mapper import OrderIdMapper
from .leader_election import LeaderElector

# Global stop event for handling termination signals
_app_stop_event = threading.Event()

# Initial logger setup (will be replaced by JSON logging)
# logger = logging.getLogger(__name__) # Get logger for this module

def setup_logging(log_level_str: str = "INFO"): # New function for clarity
    logger = logging.getLogger() # Get root logger

    # Remove existing handlers if any were added by basicConfig or other means
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_handler = logging.StreamHandler()
    # Example format: '%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(threadName)s %(message)s'
    # These will become fields in the JSON log.
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(threadName)s %(message)s'
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # Set initial level, can be overridden by config later
    initial_log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    logger.setLevel(initial_log_level)
    # Test message (optional)
    # logging.getLogger(__name__).info("JSON logging configured with default level.")


def _signal_handler(signum, frame):
    # Use a generic logger here as this might be called before specific module loggers are fully set up post-config
    logging.getLogger().info(f"OS Signal {signal.Signals(signum).name} received, initiating graceful shutdown...")
    _app_stop_event.set()

def main():
    # Call setup_logging early.
    setup_logging()
    logger = logging.getLogger(__name__) # Get logger for main module after initial setup

    # Register signal handlers for SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cfg: Optional[Config] = None
    try:
        cfg = load_config()
        # Apply log level from config
        log_level_from_config = getattr(logging, cfg.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level_from_config) # Set root logger level again based on config
        logger.info(f"Configuration loaded. Log level re-applied: {cfg.log_level}.") # Use the main module logger
        logger.info(f"Service Instance ID: {cfg.service_instance_id}")
    except Exception as e:
        # Use main module logger, or fallback to root if cfg failed before logger was re-obtained
        logging.getLogger(__name__).fatal(f"Failed to load configuration: {e}", exc_info=True)
        sys.exit(1)

    # 1. Initialize EWrapper
    wrapper_impl = IBWrapperImpl()

    # 2. Initialize ConnectionManager, passing the wrapper instance
    conn_manager = ConnectionManager(
        config=cfg.ibkr,
        wrapper=wrapper_impl,
        aws_region=cfg.aws_region,
        service_instance_id=cfg.service_instance_id
    )

    # 3. Link wrapper back to connection manager so wrapper can call manager's signal methods
    wrapper_impl.set_connection_manager(conn_manager)

    # 4. Initialize IBClientWrapper. It needs the EClient instance from ConnectionManager
    # (which ConnectionManager initializes with the wrapper) and the wrapper itself.
    ib_client_w = IBClientWrapper(
        eclient=conn_manager.client, # EClient is initialized within ConnectionManager
        wrapper=wrapper_impl,
        config=cfg.ibkr
    )

    # 5. Initialize RequestHandler
    order_id_mpr = OrderIdMapper()
    # TODO: For production OrderIdMapper, initialize with a persistent store client (e.g., Redis client)
    # order_id_mpr = OrderIdMapper(redis_client=get_redis_client_from_config(cfg.redis))

    request_h = RequestHandler(
        ib_client_wrapper=ib_client_w,
        wrapper=wrapper_impl,
        order_id_mapper=order_id_mpr
    )

    # 6. Initialize Kafka Producer for Broker Events
    broker_event_kafka_prod = BrokerEventProducer(
        kafka_cfg=cfg.kafka,
        client_id_suffix=cfg.service_instance_id
    )

    # 7. Initialize ResponseProcessor
    response_proc = ResponseProcessor(
        wrapper=wrapper_impl,
        kafka_producer=broker_event_kafka_prod,
        kafka_cfg=cfg.kafka,
        order_id_mapper=order_id_mpr,
        service_instance_id=cfg.service_instance_id,
        ib_client_wrapper=ib_client_w # Added ib_client_wrapper instance
    )

    # --- Leader Election Callbacks ---
    is_leader_event = threading.Event() # Event to signal leadership status to main loop

    def on_started_leading_func():
        logger.info(f"Instance {cfg.service_instance_id} became the LEADER.")
        is_leader_event.set()
        # Start core services that only the leader should run
        logger.info("Leader: Starting IBKR Connection Manager for trading...")
        conn_manager.start() # Start connection attempts with primary/trading client ID
        logger.info("Leader: Starting Response Processor...")
        response_proc.start()
        # TODO: Leader might also start Kafka consumers for OMS orders if that's its role

    def on_stopped_leading_func():
        logger.info(f"Instance {cfg.service_instance_id} lost leadership or is stopping as leader.")
        is_leader_event.clear()
        # Stop core services or transition them to standby
        logger.info("Not Leader: Stopping Response Processor...")
        response_proc.stop()
        logger.info("Not Leader: Stopping IBKR Connection Manager...")
        conn_manager.stop()
        # TODO: Leader might also stop Kafka consumers for OMS orders

    # 8. Initialize LeaderElector
    # POD_NAME should be passed as identity for K8s environments via Downward API
    pod_identity = os.getenv("POD_NAME", cfg.service_instance_id)
    leader_elector = LeaderElector(
        lease_name=cfg.leader_election.lease_name,
        lease_namespace=cfg.leader_election.lease_namespace,
        identity=pod_identity,
        on_started_leading=on_started_leading_func,
        on_stopped_leading=on_stopped_leading_func,
        lease_duration_seconds=cfg.leader_election.lease_duration_seconds,
        renew_deadline_seconds=cfg.leader_election.renew_deadline_seconds, # This is effectively used to calc renew interval now
        retry_period_seconds=cfg.leader_election.retry_period_seconds
    )
    logger.info("Starting Leader Election process...")
    leader_elector.start() # Starts the election loop in a separate thread


    # Main application loop
    try:
        logger.info("IBKR Gateway Service initialized. Main loop running (Ctrl+C to stop).")
        while not _app_stop_event.is_set():
            if is_leader_event.is_set():
                if not conn_manager.is_api_ready():
                    logger.warning("Leader: IBKR API not ready. ConnectionManager is attempting to connect/reconnect.")
                else:
                    # logger.debug("Leader: IBKR API is ready. Service operational.")
                    # TODO: Leader specific tasks, e.g., processing incoming OMS orders via Kafka/gRPC
                    # This part would use `request_h.process_internal_order_request()`
                    pass
            else:
                logger.info("Not Leader: Standing by. Will attempt to become leader if current leader fails.")
                # Non-leader can perform other tasks, e.g. serve read-only data if connected with different client ID

            _app_stop_event.wait(timeout=10.0) # Check stop signal every 10 seconds

        logger.info("Main loop: Shutdown signal received.")

    except Exception as e:
        logger.fatal(f"Critical error in main application loop: {e}", exc_info=True)
        _app_stop_event.set()
    finally:
        logger.info("Initiating service shutdown sequence...")

        logger.info("Stopping Leader Elector...")
        leader_elector.stop() # This will also call on_stopped_leading if it was the leader

        # on_stopped_leading should have already called response_proc.stop() and conn_manager.stop()
        # if this instance was the leader. If it wasn't, they weren't started by leader callbacks.
        # However, ensure they are gracefully stopped if they were somehow running.
        if response_proc._thread and response_proc._thread.is_alive(): # Check if processor was started
            logger.info("Ensuring Response Processor is stopped...")
            response_proc.stop()

        if conn_manager._connection_thread and conn_manager._connection_thread.is_alive(): # Check if manager was started
            logger.info("Ensuring Connection Manager is stopped...")
            conn_manager.stop()

        logger.info("Flushing and closing Broker Event Kafka Producer...")
        broker_event_kafka_prod.close()

        logger.info("IBKR Gateway Service shut down gracefully.")
        sys.exit(0)

if __name__ == "__main__":
    # This allows running the service directly using `python -m ibkr_gateway_service.main`
    # Ensure PYTHONPATH includes the root of your project if necessary for imports.
    main()
# --- Health Check Server Implementation ---

class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    # These will be set by the factory
    conn_manager_ref: Optional[ConnectionManager] = None
    response_proc_ref: Optional[ResponseProcessor] = None
    kafka_producer_ref: Optional[BrokerEventProducer] = None
    leader_elector_ref: Optional[LeaderElector] = None

    def do_GET(self):
        if self.path == '/health':
            health_status = {
                "overall_status": "HEALTHY", # Default to healthy
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "leader_status": "UNKNOWN",
                "ibkr_connection_status": "UNKNOWN",
                "response_processor_status": "UNKNOWN",
                "connection_manager_thread_status": "UNKNOWN", # Renamed for clarity
                "kafka_producer_status": "UNKNOWN"
            }
            is_unhealthy = False
            status_code = 200

            if HealthCheckHandler.leader_elector_ref:
                health_status["leader_status"] = "LEADER" if HealthCheckHandler.leader_elector_ref.is_leader() else "NOT_LEADER"

            if HealthCheckHandler.conn_manager_ref:
                health_status["ibkr_connection_status"] = "UP" if HealthCheckHandler.conn_manager_ref.is_api_ready() else "DOWN"
                health_status["connection_manager_thread_status"] = "ALIVE" if HealthCheckHandler.conn_manager_ref._connection_thread and HealthCheckHandler.conn_manager_ref._connection_thread.is_alive() else "DEAD"
                # IBKR connection is critical only if we are the leader
                if HealthCheckHandler.leader_elector_ref and HealthCheckHandler.leader_elector_ref.is_leader() and not HealthCheckHandler.conn_manager_ref.is_api_ready():
                    is_unhealthy = True
                if not (HealthCheckHandler.conn_manager_ref._connection_thread and HealthCheckHandler.conn_manager_ref._connection_thread.is_alive()):
                    is_unhealthy = True # Connection manager thread should always be alive

            if HealthCheckHandler.response_proc_ref:
                health_status["response_processor_status"] = "ALIVE" if HealthCheckHandler.response_proc_ref._thread and HealthCheckHandler.response_proc_ref._thread.is_alive() else "DEAD"
                # Response processor is critical only if we are the leader
                if HealthCheckHandler.leader_elector_ref and HealthCheckHandler.leader_elector_ref.is_leader() and not (HealthCheckHandler.response_proc_ref._thread and HealthCheckHandler.response_proc_ref._thread.is_alive()):
                    is_unhealthy = True

            if HealthCheckHandler.kafka_producer_ref:
                health_status["kafka_producer_status"] = "HEALTHY" if HealthCheckHandler.kafka_producer_ref.is_healthy() else "UNHEALTHY"
                if not HealthCheckHandler.kafka_producer_ref.is_healthy():
                    is_unhealthy = True

            if is_unhealthy:
                health_status["overall_status"] = "UNHEALTHY"
                status_code = 503 # Service Unavailable

            self.send_response(status_code)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(health_status).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        # Suppress default logging to stdout/stderr, as we use JSON logging via root logger
        return

def start_health_server(port: int,
                        comp_conn_manager: ConnectionManager,
                        comp_response_proc: ResponseProcessor,
                        comp_kafka_prod: BrokerEventProducer,
                        comp_leader_elector: LeaderElector):

    # Assign components to class variables of HealthCheckHandler
    # This is a way to make them accessible to handler instances without complex server subclassing for this basic case.
    HealthCheckHandler.conn_manager_ref = comp_conn_manager
    HealthCheckHandler.response_proc_ref = comp_response_proc
    HealthCheckHandler.kafka_producer_ref = comp_kafka_prod
    HealthCheckHandler.leader_elector_ref = comp_leader_elector

    with socketserver.TCPServer(("", port), HealthCheckHandler) as httpd: # Use the base handler
        logger.info(f"Health check server starting on port {port}")
        httpd.serve_forever()
