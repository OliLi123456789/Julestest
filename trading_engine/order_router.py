import logging
from trading_engine.oms.models import Order # Assuming this path works from where OMS is run
from trading_engine.gen.python.requests.new_order_request_pb2 import NewOrderRequest
from trading_engine.kafka_config import KafkaTradingEngineConfig
# from confluent_kafka import Producer # Conceptual import

logger = logging.getLogger(__name__)

class MockKafkaProducer: # Mock for confluent_kafka.Producer
    def __init__(self, config):
        self.config = config
        logger.info(f"MockKafkaProducer initialized with: {config}")

    def produce(self, topic, key, value, callback=None):
        # In a real scenario, key would be str or bytes, value would be bytes.
        # For logging, ensure key is decoded if bytes.
        log_key = key
        if isinstance(key, bytes):
            log_key = key.decode('utf-8', 'ignore')
        logger.info(f"MockKafka: Producing to {topic}, key={log_key}, value_len={len(value)}")
        if callback: # Simulate async delivery report
            # In real client, this happens in a different thread via poll() or flush()
            # For mock, we can call it directly for simplicity if needed for testing the callback logic itself.
            # callback(None, f"Mocked message for key {log_key}") # (err, msg_mock)
            pass # For now, not invoking callback directly to keep it simple.

    def flush(self, timeout=5):
        logger.info(f"MockKafka: Flush called with timeout={timeout}")
        return 0 # Assuming 0 messages remaining after flush for mock

class OrderRouter:
    def __init__(self, kafka_config: KafkaTradingEngineConfig):
        self.kafka_config = kafka_config
        producer_conf = {'bootstrap.servers': self.kafka_config.bootstrap_servers}
        # self.producer = Producer(producer_conf) # Actual producer
        self.producer = MockKafkaProducer(producer_conf) # Use mock for this subtask
        logger.info(f"OrderRouter initialized. Target Kafka topic for new orders: {self.kafka_config.new_orders_topic}")

    def send_order_request(self, domain_order: Order, user_trade_config: dict) -> bool:
        # user_trade_config might contain account_id, sec_type, exchange, currency, TIF etc.
        # or these are enriched from instrument master / user preferences.
        try:
            order_request_proto = NewOrderRequest.FromDomainOrder(domain_order, user_trade_config)
            payload = order_request_proto.SerializeToString()

            key_str = domain_order.order_id # platform_order_id is key

            logger.info(f"Routing order {domain_order.order_id} to Kafka topic {self.kafka_config.new_orders_topic}")
            self.producer.produce(
                topic=self.kafka_config.new_orders_topic,
                key=key_str, # Kafka client typically expects str or bytes
                value=payload
                # callback=self._delivery_report # Optional delivery callback
            )
            # self.producer.poll(0) # For non-blocking, or flush for blocking
            self.producer.flush() # Ensure message is sent for this subtask's context
            logger.info(f"Order {domain_order.order_id} successfully routed to Kafka.")
            return True
        except Exception as e:
            logger.error(f"Failed to route order {domain_order.order_id} to Kafka: {e}", exc_info=True)
            return False

    # def _delivery_report(self, err, msg): # Optional
    #     key = msg.key().decode('utf-8') if msg.key() else None
    #     if err is not None:
    #         logger.error(f"Message delivery failed for order {key}: {err}")
    #     else:
    #         logger.info(f"Message delivered for order {key} to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

    def close(self): # Ensure producer is closed gracefully
         if self.producer:
             logger.info("OrderRouter: Flushing producer before close.")
             self.producer.flush()
             # If self.producer had an actual close() method, call it here. Mock doesn't.
             logger.info("OrderRouter: Producer flushed (MockKafkaProducer has no explicit close).")
