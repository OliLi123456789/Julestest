import logging
import time # Added for health check
from confluent_kafka import Producer #type: ignore
from google.protobuf.message import Message as ProtoMessage #type: ignore
from typing import Optional

# Assuming config.py is in the same package structure
from .config import KafkaConfig

logger = logging.getLogger(__name__)

class BrokerEventProducer:
    def __init__(self, kafka_cfg: KafkaConfig, client_id_suffix: Optional[str] = None):
        self.kafka_cfg = kafka_cfg

        producer_client_id = "ibkr-gateway-producer"
        if client_id_suffix:
            producer_client_id += f"-{client_id_suffix}"

        producer_conf = {
            'bootstrap.servers': kafka_cfg.bootstrap_servers,
            'client.id': producer_client_id,
            'linger.ms': 100, # Default linger.ms for batching
            'retries': 3,     # Default retries
            'acks': 'all',    # Ensure durability for critical broker events
            # 'compression.type': 'snappy', # Consider compression for higher volume
        }

        # Conceptual: Add SASL/SSL configuration if provided in kafka_cfg
        # if kafka_cfg.security_protocol and kafka_cfg.sasl_mechanism:
        #     producer_conf['security.protocol'] = kafka_cfg.security_protocol
        #     producer_conf['sasl.mechanism'] = kafka_cfg.sasl_mechanism
        #     if kafka_cfg.sasl_username and kafka_cfg.sasl_password: # Assuming these are actual creds
        #         producer_conf['sasl.username'] = kafka_cfg.sasl_username
        #         producer_conf['sasl.password'] = kafka_cfg.sasl_password
        #     logger.info(f"BrokerEventProducer: Configuring Kafka producer with SASL: {kafka_cfg.security_protocol}")

        try:
            self.producer = Producer(producer_conf)
            logger.info(f"BrokerEventProducer initialized. Client ID: {producer_client_id}, Brokers: {kafka_cfg.bootstrap_servers}")
        except Exception as e:
            logger.fatal(f"Failed to create BrokerEventProducer: {e}", exc_info=True)
            raise # Propagate error to fail fast if producer cannot be created

        self.delivery_reports_processed = 0
        self.delivery_errors = 0
        self._is_healthy = True # Health flag
        self._last_produce_error_ts: Optional[float] = None # Timestamp of last persistent error

        # Start a goroutine (in Go) or thread (in Python) for handling delivery reports
        # For Python client, poll() in produce or flush() handles this.
        # A separate thread for p.poll(0) in a loop is also an option for continuous background processing.
        # For this example, we'll rely on poll() during produce calls and flush().

    def _delivery_report_callback(self, err, msg):
        """ Called by poll() or flush() on success or failure of message delivery. """
        self.delivery_reports_processed += 1
        if err is not None:
            self.delivery_errors += 1
            logger.error(f'BrokerEvent delivery failed for topic {msg.topic()} key {msg.key()}: {err}')
            # Consider marking unhealthy on persistent errors.
            # For example, if specific error codes from `err` indicate a persistent issue.
            # err is a KafkaError object. err.code() gives specific error codes.
            # Example: if err.fatal(): self._is_healthy = False; self._last_produce_error_ts = time.time()
            # This needs careful selection of which errors are truly unrecoverable by the client.
        else:
            # Successful delivery could potentially mark as healthy if previously unhealthy and error condition cleared.
            # if not self._is_healthy and self._last_produce_error_ts and (time.time() - self._last_produce_error_ts > SOME_RECOVERY_THRESHOLD_SECONDS):
            #    self._is_healthy = True # Or after a few successful publishes
            #    logger.info("KafkaProducer marked as healthy again after successful publish.")
            # This can be very verbose, enable only for debugging.
            # logger.debug(f'BrokerEvent delivered to {msg.topic()} [{msg.partition()}] @ {msg.offset()} (Key: {msg.key()})')
            pass

    def publish_message(self, message: ProtoMessage, key: str, topic: str):
        if not self.producer:
            logger.error("BrokerEventProducer: Producer not initialized. Cannot publish.")
            return

        if not topic:
            logger.error(f"BrokerEventProducer: Topic is empty for message with key {key}. Cannot publish.")
            return

        try:
            payload = message.SerializeToString()
        except Exception as e:
            logger.error(f"BrokerEventProducer: Failed to serialize protobuf message (key: {key}, type: {type(message).__name__}) for topic {topic}: {e}", exc_info=True)
            return

        try:
            # produce() is asynchronous. Delivery report via callback.
            self.producer.produce(
                topic,
                key=key.encode('utf-8') if key else None,
                value=payload,
                callback=self._delivery_report_callback
            )
            # Poll for delivery reports. 0 means non-blocking.
            # For high-throughput, a dedicated polling thread is better than polling after each produce.
            # However, for moderate load or scripting, this can be acceptable.
            # Or, rely on linger.ms and flush() for batching and report handling.
            self.producer.poll(0)
        except BufferError:
            # This means the internal producer queue is full.
            logger.warning(f"BrokerEventProducer: Kafka producer queue full for topic {topic}. Flushing and retrying for key {key}...")
            self.producer.flush(5) # Flush for 5 seconds to make space
            try: # Retry once after flush
                self.producer.produce(topic, key=key.encode('utf-8') if key else None, value=payload, callback=self._delivery_report_callback)
                self.producer.poll(0)
            except Exception as e_retry:
                 logger.error(f"BrokerEventProducer: Error publishing message (after retry for BufferError) for key {key} to {topic}: {e_retry}", exc_info=True)
                 # This could be a point to mark unhealthy if retries fail consistently
                 self._is_healthy = False
                 self._last_produce_error_ts = time.time()
                 logger.critical(f"KafkaProducer marked as unhealthy due to persistent publishing failure (BufferError retry) for topic {topic}.")
        except Exception as e:
            logger.error(f"BrokerEventProducer: Error publishing message with key {key} to {topic}: {e}", exc_info=True)
            # This could also be a point to mark unhealthy depending on the exception type
            # For example, if it's a configuration error or authentication failure.
            # For now, only BufferError after retry explicitly marks unhealthy.
            # Consider adding:
            # self._is_healthy = False
            # self._last_produce_error_ts = time.time()
            # logger.critical(f"KafkaProducer marked as unhealthy due to publishing failure for topic {topic}.")


    def is_healthy(self) -> bool:
        # A more sophisticated check could involve:
        # - Checking producer.poll(0) for any immediate non-fatal errors if the client provides such status.
        # - Checking if the last known error (_last_produce_error_ts) is recent and implies a persistent problem.
        # - For now, it becomes unhealthy on critical publish errors and stays that way.
        #   Recovery to healthy might need a successful publish or a timer.
        if not self._is_healthy and self._last_produce_error_ts:
            # Example: try to become healthy again if last error was some time ago and we haven't had new ones.
            # This is a simplistic recovery idea. True recovery might need more checks.
            if (time.time() - self._last_produce_error_ts) > 300: # e.g., 5 minutes
                # Attempt a benign check or assume if no new errors, it might be ok.
                # For now, let's say it needs a successful publish to recover.
                # Or, for a health endpoint, just report current _is_healthy state.
                pass # Stays unhealthy until a more robust recovery is implemented
        return self._is_healthy

    def flush(self, timeout_seconds: int = 15):
        """
        Wait for all messages in the Producer queue to be delivered.
        Call this before shutting down.
        """
        if self.producer:
            logger.info(f"BrokerEventProducer: Flushing Kafka producer (timeout: {timeout_seconds}s)...")
            remaining = self.producer.flush(timeout_seconds)
            if remaining > 0:
                logger.warning(f"BrokerEventProducer: {remaining} Kafka messages still pending in queue after flush timeout.")
            else:
                logger.info("BrokerEventProducer: All Kafka messages flushed successfully.")
            logger.info(f"BrokerEventProducer: Final delivery stats - Reports Processed: {self.delivery_reports_processed}, Errors: {self.delivery_errors}")
        else:
            logger.info("BrokerEventProducer: No producer to flush.")

    def close(self, timeout_seconds: int = 15): # Added close method
        """Flushes and closes the producer. Currently, confluent_kafka Python producer doesn't have explicit close."""
        logger.info("BrokerEventProducer: Closing producer...")
        self.flush(timeout_seconds)
        # The confluent_kafka.Producer is closed when its instance is garbage collected or program exits.
        # There isn't an explicit .close() method like in some other Kafka clients.
        # Flushing is the main action for graceful shutdown.
        logger.info("BrokerEventProducer: Producer flushed (confluent-kafka auto-closes).")

# Example usage (for testing, typically called from main.py)
if __name__ == '__main__':
    # This setup assumes you have a Kafka instance running and topics created.

    # Mock config for testing
    class MockKafkaCfg:
        bootstrap_servers = "localhost:9092" # Change to your Kafka broker
        # These topics would be set from the main config in a real scenario
        order_updates_topic= "ibkr.test.order-updates"
        # ... other topics

    cfg = MockKafkaCfg()
    producer = BrokerEventProducer(cfg, "test-instance")

    # Create a dummy Protobuf message (requires actual pb2 generated code)
    # from common.gen.python.broker_events import broker_events_pb2 as pb
    # order_status_msg = pb.OrderStatusEvent(platform_order_id="test123", broker_order_id=1, status="Submitted")
    # producer.publish_message(order_status_msg, "test123", cfg.order_updates_topic)

    logger.info("Example message published (asynchronously). Check Kafka topic and delivery reports (if any errors).")

    producer.close()
    logger.info("BrokerEventProducer example finished.")
