import logging
import sys
import os
# Ensure python-json-logger is notionally available
# For the tool environment, we assume it would be installed.
try:
    from python_json_logger import jsonlogger
except ImportError:
    # Provide a mock/fallback if the library isn't in the test environment
    # This allows the rest of the code to be syntactically correct.
    print("WARNING: python-json-logger not found. Using basic formatter for trading_engine.")
    class MockJsonFormatter(logging.Formatter):
        def format(self, record):
            # Basic format if jsonlogger is not available
            return super().format(record)
    jsonlogger = type('JsonLoggerModule', (object,), {'JsonFormatter': MockJsonFormatter})


# Store the initial TRADING_ENGINE_LOG_LEVEL at import time,
# as environment variables might be checked only once by some logging setups.
TRADING_ENGINE_LOG_LEVEL_ENV = os.getenv("TRADING_ENGINE_LOG_LEVEL", "INFO").upper()

def setup_trading_engine_logging(log_level_str: Optional[str] = None):
    """
    Sets up structured JSON logging for the 'trading_engine' root logger.
    """
    if log_level_str is None:
        log_level_str = TRADING_ENGINE_LOG_LEVEL_ENV

    # Get the specific logger for 'trading_engine'
    # This allows other parts of a larger application (if any) to use a different root logger setup.
    # If this is the absolute root, logging.getLogger() would suffice.
    # For modularity, targeting 'trading_engine' specifically.
    logger = logging.getLogger("trading_engine")

    # Clear any existing handlers from this specific logger to avoid duplicate logs
    # or conflicts if this function is called multiple times.
    if logger.hasHandlers():
        logger.handlers.clear()

    # Prevent messages from being passed to the root logger if it has its own handlers,
    # to avoid duplicate output if the root logger is also configured (e.g. by basicConfig).
    logger.propagate = False

    log_handler = logging.StreamHandler(sys.stdout) # Or sys.stderr for errors

    # Example format string including common fields useful for structured logging
    # These will become fields in the JSON log.
    formatter_str = '%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(threadName)s %(message)s'

    # Custom fields can be added globally to the formatter or per log record.
    # Example of adding a static custom field (e.g., service name, version)
    # class CustomJsonFormatter(jsonlogger.JsonFormatter):
    #     def add_fields(self, log_record, record, message_dict):
    #         super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
    #         if not log_record.get('service_context'):
    #             log_record['service_context'] = {'service': 'trading_engine', 'version': '0.1.0'}

    formatter = jsonlogger.JsonFormatter(
        formatter_str,
        # rename_fields={'levelname': 'level', 'asctime': 'timestamp'}, # Optional: rename fields
        # timestamp=True # Handled by asctime in format string
    )

    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    try:
        log_level = getattr(logging, log_level_str.upper())
    except AttributeError:
        log_level = logging.INFO
        # Use the root logger for this initial warning as 'trading_engine' logger might not be fully set up.
        logging.getLogger().warning(f"Invalid TRADING_ENGINE_LOG_LEVEL '{log_level_str}'. Defaulting to INFO for 'trading_engine' logger.")

    logger.setLevel(log_level)

    # Test message to confirm setup
    # logger.info("Trading Engine JSON logging configured.", extra={'initial_log_level': log_level_str})

# Example of how to call it early:
# if __name__ == 'trading_engine.config.logging_config': # Or similar check for main module
#     setup_trading_engine_logging()
# Or, more typically, called from the application's main entry point.
