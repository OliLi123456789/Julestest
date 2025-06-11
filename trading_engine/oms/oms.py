from typing import Optional, Dict, Any, List, TYPE_CHECKING
from trading_engine.oms.models import Order, OrderStatus, OrderType
from trading_engine.oms.order_repository import OrderRepository
from trading_engine.database import init_db, async_get_db_session
from trading_engine.order_router import OrderRouter
from trading_engine.kafka_config import KafkaTradingEngineConfig
from trading_engine.gen.python.broker_events.broker_events_pb2 import OrderStatusEvent, ExecutionReportEvent
from trading_engine.oms.position_manager import PositionManager
from trading_engine.risk_management.risk_manager import RiskManager
from trading_engine.risk_management.risk_rules import AccountInfo
import datetime
import logging
import time
import asyncio

if TYPE_CHECKING:
    from trading_engine.strategies.strategy_manager import StrategyManager

logger = logging.getLogger(__name__)

class OrderManagementSystem:
    def __init__(self):
        self.kafka_cfg = KafkaTradingEngineConfig()
        self.order_router = OrderRouter(self.kafka_cfg)
        self.risk_manager = RiskManager(config_file_path="risk_config.json")
        self.strategy_manager: Optional['StrategyManager'] = None

    def set_strategy_manager(self, strategy_manager: 'StrategyManager'):
        self.strategy_manager = strategy_manager

    async def submit_order(self, order: Order, user_trade_config: Optional[Dict[str, Any]] = None, strategy_id: Optional[str] = None) -> str:
        logger.info(f"OMS: Received new order {order.order_id} for {order.symbol}, User: {order.user_id}, StrategyID: {strategy_id}")
        # Order status is NEW by default from domain model

        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            position_manager = PositionManager(session)

            # RiskManager might change order.status to REJECTED or ERROR
            mock_account_info = AccountInfo(user_id=order.user_id, balance=1000000, buying_power=2000000)
            current_user_positions = position_manager.get_all_user_positions(order.user_id)

            if not self.risk_manager.check_pre_trade_rules(order, current_user_positions, mock_account_info):
                order_repository.add(order) # Add the order with status set by RiskManager
                try:
                    session.commit()
                    logger.info(f"OMS: Order {order.order_id} (status: {order.status.value}) persisted after failing risk checks.")
                except Exception as e_commit_risk_fail:
                    logger.error(f"OMS: DB Commit failed for risk-rejected order {order.order_id}: {e_commit_risk_fail}", exc_info=True)
                    session.rollback()

                if strategy_id and self.strategy_manager and self.strategy_manager.strategies.get(strategy_id):
                    await self.strategy_manager.route_order_update(order)
                return order.order_id

            # If risk checks pass, set to PENDING_SUBMIT and then add to repository
            order.update_status(OrderStatus.PENDING_SUBMIT)
            order_repository.add(order)
            logger.info(f"OMS: Order {order.order_id} passed risk checks, status PENDING_SUBMIT.")

            routing_config = user_trade_config if user_trade_config is not None else {
                "sec_type": "STK", "exchange": "SMART", "currency": "USD",
                "account_id": order.user_id,
                "time_in_force": "DAY"
            }
            if user_trade_config and "account_id" not in routing_config: # Ensure account_id is in routing_config
                 routing_config["account_id"] = order.user_id # or a default account

            route_success = self.order_router.send_order_request(order, routing_config)

            if route_success:
                logger.info(f"OMS: Order {order.order_id} successfully routed to Kafka. Status: {order.status.value}")
                if strategy_id and self.strategy_manager:
                    self.strategy_manager.record_order_strategy_mapping(order.order_id, strategy_id)
                try:
                    session.commit()
                except Exception as e_commit_route_ok:
                    logger.error(f"OMS: DB Commit failed for PENDING_SUBMIT order {order.order_id}: {e_commit_route_ok}", exc_info=True)
                    session.rollback()
            else:
                logger.error(f"OMS: Order {order.order_id} failed to be routed to Kafka. Order status will be ERROR.")
                # Order was already added with PENDING_SUBMIT, now update to ERROR
                order.update_status(OrderStatus.ERROR)
                order_repository.update(order) # Update existing record to ERROR
                try:
                    session.commit()
                    logger.info(f"OMS: Order {order.order_id} status set to ERROR and persisted due to routing failure.")
                except Exception as e_commit_error_state:
                    logger.error(f"OMS: DB Commit failed for ERROR state order {order.order_id} after routing failure: {e_commit_error_state}", exc_info=True)
                    session.rollback()

            if strategy_id and self.strategy_manager and self.strategy_manager.strategies.get(strategy_id):
                 await self.strategy_manager.route_order_update(order)
            return order.order_id

    IBKR_TO_OMS_STATUS_MAP = {
        "PENDINGSUBMIT": OrderStatus.API_PENDING,
        "APIPENDING": OrderStatus.API_PENDING,
        "PENDINGCANCEL": OrderStatus.PENDING_CANCEL,
        "PRESUBMITTED": OrderStatus.PRE_SUBMITTED,
        "SUBMITTED": OrderStatus.SUBMITTED,
        "APICANCELLED": OrderStatus.API_CANCELLED,
        "CANCELLED": OrderStatus.CANCELED,
        "FILLED": OrderStatus.FILLED,
        "PARTIALLYFILLED": OrderStatus.PARTIALLY_FILLED,
        "INACTIVE": OrderStatus.INACTIVE,
        "REJECTED": OrderStatus.REJECTED,
    }

    async def _handle_broker_order_status_update(self, event: OrderStatusEvent):
        logger.info(f"OMS: Processing OrderStatusEvent for platform_order_id: {event.platform_order_id}, broker_order_id: {event.broker_order_id}, broker_status: '{event.status}'")
        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            domain_order = order_repository.get_by_id(event.platform_order_id)
            if not domain_order:
                logger.warning(f"OMS: Received status update for unknown platform_order_id {event.platform_order_id}")
                return

            current_oms_status = domain_order.status
            broker_status_normalized = event.status.upper().replace(" ", "") if event.status else ""
            target_oms_status = self.IBKR_TO_OMS_STATUS_MAP.get(broker_status_normalized)

            if target_oms_status is None:
                logger.warning(f"OMS: Unmapped IBKR status '{event.status}' for order {event.platform_order_id}. Current OMS status: {current_oms_status.value}. Setting to OrderStatus.ERROR.")
                target_oms_status = OrderStatus.ERROR

            if current_oms_status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED] and \
               target_oms_status != current_oms_status and \
               target_oms_status != OrderStatus.ERROR:
                logger.warning(f"OMS: Order {event.platform_order_id} is already in terminal state {current_oms_status.value} but received new status '{event.status}' ({target_oms_status.value}). Allowing update.")

            domain_order.status = target_oms_status

            if event.broker_order_id and str(event.broker_order_id) != "0": domain_order.broker_order_id = str(event.broker_order_id)
            if event.perm_id and event.perm_id != 0: domain_order.perm_id = event.perm_id

            domain_order.filled_quantity = float(event.filled_quantity)
            if event.average_fill_price is not None and float(event.average_fill_price) >= 0:
                domain_order.average_fill_price = float(event.average_fill_price)

            # Refine status based on fill quantities from OrderStatusEvent
            if domain_order.status == OrderStatus.FILLED:
                if abs(domain_order.filled_quantity - domain_order.quantity) > 1e-9:
                     logger.warning(f"OMS: Order {domain_order.order_id} status from event is FILLED, but filled_quantity ({domain_order.filled_quantity}) != order_quantity ({domain_order.quantity}). Correcting filled_quantity.")
                     domain_order.filled_quantity = domain_order.quantity
            elif domain_order.status != OrderStatus.REJECTED and \
                 domain_order.status != OrderStatus.CANCELED and \
                 domain_order.status != OrderStatus.API_CANCELLED and \
                 domain_order.filled_quantity > 0 and \
                 abs(domain_order.filled_quantity) < abs(domain_order.quantity) - 1e-9:
                logger.info(f"OMS: Order {domain_order.order_id} has fills (Qty: {domain_order.filled_quantity}). Setting/confirming status PARTIALLY_FILLED from event status {target_oms_status.value}.")
                domain_order.status = OrderStatus.PARTIALLY_FILLED

            domain_order.update_status(domain_order.status) # This updates version and updated_at

            order_repository.update(domain_order)
            try:
                session.commit()
                logger.info(f"OMS: Order {domain_order.order_id} updated by OrderStatusEvent: New Status={domain_order.status.value}, FilledQty={domain_order.filled_quantity}, AvgPx={domain_order.average_fill_price}")
                if self.strategy_manager: await self.strategy_manager.route_order_update(domain_order)
            except Exception as e_commit:
                logger.error(f"OMS: DB Commit failed after OrderStatusEvent for order {domain_order.order_id}: {e_commit}", exc_info=True)
                session.rollback()

    async def _handle_broker_execution_report(self, event: ExecutionReportEvent):
        logger.info(f"OMS: Processing ExecutionReportEvent for platform_order_id: {event.platform_order_id}, exec_id: {event.execution_id}")
        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            position_manager = PositionManager(session)
            domain_order = order_repository.get_by_id(event.platform_order_id)
            if not domain_order:
                logger.warning(f"OMS: Received execution report for unknown platform_order_id {event.platform_order_id}")
                return

            domain_order.filled_quantity = float(event.cumulative_quantity)
            if event.average_price is not None and float(event.average_price) >= 0: domain_order.average_fill_price = float(event.average_price)
            if event.broker_order_id and str(event.broker_order_id) != "0": domain_order.broker_order_id = str(event.broker_order_id)
            if event.perm_id and event.perm_id != 0: domain_order.perm_id = event.perm_id

            new_status = domain_order.status
            if abs(domain_order.filled_quantity) >= abs(domain_order.quantity) - 1e-9:
                new_status = OrderStatus.FILLED
            elif abs(domain_order.filled_quantity) > 1e-9:
                new_status = OrderStatus.PARTIALLY_FILLED

            domain_order.update_status(new_status)
            order_repository.update(domain_order)

            user_id_for_position = domain_order.user_id
            if user_id_for_position:
                logger.info(f"Updating position based on execution for order {domain_order.order_id}, user {user_id_for_position}, exec_id {event.execution_id}")
                try: position_manager.update_position_from_fill(event, user_id_for_position)
                except Exception as pos_e:
                    logger.error(f"Failed to update position for user {user_id_for_position}, symbol {event.instrument.symbol} from exec_id {event.execution_id}: {pos_e}. Rolling back.", exc_info=True)
                    session.rollback(); return
            else:
                logger.error(f"Could not determine user_id for position update from order {domain_order.order_id}. Rolling back.")
                session.rollback(); return
            try:
                session.commit()
                logger.info(f"OMS: Order {domain_order.order_id} and related position updated by ExecutionReportEvent: New Status={domain_order.status.value}, CumQty={domain_order.filled_quantity}, AvgPx={domain_order.average_fill_price}")
                if self.strategy_manager: await self.strategy_manager.route_order_update(domain_order)
            except Exception as commit_e:
                logger.error(f"OMS: DB Commit failed after processing execution {event.execution_id} for order {domain_order.order_id}: {commit_e}", exc_info=True)
                session.rollback()

    async def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            domain_order = order_repository.get_by_id(order_id)
            return domain_order.status if domain_order else None

    async def cancel_order(self, order_id: str) -> bool:
        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            domain_order = order_repository.get_by_id(order_id)
            if not domain_order:
                logger.warning(f"OMS: Cancel request failed: Order {order_id} not found.")
                return False
            if domain_order.status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.API_CANCELLED, OrderStatus.PENDING_CANCEL]:
                logger.warning(f"OMS: Cancel request for order {order_id} denied: Order is already in state {domain_order.status.value}.")
                return False
            cancelable_states = [OrderStatus.NEW, OrderStatus.PENDING_SUBMIT, OrderStatus.API_PENDING, OrderStatus.PRE_SUBMITTED, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED]
            if domain_order.status in cancelable_states:
                domain_order.update_status(OrderStatus.PENDING_CANCEL)
                order_repository.update(domain_order)
                logger.info(f"OMS: Order {order_id} status set to PENDING_CANCEL. Routing cancel request (simulation).")
                # TODO: self.order_router.send_cancel_request(domain_order, ...)
                session.commit()
                if self.strategy_manager: await self.strategy_manager.route_order_update(domain_order)
                return True
            else:
                logger.warning(f"OMS: Cancel request for order {order_id} in unhandled state {domain_order.status.value}.")
                return False

    def _handle_ibkr_fill_update(self, order_id: str, fill_price: float, fill_quantity: float): pass
    def _handle_ibkr_cancel_confirm(self, order_id: str): pass
    def _handle_ibkr_rejection_update(self, order_id: str, reason: str): pass

    async def get_all_orders(self) -> List[Order]:
        async with async_get_db_session() as session:
            order_repository = OrderRepository(session)
            return order_repository.list_all()

    def close(self):
        logger.info("OrderManagementSystem: Closing resources...")
        if self.order_router: self.order_router.close()
        logger.info("OrderManagementSystem: Resources closed (DB session closed by async context manager).")

async def main_async():
    init_db()
    oms = OrderManagementSystem()
    from trading_engine.strategies.base_strategy import BaseStrategy
    from trading_engine.strategies.strategy_manager import StrategyManager
    from trading_engine.market_data_handler import StrategyMarketDataConsumer, MockQuote
    from trading_engine.broker_event_consumer import BrokerEventConsumer
    from trading_engine.broker_event_consumer import MockKafkaConsumer as BrokerMockConsumer
    from trading_engine.market_data_handler import MockKafkaConsumer as MDMockConsumer

    strat_manager = StrategyManager(oms)
    oms.set_strategy_manager(strat_manager)

    class MyDummyStrategy(BaseStrategy):
        def on_start(self): logger.info(f"Strategy {self.strategy_id} started, monitoring: {self.symbols_of_interest}")
        def on_stop(self): logger.info(f"Strategy {self.strategy_id} stopped.")
        async def on_market_data(self, symbol: str, market_data: Any):
            logger.info(f"Strategy {self.strategy_id} received market data for {symbol}: {market_data}")
            if isinstance(market_data, MockQuote) and market_data.ticker == "TESTSYM" and market_data.ask_price and 0 < market_data.ask_price < 100:
                logger.info(f"{self.strategy_id} sees favorable price for TESTSYM ({market_data.ask_price}), attempting to buy.")
                try:
                    domain_order = Order(user_id=f"{self.strategy_id}_user", symbol="TESTSYM", quantity=10, order_type=OrderType.LIMIT, price=market_data.ask_price)
                    user_trade_cfg = {"sec_type": "STK", "exchange": "SMART", "currency": "USD", "account_id": "STRAT_ACC_001", "time_in_force": "GTC"}
                    order_id = await self._oms_interface.submit_order(domain_order, user_trade_config=user_trade_cfg, strategy_id=self.strategy_id)
                    logger.info(f"Strategy {self.strategy_id} submitted order {order_id} for TESTSYM.")
                except Exception as e: logger.error(f"Strategy {self.strategy_id} failed to submit order for TESTSYM: {e}", exc_info=True)
        async def on_order_update(self, order: Order): logger.info(f"Strategy {self.strategy_id} received order update: ID={order.order_id}, Status={order.status.value}, FilledQty={order.filled_quantity}")

    dummy_strat = MyDummyStrategy("dummy_strat_1", ["AAPL", "TESTSYM"])
    strat_manager.add_strategy(dummy_strat)
    strat_manager.start_all_strategies()
    broker_event_consumer = BrokerEventConsumer(oms, oms.kafka_cfg)
    broker_event_consumer.start()
    market_data_consumer = StrategyMarketDataConsumer(strat_manager, oms.kafka_cfg)
    market_data_consumer.start()
    manual_user_trade_config = {"account_id": "U456MANUAL", "sec_type": "STK", "exchange": "SMART", "currency": "USD"}
    manual_market_order = Order(user_id="manual_user", symbol="GOOG", quantity=3, order_type=OrderType.MARKET)
    await oms.submit_order(manual_market_order, user_trade_config=manual_user_trade_config, strategy_id="manual_trader")
    logger.info(f"Status for manual order {manual_market_order.order_id}: {await oms.get_order_status(manual_market_order.order_id)}")
    sim_status_event_payload_manual = {"platform_order_id": manual_market_order.order_id, "broker_order_id": "IB001", "perm_id": 12345, "status": "Submitted", "filled_quantity": 0.0, "remaining_quantity": 3.0, "average_fill_price": 0.0, "ib_account_id": "U456MANUAL"}
    if hasattr(broker_event_consumer.consumer, 'add_message'): broker_event_consumer.consumer.add_message(oms.kafka_cfg.order_status_updates_topic, sim_status_event_payload_manual)
    sim_market_data_quote = { "ticker": "TESTSYM", "bid_price": 98.0, "ask_price": 99.5, "bid_size": 100, "ask_size": 120, "timestamp_ns": int(time.time() * 1e9) }
    if hasattr(market_data_consumer.consumer, 'add_message'):
         md_ticks_topic = getattr(oms.kafka_cfg, 'market_data_ticks_topic', "ibkr.market-data.ticks")
         market_data_consumer.consumer.add_message(md_ticks_topic, sim_market_data_quote)
    logger.info("Waiting for consumers to process simulated messages...")
    await asyncio.sleep(3)
    logger.info(f"Final status for manual order {manual_market_order.order_id}: {await oms.get_order_status(manual_market_order.order_id)}")
    all_orders = await oms.get_all_orders()
    strategy_orders = [o for o in all_orders if o.user_id == "dummy_strat_1_user"]
    if strategy_orders:
        strat_order_id = strategy_orders[0].order_id
        logger.info(f"Strategy dummy_strat_1 submitted order: {strategy_orders[0]}")
        sim_strat_exec_report = {"platform_order_id": strat_order_id, "broker_order_id": "IB002", "perm_id": 12346, "execution_id": "exec002", "instrument": {"symbol": "TESTSYM", "sec_type": "STK"}, "side": "BUY", "filled_quantity": 10.0, "fill_price": 99.5, "cumulative_quantity": 10.0, "average_price": 99.5, "ib_account_id": "STRAT_ACC_001"}
        if hasattr(broker_event_consumer.consumer, 'add_message'): broker_event_consumer.consumer.add_message(oms.kafka_cfg.execution_reports_topic, sim_strat_exec_report)
        await asyncio.sleep(2)
        logger.info(f"Final status for strategy order {strat_order_id}: {await oms.get_order_status(strat_order_id)}")
    print("\nAll Orders in OMS:")
    all_orders_final = await oms.get_all_orders()
    for o in all_orders_final: print(f"  - {o} - Status: {o.status.value} - BrokerID: {o.broker_order_id} - PermID: {o.perm_id} - Filled: {o.filled_quantity} @ {o.average_fill_price} - Updated: {o.updated_at}")
    market_data_consumer.stop()
    broker_event_consumer.stop()
    strat_manager.stop_all_strategies()
    oms.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    asyncio.run(main_async())
