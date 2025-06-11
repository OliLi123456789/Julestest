import logging
import threading
import json
import time
import os
import asyncio # New import

from trading_engine.strategies.strategy_manager import StrategyManager
from trading_engine.kafka_config import KafkaTradingEngineConfig
# from confluent_kafka import Consumer, KafkaError

logger = logging.getLogger(__name__)

# Simplified mock market data protos for this subtask
class MockQuote:
    def __init__(self, ticker="", bid_price=0.0, ask_price=0.0, bid_size=0, ask_size=0, timestamp_ns=0, **kwargs):
        self.ticker=ticker
        self.bid_price=bid_price
        self.ask_price=ask_price
        self.bid_size = bid_size # Added
        self.ask_size = ask_size # Added
        self.timestamp_ns = timestamp_ns # Added
        self.kwargs=kwargs
    @classmethod
    def FromString(cls, b):
        data = json.loads(b.decode('utf-8'))
        # Simulate potential structure from actual proto which might have nested timestamp
        if 'timestamp_ns' not in data and 'timestamp' in data and isinstance(data['timestamp'], dict): # Compatibility
            data['timestamp_ns'] = data['timestamp'].get('seconds', 0) * 1_000_000_000 + data['timestamp'].get('nanos', 0)
        return cls(**data)
    def __str__(self): return f"MockQuote({self.ticker} Bx:{self.bid_size}@{self.bid_price} Ax:{self.ask_size}@{self.ask_price} T:{self.timestamp_ns})"

class MockTrade:
    def __init__(self, ticker="", price=0.0, size=0, timestamp_ns=0, **kwargs):
        self.ticker=ticker
        self.price=price
        self.size=size
        self.timestamp_ns = timestamp_ns # Added
        self.kwargs=kwargs
    @classmethod
    def FromString(cls, b):
        data = json.loads(b.decode('utf-8'))
        if 'timestamp_ns' not in data and 'timestamp' in data and isinstance(data['timestamp'], dict):
            data['timestamp_ns'] = data['timestamp'].get('seconds', 0) * 1_000_000_000 + data['timestamp'].get('nanos', 0)
        return cls(**data)
    def __str__(self): return f"MockTrade({self.ticker} P:{self.price} S:{self.size} T:{self.timestamp_ns})"

class MockAggregate: # Represents a Bar
    def __init__(self, ticker="", open=0.0, high=0.0, low=0.0, close=0.0, volume=0, timeframe="M1", start_time_ns=0, end_time_ns=0, **kwargs):
        self.ticker=ticker; self.open=open; self.high=high; self.low=low; self.close=close; self.volume=volume;
        self.timeframe=timeframe; self.start_time_ns=start_time_ns; self.end_time_ns=end_time_ns; self.kwargs=kwargs
    @classmethod
    def FromString(cls, b):
        data = json.loads(b.decode('utf-8'))
        # Handle potential nested timestamp for start/end times if that's how it's serialized
        if 'start_time_ns' not in data and 'start_time' in data and isinstance(data['start_time'], dict):
            data['start_time_ns'] = data['start_time'].get('seconds', 0) * 1_000_000_000 + data['start_time'].get('nanos', 0)
        if 'end_time_ns' not in data and 'end_time' in data and isinstance(data['end_time'], dict):
            data['end_time_ns'] = data['end_time'].get('seconds', 0) * 1_000_000_000 + data['end_time'].get('nanos', 0)
        return cls(**data)
    def __str__(self): return f"MockAgg({self.ticker} TF:{self.timeframe} O:{self.open} H:{self.high} L:{self.low} C:{self.close} V:{self.volume} StartT:{self.start_time_ns})"


class MockKafkaConsumer:
    def __init__(self, config):
        self.config=config
        self.subscribed_topics=[]
        self.messages_to_consume={} # topic: [(value_bytes, error_obj)]
        self._closed = False
        logger.info(f"MD MockKafkaConsumer initialized with config: {config}")
    def subscribe(self, topics):
        if self._closed: raise RuntimeError("MockKafkaConsumer is closed.")
        self.subscribed_topics=topics
        logger.info(f"MD MockKafkaConsumer subscribed to: {topics}")
    def poll(self, timeout=1.0):
        if self._closed: return None
        start_time = time.time()
        while time.time() - start_time < timeout:
            for topic in self.subscribed_topics:
                if topic in self.messages_to_consume and self.messages_to_consume[topic]:
                    msg_val_bytes, err_obj = self.messages_to_consume[topic].pop(0)
                    mock_msg = type('MockMessage', (), {'error': lambda: err_obj, 'value': lambda: msg_val_bytes, 'topic': lambda: topic, 'partition': lambda:0, 'offset': lambda:0, 'key': lambda: b'mockkey'})
                    return mock_msg
            time.sleep(0.1)
        return None
    def close(self):
        logger.info("MD MockKafkaConsumer closed.")
        self._closed = True
    def add_message(self, topic, message_dict_payload, error=None): # For testing
        if topic not in self.messages_to_consume: self.messages_to_consume[topic] = []
        self.messages_to_consume[topic].append((json.dumps(message_dict_payload).encode('utf-8'), error))


class StrategyMarketDataConsumer:
    def __init__(self, strategy_manager: StrategyManager, kafka_config: KafkaTradingEngineConfig):
        self.strategy_manager = strategy_manager
        self.kafka_config = kafka_config
        consumer_conf = {
            'bootstrap.servers': self.kafka_config.bootstrap_servers,
            'group.id': 'trading_engine_strategy_md_group_1',
            'auto.offset.reset': 'latest'
        }
        self.consumer = MockKafkaConsumer(consumer_conf)
        self._running = False
        self._thread = None # For polling
        self.loop = asyncio.new_event_loop() # New asyncio loop
        self._async_loop_thread = None # For running the asyncio loop

        # Get topic names from the passed KafkaTradingEngineConfig instance
        self.ticks_topic = os.getenv("KAFKA_MARKET_DATA_TICKS_TOPIC", "ibkr.market-data.ticks") # Default if not in main config
        self.bars_topic = os.getenv("KAFKA_MARKET_DATA_BARS_TOPIC", "ibkr.market-data.bars") # Default if not in main config
        # If KafkaTradingEngineConfig is enhanced to hold these, use them:
        # self.ticks_topic = self.kafka_config.market_data_ticks_topic (if defined there)
        # self.bars_topic = self.kafka_config.market_data_bars_topic (if defined there)


    def start(self):
        if self._running:
            logger.warning("StrategyMarketDataConsumer already running.")
            return
        self._running = True
        topics_to_subscribe = []
        if hasattr(self.kafka_config, 'market_data_ticks_topic'): # Check if attribute exists
            topics_to_subscribe.append(self.kafka_config.market_data_ticks_topic)
        else: # Fallback to direct env var or hardcoded default used above
            topics_to_subscribe.append(self.ticks_topic)

        if hasattr(self.kafka_config, 'market_data_bars_topic'): # Check if attribute exists
            topics_to_subscribe.append(self.kafka_config.market_data_bars_topic)
        else: # Fallback
            topics_to_subscribe.append(self.bars_topic)

        self.consumer.subscribe(topics_to_subscribe)
        self._async_loop_thread = threading.Thread(target=self._run_async_loop, daemon=True, name="StrategyMDAsyncLoopThread")
        self._async_loop_thread.start()

        self.consumer.subscribe(topics_to_subscribe)
        self._thread = threading.Thread(target=self._consume_loop, daemon=True, name="StrategyMDConsumerPollThread")
        self._thread.start()
        logger.info(f"StrategyMarketDataConsumer started, subscribed to: {topics_to_subscribe}")

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            if hasattr(self.loop, 'shutdown_asyncgens'):
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()
            logger.info("StrategyMarketDataConsumer: Asyncio event loop closed.")

    def _consume_loop(self):
        logger.info("StrategyMarketDataConsumer: Polling loop started.")
        try:
            while self._running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None: continue
                if msg.error():
                    logger.error(f"MD Kafka Consumer error on topic {msg.topic()}: {msg.error()}");
                    continue
                # Schedule async processing
                asyncio.run_coroutine_threadsafe(self._process_market_data_message_async(msg), self.loop)
        except Exception as e:
             logger.error(f"Exception in StrategyMarketDataConsumer polling loop: {e}", exc_info=True)
        finally:
            self.consumer.close()
            logger.info("StrategyMarketDataConsumer: Polling loop stopped and consumer closed.")

    async def _process_market_data_message_async(self, msg): # Now async
        topic = msg.topic()
        payload_bytes = msg.value()
        market_data_event = None
        symbol = None
        try:
            cfg_ticks_topic = getattr(self.kafka_config, 'market_data_ticks_topic', self.ticks_topic)
            cfg_bars_topic = getattr(self.kafka_config, 'market_data_bars_topic', self.bars_topic)

            if topic == cfg_ticks_topic:
                data_dict = json.loads(payload_bytes.decode('utf-8'))
                if 'bid_price' in data_dict or 'ask_price' in data_dict or 'bid_size' in data_dict or 'ask_size' in data_dict:
                    market_data_event = MockQuote.FromString(payload_bytes)
                    symbol = market_data_event.ticker
                elif 'price' in data_dict and 'size' in data_dict:
                    market_data_event = MockTrade.FromString(payload_bytes)
                    symbol = market_data_event.ticker
                else:
                    logger.warning(f"Unknown message structure on ticks topic {topic}: {data_dict}")
                    return
            elif topic == cfg_bars_topic:
                market_data_event = MockAggregate.FromString(payload_bytes)
                symbol = market_data_event.ticker
            else:
                logger.warning(f"Received message from unhandled market data topic: {topic}")
                return

            if market_data_event and symbol:
                # StrategyManager.route_market_data is sync, and Strategy.on_market_data is now async
                # This means route_market_data needs to be able to handle/schedule async strategy methods
                # Or, for simplicity now, we assume strategy_manager.route_market_data can call async methods
                # if it's run within an asyncio context (which it is, via run_coroutine_threadsafe).
                # If BaseStrategy.on_market_data is truly async def, it should be awaited.
                # However, StrategyManager.route_market_data is currently synchronous.
                # This part might need StrategyManager to also become async-aware or use run_coroutine_threadsafe for each strategy call.
                # For now, keeping it as is, assuming strategy on_market_data can be called if it's async.
                # This will likely require strategy on_market_data to be called via asyncio.create_task or similar
                # if route_market_data itself is not async.
                # The prompt implies strategy on_market_data becomes async.
                # Let's assume StrategyManager.route_market_data is adapted to handle this (e.g. by awaiting).
                # StrategyManager.route_market_data is now async, so it should be awaited.
                await self.strategy_manager.route_market_data(symbol, market_data_event)


        except Exception as e:
            logger.error(f"Error async processing market data message from {topic}: {e}. Payload: {payload_bytes[:100]}", exc_info=True)

    def stop(self):
        if not self._running: return
        logger.info("StrategyMarketDataConsumer stopping...")
        self._running = False # Signal loops to stop

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        if self._thread: # Polling thread
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                 logger.warning("StrategyMarketDataConsumer polling thread did not stop gracefully.")

        if hasattr(self, '_async_loop_thread') and self._async_loop_thread: # Async loop thread
            self._async_loop_thread.join(timeout=5.0)
            if self._async_loop_thread.is_alive():
                 logger.warning("StrategyMarketDataConsumer asyncio loop thread did not stop gracefully.")
        logger.info("StrategyMarketDataConsumer stopped.")
