import logging
import threading
import time
from typing import Optional, Any # Any for EWrapper placeholder for now

from ibapi.client import EClient # Official IB API
# from ibapi.wrapper import EWrapper # Will be implemented in ib_wrapper.py

# Assuming config.py and utils/secrets.py are in the same package structure
from .config import IBKRConfig
from .utils.secrets import get_secret

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self, config: IBKRConfig, wrapper: Any, aws_region: str, service_instance_id: str): # wrapper type will be EWrapper
        self.config = config
        self.aws_region = aws_region
        self.service_instance_id = service_instance_id # For logging and client ID suffix if needed

        self.wrapper = wrapper
        self.client = EClient(self.wrapper)

        self._ib_username: Optional[str] = None
        self._ib_password: Optional[str] = None # These are for Gateway login, not EClient.connect()

        self.connected_event = threading.Event()     # Set when API connection is live (nextValidId received and grace period passed)
        self.connection_lost_event = threading.Event() # Set by wrapper on disconnect or critical error
        self.stop_event = threading.Event()
        self._next_valid_id_event = threading.Event() # Set when nextValidId callback is received
        self._critical_post_connect_error_event = threading.Event() # Set if critical error occurs in grace period

        self.post_connect_error_grace_seconds = float(config.post_connect_error_grace_seconds)
        self.active_keepalive_interval_seconds = int(config.active_keepalive_interval_seconds)
        self.keepalive_activity_check_threshold_seconds = int(config.keepalive_activity_check_threshold_seconds)

        self._connection_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._keepalive_stop_event = threading.Event()
        self._current_client_id = self.config.client_id
        self._api_thread_active = False

        # Stale connection detection
        self.max_silence_duration_seconds = config.max_silence_duration_seconds # from IBKRConfig via main config
        if self.max_silence_duration_seconds <= 0: # Disable if 0 or negative
            self.max_silence_duration_seconds = 0
            logger.info("ConnectionManager: Stale connection detection is disabled (max_silence_duration_seconds <= 0).")
        else:
            logger.info(f"ConnectionManager: Stale connection detection enabled (max silence: {self.max_silence_duration_seconds}s).")


        # Link wrapper and manager
        if wrapper: # wrapper can be None if ConnectionManager is created first then wrapper set.
            if hasattr(wrapper, 'set_connection_manager'):
                wrapper.set_connection_manager(self)
            else:
                logger.warning("EWrapper implementation does not have 'set_connection_manager' method.")

        # Fetch Gateway login credentials on initialization if configured
        self._fetch_gateway_login_credentials()


    def _fetch_gateway_login_credentials(self):
        """
        Fetches IB Gateway login credentials. These are intended for use by an
        external Gateway automation tool (e.g., IBController) if automated Gateway
        login is implemented. This service itself does not use these credentials
        for EClient.connect(), which uses socket-based authentication (e.g. trusted IPs).
        """
        if self.config.username_secret_name and self.config.password_secret_name and \
           self.config.username_secret_name.strip() and self.config.password_secret_name.strip():
            logger.info("Attempting to fetch IBKR Gateway login credentials from Secrets Manager...")
            try:
                self._ib_username = get_secret(self.config.username_secret_name, self.aws_region)
                self._ib_password = get_secret(self.config.password_secret_name, self.aws_region)
                if self._ib_username: # Check if secret actually had a value
                    logger.info(
                        "IBKR Gateway login credentials (username/password) have been fetched. "
                        "These are intended for use by an external Gateway automation tool (e.g., IBController) "
                        "if automated Gateway login is implemented. This service itself does not use these "
                        "credentials for EClient.connect()."
                    )
                else: # Secret name configured but secret was empty
                    logger.warning(
                        "IBKR Gateway login credential secret names are configured, but fetched username is empty. "
                        "This service assumes the IBKR Gateway/TWS is pre-authenticated and running, or uses other auth methods."
                    )
                    self._ib_username = None # Ensure it's None if fetched empty
                    self._ib_password = None
            except Exception as e:
                logger.error(f"Failed to fetch IBKR Gateway login credentials: {e}")
                logger.warning(
                    "Proceeding without fetched Gateway login credentials due to error. "
                    "This service assumes the IBKR Gateway/TWS is pre-authenticated and running."
                )
                self._ib_username = None # Ensure None on error
                self._ib_password = None
        else:
            logger.info(
                "IBKR Gateway login credential secret names not provided or are empty. "
                "This service assumes the IBKR Gateway/TWS is pre-authenticated and running, or uses other auth methods."
            )
            self._ib_username = None
            self._ib_password = None


    def _connect_attempt(self):
        """Attempts to connect and start the EClient processing loop."""
        if self.client.isConnected():
            logger.info("ConnectionManager: Already connected according to EClient.")
            # This might happen if a previous disconnect wasn't fully cleaned up on client side.
            # Attempt to ensure a clean state.
            self.client.disconnect()
            time.sleep(1) # Give a moment for disconnect to process

        self.connected_event.clear()
        self.connection_lost_event.clear()
        self.next_valid_id_event.clear()
        self._critical_post_connect_error_event.clear() # Clear before new attempt
        self._api_thread_active = False

        logger.info(f"ConnectionManager: Attempting to connect to IB Gateway at {self.config.gateway_host}:{self.config.gateway_port} with ClientID {self._current_client_id}")
        self.client.connect(self.config.gateway_host, self.config.gateway_port, clientId=self._current_client_id)

        if not self.client.isConnected(): # Initial socket connection check
            logger.error("ConnectionManager: Failed to establish initial socket connection with IB Gateway.")
            self.signal_connection_lost() # Use the signal method
            return False # Connection failed

        logger.info("ConnectionManager: Socket connection established. Starting API client message processing thread.")

        # Start EClient's message processing loop in a new thread
        api_thread = threading.Thread(target=self.client.run, name="EClientRunLoop", daemon=True)
        api_thread.start()
        self._api_thread_active = True

        # Wait for connection confirmation (nextValidId from EWrapper) with a timeout
        if not self._next_valid_id_event.wait(timeout=self.config.connect_timeout_seconds):
            logger.error(f"ConnectionManager: Connection to IB Gateway API timed out after {self.config.connect_timeout_seconds} seconds (nextValidId not received).")
            self.client.disconnect() # Attempt to clean up socket
            self._api_thread_active = False # Thread should exit after disconnect
            api_thread.join(timeout=2) # Wait briefly for thread to exit
            self.client.disconnect() # Attempt to clean up socket
            self._api_thread_active = False # Thread should exit after disconnect
            if api_thread.is_alive(): api_thread.join(timeout=2) # Wait briefly for thread to exit
            self.signal_connection_lost()
            return False # Connection failed

        # Grace period to check for critical errors immediately after nextValidId
        logger.info(f"ConnectionManager: nextValidId received. Entering grace period of {self.post_connect_error_grace_seconds}s for critical error checks.")
        self._critical_post_connect_error_event.clear() # Clear before waiting for this specific period
        if self._critical_post_connect_error_event.wait(timeout=self.post_connect_error_grace_seconds):
            logger.error("ConnectionManager: Critical post-connect error received during grace period. Connection attempt failed.")
            if self.client.isConnected(): self.client.disconnect()
            self._api_thread_active = False
            # api_thread should stop on its own after client disconnect
            self.signal_connection_lost() # This clears connected_event, next_valid_id_event
            return False # Connection failed

        logger.info("ConnectionManager: Grace period passed without critical errors.")
        # Original logic to set connected_event and reqMarketDataType follows here
        self.connected_event.set()
        # Request market data type (important for some API behaviors)
        # 1: Live, 2: Frozen, 3: Delayed, 4: Delayed Frozen
        # Use Frozen for paper accounts or if live data isn't from IBKR. Example:
        self.client.reqMarketDataType(2)
        logger.info("ConnectionManager: Successfully connected and API confirmed (post-grace period). Requested market data type 2 (Frozen).")

        # Start keepalive thread if enabled
        if self.active_keepalive_interval_seconds > 0:
            logger.info("ConnectionManager: Starting keepalive thread.")
            if self._keepalive_thread and self._keepalive_thread.is_alive():
                self._keepalive_stop_event.set()
                self._keepalive_thread.join(timeout=2) # Wait for old one to die

            self._keepalive_stop_event.clear()
            self._keepalive_thread = threading.Thread(target=self._keepalive_loop, name="IBKRKeepaliveLoop", daemon=True)
            self._keepalive_thread.start()

        return True # Connection successful

    def _keepalive_loop(self):
        logger.info("ConnectionManager: Keepalive loop started.")
        while not self._keepalive_stop_event.wait(self.active_keepalive_interval_seconds):
            if not self.is_api_ready():
                # logger.debug("Keepalive: API not ready, skipping keepalive ping.")
                continue

            # Check if there has been recent API activity
            now = time.time()
            if hasattr(self.wrapper, 'last_api_activity_time'):
                time_since_last_activity = now - self.wrapper.last_api_activity_time
                if time_since_last_activity < self.keepalive_activity_check_threshold_seconds:
                    # logger.debug(f"Keepalive: Recent API activity ({time_since_last_activity:.0f}s ago). Skipping explicit keepalive.")
                    continue

            if self.client.isConnected():
                logger.info("Keepalive: Sending reqCurrentTime() as keepalive.")
                try:
                    self.client.reqCurrentTime()
                    # The response (currentTime callback in wrapper) will update last_api_activity_time
                except Exception as e:
                    logger.error(f"Keepalive: Error sending reqCurrentTime(): {e}")
                    # If this fails, the main connection loop's error handling or stale detection should pick it up.
            else:
                logger.warning("Keepalive: Client not connected, cannot send keepalive.")
        logger.info("ConnectionManager: Keepalive loop stopped.")

    def _connection_loop(self):
        logger.info("ConnectionManager: Starting connection management loop.")
        # self._fetch_gateway_login_credentials() # Fetch once if using automated login tools that need them.

        attempts = 0
        while not self.stop_event.is_set():
            if not self.is_api_ready(): # Checks connected_event and next_valid_id_event
                if attempts > 0: # Apply backoff only after the first actual attempt
                    # Exponential backoff with jitter (simplified for brevity here, use proper algo)
                    backoff_seconds = min(self.config.reconnect_interval_seconds * (2 ** (attempts -1)), 60) # Max 60s
                    jitter = (time.time() * 1000) % 1000 / 1000 # Simple sub-second jitter
                    sleep_duration = time.Duration(float(backoff_seconds) + jitter) * time.Second

                    logger.info(f"ConnectionManager: Connection unavailable. Waiting {sleep_duration} before reconnect attempt #{attempts + 1}.")
                    if self.stop_event.wait(sleep_duration): # Wait or until stop is signaled
                        logger.info("ConnectionManager: Stop event received during reconnect wait.")
                        break

                if self.stop_event.is_set(): break

                if self.config.max_reconnect_attempts > 0 and attempts >= self.config.max_reconnect_attempts:
                    logger.fatal(f"CRITICAL_ALERT: ConnectionManager: Max reconnect attempts ({self.config.max_reconnect_attempts}) reached. Service will not attempt further connections. IBKR_GATEWAY_CONNECTION_FAILURE")
                    # TODO: This should trigger a service shutdown or enter a permanent error state.
                    # For now, just break the loop. The service would appear "down".
                    self.stop_event.set() # Signal other parts of service to stop
                    break

                logger.info(f"ConnectionManager: Initiating connection attempt #{attempts + 1}.")
                if self._connect_attempt():
                    attempts = 0 # Reset attempts on successful connection
                else:
                    attempts += 1
                    # _connect_attempt already logs errors. It also calls signal_connection_lost().
            else: # API is ready, monitor for staleness or external signals
                # Stale Connection Check
                if self.max_silence_duration_seconds > 0 and hasattr(self.wrapper, 'last_api_activity_time'):
                    silence_duration = time.time() - self.wrapper.last_api_activity_time
                    if silence_duration > float(self.max_silence_duration_seconds):
                        logger.warning(f"ConnectionManager: No API activity from IBKR for {silence_duration:.0f} seconds (threshold: {self.max_silence_duration_seconds}s). Assuming stale connection and forcing reconnect cycle.")
                        if self.client.isConnected(): # Check before calling disconnect
                            self.client.disconnect() # This should trigger EWrapper.connectionClosed()
                        # Ensure state reflects disconnect for immediate reconnect attempt by the loop
                        self.signal_connection_lost() # This clears connected_event & next_valid_id_event, sets connection_lost_event
                        # The connection_lost_event being set will cause the next block to see it.
                        # No 'continue' needed here, the state change will drive the loop.

                # Wait for connection_lost_event (signaled by wrapper or stale check) or stop_event
                # Use a timeout to periodically re-evaluate the stale connection condition if no events occur.
                connection_lost_signaled = self.connection_lost_event.wait(timeout=1.0) # Check every second

                if self.stop_event.is_set():
                    logger.info("ConnectionManager: Stop event received while connection was active/monitored.")
                    break
                if connection_lost_signaled:
                    logger.warning("ConnectionManager: Connection lost event signaled. Will attempt to reconnect.")
                    # Events (connected_event, next_valid_id_event) are already cleared by signal_connection_lost()
                    # No need to increment `attempts` here, the main path for `!is_api_ready()` will handle it in the next iteration.

        # Loop termination cleanup
        if self.client.isConnected():
            logger.info("ConnectionManager: Connection loop ending, ensuring client is disconnected.")
            self.client.disconnect()
        if self._api_thread_active:
             logger.info("ConnectionManager: Loop ending, EClient.run() thread might still be active if disconnect is slow.")
             # EClient.run() should exit when client.disconnect() is called and socket closes.
        logger.info("ConnectionManager: Connection loop terminated.")

    def start(self):
        if self._connection_thread is not None and self._connection_thread.is_alive():
            logger.warning("ConnectionManager: Start called but connection thread already running.")
            return

        logger.info("ConnectionManager: Starting connection management thread...")
        self.stop_event.clear()
        self.connection_lost_event.clear() # Clear at start
        self.connected_event.clear()
        self.next_valid_id_event.clear()
        self._critical_post_connect_error_event.clear() # Clear at start

        self._connection_thread = threading.Thread(target=self._connection_loop, name="IBKRConnectionLoop", daemon=True)
        self._connection_thread.start()

    def stop(self):
        logger.info("ConnectionManager: Stop requested.")
        self.stop_event.set() # Signal the connection loop to stop
        self._keepalive_stop_event.set() # Signal the keepalive loop to stop

        if self._keepalive_thread and self._keepalive_thread.is_alive():
            logger.info("ConnectionManager: Waiting for keepalive thread to terminate...")
            self._keepalive_thread.join(timeout=2)
            if self._keepalive_thread.is_alive():
                logger.warning("ConnectionManager: Keepalive thread did not terminate in time.")
        self._keepalive_thread = None

        # No direct client.disconnect() here, as the loop should handle it on seeing stop_event.
        # If the loop is stuck, the join timeout will trigger.
        # Forcing a disconnect here might race with the loop's own disconnect logic.

        if self._connection_thread and self._connection_thread.is_alive():
            logger.info("ConnectionManager: Waiting for connection thread to terminate...")
            self._connection_thread.join(timeout=self.config.connect_timeout_seconds + 5) # Generous timeout
            if self._connection_thread.is_alive():
                logger.warning("ConnectionManager: Connection thread did not terminate gracefully. Forcing client disconnect.")
                if self.client.isConnected():
                    self.client.disconnect() # Force disconnect if thread is stuck
            else:
                 logger.info("ConnectionManager: Connection thread terminated.")
        else:
            logger.info("ConnectionManager: No active connection thread to stop.")

        # Final check on client connection status after attempting to stop the loop
        if self.client.isConnected(): # This check is important
            logger.warning("ConnectionManager: Client still connected after stop. Attempting final disconnect.")
            self.client.disconnect()

        logger.info("ConnectionManager: Stop process completed.")


    def is_api_ready(self) -> bool:
        # API is ready if general connected_event is set AND nextValidId has been processed.
        return self.connected_event.is_set() and self._next_valid_id_event.is_set()

    # --- Callbacks for EWrapper to signal ConnectionManager ---
    def signal_api_ready(self): # Called by EWrapper.nextValidId
        logger.info("ConnectionManager: Signal API ready received (from EWrapper.nextValidId), _next_valid_id_event is set.")
        self._next_valid_id_event.set()
        # self.connected_event.set() # DO NOT set connected_event here; _connect_attempt will set it after grace period.
        self.connection_lost_event.clear() # Clear any prior lost state, as we've received nextValidId

    def signal_critical_post_connect_error(self, error_code: int, error_string: str):
        logger.error(f"ConnectionManager: Received critical post-connect error: Code={error_code}, Msg='{error_string}'. Signaling failure.")
        self._critical_post_connect_error_event.set()
        # This event will be checked by _connect_attempt during its grace period.
        # It does not immediately clear connected_event or next_valid_id_event, as _connect_attempt
        # might still be in the process of deciding if the connection is fully up.
        # If _connect_attempt has already passed the grace period, this signal would be late,
        # and a subsequent stale check or other error might be needed to recycle.
        # However, the primary design is for errors *during* the grace period.

    def signal_connection_lost(self): # Called by EWrapper.connectionClosed or EWrapper.error for critical errors
        logger.warning("ConnectionManager: Signal connection lost received (from EWrapper or internal).")
        self.connected_event.clear()
        self._next_valid_id_event.clear()
        self._critical_post_connect_error_event.clear() # Ensure this is also cleared
        self.connection_lost_event.set()

        # Stop keepalive thread on connection loss
        self._keepalive_stop_event.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            logger.debug("ConnectionManager: Attempting to join keepalive thread due to connection loss.")
            self._keepalive_thread.join(timeout=1) # Short timeout
            if self._keepalive_thread.is_alive():
                    logger.warning("ConnectionManager: Keepalive thread did not stop in time after connection loss.")
        self._keepalive_thread = None

        # The EClient.run() thread will likely terminate or be unblocked after this.
        # The _connection_loop will detect !is_api_ready() and attempt reconnection.
        if self.client.isConnected(): # If wrapper signals lost but EClient still thinks it's connected
            logger.info("ConnectionManager: EClient still reports connected, forcing disconnect due to wrapper signal.")
            self.client.disconnect()
        self._api_thread_active = False

    def get_client(self) -> EClient:
        return self.client

    def get_wrapper(self) -> Any: # EWrapper
        return self.wrapper

    # Placeholder for getting next order ID, actual logic in EWrapper
    # def get_next_order_id(self) -> Optional[int]:
    //     if hasattr(self.wrapper, 'get_next_order_id_from_wrapper_logic'):
    //         return self.wrapper.get_next_order_id_from_wrapper_logic()
    //     logger.error("Wrapper does not have get_next_order_id_from_wrapper_logic method.")
    //     return None
