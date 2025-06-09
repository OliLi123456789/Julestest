import logging
from typing import Optional
from confluent_kafka import Producer
from google.protobuf.message import Message # For type hinting proto messages

# Assuming config.py is in the same package historical_ingestor
from .config import KafkaConfig

logger = logging.getLogger(__name__)

class MarketDataProducer:
    def __init__(self, config: KafkaConfig):
        self.config = config
        producer_conf = {
            'bootstrap.servers': self.config.bootstrap_servers,
            'linger.ms': self.config.producer_linger_ms,
            'retries': self.config.producer_retries,
            # 'acks': 'all', # Recommended for durability
            # 'compression.type': 'snappy', # Or lz4, gzip, zstd
            # 'message.max.bytes': 10485760, # Example: 10MB
        }

        # Conceptual: Add SASL/SSL configuration if provided in self.config
        # if self.config.security_protocol and self.config.sasl_mechanism:
        #     producer_conf['security.protocol'] = self.config.security_protocol
        #     producer_conf['sasl.mechanism'] = self.config.sasl_mechanism
        #     if self.config.sasl_username and self.config.sasl_password: # Assuming these are actual creds now
        #         producer_conf['sasl.username'] = self.config.sasl_username
        #         producer_conf['sasl.password'] = self.config.sasl_password
        #     logger.info(f"Configuring Kafka producer with SASL: {self.config.security_protocol}")


        self.producer = Producer(producer_conf)
        self.delivery_reports_processed = 0
        self.delivery_errors = 0
        self.messages_produced = 0
        logger.info(f"Kafka producer initialized with brokers: {self.config.bootstrap_servers}")

        # Optional: A separate goroutine/thread could handle delivery reports if high throughput
        # For scripting, polling after produce or during flush might be sufficient.

    def _delivery_report(self, err, msg):
        """ Called by poll() or flush() on success or failure of message delivery. """
        self.delivery_reports_processed +=1
        if err is not None:
            self.delivery_errors += 1
            logger.error(f'Message delivery failed for {msg.key()}: {err} on topic {msg.topic()} [{msg.partition()}]')
            # TODO: Implement DLQ or more robust error handling for failed deliveries.
        else:
            # logger.debug(f'Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()} (Key: {msg.key()})')
            pass

    def publish_message(self, message: Message, key: str, message_type: str):
        """
        Serializes a Protobuf message and publishes it to the appropriate Kafka topic.
        """
        topic: Optional[str] = None
        if message_type == "trade": topic = self.config.trade_topic
        elif message_type == "quote": topic = self.config.quote_topic
        elif message_type == "aggregate": topic = self.config.aggregate_topic
        else:
            logger.error(f"Unknown message type for Kafka publishing: {message_type} for key {key}")
            return

        if not topic:
            logger.error(f"Kafka topic for message type '{message_type}' is not configured or empty. Key: {key}")
            return

        try:
            payload = message.SerializeToString()
        except Exception as e:
            logger.error(f"Failed to serialize protobuf message (type: {message_type}, key: {key}): {e}", exc_info=True)
            return

        try:
            # Produce is asynchronous. Delivery report callback will be triggered by poll() or flush().
            self.producer.produce(topic, key=key.encode('utf-8'), value=payload, callback=self._delivery_report)
            self.messages_produced += 1

            # Poll periodically to serve delivery reports.
            # For a script that produces many messages, you might poll less frequently
            # and do a final flush. If it's a long-running producer, a background poll thread is better.
            if self.messages_produced % 100 == 0: # Example: poll every 100 messages
                 self.producer.poll(0) # Non-blocking poll

        except BufferError as e: # Producer queue is full
            logger.error(f"Kafka producer queue is full for topic {topic} (key: {key}): {e}. Flushing producer...")
            self.producer.flush(5) # Flush for 5 seconds
            # Retry producing the message after flush
            try:
                self.producer.produce(topic, key=key.encode('utf-8'), value=payload, callback=self._delivery_report)
                self.messages_produced += 1
            except Exception as e_retry:
                 logger.error(f"Failed to produce message to {topic} (key: {key}) after flush: {e_retry}", exc_info=True)
        except Exception as e:
            logger.error(f"Error publishing message to {topic} (key: {key}): {e}", exc_info=True)


    def flush(self, timeout_seconds: int = 30):
        """
        Wait for all messages in the Producer queue to be delivered.
        Call this before shutting down.
        """
        logger.info(f"Flushing Kafka producer (timeout: {timeout_seconds}s). Messages produced: {self.messages_produced}, Delivery reports processed: {self.delivery_reports_processed}, Delivery errors: {self.delivery_errors}")
        remaining = self.producer.flush(timeout_seconds)
        if remaining > 0:
            logger.warning(f"{remaining} Kafka messages still pending in queue after flush timeout.")
        else:
            logger.info("All Kafka messages flushed successfully.")

        # Log final stats after flush, as flush triggers delivery reports
        logger.info(f"Final Kafka delivery stats: {self.delivery_reports_processed} reports processed, {self.delivery_errors} errors.")

# Example usage (for testing, typically called from main.py)
if __name__ == '__main__':
    # This setup assumes you have a Kafka instance running and topics created.
    # It also assumes your protobuf definitions are compiled and importable.
    # from market_data import market_data_pb2 as pb # Adjust import path

    # Mock config for testing
    class MockKafkaConfig:
        bootstrap_servers = "localhost:9092" # Change to your Kafka broker
        trade_topic = "marketdata.test.trades"
        quote_topic = "marketdata.test.quotes"
        aggregate_topic = "marketdata.test.aggregates"
        producer_linger_ms = 10
        producer_retries = 2

    cfg = MockKafkaConfig()
    producer = MarketDataProducer(cfg)

    # Create a dummy Aggregate message (requires actual pb2 generated code)
    # agg_msg = pb.Aggregate(ticker="TEST", open=100, high=101, low=99, close=100.5, volume=1000, start_time_ns=time.time_ns())
    # producer.publish_message(agg_msg, "TEST", "aggregate")

    # logger.info("Example message published (asynchronously). Check Kafka topic and delivery reports (if any errors).")

    producer.flush() # Important to see delivery reports and ensure messages are sent before exit
    logger.info("Kafka producer flushed and closed (implicitly by Python exit, or call producer.close() if it had such method).")
