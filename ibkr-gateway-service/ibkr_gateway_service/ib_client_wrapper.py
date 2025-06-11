import asyncio
import logging
import threading
import time
from typing import Optional, List, Dict, Any, Coroutine

from ibapi.client import EClient #type: ignore
from ibapi.contract import Contract, ContractDetails #type: ignore
from ibapi.order import Order #type: ignore
from ibapi.execution import ExecutionFilter #type: ignore
# from ibapi.tag_value import TagValue # For advanced order properties, if needed

# Assuming relative import works if these files are in the same package
from .ib_wrapper import IBWrapperImpl
from .config import IBKRConfig
from .utils.exceptions import IBError, RateLimitExceededError, ConnectionError as IBConnectionError
from .utils.retry import async_retry_on_ib_error


logger = logging.getLogger(__name__)

InternalOrderRequest = Dict[str, Any]

RETRYABLE_IB_ERROR_CODES = [
    2103,
    2105,
    2107,
    2108,
]


class TokenBucketRateLimiter:
    def __init__(self, capacity: int, refill_rate_per_second: float):
        self.capacity = float(max(1, capacity))
        self.tokens = float(max(1, capacity))
        self.refill_rate_per_second = float(max(0.1, refill_rate_per_second))
        self.last_refill_timestamp = time.monotonic()
        self._lock = threading.Lock()
        logger.info(f"TokenBucketRateLimiter initialized with capacity {self.capacity}, refill rate {self.refill_rate_per_second} tps.")

    def _refill_tokens(self):
        now = time.monotonic()
        elapsed_time = now - self.last_refill_timestamp
        if elapsed_time > 0:
            tokens_to_add = elapsed_time * self.refill_rate_per_second
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill_timestamp = now

    def consume(self, tokens_to_consume: int = 1, blocking: bool = True, timeout_seconds: Optional[float] = 5.0) -> bool:
        if tokens_to_consume <= 0:
            return True
        start_time = time.monotonic()
        while True:
            with self._lock:
                self._refill_tokens()
                if self.tokens >= tokens_to_consume:
                    self.tokens -= tokens_to_consume
                    return True
            if not blocking:
                return False
            if timeout_seconds is not None:
                elapsed_wait_time = time.monotonic() - start_time
                remaining_timeout = timeout_seconds - elapsed_wait_time
                if remaining_timeout <= 0:
                    logger.warning(f"RateLimiter: Timeout ({timeout_seconds:.2f}s) exceeded waiting for {tokens_to_consume} tokens. Current tokens: {self.tokens:.2f}")
                    return False
            needed_tokens_to_generate = tokens_to_consume - self.tokens
            if needed_tokens_to_generate <=0 :
                 needed_tokens_to_generate = 1
            estimated_wait_for_needed_tokens = needed_tokens_to_generate / self.refill_rate_per_second
            sleep_interval = min(0.05, estimated_wait_for_needed_tokens / 2 if estimated_wait_for_needed_tokens > 0 else 0.05)
            if sleep_interval <=0: sleep_interval = 0.01
            if remaining_timeout is not None and remaining_timeout < sleep_interval:
                sleep_interval = remaining_timeout
            time.sleep(sleep_interval)


class IBClientWrapper:
    def __init__(self, eclient: EClient, wrapper: IBWrapperImpl, config: IBKRConfig):
        self.client: EClient = eclient
        self.wrapper: IBWrapperImpl = wrapper
        self.config: IBKRConfig = config
        self.active_market_data_reqs: Dict[int, Any] = {}
        self.active_realtime_bars_reqs: Dict[int, Any] = {}

        self.rate_limiter = TokenBucketRateLimiter(
            capacity=config.max_requests_per_second,
            refill_rate_per_second=float(config.max_requests_per_second)
        )
        self.async_request_semaphore = asyncio.Semaphore(self.config.max_concurrent_api_requests)
        logger.info(f"IBClientWrapper: Initialized asyncio.Semaphore with count {self.config.max_concurrent_api_requests}")
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._setup_async_loop()

    def _setup_async_loop(self):
        if IBClientWrapper._instance_count == 0:
            try:
                self.loop = asyncio.get_event_loop_policy().get_event_loop()
                if self.loop.is_running():
                    logger.info("IBClientWrapper: Using existing running event loop.")
                else:
                    logger.info("IBClientWrapper: No running event loop found, starting a dedicated thread.")
                    self._start_loop_in_thread()
            except RuntimeError:
                self._start_loop_in_thread()
        IBClientWrapper._instance_count +=1

    def _start_loop_in_thread(self):
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, name="IBClientAsyncLoop", daemon=True)
        self._loop_thread.start()
        logger.info("IBClientWrapper: Dedicated asyncio event loop started in thread.")

    def _run_loop(self):
        if not self.loop:
            logger.error("IBClientWrapper: Event loop not initialized for _run_loop.")
            return
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()
            logger.info("IBClientWrapper: Asyncio event loop closed.")

    def shutdown_async_loop(self):
        IBClientWrapper._instance_count -=1
        if IBClientWrapper._instance_count == 0 and self.loop and self.loop.is_running():
            logger.info("IBClientWrapper: Requesting asyncio event loop to stop.")
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=5)
                if self._loop_thread.is_alive():
                    logger.warning("IBClientWrapper: Asyncio loop thread did not terminate gracefully.")
        elif self.loop and not self.loop.is_running() and self._loop_thread and self._loop_thread.is_alive():
            if self._loop_thread and self._loop_thread.is_alive():
                 self._loop_thread.join(timeout=1)
    _instance_count = 0

    def create_ib_contract(self, internal_order: InternalOrderRequest) -> Contract:
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
            if strike is not None: contract.strike = float(strike)
            else: raise ValueError(f"Strike price is required for options (symbol: {contract.symbol})")
            right = internal_order.get("right")
            if right and str(right).upper() in ["C", "P", "CALL", "PUT"]: contract.right = str(right).upper()[0]
            else: raise ValueError(f"Valid right ('C' or 'P') is required for options (symbol: {contract.symbol})")
        if contract.secType == "CASH":
            contract.exchange = "IDEALPRO"
            if '.' in contract.symbol:
                parts = contract.symbol.split('.')
                if len(parts) == 2: contract.symbol = parts[0].upper(); contract.currency = parts[1].upper()
        logger.debug(f"Created IB Contract: Symbol={contract.symbol}, SecType={contract.secType}, Exchange={contract.exchange}, Currency={contract.currency}, LastTradeDate={contract.lastTradeDateOrContractMonth}, Strike={contract.strike}, Right={contract.right}, Multiplier={contract.multiplier}, PrimaryExch={contract.primaryExchange}")
        return contract

    def create_ib_order(self, internal_order: InternalOrderRequest, ib_order_id: int) -> Order:
        order = Order()
        order.orderId = ib_order_id
        order.action = str(internal_order.get("side", "")).upper()
        quantity = internal_order.get("quantity")
        if quantity is None or float(quantity) <= 0: raise ValueError(f"Invalid or missing quantity for order: {quantity}")
        order.totalQuantity = float(quantity)
        order.orderType = str(internal_order.get("order_type", "")).upper()
        order.tif = str(internal_order.get("time_in_force", "DAY")).upper()
        if order.orderType in ["LMT", "STP LMT"]:
            limit_price = internal_order.get("limit_price")
            if limit_price is None: raise ValueError(f"Limit price required for {order.orderType} order.")
            order.lmtPrice = float(limit_price)
        if order.orderType in ["STP", "STP LMT"]:
            stop_price = internal_order.get("stop_price")
            if stop_price is None: raise ValueError(f"Stop price required for {order.orderType} order.")
            order.auxPrice = float(stop_price)
        if order.orderType == "TRAIL":
            if internal_order.get("trailing_percent") is not None:
                order.trailingPercent = float(internal_order["trailing_percent"])
                if internal_order.get("limit_offset") is not None:
                     if internal_order.get("limit_price") is not None: order.lmtPrice = float(internal_order.get("limit_price"))
            elif internal_order.get("trailing_amount") is not None:
                order.auxPrice = float(internal_order["trailing_amount"])
            else: raise ValueError("Trailing percent or trailing amount required for TRAIL order offset.")
            if internal_order.get("trail_stop_price") is not None: order.trailStopPrice = float(internal_order["trail_stop_price"])
            if order.orderType == "TRAILLIMIT" and internal_order.get("limit_price") is not None: order.lmtPrice = float(internal_order.get("limit_price"))
        order.transmit = True
        account_to_use = internal_order.get("account_id") or self.config.account_code
        if account_to_use: order.account = str(account_to_use)
        logger.debug(f"Created IB Order: Id={order.orderId}, Account='{order.account}', Action='{order.action}', Type='{order.orderType}', Qty={order.totalQuantity}, LmtPrc={order.lmtPrice}, AuxPrc={order.auxPrice}, Trail%={getattr(order, 'trailingPercent', 'N/A')}, TrailStopPrc={getattr(order, 'trailStopPrice', 'N/A')}")
        return order

    @async_retry_on_ib_error(max_attempts=3, initial_backoff_seconds=0.5, max_backoff_seconds=3.0, retryable_error_codes=RETRYABLE_IB_ERROR_CODES)
    async def _resolve_contract_details_async(self, contract_to_resolve: Contract, req_id: int) -> Optional[List[ContractDetails]]:
        await self.async_request_semaphore.acquire()
        try:
            if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
                raise IBConnectionError("API not ready when trying to resolve contract details.")
            logger.info(f"Requesting contract details: reqId={req_id}, Symbol='{contract_to_resolve.symbol}', SecType='{contract_to_resolve.secType}'")
            async_event = asyncio.Event()
            with self.wrapper._contract_details_lock:
                self.wrapper._contract_details_results[req_id] = []
                self.wrapper._contract_details_events[req_id] = async_event
                if req_id in self.wrapper._request_errors: self.wrapper._request_errors.pop(req_id)
            self.client.reqContractDetails(req_id, contract_to_resolve)
            await async_event.wait()
            if req_id in self.wrapper._request_errors:
                ib_error = self.wrapper._request_errors.pop(req_id)
                with self.wrapper._contract_details_lock:
                    self.wrapper._contract_details_results.pop(req_id, None)
                    self.wrapper._contract_details_events.pop(req_id, None)
                raise ib_error
            with self.wrapper._contract_details_lock:
                resolved_details_list = list(self.wrapper._contract_details_results.pop(req_id, []))
                self.wrapper._contract_details_events.pop(req_id, None)
            if not resolved_details_list:
                logger.warning(f"Contract details resolution for reqId {req_id} ({contract_to_resolve.symbol}) completed but returned no details.")
            else:
                logger.info(f"Contract details received: reqId={req_id}, Count={len(resolved_details_list) if resolved_details_list else 0}")
            return resolved_details_list
        finally:
            self.async_request_semaphore.release()

    def resolve_contract_details(self, contract_to_resolve: Contract, timeout_seconds: Optional[int] = None) -> Optional[List[ContractDetails]]:
        effective_timeout = float(timeout_seconds if timeout_seconds is not None else self.config.default_contract_resolution_timeout_seconds)
        if not self.loop or not self.loop.is_running() or not self._loop_thread or not self._loop_thread.is_alive():
            logger.error("Asyncio event loop is not running. Cannot resolve contract details.")
            raise IBConnectionError("Asyncio loop not available for contract detail resolution.")
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout):
            msg = f"Rate limit exceeded for resolve_contract_details ({contract_to_resolve.symbol}). Request not sent."
            logger.error(msg); raise RateLimitExceededError(msg)
        req_id = self.wrapper.get_next_request_id()
        future = asyncio.run_coroutine_threadsafe(self._resolve_contract_details_async(contract_to_resolve, req_id), self.loop)
        try:
            return future.result(timeout=effective_timeout + 5.0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for _resolve_contract_details_async (reqId: {req_id}, symbol: {contract_to_resolve.symbol}) to complete. Overall timeout: {effective_timeout + 5.0}s")
            with self.wrapper._contract_details_lock:
                self.wrapper._contract_details_events.pop(req_id, None)
                self.wrapper._contract_details_results.pop(req_id, None)
            self.wrapper._request_errors.pop(req_id, None); return None
        except IBError as e: logger.error(f"IBError during sync call to resolve_contract_details for reqId {req_id}: {e}"); raise
        except Exception as e: logger.error(f"Exception during sync call to resolve_contract_details for reqId {req_id}: {e}", exc_info=True); raise

    def place_or_modify_order(self, contract: Contract, order: Order, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout):
            msg = f"Rate limit exceeded for place_or_modify_order (ID: {order.orderId}, timeout: {effective_timeout}s). Order not sent."
            logger.error(msg); raise RateLimitExceededError(msg)
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            msg = f"API not ready for order placement/modification (ID: {order.orderId})."
            logger.error(msg); raise IBConnectionError(msg)
        logger.info(f"Submitting Place/Modify Order: IBOrderID={order.orderId}, Account='{order.account}', Action='{order.action}', Type='{order.orderType}', Qty={order.totalQuantity} for Symbol='{contract.symbol}', ConID={contract.conId if contract.conId else 'N/A'}")
        self.client.placeOrder(order.orderId, contract, order)

    def cancel_order(self, ib_order_id: int, manual_cancel_order_time: str = "", req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout):
            msg = f"Rate limit exceeded for cancel_order (ID: {ib_order_id}, timeout: {effective_timeout}s). Request not sent."
            logger.error(msg); raise RateLimitExceededError(msg)
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            msg = f"API not ready for order cancellation (ID: {ib_order_id})."
            logger.error(msg); raise IBConnectionError(msg)
        logger.info(f"Requesting Cancel Order: IBOrderID={ib_order_id}")
        self.client.cancelOrder(ib_order_id, manual_cancel_order_time)

    def request_open_orders(self, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for reqOpenOrders (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise IBConnectionError("API not ready for reqOpenOrders.")
        logger.info("Requesting client-specific open orders (reqOpenOrders).")
        self.client.reqOpenOrders()

    def request_all_open_orders(self, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for reqAllOpenOrders (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise IBConnectionError("API not ready for reqAllOpenOrders.")
        logger.info("Requesting all open orders for the account (reqAllOpenOrders).")
        self.client.reqAllOpenOrders()

    def request_auto_open_orders(self, auto_bind: bool, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for reqAutoOpenOrders (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise IBConnectionError("API not ready for reqAutoOpenOrders.")
        logger.info(f"Requesting auto open orders bind: {auto_bind}")
        self.client.reqAutoOpenOrders(auto_bind)

    def request_executions(self, exec_filter_dict: Optional[Dict[str, Any]] = None, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_account_data_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for reqExecutions (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready(): raise IBConnectionError("API not ready for requesting executions.")
        req_id = self.wrapper.get_next_request_id()
        exec_filter = ExecutionFilter()
        if exec_filter_dict:
            if exec_filter_dict.get("clientId") is not None: exec_filter.clientId = int(exec_filter_dict["clientId"])
            if exec_filter_dict.get("acctCode"): exec_filter.acctCode = str(exec_filter_dict["acctCode"])
            if exec_filter_dict.get("time"): exec_filter.time = str(exec_filter_dict["time"])
            if exec_filter_dict.get("symbol"): exec_filter.symbol = str(exec_filter_dict["symbol"])
            if exec_filter_dict.get("secType"): exec_filter.secType = str(exec_filter_dict["secType"])
            if exec_filter_dict.get("exchange"): exec_filter.exchange = str(exec_filter_dict["exchange"])
            if exec_filter_dict.get("side"): exec_filter.side = str(exec_filter_dict["side"])
        logger.info(f"Requesting executions (reqId: {req_id}) with filter: ClientId={exec_filter.clientId}, Acct={exec_filter.acctCode}, Time={exec_filter.time}, Sym={exec_filter.symbol}, SecType={exec_filter.secType}, Exch={exec_filter.exchange}, Side={exec_filter.side}")
        self.client.reqExecutions(req_id, exec_filter)

    def request_account_summary_sync(self, timeout_seconds: Optional[int] = None, group_name: str = "All", tags: str = "$AccountSummary:AccountType,NetLiquidation,TotalCashValue,SettledCash,BuyingPower,GrossPositionValue") -> Optional[Dict[str, Any]]:
        effective_timeout = float(timeout_seconds if timeout_seconds is not None else self.config.default_account_data_timeout_seconds)
        if not self.loop or not self.loop.is_running() or not self._loop_thread or not self._loop_thread.is_alive():
            logger.error("Asyncio event loop is not running. Cannot request account summary.")
            raise IBConnectionError("Asyncio loop not available for account summary.")
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout):
             raise RateLimitExceededError(f"Rate limit exceeded for request_account_summary_sync (group: {group_name}, timeout: {effective_timeout}s).")
        req_id = self.wrapper.get_next_request_id()
        future = asyncio.run_coroutine_threadsafe(self._request_account_summary_async(req_id, group_name, tags), self.loop)
        try: return future.result(timeout=effective_timeout + 5.0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for _request_account_summary_async (reqId: {req_id}) to complete. Overall timeout: {effective_timeout + 5.0}s")
            with self.wrapper._account_summary_lock:
                self.wrapper._account_summary_events.pop(req_id, None); self.wrapper._account_summary_results.pop(req_id, None)
            self.wrapper._request_errors.pop(req_id, None); self.client.cancelAccountSummary(req_id); return None
        except IBError as e: logger.error(f"IBError during sync request_account_summary_sync for reqId {req_id}: {e}"); raise
        except Exception as e: logger.error(f"Exception during sync request_account_summary_sync for reqId {req_id}: {e}", exc_info=True); raise

    @async_retry_on_ib_error(max_attempts=3, initial_backoff_seconds=0.5, max_backoff_seconds=3.0, retryable_error_codes=RETRYABLE_IB_ERROR_CODES)
    async def _request_account_summary_async(self, req_id: int, group_name: str, tags: str) -> Optional[Dict[str, Any]]:
        await self.async_request_semaphore.acquire()
        try:
            if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
                raise IBConnectionError("API not ready when trying to request account summary.")
            logger.info(f"Requesting account summary: reqId={req_id}, Group='{group_name}', Tags='{tags}'")
            async_event = asyncio.Event()
            with self.wrapper._account_summary_lock:
                self.wrapper._account_summary_events[req_id] = async_event
                self.wrapper._account_summary_results[req_id] = {"account": None, "summary_values": {}}
                if req_id in self.wrapper._request_errors: self.wrapper._request_errors.pop(req_id)
            self.client.reqAccountSummary(req_id, group_name, tags)
            await async_event.wait()
            if req_id in self.wrapper._request_errors:
                ib_error = self.wrapper._request_errors.pop(req_id)
                with self.wrapper._account_summary_lock:
                    self.wrapper._account_summary_events.pop(req_id, None); self.wrapper._account_summary_results.pop(req_id, None)
                raise ib_error
            with self.wrapper._account_summary_lock:
                summary_data = self.wrapper._account_summary_results.pop(req_id, None)
                self.wrapper._account_summary_events.pop(req_id, None)
            logger.info(f"Account summary data received: reqId={req_id}, Account='{summary_data.get('account') if summary_data else 'N/A'}'")
            return summary_data
        finally:
            self.async_request_semaphore.release()

    def cancel_account_summary(self, req_id: int, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for cancelAccountSummary (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"Cannot cancel account summary {req_id}: API not ready."); return
        logger.info(f"Cancelling account summary request (reqId: {req_id})")
        self.client.cancelAccountSummary(req_id)
        with self.wrapper._account_summary_lock:
            if req_id in self.wrapper._account_summary_events:
                self.wrapper._account_summary_events[req_id].set(); self.wrapper._account_summary_events.pop(req_id, None)
            self.wrapper._account_summary_results.pop(req_id, None)

    def request_positions_sync(self, timeout_seconds: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.config.default_position_timeout_seconds
        if not self.loop or not self.loop.is_running() or not self._loop_thread or not self._loop_thread.is_alive():
            logger.error("Asyncio event loop is not running. Cannot request positions.")
            raise IBConnectionError("Asyncio loop not available for positions.")
        if not self.rate_limiter.consume(timeout_seconds=float(effective_timeout)):
            raise RateLimitExceededError(f"Rate limit exceeded for reqPositions_sync (timeout: {effective_timeout}s)")
        future = asyncio.run_coroutine_threadsafe(self._request_positions_async(), self.loop)
        try: return future.result(timeout=effective_timeout + 5.0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for _request_positions_async to complete. Overall timeout: {effective_timeout + 5.0}s")
            with self.wrapper._positions_lock:
                if self.wrapper._positions_event and isinstance(self.wrapper._positions_event, asyncio.Event): self.wrapper._positions_event.set()
                self.wrapper._positions_event = None
            self.client.cancelPositions(); return None
        except IBError as e: logger.error(f"IBError during synchronous request_positions_sync: {e}"); raise
        except Exception as e: logger.error(f"Exception during synchronous request_positions_sync: {e}", exc_info=True); raise

    @async_retry_on_ib_error(max_attempts=2, initial_backoff_seconds=1.0, max_backoff_seconds=5.0, retryable_error_codes=RETRYABLE_IB_ERROR_CODES)
    async def _request_positions_async(self) -> Optional[List[Dict[str, Any]]]:
        await self.async_request_semaphore.acquire()
        try:
            if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
                raise IBConnectionError("API not ready when trying to request positions.")
            logger.info("Requesting current positions.")
            async_event = asyncio.Event()
            with self.wrapper._positions_lock:
                if self.wrapper._positions_event is not None and hasattr(self.wrapper._positions_event, 'is_set') and not self.wrapper._positions_event.is_set():
                    logger.warning("An existing positions request might be active. Overwriting event.")
                self.wrapper._positions_event = async_event
                self.wrapper._positions_results = []
            self.client.reqPositions()
            await async_event.wait()
            with self.wrapper._positions_lock:
                position_list = list(self.wrapper._positions_results)
                self.wrapper._positions_event = None
            logger.info(f"Position data received: Count={len(position_list) if position_list else 0}")
            return position_list
        finally:
            self.async_request_semaphore.release()

    def cancel_positions(self, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for cancelPositions (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning("Cannot cancel positions subscription: API not ready."); return
        logger.info("Cancelling positions subscription (cancelPositions).")
        self.client.cancelPositions()
        with self.wrapper._positions_lock:
             if self.wrapper._positions_event:
                self.wrapper._positions_event.set(); self.wrapper._positions_event = None
             self.wrapper._positions_results = []

    def request_pnl_sync(self, account:str, model_code:str = "", con_id:int = 0, timeout_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.config.default_pnl_timeout_seconds
        if not self.loop or not self.loop.is_running() or not self._loop_thread or not self._loop_thread.is_alive():
            logger.error("Asyncio event loop is not running. Cannot request PnL.")
            raise IBConnectionError("Asyncio loop not available for PnL.")
        if not self.rate_limiter.consume(timeout_seconds=float(effective_timeout)):
            raise RateLimitExceededError(f"Rate limit exceeded for request_pnl_sync (timeout: {effective_timeout}s)")
        req_id = self.wrapper.get_next_request_id()
        future = asyncio.run_coroutine_threadsafe(self._request_pnl_async(req_id, account, model_code, con_id), self.loop)
        try: return future.result(timeout=effective_timeout + 5.0)
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for _request_pnl_async (reqId: {req_id}) to complete. Overall timeout: {effective_timeout + 5.0}s")
            with self.wrapper._pnl_lock:
                self.wrapper._pnl_events.pop(req_id, None); self.wrapper._pnl_results.pop(req_id, None)
            self.wrapper._request_errors.pop(req_id, None); self.client.cancelPnL(req_id); return None
        except IBError as e: logger.error(f"IBError during sync request_pnl_sync for reqId {req_id}: {e}"); raise
        except Exception as e: logger.error(f"Exception during sync request_pnl_sync for reqId {req_id}: {e}", exc_info=True); raise

    @async_retry_on_ib_error(max_attempts=3, initial_backoff_seconds=0.5, max_backoff_seconds=3.0, retryable_error_codes=RETRYABLE_IB_ERROR_CODES)
    async def _request_pnl_async(self, req_id: int, account: str, model_code: str, con_id: int) -> Optional[Dict[str, Any]]:
        await self.async_request_semaphore.acquire()
        try:
            if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
                raise IBConnectionError("API not ready when trying to request PnL.")
            logger.info(f"Requesting PnL: reqId={req_id}, Account='{account}', ConID={con_id}, ModelCode='{model_code}'")
            async_event = asyncio.Event()
            with self.wrapper._pnl_lock:
                self.wrapper._pnl_events[req_id] = async_event
                self.wrapper._pnl_results.pop(req_id, None)
                if req_id in self.wrapper._request_errors: self.wrapper._request_errors.pop(req_id)
            self.client.reqPnL(req_id, account, model_code, con_id)
            await async_event.wait()
            if req_id in self.wrapper._request_errors:
                ib_error = self.wrapper._request_errors.pop(req_id)
                with self.wrapper._pnl_lock:
                    self.wrapper._pnl_events.pop(req_id, None); self.wrapper._pnl_results.pop(req_id, None)
                raise ib_error
            with self.wrapper._pnl_lock:
                pnl_data = self.wrapper._pnl_results.pop(req_id, None)
                self.wrapper._pnl_events.pop(req_id, None)
            logger.info(f"PnL data received: reqId={req_id}, DailyPnL={pnl_data.get('dailyPnL') if pnl_data else 'N/A'}")
            return pnl_data
        finally:
            self.async_request_semaphore.release()

    def cancel_pnl(self, req_id:int, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for cancelPnL (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"Cannot cancel PnL {req_id}: API not ready."); return
        logger.info(f"Cancelling PnL request (reqId: {req_id})")
        self.client.cancelPnL(req_id)
        with self.wrapper._pnl_lock:
            if req_id in self.wrapper._pnl_events:
                self.wrapper._pnl_events[req_id].set(); self.wrapper._pnl_events.pop(req_id, None)
            self.wrapper._pnl_results.pop(req_id, None)

    # --- ReqId to Contract Mapping ---
    def get_contract_for_reqid(self, req_id: int) -> Optional[Contract]: # Returns ibapi.contract.Contract
        market_data_sub = self.active_market_data_reqs.get(req_id)
        if market_data_sub:
            return market_data_sub

        realtime_bars_sub = self.active_realtime_bars_reqs.get(req_id)
        if realtime_bars_sub:
            return realtime_bars_sub.get("contract")

        if not market_data_sub and not realtime_bars_sub:
            logger.warning(f"No active contract found for req_id: {req_id}")
        return None

    # --- Placeholder methods for market data and realtime bars subscriptions ---
    def request_market_data_stream(self, contract_obj: Contract, generic_tick_list: str = "", snapshot: bool = False, regulatory_snapshot: bool = False, mkt_data_options: Optional[List[Any]] = None) -> int:
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise IBConnectionError("API not ready for requesting market data stream.")
        req_id = self.wrapper.get_next_request_id()
        logger.info(f"Requesting market data: reqId={req_id}, Symbol='{contract_obj.symbol}', SecType='{contract_obj.secType}'")
        self.active_market_data_reqs[req_id] = contract_obj
        # self.client.reqMktData(req_id, contract_obj, generic_tick_list, snapshot, regulatory_snapshot, mkt_data_options) # Actual call
        logger.debug(f"Placeholder: Called self.client.reqMktData for reqId {req_id}")
        return req_id

    def cancel_market_data_stream(self, req_id: int):
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"API not ready, attempting to cancel market data stream for reqId {req_id} locally.")
        logger.info(f"Cancelling market data: reqId={req_id}")
        self.active_market_data_reqs.pop(req_id, None)
        # self.client.cancelMktData(req_id) # Actual call
        logger.debug(f"Placeholder: Called self.client.cancelMktData for reqId {req_id}")

    def request_realtime_bars_stream(self, contract_obj: Contract, bar_size: int = 5, what_to_show: str = "TRADES", use_rth: bool = True, real_time_bars_options: Optional[List[Any]] = None) -> int:
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise IBConnectionError("API not ready for requesting realtime bars stream.")
        req_id = self.wrapper.get_next_request_id()
        logger.info(f"Requesting real-time bars: reqId={req_id}, Symbol='{contract_obj.symbol}', BarSize='{bar_size}', DataType='{what_to_show}'")
        self.active_realtime_bars_reqs[req_id] = {"contract": contract_obj, "bar_size": bar_size}
        # self.client.reqRealTimeBars(req_id, contract_obj, bar_size, what_to_show, use_rth, real_time_bars_options) # Actual call
        logger.debug(f"Placeholder: Called self.client.reqRealTimeBars for reqId {req_id}")
        return req_id

    def cancel_realtime_bars_stream(self, req_id: int):
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.warning(f"API not ready, attempting to cancel realtime bars stream for reqId {req_id} locally.")
        logger.info(f"Cancelling real-time bars: reqId={req_id}")
        self.active_realtime_bars_reqs.pop(req_id, None)
        # self.client.cancelRealTimeBars(req_id) # Actual call
        logger.debug(f"Placeholder: Called self.client.cancelRealTimeBars for reqId {req_id}")

    def subscribe_account_updates(self, account_code: str, subscribe: bool = True, req_timeout_seconds: Optional[float] = None):
        effective_timeout = req_timeout_seconds if req_timeout_seconds is not None else self.config.default_order_placement_timeout_seconds
        if not self.rate_limiter.consume(timeout_seconds=effective_timeout): raise RateLimitExceededError(f"Rate limit exceeded for reqAccountUpdates (timeout: {effective_timeout}s)")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            raise IBConnectionError("API not ready for account updates subscription.")
        effective_account_code = account_code if account_code else self.config.account_code or ""
        if not effective_account_code:
            raise ValueError("Account code must be specified for account updates subscription.")
        logger.info(f"{'Subscribing to' if subscribe else 'Unsubscribing from'} account updates for {effective_account_code}.")
        self.client.reqAccountUpdates(subscribe, effective_account_code)
