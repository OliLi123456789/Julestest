import logging
from typing import Dict, List, Any, TYPE_CHECKING
from .base_strategy import BaseStrategy
from trading_engine.oms.models import Order # For on_order_update type hint

if TYPE_CHECKING:
    from trading_engine.oms.oms import OrderManagementSystem

logger = logging.getLogger(__name__)

class StrategyManager:
    def __init__(self, oms_interface: 'OrderManagementSystem'):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.symbol_to_strategies: Dict[str, List[BaseStrategy]] = {}
        self.oms_interface = oms_interface
        # For routing order updates back to strategies
        # This requires orders to be associated with a strategy_id when created.
        self.order_id_to_strategy_id_map: Dict[str, str] = {}


    def add_strategy(self, strategy: BaseStrategy):
        if strategy.strategy_id in self.strategies:
            logger.warning(f"Strategy with ID {strategy.strategy_id} already exists. Not adding.")
            return

        strategy.set_oms_interface(self.oms_interface)
        self.strategies[strategy.strategy_id] = strategy
        for symbol in strategy.symbols_of_interest:
            if symbol not in self.symbol_to_strategies:
                self.symbol_to_strategies[symbol] = []
            self.symbol_to_strategies[symbol].append(strategy)
        logger.info(f"Strategy {strategy.strategy_id} added, interested in symbols: {strategy.symbols_of_interest}")

    def record_order_strategy_mapping(self, order_id: str, strategy_id: str):
        """Records which strategy an order belongs to."""
        self.order_id_to_strategy_id_map[order_id] = strategy_id
        logger.debug(f"Order {order_id} mapped to strategy {strategy_id}.")


    def start_all_strategies(self):
        if not self.strategies:
            logger.info("No strategies to start.")
            return
        for strategy_id, strategy_instance in self.strategies.items():
            try:
                logger.info(f"Starting strategy: {strategy_id}")
                strategy_instance.on_start()
            except Exception as e:
                logger.error(f"Error starting strategy {strategy_id}: {e}", exc_info=True)

    def stop_all_strategies(self):
        if not self.strategies:
            logger.info("No strategies to stop.")
            return
        for strategy_id, strategy_instance in self.strategies.items():
            try:
                logger.info(f"Stopping strategy: {strategy_id}")
                strategy_instance.on_stop()
            except Exception as e:
                logger.error(f"Error stopping strategy {strategy_id}: {e}", exc_info=True)

    async def route_market_data(self, symbol: str, market_data: Any): # Changed to async
        if symbol in self.symbol_to_strategies:
            # logger.debug(f"Routing market data for {symbol} to {len(self.symbol_to_strategies[symbol])} strategies.")
            for strategy in self.symbol_to_strategies[symbol]:
                try:
                    await strategy.on_market_data(symbol, market_data) # Await async strategy method
                except Exception as e:
                    logger.error(f"Error in strategy {strategy.strategy_id} on_market_data for {symbol}: {e}", exc_info=True)
        # else:
            # This log can be very noisy if many symbols are not handled by any strategy.
            # logger.debug(f"No strategy interested in market data for {symbol}")


    async def route_order_update(self, order: Order): # Changed to async
        strategy_id = self.order_id_to_strategy_id_map.get(order.order_id)
        if strategy_id and strategy_id in self.strategies:
            strategy = self.strategies[strategy_id]
            try:
                logger.debug(f"Routing order update for order {order.order_id} to strategy {strategy_id}")
                await strategy.on_order_update(order) # Await async strategy method
            except Exception as e:
                logger.error(f"Error in strategy {strategy.strategy_id} on_order_update for order {order.order_id}: {e}", exc_info=True)
        else:
            # This could happen for orders not managed by strategies or if mapping is missing.
            logger.debug(f"No strategy found or mapped for order update: {order.order_id}. User ID: {order.user_id}")
            # Optionally, could iterate all strategies if a general broadcast is desired for some updates,
            # but typically order updates are specific to the originator.
            # For example, if user_id itself is the strategy_id or contains it:
            # if order.user_id in self.strategies:
            #    self.strategies[order.user_id].on_order_update(order)
            pass
