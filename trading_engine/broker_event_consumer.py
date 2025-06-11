import logging
import threading
import json
import time
import asyncio # New import
from trading_engine.oms.oms import OrderManagementSystem
from trading_engine.gen.python.broker_events.broker_events_pb2 import OrderStatusEvent, ExecutionReportEvent
from trading_engine.kafka_config import KafkaTradingEngineConfig
# from confluent_kafka import Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)

class MockKafkaConsumer:
    def __init__(self, config):
        self.config = config
        self.subscribed_topics = []
        self.messages_to_consume = {} # topic: [(value_bytes, error_obj)]
        self._closed = False
        logger.info(f"MockKafkaConsumer initialized with config: {config}")

    def subscribe(self, topics):
        if self._closed:
            raise RuntimeError("MockKafkaConsumer is closed.")
        self.subscribed_topics = topics
        logger.info(f"MockKafkaConsumer subscribed to: {topics}")

    def poll(self, timeout=1.0):
        if self._closed:
            # In confluent-kafka, poll() on a closed consumer might raise an error or return None.
            # Let's simulate returning None.
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            for topic in self.subscribed_topics:
                if topic in self.messages_to_consume and self.messages_to_consume[topic]:
                    msg_val_bytes, err_obj = self.messages_to_consume[topic].pop(0)

                    # Simulate key if needed, though not strictly used by handlers here
                    key_bytes = b'somekey'
                    if msg_val_bytes: # Try to get platform_order_id from payload for key
                        try:
                            msg_dict = json.loads(msg_val_bytes.decode('utf-8'))
                            platform_id = msg_dict.get('platform_order_id')
                            if platform_id:
                                key_bytes = str(platform_id).encode('utf-8')
                        except: # Fallback if payload not JSON or no platform_order_id
                            pass

                    mock_msg = type('MockMessage', (), {
                        'error': lambda: err_obj,
                        'value': lambda: msg_val_bytes,
                        'topic': lambda: topic,
                        'partition': lambda: 0,
                        'offset': lambda: 0, # Mock offset
                        'key': lambda: key_bytes
                    })
                    return mock_msg
            time.sleep(0.1) # Simulate waiting for messages
        return None

    def close(self):
        logger.info("MockKafkaConsumer closed.")
        self._closed = True # Mark as closed

    def add_message(self, topic, message_dict_payload, error=None): # For testing
        if topic not in self.messages_to_consume:
            self.messages_to_consume[topic] = []
        # Simulate protobuf serialization (as done by producer)
        self.messages_to_consume[topic].append((json.dumps(message_dict_payload).encode('utf-8'), error))


class BrokerEventConsumer:
    def __init__(self, oms: OrderManagementSystem, kafka_config: KafkaTradingEngineConfig):
        self.oms = oms
        self.kafka_config = kafka_config
        consumer_conf = {
            'bootstrap.servers': self.kafka_config.bootstrap_servers,
            'group.id': 'trading_engine_oms_group_1',
            'auto.offset.reset': 'earliest',
            # 'enable.auto.commit': False # For more control, but True is simpler for mock
        }
        self.consumer = MockKafkaConsumer(consumer_conf)
        self._running = False
        self._thread = None
        self.loop = asyncio.new_event_loop() # New asyncio loop

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            # Clean up loop resources if run_forever exits
            if hasattr(self.loop, 'shutdown_asyncgens'): # Python 3.6+
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()
            logger.info("BrokerEventConsumer: Asyncio event loop closed.")

    def start(self):
        if self._running:
            logger.warning("BrokerEventConsumer already running.")
            return

        self._running = True
        # Start the asyncio event loop in its own thread
        self._async_loop_thread = threading.Thread(target=self._run_async_loop, daemon=True, name="BrokerEventAsyncLoopThread")
        self._async_loop_thread.start()

        self.consumer.subscribe([
            self.kafka_config.order_status_updates_topic,
            self.kafka_config.execution_reports_topic
        ])
        self._thread = threading.Thread(target=self._consume_loop, daemon=True, name="BrokerEventConsumerPollThread")
        self._thread.start()
        logger.info("BrokerEventConsumer started with polling and async processing threads.")

    def _consume_loop(self):
        logger.info("BrokerEventConsumer: Polling loop started.")
        try:
            while self._running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    logger.error(f"Kafka Consumer error on topic {msg.topic()}: {msg.error()}")
                    continue

                logger.debug(f"Received message from topic {msg.topic()}, submitting to async processing.")
                # Schedule the async processing in the event loop
                asyncio.run_coroutine_threadsafe(self._process_message_async(msg), self.loop)
        except Exception as e:
             logger.error(f"Exception in BrokerEventConsumer polling loop: {e}", exc_info=True)
        finally:
            self.consumer.close() # Close Kafka consumer when polling loop exits
            logger.info("BrokerEventConsumer: Polling loop stopped and consumer closed.")

    async def _process_message_async(self, msg): # Now async
        topic = msg.topic()
        payload_bytes = msg.value()
        try:
            if topic == self.kafka_config.order_status_updates_topic:
                event = OrderStatusEvent.FromString(payload_bytes)
                logger.info(f"Async processing OrderStatusEvent for platform_order_id: {event.platform_order_id}, status: {event.status}")
                await self.oms._handle_broker_order_status_update(event) # Await async OMS method
            elif topic == self.kafka_config.execution_reports_topic:
                event = ExecutionReportEvent.FromString(payload_bytes)
                logger.info(f"Async processing ExecutionReportEvent for platform_order_id: {event.platform_order_id}, exec_id: {event.execution_id}")
                await self.oms._handle_broker_execution_report(event) # Await async OMS method
            else:
                logger.warning(f"Received message from unknown topic: {topic}")
        except Exception as e:
            logger.error(f"Error async processing message from topic {topic}: {e}. Payload (first 100 bytes): {payload_bytes[:100]}", exc_info=True)

    def stop(self):
        if not self._running:
            return
        logger.info("BrokerEventConsumer stopping...")
        self._running = False # Signal loops to stop

        # Stop the asyncio event loop first
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        if self._thread: # Polling thread
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("BrokerEventConsumer polling thread did not stop gracefully.")

        if hasattr(self, '_async_loop_thread') and self._async_loop_thread: # Async loop thread
            self._async_loop_thread.join(timeout=5.0)
            if self._async_loop_thread.is_alive():
                 logger.warning("BrokerEventConsumer asyncio loop thread did not stop gracefully.")

        logger.info("BrokerEventConsumer stopped.")
