import unittest
from unittest.mock import MagicMock, patch, call
import logging

# Assuming BrokerEventProducer and its dependencies are importable
from ibkr_gateway_service.kafka_producer import BrokerEventProducer
from ibkr_gateway_service.config import KafkaConfig
# from google.protobuf.message import Message as ProtoMessage # Will be mocked
# from confluent_kafka import Producer as ConfluentProducer # Will be mocked


# Mock ProtoMessage for testing
class MockProtoMessage:
    def SerializeToString(self):
        return b"serialized_payload"

class TestBrokerEventProducer(unittest.TestCase):

    def setUp(self):
        self.mock_kafka_cfg = MagicMock(spec=KafkaConfig)
        self.mock_kafka_cfg.bootstrap_servers = "kafka:9092"
        # self.mock_kafka_cfg.security_protocol = None # For tests not covering SASL
        # self.mock_kafka_cfg.sasl_mechanism = None
        # self.mock_kafka_cfg.sasl_username = None
        # self.mock_kafka_cfg.sasl_password = None

        self.client_id_suffix = "test_instance"

        # Patch confluent_kafka.Producer before BrokerEventProducer is instantiated
        self.confluent_producer_patcher = patch('ibkr_gateway_service.kafka_producer.Producer')
        self.MockConfluentProducer = self.confluent_producer_patcher.start()
        self.mock_producer_instance = self.MockConfluentProducer.return_value


    def tearDown(self):
        self.confluent_producer_patcher.stop()

    # 1. Initialization Tests
    def test_init_success(self):
        producer = BrokerEventProducer(kafka_cfg=self.mock_kafka_cfg, client_id_suffix=self.client_id_suffix)

        expected_client_id = f"ibkr-gateway-producer-{self.client_id_suffix}"
        expected_producer_conf = {
            'bootstrap.servers': "kafka:9092",
            'client.id': expected_client_id,
            'linger.ms': 100,
            'retries': 3,
            'acks': 'all',
        }
        self.MockConfluentProducer.assert_called_once_with(expected_producer_conf)
        self.assertEqual(producer.producer, self.mock_producer_instance)
        self.assertEqual(producer.delivery_reports_processed, 0)
        self.assertEqual(producer.delivery_errors, 0)
        self.assertEqual(producer.consecutive_delivery_errors, 0)
        self.assertIsInstance(producer.DELIVERY_ERROR_THRESHOLD, int) # Check it's set

    def test_init_no_suffix(self):
        producer = BrokerEventProducer(kafka_cfg=self.mock_kafka_cfg)
        expected_client_id = "ibkr-gateway-producer"
        expected_producer_conf = {
            'bootstrap.servers': "kafka:9092",
            'client.id': expected_client_id,
            'linger.ms': 100,
            'retries': 3,
            'acks': 'all',
        }
        self.MockConfluentProducer.assert_called_once_with(expected_producer_conf)


    def test_init_producer_creation_fails(self):
        self.MockConfluentProducer.side_effect = Exception("Kafka connection error")
        with self.assertRaises(Exception) as context:
            BrokerEventProducer(kafka_cfg=self.mock_kafka_cfg, client_id_suffix=self.client_id_suffix)
        self.assertTrue("Kafka connection error" in str(context.exception))

    # 2. _delivery_report_callback Tests
    def test_delivery_report_callback_error(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "test_topic" # confluent_kafka.Message methods
        mock_msg.key.return_value = "test_key"

        err_msg = "Broker: Unknown topic or partition"

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer._delivery_report_callback(err_msg, mock_msg)

        self.assertEqual(producer.delivery_reports_processed, 1)
        self.assertEqual(producer.delivery_errors, 1)
        self.assertEqual(producer.consecutive_delivery_errors, 1)
        self.assertTrue(any(f"BrokerEvent delivery failed for topic test_topic key test_key: {err_msg}" in rec.getMessage() for rec in log_cm.records))

    def test_delivery_report_callback_error_critical_alert(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        producer.DELIVERY_ERROR_THRESHOLD = 2 # Lower for test
        producer.consecutive_delivery_errors = 2 # Already at threshold - 1

        mock_msg = MagicMock()
        mock_msg.topic.return_value = "critical_topic"
        mock_msg.key.return_value = "critical_key"
        err_msg = "Broker: Message timed out"

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='CRITICAL') as log_cm:
            producer._delivery_report_callback(err_msg, mock_msg) # This error makes it cross threshold

        self.assertEqual(producer.consecutive_delivery_errors, 3)
        self.assertTrue(any("CRITICAL_ALERT: BrokerEventProducer: Too many consecutive Kafka delivery failures (3)" in rec.getMessage() for rec in log_cm.records))
        self.assertTrue(any(f"Last error for topic critical_topic key critical_key: {err_msg}. KAFKA_PRODUCER_FAILURE" in rec.getMessage() for rec in log_cm.records))


    def test_delivery_report_callback_success(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        producer.consecutive_delivery_errors = 5 # Simulate prior errors
        mock_msg = MagicMock()
        # mock_msg.topic.return_value = "test_topic"
        # mock_msg.key.return_value = "test_key"

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='INFO') as log_cm:
            producer._delivery_report_callback(None, mock_msg) # No error

        self.assertEqual(producer.delivery_reports_processed, 1)
        self.assertEqual(producer.delivery_errors, 0) # delivery_errors is total, not reset
        self.assertEqual(producer.consecutive_delivery_errors, 0) # Reset on success
        self.assertTrue(any("Kafka delivery successful after 5 previous consecutive failures" in rec.getMessage() for rec in log_cm.records))


    # 3. publish_message Tests
    def test_publish_message_success(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MockProtoMessage() # Simple mock with SerializeToString

        producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")

        self.mock_producer_instance.produce.assert_called_once_with(
            "target_topic",
            key=b"test_key",
            value=b"serialized_payload",
            callback=producer._delivery_report_callback
        )
        self.mock_producer_instance.poll.assert_called_once_with(0)

    def test_publish_message_no_producer(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        producer.producer = None # Simulate init failure scenario
        mock_proto_msg = MockProtoMessage()
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")
        self.assertTrue(any("Producer not initialized. Cannot publish." in rec.getMessage() for rec in log_cm.records))


    def test_publish_message_empty_topic(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MockProtoMessage()
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="")
        self.assertTrue(any("Topic is empty for message with key test_key. Cannot publish." in rec.getMessage() for rec in log_cm.records))
        self.mock_producer_instance.produce.assert_not_called()


    def test_publish_message_serialization_error(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MagicMock() # More flexible mock
        mock_proto_msg.SerializeToString.side_effect = Exception("Serialization failed")

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")

        self.assertTrue(any("Failed to serialize protobuf message" in rec.getMessage() for rec in log_cm.records))
        self.mock_producer_instance.produce.assert_not_called()

    def test_publish_message_buffer_error_then_success(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MockProtoMessage()

        # Simulate BufferError on first produce, then success on retry
        self.mock_producer_instance.produce.side_effect = [BufferError("Queue full"), None]

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='WARNING') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")

        self.assertTrue(any("Kafka producer queue full" in rec.getMessage() for rec in log_cm.records))
        self.mock_producer_instance.flush.assert_called_once_with(5)
        self.assertEqual(self.mock_producer_instance.produce.call_count, 2)
        self.assertEqual(self.mock_producer_instance.poll.call_count, 2) # Poll after each produce

    def test_publish_message_buffer_error_then_fail(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MockProtoMessage()

        self.mock_producer_instance.produce.side_effect = [BufferError("Queue full"), Exception("Retry failed")]

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")

        self.assertTrue(any("Error publishing message (after retry for BufferError)" in rec.getMessage() for rec in log_cm.records))
        self.assertEqual(self.mock_producer_instance.produce.call_count, 2)


    def test_publish_message_other_produce_error(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        mock_proto_msg = MockProtoMessage()
        self.mock_producer_instance.produce.side_effect = Exception("Some Kafka error")

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='ERROR') as log_cm:
            producer.publish_message(message=mock_proto_msg, key="test_key", topic="target_topic")

        self.assertTrue(any("Error publishing message with key test_key" in rec.getMessage() for rec in log_cm.records))

    # 4. flush Tests
    def test_flush_success(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        self.mock_producer_instance.flush.return_value = 0 # No messages remaining

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='INFO') as log_cm:
            producer.flush(timeout_seconds=5)

        self.mock_producer_instance.flush.assert_called_once_with(5)
        self.assertTrue(any("All Kafka messages flushed successfully." in rec.getMessage() for rec in log_cm.records))

    def test_flush_messages_pending(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        self.mock_producer_instance.flush.return_value = 3 # 3 messages remaining

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='WARNING') as log_cm:
            producer.flush(timeout_seconds=2)

        self.mock_producer_instance.flush.assert_called_once_with(2)
        self.assertTrue(any("3 Kafka messages still pending in queue after flush timeout." in rec.getMessage() for rec in log_cm.records))

    def test_flush_no_producer(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        producer.producer = None
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.kafka_producer'), level='INFO') as log_cm:
            producer.flush()
        self.assertTrue(any("No producer to flush." in rec.getMessage() for rec in log_cm.records))


    # 5. close Tests
    def test_close(self):
        producer = BrokerEventProducer(self.mock_kafka_cfg)
        with patch.object(producer, 'flush') as mock_flush_method:
            producer.close(timeout_seconds=7)
            mock_flush_method.assert_called_once_with(7)


if __name__ == '__main__':
    unittest.main()
