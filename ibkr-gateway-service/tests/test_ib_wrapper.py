import unittest
from unittest.mock import MagicMock, patch, call
import time
import threading # For events and locks

# Assuming IBWrapperImpl is in the parent directory or PYTHONPATH is set up correctly
from ibkr_gateway_service.ib_wrapper import IBWrapperImpl

# Mock actual IB API objects if they are complex or not easily instantiated
# For simple attribute access, MagicMock can often suffice.
# from ibapi.contract import Contract # If needed for isinstance checks, etc.
# from ibapi.order import Order
# from ibapi.execution import Execution
# from ibapi.commission_report import CommissionReport
# from ibapi.contract import ContractDetails


class TestIBWrapperImpl(unittest.TestCase):

    def setUp(self):
        self.wrapper = IBWrapperImpl()
        self.mock_conn_manager = MagicMock()
        # Mock events that ConnectionManager would have
        self.mock_conn_manager._next_valid_id_event = MagicMock(spec=threading.Event)
        self.wrapper.set_connection_manager(self.mock_conn_manager)

        # Patch time.time for predictable timestamps in _update_last_api_activity_time
        self.mock_time_patcher = patch('time.time', return_value=12345.6789)
        self.mock_time = self.mock_time_patcher.start()

    def tearDown(self):
        self.mock_time_patcher.stop()

    def assert_last_api_activity_updated(self):
        self.assertEqual(self.wrapper.last_api_activity_time, 12345.6789)

    # 1. Initialization Tests
    def test_init(self):
        wrapper = IBWrapperImpl() # Test fresh instance
        self.assertIsNone(wrapper.conn_manager)
        self.assertEqual(wrapper.order_status_queue, [])
        self.assertEqual(wrapper.exec_details_queue, [])
        self.assertEqual(wrapper.portfolio_updates_queue, [])
        self.assertEqual(wrapper.error_messages_queue, [])
        self.assertEqual(wrapper.streaming_account_value_queue, [])
        self.assertEqual(wrapper.commission_reports_cache, {})
        self.assertIsNone(wrapper._next_valid_order_id)
        self.assertIsNotNone(wrapper._next_order_id_lock)
        self.assertIsNotNone(wrapper.commission_reports_cache_lock)
        self.assertIsNotNone(wrapper.last_api_activity_time) # Initialized to time.time()

        # For event/result dicts used in synchronous-like patterns
        self.assertEqual(wrapper._contract_details_results, {})
        self.assertEqual(wrapper._contract_details_events, {})
        self.assertIsNotNone(wrapper._contract_details_lock)
        self.assertEqual(wrapper._account_summary_results, {})
        self.assertEqual(wrapper._account_summary_events, {})
        self.assertIsNotNone(wrapper._account_summary_lock)
        self.assertEqual(wrapper._pnl_results, {})
        self.assertEqual(wrapper._pnl_events, {})
        self.assertIsNotNone(wrapper._pnl_lock)
        self.assertEqual(wrapper._positions_results, [])
        self.assertIsNone(wrapper._positions_event)
        self.assertIsNotNone(wrapper._positions_lock)


    def test_set_connection_manager(self):
        wrapper = IBWrapperImpl()
        mock_mgr = MagicMock()
        wrapper.set_connection_manager(mock_mgr)
        self.assertEqual(wrapper.conn_manager, mock_mgr)

    # 2. Callback Methods - Core Functionality
    def test_nextValidId(self):
        self.wrapper.nextValidId(orderId=123)
        self.mock_conn_manager.signal_api_ready.assert_called_once()
        self.assertEqual(self.wrapper._next_valid_order_id, 123)
        self.assert_last_api_activity_updated()

    def test_connectionClosed(self):
        self.wrapper.connectionClosed()
        self.mock_conn_manager.signal_connection_lost.assert_called_once()
        # _update_last_api_activity_time is NOT called by EWrapper.connectionClosed() itself
        # self.assert_last_api_activity_updated() # No, this is not called in base EWrapper

    def test_error_socket_disconnect(self):
        # Test a socket disconnect code (e.g., 502)
        self.wrapper.error(reqId=-1, errorCode=502, errorString="Cannot connect")
        self.mock_conn_manager.signal_connection_lost.assert_called_once()
        self.assertTrue(any(e["errorCode"] == 502 for e in self.wrapper.error_messages_queue)) # Should still queue
        self.assert_last_api_activity_updated()

    def test_error_session_issue(self):
        # Test a session issue code (e.g., 501)
        self.wrapper.error(reqId=-1, errorCode=501, errorString="Already connected")
        self.mock_conn_manager.signal_connection_lost.assert_called_once()
        self.assertTrue(any(e["errorCode"] == 501 for e in self.wrapper.error_messages_queue)) # Should still queue
        self.assert_last_api_activity_updated()

    def test_error_critical_post_connect_before_nextvalidid(self):
        self.mock_conn_manager._next_valid_id_event.is_set.return_value = False
        self.wrapper.error(reqId=-1, errorCode=506, errorString="Unsupported TWS") # 506 is in CRITICAL_POST_CONNECT_ERROR_CODES
        self.mock_conn_manager.signal_connection_lost.assert_called_once() # Falls back to this
        self.mock_conn_manager.signal_critical_post_connect_error.assert_not_called()
        # self.assertFalse(any(e["errorCode"] == 506 for e in self.wrapper.error_messages_queue)) # Not queued if fatal signal
        self.assert_last_api_activity_updated()

    def test_error_critical_post_connect_after_nextvalidid(self):
        self.mock_conn_manager._next_valid_id_event.is_set.return_value = True
        self.wrapper.error(reqId=-1, errorCode=530, errorString="Login failed") # 530 is in CRITICAL_POST_CONNECT_ERROR_CODES
        self.mock_conn_manager.signal_critical_post_connect_error.assert_called_once_with(530, "Login failed")
        self.mock_conn_manager.signal_connection_lost.assert_not_called()
        # self.assertFalse(any(e["errorCode"] == 530 for e in self.wrapper.error_messages_queue)) # Not queued if fatal signal
        self.assert_last_api_activity_updated()

    def test_error_info_code(self):
        # Test an info code (e.g., 2104)
        self.wrapper.error(reqId=-1, errorCode=2104, errorString="Market data farm OK")
        self.mock_conn_manager.signal_connection_lost.assert_not_called()
        self.mock_conn_manager.signal_critical_post_connect_error.assert_not_called()
        self.assertTrue(any(e["errorCode"] == 2104 and e["type"] == "info" for e in self.wrapper.error_messages_queue))
        self.assert_last_api_activity_updated()

    def test_error_warning_code(self):
        # Test a warning code (e.g., 2100)
        self.wrapper.error(reqId=1, errorCode=2100, errorString="Subscription issue")
        self.mock_conn_manager.signal_connection_lost.assert_not_called()
        self.assertTrue(any(e["errorCode"] == 2100 and e["type"] == "warning" for e in self.wrapper.error_messages_queue))
        self.assert_last_api_activity_updated()

    def test_error_request_specific(self):
        # Test a request-specific error code (e.g., 321)
        self.wrapper.error(reqId=123, errorCode=321, errorString="Invalid order")
        self.mock_conn_manager.signal_connection_lost.assert_not_called()
        self.assertTrue(any(e["errorCode"] == 321 and e["reqId"] == 123 and e["type"] == "error" for e in self.wrapper.error_messages_queue))
        self.assert_last_api_activity_updated()

    def test_orderStatus(self):
        self.wrapper.orderStatus(orderId=1, status="Filled", filled=10.0, remaining=0.0, avgFillPrice=150.0,
                                permId=987, parentId=0, lastFillPrice=150.0, clientId=1, whyHeld="", mktCapPrice=0.0)
        self.assertEqual(len(self.wrapper.order_status_queue), 1)
        status_event = self.wrapper.order_status_queue[0]
        self.assertEqual(status_event["orderId"], 1)
        self.assertEqual(status_event["status"], "Filled")
        self.assert_last_api_activity_updated()

    def test_openOrder(self):
        # openOrder mainly logs, doesn't queue by current design
        mock_contract = MagicMock()
        mock_contract.symbol = "AAPL"
        mock_order = MagicMock()
        mock_order.action = "BUY"
        mock_order.orderType = "LMT"
        mock_order.totalQuantity = 100
        mock_order_state = MagicMock()
        mock_order_state.status = "Submitted"

        with patch.object(self.wrapper.logger, 'info') as mock_log_info:
            self.wrapper.openOrder(orderId=2, contract=mock_contract, order=mock_order, orderState=mock_order_state)
            mock_log_info.assert_called_once() # Check it logged something
        self.assert_last_api_activity_updated()

    def test_execDetails(self):
        mock_contract = MagicMock(symbol="MSFT")
        mock_execution = MagicMock(orderId=3, execId="exec001")
        self.wrapper.execDetails(reqId=1, contract=mock_contract, execution=mock_execution)
        self.assertEqual(len(self.wrapper.exec_details_queue), 1)
        exec_detail_item = self.wrapper.exec_details_queue[0]
        self.assertEqual(exec_detail_item["contract_obj"].symbol, "MSFT")
        self.assertEqual(exec_detail_item["execution_obj"].execId, "exec001")
        self.assert_last_api_activity_updated()

    def test_commissionReport(self):
        mock_commission_report = MagicMock(execId="exec001", commission=5.0, currency="USD")
        with self.wrapper.commission_reports_cache_lock: # Lock is used inside method
            self.wrapper.commissionReport(commissionReport=mock_commission_report)

        self.assertIn("exec001", self.wrapper.commission_reports_cache)
        self.assertEqual(self.wrapper.commission_reports_cache["exec001"].commission, 5.0)
        self.assert_last_api_activity_updated()

    def test_updateAccountValue(self):
        self.wrapper.updateAccountValue(key="TotalCashValue", val="100000", currency="USD", accountName="U123")
        self.assertEqual(len(self.wrapper.streaming_account_value_queue), 1)
        acc_val_event = self.wrapper.streaming_account_value_queue[0]
        self.assertEqual(acc_val_event["type"], "AccountValueUpdate")
        self.assertEqual(acc_val_event["key"], "TotalCashValue")
        self.assertEqual(acc_val_event["val"], "100000")
        self.assert_last_api_activity_updated()

    def test_updatePortfolio(self):
        mock_contract = MagicMock(symbol="GOOG")
        self.wrapper.updatePortfolio(contract=mock_contract, position=10, marketPrice=2000, marketValue=20000,
                                    averageCost=1900, unrealizedPNL=1000, realizedPNL=0, accountName="U123")
        self.assertEqual(len(self.wrapper.portfolio_updates_queue), 1)
        port_event = self.wrapper.portfolio_updates_queue[0]
        self.assertEqual(port_event["contract_obj"].symbol, "GOOG")
        self.assertEqual(port_event["position"], 10)
        self.assert_last_api_activity_updated()

    def test_accountSummary_synchronous(self):
        mock_event = MagicMock(spec=threading.Event)
        self.wrapper._account_summary_events[123] = mock_event # Simulate active request

        self.wrapper.accountSummary(reqId=123, account="U123", tag="NetLiquidation", value="200000", currency="USD")
        self.assertIn(123, self.wrapper._account_summary_results)
        self.assertEqual(self.wrapper._account_summary_results[123]["summary_values"]["NetLiquidation"]["value"], "200000")
        self.assertEqual(len(self.wrapper.streaming_account_value_queue), 0) # Should not go to streaming queue
        self.assert_last_api_activity_updated()

    def test_accountSummary_streaming(self):
        self.wrapper.accountSummary(reqId=999, account="U123", tag="BuyingPower", value="50000", currency="USD") # reqId 999 not in _account_summary_events
        self.assertEqual(len(self.wrapper.streaming_account_value_queue), 1)
        stream_event = self.wrapper.streaming_account_value_queue[0]
        self.assertEqual(stream_event["type"], "AccountSummaryStream")
        self.assertEqual(stream_event["tag"], "BuyingPower")
        self.assert_last_api_activity_updated()

    def test_accountSummaryEnd(self):
        mock_event = MagicMock(spec=threading.Event)
        self.wrapper._account_summary_events[123] = mock_event
        self.wrapper.accountSummaryEnd(reqId=123)
        mock_event.set.assert_called_once()
        self.assert_last_api_activity_updated()

    def test_contractDetails(self):
        mock_details = MagicMock()
        mock_details.contract = MagicMock(symbol="SPY")
        self.wrapper.contractDetails(reqId=789, contractDetails=mock_details)
        self.assertIn(789, self.wrapper._contract_details_results)
        self.assertEqual(len(self.wrapper._contract_details_results[789]), 1)
        self.assertEqual(self.wrapper._contract_details_results[789][0].contract.symbol, "SPY")
        self.assert_last_api_activity_updated()

    def test_contractDetailsEnd(self):
        mock_event = MagicMock(spec=threading.Event)
        self.wrapper._contract_details_events[789] = mock_event
        self.wrapper.contractDetailsEnd(reqId=789)
        mock_event.set.assert_called_once()
        self.assert_last_api_activity_updated()

    def test_position(self):
        mock_contract = MagicMock(symbol="TSLA")
        # Case 1: Active positions event
        self.wrapper._positions_event = MagicMock(spec=threading.Event)
        self.wrapper._positions_event.is_set.return_value = False # Not yet set
        self.wrapper.position(account="U123", contract=mock_contract, position=5, avgCost=200)
        self.assertEqual(len(self.wrapper._positions_results), 1)
        self.assertEqual(self.wrapper._positions_results[0]["contract_obj"].symbol, "TSLA")

        # Case 2: No active event (should ideally log or go to portfolio_updates_queue if streaming is desired)
        self.wrapper._positions_event = None
        self.wrapper.position(account="U123", contract=mock_contract, position=5, avgCost=200)
        # Current implementation logs debug and does nothing else if _positions_event is None
        self.assert_last_api_activity_updated()


    def test_positionEnd(self):
        mock_event = MagicMock(spec=threading.Event)
        self.wrapper._positions_event = mock_event
        self.wrapper.positionEnd()
        mock_event.set.assert_called_once()
        self.assert_last_api_activity_updated()

    def test_pnl_synchronous(self):
        mock_event = MagicMock(spec=threading.Event)
        self.wrapper._pnl_events[456] = mock_event
        self.wrapper.pnl(reqId=456, dailyPnL=100.0, unrealizedPnL=200.0, realizedPnL=50.0)
        self.assertIn(456, self.wrapper._pnl_results)
        self.assertEqual(self.wrapper._pnl_results[456]["dailyPnL"], 100.0)
        mock_event.set.assert_called_once()
        self.assert_last_api_activity_updated()

    def test_pnl_streaming(self):
        self.wrapper.pnl(reqId=999, dailyPnL=100.0, unrealizedPnL=200.0, realizedPnL=50.0) # reqId 999 not in _pnl_events
        self.assertTrue(any(e["type"] == "pnl_stream" and e["reqId"] == 999 for e in self.wrapper.error_messages_queue))
        self.assert_last_api_activity_updated()


    def test_currentTime(self):
        # currentTime just calls _update_last_api_activity_time and logs at debug
        with patch.object(self.wrapper.logger, 'debug') as mock_log_debug: # Check if it logs
            self.wrapper.currentTime(time_val=int(time.time()))
            self.assert_last_api_activity_updated()
            # mock_log_debug.assert_called_once() # Logger format might make this tricky

    # 3. Order ID Management
    def test_get_next_order_id_and_increment_none(self):
        self.wrapper._next_valid_order_id = None
        with self.assertLogs(self.wrapper.logger, level='ERROR') as log_capture:
            order_id = self.wrapper.get_next_order_id_and_increment()
        self.assertIsNone(order_id)
        self.assertTrue(any("_next_valid_order_id is not set" in rec.getMessage() for rec in log_capture.records))

    def test_get_next_order_id_and_increment_success(self):
        self.wrapper._next_valid_order_id = 201

        # Simulate lock for completeness, though actual threading isn't tested here
        with patch.object(self.wrapper, '_next_order_id_lock', MagicMock(spec=threading.Lock)) as mock_lock:
            order_id_1 = self.wrapper.get_next_order_id_and_increment()
            self.assertEqual(order_id_1, 201)
            self.assertEqual(self.wrapper._next_valid_order_id, 202)
            mock_lock.__enter__.assert_called_once() # Check lock was used
            mock_lock.__exit__.assert_called_once()

            order_id_2 = self.wrapper.get_next_order_id_and_increment()
            self.assertEqual(order_id_2, 202)
            self.assertEqual(self.wrapper._next_valid_order_id, 203)


if __name__ == '__main__':
    unittest.main()
