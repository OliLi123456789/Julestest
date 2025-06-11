import datetime
from typing import List, Dict, Optional, Any
import logging
import os
import pandas as pd
import yaml

from backtester.data import AbstractDataHandler, MarketDataEvent, CsvDataHandler
from backtester.strategy import AbstractStrategy, SignalEvent, BuyAndHoldStrategy
from backtester.portfolio import Portfolio, OrderEvent, FillEvent, OrderType, OrderStatus # Added OrderStatus
from backtester.performance import PerformanceCalculator
from backtester.config_loader import load_backtest_config, create_sample_config
from backtester.walk_forward import WalkForwardRunner
from backtester.results_writer import ResultsWriter # Added

logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self, data_handler: AbstractDataHandler, strategy: AbstractStrategy,
                 portfolio: Portfolio, performance_calculator_class=PerformanceCalculator):
        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.performance_calculator_class = performance_calculator_class

        # self.events_queue is removed
        self.pending_execution_orders: List[OrderEvent] = [] # Stores orders generated in T-1, for execution at T
        self.current_market_data: Dict[str, MarketDataEvent] = {}
        self.current_timestamp: Optional[datetime.datetime] = None
        self.config: Dict[str, Any] = {}
        self.last_run_calculator_instance: Optional[PerformanceCalculator] = None # Added

    # _process_market_event_bundle, _process_signal_event, _process_order_event, _process_fill_event are removed
    # as their logic is integrated into the new run_backtest loop.

    def run_backtest(self) -> Optional[Dict[str, Any]]:
        logger.info("Engine: Starting backtest with refined event loop...")
        self.pending_execution_orders.clear()
        self.current_market_data.clear()
        self.last_run_calculator_instance = None # Reset for current run
        # Initial MTM update is implicitly handled by the first call to portfolio.update_timeindex

        # --- Main Event Loop ---
        # Data handler now yields (timestamp, market_data_bundle for that timestamp)
        for timestamp, market_data_bundle in self.data_handler.stream_next_bar():
            if not market_data_bundle: # Skip if bundle is empty (e.g., no data for any symbol at this time)
                logger.debug(f"Engine: Empty market data bundle for timestamp {timestamp}. Skipping.")
                continue

            self.current_timestamp = timestamp # Set current timestamp for the engine

            # A. Market Data Update (for current timestamp T)
            # This updates the portfolio's view of current market prices for all symbols in the bundle.
            self.current_market_data.update(market_data_bundle)
            logger.debug(f"Engine: Processing Bar at Timestamp: {self.current_timestamp}")

            # D. Order Execution Simulation (for orders from T-1, using data of current bar T)
            # These orders were generated based on the previous bar's data (T-1).
            # They are simulated to execute using current bar's data (T - e.g., T's OPEN).
            new_fills_this_bar: List[FillEvent] = []
            remaining_pending_orders_after_execution: List[OrderEvent] = []

            if not self.pending_execution_orders:
                logger.debug(f"Engine: No orders pending execution for timestamp {self.current_timestamp}.")

            for order_to_execute in self.pending_execution_orders:
                # Ensure order is still PENDING before attempting execution
                if order_to_execute.status != OrderStatus.PENDING:
                    # If it was somehow filled or cancelled by another logic (not in this basic engine)
                    # or if it's a LIMIT order that became REJECTED by a previous simulate_order_execution.
                    # We might want to keep it in a list of "dead" orders for the day for audit.
                    # For now, if not PENDING, we don't try to execute.
                    if order_to_execute.status == OrderStatus.REJECTED: # From a previous failed limit order validation
                         logger.info(f"Engine: Order {order_to_execute} was already REJECTED. Removing from pending.")
                    # else, if it's somehow FILLED or CANCELED already, it shouldn't be in pending_execution_orders.
                    continue

                market_event_for_exec = self.current_market_data.get(order_to_execute.symbol)
                if market_event_for_exec:
                    # Ensure the market event's timestamp matches the current engine timestamp
                    if market_event_for_exec.timestamp != self.current_timestamp:
                        logger.warning(f"Timestamp mismatch! Order {order_to_execute} for {order_to_execute.timestamp} "
                                       f"vs MarketEvent {market_event_for_exec.symbol} for {market_event_for_exec.timestamp}. "
                                       f"Order remains PENDING.")
                        remaining_pending_orders_after_execution.append(order_to_execute)
                        continue

                    logger.debug(f"Engine: Attempting to execute {order_to_execute} using market data from {self.current_timestamp}")
                    fill = self.portfolio.simulate_order_execution(order_to_execute, market_event_for_exec)
                    if fill:
                        new_fills_this_bar.append(fill)
                        logger.debug(f"Engine: Order generated fill: {fill}")
                    else: # No fill occurred
                        if order_to_execute.status == OrderStatus.PENDING: # e.g. LIMIT not hit
                            remaining_pending_orders_after_execution.append(order_to_execute)
                            logger.debug(f"Engine: Order {order_to_execute} remains PENDING.")
                        else: # e.g. REJECTED by execution simulation (cash check etc.)
                            logger.info(f"Engine: Order {order_to_execute} is now {order_to_execute.status.value} after execution attempt.")
                else: # No market data for this symbol at current timestamp T
                    logger.warning(f"Engine: No market data for {order_to_execute.symbol} at {self.current_timestamp} to execute order. Order remains PENDING.")
                    remaining_pending_orders_after_execution.append(order_to_execute)

            self.pending_execution_orders = remaining_pending_orders_after_execution

            # E. Portfolio State Update from Fills (from orders of T-1, filled at T)
            if new_fills_this_bar:
                for fill_event in new_fills_this_bar:
                    logger.debug(f"Engine: Portfolio processing fill: {fill_event}")
                    self.portfolio.process_fill(fill_event)
                    # TODO: If strategies need fill confirmations, route them here (e.g., self.strategy.on_fill(fill_event))

            # F. Portfolio Mark-to-Market (at end of bar T, using T's CLOSE prices from current_market_data)
            self.portfolio.update_timeindex(self.current_timestamp, self.current_market_data)
            if self.portfolio.portfolio_value_over_time: # Check if list is not empty
                logger.debug(f"Engine: Portfolio MTM updated for {self.current_timestamp}. Value: {self.portfolio.portfolio_value_over_time[-1]['value']:.2f}")
            else: # Should not happen if initial capital was set and first bar processed
                logger.warning(f"Engine: Portfolio MTM not recorded for {self.current_timestamp}")


            # B. Strategy Signal Generation (based on current bar T's data, for execution on T+1)
            new_signals_this_bar: List[SignalEvent] = []
            for symbol, market_event_for_strat in self.current_market_data.items(): # Use current_market_data which is the full bundle
                if self.strategy.symbols and symbol not in self.strategy.symbols: continue # Strategy only interested in certain symbols

                logger.debug(f"Engine: Strategy processing {symbol} bar for {market_event_for_strat.timestamp}")
                signals_from_strat = self.strategy.calculate_signals(market_event_for_strat)
                if signals_from_strat:
                    new_signals_this_bar.extend(signals_from_strat)
                    for sig in signals_from_strat: logger.debug(f"Engine: Strategy generated signal: {sig}")

            # C. Portfolio Order Creation (from signals of bar T, for execution on T+1)
            newly_generated_orders_this_bar: List[OrderEvent] = []
            if new_signals_this_bar:
                for signal_event in new_signals_this_bar:
                    logger.debug(f"Engine: Portfolio processing signal: {signal_event}")
                    order = self.portfolio.process_signal(signal_event)
                    if order:
                        newly_generated_orders_this_bar.append(order)
                        logger.debug(f"Engine: Portfolio generated order: {order}")

            # These new orders become pending for the NEXT bar's execution phase
            self.pending_execution_orders.extend(newly_generated_orders_this_bar)

        # --- End of Main Event Loop ---
        logger.info("Engine: Backtest event loop finished.")

        if not self.portfolio.portfolio_value_over_time:
             logger.warning("Engine: No portfolio value history recorded. This may indicate no data was processed or an issue with MTM updates.")
             # If initial_capital is the only value, P&L etc. will be based on that.
        elif self.current_timestamp: # Log final value if loop ran
             logger.info(f"Engine: Final portfolio value at {self.current_timestamp}: {self.portfolio.portfolio_value_over_time[-1]['value']:.2f}")

        logger.info("Engine: Calculating performance metrics...")
        risk_free_rate = self.config.get('general_settings', {}).get('risk_free_rate_annual', 0.0)
        periods_per_year = self.config.get('general_settings', {}).get('periods_in_year', 252)

        calculator = self.performance_calculator_class(
            portfolio_value_history=self.portfolio.portfolio_value_over_time,
            trades=self.portfolio.trades,
            initial_capital=self.portfolio.initial_cash
        )
        metrics = calculator.calculate_metrics(risk_free_rate_annual=risk_free_rate, periods_in_year=periods_per_year)
        # Modify display_metrics to accept metrics dict
        calculator.display_metrics(metrics_dict_to_display=metrics)

        logger.info("Engine: Backtest complete.")
        return metrics

# --- Main execution function for a single backtest run ---
def execute_single_backtest_run(config_dict: Dict[str, Any], run_label: str = "SingleRun") -> Optional[Dict[str, Any]]:
    logger.info(f"--- Starting {run_label} ---")
    # logger.debug(f"Using configuration: {config_dict}") # Can be very verbose

    gs_config = config_dict['general_settings']
    dh_config = config_dict['data_handler']
    strat_config = config_dict['strategy']
    port_config = config_dict['portfolio_settings']

    if dh_config['type'].lower() == 'csv':
        data_handler = CsvDataHandler(
            csv_dir=dh_config['csv_directory'], symbols=dh_config['symbols'],
            ffill=dh_config.get('ffill_missing_data', True),
            start_date=gs_config.get('start_date'), end_date=gs_config.get('end_date')
        )
    else:
        logger.critical(f"Unsupported data_handler type: {dh_config['type']}. Exiting.")
        return None

    available_strategies = {"BuyAndHoldStrategy": BuyAndHoldStrategy}
    StrategyClass = available_strategies.get(strat_config['name'])
    if not StrategyClass:
        logger.critical(f"Strategy '{strat_config['name']}' not found. Exiting.")
        return None

    strategy_params = strat_config.get('parameters', {})
    strategy = StrategyClass(symbols=dh_config['symbols'], **strategy_params)
    logger.info(f"Strategy '{strat_config['name']}' initialized with params: {strategy_params}")

    portfolio = Portfolio(
        initial_cash=float(gs_config['initial_capital']), data_handler=data_handler, **port_config
    )

    engine = BacktestEngine(data_handler, strategy, portfolio)
    engine.config = config_dict
    results = engine.run_backtest()
    logger.info(f"--- {run_label} Completed ---")
    return results

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    CONFIG_DIR = "configs"
    CONFIG_FILEPATH = os.path.join(CONFIG_DIR, "main_backtest_config.yaml")

    if not os.path.exists(CONFIG_FILEPATH):
        logger.info(f"Config file not found at {CONFIG_FILEPATH}. Creating sample.")
        dummy_data_dir = os.path.join(CONFIG_DIR, "sample_data")
        if not os.path.exists(dummy_data_dir): os.makedirs(dummy_data_dir)

        sample_sym = "SAMPLE"
        ts = pd.to_datetime([f'2023-01-{d:02d} 10:00:00' for d in range(1, 11)]) # Added time component
        df_sample = pd.DataFrame({
            'Timestamp': ts, 'OPEN': [10+i*0.1 for i in range(10)], 'HIGH': [11+i*0.1 for i in range(10)],
            'LOW': [9+i*0.1 for i in range(10)], 'CLOSE': [10.5+i*0.1 for i in range(10)], 'VOLUME': [1000+i*10 for i in range(10)]
        })
        sample_csv_path = os.path.join(dummy_data_dir, f"{sample_sym}_data.csv")
        df_sample.to_csv(sample_csv_path, index=False)
        logger.info(f"Created dummy CSV data for sample config at: {sample_csv_path}")

        create_sample_config(CONFIG_FILEPATH)
        temp_cfg = load_backtest_config(CONFIG_FILEPATH)
        if temp_cfg:
            temp_cfg["data_handler"]["csv_directory"] = dummy_data_dir
            temp_cfg["data_handler"]["symbols"] = [sample_sym]
            temp_cfg["general_settings"]["start_date"] = "2023-01-01" # Ensure sample config dates align with dummy data
            temp_cfg["general_settings"]["end_date"] = "2023-01-10"
            # temp_cfg["walk_forward_settings"]["enabled"] = True
            # temp_cfg["walk_forward_settings"]["in_sample_period"] = "5D"
            # temp_cfg["walk_forward_settings"]["out_of_sample_period"] = "2D"
            # temp_cfg["walk_forward_settings"]["step_size"] = "2D"
            with open(CONFIG_FILEPATH, 'w') as f: yaml.dump(temp_cfg, f, sort_keys=False, indent=2)
            logger.info(f"Sample config at {CONFIG_FILEPATH} updated for dummy data: {dummy_data_dir}")

    config = load_backtest_config(CONFIG_FILEPATH)
    if not config:
        logger.critical("Exiting: Could not load backtest configuration.")
        exit()

    if config.get("walk_forward_settings", {}).get("enabled", False):
        logger.info("Walk-forward analysis enabled in configuration.")
        wf_runner = WalkForwardRunner(base_config=config)
        wf_results = wf_runner.run_walk_forward()
    else:
        logger.info("Single backtest run enabled in configuration.")
        single_run_results = execute_single_backtest_run(config, "MainRun")

    logger.info("Backtesting process from __main__ completed.")
