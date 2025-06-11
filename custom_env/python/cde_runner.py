# custom_env/python/cde_runner.py
import logging
import os
import sys
import importlib # For dynamic strategy loading
import datetime
from typing import Dict, Any, Optional, Type, List # Adjusted imports
import pandas as pd # For type hint in on_bar, and for dummy data creation in main
import yaml # For sample config update in main

# --- Setup CDE_Runner's own logger ---
# This logger is for the runner itself. SDK and Strategy will use sdk.log().
logger = logging.getLogger("CDE_RUNNER")
if not logger.handlers: # Configure only if no handlers are already set (e.g. by root config)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout) # Explicitly use stdout
    formatter = logging.Formatter('%(asctime)s - CDE_RUNNER - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False # Don't pass to root logger if we configured it here

# --- SDK and Backtester Imports ---
# These are crucial. cde_runner assumes backtester package is in PYTHONPATH.
try:
    from backtester.config_loader import load_backtest_config, create_sample_config
    from backtester.data import CsvDataHandler, AbstractDataHandler # For type hint
    from backtester.portfolio import Portfolio, OrderStatus, FillEvent # For type hint
    # BacktestEngine class itself is not directly used here, but its concepts are replicated.
    from backtester.performance import PerformanceCalculator
    from backtester.results_writer import ResultsWriter
    BACKTESTER_AVAILABLE = True
except ImportError as e:
    logger.critical(f"Failed to import backtester components: {e}. Ensure 'backtester' package is in PYTHONPATH.", exc_info=True)
    BACKTESTER_AVAILABLE = False
    # Define dummy classes for type hints if needed, or exit if critical.
    # For this runner, if backtester isn't available, it can't run.
    # sys.exit(1) # Or handle gracefully in run_cde_backtest

import sdk # From custom_env/python (should be in PYTHONPATH or same dir)


# --- Strategy Registry (Optional but good for managing multiple strategies) ---
# AVAILABLE_STRATEGIES_CDE: Dict[str, Type[sdk.BaseStrategy]] = {}
# def register_strategy_cde(name: str, strategy_class: Type[sdk.BaseStrategy]):
#     AVAILABLE_STRATEGIES_CDE[name] = strategy_class
#     logger.info(f"Registered strategy '{name}' in CDE Runner.")


def run_cde_backtest(config_filepath: str,
                     strategy_module_name: str, # e.g., "user_strategy" (filename without .py)
                     strategy_class_name: str   # e.g., "MyMomentumStrategy"
                    ):
    if not BACKTESTER_AVAILABLE:
        logger.critical("Backtester package not available. CDE backtest cannot run.")
        return

    # 1. Configure SDK Logging (from config or defaults)
    temp_config_for_sdk_log = load_backtest_config(config_filepath) # Load once for this
    sdk_log_settings = temp_config_for_sdk_log.get("sdk_settings", {}) if temp_config_for_sdk_log else {}
    sdk_log_level_str = sdk_log_settings.get("log_level", "INFO")
    sdk_json_logging = sdk_log_settings.get("json_logs", True)
    sdk.setup_sdk_logging(level=getattr(logging, sdk_log_level_str.upper(), logging.INFO),
                          json_format=sdk_json_logging, force_setup=True) # Force SDK to use this config

    logger.info(f"--- CDE: Initializing Backtest ---")
    logger.info(f"Config file: {config_filepath}")
    logger.info(f"Strategy module: {strategy_module_name}, class: {strategy_class_name}")

    # 2. Load Full Configuration
    config = load_backtest_config(config_filepath) # Reload or use temp_config_for_sdk_log
    if not config:
        logger.critical(f"Failed to load backtest config from {config_filepath}. Exiting.")
        return

    gs_cfg = config['general_settings']
    dh_cfg = config['data_handler']
    # Strategy params will be taken from config, but class is loaded dynamically
    strat_cfg_params = config.get('strategy', {}).get('parameters', {})
    port_cfg = config['portfolio_settings']
    output_cfg = config.get('output_settings', {})

    # 3. Dynamically Load User Strategy Class
    try:
        user_module = importlib.import_module(strategy_module_name)
        UserStrategyClass = getattr(user_module, strategy_class_name)
        if not issubclass(UserStrategyClass, sdk.BaseStrategy):
            logger.critical(f"Strategy class {strategy_class_name} from {strategy_module_name} must inherit from sdk.BaseStrategy.")
            return
    except Exception as e:
        logger.critical(f"Failed to load strategy {strategy_class_name} from {strategy_module_name}: {e}", exc_info=True)
        return

    # 4. Instantiate Backtester Components
    logger.info(f"DataHandler symbols: {dh_cfg['symbols']}")
    data_handler: AbstractDataHandler = CsvDataHandler(
        csv_dir=dh_cfg['csv_directory'], symbols=dh_cfg['symbols'],
        ffill=dh_cfg.get('ffill_missing_data', True),
        start_date=gs_cfg.get('start_date'), end_date=gs_cfg.get('end_date')
    )

    strategy_id = f"{strategy_class_name}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    strategy_instance: sdk.BaseStrategy = UserStrategyClass(
        strategy_id=strategy_id,
        symbols_of_interest=dh_cfg['symbols'], # Strategy interested in all symbols from data handler
        **strat_cfg_params
    )

    portfolio = Portfolio(initial_cash=float(gs_cfg['initial_capital']), data_handler=data_handler, **port_cfg)

    # Simplified context object mimicking engine parts needed by SDK's global context
    class CDEBacktestContext:
        def __init__(self, conf):
            self.pending_execution_orders: List[Any] = [] # List of backtester.portfolio.OrderEvent
            self.config = conf # Full config dict
            self.current_market_data: Dict[str, Any] = {} # Populated by CDE runner loop
            self.last_run_calculator_instance: Optional[PerformanceCalculator] = None # For results writer

    cde_context = CDEBacktestContext(config)
    strategy_instance._set_sdk_internals(oms_interface=None, sdk_context_ref=sdk) # Pass SDK module itself for global access

    # 5. Main Backtest Loop
    logger.info(f"CDE_Runner: Starting backtest loop for strategy '{strategy_instance.strategy_id}'...")
    sdk.set_backtest_context(cde_context, portfolio, None) # Initial SDK context

    current_processed_timestamp: Optional[datetime.datetime] = None

    try:
        strategy_instance.on_start()

        for timestamp, market_data_bundle in data_handler.stream_next_bar():
            sdk.CURRENT_TIMESTAMP = timestamp # Critical: Update global timestamp for SDK functions
            cde_context.current_market_data = market_data_bundle
            current_processed_timestamp = timestamp
            logger.debug(f"Runner: Processing bar for {timestamp}")

            executed_fills_this_bar: List[FillEvent] = []
            remaining_pending_orders: List[Any] = [] # backtester.portfolio.OrderEvent

            for order_to_exec in cde_context.pending_execution_orders:
                if order_to_exec.status != OrderStatus.PENDING: continue # Should only be PENDING

                mkt_event = cde_context.current_market_data.get(order_to_exec.symbol)
                if mkt_event and mkt_event.timestamp == timestamp: # Ensure market data is for current bar
                    fill = portfolio.simulate_order_execution(order_to_exec, mkt_event)
                    if fill: executed_fills_this_bar.append(fill)
                    elif order_to_exec.status == OrderStatus.PENDING: remaining_pending_orders.append(order_to_exec)
                else: remaining_pending_orders.append(order_to_exec) # Keep if no market data for symbol this bar
            cde_context.pending_execution_orders = remaining_pending_orders

            for fill in executed_fills_this_bar:
                portfolio.process_fill(fill)
                fill_info = {"timestamp": fill.timestamp.isoformat(), "symbol": fill.symbol,
                                "quantity": fill.quantity, "direction": fill.direction.value,
                                "fill_price": fill.fill_price, "commission": fill.commission,
                                "realized_pnl": getattr(fill, 'realized_pnl_for_this_fill', None)}
                try: strategy_instance.on_fill(fill_info)
                except Exception as e_fill_strat: logger.error(f"Error in strategy on_fill: {e_fill_strat}", exc_info=True)

            portfolio.update_timeindex(timestamp, cde_context.current_market_data)

            sdk_bar_bundle = {sym: {**mdevent.data, 'timestamp': mdevent.timestamp.isoformat()+"Z"}
                              for sym, mdevent in market_data_bundle.items()}
            try: strategy_instance.on_bar(timestamp, sdk_bar_bundle)
            except Exception as e_bar_strat: logger.error(f"Error in strategy on_bar: {e_bar_strat}", exc_info=True)

        strategy_instance.on_stop()
    except Exception as e_loop:
        logger.critical(f"CDE_Runner: Critical error in backtest loop: {e_loop}", exc_info=True)
        try: strategy_instance.on_stop()
        except: pass
    finally:
        sdk.set_backtest_context(None, None, None) # Clear SDK context
        logger.info("CDE_Runner: Backtest loop finished.")

    # 6. Performance Calculation & Results Saving
    if portfolio.portfolio_value_over_time: # Check if any MTM was recorded
        logger.info("CDE_Runner: Calculating performance...")
        risk_free = gs.get('risk_free_rate_annual', 0.0)
        ppy = gs.get('periods_in_year', 252)
        calculator = PerformanceCalculator(
            portfolio_value_history=portfolio.portfolio_value_over_time,
            trades=portfolio.trades, initial_capital=portfolio.initial_cash
        )
        metrics = calculator.calculate_metrics(risk_free_rate_annual=risk_free, periods_in_year=ppy)
        calculator.display_metrics(metrics_dict_to_display=metrics)
        cde_context.last_run_calculator_instance = calculator

        if output_cfg and (output_cfg.get("save_metrics") or output_cfg.get("save_portfolio_history") or output_cfg.get("save_trades_log")):
            logger.info("CDE_Runner: Saving backtest results...")
            results_writer = ResultsWriter(output_config=output_cfg, base_config=config)
            results_writer.save_all_results(
                metrics=metrics,
                portfolio_history_df=cde_context.last_run_calculator_instance.portfolio_df,
                trades_list=portfolio.trades
            )
    else:
        logger.warning("CDE_Runner: No portfolio value history recorded. Skipping performance calculation and results saving.")
        metrics = None # No metrics to return

    logger.info(f"CDE_Runner: --- Backtest Run Complete for Strategy '{strategy_instance.strategy_id}' ---")
    return metrics


if __name__ == '__main__':
    # This main block is for direct testing of the CDE runner itself.
    # It requires a config file and a user strategy module.
    # Standard logging setup for this test run
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info("CDE_Runner __main__ started. Creating dummy strategy and config for test.")

    # Create a dummy user_strategy.py for testing the runner
    # This strategy module will be dynamically imported by run_cde_backtest.
    dummy_strategy_module_name = "my_cde_test_strategy"
    dummy_strategy_class_name = "TestStrategyForCDERunner"
    user_strat_content = f"""
import sdk # Custom env SDK
import datetime

class {dummy_strategy_class_name}(sdk.BaseStrategy):
    def __init__(self, strategy_id: str, symbols_of_interest: list, **strategy_params):
        super().__init__(strategy_id, symbols_of_interest, **strategy_params)
        # Explicitly get parameters used by this strategy
        self.my_custom_param = self.strategy_params.get("my_custom_param", "default_value_cde_test")
        self.aapl_buy_threshold = self.strategy_params.get("aapl_buy_threshold", 150.0) # Default if not in config
        self.aapl_sell_threshold = self.strategy_params.get("aapl_sell_threshold", 140.0)
        self.aapl_buy_quantity = self.strategy_params.get("aapl_buy_quantity", 10) # Default if not in config

    def on_start(self):
        sdk.log(f"Strategy '{self.strategy_id}' started. Symbols: {self.symbols_of_interest}, Params: {self.strategy_params}", level="INFO")
        sdk.log(f"My custom param value: {self.my_custom_param}", level="INFO")
        sdk.log(f"AAPL Buy Threshold: {self.aapl_buy_threshold}, AAPL Sell Threshold: {self.aapl_sell_threshold}, AAPL Buy Qty: {self.aapl_buy_quantity}", level="INFO")


    def on_bar(self, timestamp: datetime.datetime, current_bar_data_bundle: dict):
        sdk.log(f"Strategy '{self.strategy_id}' on_bar for {timestamp}. AAPL Close: {current_bar_data_bundle.get('AAPL', {}).get('CLOSE')}", level="DEBUG")

        aapl_data = current_bar_data_bundle.get("AAPL")
        if aapl_data and "AAPL" in self.symbols_of_interest: # Ensure symbol is relevant
            current_portfolio = sdk.get_portfolio_summary()
            aapl_position_qty = 0
            if current_portfolio and "positions" in current_portfolio:
                for pos in current_portfolio.get("positions", []):
                    if pos["symbol"] == "AAPL": aapl_position_qty = pos["quantity"]; break

            # Use parameters fetched in __init__
            if aapl_data['CLOSE'] > self.aapl_buy_threshold and aapl_position_qty == 0:
                sdk.log(f"AAPL > {self.aapl_buy_threshold}, BUY {self.aapl_buy_quantity}", level="INFO")
                sdk.submit_order("AAPL", "MARKET", self.aapl_buy_quantity)
            elif aapl_data['CLOSE'] < self.aapl_sell_threshold and aapl_position_qty > 0:
                sdk.log(f"AAPL < {self.aapl_sell_threshold}, SELL {aapl_position_qty}", level="INFO")
                sdk.submit_order("AAPL", "MARKET", -aapl_position_qty)

    def on_fill(self, fill_info: dict):
        super().on_fill(fill_info)
        sdk.log(f"Strategy '{self.strategy_id}' received fill for {fill_info['symbol']}.", level="INFO")

    def on_stop(self):
        sdk.log(f"Strategy '{self.strategy_id}' stopped.", level="INFO")
"""
    with open(f"{dummy_strategy_module_name}.py", "w") as f: f.write(user_strat_content)

    # Create a sample config file for this test
    # Ensure HISTORICAL_DATA_DIR from sdk.py is used and has data.
    os.makedirs(sdk.HISTORICAL_DATA_DIR, exist_ok=True)
    aapl_test_csv_path = os.path.join(sdk.HISTORICAL_DATA_DIR, "AAPL_data.csv")
    if not os.path.exists(aapl_test_csv_path):
        test_df = pd.DataFrame({
            'Timestamp': pd.to_datetime(['2023-01-01T10:00:00Z', '2023-01-02T10:00:00Z', '2023-01-03T10:00:00Z', '2023-01-04T10:00:00Z']),
            'OPEN': [148, 150, 151, 139], 'HIGH': [150, 152, 153, 145],
            'LOW': [147, 149, 140, 138], 'CLOSE': [149, 151, 142, 143], # Includes sell trigger
            'VOLUME': [1000,1200,1100,1300]
        })
        test_df.to_csv(aapl_test_csv_path, index=False)
        logger.info(f"CDE_Runner Main: Created dummy AAPL CSV at {aapl_test_csv_path}")

    test_config_path = "cde_runner_main_test_config.yaml"
    test_config_content = {
        "general_settings": {"start_date": "2023-01-01", "end_date": "2023-01-04", "initial_capital": 50000.0, "risk_free_rate_annual": 0.01, "periods_per_year": 252},
        "data_handler": {"type": "csv", "csv_directory": sdk.HISTORICAL_DATA_DIR, "symbols": ["AAPL"], "ffill_missing_data": True},
        "strategy": {{
            "name": dummy_strategy_class_name,
            "parameters": {{
                "my_custom_param": "ValueFromConfigRunnerTest",
                "aapl_buy_threshold": 150.5,
                "aapl_sell_threshold": 142.0,
                "aapl_buy_quantity": 12 # Test with a different quantity
            }}
        }},
        "portfolio_settings": {"slippage_model":"none", "commission_model":"fixed_per_trade", "commission_fixed_amount":1.0},
        "output_settings": {"results_directory": "cde_main_results", "save_metrics":True, "save_portfolio_history":True, "save_trades_log":True, "filename_prefix_parts": ["strategy_name"]},
        "sdk_settings": {"log_level": "DEBUG", "json_logs": False} # SDK specific logging for this run
    }
    with open(test_config_path, 'w') as f: yaml.dump(test_config_content, f)
    logger.info(f"CDE_Runner Main: Created dummy test config at {test_config_path}")

    # Run the CDE backtest using the dummy strategy and config
    run_cde_backtest(config_filepath=test_config_path,
                     strategy_module_name=dummy_strategy_module_name,
                     strategy_class_name=dummy_strategy_class_name)

    # Clean up dummy files
    # os.remove(f"{dummy_strategy_module_name}.py")
    # os.remove(test_config_path)
    # logger.info("CDE_Runner Main: Cleaned up dummy files.")
