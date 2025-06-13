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
        self.consecutive_processing_errors = 0
        self.PROCESSING_ERROR_THRESHOLD = 5 # Max consecutive errors in main loop before CRITICAL_ALERT

        # self._commission_reports_by_exec_id and self._commission_report_lock are removed
        # as commission reports are now cached in IBWrapperImpl.

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
        while self.wrapper.exec_details_queue: # This queue now only contains execution details
            try:
                exec_data_item = self.wrapper.exec_details_queue.pop(0)
            except IndexError:
                break
            processed_count += 1

            try:
                # Ensure item is an execution detail, not a mis-queued commission report
                if "execution" not in exec_data_item or "contract" not in exec_data_item:
                    logger.warning(f"Skipping unexpected item in exec_details_queue: {exec_data_item}")
                    continue

                ib_contract = exec_data_item["contract"]    # ibapi.contract.Contract
                ib_execution = exec_data_item["execution"]  # ibapi.execution.Execution
                received_at = exec_data_item.get("received_at", time.time())


                platform_order_id = self.order_id_mapper.get_internal_id(ib_execution.orderId)
                if not platform_order_id:
                    logger.debug(f"No platform_order_id mapping for broker_order_id {ib_execution.orderId} in exec {ib_execution.execId}. Publishing with broker_order_id only.")
                    platform_order_id = f"UNMAPPED_IB_{ib_execution.orderId}"

                # Attempt to link commission report from IBWrapperImpl's cache
                commission_data_proto = broker_pb.CommissionReportData() # Default empty
                with self.wrapper.commission_reports_cache_lock: # Use wrapper's lock
                    if ib_execution.execId in self.wrapper.commission_reports_cache:
                        cached_commission_report = self.wrapper.commission_reports_cache.pop(ib_execution.execId)
                        # Normalize ibapi.CommissionReport to broker_pb.CommissionReportData
                        commission_data_proto = broker_pb.CommissionReportData(
                            execution_id=cached_commission_report.execId, # Corrected field name
                            commission=cached_commission_report.commission,
                            currency=cached_commission_report.currency,
                            realized_pnl=cached_commission_report.realizedPNL,
                            yield_val=getattr(cached_commission_report, 'yield', 0.0), # 'yield' might not always exist
                            yield_redemption_date=getattr(cached_commission_report, 'yieldRedemptionDate', 0) # int YYYYMMDD
                        )
                        logger.info(f"Found and linked commission report for execId {ib_execution.execId}")
                    else:
                        logger.debug(f"No commission report found in cache for execId {ib_execution.execId}")

                # Placeholder for execution_timestamp_ns until parsing logic is added/confirmed
                # execution_time_ib = ib_execution.time # Format "YYYYMMDD  HH:MM:SS" (potentially local TWS time)
                # execution_timestamp_ns_val = 0 # Default to 0 or handle missing
                # if execution_time_ib:
                #     try:
                #         # This is a placeholder - robust parsing/conversion needed
                #         dt_obj = datetime.datetime.strptime(execution_time_ib, "%Y%m%d  %H:%M:%S")
                #         # TODO: Confirm timezone of execution.time from IBKR. Assume UTC for now if not specified.
                #         # If it's local, it needs to be converted to UTC.
                #         execution_timestamp_ns_val = int(dt_obj.replace(tzinfo=datetime.timezone.utc).timestamp() * 1e9)
                #     except ValueError as ve:
                #         logger.error(f"Could not parse execution time '{execution_time_ib}': {ve}")


                event = broker_pb.ExecutionReportEvent(
                    platform_order_id=platform_order_id,
                    broker_order_id=ib_execution.orderId,
                    execution_id=ib_execution.execId,
                    perm_id=ib_execution.permId,
                    instrument=normalize_ib_contract_to_broker_instrument(ib_contract),
                    side=ib_execution.side,
                    filled_quantity=float(ib_execution.shares), # Ensure float
                    fill_price=ib_execution.price,
                    # execution_timestamp_ns=execution_timestamp_ns_val, # Requires parsing execution.time
                    executing_exchange=ib_execution.exchange, # This is from Execution object
                    currency=ib_contract.currency, # From Contract object
                    commission_data=commission_data_proto, # Use the populated or empty proto
                    event_timestamp_utc=_get_proto_timestamp(received_at),
                    ib_account_id=ib_execution.acctNumber, # From Execution object
                    average_price=ib_execution.avgPrice, # From Execution object
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

    def _process_streaming_account_values_queue(self):
        """Processes AccountValueUpdate and streaming AccountSummary items from IBWrapperImpl."""
        processed_count = 0
        # Ensure this queue exists on the wrapper instance
        queue_to_process = getattr(self.wrapper, 'streaming_account_value_queue', None)
        if not queue_to_process:
            # logger.debug("streaming_account_value_queue not found on wrapper. Skipping.") # Can be noisy
            return

        while queue_to_process: # Process all available at this moment
            try:
                item = queue_to_process.pop(0)
            except IndexError:
                break # Queue is empty
            processed_count +=1

            try:
                item_type = item.get("type")
                timestamp = item.get("timestamp", time.time()) # Fallback to now if timestamp missing

                if item_type == "AccountValueUpdate":
                    # This is from IBWrapperImpl.updateAccountValue
                    event = broker_pb.AccountValueUpdateEvent(
                        account_id=item["accountName"],
                        key=item["key"],
                        value=item["val"],
                        currency=item["currency"],
                        event_timestamp_utc=_get_proto_timestamp(timestamp)
                    )
                    kafka_key = f"{item['accountName']}:{item['key']}"
                    self.kafka_producer.publish_message(event, kafka_key, self.kafka_cfg.account_data_topic)

                elif item_type == "AccountSummaryStream":
                    # This is from IBWrapperImpl.accountSummary for non-awaited reqIds
                    # Treated similarly to AccountValueUpdateEvent, mapping 'tag' to 'key'.
                    event = broker_pb.AccountValueUpdateEvent(
                        account_id=item["account"],
                        key=item["tag"], # Map 'tag' from accountSummary to 'key'
                        value=item["value"],
                        currency=item["currency"],
                        event_timestamp_utc=_get_proto_timestamp(timestamp)
                    )
                    kafka_key = f"{item['account']}:{item['tag']}"
                    self.kafka_producer.publish_message(event, kafka_key, self.kafka_cfg.account_data_topic)
                else:
                    logger.warning(f"Unknown item type in streaming_account_value_queue: {item_type}. Item: {item}")

            except Exception as e:
                logger.error(f"Error processing streaming account value message {item}: {e}", exc_info=True)
        # if processed_count > 0: logger.debug(f"Processed {processed_count} streaming account value events.")

    def _run_processor_loop(self):
        logger.info("ResponseProcessor loop started.")
        while not self._stop_event.is_set():
            processed_something_in_pass = False
            try:
                # Process all queues
                if self.wrapper.order_status_queue:
                    self._process_order_status_queue()
                    processed_something_in_pass = True
                if self.wrapper.exec_details_queue:
                    self._process_exec_details_queue()
                    processed_something_in_pass = True
                if self.wrapper.portfolio_updates_queue:
                    self._process_portfolio_updates_queue()
                    processed_something_in_pass = True
                if self.wrapper.error_messages_queue:
                    self._process_error_messages_queue()
                    processed_something_in_pass = True

                queue_to_process = getattr(self.wrapper, 'streaming_account_value_queue', None)
                if queue_to_process and queue_to_process: # Check if queue exists and is not empty
                    self._process_streaming_account_values_queue()
                    processed_something_in_pass = True

                # If any processing happened or all queues were empty (implying a successful idle pass)
                # reset consecutive error count.
                self.consecutive_processing_errors = 0 # Reset on successful pass through all queues

                if not processed_something_in_pass: # All known queues were empty
                    self._stop_event.wait(timeout=0.01) # Sleep briefly, also checks stop_event

            except Exception as e:
                self.consecutive_processing_errors += 1
                logger.error(f"Exception in ResponseProcessor loop (attempt #{self.consecutive_processing_errors}): {e}", exc_info=True)
                if self.consecutive_processing_errors > self.PROCESSING_ERROR_THRESHOLD:
                    logger.critical(
                        f"CRITICAL_ALERT: ResponseProcessor: Too many consecutive errors in processing loop ({self.consecutive_processing_errors}). "
                        f"Last error: {e}. RESPONSE_PROCESSOR_FAILURE", exc_info=True
                    )
                    # Do not reset counter here, so it keeps alerting if problem persists in next iterations,
                    # or reset after a cool-down period if alert fatigue is a concern.
                    # For this implementation, it will alert every time after threshold is crossed if error continues.

                # Avoid rapid looping on persistent error by sleeping
                # The sleep duration could be made configurable or increase exponentially.
                self._stop_event.wait(timeout=1.0) # Sleep for 1s, also checks stop_event

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
