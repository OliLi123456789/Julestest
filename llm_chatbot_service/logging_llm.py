# llm_chatbot_service/logging_llm.py
import logging
import sys
import os
from typing import Optional # Added for type hint

# Conditional import for python-json-logger
try:
    from python_json_logger import jsonlogger
    JSON_LOGGER_AVAILABLE_LLM = True
except ImportError:
    JSON_LOGGER_AVAILABLE_LLM = False
    # Define a mock JsonFormatter if python-json-logger is not available.
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
            if record.exc_info: log_entry['exc_info'] = self.formatException(record.exc_info)
            if record.stack_info: log_entry['stack_info'] = self.formatStack(record.stack_info)

            # Include 'extra' fields passed to logger
            # Based on how python-json-logger handles 'extra'
            standard_keys = {'asctime', 'args', 'created', 'exc_info', 'exc_text', 'filename',
                             'funcName', 'levelname', 'levelno', 'lineno', 'message', 'module',
                             'msecs', 'msg', 'name', 'pathname', 'process', 'processName',
                             'relativeCreated', 'stack_info', 'thread', 'threadName'}
            extra_data = {key: value for key, value in record.__dict__.items() if key not in standard_keys}
            if extra_data: log_entry.update(extra_data)

            try: import json; return json.dumps(log_entry, default=str)
            except Exception: return super().format(record)

    jsonlogger_module_mock = type('JsonLoggerModuleMock', (object,), {'JsonFormatter': MockJsonFormatter})
    jsonlogger = jsonlogger_module_mock


LLM_SERVICE_ROOT_LOGGER_NAME = "LLMChatbotService" # Root logger for this service

def setup_llm_service_logging(
    log_level_str: Optional[str] = None,
    force_reconfigure: bool = False # Renamed from force_reconfigure_root for clarity
):
    """
    Configures the root logger for the LLM Chatbot Service.
    Uses JSON formatting if python-json-logger is available.
    """
    if log_level_str is None:
        log_level_str = os.getenv("LLM_SERVICE_LOG_LEVEL", "INFO").upper()

    logger = logging.getLogger(LLM_SERVICE_ROOT_LOGGER_NAME)

    if logger.handlers and getattr(logger, '_is_llm_service_configured', False) and not force_reconfigure:
        logger.debug(f"Logger '{LLM_SERVICE_ROOT_LOGGER_NAME}' already configured by this setup. Skipping.")
        return

    # Clear existing handlers for this specific logger to apply new config
    logger.handlers.clear()
    # If this is truly the "root" for this service, propagate should be False
    # to avoid duplication if a higher-level root logger (e.g. from Uvicorn) also logs.
    logger.propagate = False

    log_handler = logging.StreamHandler(sys.stdout) # Output to stdout for containerized environments

    # Example format string for jsonlogger, can include more default fields
    # python-json-logger automatically includes keys from 'extra'
    formatter_str = '%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s'

    if JSON_LOGGER_AVAILABLE_LLM:
        formatter = jsonlogger.JsonFormatter(formatter_str)
        log_handler.setFormatter(formatter)
    else:
        basic_formatter_str = f'%(asctime)s - {LLM_SERVICE_ROOT_LOGGER_NAME} - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
        formatter = logging.Formatter(basic_formatter_str)
        log_handler.setFormatter(formatter)
        # Warn once if JSON logger is not available using a global attribute on logging module
        if not hasattr(logging, '_warned_json_missing_llm_service'):
            logger.warning("python-json-logger not found for LLM Service. Using basic text logging format.")
            setattr(logging, '_warned_json_missing_llm_service', True)

    logger.addHandler(log_handler)

    try:
        log_level_int = getattr(logging, log_level_str)
    except AttributeError:
        log_level_int = logging.INFO
        logger.warning(f"Invalid LLM_SERVICE_LOG_LEVEL '{log_level_str}'. Defaulting to INFO.")

    logger.setLevel(log_level_int)
    setattr(logger, '_is_llm_service_configured', True) # Mark as configured by this function

    logger.info(
        f"{LLM_SERVICE_ROOT_LOGGER_NAME} logging configured. Level: {log_level_str}, JSON: {JSON_LOGGER_AVAILABLE_LLM}."
    )

if __name__ == '__main__':
    print("--- Testing Default Logging (JSON if available, INFO level) ---")
    setup_llm_service_logging()
    root_logger = logging.getLogger(LLM_SERVICE_ROOT_LOGGER_NAME)
    root_logger.debug("This root debug message should NOT appear (INFO default).")
    root_logger.info("This root info message should appear.")

    child_logger = logging.getLogger(f"{LLM_SERVICE_ROOT_LOGGER_NAME}.TestModule")
    child_logger.debug("This child debug message should NOT appear.")
    child_logger.info("This child info message should appear.")
    child_logger.warning("A warning from child.", extra={"custom_field": "value123"})
    try: 1/0
    except ZeroDivisionError: child_logger.error("ZeroDivision Test", exc_info=True)

    print("\n--- Testing DEBUG Logging (JSON if available) ---")
    setup_llm_service_logging(log_level_str="DEBUG", force_reconfigure=True)
    root_logger.debug("This root debug message SHOULD appear now.")
    child_logger.debug("This child debug message SHOULD also appear now.")

    print("\n--- Testing Basic Text Logging (by forcing JSON_LOGGER_AVAILABLE_LLM=False temporarily) ---")
    original_json_flag = JSON_LOGGER_AVAILABLE_LLM
    JSON_LOGGER_AVAILABLE_LLM = False
    setup_llm_service_logging(log_level_str="DEBUG", force_reconfigure=True)
    root_logger.info("Info message with basic text formatting (JSON forced off).")
    root_logger.debug("Debug message with basic text formatting (JSON forced off).", extra={'another_field': 456})
    JSON_LOGGER_AVAILABLE_LLM = original_json_flag # Restore

    print(f"\npython-json-logger was {'AVAILABLE' if original_json_flag else 'NOT AVAILABLE'} during this test run.")
