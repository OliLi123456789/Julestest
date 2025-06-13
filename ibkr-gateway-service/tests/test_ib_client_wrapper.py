import unittest
from unittest.mock import MagicMock, patch, ANY, call
import threading
import time

from ibkr_gateway_service.ib_client_wrapper import IBClientWrapper, TokenBucketRateLimiter, RateLimitExceededError
from ibkr_gateway_service.config import IBKRConfig
# from ibkr_gateway_service.ib_wrapper import IBWrapperImpl # Will be mocked
# from ibapi.client import EClient # Will be mocked
# from ibapi.contract import Contract # For isinstance checks or specific attributes
# from ibapi.order import Order # For isinstance checks or specific attributes


# Mock EClient from ibapi, as we don't want to connect to a real IB Gateway
class MockEClient: # Copied from test_connection_manager, can be refactored to a common test util
    def __init__(self, wrapper):
        self.wrapper = wrapper
    # Add mocks for all EClient methods called by IBClientWrapper
    reqContractDetails = MagicMock()
    placeOrder = MagicMock()
    cancelOrder = MagicMock()
    reqAccountSummary = MagicMock()
    cancelAccountSummary = MagicMock()
    reqPositions = MagicMock()
    cancelPositions = MagicMock()
    reqPnL = MagicMock()
    cancelPnL = MagicMock()
    reqMktData = MagicMock()
    cancelMktData = MagicMock()
    # Add any other methods that IBClientWrapper might call


class TestTokenBucketRateLimiter(unittest.TestCase):
    def setUp(self):
        self.rate = 10  # tokens per second
        self.capacity = 20 # bucket capacity
        self.limiter = TokenBucketRateLimiter(rate_per_second=self.rate, capacity=self.capacity)

    def test_initialization(self):
        self.assertEqual(self.limiter.rate_per_second, self.rate)
        self.assertEqual(self.limiter.capacity, self.capacity)
        self.assertEqual(self.limiter._tokens, self.capacity) # Should start full
        self.assertIsNotNone(self.limiter._lock)

    def test_consume_sufficient_tokens(self):
        self.assertTrue(self.limiter.consume(5))
        self.assertEqual(self.limiter._tokens, self.capacity - 5)
        self.assertTrue(self.limiter.consume(self.capacity - 5))
        self.assertEqual(self.limiter._tokens, 0)

    def test_consume_insufficient_tokens_non_blocking(self):
        self.limiter.consume(self.capacity) # Empty the bucket
        self.assertFalse(self.limiter.consume(1, blocking=False))
        self.assertEqual(self.limiter._tokens, 0)

    @patch('time.sleep', return_value=None) # Mock sleep to avoid actual waiting
    @patch('time.time')
    def test_consume_insufficient_tokens_blocking_timeout(self, mock_time, mock_sleep):
        mock_time.side_effect = [0, 0.1, 0.2, 0.3] # Simulate time passing but not enough to refill
        self.limiter._tokens = 0 # Start with empty bucket
        self.limiter.last_refill_time = 0 # Ensure refill is attempted

        self.assertFalse(self.limiter.consume(1, blocking=True, timeout_seconds=0.25))
        self.assertTrue(mock_sleep.called) # Check that it attempted to wait

    @patch('time.sleep', return_value=None)
    @patch('time.time')
    def test_consume_blocking_success_after_refill(self, mock_time, mock_sleep):
        self.limiter._tokens = 0
        # Simulate initial time, then time after sleep that allows for refill
        mock_time.side_effect = [
            0, # Initial last_refill_time
            0.01, # First call to time.time in consume
            0.02, # Second call to time.time in consume (for _refill_tokens)
            0.03, # Third call after potential sleep (still not enough tokens)
            0.04, # Fourth call (still not enough)
            1.0,  # Enough time passed for a full refill (10 tokens)
            1.01  # Next call
        ]
        self.limiter.last_refill_time = 0

        self.assertTrue(self.limiter.consume(5, blocking=True, timeout_seconds=2))
        self.assertEqual(self.limiter._tokens, self.rate - 5) # 10 tokens refilled, 5 consumed

    @patch('time.time')
    def test_refill_logic(self, mock_time):
        self.limiter._tokens = 0
        mock_time.return_value = self.limiter.last_refill_time + 1 # 1 second passed
        self.limiter._refill_tokens()
        self.assertEqual(self.limiter._tokens, self.rate)

        self.limiter._tokens = self.capacity - 1 # Almost full
        mock_time.return_value = self.limiter.last_refill_time + 1
        self.limiter._refill_tokens()
        self.assertEqual(self.limiter._tokens, self.capacity) # Should not exceed capacity

    def test_consume_exact_capacity(self):
        self.assertTrue(self.limiter.consume(self.capacity))
        self.assertEqual(self.limiter._tokens, 0)

    def test_consume_more_than_capacity_non_blocking(self):
        self.assertFalse(self.limiter.consume(self.capacity + 1, blocking=False))
        self.assertEqual(self.limiter._tokens, self.capacity) # Tokens unchanged


class TestIBClientWrapper(unittest.TestCase):

    def setUp(self):
        self.mock_eclient = MagicMock(spec=MockEClient) # Using spec of our MockEClient
        self.mock_wrapper = MagicMock(name="IBWrapperImplMock")
        self.mock_config = MagicMock(spec=IBKRConfig)
        self.mock_config.max_requests_per_second = 10
        self.mock_config.account_code = "U123Test"

        # Mock ConnectionManager for is_api_ready check
        self.mock_conn_manager = MagicMock(name="ConnectionManagerMock")
        self.mock_wrapper.conn_manager = self.mock_conn_manager # IBWrapper has a conn_manager attribute

        self.client_wrapper = IBClientWrapper(
            eclient=self.mock_eclient,
            wrapper=self.mock_wrapper,
            config=self.mock_config
        )

    # 1. Initialization
    def test_init(self):
        self.assertEqual(self.client_wrapper.client, self.mock_eclient)
        self.assertEqual(self.client_wrapper.wrapper, self.mock_wrapper)
        self.assertEqual(self.client_wrapper.config, self.mock_config)
        self.assertEqual(self.client_wrapper._request_id_counter, 0)
        self.assertIsNotNone(self.client_wrapper._req_id_lock)
        self.assertIsInstance(self.client_wrapper.rate_limiter, TokenBucketRateLimiter)
        self.assertEqual(self.client_wrapper.rate_limiter.rate_per_second, 10)

    # 2. _get_next_req_id
    def test_get_next_req_id(self):
        # Test with a lock mock to ensure it's used, though true thread safety isn't tested here.
        with patch.object(self.client_wrapper, '_req_id_lock', MagicMock(spec=threading.Lock)) as mock_lock:
            id1 = self.client_wrapper._get_next_req_id()
            id2 = self.client_wrapper._get_next_req_id()
            self.assertEqual(id1, 1)
            self.assertEqual(id2, 2)
            self.assertEqual(self.client_wrapper._request_id_counter, 2)
            self.assertEqual(mock_lock.__enter__.call_count, 2)
            self.assertEqual(mock_lock.__exit__.call_count, 2)


    # 3. create_ib_contract
    def test_create_ib_contract_stock(self):
        req = {"symbol": "AAPL", "secType": "STK", "exchange": "SMART", "currency": "USD", "primaryExchange": "NASDAQ"}
        contract = self.client_wrapper.create_ib_contract(req)
        self.assertEqual(contract.symbol, "AAPL")
        self.assertEqual(contract.secType, "STK")
        self.assertEqual(contract.exchange, "SMART")
        self.assertEqual(contract.currency, "USD")
        self.assertEqual(contract.primaryExchange, "NASDAQ")

    def test_create_ib_contract_option(self):
        req = {"symbol": "GOOG", "secType": "OPT", "exchange": "SMART", "currency": "USD",
               "lastTradeDateOrContractMonth": "20240119", "strike": 150.0, "right": "C", "multiplier": "100"}
        contract = self.client_wrapper.create_ib_contract(req)
        self.assertEqual(contract.symbol, "GOOG")
        self.assertEqual(contract.secType, "OPT")
        self.assertEqual(contract.lastTradeDateOrContractMonth, "20240119")
        self.assertEqual(contract.strike, 150.0)
        self.assertEqual(contract.right, "C")
        self.assertEqual(contract.multiplier, "100")

    def test_create_ib_contract_option_default_multiplier(self):
        req = {"symbol": "MSFT", "secType": "OPT", "exchange": "SMART", "currency": "USD",
               "lastTradeDateOrContractMonth": "20240315", "strike": 300.0, "right": "P"}
        contract = self.client_wrapper.create_ib_contract(req)
        self.assertEqual(contract.multiplier, "100") # Default

    def test_create_ib_contract_cash(self):
        req = {"symbol": "EUR.USD", "secType": "CASH", "currency": "USD"} # Exchange should be IDEALPRO
        contract = self.client_wrapper.create_ib_contract(req)
        self.assertEqual(contract.symbol, "EUR") # Base currency
        self.assertEqual(contract.secType, "CASH")
        self.assertEqual(contract.exchange, "IDEALPRO")
        self.assertEqual(contract.currency, "USD") # Quote currency

    def test_create_ib_contract_future(self):
        req = {"symbol": "ES", "secType": "FUT", "exchange": "CME", "currency": "USD",
               "lastTradeDateOrContractMonth": "202312", "multiplier": "50"}
        contract = self.client_wrapper.create_ib_contract(req)
        self.assertEqual(contract.symbol, "ES")
        self.assertEqual(contract.secType, "FUT")
        self.assertEqual(contract.lastTradeDateOrContractMonth, "202312")
        self.assertEqual(contract.multiplier, "50")

    def test_create_ib_contract_option_missing_fields(self):
        req = {"symbol": "SPY", "secType": "OPT", "exchange": "SMART", "currency": "USD"} # Missing strike/right
        with self.assertRaises(ValueError):
            self.client_wrapper.create_ib_contract(req)

    # 4. create_ib_order
    def test_create_ib_order_market(self):
        req = {"action": "BUY", "quantity": 100, "order_type": "MARKET", "tif": "DAY", "account": "U123"}
        order = self.client_wrapper.create_ib_order(0, req) # orderId 0 for new order
        self.assertEqual(order.action, "BUY")
        self.assertEqual(order.totalQuantity, 100)
        self.assertEqual(order.orderType, "MKT")
        self.assertEqual(order.tif, "DAY")
        self.assertEqual(order.account, "U123")

    def test_create_ib_order_limit(self):
        req = {"action": "SELL", "quantity": 50, "order_type": "LIMIT", "limit_price": 200.50, "tif": "GTC"}
        order = self.client_wrapper.create_ib_order(0, req)
        self.assertEqual(order.action, "SELL")
        self.assertEqual(order.totalQuantity, 50)
        self.assertEqual(order.orderType, "LMT")
        self.assertEqual(order.lmtPrice, 200.50)
        self.assertEqual(order.tif, "GTC")
        self.assertEqual(order.account, self.mock_config.account_code) # Default account

    def test_create_ib_order_stop(self):
        req = {"action": "BUY", "quantity": 10, "order_type": "STOP", "stop_price": 50.0}
        order = self.client_wrapper.create_ib_order(0, req)
        self.assertEqual(order.orderType, "STP")
        self.assertEqual(order.auxPrice, 50.0)

    def test_create_ib_order_trail(self):
        req = {"action": "SELL", "quantity": 5, "order_type": "TRAIL",
               "trailing_percent": 1.5, "trail_stop_price": 190.0}
        order = self.client_wrapper.create_ib_order(0, req)
        self.assertEqual(order.orderType, "TRAIL")
        self.assertEqual(order.trailingPercent, 1.5)
        self.assertEqual(order.trailStopPrice, 190.0)

    def test_create_ib_order_invalid_quantity(self):
        req = {"action": "BUY", "quantity": 0, "order_type": "MARKET"}
        with self.assertRaises(ValueError):
            self.client_wrapper.create_ib_order(0, req)

    def test_create_ib_order_limit_missing_price(self):
        req = {"action": "BUY", "quantity": 100, "order_type": "LIMIT"}
        with self.assertRaises(ValueError):
            self.client_wrapper.create_ib_order(0, req)

    # 6. API Calling Methods (Example: resolve_contract_details)
    @patch('threading.Event') # Mock the Event class itself
    def test_resolve_contract_details_success(self, MockEvent):
        mock_event_instance = MockEvent.return_value # This is the instance of the event
        mock_event_instance.wait.return_value = True # Simulate event being set (success)

        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=True)
        self.mock_conn_manager.is_api_ready.return_value = True

        mock_contract_to_resolve = MagicMock() # Assume this is a valid Contract object
        # Simulate result being populated by wrapper
        req_id_expected = self.client_wrapper._request_id_counter + 1
        self.mock_wrapper._contract_details_results = {req_id_expected: ["details_obj_1"]}

        details = self.client_wrapper.resolve_contract_details(req_id_expected, mock_contract_to_resolve)

        self.mock_eclient.reqContractDetails.assert_called_once_with(req_id_expected, mock_contract_to_resolve)
        mock_event_instance.wait.assert_called_with(timeout=self.client_wrapper.DEFAULT_REQUEST_TIMEOUT)
        self.assertEqual(details, ["details_obj_1"])
        self.assertNotIn(req_id_expected, self.mock_wrapper._contract_details_events) # Check cleanup
        self.assertNotIn(req_id_expected, self.mock_wrapper._contract_details_results)


    @patch('threading.Event')
    def test_resolve_contract_details_timeout(self, MockEvent):
        mock_event_instance = MockEvent.return_value
        mock_event_instance.wait.return_value = False # Simulate timeout

        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=True)
        self.mock_conn_manager.is_api_ready.return_value = True
        mock_contract_to_resolve = MagicMock()
        req_id_expected = self.client_wrapper._request_id_counter + 1

        with self.assertLogs(self.client_wrapper.logger, level='WARNING') as log_cm:
            details = self.client_wrapper.resolve_contract_details(req_id_expected, mock_contract_to_resolve)

        self.mock_eclient.reqContractDetails.assert_called_once_with(req_id_expected, mock_contract_to_resolve)
        self.assertIsNone(details)
        self.assertTrue(any(f"Timeout waiting for contractDetails for reqId={req_id_expected}" in rec.getMessage() for rec in log_cm.records))
        # self.mock_eclient.cancelContractDetails was not defined in mock, but would be called if existed.
        # For now, we just check cleanup.
        self.assertNotIn(req_id_expected, self.mock_wrapper._contract_details_events)
        self.assertNotIn(req_id_expected, self.mock_wrapper._contract_details_results)

    def test_api_call_rate_limited(self):
        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=False) # Simulate rate limit hit
        self.mock_conn_manager.is_api_ready.return_value = True
        mock_contract_to_resolve = MagicMock()

        with self.assertRaises(RateLimitExceededError):
            self.client_wrapper.resolve_contract_details(1, mock_contract_to_resolve)
        self.mock_eclient.reqContractDetails.assert_not_called()

    def test_api_call_not_ready(self):
        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=True)
        self.mock_conn_manager.is_api_ready.return_value = False # Simulate API not ready
        mock_contract_to_resolve = MagicMock()

        with self.assertRaises(ConnectionError): # Assuming it raises ConnectionError
            self.client_wrapper.resolve_contract_details(1, mock_contract_to_resolve)
        self.mock_eclient.reqContractDetails.assert_not_called()

    # Test place_or_modify_order
    def test_place_or_modify_order(self):
        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=True)
        self.mock_conn_manager.is_api_ready.return_value = True
        mock_order_obj = MagicMock() # ibapi.order.Order
        mock_contract_obj = MagicMock() # ibapi.contract.Contract

        self.client_wrapper.place_or_modify_order(123, mock_contract_obj, mock_order_obj)
        self.mock_eclient.placeOrder.assert_called_once_with(123, mock_contract_obj, mock_order_obj)

    # Test cancel_order
    def test_cancel_order(self):
        self.client_wrapper.rate_limiter.consume = MagicMock(return_value=True)
        self.mock_conn_manager.is_api_ready.return_value = True

        self.client_wrapper.cancel_order(123, "") # manualOrderCancelTime not used by current impl.
        self.mock_eclient.cancelOrder.assert_called_once_with(123, "")


if __name__ == '__main__':
    unittest.main()
