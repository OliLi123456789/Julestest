import logging
import time
import threading # For stop_event and thread
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from google.protobuf.timestamp_pb2 import Timestamp as ProtoTimestamp #type: ignore

# Assuming generated protos are accessible via PYTHONPATH setup in Docker or local dev
# This path assumes 'common' is a top-level package discoverable.
from common.gen.python.broker_events import broker_events_pb2 as broker_pb

from .ib_wrapper import IBWrapperImpl # For accessing its internal queues/maps
from .kafka_producer import BrokerEventProducer # To be created in this sub-step
from .config import KafkaConfig # For topic names
from .order_id_mapper import OrderIdMapper

if TYPE_CHECKING: # To avoid circular import issues at runtime but allow type hinting
    from .ib_wrapper import IBWrapperImpl


logger = logging.getLogger(__name__)

# Helper to convert Python datetime/timestamp to google.protobuf.Timestamp
def _get_proto_timestamp(ts: Optional[float] = None) -> ProtoTimestamp:
    if ts is None:
        ts = time.time()
    seconds = int(ts)
    nanos = int((ts - seconds) * 1e9)
    return ProtoTimestamp(seconds=seconds, nanos=nanos)

# Helper to convert IBKR Contract to BrokerInstrument Protobuf
def normalize_ib_contract_to_broker_instrument(ib_contract: Any) -> broker_pb.BrokerInstrument:
    # ib_contract is ibapi.contract.Contract
    # Ensure all attributes are accessed safely with defaults if they might be missing
    # from certain contract types or API versions.
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
                 service_instance_id: str):
        self.wrapper = wrapper
        self.kafka_producer = kafka_producer
        self.kafka_cfg = kafka_cfg
        self.order_id_mapper = order_id_mapper
        self.service_instance_id = service_instance_id # For tagging events or error source

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # To store linked commission reports temporarily
        self._commission_reports_by_exec_id: Dict[str, broker_pb.CommissionReportData] = {}
        self._commission_report_lock = threading.Lock()


    def _process_order_status_queue(self):
        processed_count = 0
        while self.wrapper.order_status_queue: # Process all available
            try:
                status_data = self.wrapper.order_status_queue.pop(0) # FIFO
            except IndexError: # Should not happen with while loop check but good for safety
                break
            processed_count += 1

            try:
                broker_order_id = status_data.get("orderId", 0) # From IBWrapperImpl log_entry
                platform_order_id = self.order_id_mapper.get_internal_id(broker_order_id)

                if not platform_order_id:
                    # This can happen for orders not placed by this session/system but reported by IB
                    logger.debug(f"No platform_order_id mapping for broker_order_id {broker_order_id} in OrderStatus. Publishing with broker_order_id only.")
                    platform_order_id = f"UNMAPPED_IB_{broker_order_id}" # Use a placeholder or special value

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
                    event_timestamp_utc=_get_proto_timestamp(status_data.get("timestamp")), # Use wrapper's log time
                    ib_account_id=self.wrapper.conn_manager.config.account_code if self.wrapper.conn_manager else "" # Get account from conn_manager config
                )
                self.kafka_producer.publish_message(event, str(event.broker_order_id), self.kafka_cfg.order_updates_topic)
            except Exception as e:
                logger.error(f"Error processing order status from queue: {status_data} - {e}", exc_info=True)
        # if processed_count > 0: logger.debug(f"Processed {processed_count} order status events.")


    def _process_exec_details_queue(self):
        processed_count = 0
        while self.wrapper.exec_details_queue:
            try:
                exec_data_item = self.wrapper.exec_details_queue.pop(0)
            except IndexError:
                break
            processed_count += 1

            try:
                ib_contract = exec_data_item["contract"]    # ibapi.contract.Contract
                ib_execution = exec_data_item["execution"]  # ibapi.execution.Execution

                platform_order_id = self.order_id_mapper.get_internal_id(ib_execution.orderId)
                if not platform_order_id:
                    logger.debug(f"No platform_order_id mapping for broker_order_id {ib_execution.orderId} in exec {ib_execution.execId}. Publishing with broker_order_id only.")
                    platform_order_id = f"UNMAPPED_IB_{ib_execution.orderId}"

                # Check for and link commission report
                commission_data = broker_pb.CommissionReportData() # Default empty
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
                    filled_quantity=float(ib_execution.shares), # Ensure float
                    fill_price=ib_execution.price,
                    execution_time_str=ib_execution.time,
                    executing_exchange=ib_execution.exchange,
                    currency=ib_contract.currency,
                    commission_data=commission_data,
                    event_timestamp_utc=_get_proto_timestamp(exec_data_item.get("received_at")),
                    ib_account_id=ib_execution.acctNumber,
                    average_price=ib_execution.avgPrice,
                    cumulative_quantity=float(ib_execution.cumQty) # Ensure float
                )
                self.kafka_producer.publish_message(event, event.execution_id, self.kafka_cfg.execution_reports_topic)
            except Exception as e:
                logger.error(f"Error processing execution detail from queue: {exec_data_item} - {e}", exc_info=True)
        # if processed_count > 0: logger.debug(f"Processed {processed_count} execution details.")


    def _process_commission_reports_from_wrapper(self):
        # The wrapper's commissionReport callback should now populate a queue or map.
        # Let's assume wrapper has `self.commission_report_queue` similar to others.
        # Or, if wrapper directly populates `self._commission_reports_by_exec_id` under lock.
        # For now, this method is a placeholder if direct processing from wrapper queue is needed.
        # The current design tries to link them in `_process_exec_details_queue`.
        # If commission reports can arrive *before* execDetails, they need to be cached.
        # The IBWrapperImpl currently just logs commission reports. It should queue them or pass to a map here.
        # For now, assuming IBWrapperImpl's `commissionReport` callback will populate `self._commission_reports_by_exec_id`
        # (This means IBWrapperImpl needs a reference to ResponseProcessor's map or its own map to be polled)
        # For simplicity, let's assume IBWrapperImpl is modified to directly populate ResponseProcessor's map.
        # This is not ideal; better for wrapper to have its own queue.
        # Let's assume wrapper.commission_report_queue exists:

        # This is a conceptual refinement: IBWrapperImpl should have its own commission_report_queue
        # if hasattr(self.wrapper, 'commission_report_queue'):
        #     while self.wrapper.commission_report_queue:
        #         try:
        #             report_data = self.wrapper.commission_report_queue.pop(0) # report_data is ibapi.CommissionReport
        #             with self._commission_report_lock:
        #                 self._commission_reports_by_exec_id[report_data.execId] = broker_pb.CommissionReportData(
        #                     exec_id=report_data.execId,
        #                     commission=report_data.commission,
        #                     currency=report_data.currency,
        #                     realized_pnl=report_data.realizedPNL,
        #                     yield_val=report_data.yield_val, # Corrected attribute name from .yield
        #                     yield_redemption_date=report_data.yieldRedemptionDate
        #                 )
        #             logger.debug(f"Cached commission report for execId {report_data.execId}")
        #         except IndexError: break
        #         except Exception as e: logger.error(f"Error processing commission report from wrapper queue: {e}", exc_info=True)
        pass


    def _process_portfolio_updates_queue(self):
        processed_count = 0
        while self.wrapper.portfolio_updates_queue:
            try:
                portfolio_data = self.wrapper.portfolio_updates_queue.pop(0)
            except IndexError:
                break
            processed_count += 1
            try:
                ib_contract = portfolio_data.get("contract_object") # Assuming wrapper stores the full Contract object
                if not ib_contract: # Fallback if only symbol related fields were queued
                    # Reconstruct a minimal Contract if needed, though wrapper should provide full object
                    ib_contract = type('Contract', (object,), {
                        'symbol': portfolio_data.get("contract_symbol"),
                        'secType': portfolio_data.get("contract_secType"),
                        'exchange': portfolio_data.get("contract_exchange"),
                        'currency': portfolio_data.get("contract_currency"),
                        'conId': 0 # ConId might not be in basic portfolio update, needs enrichment if essential
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
                # Key for portfolio updates: account_id + conId (or symbol if conId not available)
                key = f"{event.ib_account_id}:{event.instrument.symbol}"
                if event.instrument.con_id:
                    key = f"{event.ib_account_id}:{event.instrument.con_id}"
                self.kafka_producer.publish_message(event, key, self.kafka_cfg.position_data_topic)
            except Exception as e:
                logger.error(f"Error processing portfolio update from queue: {portfolio_data} - {e}", exc_info=True)
        # if processed_count > 0: logger.debug(f"Processed {processed_count} portfolio updates.")


    def _process_account_summary_events(self):
        # This method processes data collected by IBWrapperImpl from accountSummary and updateAccountValue
        # For accountSummary (snapshot):
        # IBWrapperImpl's accountSummaryEnd signals completion for a reqId.
        # The results are in wrapper._account_summary_results[reqId].
        # This needs to be triggered by some logic, perhaps main periodically checks for completed reqIds.
        # For now, this is a conceptual placeholder for snapshot processing.

        # For updateAccountValue (streaming):
        # The wrapper stores these in `account_summary_map`. We can iterate this map
        # or have the wrapper put them onto a dedicated queue if they need to be individual events.
        # Let's assume wrapper.account_summary_map is polled or items are moved to a queue.
        # For simplicity, let's assume items from updateAccountValue are also put on a specific queue by wrapper.
        # If wrapper.account_update_value_queue:
        #    data = wrapper.account_update_value_queue.pop(0)
        #    event = broker_pb.AccountValueUpdateEvent(...)
        #    self.kafka_producer.publish_message(event, ...)
        pass


    def _process_error_messages_queue(self):
        processed_count = 0
        while self.wrapper.error_messages_queue:
            try:
                error_data = self.wrapper.error_messages_queue.pop(0)
            except IndexError:
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
                self.kafka_producer.publish_message(event, str(event.error_code), self.kafka_cfg.error_events_topic)
            except Exception as e:
                logger.error(f"Error processing broker error message from queue: {error_data} - {e}", exc_info=True)
        # if processed_count > 0: logger.debug(f"Processed {processed_count} error messages.")

    def _run_processor_loop(self):
        logger.info("ResponseProcessor loop started.")
        while not self._stop_event.is_set():
            try:
                self._process_order_status_queue()
                self._process_exec_details_queue()
                self._process_portfolio_updates_queue()
                # self._process_account_summary_events() # Refine this based on how wrapper provides summary data
                self._process_error_messages_queue()

                # Check if any work was done
                # This is a simple way to avoid tight loop if all queues are consistently empty.
                # More sophisticated would be to use blocking queues or condition variables.
                # For now, a short sleep if all known queues were empty in this pass.
                # (This logic needs refinement as .pop(0) will raise IndexError if empty)
                # A better check might be:
                all_queues_empty = not (self.wrapper.order_status_queue or \
                                       self.wrapper.exec_details_queue or \
                                       self.wrapper.portfolio_updates_queue or \
                                       self.wrapper.error_messages_queue) # and other relevant queues

                if all_queues_empty:
                    time.sleep(0.01) # Sleep briefly (e.g., 10ms)
            except Exception as e:
                logger.error(f"Exception in ResponseProcessor loop: {e}", exc_info=True)
                time.sleep(1) # Avoid rapid looping on persistent error
        logger.info("ResponseProcessor loop stopped.")

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("ResponseProcessor already running.")
            return
        self._stop_event.clear()
        # The wrapper's queues should be thread-safe if using standard Python list.pop(0) and append,
        # but access from two threads (wrapper appends, processor pops) needs care.
        # Python's list.pop(0) and list.append are thread-safe individually (atomic due to GIL),
        # but combined operations or checks like `if queue: item = queue.pop(0)` are not.
        # Using `queue.Queue` from Python's `queue` module is thread-safe for multi-producer/multi-consumer.
        # For this PoC, assuming current list approach with frequent checks.
        self._thread = threading.Thread(target=self._run_processor_loop, name="IBResponseProcLoop", daemon=True)
        self._thread.start()
        logger.info("ResponseProcessor started.")

    def stop(self):
        logger.info("ResponseProcessor stopping...")
        self._stop_event.set()

        # Wait for the processing loop to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10) # Wait up to 10s for existing items to be processed
            if self._thread.is_alive():
                logger.warning("ResponseProcessor loop did not stop gracefully within timeout.")

        # Final flush of Kafka producer
        if self.kafka_producer:
             logger.info("Flushing BrokerEventProducer...")
             self.kafka_producer.flush()

        logger.info("ResponseProcessor stopped.")
