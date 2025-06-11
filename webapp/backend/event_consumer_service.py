# webapp/backend/event_consumer_service.py
import logging
import threading
import json # For mock consumer and dummy proto parsing
import os # For environment variables for topic names
import asyncio # New import for asyncio operations

# from .kafka_config_web import KafkaWebBackendConfig # Removed
from .config_web import app_config # Added
from .data_cache_service import DataCacheService
# Import Pydantic models for structuring WebSocket messages
from .main import OrderResponse # Assuming OrderResponse is in main.py
from .data_cache_service import PositionData # PositionData is in data_cache_service.py

# Import WebSocket manager
from .websocket_manager import websocket_conn_manager

# Assuming these protos are accessible and have FromString method or equivalent for mocks
# Ensure AccountValueUpdateEvent and AccountSummarySnapshotEvent are defined in broker_events_pb2.py
# For this subtask, we'll assume they exist or are mocked like the others.
from trading_engine.gen.python.broker_events.broker_events_pb2 import (
    OrderStatusEvent, ExecutionReportEvent, PortfolioUpdateEvent, BrokerInstrument,
    AccountValueUpdateEvent # Added
    # AccountSummarySnapshotEvent # Add if distinct and used
)

logger = logging.getLogger(__name__)

# --- Mock Protobufs and Helpers if not fully available/simulated previously ---
# This section ensures that even if the .proto files are basic, we have some mock functionality.
# A real system would rely on protoc-generated Python files.

def _ensure_mock_from_string(proto_class, class_name_str):
    if not hasattr(proto_class, 'FromString'):
        logger.info(f"Mocking FromString for {class_name_str} as it's missing.")
        def from_string_mock(byte_string):
            try:
                data = json.loads(byte_string.decode('utf-8'))
                # Create a new instance and populate its __dict__
                # This is a simplified deserialization for mock purposes.
                instance = proto_class() # Assumes default constructor exists
                instance.__dict__.update(data) # Directly update attributes
                # If BrokerInstrument is nested, it needs similar handling or assume it's a dict in data
                if 'instrument' in data and isinstance(data['instrument'], dict) and hasattr(instance, 'instrument'):
                    # If instance.instrument is expected to be a BrokerInstrument object
                    if hasattr(BrokerInstrument, '__init__'): # Check if BrokerInstrument can be instantiated
                         # This is a simplification; real proto would handle nested types.
                        instrument_obj = BrokerInstrument()
                        instrument_obj.__dict__.update(data['instrument'])
                        instance.instrument = instrument_obj
                return instance
            except json.JSONDecodeError:
                logger.error(f"Mock FromString for {class_name_str}: Could not decode JSON: {byte_string}")
                return proto_class() # Return default instance on error
            except Exception as e:
                logger.error(f"Mock FromString for {class_name_str} error: {e}")
                return proto_class()
        setattr(proto_class, 'FromString', classmethod(from_string_mock) if isinstance(proto_class, type) else from_string_mock)

_ensure_mock_from_string(OrderStatusEvent, "OrderStatusEvent")
_ensure_mock_from_string(ExecutionReportEvent, "ExecutionReportEvent")
_ensure_mock_from_string(PortfolioUpdateEvent, "PortfolioUpdateEvent")
_ensure_mock_from_string(BrokerInstrument, "BrokerInstrument")
_ensure_mock_from_string(AccountValueUpdateEvent, "AccountValueUpdateEvent") # Ensure mock for new type
# _ensure_mock_from_string(AccountSummarySnapshotEvent, "AccountSummarySnapshotEvent")


class MockKafkaConsumer:
    def __init__(self, config):
        self.config = config
        self.subscribed_topics = []
        self.messages_to_consume = {} # topic: [(value_bytes, error, key), ...]
        self.is_closed = False
        logger.info(f"WebApp EventConsumer MockKafka initialized: {config}")

    def subscribe(self, topics):
        if self.is_closed: raise RuntimeError("Consumer closed")
        self.subscribed_topics = topics
        logger.info(f"WebApp EventConsumer MockKafka subscribed to: {topics}")

    def poll(self, timeout=1.0):
        if self.is_closed: raise RuntimeError("Consumer closed")
        # Basic round-robin poll for simplicity
        for topic in self.subscribed_topics:
            if topic in self.messages_to_consume and self.messages_to_consume[topic]:
                msg_val_bytes, err, key_bytes = self.messages_to_consume[topic].pop(0)

                # Create a mock message object similar to confluent_kafka's Message
                mock_msg = type('MockMessage', (), {
                    'error': lambda: err,
                    'value': lambda: msg_val_bytes,
                    'topic': lambda: topic,
                    'key': lambda: key_bytes,
                    'partition': lambda: 0, # Mock partition
                    'offset': lambda: 0 # Mock offset
                })()
                return mock_msg
        return None # No message

    def close(self):
        if not self.is_closed:
            self.is_closed = True
            logger.info("WebApp EventConsumer MockKafka closed.")

    def add_message(self, topic, message_dict_payload, key_str='somekey', error=None):
        """ Helper to inject messages into the mock consumer for testing. """
        if topic not in self.messages_to_consume:
            self.messages_to_consume[topic] = []

        key_bytes = key_str.encode('utf-8') if key_str else None
        # Simulate protobuf serialization by encoding to JSON string then bytes
        value_bytes = json.dumps(message_dict_payload).encode('utf-8')
        self.messages_to_consume[topic].append((value_bytes, error, key_bytes))
        logger.debug(f"MockKafkaConsumer: Added message to topic {topic}, key {key_str}")


class WebAppEventConsumerService:
    def __init__(self, data_cache_service: DataCacheService): # kafka_config removed
        self.cache_service = data_cache_service
        # Kafka settings from app_config
        self.bootstrap_servers = app_config.KAFKA_BOOTSTRAP_SERVERS
        self.consumer_group_id = app_config.KAFKA_WEBAPP_CONSUMER_GROUP
        self.order_updates_topic = app_config.KAFKA_ORDER_STATUS_UPDATES_TOPIC
        self.exec_reports_topic = app_config.KAFKA_EXECUTION_REPORTS_TOPIC
        self.position_updates_topic = app_config.KAFKA_POSITION_DATA_TOPIC
        self.account_data_topic = app_config.KAFKA_ACCOUNT_DATA_TOPIC # New topic

        consumer_conf = {
            'bootstrap.servers': self.bootstrap_servers,
            'group.id': self.consumer_group_id,
            'auto.offset.reset': 'earliest'
        }
        # self.consumer = confluent_kafka.Consumer(consumer_conf) # Actual consumer
        self.consumer = MockKafkaConsumer(consumer_conf) # Use mock for now
        self._running = False
        self._kafka_poll_thread = None

        self._processing_loop = asyncio.new_event_loop()
        self._processing_thread = threading.Thread(
            target=self._run_processing_loop,
            daemon=True,
            name="WebAppEventProcThread"
        )

    def start(self):
        if self._running:
            logger.info("WebAppEventConsumerService already running.")
            return
        self._running = True

        # Start the asyncio processing loop thread
        if not self._processing_thread.is_alive():
            self._processing_thread.start()

        topics_to_subscribe = [
            self.order_updates_topic,
            self.exec_reports_topic,
            self.position_updates_topic,
            self.account_data_topic # Subscribe to new topic
        ]
        self.consumer.subscribe(topics_to_subscribe)
        self._kafka_poll_thread = threading.Thread(target=self._consume_loop, daemon=True, name="WebAppKafkaPollThread")
        self._kafka_poll_thread.start()
        logger.info(f"WebAppEventConsumerService started, consuming from topics: {topics_to_subscribe}")

    def _run_processing_loop(self):
        logger.info("WebAppEventConsumerService: Asyncio processing loop starting.")
        asyncio.set_event_loop(self._processing_loop)
        try:
            self._processing_loop.run_forever()
        finally:
            self._processing_loop.close()
            logger.info("WebAppEventConsumerService: Asyncio processing loop stopped and closed.")

    def _consume_loop(self):
        logger.info(f"WebAppEventConsumerService: Kafka polling loop started for group {self.consumer.config.get('group.id')}")
        try:
            while self._running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None: continue
                if msg.error():
                    logger.error(f"WebApp Kafka Consumer error: {msg.error()} on topic {msg.topic()}")
                    continue
                # Schedule asynchronous processing of the message
                asyncio.run_coroutine_threadsafe(self._process_message_async(msg), self._processing_loop)
        except Exception as e:
            logger.error(f"Exception in Kafka polling loop: {e}", exc_info=True)
        finally:
            if hasattr(self.consumer, 'close'): # Check if consumer has close method
                self.consumer.close()
            logger.info("WebAppEventConsumerService: Kafka polling loop stopped.")

    async def _process_message_async(self, msg): # Now async
        topic = msg.topic()
        payload_bytes = msg.value()
        key_str = msg.key().decode('utf-8') if msg.key() else None
        logger.debug(f"WebApp Consumer Async: Processing message from topic {topic}, key {key_str}")

        try:
            event_data_dict = {}
            parsed_proto = None
            user_id_for_broadcast = None
            ws_message_type = None
            ws_payload_data = None

            if topic == self.order_updates_topic:
                parsed_proto = OrderStatusEvent.FromString(payload_bytes)
                event_data_dict = parsed_proto.__dict__.copy() # Make a copy for modification
                user_id_for_broadcast = event_data_dict.get('user_id') # Assumes user_id is in event
                # If user_id is not directly in event, it might be derived from platform_order_id
                # by DataCacheService or a lookup service. For now, we rely on it being present
                # or being added by the cache service if it can derive it.
                # The cache service stores data that should be OrderResponse compatible.
                self.cache_service.update_order_from_event(event_data_dict)
                # Retrieve the potentially enriched/validated order data from cache for broadcast
                order_for_ws = self.cache_service.get_order_by_id(
                    user_id=user_id_for_broadcast, # This assumes user_id_for_broadcast is known
                    order_id=event_data_dict.get("platform_order_id") or event_data_dict.get("order_id")
                )
                if order_for_ws: # order_for_ws is an OrderResponse model instance
                    ws_message_type = "ORDER_UPDATE"
                    ws_payload_data = order_for_ws.dict() # Pydantic V1
                    if not user_id_for_broadcast: user_id_for_broadcast = order_for_ws.user_id

            elif topic == self.exec_reports_topic:
                parsed_proto = ExecutionReportEvent.FromString(payload_bytes)
                event_data_dict = parsed_proto.__dict__.copy()
                user_id_for_broadcast = event_data_dict.get('user_id')
                self.cache_service.update_order_from_event(event_data_dict)
                exec_report_order_id = event_data_dict.get("platform_order_id") or event_data_dict.get("order_id")
                order_for_ws = self.cache_service.get_order_by_id(
                    user_id=user_id_for_broadcast,
                    order_id=exec_report_order_id
                )
                if order_for_ws:
                    ws_message_type = "EXECUTION_REPORT" # Or could be generic ORDER_UPDATE
                    ws_payload_data = order_for_ws.dict() # Pydantic V1
                    if not user_id_for_broadcast: user_id_for_broadcast = order_for_ws.user_id


            elif topic == self.position_updates_topic:
                parsed_proto = PortfolioUpdateEvent.FromString(payload_bytes)
                event_data_dict = parsed_proto.__dict__.copy()
                user_id_for_broadcast = event_data_dict.get("ib_account_id") # This field holds user_id for positions
                self.cache_service.update_position_from_event(event_data_dict)
                symbol_from_event = event_data_dict.get("instrument", {}).get("symbol")
                if user_id_for_broadcast and symbol_from_event:
                    position_for_ws = self.cache_service.get_position(user_id=user_id_for_broadcast, symbol=symbol_from_event)
                    if position_for_ws:
                         ws_message_type = "POSITION_UPDATE"
                         ws_payload_data = position_for_ws.dict()

            elif topic == self.account_data_topic:
                # Assuming AccountValueUpdateEvent is the primary type on this topic.
                # A more robust solution might involve trying to parse as different known account event types
                # or having a wrapper message type in the .proto definition.
                try:
                    # Use the (potentially mocked) AccountValueUpdateEvent from global scope
                    account_event_proto = AccountValueUpdateEvent.FromString(payload_bytes)
                    event_data_dict = account_event_proto.__dict__.copy()

                    # Ensure user_id is consistently named for the cache service
                    # The cache service expects 'account_id' or 'user_id' for account events
                    if 'account_id' not in event_data_dict and 'ib_account_id' in event_data_dict:
                        event_data_dict['account_id'] = event_data_dict['ib_account_id']
                    elif 'account_id' not in event_data_dict and 'user_id' in event_data_dict: # if proto uses user_id
                         event_data_dict['account_id'] = event_data_dict['user_id']

                    self.cache_service.update_account_summary_from_event(event_data_dict)

                    user_id_for_broadcast = event_data_dict.get("account_id")
                    if user_id_for_broadcast: # Prepare for WebSocket broadcast
                        ws_message_type = "ACCOUNT_VALUE_UPDATE"
                        # Send a focused payload for account value updates
                        ws_payload_data = {
                           "key": event_data_dict.get("key"),
                           "value": event_data_dict.get("value"),
                           "currency": event_data_dict.get("currency"),
                           "account_id": user_id_for_broadcast
                        }
                        # Note: Full portfolio summary is not broadcast on each value update.
                        # Frontend can request full summary via API or another WS message if needed.
                except Exception as e_av:
                    logger.error(f"WebApp Consumer Async: Error processing AccountValueUpdate from {topic}, key {key_str}. Error: {e_av}", exc_info=True)
                    # Optionally, try parsing as AccountSummarySnapshotEvent if that's a possibility for the topic

            else:
                logger.warning(f"WebApp Consumer Async: Received message from unhandled topic: {topic}")

            # Broadcast if user_id and message are available
            if user_id_for_broadcast and ws_message_type and ws_payload_data:
                ws_message = {"type": ws_message_type, "data": ws_payload_data}
                await websocket_conn_manager.broadcast_to_user(user_id_for_broadcast, ws_message)
            elif ws_message_type:
                logger.warning(f"Processed {ws_message_type} for topic {topic}, but no user_id for broadcast. Key: {key_str}, Event main ID: {event_data_dict.get('platform_order_id') or event_data_dict.get('symbol') or event_data_dict.get('key')}")

        except Exception as e:
            logger.error(f"WebApp Consumer Async: Error processing message from topic {topic}, key {key_str}. Error: {e}", exc_info=True)

    def stop(self):
        if not self._running:
            logger.info("WebAppEventConsumerService already stopped or not started.")
            return
        logger.info("WebAppEventConsumerService stopping...")
        self._running = False # Signal Kafka polling loop to stop

        # Stop the asyncio processing loop
        if self._processing_loop.is_running():
            self._processing_loop.call_soon_threadsafe(self._processing_loop.stop)

        # Wait for Kafka polling thread to finish
        if self._kafka_poll_thread and self._kafka_poll_thread.is_alive():
            self._kafka_poll_thread.join(timeout=5.0)
            if self._kafka_poll_thread.is_alive():
                 logger.warning("WebAppKafkaPollThread did not exit in time.")

        # Wait for processing thread to finish
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
            if self._processing_thread.is_alive():
                 logger.warning("WebAppEventProcThread did not exit in time.")

        logger.info("WebAppEventConsumerService fully stopped.")

    # --- Helper to manually add messages to mock consumer for testing ---
    def add_mock_message(self, topic: str, message_dict: Dict, key: Optional[str] = None):
        if isinstance(self.consumer, MockKafkaConsumer):
            self.consumer.add_message(topic, message_dict, key_str=key if key else 'test_key')
            logger.info(f"Added mock message to topic {topic} for consumer.")
        else:
            logger.warning("Cannot add mock message: Consumer is not a MockKafkaConsumer.")
