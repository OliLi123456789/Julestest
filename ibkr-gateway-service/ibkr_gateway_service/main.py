import logging
import signal
import sys
import time
import threading # Added for stop_event

from .config import load_config, Config # Assuming Config is defined or imported in .config
from .connection_manager import ConnectionManager
from .ib_wrapper import IBWrapperImpl
from .ib_client_wrapper import IBClientWrapper
from .request_handler import RequestHandler
from .response_processor import ResponseProcessor
from .kafka_producer import BrokerEventProducer
from .order_id_mapper import OrderIdMapper
from .leader_election import LeaderElector # New import

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global stop event for handling termination signals
# This allows goroutines/threads to observe a shutdown request.
# However, Python's signal handling runs in the main thread,
# so direct use of this in threads needs care. Threading events are better for thread coordination.
# ConnectionManager uses its own threading.Event for its loop.
# This global one is for the main loop here.
_app_stop_event = threading.Event()

def _signal_handler(signum, frame):
    logger.info(f"OS Signal {signal.Signals(signum).name} received, initiating graceful shutdown...")
    _app_stop_event.set()

def main():
    # Register signal handlers for SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cfg: Optional[Config] = None
    try:
        cfg = load_config()
        # Apply log level from config if possible (requires more advanced logging setup)
        log_level_from_config = getattr(logging, cfg.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level_from_config) # Set root logger level
        logger.info(f"Configuration loaded. Log level set to {cfg.log_level}.")
        logger.info(f"Service Instance ID: {cfg.service_instance_id}")
    except Exception as e:
        logger.fatal(f"Failed to load configuration: {e}", exc_info=True)
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
        service_instance_id=cfg.service_instance_id
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
