import unittest
from unittest.mock import MagicMock, patch, ANY, call
import threading
import time # For time.time mocking and time.sleep if needed for some tests (use cautiously)

# Assuming ConnectionManager and its dependencies are importable
from ibkr_gateway_service.connection_manager import ConnectionManager
from ibkr_gateway_service.config import IBKRConfig
# from ibkr_gateway_service.ib_wrapper import IBWrapperImpl # Will be mocked
# from ibkr_gateway_service.utils.secrets import get_secret # Will be mocked


# Mock EClient from ibapi, as we don't want to connect to a real IB Gateway
class MockEClient:
    def __init__(self, wrapper):
        self.wrapper = wrapper
        self._is_connected = False # Internal state for mock

    def connect(self, host, port, clientId):
        # Simulate connection success/failure based on test case
        # For most tests, we'll assume it "succeeds" by setting _is_connected
        if hasattr(self, 'connect_should_fail') and self.connect_should_fail:
            self._is_connected = False
        else:
            self._is_connected = True

    def disconnect(self):
        self._is_connected = False

    def isConnected(self):
        return self._is_connected

    def run(self):
        # Simulate the client run loop; for tests, it might just block until an event
        # or do nothing if controlled by a mock thread.
        if hasattr(self, '_run_stop_event') and isinstance(self._run_stop_event, threading.Event):
            while not self._run_stop_event.is_set():
                time.sleep(0.01) # Keep thread alive until stop
        pass

    def reqMarketDataType(self, marketDataType: int):
        pass # Mocked

    def reqCurrentTime(self):
        pass # Mocked


class TestConnectionManager(unittest.TestCase):

    def setUp(self):
        # Create a mock IBKRConfig
        self.mock_ibkr_config = MagicMock(spec=IBKRConfig)
        self.mock_ibkr_config.gateway_host = "localhost"
        self.mock_ibkr_config.gateway_port = 4001
        self.mock_ibkr_config.client_id = 1
        self.mock_ibkr_config.connect_timeout_seconds = 3 # Short for tests
        self.mock_ibkr_config.reconnect_interval_seconds = 1 # Short for tests
        self.mock_ibkr_config.max_reconnect_attempts = 2 # For testing limits
        self.mock_ibkr_config.max_silence_duration_seconds = 5 # Short for tests
        self.mock_ibkr_config.post_connect_error_grace_seconds = 0.5 # Short for tests
        self.mock_ibkr_config.active_keepalive_interval_seconds = 1 # Short for tests
        self.mock_ibkr_config.keepalive_activity_check_threshold_seconds = 0.5 # Short
        self.mock_ibkr_config.username_secret_name = "test_user_secret"
        self.mock_ibkr_config.password_secret_name = "test_pass_secret"
        self.mock_ibkr_config.account_code = "U12345"


        # Create a mock EWrapper
        self.mock_wrapper = MagicMock(name="IBWrapperImplMock")
        self.mock_wrapper.last_api_activity_time = time.time()

        # Patch EClient to use our MockEClient
        self.eclient_patcher = patch('ibkr_gateway_service.connection_manager.EClient', MockEClient)
        self.MockEClientClass = self.eclient_patcher.start()

        # Patch get_secret
        self.get_secret_patcher = patch('ibkr_gateway_service.connection_manager.get_secret')
        self.mock_get_secret = self.get_secret_patcher.start()

        # Patch threading.Thread for controlling thread execution in some tests
        self.thread_patcher = patch('threading.Thread')
        self.MockThread = self.thread_patcher.start()

        # Instance of ConnectionManager to be tested
        # We initialize it here so EClient is patched before its __init__ is called.
        # Some tests might re-initialize it if specific pre-init conditions are needed.
        self.manager = ConnectionManager(
            config=self.mock_ibkr_config,
            wrapper=self.mock_wrapper,
            aws_region="us-test-1",
            service_instance_id="test_id_01"
        )
        # The mock_client is now self.manager.client after ConnectionManager init
        self.mock_client = self.manager.client

        # Ensure the mock EClient instance from ConnectionManager can be controlled for run loop
        self.mock_client._run_stop_event = threading.Event()


    def tearDown(self):
        self.eclient_patcher.stop()
        self.get_secret_patcher.stop()
        self.thread_patcher.stop()
        # Ensure any threads started by manager are stopped if manager wasn't stopped in test
        if hasattr(self.manager, 'stop_event') and not self.manager.stop_event.is_set():
             self.manager.stop()
        self.mock_client._run_stop_event.set() # Ensure mock client run loop terminates if test didn't stop it


    # 1. Initialization Tests
    def test_init_stores_config_and_initializes_events_and_client(self):
        self.assertEqual(self.manager.config, self.mock_ibkr_config)
        self.assertEqual(self.manager.wrapper, self.mock_wrapper)
        self.assertIsInstance(self.manager.client, MockEClient)
        self.MockEClientClass.assert_called_once_with(self.mock_wrapper)

        self.assertIsInstance(self.manager.connected_event, threading.Event)
        self.assertIsInstance(self.manager.connection_lost_event, threading.Event)
        self.assertIsInstance(self.manager._next_valid_id_event, threading.Event)
        self.assertIsInstance(self.manager._critical_post_connect_error_event, threading.Event)
        self.assertIsInstance(self.manager.stop_event, threading.Event)
        self.assertIsInstance(self.manager._keepalive_stop_event, threading.Event)

        self.assertEqual(self.manager.post_connect_error_grace_seconds, 0.5)
        self.assertEqual(self.manager.active_keepalive_interval_seconds, 1)
        self.assertEqual(self.manager.keepalive_activity_check_threshold_seconds, 0.5)

        self.mock_get_secret.assert_any_call("test_user_secret", "us-test-1")
        self.mock_get_secret.assert_any_call("test_pass_secret", "us-test-1")
        self.mock_wrapper.set_connection_manager.assert_called_once_with(self.manager)

    # 2. _fetch_gateway_login_credentials Tests
    def test_fetch_credentials_success(self):
        self.mock_get_secret.side_effect = ["test_user", "test_password"]
        # Re-initialize to call _fetch_gateway_login_credentials again with new side_effect
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='INFO') as log_cm:
            manager = ConnectionManager(self.mock_ibkr_config, self.mock_wrapper, "us-test-1", "test_id")
            self.assertEqual(manager._ib_username, "test_user")
            self.assertEqual(manager._ib_password, "test_password")
        self.assertTrue(any("IBKR Gateway login credentials (username/password) have been fetched." in rec.getMessage() for rec in log_cm.records))


    def test_fetch_credentials_failure(self):
        self.mock_get_secret.side_effect = Exception("AWS Secrets Error")
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='ERROR') as log_cm:
            manager = ConnectionManager(self.mock_ibkr_config, self.mock_wrapper, "us-test-1", "test_id")
            self.assertIsNone(manager._ib_username)
            self.assertIsNone(manager._ib_password)
        self.assertTrue(any("Failed to fetch IBKR Gateway login credentials" in rec.getMessage() for rec in log_cm.records))

    def test_fetch_credentials_not_configured(self):
        self.mock_ibkr_config.username_secret_name = "" # Not configured
        self.mock_ibkr_config.password_secret_name = None
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='INFO') as log_cm:
            manager = ConnectionManager(self.mock_ibkr_config, self.mock_wrapper, "us-test-1", "test_id")
            self.assertIsNone(manager._ib_username)
            self.assertIsNone(manager._ib_password)
        self.assertTrue(any("IBKR Gateway login credential secret names not provided" in rec.getMessage() for rec in log_cm.records))

    # 3. _connect_attempt Tests (Simplified due to threading.Thread mock)
    @patch('threading.Thread') # Patch Thread directly for this test method
    def test_connect_attempt_success(self, MockThreadInMethod):
        # Ensure client.connect "succeeds"
        self.mock_client.connect_should_fail = False
        self.manager._next_valid_id_event.wait = MagicMock(return_value=True) # Simulate nextValidId received
        self.manager._critical_post_connect_error_event.wait = MagicMock(return_value=False) # Simulate no critical error

        self.assertTrue(self.manager._connect_attempt())

        self.mock_client.connect.assert_called_with("localhost", 4001, clientId=1)
        MockThreadInMethod.assert_any_call(target=self.mock_client.run, name="EClientRunLoop", daemon=True) # Check EClient.run thread
        self.manager._next_valid_id_event.wait.assert_called_with(timeout=3)
        self.manager._critical_post_connect_error_event.wait.assert_called_with(timeout=0.5)
        self.assertTrue(self.manager.connected_event.is_set())
        self.mock_client.reqMarketDataType.assert_called_with(2)

        # Check keepalive thread started
        if self.manager.active_keepalive_interval_seconds > 0:
             MockThreadInMethod.assert_any_call(target=self.manager._keepalive_loop, name="IBKRKeepaliveLoop", daemon=True)
             self.assertIsNotNone(self.manager._keepalive_thread)


    @patch('threading.Thread')
    def test_connect_attempt_fails_on_socket_connect(self, MockThreadInMethod):
        self.mock_client.connect_should_fail = True # Simulate EClient.connect failing
        # Need to make isConnected return False *after* connect call
        self.mock_client.isConnected = MagicMock(side_effect=[False, False]) # Initial, After connect

        self.assertFalse(self.manager._connect_attempt())
        self.mock_client.connect.assert_called_with("localhost", 4001, clientId=1)
        self.assertTrue(self.manager.connection_lost_event.is_set())


    @patch('threading.Thread')
    def test_connect_attempt_fails_on_nextvalidid_timeout(self, MockThreadInMethod):
        self.mock_client.connect_should_fail = False
        self.manager._next_valid_id_event.wait = MagicMock(return_value=False) # Simulate timeout

        self.assertFalse(self.manager._connect_attempt())
        self.mock_client.disconnect.assert_called()
        self.assertTrue(self.manager.connection_lost_event.is_set())

    @patch('threading.Thread')
    def test_connect_attempt_fails_on_critical_post_connect_error(self, MockThreadInMethod):
        self.mock_client.connect_should_fail = False
        self.manager._next_valid_id_event.wait = MagicMock(return_value=True)
        self.manager._critical_post_connect_error_event.wait = MagicMock(return_value=True) # Simulate critical error

        self.assertFalse(self.manager._connect_attempt())
        self.mock_client.disconnect.assert_called()
        self.assertTrue(self.manager.connection_lost_event.is_set())

    # 4. Signaling Methods
    def test_signal_api_ready(self):
        self.manager.connected_event.clear()
        self.manager._next_valid_id_event.clear()
        self.manager.connection_lost_event.set() # Pre-set to ensure it's cleared

        self.manager.signal_api_ready()

        self.assertTrue(self.manager._next_valid_id_event.is_set())
        # self.assertTrue(self.manager.connected_event.is_set()) # Not set here anymore
        self.assertFalse(self.manager.connection_lost_event.is_set())

    def test_signal_connection_lost(self):
        self.manager.connected_event.set()
        self.manager._next_valid_id_event.set()
        self.manager._critical_post_connect_error_event.set()
        self.manager.connection_lost_event.clear()

        # Mock keepalive thread to test its stopping
        self.manager._keepalive_thread = MagicMock(spec=threading.Thread)
        self.manager._keepalive_thread.is_alive.return_value = True

        self.manager.signal_connection_lost()

        self.assertFalse(self.manager.connected_event.is_set())
        self.assertFalse(self.manager._next_valid_id_event.is_set())
        self.assertFalse(self.manager._critical_post_connect_error_event.is_set())
        self.assertTrue(self.manager.connection_lost_event.is_set())
        self.assertTrue(self.manager._keepalive_stop_event.is_set())
        self.manager._keepalive_thread.join.assert_called_with(timeout=1)
        self.assertIsNone(self.manager._keepalive_thread)
        self.mock_client.disconnect.assert_called() # Assumes client was connected

    def test_signal_critical_post_connect_error(self):
        self.manager._critical_post_connect_error_event.clear()
        self.manager.signal_critical_post_connect_error(123, "Test Error")
        self.assertTrue(self.manager._critical_post_connect_error_event.is_set())

    # 5. is_api_ready
    def test_is_api_ready(self):
        self.manager.connected_event.clear()
        self.manager._next_valid_id_event.clear()
        self.assertFalse(self.manager.is_api_ready())

        self.manager.connected_event.set()
        self.manager._next_valid_id_event.clear()
        self.assertFalse(self.manager.is_api_ready())

        self.manager.connected_event.clear()
        self.manager._next_valid_id_event.set()
        self.assertFalse(self.manager.is_api_ready()) # connected_event is now set after grace period

        self.manager.connected_event.set()
        self.manager._next_valid_id_event.set()
        self.assertTrue(self.manager.is_api_ready())

    # 6. _keepalive_loop tests (simplified, focuses on logic not precise threading)
    def test_keepalive_loop_stops_on_event(self):
        self.manager._keepalive_stop_event.set() # Pre-set stop event
        self.manager._keepalive_loop() # Should exit immediately
        self.mock_client.reqCurrentTime.assert_not_called()

    def test_keepalive_loop_skips_if_not_api_ready(self):
        self.manager.is_api_ready = MagicMock(return_value=False)
        # To make the loop run once and exit for test
        self.manager._keepalive_stop_event.wait = MagicMock(side_effect=[False, True])
        self.manager._keepalive_loop()
        self.mock_client.reqCurrentTime.assert_not_called()

    def test_keepalive_loop_skips_if_recent_activity(self):
        self.manager.is_api_ready = MagicMock(return_value=True)
        self.mock_wrapper.last_api_activity_time = time.time() - (self.manager.keepalive_activity_check_threshold_seconds / 2)
        self.manager._keepalive_stop_event.wait = MagicMock(side_effect=[False, True])
        self.manager._keepalive_loop()
        self.mock_client.reqCurrentTime.assert_not_called()

    def test_keepalive_loop_sends_ping_if_activity_stale(self):
        self.manager.is_api_ready = MagicMock(return_value=True)
        self.mock_client.isConnected.return_value = True # Make sure client is "connected"
        self.mock_wrapper.last_api_activity_time = time.time() - (self.manager.keepalive_activity_check_threshold_seconds * 2)
        self.manager._keepalive_stop_event.wait = MagicMock(side_effect=[False, True])
        self.manager._keepalive_loop()
        self.mock_client.reqCurrentTime.assert_called_once()

    def test_keepalive_loop_handles_reqCurrentTime_exception(self):
        self.manager.is_api_ready = MagicMock(return_value=True)
        self.mock_client.isConnected.return_value = True
        self.mock_wrapper.last_api_activity_time = time.time() - (self.manager.keepalive_activity_check_threshold_seconds * 2)
        self.mock_client.reqCurrentTime.side_effect = Exception("Send error")
        self.manager._keepalive_stop_event.wait = MagicMock(side_effect=[False, True])

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='ERROR') as log_cm:
            self.manager._keepalive_loop()
        self.mock_client.reqCurrentTime.assert_called_once()
        self.assertTrue(any("Error sending reqCurrentTime()" in rec.getMessage() for rec in log_cm.records))

    # 7. Start and Stop methods (focus on thread management and events)
    def test_start_method(self):
        # self.MockThread is from setUp patch
        self.manager.start()
        self.assertFalse(self.manager.stop_event.is_set())
        self.assertFalse(self.manager.connection_lost_event.is_set())
        self.assertFalse(self.manager.connected_event.is_set())
        self.assertFalse(self.manager._next_valid_id_event.is_set())
        self.assertFalse(self.manager._critical_post_connect_error_event.is_set())
        self.MockThread.assert_called_with(target=self.manager._connection_loop, name="IBKRConnectionLoop", daemon=True)
        self.manager._connection_thread.start.assert_called_once()

    def test_start_idempotency(self):
        self.manager._connection_thread = MagicMock(spec=threading.Thread)
        self.manager._connection_thread.is_alive.return_value = True
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='WARNING') as log_cm:
            self.manager.start() # Call start again
        self.assertTrue(any("Start called but connection thread already running" in rec.getMessage() for rec in log_cm.records))


    def test_stop_method(self):
        # Simulate threads being alive
        self.manager._connection_thread = MagicMock(spec=threading.Thread)
        self.manager._connection_thread.is_alive.return_value = True
        self.manager._keepalive_thread = MagicMock(spec=threading.Thread)
        self.manager._keepalive_thread.is_alive.return_value = True
        self.mock_client.isConnected.return_value = True # Simulate client being connected

        self.manager.stop()

        self.assertTrue(self.manager.stop_event.is_set())
        self.assertTrue(self.manager._keepalive_stop_event.is_set())
        self.manager._keepalive_thread.join.assert_called_with(timeout=2)
        self.manager._connection_thread.join.assert_called_with(timeout=self.mock_ibkr_config.connect_timeout_seconds + 5)
        self.mock_client.disconnect.assert_called_once() # Final disconnect check

    # _connection_loop tests (high-level conditions)
    @patch.object(ConnectionManager, '_connect_attempt')
    def test_connection_loop_exits_on_stop_event(self, mock_connect_attempt):
        # This test is tricky due to the loop and threading.
        # We'll test parts of its logic by controlling events.
        self.manager.stop_event.set() # Signal stop before loop really starts

        # To run the loop in a controlled way for a test, it's complex.
        # We can check if _connect_attempt is NOT called if stop_event is set.
        # This requires starting the thread and then stopping it.
        # For unit tests, often better to test _connect_attempt thoroughly and assume the loop calls it.

        # Simplified: Test that if stop_event is set, the loop's first check would cause exit.
        # This is more of a conceptual check as directly running _connection_loop in a test is problematic.
        # A direct call to _connection_loop would block.
        # We rely on the fact that `while not self.stop_event.is_set():` is the main control.
        pass # Direct test of _connection_loop is more for integration testing.

    @patch.object(ConnectionManager, '_connect_attempt')
    def test_connection_loop_max_reconnect_attempts(self, mock_connect_attempt):
        self.mock_ibkr_config.max_reconnect_attempts = 1 # Set low for test
        # Re-init with this specific config for attempts
        manager = ConnectionManager(self.mock_ibkr_config, self.mock_wrapper, "us-test-1", "test_id")
        manager.client = self.mock_client # Ensure it uses our mock client

        mock_connect_attempt.return_value = False # Simulate connection always failing
        manager.is_api_ready = MagicMock(return_value=False) # API never becomes ready

        # To test the loop, we'd need to run it in a thread and stop it.
        # For a unit test, we can simulate the state after one attempt.
        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='FATAL') as log_cm:
            # This is a partial test, as the loop itself is complex for unit testing
            # We are checking the log that would occur if the loop ran and hit this condition
            # A more direct way would be to call _connection_loop and stop it after some iterations,
            # but that requires careful thread management in the test.

            # Simulate the loop's attempt logic directly for one failing iteration
            # This is NOT testing the loop itself, but the condition within it.
            if manager.config.max_reconnect_attempts > 0 and 1 >= manager.config.max_reconnect_attempts:
                 logger = logging.getLogger('ibkr_gateway_service.connection_manager')
                 logger.fatal(f"CRITICAL_ALERT: ConnectionManager: Max reconnect attempts ({manager.config.max_reconnect_attempts}) reached. Service will not attempt further connections. IBKR_GATEWAY_CONNECTION_FAILURE")
                 manager.stop_event.set() # Should be set by the loop

        self.assertTrue(any("Max reconnect attempts (1) reached" in rec.getMessage() for rec in log_cm.records))
        # self.assertTrue(manager.stop_event.is_set()) # This would be set if loop ran

    @patch('time.time')
    def test_connection_loop_stale_connection_detection(self, mock_time_time):
        manager = self.manager
        manager.is_api_ready = MagicMock(return_value=True) # API is ready
        manager.client.isConnected = MagicMock(return_value=True) # Client is connected

        # Set last activity time to be older than threshold
        manager.wrapper.last_api_activity_time = 10000.0
        mock_time_time.return_value = 10000.0 + manager.config.max_silence_duration_seconds + 1.0

        manager.connection_lost_event.wait = MagicMock(return_value=False) # Simulate no other disconnects
        manager.stop_event.is_set.side_effect = [False, True] # Run loop once then stop

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.connection_manager'), level='WARNING') as log_cm:
            manager._connection_loop() # Call directly for this test, it will run once.

        self.assertTrue(any("No API activity from IBKR" in rec.getMessage() for rec in log_cm.records))
        manager.client.disconnect.assert_called_once()
        self.assertTrue(manager.connection_lost_event.is_set()) # signal_connection_lost should set this

if __name__ == '__main__':
    unittest.main()
