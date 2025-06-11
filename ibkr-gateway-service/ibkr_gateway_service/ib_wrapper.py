import logging
import queue # New import
import threading
import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.execution import Execution
from ibapi.common import TickerId, OrderId, TickTypeEnum # Added TickTypeEnum
from ibapi.commission_report import CommissionReport

from .utils.exceptions import IBError # New import

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

class IBWrapperImpl(EWrapper):
    def __init__(self):
        super().__init__()
        self.conn_manager: Optional['ConnectionManager'] = None

        # Data queues for ResponseProcessor (now thread-safe)
        self.order_status_queue = queue.Queue()
        self.exec_details_queue = queue.Queue()
        self.portfolio_updates_queue = queue.Queue()
        self.error_messages_queue = queue.Queue()
        self.commission_report_data_queue = queue.Queue()
        self.account_value_update_queue = queue.Queue()
        self.tick_data_queue = queue.Queue()
        self.realtime_bar_queue = queue.Queue() # New queue for realtime bars
        # For accountSummary that is not part of a specific request-response pattern
        self.streaming_account_summary_map: Dict[str, Dict[str, Any]] = {}

        # Order ID management
        self._next_valid_order_id: Optional[OrderId] = None
        self._next_order_id_lock = threading.Lock()
        self.order_parent_map: Dict[OrderId, OrderId] = {} # For mapping orderId to parentId

        # Request ID management (for non-order requests)
        self._next_request_id: int = int(time.time() * 1000) # Initialize with a high value
        self._request_id_lock = threading.Lock()
        self._request_errors: Dict[int, IBError] = {} # To store errors for async requests


        # Connection health tracking
        self.last_api_activity_time: float = time.time()

        # For reqContractDetails resolution
        self._contract_details_results: Dict[int, List[ContractDetails]] = {}
        self._contract_details_events: Dict[int, Any] = {} # Will store asyncio.Event
        self._contract_details_lock = threading.Lock() # For synchronous access to dicts, not for event itself

        # For reqAccountSummary resolution
        self._account_summary_results: Dict[int, Dict[str, Any]] = {}
        self._account_summary_events: Dict[int, Any] = {} # Will store asyncio.Event
        self._account_summary_lock = threading.Lock()

        # For reqPnL resolution
        self._pnl_results: Dict[int, Dict[str, Any]] = {}
        self._pnl_events: Dict[int, Any] = {} # Will store asyncio.Event
        self._pnl_lock = threading.Lock()

        # For reqPositions() snapshot
        self._positions_results: List[Dict[str, Any]] = [] # This will be populated by position events
        self._positions_event: Optional[Any] = None # Stores the single asyncio.Event for reqPositions
        self._positions_lock = threading.Lock() # For synchronous access to the results list and event

    def set_connection_manager(self, conn_manager: 'ConnectionManager'):
        self.conn_manager = conn_manager

    def _update_last_api_activity_time(self): # Renamed
        self.last_api_activity_time = time.time()

    # --- Connection and Server Callbacks ---
    def nextValidId(self, orderId: OrderId):
        super().nextValidId(orderId)
        self._update_last_api_activity_time()
        logger.info(f"nextValidId received: {orderId}")
        with self._next_order_id_lock:
            self._next_valid_order_id = orderId
        if self.conn_manager:
            self.conn_manager.signal_api_ready()

    def connectAck(self):
        super().connectAck()
        self._update_last_api_activity_time()
        logger.info("connectAck: Connection handshake acknowledged by TWS/Gateway.")

    def connectionClosed(self):
        super().connectionClosed()
        logger.warning("connectionClosed: Connection to TWS/Gateway was closed by the server.")
        if self.conn_manager:
            self.conn_manager.signal_connection_lost()

    def error(self, reqId: TickerId, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        super().error(reqId, errorCode, errorString, advancedOrderRejectJson)
        self._update_last_api_activity_time()

        log_message = f"IB API Error: reqId={reqId}, errorCode={errorCode}, errorString='{errorString}'"
        if advancedOrderRejectJson:
            log_message += f", advancedOrderRejectJson='{advancedOrderRejectJson}'"

        socket_disconnect_codes = [502, 504, 507, 1100, 1300]
        session_or_data_farm_issue_codes = [501, 503, 509, 1101, 1102, 2103, 2105, 2107, 2108, 2158, 2150]
        connectivity_info_codes = [2104, 2106, 2157]
        client_subscription_issue_codes = [2100]

        is_socket_disconnect = errorCode in socket_disconnect_codes
        is_session_issue = errorCode in session_or_data_farm_issue_codes

        # Check if this error corresponds to an active data request that uses an asyncio.Event
        event_to_signal: Optional[Any] = None # Should be asyncio.Event
        if reqId != -1 : # reqId == -1 are general notifications, not tied to specific requests
            # Check across all event dictionaries - this could be consolidated if event dicts are merged
            # For simplicity, checking known ones. A more robust way might be a single combined event map.
            for event_map in [self._contract_details_events, self._account_summary_events, self._pnl_events]:
                if reqId in event_map:
                    event_to_signal = event_map.get(reqId)
                    break
            if reqId in self._positions_event if isinstance(self._positions_event, dict) else False: # Assuming _positions_event might become a dict for multiple reqs
                 # This part needs careful thought if _positions_event handles multiple reqIds.
                 # For now, assuming it's singular or reqId is key if it's a dict.
                 # If it's a single event for all position requests, this logic is simpler:
                 # if self._positions_event and self._positions_event.is_set() is False: event_to_signal = self._positions_event

                 # Simplified: if self._positions_event is an asyncio.Event and corresponds to this reqId (needs mapping if so)
                 # This part needs more robust handling if multiple position requests can be active.
                 # For now, let's assume reqId specific events are primarily in the dicts.
            # For reqPositions, if errorCode is retryable and _positions_event is active:
            if self._positions_event and not self._positions_event.is_set() and errorCode in RETRYABLE_IB_ERROR_CODES_FOR_GLOBAL_REQUESTS: # Define this list
                 # This error is not specific to a reqId for positions, but it's a global state.
                 # We need a way to signal the _request_positions_async if it's waiting.
                 # This is imperfect as the error isn't tied via reqId.
                 # A potential way: store a generic error for "positions" operation.
                 # self._request_errors[SOME_GENERIC_ID_FOR_POSITIONS] = ib_err
                 # For now, let's assume such errors might need manual interpretation or a different retry trigger.
                 # The current retry decorator is tied to exceptions from the called function.
                 # A simple approach: if a retryable global error occurs while _positions_event is waiting, set the event.
                 # The async function would then wake up, find no data, and potentially be retried if the decorator
                 # can be made to catch a generic "no data" error or a specific error raised by _request_positions_async.
                 # This is getting complex for the current retry structure.
                 # For now, error handling for reqPositions will be limited to errors that *do* somehow signal its event.
                 pass


        if event_to_signal: # This handles reqId-specific events
            ib_err = IBError(reqId, errorCode, errorString, advancedOrderRejectJson)
            self._request_errors[reqId] = ib_err
            if hasattr(event_to_signal, 'set'):
                event_to_signal.set()
            logger.warning(f"IB API Error for specific request {reqId} (Code: {errorCode}): '{errorString}'. Signaling event for specific reqId.")

        # Global error handling (socket disconnect, session issues, etc.)
        # These errors are not tied to a specific reqId's event but affect the whole connection.
        # The _request_errors dictionary is for reqId-specific errors that unblock an await.
        elif is_socket_disconnect:
            logger.error(log_message + " [SOCKET_DISCONNECT_ERROR]")
            if self.conn_manager: self.conn_manager.signal_connection_lost()
            # Add to general error queue as it's a global issue
            self.error_messages_queue.append({
                "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time()
            })
        elif is_session_issue:
            logger.error(log_message + " [SESSION_OR_DATA_FARM_ERROR]")
            if self.conn_manager: self.conn_manager.signal_connection_lost() # Treat as needing full reconnect
            self.error_messages_queue.append({
                "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time()
            })
        elif errorCode in connectivity_info_codes:
            logger.info(log_message + " [CONNECTIVITY_INFO]")
            # Optionally queue these if they are useful for general service health monitoring
        elif errorCode in client_subscription_issue_codes:
            logger.warning(log_message + " [CLIENT_SUBSCRIPTION_ISSUE]")
            self.error_messages_queue.append({
                "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time()
            })
        else: # General errors not tied to a specific async request or connection event
            logger.error(log_message + " [REQUEST_SPECIFIC_ERROR_OR_WARNING_OR_INFO]")
            # Only add to queue if reqId is not -1 (system message) or if it's an actual error worth reporting generally
            # This avoids flooding Kafka with info messages if not desired.
            # For now, queuing all non-specific-request, non-connection critical errors.
            if reqId != -1 : # Exclude system messages unless explicitly handled as errors
                 self.error_messages_queue.put({ # Changed to put
                    "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                    "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time()
                })


    def orderStatus(self, orderId: OrderId, status: str, filled: float, remaining: float, avgFillPrice: float,
                    permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        self._update_last_api_activity_time()
        retrieved_parent_id = self.order_parent_map.get(orderId) # Get parentId if available
        log_entry = {"orderId": orderId, "status": status, "filled": filled, "remaining": remaining,
                     "avgFillPrice": avgFillPrice, "permId": permId,
                     "parentId": retrieved_parent_id if retrieved_parent_id is not None else parentId,
                     "lastFillPrice": lastFillPrice, "clientId": clientId, "whyHeld": whyHeld,
                     "mktCapPrice": mktCapPrice, "timestamp": time.time()}
        logger.info(f"OrderStatus: BrokerOrderID={orderId}, PermID={permId}, Status='{status}', Filled={filled}, Remaining={remaining}, AvgFillPrice={avgFillPrice}, ParentId={log_entry['parentId']}") # Enhanced log
        self.order_status_queue.put(log_entry)

    def openOrder(self, orderId: OrderId, contract: Contract, order: Order, orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        self._update_last_api_activity_time()
        self.order_parent_map[orderId] = order.parentId # Store parentId
        # This callback provides full order state. It can be added to order_status_queue or a specific open_order_queue.
        # To avoid duplication if orderStatus also provides comprehensive updates, decide which one is primary source for Kafka.
        # For now, mainly logging it here. ResponseProcessor will use orderStatus primarily.
        logger.info(f"openOrder: Id={orderId}, ParentId={order.parentId}, Symbol='{contract.symbol}', Action='{order.action}', Type='{order.orderType}', Qty={order.totalQuantity}, Status='{orderState.status}'")

    def openOrderEnd(self):
        super().openOrderEnd()
        self._update_last_api_activity_time()
        logger.info("openOrderEnd: All open orders have been sent by TWS/Gateway for this client.")

    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        self._update_last_api_activity_time()
        logger.info(f"ExecDetails: ReqID={reqId}, BrokerOrderID={execution.orderId}, ExecID='{execution.execId}', Symbol='{contract.symbol}', Side='{execution.side}', Qty={execution.shares}, Price={execution.price}, Account='{execution.acctNumber}'") # Enhanced log
        self.exec_details_queue.put({"reqId": reqId, "contract_obj": contract, "execution_obj": execution, "received_at": time.time()})

    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"execDetailsEnd for reqId: {reqId}")

    def commissionReport(self, commissionReport: CommissionReport):
        super().commissionReport(commissionReport)
        self._update_last_api_activity_time()
        logger.info(f"CommissionReport: ExecID='{commissionReport.execId}', Commission={commissionReport.commission}, Currency='{commissionReport.currency}', RealizedPNL={commissionReport.realizedPNL}") # Log already good, minor label consistency
        self.commission_report_data_queue.put(commissionReport)


    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        self._update_last_api_activity_time()
        log_entry = {"key": key, "val": val, "currency": currency, "accountName": accountName, "timestamp": time.time()}
        key_account_values = ["AccountCode", "TotalCashValue", "NetLiquidation", "BuyingPower", "AvailableFunds", "ExcessLiquidity", "MaintMarginReq", "InitMarginReq"]
        if key in key_account_values:
             logger.info(f"updateAccountValue: Acc='{accountName}', Key='{key}', Val='{val}', Curr='{currency}'")
        else:
            logger.debug(f"updateAccountValue: {log_entry}")
        # This is a streaming update, store in a way ResponseProcessor can create AccountValueUpdateEvent
        self.account_summary_map[f"{accountName}:{key}:{currency}"] = log_entry # Keep for snapshot logic if needed
        self.account_value_update_queue.put(log_entry) # Also put on the dedicated queue for streaming

    def updatePortfolio(self, contract: Contract, position: float, marketPrice: float, marketValue: float,
                        averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str):
        super().updatePortfolio(contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName)
        self._update_last_api_activity_time()
        log_entry = {
            "contract_obj": contract, "position": position, "marketPrice": marketPrice,
            "marketValue": marketValue, "averageCost": averageCost, "unrealizedPNL": unrealizedPNL,
            "realizedPNL": realizedPNL, "accountName": accountName, "timestamp": time.time()
        }
        logger.info(f"UpdatePortfolio: Account='{accountName}', Symbol='{contract.symbol}', SecType='{contract.secType}', ConID={contract.conId}, Position={position}, AvgCost={averageCost}, UnrealizedPNL={unrealizedPNL}") # Enhanced log
        self.portfolio_updates_queue.put(log_entry)

    def updateAccountTime(self, timeStamp: str):
        super().updateAccountTime(timeStamp)
        self._update_last_api_activity_time()
        logger.debug(f"updateAccountTime: Server time is {timeStamp}")

    def accountDownloadEnd(self, accountName: str):
        super().accountDownloadEnd(accountName)
        self._update_last_api_activity_time()
        logger.info(f"accountDownloadEnd for account: {accountName}.")

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        self._update_last_api_activity_time()
        with self._account_summary_lock:
            if reqId in self._account_summary_events:
                if reqId not in self._account_summary_results:
                    self._account_summary_results[reqId] = {"account": account, "summary_values": {}}
                self._account_summary_results[reqId]["summary_values"][tag] = {"value": value, "currency": currency}
                logger.debug(f"accountSummary (for active reqId={reqId}): Tag='{tag}', Value='{value}', Acc='{account}'")
            else: # Streaming update (not part of a specific reqAccountSummary call by this client)
                logger.debug(f"accountSummary (streaming): Account='{account}', Tag='{tag}', Value='{value}', Curr='{currency}'")
                streaming_entry = {
                    "key": tag, "val": value, "currency": currency, "accountName": account,
                    "timestamp": time.time()
                }
                self.account_value_update_queue.put(streaming_entry)
                self.streaming_account_summary_map[f"{account}:{tag}:{currency}"] = {"value": value, "currency": currency, "timestamp": streaming_entry["timestamp"]}


    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"accountSummaryEnd for reqId: {reqId}")
        with self._account_summary_lock:
            if reqId in self._account_summary_events:
                self._account_summary_events[reqId].set()
            else:
                logger.warning(f"Received accountSummaryEnd for reqId: {reqId} not actively awaited or already cleared.")

    def pnl(self, reqId: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float):
        super().pnl(reqId, dailyPnL, unrealizedPnL, realizedPnL)
        self._update_last_api_activity_time()
        log_entry = {"dailyPnL": dailyPnL, "unrealizedPnL": unrealizedPnL, "realizedPnL": realizedPnL}
        logger.info(f"pnl for reqId={reqId}: DailyPnL={dailyPnL}, UnrealizedPnL={unrealizedPnL}, RealizedPnL={realizedPnL}")
        with self._pnl_lock:
            if reqId in self._pnl_events:
                self._pnl_results[reqId] = log_entry
                self._pnl_events[reqId].set()
            else: # Streaming PnL update
                self.error_messages_queue.put({"type": "pnl_stream", "reqId": reqId, "data": log_entry, "timestamp": time.time()}) # Changed to put

    def pnlSingle(self, reqId: int, pos: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float, value: float):
        super().pnlSingle(reqId, pos, dailyPnL, unrealizedPnL, realizedPnL, value)
        self._update_last_api_activity_time()
        log_entry = {"pos": pos, "dailyPnL": dailyPnL, "unrealizedPnL": unrealizedPnL, "realizedPnL": realizedPnL, "value": value}
        logger.info(f"pnlSingle for reqId={reqId}, pos={pos}: DailyPnL={dailyPnL}, UnrealizedPnL={unrealizedPnL}, Value={value}")
        # Similar to pnl, would need event/result dicts if used synchronously
        self.error_messages_queue.put({"type": "pnl_single_stream", "reqId": reqId, "data": log_entry, "timestamp": time.time()}) # Changed to put

    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        super().position(account, contract, position, avgCost)
        self._update_last_api_activity_time()
        log_entry = {"account": account, "contract_obj": contract, "position": position, "avgCost": avgCost, "timestamp": time.time()}
        with self._positions_lock:
            if self._positions_event is not None and not self._positions_event.is_set():
                self._positions_results.append(log_entry)
            else:
                logger.debug(f"Received position data for {contract.symbol} outside active reqPositions or event already set.")
                # This could be a streaming position update if reqAccountUpdates(..., True) was called
                # For now, only collect if _positions_event is active. If streaming needed, add to portfolio_updates_queue.
                # self.portfolio_updates_queue.append(log_entry) # If general position updates are desired on this queue


    def positionEnd(self):
        super().positionEnd()
        self._update_last_api_activity_time()
        logger.info("positionEnd: All positions have been sent (response to reqPositions).")
        with self._positions_lock:
            if self._positions_event is not None:
                self._positions_event.set()

    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        self._update_last_api_activity_time()
        logger.info(f"managedAccounts: {accountsList}")
        # self.managed_accounts_list = accountsList.split(",") # Store if needed by ConnectionManager

    def get_next_order_id_and_increment(self) -> Optional[OrderId]:
        with self._next_order_id_lock:
            if self._next_valid_order_id is not None:
                current_id = self._next_valid_order_id
                # logger.debug(f"Providing order ID {current_id}, next will be {current_id + 1}") # Too verbose for default
                self._next_valid_order_id += 1
                return current_id
            else:
                logger.error("get_next_order_id_and_increment: _next_valid_order_id is not set. API not ready?")
                return None

    def get_next_request_id(self) -> int:
        """Generates a new unique request ID for data requests."""
        with self._request_id_lock:
            self._next_request_id += 1
            # logger.debug(f"Providing request ID {self._next_request_id}") # Too verbose
            return self._next_request_id

    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().contractDetails(reqId, contractDetails)
        self._update_last_api_activity_time()
        logger.info(f"contractDetails: reqId={reqId}, Symbol={contractDetails.contract.symbol}, ConId={contractDetails.contract.conId}, Exchange={contractDetails.contract.exchange}, PrimaryExchange={contractDetails.contract.primaryExchange}")
        with self._contract_details_lock:
            if reqId not in self._contract_details_results:
                self._contract_details_results[reqId] = []
            self._contract_details_results[reqId].append(contractDetails)

    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"contractDetailsEnd for reqId: {reqId}")
        with self._contract_details_lock:
            if reqId in self._contract_details_events:
                self._contract_details_events[reqId].set()
            else:
                logger.warning(f"Received contractDetailsEnd for unknown reqId: {reqId} or event already cleared.")

    # Ensure all other overridden EWrapper methods also call self._update_last_api_activity_time()
    # For example:
    # def historicalData(self, reqId: int, bar: BarData):
    #    super().historicalData(reqId, bar)
    #    self._update_last_api_activity_time()
    #    # ...
    # def realtimeBar(self, reqId: TickerId, time: int, open_: float, high: float, low: float, close: float, volume: int, wap: float, count: int):
    #    super().realtimeBar(reqId, time, open_, high, low, close, volume, wap, count)
    #    self._update_last_api_activity_time()
    #    # ...
    # etc. for all other callbacks used.

    # --- Tick Data Callbacks ---
    def tickPrice(self, reqId: TickerId, tickType: int, price: float, attrib: Any): # tickType is TickType enum
        super().tickPrice(reqId, tickType, price, attrib)
        self._update_last_api_activity_time()
        logger.debug(f"TickPrice: ReqID={reqId}, TickType={TickTypeEnum.idx2name[tickType] if tickType < len(TickTypeEnum.idx2name) and TickTypeEnum.idx2name[tickType] else tickType}, Price={price}")
        data = {"type": "price", "reqId": reqId, "tickType": tickType, "price": price, "attrib": attrib, "timestamp": time.time()}
        self.tick_data_queue.put(data)

    def tickSize(self, reqId: TickerId, tickType: int, size: float): # tickType is TickType enum / size is Decimal
        super().tickSize(reqId, tickType, size)
        self._update_last_api_activity_time()
        logger.debug(f"TickSize: ReqID={reqId}, TickType={TickTypeEnum.idx2name[tickType] if tickType < len(TickTypeEnum.idx2name) and TickTypeEnum.idx2name[tickType] else tickType}, Size={size}")
        data = {"type": "size", "reqId": reqId, "tickType": tickType, "size": size, "timestamp": time.time()}
        self.tick_data_queue.put(data)

    def tickOptionComputation(self, reqId: TickerId, tickType: int, tickAttrib: int,
                             impliedVol: float, delta: float, optPrice: float, pvDividend: float,
                             gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
        self._update_last_api_activity_time()
        logger.debug(f"TickOptionComputation: ReqID={reqId}, TickType={TickTypeEnum.idx2name[tickType] if tickType < len(TickTypeEnum.idx2name) and TickTypeEnum.idx2name[tickType] else tickType}, ImpliedVol={impliedVol}, Delta={delta}, OptPrice={optPrice}, UndPrice={undPrice}")
        # Potentially queue this if needed, format similar to other ticks. For now, just logging.
        # data = {"type": "option_computation", "reqId": reqId, "tickType": tickType, ... , "timestamp": time.time()}
        # self.tick_data_queue.put(data)


    def tickGeneric(self, reqId: TickerId, tickType: int, value: float): # tickType is TickType enum
        super().tickGeneric(reqId, tickType, value)
        self._update_last_api_activity_time()
        logger.debug(f"TickGeneric: ReqID={reqId}, TickType={TickTypeEnum.idx2name[tickType] if tickType < len(TickTypeEnum.idx2name) and TickTypeEnum.idx2name[tickType] else tickType}, Value={value}")
        data = {"type": "generic", "reqId": reqId, "tickType": tickType, "value": value, "timestamp": time.time()}
        self.tick_data_queue.put(data)

    def tickString(self, reqId: TickerId, tickType: int, value: str): # tickType is TickType enum
        super().tickString(reqId, tickType, value)
        self._update_last_api_activity_time()
        logger.debug(f"TickString: ReqID={reqId}, TickType={TickTypeEnum.idx2name[tickType] if tickType < len(TickTypeEnum.idx2name) and TickTypeEnum.idx2name[tickType] else tickType}, Value='{value}'")
        data = {"type": "string", "reqId": reqId, "tickType": tickType, "value": value, "timestamp": time.time()}
        self.tick_data_queue.put(data)

    def tickEFP(self, reqId: TickerId, tickType: int, basisPoints: float,
                formattedBasisPoints: str, totalDividends: float,
                hoursToExpiration: int, dividendImpact: float, dividendsToExpiration: float): # tickType is TickType enum
        super().tickEFP(reqId, tickType, basisPoints, formattedBasisPoints, totalDividends, hoursToExpiration, dividendImpact, dividendsToExpiration)
        self._update_last_api_activity_time()
        # logger.debug(f"tickEFP: reqId={reqId}, tickType={tickType}")
        # Implement further processing or queuing if needed

    def tickSnapshotEnd(self, reqId: int):
        super().tickSnapshotEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"tickSnapshotEnd for reqId: {reqId}")
        # Implement further processing or queuing if needed

    def marketDataType(self, reqId: TickerId, marketDataType: int):
        super().marketDataType(reqId, marketDataType)
        self._update_last_api_activity_time()
        logger.info(f"marketDataType: reqId={reqId}, marketDataType={marketDataType}")
        # Implement further processing or queuing if needed

    # --- Market Depth Callbacks ---
    def updateMktDepth(self, reqId: TickerId, position: int, operation: int, side: int, price: float, size: float): # size is Decimal
        super().updateMktDepth(reqId, position, operation, side, price, size)
        self._update_last_api_activity_time()
        # logger.debug(f"updateMktDepth: reqId={reqId}, position={position}, operation={operation}, side={side}, price={price}, size={size}")
        # Implement further processing or queuing if needed

    def updateMktDepthL2(self, reqId: TickerId, position: int, marketMaker: str, operation: int, side: int, price: float, size: float, isSmartDepth: bool): # size is Decimal
        super().updateMktDepthL2(reqId, position, marketMaker, operation, side, price, size, isSmartDepth)
        self._update_last_api_activity_time()
        # logger.debug(f"updateMktDepthL2: reqId={reqId}, position={position}, marketMaker='{marketMaker}', operation={operation}, side={side}, price={price}, size={size}, isSmartDepth={isSmartDepth}")
        # Implement further processing or queuing if needed

    def mktDepthExchanges(self, depthMktDataDescriptions: Any): # Type is list of DepthMktDataDescription
        super().mktDepthExchanges(depthMktDataDescriptions)
        self._update_last_api_activity_time()
        logger.info("mktDepthExchanges received")
        # Implement further processing or queuing if needed

    # --- News Callbacks ---
    def updateNewsBulletin(self, msgId: int, msgType: int, newsMessage: str, originExch: str):
        super().updateNewsBulletin(msgId, msgType, newsMessage, originExch)
        self._update_last_api_activity_time()
        logger.info(f"updateNewsBulletin: msgId={msgId}, msgType={msgType}, originExch='{originExch}', message='{newsMessage}'")
        # Implement further processing or queuing if needed

    # --- Financial Advisor Callbacks ---
    def receiveFA(self, faData: int, cxml: str): # faData is FaDataType enum
        super().receiveFA(faData, cxml)
        self._update_last_api_activity_time()
        logger.info(f"receiveFA: faDataType={faData}")
        # Implement further processing or queuing if needed

    def replaceFAEnd(self, reqId: int, text: str):
        super().replaceFAEnd(reqId, text)
        self._update_last_api_activity_time()
        logger.info(f"replaceFAEnd for reqId: {reqId}, text: {text}")

    # --- Historical Data Callbacks ---
    def historicalData(self, reqId: int, bar: Any): # Type is BarData
        super().historicalData(reqId, bar)
        self._update_last_api_activity_time()
        # logger.debug(f"historicalData: reqId={reqId}, bar date={bar.date}, open={bar.open}, high={bar.high}, low={bar.low}, close={bar.close}")
        # Implement further processing or queuing if needed

    def historicalDataUpdate(self, reqId: int, bar: Any): # Type is BarData
        super().historicalDataUpdate(reqId, bar)
        self._update_last_api_activity_time()
        # logger.debug(f"historicalDataUpdate: reqId={reqId}, bar date={bar.date}")
        # Implement further processing or queuing if needed

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        self._update_last_api_activity_time()
        logger.info(f"historicalDataEnd for reqId: {reqId}, start='{start}', end='{end}'")
        # Implement further processing or queuing if needed

    # --- Realtime Bars Callbacks ---
    def realtimeBar(self, reqId: TickerId, time_epoch_seconds: int, open_: float, high: float, low: float, close: float, volume: float, wap: float, count: int): # volume, wap are Decimal
        super().realtimeBar(reqId, time_epoch_seconds, open_, high, low, close, volume, wap, count)
        self._update_last_api_activity_time()
        logger.debug(f"RealTimeBar: ReqID={reqId}, Time={time_epoch_seconds}, O={open_}, H={high}, L={low}, C={close_}, V={volume}") # Enhanced log
        data = {
            "reqId": reqId,
            "time_epoch_seconds": time_epoch_seconds,
            "open": float(open_), "high": float(high), "low": float(low), "close": float(close_),
            "volume": float(volume), "wap": float(wap), "count": int(count),
            "timestamp": time.time() # Processing timestamp
        }
        self.realtime_bar_queue.put(data)

    # --- Scanner Callbacks ---
    def scannerParameters(self, xml: str):
        super().scannerParameters(xml)
        self._update_last_api_activity_time()
        logger.info("scannerParameters received.")
        # For lengthy XML, consider logging only a snippet or its presence.
        # logger.debug(f"scannerParameters: xml='{xml}'")
        # Implement further processing or queuing if needed

    def scannerData(self, reqId: int, rank: int, contractDetails: ContractDetails, distance: str, benchmark: str, projection: str, legsStr: str):
        super().scannerData(reqId, rank, contractDetails, distance, benchmark, projection, legsStr)
        self._update_last_api_activity_time()
        # logger.debug(f"scannerData: reqId={reqId}, rank={rank}, symbol={contractDetails.contract.symbol}")
        # Implement further processing or queuing if needed

    def scannerDataEnd(self, reqId: int):
        super().scannerDataEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"scannerDataEnd for reqId: {reqId}")
        # Implement further processing or queuing if needed

    # --- Historical Ticks Callbacks ---
    def historicalTicks(self, reqId: int, ticks: List[Any], done: bool): # Type of ticks is list of HistoricalTick
        super().historicalTicks(reqId, ticks, done)
        self._update_last_api_activity_time()
        # logger.debug(f"historicalTicks: reqId={reqId}, num_ticks={len(ticks)}, done={done}")
        # Implement further processing or queuing if needed

    def historicalTicksBidAsk(self, reqId: int, ticks: List[Any], done: bool): # Type of ticks is list of HistoricalTickBidAsk
        super().historicalTicksBidAsk(reqId, ticks, done)
        self._update_last_api_activity_time()
        # logger.debug(f"historicalTicksBidAsk: reqId={reqId}, num_ticks={len(ticks)}, done={done}")
        # Implement further processing or queuing if needed

    def historicalTicksLast(self, reqId: int, ticks: List[Any], done: bool): # Type of ticks is list of HistoricalTickLast
        super().historicalTicksLast(reqId, ticks, done)
        self._update_last_api_activity_time()
        # logger.debug(f"historicalTicksLast: reqId={reqId}, num_ticks={len(ticks)}, done={done}")
        # Implement further processing or queuing if needed

    # --- Other Callbacks ---
    def tickReqParams(self, tickerId: int, minTick: float, bboExchange: str, snapshotPermissions: int):
        super().tickReqParams(tickerId, minTick, bboExchange, snapshotPermissions)
        self._update_last_api_activity_time()
        logger.info(f"tickReqParams: tickerId={tickerId}, minTick={minTick}, bboExchange='{bboExchange}', snapshotPermissions={snapshotPermissions}")
        # Implement further processing or queuing if needed

    def headTimestamp(self, reqId: int, headTimestamp: str):
        super().headTimestamp(reqId, headTimestamp)
        self._update_last_api_activity_time()
        logger.info(f"headTimestamp for reqId {reqId}: {headTimestamp}")
        # Implement further processing or queuing if needed

    def tickByTickAllLast(self, reqId: int, tickType: int, time: int, price: float, size: float, tickAttribLast: Any, exchange: str, specialConditions: str): # size is Decimal, tickAttribLast is TickAttribLast
        super().tickByTickAllLast(reqId, tickType, time, price, size, tickAttribLast, exchange, specialConditions)
        self._update_last_api_activity_time()
        # logger.debug(f"tickByTickAllLast: reqId={reqId}, time={time}, price={price}, size={size}")
        # Implement further processing or queuing if needed

    def tickByTickBidAsk(self, reqId: int, time: int, bidPrice: float, askPrice: float, bidSize: float, askSize: float, tickAttribBidAsk: Any): # bidSize, askSize are Decimal, tickAttribBidAsk is TickAttribBidAsk
        super().tickByTickBidAsk(reqId, time, bidPrice, askPrice, bidSize, askSize, tickAttribBidAsk)
        self._update_last_api_activity_time()
        # logger.debug(f"tickByTickBidAsk: reqId={reqId}, time={time}, bidPrice={bidPrice}, askPrice={askPrice}")
        # Implement further processing or queuing if needed

    def tickByTickMidPoint(self, reqId: int, time: int, midPoint: float):
        super().tickByTickMidPoint(reqId, time, midPoint)
        self._update_last_api_activity_time()
        # logger.debug(f"tickByTickMidPoint: reqId={reqId}, time={time}, midPoint={midPoint}")
        # Implement further processing or queuing if needed

    def orderBound(self, reqId: int, apiClientId: int, apiOrderId: int):
        super().orderBound(reqId, apiClientId, apiOrderId)
        self._update_last_api_activity_time()
        logger.info(f"orderBound: reqId={reqId}, apiClientId={apiClientId}, apiOrderId={apiOrderId}")
        # Implement further processing or queuing if needed

    def completedOrder(self, contract: Contract, order: Order, orderState: OrderState):
        super().completedOrder(contract, order, orderState)
        self._update_last_api_activity_time()
        logger.info(f"completedOrder: Symbol='{contract.symbol}', IBOrderID={order.orderId}, Status='{orderState.status}'")
        # Implement further processing or queuing if needed (e.g., for a separate completed orders topic)

    def completedOrdersEnd(self):
        super().completedOrdersEnd()
        self._update_last_api_activity_time()
        logger.info("completedOrdersEnd received.")
        # Implement further processing or queuing if needed

    def wshMetaData(self, reqId: int, dataJson: str):
        super().wshMetaData(reqId, dataJson)
        self._update_last_api_activity_time()
        logger.info(f"wshMetaData for reqId {reqId} received.")
        # Implement further processing or queuing if needed

    def wshEventData(self, reqId: int, dataJson: str):
        super().wshEventData(reqId, dataJson)
        self._update_last_api_activity_time()
        logger.info(f"wshEventData for reqId {reqId} received.")
        # Implement further processing or queuing if needed

    def historicalSchedule(self, reqId: int, startDateTime: str, endDateTime: str, timeZone: str, sessions: List[Any]): # sessions is list of HistoricalSession
        super().historicalSchedule(reqId, startDateTime, endDateTime, timeZone, sessions)
        self._update_last_api_activity_time()
        logger.info(f"historicalSchedule for reqId {reqId} received.")
        # Implement further processing or queuing if needed

    def userInfo(self, reqId: int, whiteBrandingId: str):
        super().userInfo(reqId, whiteBrandingId)
        self._update_last_api_activity_time()
        logger.info(f"userInfo for reqId {reqId}: whiteBrandingId={whiteBrandingId}")
        # Implement further processing or queuing if needed
