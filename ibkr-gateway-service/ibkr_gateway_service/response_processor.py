import logging
import queue
import time
import threading
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from google.protobuf.timestamp_pb2 import Timestamp as ProtoTimestamp

from common.gen.python.broker_events import broker_events_pb2 as broker_pb
from common.gen.python.market_data import market_data_pb2

from ibapi.common import TickTypeEnum

from .ib_wrapper import IBWrapperImpl
from .kafka_producer import BrokerEventProducer
from .config import KafkaConfig
from .order_id_mapper import OrderIdMapper

if TYPE_CHECKING:
    from .ib_wrapper import IBWrapperImpl
    from .ib_client_wrapper import IBClientWrapper

logger = logging.getLogger(__name__)

def _get_proto_timestamp(ts: Optional[float] = None) -> ProtoTimestamp:
    if ts is None:
        ts = time.time()
    seconds = int(ts)
    nanos = int((ts - seconds) * 1e9)
    return ProtoTimestamp(seconds=seconds, nanos=nanos)

def normalize_ib_contract_to_broker_instrument(ib_contract: Any) -> broker_pb.BrokerInstrument:
    return broker_pb.BrokerInstrument(
        symbol=getattr(ib_contract, 'symbol', ""),
        sec_type=getattr(ib_contract, 'secType', ""),
        exchange=getattr(ib_contract, 'exchange', ""),
        currency=getattr(ib_contract, 'currency', ""),
        con_id=getattr(ib_contract, 'conId', 0),
        last_trade_date_or_contract_month=getattr(ib_contract, 'lastTradeDateOrContractMonth', ""),
        strike=getattr(ib_contract, 'strike', 0.0),
        right=getattr(ib_contract, 'right', ""),
        multiplier=getattr(ib_contract, 'multiplier', ""),
        primary_exchange=getattr(ib_contract, 'primaryExchange', "")
    )

class ResponseProcessor:
    def __init__(self,
                 wrapper: 'IBWrapperImpl',
                 kafka_producer: 'BrokerEventProducer',
                 kafka_cfg: KafkaConfig,
                 order_id_mapper: OrderIdMapper,
                 service_instance_id: str,
                 ib_client_wrapper: 'IBClientWrapper'):
        self.wrapper = wrapper
        self.kafka_producer = kafka_producer
        self.kafka_cfg = kafka_cfg
        self.order_id_mapper = order_id_mapper
        self.service_instance_id = service_instance_id
        self.ib_client_wrapper = ib_client_wrapper
        self.market_data_states: Dict[int, Dict[str, Any]] = {}

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._commission_reports_by_exec_id: Dict[str, broker_pb.CommissionReportData] = {}
        self._commission_report_lock = threading.Lock()


    def _process_order_status_queue(self):
        processed_count = 0
        while True:
            try:
                status_data = self.wrapper.order_status_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                broker_order_id = status_data.get("orderId", 0)
                platform_order_id = self.order_id_mapper.get_internal_id(broker_order_id)
                if not platform_order_id:
                    logger.debug(f"No platform_order_id mapping for broker_order_id {broker_order_id} in OrderStatus. Publishing with broker_order_id only.")
                    platform_order_id = f"UNMAPPED_IB_{broker_order_id}"

                event = broker_pb.OrderStatusEvent(
                    platform_order_id=platform_order_id,
                    broker_order_id=broker_order_id,
                    perm_id=status_data.get("permId", 0),
                    status=status_data.get("status", ""),
                    filled_quantity=status_data.get("filled", 0.0),
                    remaining_quantity=status_data.get("remaining", 0.0),
                    average_fill_price=status_data.get("avgFillPrice", 0.0),
                    last_fill_price=status_data.get("lastFillPrice", 0.0),
                    client_id=status_data.get("clientId", 0),
                    why_held=status_data.get("whyHeld", ""),
                    mkt_cap_price=status_data.get("mktCapPrice", 0.0),
                    parent_broker_order_id=str(status_data.get("parentId", 0)) if status_data.get("parentId") and status_data.get("parentId") != 0 else "",
                    event_timestamp_utc=_get_proto_timestamp(status_data.get("timestamp")),
                    ib_account_id=self.wrapper.conn_manager.config.account_code if self.wrapper.conn_manager else ""
                )
                logger.info(f"Publishing OrderStatusEvent: BrokerOrderID={event.broker_order_id}, PlatformOrderID='{event.platform_order_id}', Status='{event.status}' to topic '{self.kafka_cfg.order_updates_topic}'")
                self.kafka_producer.publish_message(event, str(event.broker_order_id), self.kafka_cfg.order_updates_topic)
            except Exception as e:
                logger.error(f"Error processing order status from queue: {status_data} - {e}", exc_info=True)

    def _process_exec_details_queue(self):
        processed_count = 0
        while True:
            try:
                exec_data_item = self.wrapper.exec_details_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                ib_contract = exec_data_item["contract_obj"]
                ib_execution = exec_data_item["execution_obj"]
                platform_order_id = self.order_id_mapper.get_internal_id(ib_execution.orderId)
                if not platform_order_id:
                    logger.debug(f"No platform_order_id mapping for broker_order_id {ib_execution.orderId} in exec {ib_execution.execId}. Publishing with broker_order_id only.")
                    platform_order_id = f"UNMAPPED_IB_{ib_execution.orderId}"
                commission_data = broker_pb.CommissionReportData()
                with self._commission_report_lock:
                    if ib_execution.execId in self._commission_reports_by_exec_id:
                        commission_data = self._commission_reports_by_exec_id.pop(ib_execution.execId)
                        logger.debug(f"Found and linked commission report for execId {ib_execution.execId}")
                event = broker_pb.ExecutionReportEvent(
                    platform_order_id=platform_order_id,
                    broker_order_id=ib_execution.orderId,
                    execution_id=ib_execution.execId,
                    perm_id=ib_execution.permId,
                    instrument=normalize_ib_contract_to_broker_instrument(ib_contract),
                    side=ib_execution.side,
                    filled_quantity=float(ib_execution.shares),
                    fill_price=ib_execution.price,
                    execution_time_str=ib_execution.time,
                    executing_exchange=ib_execution.exchange,
                    currency=ib_contract.currency,
                    commission_data=commission_data,
                    event_timestamp_utc=_get_proto_timestamp(exec_data_item.get("received_at")),
                    ib_account_id=ib_execution.acctNumber,
                    average_price=ib_execution.avgPrice,
                    cumulative_quantity=float(ib_execution.cumQty)
                )
                logger.info(f"Publishing ExecutionReportEvent: BrokerOrderID={event.broker_order_id}, ExecID='{event.execution_id}', Symbol='{event.instrument.symbol}' to topic '{self.kafka_cfg.execution_reports_topic}'")
                self.kafka_producer.publish_message(event, event.execution_id, self.kafka_cfg.execution_reports_topic)
            except Exception as e:
                logger.error(f"Error processing execution detail from queue: {exec_data_item} - {e}", exc_info=True)

    def _process_commission_reports_from_wrapper(self):
        pass

    def _process_commission_report_data_queue(self):
        processed_count = 0
        while True:
            try:
                report_data = self.wrapper.commission_report_data_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                commission_pb = broker_pb.CommissionReportData(
                    execution_id=report_data.execId,
                    commission=report_data.commission,
                    currency=report_data.currency,
                    realized_pnl=getattr(report_data, 'realizedPNL', 0.0),
                    yield_val=getattr(report_data, 'yield', 0.0),
                    yield_redemption_date=getattr(report_data, 'yieldRedemptionDate', 0)
                )
                with self._commission_report_lock:
                    self._commission_reports_by_exec_id[report_data.execId] = commission_pb
                logger.info(f"Cached CommissionReportData: ExecID='{commission_pb.execution_id}'")
            except Exception as e:
                logger.error(f"Error processing commission report from wrapper queue: {report_data} - {e}", exc_info=True)

    def _process_portfolio_updates_queue(self):
        processed_count = 0
        while True:
            try:
                portfolio_data = self.wrapper.portfolio_updates_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                ib_contract = portfolio_data.get("contract_obj")
                if not ib_contract:
                    ib_contract = type('Contract', (object,), {
                        'symbol': portfolio_data.get("contract_symbol"),
                        'secType': portfolio_data.get("contract_secType"),
                        'exchange': portfolio_data.get("contract_exchange"),
                        'currency': portfolio_data.get("contract_currency"),
                        'conId': 0
                    })
                event = broker_pb.PortfolioUpdateEvent(
                    ib_account_id=portfolio_data.get("accountName", ""),
                    instrument=normalize_ib_contract_to_broker_instrument(ib_contract),
                    position=portfolio_data.get("position", 0.0),
                    market_price=portfolio_data.get("marketPrice", 0.0),
                    market_value=portfolio_data.get("marketValue", 0.0),
                    average_cost=portfolio_data.get("averageCost", 0.0),
                    unrealized_pnl=portfolio_data.get("unrealizedPNL", 0.0),
                    realized_pnl=portfolio_data.get("realizedPNL", 0.0),
                    event_timestamp_utc=_get_proto_timestamp(portfolio_data.get("timestamp"))
                )
                key = f"{event.ib_account_id}:{event.instrument.symbol}"
                if event.instrument.con_id:
                    key = f"{event.ib_account_id}:{event.instrument.con_id}"
                logger.info(f"Publishing PortfolioUpdateEvent: Account='{event.ib_account_id}', Symbol='{event.instrument.symbol}', Position={event.position} to topic '{self.kafka_cfg.position_data_topic}'")
                self.kafka_producer.publish_message(event, key, self.kafka_cfg.position_data_topic)
            except Exception as e:
                logger.error(f"Error processing portfolio update from queue: {portfolio_data} - {e}", exc_info=True)

    def _process_account_summary_events(self):
        pass

    def _process_account_value_update_queue(self):
        processed_count = 0
        while True:
            try:
                data = self.wrapper.account_value_update_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                event = broker_pb.AccountValueUpdateEvent(
                    account_id=data.get("accountName", ""),
                    key=data.get("key", ""),
                    value=data.get("val", ""),
                    currency=data.get("currency", ""),
                    event_timestamp_utc=_get_proto_timestamp(data.get("timestamp"))
                )
                kafka_key = f"{event.account_id}:{event.key}"
                logger.info(f"Publishing AccountValueUpdateEvent: Account='{event.account_id}', Key='{event.key}', Value='{event.value}' to topic '{self.kafka_cfg.account_value_updates_topic}'")
                self.kafka_producer.publish_message(event, kafka_key, self.kafka_cfg.account_value_updates_topic)
            except Exception as e:
                logger.error(f"Error processing account value update from queue: {data} - {e}", exc_info=True)

    def _process_tick_data_queue(self):
        processed_count = 0
        min_publish_interval_seconds = 0.2
        while True:
            try:
                tick = self.wrapper.tick_data_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                req_id = tick.get("reqId")
                if req_id is None:
                    logger.warning(f"Tick data missing reqId: {tick}")
                    continue
                if req_id not in self.market_data_states:
                    contract = self.ib_client_wrapper.get_contract_for_reqid(req_id)
                    if not contract:
                        logger.warning(f"No contract mapping found for tick's req_id {req_id}. Skipping tick: {tick}")
                        continue
                    self.market_data_states[req_id] = {
                        "contract": contract, "bid_price": None, "bid_size": None,
                        "ask_price": None, "ask_size": None, "last_price": None, "last_size": None,
                        "high_price": None, "low_price": None, "close_price": None, "volume": None,
                        "last_timestamp_ns": None, "last_update_ts_ns": None,
                        "last_quote_publish_time": 0, "last_trade_publish_time": 0,
                    }
                state = self.market_data_states[req_id]
                contract = state["contract"]
                tick_type_val = tick.get("tickType")
                current_event_ts_ns = int(tick.get("timestamp", time.time()) * 1e9)
                state["last_update_ts_ns"] = current_event_ts_ns
                if tick.get("type") == "price":
                    price = tick.get("price")
                    if tick_type_val == TickTypeEnum.BID: state["bid_price"] = price
                    elif tick_type_val == TickTypeEnum.ASK: state["ask_price"] = price
                    elif tick_type_val == TickTypeEnum.LAST: state["last_price"] = price
                    elif tick_type_val == TickTypeEnum.HIGH: state["high_price"] = price
                    elif tick_type_val == TickTypeEnum.LOW: state["low_price"] = price
                    elif tick_type_val == TickTypeEnum.CLOSE: state["close_price"] = price
                elif tick.get("type") == "size":
                    size = int(tick.get("size",0))
                    if tick_type_val == TickTypeEnum.BID_SIZE: state["bid_size"] = size
                    elif tick_type_val == TickTypeEnum.ASK_SIZE: state["ask_size"] = size
                    elif tick_type_val == TickTypeEnum.LAST_SIZE: state["last_size"] = size
                    elif tick_type_val == TickTypeEnum.VOLUME: state["volume"] = size
                elif tick.get("type") == "string":
                    if tick_type_val == TickTypeEnum.LAST_TIMESTAMP:
                        try: state["last_timestamp_ns"] = int(tick.get("value")) * 1_000_000_000
                        except ValueError: logger.warning(f"Could not parse LAST_TIMESTAMP string value '{tick.get('value')}' to int for reqId {req_id}")

                can_publish_quote = (time.time() - state.get("last_quote_publish_time",0)) > min_publish_interval_seconds
                if (state.get("bid_price") is not None and state.get("bid_size") is not None and
                    state.get("ask_price") is not None and state.get("ask_size") is not None and can_publish_quote):
                    quote_event = market_data_pb2.Quote(
                        ticker=contract.symbol, bid_price=state["bid_price"], bid_size=state["bid_size"],
                        ask_price=state["ask_price"], ask_size=state["ask_size"], timestamp_ns=state["last_update_ts_ns"],
                        exchange=contract.exchange, currency=contract.currency,
                        day_high=state.get("high_price") if state.get("high_price") is not None else -1.0,
                        day_low=state.get("low_price") if state.get("low_price") is not None else -1.0,
                        prev_day_close=state.get("close_price") if state.get("close_price") is not None else -1.0,
                        day_volume=state.get("volume") if state.get("volume") is not None else -1)
                    kafka_key = f"{contract.symbol}_{contract.exchange}_quote"
                    if contract.conId: kafka_key = f"{contract.conId}_quote"
                    logger.info(f"Publishing Quote: ReqID={req_id}, Symbol='{state['contract'].symbol}', Bid={state.get('bid_price')}, Ask={state.get('ask_price')}, Topic='{self.kafka_cfg.market_data_ticks_topic}'")
                    self.kafka_producer.publish_message(quote_event, kafka_key, self.kafka_cfg.market_data_ticks_topic)
                    state["last_quote_publish_time"] = time.time()

                can_publish_trade = (time.time() - state.get("last_trade_publish_time", 0)) > min_publish_interval_seconds
                trade_ts_ns = state.get("last_timestamp_ns", current_event_ts_ns)
                price_to_log, size_to_log = None, None
                if tick_type_val == TickTypeEnum.LAST and state.get("last_size") is not None and can_publish_trade:
                    price_to_log = tick.get("price"); size_to_log = state["last_size"]
                    trade_event = market_data_pb2.Trade(
                        ticker=contract.symbol, price=price_to_log, size=size_to_log,
                        timestamp_ns=trade_ts_ns, exchange=contract.exchange, currency=contract.currency)
                    kafka_key = f"{contract.symbol}_{contract.exchange}_trade";
                    if contract.conId: kafka_key = f"{contract.conId}_trade"
                    logger.info(f"Publishing Trade: ReqID={req_id}, Symbol='{state['contract'].symbol}', Price={price_to_log}, Size={size_to_log}, Topic='{self.kafka_cfg.market_data_ticks_topic}'")
                    self.kafka_producer.publish_message(trade_event, kafka_key, self.kafka_cfg.market_data_ticks_topic)
                    state["last_trade_publish_time"] = time.time()
                elif tick_type_val == TickTypeEnum.LAST_SIZE and state.get("last_price") is not None and can_publish_trade:
                    price_to_log = state["last_price"]; size_to_log = int(tick.get("size",0))
                    trade_event = market_data_pb2.Trade(
                        ticker=contract.symbol, price=price_to_log, size=size_to_log,
                        timestamp_ns=trade_ts_ns, exchange=contract.exchange, currency=contract.currency)
                    kafka_key = f"{contract.symbol}_{contract.exchange}_trade";
                    if contract.conId: kafka_key = f"{contract.conId}_trade"
                    logger.info(f"Publishing Trade: ReqID={req_id}, Symbol='{state['contract'].symbol}', Price={price_to_log}, Size={size_to_log}, Topic='{self.kafka_cfg.market_data_ticks_topic}'")
                    self.kafka_producer.publish_message(trade_event, kafka_key, self.kafka_cfg.market_data_ticks_topic)
                    state["last_trade_publish_time"] = time.time()
            except Exception as e:
                logger.error(f"Error processing tick data from queue: {tick} - {e}", exc_info=True)

    def _process_realtime_bar_queue(self):
        processed_count = 0
        while True:
            try:
                bar_data = self.wrapper.realtime_bar_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                req_id = bar_data.get("reqId")
                contract_details = self.ib_client_wrapper.get_contract_for_reqid(req_id)
                if not contract_details:
                    logger.warning(f"Skipping realtime bar for req_id {req_id} due to missing contract mapping.")
                    continue
                instrument_pb = normalize_ib_contract_to_broker_instrument(contract_details)
                start_time_ns = int(bar_data.get("time_epoch_seconds")) * 1_000_000_000
                bar_size_seconds = 5
                active_bar_sub = self.ib_client_wrapper.active_realtime_bars_reqs.get(req_id)
                if active_bar_sub and isinstance(active_bar_sub, dict):
                    bar_size_seconds = active_bar_sub.get("bar_size", 5)
                bar_duration_ns = bar_size_seconds * 1_000_000_000
                end_time_ns = start_time_ns + bar_duration_ns
                event = market_data_pb2.Aggregate(
                    ticker=instrument_pb.symbol, open=bar_data.get("open"), high=bar_data.get("high"),
                    low=bar_data.get("low"), close=bar_data.get("close"), volume=int(bar_data.get("volume")),
                    vwap=bar_data.get("wap"), start_time_ns=start_time_ns, end_time_ns=end_time_ns,
                    timeframe=f"S{bar_size_seconds}", transactions=bar_data.get("count"))
                kafka_key = f"{instrument_pb.symbol}:{event.timeframe}"
                if instrument_pb.con_id != 0 :
                     kafka_key = f"{instrument_pb.con_id}:{event.timeframe}"
                logger.info(f"Publishing Aggregate (Bar): ReqID={req_id}, Symbol='{instrument_pb.symbol}', StartTime={event.start_time_ns}, Timeframe='{event.timeframe}' to topic '{self.kafka_cfg.market_data_bars_topic}'")
                self.kafka_producer.publish_message(event, kafka_key, self.kafka_cfg.market_data_bars_topic)
            except Exception as e:
                logger.error(f"Error processing realtime bar from queue: {bar_data} - {e}", exc_info=True)

    def _process_error_messages_queue(self):
        processed_count = 0
        while True:
            try:
                error_data = self.wrapper.error_messages_queue.get_nowait()
            except queue.Empty:
                break
            processed_count += 1
            try:
                event = broker_pb.BrokerErrorEvent(
                    request_id=error_data.get("reqId", -1),
                    error_code=error_data.get("errorCode", 0),
                    error_message=error_data.get("errorString", ""),
                    advanced_order_reject_json=error_data.get("advancedOrderRejectJson", ""),
                    event_timestamp_utc=_get_proto_timestamp(error_data.get("timestamp")),
                    source_client_id=str(self.wrapper.conn_manager.config.client_id if self.wrapper.conn_manager else 0)
                )
                logger.info(f"Publishing BrokerErrorEvent: ErrorCode={event.error_code}, ReqID={event.request_id}, Message='{event.error_message[:100]}' to topic '{self.kafka_cfg.error_events_topic}'")
                self.kafka_producer.publish_message(event, str(event.error_code), self.kafka_cfg.error_events_topic)
            except Exception as e:
                logger.error(f"Error processing broker error message from queue: {error_data} - {e}", exc_info=True)

    def _run_processor_loop(self):
        logger.info("ResponseProcessor loop started.")
        while not self._stop_event.is_set():
            try:
                self._process_order_status_queue()
                self._process_exec_details_queue()
                self._process_commission_report_data_queue()
                self._process_portfolio_updates_queue()
                self._process_account_value_update_queue()
                self._process_tick_data_queue()
                self._process_realtime_bar_queue()
                self._process_error_messages_queue()
                all_queues_empty = (self.wrapper.order_status_queue.empty() and
                                    self.wrapper.exec_details_queue.empty() and
                                    self.wrapper.commission_report_data_queue.empty() and
                                    self.wrapper.portfolio_updates_queue.empty() and
                                    self.wrapper.account_value_update_queue.empty() and
                                    self.wrapper.tick_data_queue.empty() and
                                    self.wrapper.realtime_bar_queue.empty() and
                                    self.wrapper.error_messages_queue.empty())
                if all_queues_empty:
                    time.sleep(self.kafka_cfg.processor_idle_sleep_ms / 1000.0)
            except Exception as e:
                logger.error(f"Exception in ResponseProcessor loop: {e}", exc_info=True)
                time.sleep(1)
        logger.info("ResponseProcessor loop stopped.")

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("ResponseProcessor already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_processor_loop, name="IBResponseProcLoop", daemon=True)
        self._thread.start()
        logger.info("ResponseProcessor started.")

    def stop(self):
        logger.info("ResponseProcessor stopping...")
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.kafka_cfg.processor_stop_timeout_seconds)
            if self._thread.is_alive():
                logger.warning("ResponseProcessor loop did not stop gracefully within timeout.")
        if self.kafka_producer:
             logger.info("Flushing BrokerEventProducer...")
             self.kafka_producer.flush()
        logger.info("ResponseProcessor stopped.")
