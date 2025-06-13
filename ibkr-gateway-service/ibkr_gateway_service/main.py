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
from .utils.secrets import get_secret # For Redis password

# Attempt to import redis, but don't fail if not installed unless Redis is configured
try:
    import redis # type: ignore
except ImportError:
    redis = None # type: ignore

# Kafka client and JSON for message processing
try:
    from confluent_kafka import Consumer, KafkaError, KafkaException # type: ignore
except ImportError:
    Consumer = None # type: ignore
    KafkaError = None # type: ignore
    KafkaException = None # type: ignore
import json


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

# Kafka Consumer Loop for OMS Order Requests
def oms_request_consumer_loop(cfg: Config, request_h: RequestHandler, stop_event: threading.Event, leader_event: threading.Event):
    if not Consumer:
        logger.error("OMS Consumer: confluent_kafka library not installed. Cannot start consumer loop.")
        return

    consumer_config = {
        'bootstrap.servers': cfg.kafka.bootstrap_servers,
        'group.id': cfg.kafka.consumer_group_id_oms_requests or "ibkr-gateway-oms-requests-consumer-group", # Ensure consumer_group_id_oms_requests is in KafkaConfig
        'auto.offset.reset': 'latest', # Or 'earliest', make configurable if needed
        'enable.auto.commit': True # Or False for manual commits
        # Add other consumer configs as needed, e.g., security.protocol for SASL
    }
    logger.info(f"OMS Consumer: Initializing with config: {consumer_config}")
    consumer = Consumer(consumer_config)
    consumer.subscribe([cfg.kafka.oms_order_requests_topic])
    logger.info(f"OMS Consumer: Subscribed to topic '{cfg.kafka.oms_order_requests_topic}'")

    consecutive_message_processing_errors = 0
    MESSAGE_PROCESSING_ERROR_THRESHOLD = 5

    try:
        while not stop_event.is_set():
            if not leader_event.is_set(): # Only consume if leader
                stop_event.wait(timeout=1.0)
                continue

            msg = consumer.poll(timeout=1.0)

            if msg is None:
                consecutive_message_processing_errors = 0 # Reset if poll is successful, even if no message
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug(f"OMS Consumer: Reached end of partition for {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")
                    consecutive_message_processing_errors = 0 # Reset on normal EOF
                elif msg.error().fatal():
                    logger.fatal(f"CRITICAL_ALERT: OMSOrderConsumer: Kafka consumer fatal error: {msg.error()}. OMS_CONSUMER_FATAL_ERROR")
                    break # Exit loop on fatal Kafka error
                else:
                    logger.error(f"OMS Consumer: Kafka error: {msg.error()}")
                    # Non-fatal Kafka errors might not increment message processing error counter unless they persist
                continue

            raw_msg_value = msg.value().decode('utf-8') if msg.value() else None
            logger.info(f"OMS Consumer: Received message from topic '{msg.topic()}': key='{msg.key()}', value='{raw_msg_value}'")

            if not raw_msg_value:
                logger.warning("OMS Consumer: Received empty message value. Skipping.")
                consecutive_message_processing_errors = 0 # Reset for this specific message skip
                continue

            current_msg_processed_successfully = False
            try:
                order_request_data = json.loads(raw_msg_value)
                action_type = order_request_data.get("action_type")
                payload = order_request_data.get("payload")

                if not action_type or not payload or not isinstance(payload, dict):
                    logger.error(f"OMS Consumer: Invalid message structure. 'action_type' or 'payload' missing or invalid. Message: {order_request_data}")
                    # This is a message format error, counts towards processing errors
                    raise ValueError("Invalid message structure")

                logger.info(f"OMS Consumer: Processing action '{action_type}' with payload: {payload}")
                if action_type == "NEW_ORDER":
                    result = request_h.process_internal_order_request(internal_order_req=payload)
                    logger.info(f"OMS Consumer: NEW_ORDER processing result: {result}")
                elif action_type == "CANCEL_ORDER":
                    ib_order_id_to_cancel = payload.get("ib_order_id_to_cancel")
                    platform_order_id_to_cancel = payload.get("platform_order_id_to_cancel")
                    if ib_order_id_to_cancel is not None:
                        request_h.process_order_cancellation_request(ib_order_id_to_cancel=int(ib_order_id_to_cancel))
                    elif platform_order_id_to_cancel is not None:
                         request_h.process_order_cancellation_request(platform_order_id_to_cancel=platform_order_id_to_cancel)
                    else:
                        logger.error("OMS Consumer: CANCEL_ORDER requires 'ib_order_id_to_cancel' or 'platform_order_id_to_cancel' in payload.")
                        raise ValueError("Missing order ID for cancel operation")
                elif action_type == "MODIFY_ORDER":
                    ib_order_id_to_modify = payload.get("ib_order_id_to_modify")
                    platform_order_id_to_modify = payload.get("platform_order_id_to_modify")
                    modifications = payload.get("modifications")
                    if not modifications or not isinstance(modifications, dict):
                        logger.error("OMS Consumer: MODIFY_ORDER 'modifications' payload is missing or invalid.")
                        raise ValueError("Invalid modifications payload for modify operation")

                    if ib_order_id_to_modify is not None:
                        request_h.process_order_modification_request(order_mod_req=modifications, ib_order_id_to_modify=int(ib_order_id_to_modify))
                    elif platform_order_id_to_modify is not None:
                        request_h.process_order_modification_request(order_mod_req=modifications, platform_order_id_to_modify=platform_order_id_to_modify)
                    else:
                        logger.error("OMS Consumer: MODIFY_ORDER requires 'ib_order_id_to_modify' or 'platform_order_id_to_modify' in payload.")
                        raise ValueError("Missing order ID for modify operation")
                else:
                    logger.warning(f"OMS Consumer: Unknown action_type '{action_type}'. Skipping message.")
                    # Consider if unknown action type should be an error or just a skip

                current_msg_processed_successfully = True # Mark as success if no exception from handler

            except json.JSONDecodeError as e_json:
                logger.error(f"OMS Consumer: Failed to deserialize JSON message: {e_json}. Message: {raw_msg_value}")
                # This is a message format error, counts towards processing errors
            except ValueError as e_val: # Catch custom ValueErrors from logic above
                logger.error(f"OMS Consumer: Validation error processing message: {e_val}. Message: {order_request_data if 'order_request_data' in locals() else raw_msg_value}")
            except Exception as e_proc: # Catch errors from RequestHandler calls
                logger.error(f"OMS Consumer: Error processing action '{action_type if 'action_type' in locals() else 'unknown'}': {e_proc}", exc_info=True)

            if current_msg_processed_successfully:
                consecutive_message_processing_errors = 0 # Reset on any successfully processed message (or skipped unknown action)
            else: # An error occurred during this message's processing
                consecutive_message_processing_errors += 1
                if consecutive_message_processing_errors > MESSAGE_PROCESSING_ERROR_THRESHOLD:
                    last_error_for_alert = "N/A"
                    if 'e_json' in locals(): last_error_for_alert = str(e_json)
                    elif 'e_val' in locals(): last_error_for_alert = str(e_val)
                    elif 'e_proc' in locals(): last_error_for_alert = str(e_proc)
                    logger.critical(
                        f"CRITICAL_ALERT: OMSOrderConsumer: Too many consecutive message processing failures ({consecutive_message_processing_errors}). "
                        f"Last error context: {last_error_for_alert}. OMS_CONSUMER_MESSAGE_PROCESSING_FAILURE"
                    )
                    # Potentially reset counter after alert to avoid spam, or implement cooldown
                    # consecutive_message_processing_errors = 0

    except KafkaException as e_kafka_fatal: # For fatal errors from consumer not caught by msg.error().is_fatal()
        logger.fatal(f"CRITICAL_ALERT: OMSOrderConsumer: Kafka consumer loop fatal KafkaException: {e_kafka_fatal}. OMS_CONSUMER_FATAL_KAFKA_EXCEPTION", exc_info=True)
    except Exception as e:
        logger.error(f"OMS Consumer: Unexpected error in consumer loop: {e}", exc_info=True)
    finally:
        logger.info("OMS Consumer: Closing Kafka consumer.")
        consumer.close()
        logger.info("OMS Consumer: Kafka consumer closed.")


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

    # --- Initialize Redis Client (if configured) ---
    redis_client = None
    if cfg.redis and cfg.redis.host: # Check if RedisConfig exists and host is configured
        if not redis:
            logger.error("Redis is configured (host specified) but 'redis' library is not installed. OrderIdMapper will use in-memory storage.")
        else:
            redis_password = None
            if cfg.redis.password_secret_name:
                try:
                    redis_password = get_secret(cfg.redis.password_secret_name, cfg.aws_region)
                    logger.info("Successfully fetched Redis password from Secrets Manager.")
                except Exception as e:
                    logger.error(f"Failed to load Redis password from secret '{cfg.redis.password_secret_name}': {e}. Attempting to connect without password.")

            try:
                redis_client = redis.Redis(
                    host=cfg.redis.host,
                    port=cfg.redis.port,
                    db=cfg.redis.db,
                    password=redis_password,
                    decode_responses=True # Ensures strings are returned, not bytes
                )
                redis_client.ping()
                logger.info(f"Successfully connected to Redis at {cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}. OrderIdMapper will use in-memory storage.")
                redis_client = None # Ensure it's None if connection failed
    else:
        logger.info("Redis host not configured in settings. OrderIdMapper will use in-memory storage.")

    # 5. Initialize RequestHandler
    order_id_mpr = OrderIdMapper(redis_client=redis_client)
    # OrderIdMapper's __init__ will log whether it's using Redis or in-memory.

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
    oms_consumer_thread: Optional[threading.Thread] = None
    oms_consumer_stop_event = threading.Event()


    def on_started_leading_func():
        nonlocal oms_consumer_thread # To assign to the oms_consumer_thread in the outer scope
        logger.info(f"Instance {cfg.service_instance_id} became the LEADER.")
        is_leader_event.set()

        # Start core services that only the leader should run
        logger.info("Leader: Starting IBKR Connection Manager for trading...")
        conn_manager.start()
        logger.info("Leader: Starting Response Processor...")
        response_proc.start()

        logger.info("Leader: Starting OMS Order Request Consumer...")
        oms_consumer_stop_event.clear() # Clear stop event before starting thread
        oms_consumer_thread = threading.Thread(
            target=oms_request_consumer_loop,
            args=(cfg, request_h, oms_consumer_stop_event, is_leader_event), # Pass request_h and leader_event
            name="OMSRequestConsumerLoop",
            daemon=True
        )
        oms_consumer_thread.start()

    def on_stopped_leading_func():
        nonlocal oms_consumer_thread # To access the oms_consumer_thread from the outer scope
        logger.info(f"Instance {cfg.service_instance_id} lost leadership or is stopping as leader.")
        is_leader_event.clear()

        logger.info("Not Leader: Stopping OMS Order Request Consumer...")
        if oms_consumer_thread and oms_consumer_thread.is_alive():
            oms_consumer_stop_event.set()
            oms_consumer_thread.join(timeout=5) # Wait for graceful shutdown
            if oms_consumer_thread.is_alive():
                logger.warning("OMS Consumer thread did not stop in time.")
        oms_consumer_thread = None # Clear the thread variable

        # Stop other core services
        logger.info("Not Leader: Stopping Response Processor...")
        response_proc.stop()
        logger.info("Not Leader: Stopping IBKR Connection Manager...")
        conn_manager.stop()

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

        # Stop OMS Consumer Thread (if active and not stopped by on_stopped_leading_func)
        if oms_consumer_thread and oms_consumer_thread.is_alive():
            logger.info("Ensuring OMS Order Request Consumer is stopped...")
            oms_consumer_stop_event.set()
            oms_consumer_thread.join(timeout=5)
            if oms_consumer_thread.is_alive():
                logger.warning("OMS Consumer thread did not stop in time during final shutdown.")

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
