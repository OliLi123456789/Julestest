# news_service/kafka_publishers.py
import logging
from typing import Optional, Any # For type hints

logger = logging.getLogger(__name__)

class MockAlertKafkaProducer:
    """
    A mock Kafka producer for sending alerts.
    This simulates the interface of confluent_kafka.Producer but just logs.
    """
    def __init__(self, bootstrap_servers: str, client_id: str = "news_service_alert_producer"):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        # In a real producer, config would be like:
        # conf = {'bootstrap.servers': bootstrap_servers, 'client.id': client_id}
        # self.producer = Producer(conf)
        logger.info(f"MockAlertKafkaProducer initialized: servers='{bootstrap_servers}', client_id='{client_id}'")

    def produce(self, topic: str, key: Optional[str] = None, value: Optional[bytes] = None, callback: Optional[Any] = None):
        """
        Mocks sending a message.
        `value` should be bytes (e.g., serialized protobuf).
        `key` should be string or bytes, will be logged as string.
        """
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
        value_len = len(value) if value else 'None'
        log_msg = f"MockAlertKafka: Producing to topic='{topic}', key='{key_str}', value_len={value_len}"
        # logger.debug(log_msg) # Use debug for less noise, or info if every production is important to see
        print(f"PRINT_DEBUG: {log_msg}") # Using print for now if logger level is INFO by default for module

        if callback:
            # Simulate successful delivery for callback testing if needed
            # In confluent_kafka, err is None for success, msg object for context.
            # This part is simplified as the mock doesn't actually deliver.
            # callback(None, f"Mock delivery to {topic} with key {key_str}")
            pass

    def flush(self, timeout: float = 1.0) -> int:
        """Mocks flushing messages. Returns 0 (no messages remaining)."""
        # logger.debug(f"MockAlertKafka: Flush called with timeout {timeout}s.")
        print(f"PRINT_DEBUG: MockAlertKafka: Flush called with timeout {timeout}s.")
        return 0 # In confluent_kafka, returns number of messages still in queue.

    def close(self):
        """Mocks closing the producer."""
        # In a real producer, ensure flush() is called before close if not auto-flushing.
        logger.info("MockAlertKafkaProducer closed.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Set level to DEBUG to see debug logs from producer

    # Example usage:
    kafka_servers = "mock_kafka:9092"
    producer = MockAlertKafkaProducer(bootstrap_servers=kafka_servers)

    test_topic = "test.alerts"
    test_key = "test_key_123"
    test_value_str = '{"message": "This is a test alert!"}'
    test_value_bytes = test_value_str.encode('utf-8')

    producer.produce(topic=test_topic, key=test_key, value=test_value_bytes)
    producer.produce(topic=test_topic, key="another_key", value=b'{"data":"more data"}')
    producer.flush()
    producer.close()

    logger.info("MockAlertKafkaProducer example finished.")
