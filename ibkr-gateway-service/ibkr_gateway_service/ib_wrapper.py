import logging
import threading
import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ContractDetails
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.execution import Execution
from ibapi.common import TickerId, OrderId # TickAttrib, BarData, TagValueList (not used directly here)
from ibapi.commission_report import CommissionReport

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

class IBWrapperImpl(EWrapper):
    def __init__(self):
        super().__init__()
        self.conn_manager: Optional['ConnectionManager'] = None

        # Data queues for ResponseProcessor
        self.order_status_queue: List[Dict[str, Any]] = []
        self.exec_details_queue: List[Dict[str, Any]] = []
        self.portfolio_updates_queue: List[Dict[str, Any]] = []
        self.error_messages_queue: List[Dict[str, Any]] = []
        self.streaming_account_value_queue: List[Dict[str, Any]] = []

        # Commission Report Cache
        self.commission_reports_cache: Dict[str, CommissionReport] = {}
        self.commission_reports_cache_lock = threading.Lock()

        # Order ID management
        self._next_valid_order_id: Optional[OrderId] = None
        self._next_order_id_lock = threading.Lock()

        # Connection health tracking
        self.last_api_activity_time: float = time.time()

        # For reqContractDetails resolution (synchronous-like pattern)
        self._contract_details_results: Dict[int, List[ContractDetails]] = {}
        self._contract_details_events: Dict[int, threading.Event] = {}
        self._contract_details_lock = threading.Lock()

        # For reqAccountSummary resolution (synchronous-like pattern)
        self._account_summary_results: Dict[int, Dict[str, Any]] = {}
        self._account_summary_events: Dict[int, threading.Event] = {}
        self._account_summary_lock = threading.Lock()

        # For reqPnL resolution (synchronous-like pattern)
        self._pnl_results: Dict[int, Dict[str, Any]] = {}
        self._pnl_events: Dict[int, threading.Event] = {}
        self._pnl_lock = threading.Lock()

        # For reqPositions() snapshot (synchronous-like pattern)
        self._positions_results: List[Dict[str, Any]] = []
        self._positions_event: Optional[threading.Event] = None
        self._positions_lock = threading.Lock()

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

        socket_disconnect_codes = [502, 504, 507, 1100, 1300] # Errors that mean the socket link is down
        # Errors that mean the session with TWS/Gateway is problematic, or data farms are down.
        # Excludes "connection restored/OK" messages.
        session_or_data_farm_issue_codes = [501, 503, 509, 2103, 2105, 2107, 2158, 2150] # Removed 1101, 1102, 2108
        # Informational messages about connectivity, including successful (re)connections.
        connectivity_info_codes = [2104, 2106, 2157, 1101, 1102, 2108] # Added 1101, 1102, 2108

        client_subscription_issue_codes = [2100] # E.g., "New account data requested but not subscribed"

        # Critical errors that might occur after nextValidId indicating fundamental auth/permission issues
        # These suggest the Gateway session itself is not viable for operations.
        CRITICAL_POST_CONNECT_ERROR_CODES = [
            506, # Unsupported TWS version (Gateway cannot login to IBKR backend)
            530, # Fatal error: User ID or Password check failed (for Gateway automated login)
            # Add other codes here if they represent similar "session unusable" states discovered post-nextValidId
            # e.g., specific codes for "Account disabled/not found", "Global trading permission denied for account"
            # For now, 2100 is a warning, but if "No market data permissions for account X" is a specific code, it could be here.
        ]

        is_socket_disconnect = errorCode in socket_disconnect_codes
        is_session_issue = errorCode in session_or_data_farm_issue_codes
        is_critical_post_connect_error = errorCode in CRITICAL_POST_CONNECT_ERROR_CODES

        if is_socket_disconnect:
            logger.error(log_message + " [SOCKET_DISCONNECT_ERROR]")
            if self.conn_manager: self.conn_manager.signal_connection_lost()
            # Do not add to queue, connection is lost.
        elif is_session_issue:
            logger.error(log_message + " [SESSION_OR_DATA_FARM_ERROR]")
            if self.conn_manager: self.conn_manager.signal_connection_lost() # Treat as needing full reconnect
            # Do not add to queue, connection is lost.
        elif is_critical_post_connect_error:
            logger.error(log_message + " [CRITICAL_POST_CONNECT_ERROR]")
            if self.conn_manager:
                # Check if nextValidId has already been processed by ConnectionManager.
                # Accessing _next_valid_id_event directly is not ideal but pragmatic for this specific check.
                if self.conn_manager._next_valid_id_event.is_set():
                    self.conn_manager.signal_critical_post_connect_error(errorCode, errorString)
                else:
                    # If nextValidId hasn't been confirmed yet, treat as an immediate connection failure.
                    self.conn_manager.signal_connection_lost()
            # This type of error is connection-level, do not add to general error_messages_queue.
        elif errorCode in connectivity_info_codes:
            # Log specific positive messages differently
            if errorCode in [1101, 1102, 2104, 2106, 2108, 2157]: # 2157 is "Connectivity to TWS has been resumed"
                 logger.info(log_message + " [CONNECTIVITY_RESTORED_INFO]")
            else: # Other general info
                 logger.info(log_message + " [CONNECTIVITY_INFO]")
            # These are informational, add to queue if reqId is valid (or always for general info)
            if reqId != -1 or errorCode in [2104, 2106, 1101, 1102, 2108, 2157]: # Store system-level connectivity info
                self.error_messages_queue.append({
                    "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                    "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time(), "type": "info"
                })
        elif errorCode in client_subscription_issue_codes:
            logger.warning(log_message + " [CLIENT_SUBSCRIPTION_ISSUE]")
            self.error_messages_queue.append({
                "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time(), "type": "warning"
            })
        else: # Default for other errors (typically request-specific)
            logger.error(log_message + " [REQUEST_SPECIFIC_ERROR_OR_WARNING]")
            # Add all other errors (usually request-specific) to the queue
            self.error_messages_queue.append({
                "reqId": reqId, "errorCode": errorCode, "errorString": errorString,
                "advancedOrderRejectJson": advancedOrderRejectJson, "timestamp": time.time(), "type": "error"
            })

    def orderStatus(self, orderId: OrderId, status: str, filled: float, remaining: float, avgFillPrice: float,
                    permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
            })

    def orderStatus(self, orderId: OrderId, status: str, filled: float, remaining: float, avgFillPrice: float,
                    permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        self._update_last_api_activity_time()
        log_entry = {"orderId": orderId, "status": status, "filled": filled, "remaining": remaining,
                     "avgFillPrice": avgFillPrice, "permId": permId, "parentId": parentId,
                     "lastFillPrice": lastFillPrice, "clientId": clientId, "whyHeld": whyHeld,
                     "mktCapPrice": mktCapPrice, "timestamp": time.time()}
        logger.info(f"orderStatus: Id={orderId}, Status='{status}', Filled={filled}, Rem={remaining}, AvgPx={avgFillPrice}")
        self.order_status_queue.append(log_entry)

    def openOrder(self, orderId: OrderId, contract: Contract, order: Order, orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        self._update_last_api_activity_time()
        # This callback provides full order state. It can be added to order_status_queue or a specific open_order_queue.
        # To avoid duplication if orderStatus also provides comprehensive updates, decide which one is primary source for Kafka.
        # For now, mainly logging it here. ResponseProcessor will use orderStatus primarily.
        logger.info(f"openOrder: Id={orderId}, Symbol='{contract.symbol}', Action='{order.action}', Type='{order.orderType}', Qty={order.totalQuantity}, Status='{orderState.status}'")

    def openOrderEnd(self):
        super().openOrderEnd()
        self._update_last_api_activity_time()
        logger.info("openOrderEnd: All open orders have been sent by TWS/Gateway for this client.")

    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        self._update_last_api_activity_time()
        # Storing the full objects for ResponseProcessor to normalize
        logger.info(f"execDetails: OrderId={execution.orderId}, ExecId='{execution.execId}', Side='{execution.side}', Qty={execution.shares}, Px={execution.price}")
        self.exec_details_queue.append({"reqId": reqId, "contract_obj": contract, "execution_obj": execution, "received_at": time.time()})

    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        self._update_last_api_activity_time()
        logger.info(f"execDetailsEnd for reqId: {reqId}")

    def commissionReport(self, commissionReport: CommissionReport):
        super().commissionReport(commissionReport)
        self._update_last_api_activity_time()
        with self.commission_reports_cache_lock:
            self.commission_reports_cache[commissionReport.execId] = commissionReport
        logger.info(f"Cached commissionReport: ExecId='{commissionReport.execId}', Comm={commissionReport.commission} {commissionReport.currency}")


    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        self._update_last_api_activity_time()
        log_entry = {
            "type": "AccountValueUpdate", # To help ResponseProcessor distinguish
            "key": key, "val": val, "currency": currency,
            "accountName": accountName, "timestamp": time.time()
        }
        key_account_values = ["AccountCode", "TotalCashValue", "NetLiquidation", "BuyingPower", "AvailableFunds", "ExcessLiquidity", "MaintMarginReq", "InitMarginReq"]
        if key in key_account_values:
             logger.info(f"updateAccountValue: Acc='{accountName}', Key='{key}', Val='{val}', Curr='{currency}'")
        else:
            logger.debug(f"updateAccountValue (other): {log_entry}")

        self.streaming_account_value_queue.append(log_entry)

    def updatePortfolio(self, contract: Contract, position: float, marketPrice: float, marketValue: float,
                        averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str):
        super().updatePortfolio(contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName)
        self._update_last_api_activity_time()
        log_entry = {
            "contract_obj": contract, "position": position, "marketPrice": marketPrice,
            "marketValue": marketValue, "averageCost": averageCost, "unrealizedPNL": unrealizedPNL,
            "realizedPNL": realizedPNL, "accountName": accountName, "timestamp": time.time()
        }
        logger.info(f"updatePortfolio: Acc='{accountName}', Sym='{contract.symbol}', Pos={position}, AvgCost={averageCost}")
        self.portfolio_updates_queue.append(log_entry)

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
                    self._account_summary_results[reqId] = {"account": account, "summary_values": {}} # type: ignore
                self._account_summary_results[reqId]["summary_values"][tag] = {"value": value, "currency": currency} # type: ignore
                logger.debug(f"accountSummary (for active reqId={reqId}): Tag='{tag}', Value='{value}', Acc='{account}'")
            else: # Streaming update (not part of a specific reqAccountSummary call by this client, or from general subscription)
                  # This path is less common for accountSummary; updateAccountValue is more typical for streams.
                log_entry = {
                    "type": "AccountSummaryStream", # To help ResponseProcessor distinguish
                    "account": account, "tag": tag, "value": value,
                    "currency": currency, "timestamp": time.time()
                }
                logger.debug(f"accountSummary (streaming): Account='{account}', Tag='{tag}', Value='{value}', Curr='{currency}'")
                self.streaming_account_value_queue.append(log_entry)


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
                self.error_messages_queue.append({"type": "pnl_stream", "reqId": reqId, "data": log_entry, "timestamp": time.time()})

    def pnlSingle(self, reqId: int, pos: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float, value: float):
        super().pnlSingle(reqId, pos, dailyPnL, unrealizedPnL, realizedPnL, value)
        self._update_last_api_activity_time()
        log_entry = {"pos": pos, "dailyPnL": dailyPnL, "unrealizedPnL": unrealizedPnL, "realizedPnL": realizedPnL, "value": value}
        logger.info(f"pnlSingle for reqId={reqId}, pos={pos}: DailyPnL={dailyPnL}, UnrealizedPnL={unrealizedPnL}, Value={value}")
        # Similar to pnl, would need event/result dicts if used synchronously
        self.error_messages_queue.append({"type": "pnl_single_stream", "reqId": reqId, "data": log_entry, "timestamp": time.time()})

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
                logger.debug(f"Providing order ID {current_id}, next will be {current_id + 1}")
                self._next_valid_order_id += 1
                return current_id
            else:
                logger.error("get_next_order_id_and_increment: _next_valid_order_id is not set. API not ready?")
                return None

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

    def currentTime(self, time_val: int):
        super().currentTime(time_val)
        self._update_last_api_activity_time()
        # Optional: log the time, perhaps at DEBUG level
        # import datetime
        # current_time_str = datetime.datetime.fromtimestamp(time_val, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        # logger.debug(f"currentTime: Server time is {time_val} ({current_time_str})")
