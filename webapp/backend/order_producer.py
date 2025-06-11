# webapp/backend/order_producer.py
import logging
import uuid # For platform_order_id
import time
from trading_engine.gen.python.requests.new_order_request_pb2 import NewOrderRequest, OrderTypeProto # Assumed import path
# from .kafka_config_web import KafkaWebBackendConfig # Removed
from .config_web import app_config # Added
# from confluent_kafka import Producer # Conceptual

logger = logging.getLogger(__name__)

class MockKafkaProducer: # Mock for confluent_kafka.Producer
    def __init__(self, config): self.config = config; logger.info(f"WebApp MockKafkaProducer initialized: {config}")
    def produce(self, topic, key, value, callback=None):
        logger.info(f"WebApp MockKafka: Producing to {topic}, key={key}, value_len={len(value if value else [])}")
        if callback: # Simulate async callback behavior for testing if needed
            delivery_report = MockDeliveryReport(topic, key)
            callback(None, delivery_report) # err is None for success

    def flush(self, timeout=5): logger.info("WebApp MockKafka: Flush called"); return 0
    # confluent-kafka producer doesn't have close(), it's typically managed by __del__ or context manager
    # Adding it here for explicit resource management if desired/used.
    def close(self): logger.info("WebApp MockKafkaProducer closed.")

class MockDeliveryReport: # Helper for mock producer callback
    def __init__(self, topic, key): self._topic = topic; self._key = key
    def topic(self): return self._topic
    def key(self): return self._key
    def error(self): return None # Simulate no error
    def value(self): return None # Actual message value not usually needed in report


class WebOrderProducer:
    def __init__(self): # kafka_config removed
        self.kafka_bootstrap_servers = app_config.KAFKA_BOOTSTRAP_SERVERS
        self.new_orders_topic = app_config.KAFKA_NEW_ORDERS_TOPIC

        producer_conf = {'bootstrap.servers': self.kafka_bootstrap_servers}
        # self.producer = Producer(producer_conf) # Actual producer
        self.producer = MockKafkaProducer(producer_conf) # Use mock
        logger.info(f"WebOrderProducer initialized. Target Kafka topic: {self.new_orders_topic}")

    def send_new_order_request(self, user_id: str, api_order_data) -> str: # api_order_data is OrderCreate Pydantic model
        # Generate a unique platform_order_id for this request from the webapp
        platform_order_id = str(uuid.uuid4())

        # --- Map OrderCreate to NewOrderRequest protobuf ---
        # This mapping needs to be robust.
        # For now, make some assumptions for sec_type, exchange, currency, TIF, account_id.
        # These could come from user profile, instrument master, or more detailed API request.

        proto_order_type = OrderTypeProto.MARKET # Default
        if api_order_data.order_type.upper() == "LIMIT":
            proto_order_type = OrderTypeProto.LIMIT
        # TODO: Add mappings for STOP, STOP_LIMIT, TRAIL if OrderCreate supports them

        # Example: Derive sec_type, exchange, currency based on symbol or user settings (hardcoded for now)
        # In a real system, this might come from an instrument master or user preferences.
        current_symbol = api_order_data.symbol # Keep original for logging/response
        sec_details = {"sec_type": "STK", "exchange": "SMART", "currency": "USD", "account_id": "U_WEB_DEFAULT"}

        # Simple check for forex like "EUR.USD"
        if "." in api_order_data.symbol:
            parts = api_order_data.symbol.split('.')
            if len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3: # Basic validation
                sec_details["sec_type"] = "CASH"
                sec_details["exchange"] = "IDEALPRO" # Common for FX
                sec_details["currency"] = parts[1].upper()
                # Symbol for CASH should be just the currency pair base, e.g., EUR
                current_symbol_for_proto = parts[0].upper()
            else: # Not a clear FX pair, stick to default logic or raise error
                current_symbol_for_proto = api_order_data.symbol.upper()
        else: # Not FX, assume stock or other type
            current_symbol_for_proto = api_order_data.symbol.upper()


        order_request_proto = NewOrderRequest(
            platform_order_id=platform_order_id,
            user_id=user_id,
            symbol=current_symbol_for_proto, # Use potentially modified symbol for proto
            sec_type=sec_details["sec_type"],
            exchange=sec_details["exchange"],
            currency=sec_details["currency"],
            quantity=float(api_order_data.quantity),
            order_type=proto_order_type,
            limit_price=float(api_order_data.price) if api_order_data.price is not None else 0.0,
            time_in_force="DAY", # Default, could come from api_order_data
            account_id=sec_details["account_id"], # User's trading account for this order
            request_timestamp_utc=time.time() # Current timestamp
            # Add other fields like strike, right, last_trade_date if api_order_data supports them
        )

        # For the mock NewOrderRequest, SerializeToString might not exist or work as expected.
        # We'll simulate it by encoding to bytes if it's a mock, or use actual if it's a real proto.
        payload = b""
        if hasattr(order_request_proto, 'SerializeToString'):
            payload = order_request_proto.SerializeToString()
        else: # Fallback for a very basic mock object that doesn't have SerializeToString
            payload = str(order_request_proto).encode('utf-8')

        logger.info(f"Web backend sending NewOrderRequest to Kafka: ID={platform_order_id}, User={user_id}, Symbol={api_order_data.symbol} (Proto Symbol: {current_symbol_for_proto})")

        # Define a delivery callback for the producer (optional, good for logging/debugging)
        def delivery_report_callback(err, msg):
            if err is not None:
                logger.error(f"WebApp Kafka: Message delivery failed for order {msg.key() if msg else 'N/A'} to topic {msg.topic() if msg else 'N/A'}: {err}")
            else:
                logger.info(f"WebApp Kafka: Message delivered to topic {msg.topic()}, key {msg.key().decode('utf-8') if msg.key() else 'N/A'}")

        self.producer.produce(
            topic=self.new_orders_topic, # Use class attribute
            key=platform_order_id.encode('utf-8'), # Keys should be bytes
            value=payload,
            callback=delivery_report_callback
        )
        # self.producer.poll(0) # Not strictly needed for flush, but good for processing delivery reports if not using a dedicated thread
        self.producer.flush() # Ensure message is sent (for mock or actual producer)
        logger.info(f"NewOrderRequest {platform_order_id} sent to Kafka topic {self.new_orders_topic}.")
        return platform_order_id # Return the ID generated by the web backend

    def close(self):
        if self.producer:
            logger.info("Flushing and closing web order producer...")
            self.producer.flush()
            self.producer.close() # Mock producer has close for consistency
            logger.info("Web order producer closed.")
