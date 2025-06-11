# backtester/walk_forward.py
import logging
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from datetime import datetime
import copy # For deep copying configurations

logger = logging.getLogger(__name__)

def generate_walk_forward_windows(
    overall_start_date_str: str,
    overall_end_date_str: str,
    in_sample_period_str: str,    # e.g., "180D", "6M", "1Y"
    out_of_sample_period_str: str, # e.g., "30D", "1M"
    step_size_str: Optional[str] = None # How much to advance the start of IS period. If None, defaults to OOS period.
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    Generates a list of (in_sample_start, in_sample_end, out_of_sample_start, out_of_sample_end)
    tuples for walk-forward analysis.
    Dates are inclusive.
    """
    try:
        overall_start_dt = pd.to_datetime(overall_start_date_str)
        overall_end_dt = pd.to_datetime(overall_end_date_str)

        # Using pd.offsets for robust date arithmetic (e.g., MonthEnd, YearEnd)
        # For simpler frequency strings like "30D", pd.Timedelta is also fine.
        # pd.tseries.frequencies.to_offset is good for "M", "Y", "D" etc.
        in_sample_offset = pd.tseries.frequencies.to_offset(in_sample_period_str)
        out_of_sample_offset = pd.tseries.frequencies.to_offset(out_of_sample_period_str)

        if step_size_str:
            step_offset = pd.tseries.frequencies.to_offset(step_size_str)
        else: # Default step size is the OOS period length
            step_offset = out_of_sample_offset

        if not all(isinstance(offset, pd.DateOffset) for offset in [in_sample_offset, out_of_sample_offset, step_offset]):
            # This check might be too strict if Timedelta objects are sometimes returned and are acceptable.
            # pd.tseries.frequencies.to_offset should return DateOffset.
            raise ValueError(f"Invalid period string(s) provided for offsets: IS='{in_sample_period_str}', OOS='{out_of_sample_period_str}', Step='{step_size_str}'")

    except Exception as e:
        logger.error(f"Error parsing walk-forward date/period strings: {e}", exc_info=True)
        return []

    windows = []
    current_in_sample_start = overall_start_dt
    max_iterations = 1000 # Safety break for while loop

    while current_in_sample_start < overall_end_dt and max_iterations > 0:
        max_iterations -=1
        current_in_sample_end = current_in_sample_start + in_sample_offset - pd.Timedelta(days=1) # Inclusive end

        # Ensure IS end does not exceed overall end date
        if current_in_sample_end > overall_end_dt:
            break

        current_out_of_sample_start = current_in_sample_end + pd.Timedelta(days=1)

        # If OOS start is already past overall end, then this IS period is too late to have an OOS period.
        if current_out_of_sample_start > overall_end_dt:
            break

        current_out_of_sample_end = current_out_of_sample_start + out_of_sample_offset - pd.Timedelta(days=1) # Inclusive end
        actual_out_of_sample_end = min(current_out_of_sample_end, overall_end_dt) # Cap OOS end at overall_end_dt

        windows.append((
            pd.Timestamp(current_in_sample_start.date()),
            pd.Timestamp(current_in_sample_end.date()),
            pd.Timestamp(current_out_of_sample_start.date()),
            pd.Timestamp(actual_out_of_sample_end.date())
        ))

        # Determine next IS start
        next_in_sample_start = current_in_sample_start + step_offset

        # Break if the next IS start is already past the overall end date
        if next_in_sample_start >= overall_end_dt:
            break
        # Break also if the next IS period would be too short or extend beyond overall_end_dt meaningfully
        if (next_in_sample_start + in_sample_offset - pd.Timedelta(days=1)) > overall_end_dt and \
           len(pd.date_range(next_in_sample_start, overall_end_dt)) < pd.Timedelta(days=7).days : # Arbitrary minimum IS period
            break

        current_in_sample_start = next_in_sample_start

    if max_iterations <=0: logger.warning("generate_walk_forward_windows exceeded max iterations.")
    logger.info(f"Generated {len(windows)} walk-forward windows.")
    return windows


class WalkForwardRunner:
    def __init__(self, base_config: Dict[str, Any]):
        self.base_config = copy.deepcopy(base_config) # Deep copy to avoid modifying original during runs
        self.wf_config = self.base_config.get("walk_forward_settings", {})

        if not self.wf_config.get("enabled", False):
            # This check should ideally be done before instantiating WalkForwardRunner
            logger.warning("WalkForwardRunner initialized but walk_forward_settings.enabled is False in config.")
            # raise ValueError("WalkForwardRunner initialized but walk_forward_settings.enabled is not True.")

        self.all_out_of_sample_results: List[Dict[str, Any]] = []
        self.all_in_sample_params: List[Dict[str, Any]] = [] # To store IS results and params used
        logger.info(f"WalkForwardRunner initialized. WF settings: {self.wf_config}")

    def _run_single_backtest_period(self, period_config: Dict[str, Any], period_label: str) -> Optional[Dict[str, Any]]:
        # Imports are here to avoid circular dependency issues at module load time,
        # as engine.py might also import from walk_forward.py if helper functions are moved.
        from .engine import BacktestEngine
        from .data import CsvDataHandler
        from .strategy import BuyAndHoldStrategy, AbstractStrategy
        from .portfolio import Portfolio
        from .results_writer import ResultsWriter # Added import

        available_strategies_map: Dict[str, type[AbstractStrategy]] = { # Moved map here
            "BuyAndHoldStrategy": BuyAndHoldStrategy
        }

        logger.info(f"--- Running Backtest: {period_label} "
                    f"({period_config['general_settings']['start_date']} to {period_config['general_settings']['end_date']}) ---")
        available_strategies_map: Dict[str, type[AbstractStrategy]] = {
            "BuyAndHoldStrategy": BuyAndHoldStrategy
            # "AnotherStrategy": AnotherStrategyClass
        }

        logger.info(f"--- Running Backtest: {period_label} "
                    f"({period_config['general_settings']['start_date']} to {period_config['general_settings']['end_date']}) ---")

        gs_cfg = period_config['general_settings']
        dh_cfg = period_config['data_handler']
        strat_cfg = period_config['strategy']
        port_cfg = period_config['portfolio_settings']

        try:
            data_handler = CsvDataHandler(
                csv_dir=dh_cfg['csv_directory'],
                symbols=dh_cfg['symbols'],
                ffill=dh_cfg.get('ffill_missing_data', True),
                start_date=gs_cfg.get('start_date'),
                end_date=gs_cfg.get('end_date')
            )

            StrategyClass = available_strategies_map.get(strat_cfg['name'])
            if not StrategyClass:
                logger.error(f"Strategy '{strat_cfg['name']}' not found in available_strategies_map.")
                return None

            strategy_instance = StrategyClass(
                symbols=dh_cfg['symbols'],
                **(strat_cfg.get('parameters', {}))
            )

            portfolio = Portfolio(
                initial_cash=float(gs_cfg['initial_capital']),
                data_handler=data_handler, # Portfolio might use it for MTM if data access is needed
                **port_cfg # Pass all portfolio settings from config
            )

            engine = BacktestEngine(data_handler, strategy_instance, portfolio)
            engine.config = period_config

            metrics = engine.run_backtest() # This now returns metrics or None
            logger.info(f"--- Completed Backtest: {period_label} ---")

            # Save results for this specific period if configured
            if metrics and hasattr(engine, 'last_run_calculator_instance') and engine.portfolio:
                output_cfg_period = period_config.get("output_settings")
                if output_cfg_period and \
                   (output_cfg_period.get("save_metrics") or \
                    output_cfg_period.get("save_portfolio_history") or \
                    output_cfg_period.get("save_trades_log")):

                    logger.info(f"Saving results for period: {period_label}")
                    # We need to pass the period_config to ResultsWriter's base_config
                    # for it to correctly use period-specific dates in filenames if needed.
                    results_writer_period = ResultsWriter(output_config=output_cfg_period,
                                                          base_config=period_config)
                    results_writer_period.save_all_results(
                        metrics=metrics,
                        portfolio_history_df=engine.last_run_calculator_instance.portfolio_df,
                        trades_list=engine.portfolio.trades,
                        period_label=period_label # Pass period_label for unique filenames
                    )
            return metrics
        except Exception as e:
            logger.error(f"Error during backtest for period {period_label}: {e}", exc_info=True)
            return None

    def run_walk_forward(self):
        if not self.wf_config.get("enabled", False):
            logger.info("Walk-forward analysis is disabled in configuration. Skipping.")
            return None

        logger.info("Starting Walk-Forward Analysis...")

        # Use overall_start_date/end_date from general_settings in base_config
        # These might be different from the ones in wf_config if those are specific overrides
        overall_start = self.base_config.get("general_settings", {}).get("start_date")
        overall_end = self.base_config.get("general_settings", {}).get("end_date")

        if not all([overall_start, overall_end, self.wf_config.get("in_sample_period"), self.wf_config.get("out_of_sample_period")]):
            logger.error("Missing critical date or period parameters for walk-forward analysis in configuration.")
            return None

        windows = generate_walk_forward_windows(
            overall_start_date_str=overall_start,
            overall_end_date_str=overall_end,
            in_sample_period_str=self.wf_config["in_sample_period"],
            out_of_sample_period_str=self.wf_config["out_of_sample_period"],
            step_size_str=self.wf_config.get("step_size") # Optional, defaults to OOS period
        )

        if not windows:
            logger.error("No walk-forward windows generated based on the provided parameters. Aborting.")
            return None

        for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
            period_label_is = f"IS_{i+1} ({is_start.strftime('%Y%m%d')}-{is_end.strftime('%Y%m%d')})"
            period_label_oos = f"OOS_{i+1} ({oos_start.strftime('%Y%m%d')}-{oos_end.strftime('%Y%m%d')})"
            logger.info(f"\n>>> WF Window {i+1}/{len(windows)}: In-Sample: {is_start.date()} - {is_end.date()}, Out-of-Sample: {oos_start.date()} - {oos_end.date()} <<<")

            # --- In-Sample Period (Training/Optimization) ---
            is_config = copy.deepcopy(self.base_config) # Start with a fresh copy of base config
            is_config['general_settings']['start_date'] = is_start.strftime("%Y-%m-%d")
            is_config['general_settings']['end_date'] = is_end.strftime("%Y-%m-%d")

            # TODO: Parameter Optimization Step (Conceptual for now)
            # This is where you would run an optimization routine on the In-Sample data
            # to find the best strategy parameters. For this subtask, we assume the
            # parameters in base_config['strategy']['parameters'] are either fixed or
            # represent the outcome of a hypothetical optimization.
            logger.info(f"Running In-Sample Period: {period_label_is}")
            is_metrics = self._run_single_backtest_period(is_config, period_label_is)

            # For now, "optimized" parameters are just the ones used for the IS run.
            # In a real WF, these might change after an optimization routine.
            optimized_strategy_params = is_config["strategy"]["parameters"]
            self.all_in_sample_params.append({
                "period_label": period_label_is,
                "parameters": optimized_strategy_params,
                "metrics": is_metrics
            })

            # --- Out-of-Sample Period (Validation) ---
            oos_config = copy.deepcopy(self.base_config)
            oos_config['general_settings']['start_date'] = oos_start.strftime("%Y-%m-%d")
            oos_config['general_settings']['end_date'] = oos_end.strftime("%Y-%m-%d")
            # Apply the "optimized" parameters from the In-Sample run to the strategy for OOS
            oos_config['strategy']['parameters'] = optimized_strategy_params

            logger.info(f"Running Out-of-Sample Period: {period_label_oos} using parameters from {period_label_is}")
            oos_metrics = self._run_single_backtest_period(oos_config, period_label_oos)

            if oos_metrics:
                self.all_out_of_sample_results.append({
                    "period_label": period_label_oos,
                    "is_start_date": is_start.strftime('%Y-%m-%d'),
                    "is_end_date": is_end.strftime('%Y-%m-%d'),
                    "oos_start_date": oos_start.strftime('%Y-%m-%d'),
                    "oos_end_date": oos_end.strftime('%Y-%m-%d'),
                    "metrics": oos_metrics,
                    "parameters_used": optimized_strategy_params
                })
            else:
                logger.warning(f"Out-of-Sample run for {period_label_oos} failed or returned no metrics.")

        logger.info("--- Walk-Forward Analysis Complete ---")
        self._display_aggregated_wf_results()
        # TODO: Further analysis, like creating a combined equity curve or performance report.
        return self.all_out_of_sample_results

    def _display_aggregated_wf_results(self):
        logger.info("\n--- Aggregated Walk-Forward Out-of-Sample Results ---")
        if not self.all_out_of_sample_results:
            logger.info("No Out-of-Sample results to display.")
            return

        for i, result_set in enumerate(self.all_out_of_sample_results):
            logger.info(f"\nOOS Period {i+1}: {result_set['period_label']} "
                        f"(Trained on IS: {result_set['is_start_date']} - {result_set['is_end_date']})")
            logger.info(f"  Parameters Used: {result_set['parameters_used']}")
            if result_set['metrics']:
                for key, value in result_set['metrics'].items():
                    display_value = f"{value:.4f}" if isinstance(value, float) and not (np.isinf(value) or pd.isna(value)) else str(value)
                    logger.info(f"    {key}: {display_value}")
            else:
                logger.info("    No metrics for this OOS period.")

        # TODO: Calculate overall statistics from all_out_of_sample_results if needed
        # e.g., average Sharpe, P&L distribution, etc.
        # For example, create a DataFrame of all OOS metrics:
        # oos_metrics_df = pd.DataFrame([res['metrics'] for res in self.all_out_of_sample_results if res['metrics']])
        # if not oos_metrics_df.empty:
        #     logger.info("\n--- Summary Statistics of OOS Metrics ---")
        #     logger.info(oos_metrics_df.describe())

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info("Testing generate_walk_forward_windows function...")
    windows = generate_walk_forward_windows(
        overall_start_date_str="2023-01-01",
        overall_end_date_str="2023-06-30",
        in_sample_period_str="60D", # Approx 2 months
        out_of_sample_period_str="30D", # Approx 1 month
        step_size_str="30D" # Step by one month
    )
    for i, w in enumerate(windows):
        logger.info(f"Window {i+1}: IS Start: {w[0].date()}, IS End: {w[1].date()}, OOS Start: {w[2].date()}, OOS End: {w[3].date()}")

    # To test WalkForwardRunner, you'd need a sample config file.
    # The engine's __main__ block now handles creating a sample config and running based on it.
    # So, WalkForwardRunner would typically be invoked from there if "enabled": true.
    logger.info("WalkForwardRunner would be tested via engine.py with a walk_forward_settings.enabled = true in config.")
