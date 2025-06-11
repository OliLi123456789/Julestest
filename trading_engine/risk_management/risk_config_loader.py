import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_RISK_CONFIG_CONTENT: Dict[str, Any] = {
    "max_order_value_usd": 100000.0,
    "max_position_value_usd_per_symbol": {
        "DEFAULT": 200000.0,
        "AAPL": 300000.0
    },
    "allowed_symbols": ["AAPL", "GOOG", "MSFT", "TSLA", "EUR.USD", "BTC.USD", "TESTSYM"],
    "max_order_quantity_per_symbol": {
        "DEFAULT": 1000.0,
        "EUR.USD": 500000.0,
        "TESTSYM": 500.0,
    },
    "block_market_orders_for_illiquid": ["SOME_ILLIQUID_SYM"],
    # Example of other potential rules:
    # "max_concurrent_orders_per_user": 20,
    # "block_short_selling_for_symbols": ["SOME_NON_SHORTABLE_SYM"],
    # "allowed_order_types": ["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAIL"],
    # "max_daily_loss_limit_usd": 10000.0,
    # "margin_usage_limit_percent": 80.0
}

def load_risk_config_from_file(file_path: str = "risk_config.json") -> Dict[str, Any]:
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
            logger.info(f"Risk configuration loaded successfully from {file_path}.")
            return config
    except FileNotFoundError:
        logger.warning(f"Risk config file '{file_path}' not found. Using default risk configuration.")
        # Optionally, create the default file if it doesn't exist
        try:
            with open(file_path, 'w') as f:
                json.dump(DEFAULT_RISK_CONFIG_CONTENT, f, indent=2)
            logger.info(f"Created default risk config file at '{file_path}'. Please review and adjust as needed.")
        except Exception as e_write:
            logger.error(f"Could not write default risk config to '{file_path}': {e_write}")
        return DEFAULT_RISK_CONFIG_CONTENT
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from risk config file '{file_path}': {e}. Using default config.")
        return DEFAULT_RISK_CONFIG_CONTENT
    except Exception as e:
        logger.error(f"Unexpected error loading risk config from '{file_path}': {e}. Using default config.", exc_info=True)
        return DEFAULT_RISK_CONFIG_CONTENT
