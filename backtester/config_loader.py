# backtester/config_loader.py
import yaml
import logging
from typing import Dict, Any, Optional
import os
import datetime # For date filtering, though not directly used in this file's logic

logger = logging.getLogger(__name__)
DEFAULT_CONFIG_FILENAME = "backtest_config.yaml"
DEFAULT_CONFIGS_DIR = "configs" # Default subdirectory for configs

def load_backtest_config(config_filepath: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Loads the backtest configuration from a YAML file.
    Searches for default config if no specific path is provided.
    """
    if config_filepath is None:
        # Search in common locations relative to where the script might be run from
        # or a known project structure.
        # 1. Current working directory
        # 2. ./configs/
        # 3. ./backtester/configs/ (if running from project root and config is inside backtester)
        potential_paths = [
            DEFAULT_CONFIG_FILENAME,
            os.path.join(DEFAULT_CONFIGS_DIR, DEFAULT_CONFIG_FILENAME),
            os.path.join("backtester", DEFAULT_CONFIGS_DIR, DEFAULT_CONFIG_FILENAME)
        ]
        for path_option in potential_paths:
            if os.path.exists(path_option):
                config_filepath = path_option
                break
        if config_filepath is None:
            logger.error(f"Default config '{DEFAULT_CONFIG_FILENAME}' not found in standard search paths: {potential_paths}")
            return None

    logger.info(f"Loading backtest configuration from: {config_filepath}")
    try:
        with open(config_filepath, 'r') as f:
            config = yaml.safe_load(f)

        # Basic validation for key sections
        required_sections = ['general_settings', 'data_handler', 'strategy', 'portfolio_settings']
        for section in required_sections:
            if section not in config:
                logger.error(f"Configuration file '{config_filepath}' is missing required section: '{section}'")
                return None

        logger.info("Backtest configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_filepath}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {config_filepath}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading config {config_filepath}: {e}", exc_info=True)
        return None

def create_sample_config(filepath: str = os.path.join(DEFAULT_CONFIGS_DIR, DEFAULT_CONFIG_FILENAME)):
    """
    Creates a sample backtest_config.yaml file.
    """
    sample_config = {
        "general_settings": {
            "start_date": "2023-01-01", # Inclusive
            "end_date": "2023-12-31",   # Inclusive
            "initial_capital": 100000.0
        },
        "data_handler": {
            "type": "csv", # Only 'csv' supported for now
            "csv_directory": "path/to/your/csv_data", # Relative to project root or absolute
            "symbols": ["AAPL", "GOOG"], # List of symbols to backtest
            "ffill_missing_data": True # Forward-fill missing data points
        },
        "strategy": {
            "name": "BuyAndHoldStrategy", # Name of the strategy class
            "parameters": { # Parameters to pass to the strategy's __init__
                "initial_quantity": 10 # Example parameter for BuyAndHoldStrategy
                # Add other strategy-specific parameters here
            }
        },
        "portfolio_settings": {
            "slippage_model": "percentage", # "none", "fixed_per_share", "percentage"
            "slippage_fixed_amount": 0.01,
            "slippage_percentage": 0.0005, # 0.05%
            "commission_model": "per_share", # "none", "fixed_per_trade", "per_share", "percentage_value"
            "commission_fixed_amount": 1.00,
            "commission_per_share": 0.005,
            "commission_percentage_value": 0.001, # 0.1%
            "commission_min_per_trade": 1.00
        },
        "output_settings": {
            "results_directory": "backtest_results",
            "save_metrics": True,
            "save_portfolio_history": True,
            "save_trades_log": True,
            "filename_prefix_parts": ["strategy_name", "start_date", "end_date"], # Controls prefix elements
            "run_id_timestamp_format": "%Y%m%d_%H%M%S" # Just the timestamp part for uniqueness
        },
        "walk_forward_settings": {
            "enabled": False,
            "in_sample_period": "180D", # Duration of the in-sample (training) period
            "out_of_sample_period": "60D", # Duration of the out-of-sample (validation) period
            "step_size": "60D" # How much the start of the in-sample window advances each step
                               # If not specified, defaults to out_of_sample_period.
            # "optimization_parameters": { # Optional: For strategies that support optimization
            #    "param_name_1": {"start": 10, "end": 50, "step": 5},
            #    "param_name_2": {"values": [0.01, 0.05, 0.1]}
            # }
        }
    }
    try:
        # Ensure the directory for the config file exists
        config_dir = os.path.dirname(filepath)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)
            logger.info(f"Created directory for sample config: {config_dir}")

        with open(filepath, 'w') as f:
            yaml.dump(sample_config, f, sort_keys=False, indent=2)
        logger.info(f"Sample configuration file created at: {filepath}")
    except Exception as e:
        logger.error(f"Error creating sample configuration file at {filepath}: {e}", exc_info=True)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Example: Create a sample config in a 'sample_configs' subdirectory
    sample_config_path = os.path.join("sample_configs", DEFAULT_CONFIG_FILENAME)

    # Check if it exists, if not, create it
    if not os.path.exists(sample_config_path):
        create_sample_config(sample_config_path)
    else:
        logger.info(f"Sample config already exists at {sample_config_path}, not overwriting.")

    # Example: Load the created sample config
    loaded_config = load_backtest_config(sample_config_path)

    if loaded_config:
        logger.info(f"Successfully loaded configuration for strategy: {loaded_config['strategy']['name']}")
        logger.info(f"General Settings: {loaded_config['general_settings']}")
        # print(loaded_config) # For full config print
    else:
        logger.error("Failed to load configuration.")
