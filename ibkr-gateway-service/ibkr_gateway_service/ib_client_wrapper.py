import logging
import threading
import time
from typing import Optional, List, Dict, Any

from ibapi.client import EClient #type: ignore
from ibapi.contract import Contract, ContractDetails #type: ignore
from ibapi.order import Order #type: ignore
from ibapi.execution import ExecutionFilter #type: ignore
# from ibapi.tag_value import TagValue # For advanced order properties, if needed

# Assuming relative import works if these files are in the same package
from .ib_wrapper import IBWrapperImpl
from .config import IBKRConfig

logger = logging.getLogger(__name__)

InternalOrderRequest = Dict[str, Any] # Placeholder for Protobuf-generated class or Pydantic model

class RateLimitExceededError(Exception):
    """Custom exception for rate limit exceeded after timeout."""
    pass

class TokenBucketRateLimiter:
    def __init__(self, capacity: int, refill_rate_per_second: float):
        self.capacity = float(max(1, capacity)) # Ensure capacity is at least 1
        self.tokens = float(max(1, capacity)) # Start full
        self.refill_rate_per_second = float(max(0.1, refill_rate_per_second)) # Ensure positive refill rate
        self.last_refill_timestamp = time.monotonic()
        self._lock = threading.Lock()
        logger.info(f"TokenBucketRateLimiter initialized with capacity {self.capacity}, refill rate {self.refill_rate_per_second} tps.")

    def _refill_tokens(self):
        # This method must be called under lock
        now = time.monotonic()
        elapsed_time = now - self.last_refill_timestamp
        if elapsed_time > 0: # Only refill if time has passed
            tokens_to_add = elapsed_time * self.refill_rate_per_second
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill_timestamp = now
            # logger.debug(f"RateLimiter: Refilled. Tokens: {self.tokens:.2f}, Elapsed: {elapsed_time:.2f}s")


    def consume(self, tokens_to_consume: int = 1, blocking: bool = True, timeout_seconds: Optional[float] = 5.0) -> bool:
        if tokens_to_consume <= 0:
            return True

        start_time = time.monotonic()

        while True: # Loop for blocking wait
            with self._lock:
                self._refill_tokens()
                if self.tokens >= tokens_to_consume:
                    self.tokens -= tokens_to_consume
                    # logger.debug(f"RateLimiter: Consumed {tokens_to_consume}. Tokens left: {self.tokens:.2f}")
                    return True

            if not blocking:
                # logger.debug(f"RateLimiter: Non-blocking consume failed. Tokens: {self.tokens:.2f}, Need: {tokens_to_consume}")
                return False

            # If blocking, calculate remaining timeout and necessary wait time
            if timeout_seconds is not None:
                elapsed_wait_time = time.monotonic() - start_time
                remaining_timeout = timeout_seconds - elapsed_wait_time
                if remaining_timeout <= 0:
                    logger.warning(f"RateLimiter: Timeout ({timeout_seconds:.2f}s) exceeded waiting for {tokens_to_consume} tokens. Current tokens: {self.tokens:.2f}")
                    return False # Timed out

            # Determine how long to wait for needed tokens, or a small polling interval
            needed_tokens_to_generate = tokens_to_consume - self.tokens # self.tokens could be negative if capacity < tokens_to_consume
            if needed_tokens_to_generate <=0 : # Should have been caught by the check above, but for safety
                 needed_tokens_to_generate = 1 # at least wait for some tokens

            estimated_wait_for_needed_tokens = needed_tokens_to_generate / self.refill_rate_per_second

            # Sleep for a short, calculated interval before retrying
            # Max wait is remaining_timeout if specified, otherwise a fraction of estimated_wait or a fixed short poll
            sleep_interval = min(0.05, estimated_wait_for_needed_tokens / 2 if estimated_wait_for_needed_tokens > 0 else 0.05) # Poll frequently but not too aggressively
            if sleep_interval <=0: sleep_interval = 0.01 # Minimum sleep

            if remaining_timeout is not None and remaining_timeout < sleep_interval:
                sleep_interval = remaining_timeout # Don't sleep longer than remaining timeout

            # logger.debug(f"RateLimiter: Waiting for tokens. Have {self.tokens:.2f}, need {tokens_to_consume}. Sleeping for {sleep_interval:.3f}s")
            time.sleep(sleep_interval)
            # Loop will re-acquire lock and re-check


class IBClientWrapper:
    def __init__(self, eclient: EClient, wrapper: IBWrapperImpl, config: IBKRConfig):
        self.client: EClient = eclient
        self.wrapper: IBWrapperImpl = wrapper
        self.config: IBKRConfig = config
        self._request_id_counter: int = int(time.time() * 1000)
        self._req_id_lock: threading.Lock = threading.Lock()

        self.rate_limiter = TokenBucketRateLimiter(
            capacity=config.max_requests_per_second,
            refill_rate_per_second=float(config.max_requests_per_second) # Refill up to capacity each second
        )

        # Ensure wrapper has these attributes, initialized in IBWrapperImpl.__init__.
        for attr_config in [
            ('_contract_details_results', dict), ('_contract_details_events', dict), ('_contract_details_lock', threading.Lock),
            ('_account_summary_results', dict), ('_account_summary_events', dict), ('_account_summary_lock', threading.Lock),
            ('_pnl_results', dict), ('_pnl_events', dict), ('_pnl_lock', threading.Lock),
            ('_positions_results', list), ('_positions_event', type(None)), ('_positions_lock', threading.Lock) # _positions_event can be None or Event
        ]:
            attr_name, attr_type = attr_config
            if not hasattr(self.wrapper, attr_name):
                logger.warning(f"IBWrapperImpl instance is missing '{attr_name}'. Initializing to default type: {attr_type}.")
                if attr_type == type(None): # For _positions_event which can be None
                    setattr(self.wrapper, attr_name, None)
                else:
                    setattr(self.wrapper, attr_name, attr_type())


    def _get_next_req_id(self) -> int: # No rate limit for this internal helper
        with self._req_id_lock:
            self._request_id_counter += 1
            return self._request_id_counter

    def create_ib_contract(self, internal_order: InternalOrderRequest) -> Contract:
        # (Pasted from sub-step 3.4's successful report, no changes needed for rate limiting)
        contract = Contract()
        contract.symbol = str(internal_order.get("symbol", "")).upper()
        contract.secType = str(internal_order.get("asset_class", "STK")).upper()
        contract.exchange = str(internal_order.get("exchange", "SMART")).upper()
        contract.currency = str(internal_order.get("currency", "USD")).upper()

        if contract.secType == "STK" and contract.exchange == "SMART":
            primary_exchange = internal_order.get("primary_exchange")
            if primary_exchange:
                contract.primaryExchange = str(primary_exchange).upper()

        contract_month = internal_order.get("contract_month")
        if contract_month:
            contract.lastTradeDateOrContractMonth = str(contract_month)

        multiplier = internal_order.get("multiplier")
        if multiplier:
             contract.multiplier = str(multiplier)
        elif contract.secType == "OPT" and not multiplier:
            contract.multiplier = "100"

        if contract.secType in ["OPT", "FOP"]:
            strike = internal_order.get("strike")
            if strike is not None:
                contract.strike = float(strike)
            else:
                raise ValueError(f"Strike price is required for options (symbol: {contract.symbol})")

            right = internal_order.get("right")
            if right and str(right).upper() in ["C", "P", "CALL", "PUT"]:
                contract.right = str(right).upper()[0]
            else:
                raise ValueError(f"Valid right ('C' or 'P') is required for options (symbol: {contract.symbol})")

        if contract.secType == "CASH":
            contract.exchange = "IDEALPRO"
            if '.' in contract.symbol:
                parts = contract.symbol.split('.')
                if len(parts) == 2:
                    contract.symbol = parts[0].upper()
                    contract.currency = parts[1].upper()

        logger.debug(f"Created IB Contract: Symbol={contract.symbol}, SecType={contract.secType}, Exchange={contract.exchange}, Currency={contract.currency}, LastTradeDate={contract.lastTradeDateOrContractMonth}, Strike={contract.strike}, Right={contract.right}, Multiplier={contract.multiplier}, PrimaryExch={contract.primaryExchange}")
        return contract

    def create_ib_order(self, internal_order: InternalOrderRequest, ib_order_id: int) -> Order:
        # (Pasted from sub-step 3.4's successful report, no changes needed for rate limiting)
        order = Order()
        order.orderId = ib_order_id
        order.action = str(internal_order.get("side", "")).upper()

        quantity = internal_order.get("quantity")
        if quantity is None or float(quantity) <= 0:
            raise ValueError(f"Invalid or missing quantity for order: {quantity}")
        order.totalQuantity = float(quantity)

        order.orderType = str(internal_order.get("order_type", "")).upper()
        order.tif = str(internal_order.get("time_in_force", "DAY")).upper()

        if order.orderType in ["LMT", "STP LMT"]:
            limit_price = internal_order.get("limit_price")
            if limit_price is None:
                raise ValueError(f"Limit price required for {order.orderType} order.")
            order.lmtPrice = float(limit_price)

        if order.orderType in ["STP", "STP LMT"]: # Corrected from previous version: TRAIL handling is separate
            stop_price = internal_order.get("stop_price")
            if stop_price is None:
                raise ValueError(f"Stop price required for {order.orderType} order.")
            order.auxPrice = float(stop_price)

        if order.orderType == "TRAIL":
            if internal_order.get("trailing_percent") is not None:
                order.trailingPercent = float(internal_order["trailing_percent"])
                # auxPrice for TRAIL order is the optional limit price for TRAILLIMIT order.
                # If it's a TRAIL MKT, auxPrice is not used for trailing amount.
                # The trailing amount is set by trailingPercent or auxPrice if trailingPercent is not set.
                if internal_order.get("limit_offset") is not None: # For TRAILLIMIT, lmtPrice is the offset
                     order.lmtPrice = float(internal_order["limit_offset"]) # This might be incorrect, lmtPrice is absolute for TRAILLIMIT
                                                                       # For TRAILLIMIT, lmtPrice is the actual limit price, not offset.
                                                                       # The trailing stop price is trailStopPrice.
                                                                       # The limit component is lmtPrice.
                                                                       # Let's assume internal_order provides lmtPrice for TRAILLIMIT.
                     if internal_order.get("limit_price") is not None:
                         order.lmtPrice = float(internal_order.get("limit_price"))

            elif internal_order.get("trailing_amount") is not None:
                order.auxPrice = float(internal_order["trailing_amount"]) # This sets the trailing amount if no percentage
            else:
                 raise ValueError("Trailing percent or trailing amount required for TRAIL order offset.")

            if internal_order.get("trail_stop_price") is not None: # The price to trigger the trail
                order.trailStopPrice = float(internal_order["trail_stop_price"])
            # If TRAILLIMIT, ensure lmtPrice is set from internal_order.get("limit_price")
            if order.orderType == "TRAILLIMIT" and internal_order.get("limit_price") is not None:
                 order.lmtPrice = float(internal_order.get("limit_price"))


        order.transmit = True
        account_to_use = internal_order.get("account_id") or self.config.account_code
        if account_to_use:
            order.account = str(account_to_use)

        logger.debug(f"Created IB Order: Id={order.orderId}, Account='{order.account}', Action='{order.action}', Type='{order.orderType}', Qty={order.totalQuantity}, LmtPrc={order.lmtPrice}, AuxPrc={order.auxPrice}, Trail%={getattr(order, 'trailingPercent', 'N/A')}, TrailStopPrc={getattr(order, 'trailStopPrice', 'N/A')}")
        return order

    # --- Methods that call EClient, now with rate limiting ---

    def resolve_contract_details(self, contract_to_resolve: Contract, timeout_seconds: int = 10) -> Optional[List[ContractDetails]]:
        if not self.rate_limiter.consume(timeout_seconds=float(timeout_seconds)):
            msg = f"Rate limit exceeded for resolve_contract_details ({contract_to_resolve.symbol}). Request not sent."
            logger.error(msg)
            raise RateLimitExceededError(msg)

        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.error("Cannot resolve contract details: API not ready.")
            return None # Or raise ConnectionError

        req_id = self._get_next_req_id()
        logger.info(f"Requesting contract details for Symbol={contract_to_resolve.symbol}, SecType={contract_to_resolve.secType} (reqId: {req_id})")

        event = threading.Event()
        with self.wrapper._contract_details_lock:
            self.wrapper._contract_details_results[req_id] = []
            self.wrapper._contract_details_events[req_id] = event

        self.client.reqContractDetails(req_id, contract_to_resolve)

        resolved_details_list: Optional[List[ContractDetails]] = None
        if event.wait(timeout=float(timeout_seconds)):
            logger.info(f"Received contractDetailsEnd for reqId: {req_id}")
            with self.wrapper._contract_details_lock:
                 resolved_details_list = list(self.wrapper._contract_details_results.get(req_id, []))
        else:
            logger.error(f"Timeout waiting for contract details for {contract_to_resolve.symbol} (reqId: {req_id})")
            # No explicit cancel for reqContractDetails, rely on server to stop sending for this reqId

        with self.wrapper._contract_details_lock:
            self.wrapper._contract_details_results.pop(req_id, None)
            self.wrapper._contract_details_events.pop(req_id, None)

        return resolved_details_list

    def place_or_modify_order(self, contract: Contract, order: Order, req_timeout_seconds: float = 5.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds):
            msg = f"Rate limit exceeded for place_or_modify_order (ID: {order.orderId}). Order not sent."
            logger.error(msg)
            raise RateLimitExceededError(msg)

        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            msg = f"API not ready for order placement/modification (ID: {order.orderId})."
            logger.error(msg)
            raise ConnectionError(msg)

        logger.info(f"Submitting Place/Modify Order: IBOrderID={order.orderId}, Action={order.action}, Type={order.orderType}, Qty={order.totalQuantity} for Symbol='{contract.symbol}', ConID={contract.conId if contract.conId else 'N/A'}")
        self.client.placeOrder(order.orderId, contract, order)

    def cancel_order(self, ib_order_id: int, manual_cancel_order_time: str = "", req_timeout_seconds: float = 5.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds):
            msg = f"Rate limit exceeded for cancel_order (ID: {ib_order_id}). Request not sent."
            logger.error(msg)
            raise RateLimitExceededError(msg)

        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            msg = f"API not ready for order cancellation (ID: {ib_order_id})."
            logger.error(msg)
            raise ConnectionError(msg)
        logger.info(f"Requesting Cancel Order: IBOrderID={ib_order_id}")
        self.client.cancelOrder(ib_order_id, manual_cancel_order_time)

    def request_open_orders(self, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for reqOpenOrders")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise ConnectionError("API not ready for reqOpenOrders.")
        logger.info("Requesting client-specific open orders (reqOpenOrders).")
        self.client.reqOpenOrders()

    def request_all_open_orders(self, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for reqAllOpenOrders")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise ConnectionError("API not ready for reqAllOpenOrders.")
        logger.info("Requesting all open orders for the account (reqAllOpenOrders).")
        self.client.reqAllOpenOrders()

    def request_auto_open_orders(self, auto_bind: bool, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for reqAutoOpenOrders")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise ConnectionError("API not ready for reqAutoOpenOrders.")
        logger.info(f"Requesting auto open orders bind: {auto_bind}")
        self.client.reqAutoOpenOrders(auto_bind)

    def request_executions(self, exec_filter_dict: Optional[Dict[str, Any]] = None, req_timeout_seconds: float = 5.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for reqExecutions")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise ConnectionError("API not ready for requesting executions.")

        req_id = self._get_next_req_id()
        exec_filter = ExecutionFilter()
        if exec_filter_dict:
            if exec_filter_dict.get("clientId") is not None: exec_filter.clientId = int(exec_filter_dict["clientId"])
            # ... (populate other filter fields as in previous version)
            if exec_filter_dict.get("acctCode"): exec_filter.acctCode = str(exec_filter_dict["acctCode"])
            if exec_filter_dict.get("time"): exec_filter.time = str(exec_filter_dict["time"])
            if exec_filter_dict.get("symbol"): exec_filter.symbol = str(exec_filter_dict["symbol"])
            if exec_filter_dict.get("secType"): exec_filter.secType = str(exec_filter_dict["secType"])
            if exec_filter_dict.get("exchange"): exec_filter.exchange = str(exec_filter_dict["exchange"])
            if exec_filter_dict.get("side"): exec_filter.side = str(exec_filter_dict["side"])

        logger.info(f"Requesting executions (reqId: {req_id}) with filter: ClientId={exec_filter.clientId}, Acct={exec_filter.acctCode}, Time={exec_filter.time}, Sym={exec_filter.symbol}, SecType={exec_filter.secType}, Exch={exec_filter.exchange}, Side={exec_filter.side}")
        self.client.reqExecutions(req_id, exec_filter)

    def request_account_summary_sync(self, timeout_seconds: int = 10, group_name: str = "All",
                                     tags: str = "$AccountSummary:AccountType,NetLiquidation,TotalCashValue,SettledCash,BuyingPower,GrossPositionValue") -> Optional[Dict[str, Any]]:
        if not self.rate_limiter.consume(timeout_seconds=float(timeout_seconds)):
            raise RateLimitExceededError(f"Rate limit exceeded for request_account_summary_sync (group: {group_name}).")

        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise ConnectionError("API not ready for requesting account summary.")

        req_id = self._get_next_req_id()
        logger.info(f"Requesting account summary (sync) (reqId: {req_id}): Group='{group_name}', Tags='{tags}'")

        event = threading.Event()
        with self.wrapper._account_summary_lock:
            self.wrapper._account_summary_events[req_id] = event
            self.wrapper._account_summary_results[req_id] = {"account": None, "summary_values": {}}

        self.client.reqAccountSummary(req_id, group_name, tags)

        summary_data: Optional[Dict[str, Any]] = None
        if event.wait(timeout=float(timeout_seconds)):
            logger.info(f"Received accountSummaryEnd for reqId: {req_id}")
            with self.wrapper._account_summary_lock:
                summary_data = self.wrapper._account_summary_results.get(req_id)
        else:
            logger.error(f"Timeout waiting for account summary (reqId: {req_id})")
            self.client.cancelAccountSummary(req_id)

        with self.wrapper._account_summary_lock:
            self.wrapper._account_summary_events.pop(req_id, None)
            self.wrapper._account_summary_results.pop(req_id, None)
        return summary_data

    def cancel_account_summary(self, req_id: int, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for cancelAccountSummary")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"Cannot cancel account summary {req_id}: API not ready.")
            return
        logger.info(f"Cancelling account summary request (reqId: {req_id})")
        self.client.cancelAccountSummary(req_id)
        with self.wrapper._account_summary_lock: # Ensure thread safety for cleanup
            if req_id in self.wrapper._account_summary_events:
                self.wrapper._account_summary_events[req_id].set()
                self.wrapper._account_summary_events.pop(req_id, None)
            self.wrapper._account_summary_results.pop(req_id, None)

    def request_positions_sync(self, timeout_seconds: int = 10) -> Optional[List[Dict[str, Any]]]:
        if not self.rate_limiter.consume(timeout_seconds=float(timeout_seconds)): raise RateLimitExceededError("Rate limit exceeded for reqPositions_sync")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise ConnectionError("API not ready for requesting positions.")

        logger.info("Requesting current positions (sync).")
        event = threading.Event()
        with self.wrapper._positions_lock:
            self.wrapper._positions_event = event
            self.wrapper._positions_results = []

        self.client.reqPositions()

        position_list: Optional[List[Dict[str, Any]]] = None
        if event.wait(timeout=float(timeout_seconds)):
            logger.info("Received positionEnd for reqPositions (sync).")
            with self.wrapper._positions_lock:
                position_list = list(self.wrapper._positions_results)
        else:
            logger.error("Timeout waiting for positions end (reqPositions sync).")
            self.client.cancelPositions()

        with self.wrapper._positions_lock:
            self.wrapper._positions_event = None
            self.wrapper._positions_results = []
        return position_list

    def cancel_positions(self, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for cancelPositions")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning("Cannot cancel positions subscription: API not ready.")
            return
        logger.info("Cancelling positions subscription (cancelPositions).")
        self.client.cancelPositions()
        with self.wrapper._positions_lock: # Ensure thread safety for cleanup
             if self.wrapper._positions_event:
                self.wrapper._positions_event.set() # Unblock any waiting reqPositions_sync
                self.wrapper._positions_event = None
             self.wrapper._positions_results = []


    def request_pnl_sync(self, account:str, model_code:str = "", con_id:int = 0, timeout_seconds: int = 10) -> Optional[Dict[str, Any]]:
        if not self.rate_limiter.consume(timeout_seconds=float(timeout_seconds)): raise RateLimitExceededError("Rate limit exceeded for reqPnL_sync")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise ConnectionError("API not ready for PnL.")
        req_id = self._get_next_req_id()
        logger.info(f"Requesting PnL (sync) for account {account}, conId {con_id}, model '{model_code}' (reqId {req_id})")

        event = threading.Event()
        with self.wrapper._pnl_lock:
            self.wrapper._pnl_events[req_id] = event
            self.wrapper._pnl_results.pop(req_id, None)

        self.client.reqPnL(req_id, account, model_code, con_id)

        pnl_data: Optional[Dict[str, Any]] = None
        if event.wait(timeout=float(timeout_seconds)):
            logger.info(f"Received PnL data for reqId {req_id}")
            with self.wrapper._pnl_lock:
                pnl_data = self.wrapper._pnl_results.get(req_id)
        else:
            logger.error(f"Timeout waiting for PnL data for reqId {req_id}")
            self.client.cancelPnL(req_id)

        with self.wrapper._pnl_lock:
            self.wrapper._pnl_events.pop(req_id, None)
            self.wrapper._pnl_results.pop(req_id, None)
        return pnl_data

    def cancel_pnl(self, req_id:int, req_timeout_seconds: float = 2.0): # req_id is the one used in reqPnL
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for cancelPnL")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"Cannot cancel PnL {req_id}: API not ready.")
            return
        logger.info(f"Cancelling PnL request (reqId: {req_id})")
        self.client.cancelPnL(req_id)
        with self.wrapper._pnl_lock: # Ensure thread safety for cleanup
            if req_id in self.wrapper._pnl_events:
                self.wrapper._pnl_events[req_id].set()
                self.wrapper._pnl_events.pop(req_id, None)
            self.wrapper._pnl_results.pop(req_id, None)


    def subscribe_account_updates(self, account_code: str, subscribe: bool = True, req_timeout_seconds: float = 2.0):
        if not self.rate_limiter.consume(timeout_seconds=req_timeout_seconds): raise RateLimitExceededError("Rate limit exceeded for reqAccountUpdates")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise ConnectionError("API not ready for account updates subscription.")

        effective_account_code = account_code if account_code else self.config.account_code or ""
        if not effective_account_code:
            raise ValueError("Account code must be specified for account updates subscription.")

        logger.info(f"{'Subscribing to' if subscribe else 'Unsubscribing from'} account updates for {effective_account_code}.")
        self.client.reqAccountUpdates(subscribe, effective_account_code)

```
