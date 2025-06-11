# news_service/logging_setup.py
import logging
import sys
import os

# Attempt to import python-json-logger, with a fallback mock for environments where it's not installed.
try:
    from python_json_logger import jsonlogger
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False
    # Define a mock JsonFormatter if python-json-logger is not available.
    # This allows the rest of the code to be structured for JSON logging,
    # falling back to a more basic JSON-like string format if the library is missing.
    class MockJsonFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                'timestamp': self.formatTime(record, self.datefmt or '%Y-%m-%dT%H:%M:%S.%fZ'),
                'level': record.levelname,
                'name': record.name,
                'module': record.module,
                'funcName': record.funcName,
                'lineno': record.lineno,
                'message': record.getMessage(),
            }
            # Add exception info if present
            if record.exc_info:
                log_entry['exc_info'] = self.formatException(record.exc_info)
            if record.stack_info:
                log_entry['stack_info'] = self.formatStack(record.stack_info)

            # Include any extra fields passed to the logger
            extra_props = record.__dict__.get('extra', {})
            if isinstance(extra_props, dict):
                 log_entry.update(extra_props)

            # For this mock, just dump to string; real jsonlogger handles complex objects better.
            try:
                import json # Local import
                return json.dumps(log_entry, default=str) # default=str for non-serializable
            except Exception:
                return super().format(record) # Fallback to basic Formatter if json.dumps fails

    # Create a dummy jsonlogger module object to hold the MockJsonFormatter
    jsonlogger_module_mock = type('JsonLoggerModuleMock', (object,), {'JsonFormatter': MockJsonFormatter})
    jsonlogger = jsonlogger_module_mock # Assign mock to be used if import failed

# Root logger name for all external data services (Stage 8 components)
EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME = "ExternalDataServices"

def setup_external_data_logging(
    log_level_str: Optional[str] = None,
    service_name_override: Optional[str] = None,
    force_reconfigure_root: bool = False # If true, will reconfigure the root logger for these services
):
    """
    Configures a root logger for external data services or a specific service logger.
    Uses JSON formatting if python-json-logger is available.
    """
    if log_level_str is None:
        log_level_str = os.getenv("EXTERNAL_DATA_SERVICES_LOG_LEVEL", "INFO").upper()

    logger_to_configure = logging.getLogger(service_name_override or EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME)

    # Avoid duplicate handlers if called multiple times unless forced for the root external data logger
    if logger_to_configure.handlers and getattr(logger_to_configure, '_configured_by_eds_setup', False) and not force_reconfigure_root :
        if logger_to_configure.name == EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME: # Only skip if it's our root and already configured
            logger_to_configure.debug(f"Logger '{logger_to_configure.name}' already configured by this setup. Skipping.")
            return
        # For child loggers, allow them to get the root configuration if they don't have specific handlers.

    # Clear existing handlers for this specific logger to apply new config
    # This is important if reconfiguring or if default handlers were attached.
    if logger_to_configure.name == EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME or service_name_override:
        logger_to_configure.handlers.clear()
        logger_to_configure.propagate = False # Prevent duplication if root logger is also configured by something else

    log_handler = logging.StreamHandler(sys.stdout) # Use stdout for container logs

    # Example format string for jsonlogger, can include more default fields
    formatter_fields = [
        'asctime', 'levelname', 'name', 'module', 'funcName',
        'lineno', 'message', 'exc_info', 'stack_info'
    ]
    formatter_str = ' '.join([f'%({field})s' for field in formatter_fields])

    if JSON_LOGGER_AVAILABLE:
        formatter = jsonlogger.JsonFormatter(formatter_str)
        log_handler.setFormatter(formatter)
    else:
        # Basic text fallback if python-json-logger is not installed
        basic_formatter_str = f'%(asctime)s - {logger_to_configure.name} - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
        formatter = logging.Formatter(basic_formatter_str)
        log_handler.setFormatter(formatter)
        if logger_to_configure.name == EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME or not logger_to_configure.hasHandlers(): # Log warning once from root
            logger_to_configure.warning("python-json-logger not found. Using basic text logging format.")

    logger_to_configure.addHandler(log_handler)

    try:
        log_level_int = getattr(logging, log_level_str)
    except AttributeError:
        log_level_int = logging.INFO
        logger_to_configure.warning(f"Invalid log level '{log_level_str}'. Defaulting to INFO.")

    logger_to_configure.setLevel(log_level_int)
    setattr(logger_to_configure, '_configured_by_eds_setup', True) # Mark as configured

    # Log initial message with the configured logger
    logger_to_configure.info(
        f"Logging for '{logger_to_configure.name}' configured. Level: {log_level_str}, JSON: {JSON_LOGGER_AVAILABLE}."
    )

if __name__ == '__main__':
    print("--- Testing Default Logging (JSON if available) ---")
    setup_external_data_logging(log_level_str="DEBUG") # Setup root for external data services

    # Example of a child logger inheriting from the root external data logger
    child_logger_test = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.MyTestModule")
    # No need to call setup_external_data_logging for child_logger_test if root is configured and propagate=True (default)
    # However, our setup uses propagate=False for the root one it configures.
    # So, child loggers should also call setup or use getLogger which will then inherit level if not set.
    # For simplicity, often just configuring the root for the service is enough.
    # If child loggers are used, ensure they get configured or propagate.
    # Let's test a direct child logger. If root is configured, its level applies unless child sets its own.

    child_logger_test.debug("This is a debug message from child_logger_test.")
    child_logger_test.info("This is an info message from child_logger_test.")
    child_logger_test.warning("This is a warning from child_logger_test.", extra={'custom_field': 'custom_value'})
    try:
        raise ValueError("A test error for logging.")
    except ValueError:
        child_logger_test.error("An error event occurred.", exc_info=True)

    print("\n--- Testing Basic Text Logging (by forcing JSON_LOGGER_AVAILABLE=False temporarily) ---")
    original_json_available_flag = JSON_LOGGER_AVAILABLE
    JSON_LOGGER_AVAILABLE = False # Temporarily override for this test
    setup_external_data_logging(log_level_str="INFO", service_name_override="TestServiceBasicLog", force_reconfigure_root=True)
    basic_logger_test = logging.getLogger("TestServiceBasicLog.Module")
    basic_logger_test.info("Info message with basic text formatting.", extra={'another_field': 123})
    basic_logger_test.error("Error message with basic text formatting.")
    JSON_LOGGER_AVAILABLE = original_json_available_flag # Restore flag

    print("\n--- Testing direct child logger after root setup (should use root's handlers/level if propagate=True) ---")
    # With propagate=False on the root, direct children won't use its handlers unless they also get configured.
    # If we want hierarchical dot-based naming to just work, root ExternalDataServices should not set propagate=False
    # or each module must get its logger and ensure it has a handler.
    # Let's reconfigure the root logger with propagate = True for this part of test

    # logging.getLogger(EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME).handlers.clear() # Clear previous
    # logging.getLogger(EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME).propagate = True # Test propagation
    # setup_external_data_logging(log_level_str="DEBUG") # Re-setup (will use existing handlers if not cleared)

    # For this project, modules will get loggers like:
    # logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.{__name__}")
    # And the initial setup_external_data_logging() on the EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    # will provide the base handler for all of them. The level set on root will apply unless child sets a more specific one.
    # Let's re-run setup on the root to ensure it's clean for this test.
    setup_external_data_logging(log_level_str="DEBUG", force_reconfigure_root=True)
    module_logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.module_example")
    module_logger.debug("Debug message from module_logger using root setup. Custom field.", extra={"field": "module_value"})

    # Test if python-json-logger was actually available
    print(f"\npython-json-logger was {'AVAILABLE' if original_json_available_flag else 'NOT AVAILABLE'} during this test run.")
