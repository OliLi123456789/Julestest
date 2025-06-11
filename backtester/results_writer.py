# backtester/results_writer.py
import os
import json
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ResultsWriter:
    def __init__(self, output_config: Dict[str, Any], base_config: Dict[str, Any]):
        self.output_config = output_config
        self.base_config = base_config # Used for generating parts of the filename
        self.results_dir = output_config.get("results_directory", "backtest_results")

        try:
            os.makedirs(self.results_dir, exist_ok=True)
            logger.info(f"Results will be saved in: {os.path.abspath(self.results_dir)}")
        except Exception as e:
            logger.error(f"Error creating results directory '{self.results_dir}': {e}. Results might not be saved.", exc_info=True)
            # Fallback to current directory if creation fails? Or let it fail?
            # For now, it will try to save and might fail if dir not creatable.
            self.results_dir = "." # Fallback to current directory if error, though this might not be ideal.


    def _generate_filename_prefix(self, period_label: Optional[str] = None) -> str:
        parts = []
        try:
            # Use parts from base_config for overall run, period_label for specific WF period
            config_to_use_for_naming = self.base_config

            prefix_format_parts = self.output_config.get("filename_prefix_parts", ["strategy_name"])
            strategy_name = config_to_use_for_naming.get("strategy", {}).get("name", "UnknownStrategy")

            # Dates for filenames should ideally come from the actual run dates used by the engine for this specific result set
            # If period_label provides specific dates (e.g. in WalkForwardRunner), those are more accurate for that period's files.
            # For now, using general_settings from the config passed to this writer instance.
            start_date_str = config_to_use_for_naming.get("general_settings", {}).get("start_date", "nodateS")
            end_date_str = config_to_use_for_naming.get("general_settings", {}).get("end_date", "nodateE")

            # Sanitize dates for use in filenames
            start_date_fn = str(start_date_str).replace("-","").replace(":","").replace(" ","_")
            end_date_fn = str(end_date_str).replace("-","").replace(":","").replace(" ","_")

            for part_name in prefix_format_parts:
                if part_name == "strategy_name": parts.append(strategy_name)
                elif part_name == "start_date": parts.append(start_date_fn)
                elif part_name == "end_date": parts.append(end_date_fn)
                # Add more parts here if defined in config, e.g. "symbols_list"

            if period_label: # For walk-forward periods
                safe_period_label = period_label.replace(" ", "_").replace("(", "").replace(")", "").replace(":", "").replace("-","_")
                parts.append(safe_period_label)

            ts_format = self.output_config.get("run_id_timestamp_format", "%Y%m%d_%H%M%S")
            unique_ts = datetime.now().strftime(ts_format)
            parts.append(unique_ts)

        except Exception as e:
            logger.error(f"Error generating filename prefix parts: {e}. Using default prefix.", exc_info=True)
            parts = ["backtest_run", datetime.now().strftime("%Y%m%d_%H%M%S")] # Fallback

        return "_".join(filter(None, parts))


    def save_all_results(self, metrics: Optional[Dict[str, Any]],
                         portfolio_history_df: Optional[pd.DataFrame],
                         trades_list: Optional[List[Any]], # List of FillEvent objects
                         period_label: Optional[str] = None): # For walk-forward runs to distinguish files

        if not metrics and (portfolio_history_df is None or portfolio_history_df.empty) and not trades_list:
            logger.warning("No results data provided to ResultsWriter.save_all_results(). Nothing will be saved.")
            return

        prefix = self._generate_filename_prefix(period_label)

        # Save Metrics
        if self.output_config.get("save_metrics", True) and metrics:
            filepath = os.path.join(self.results_dir, f"{prefix}_metrics.json")
            try:
                # Serialize metrics, handling special float values and datetime/timestamps
                serializable_metrics = {}
                for k, v in metrics.items():
                    if isinstance(v, float):
                        if pd.isna(v) or v == float('inf') or v == float('-inf'):
                            serializable_metrics[k] = str(v)
                        else:
                            serializable_metrics[k] = v
                    elif isinstance(v, (datetime, pd.Timestamp)):
                        serializable_metrics[k] = v.isoformat()
                    else:
                        serial_metrics[k] = v

                with open(filepath, 'w') as f:
                    json.dump(serializable_metrics, f, indent=4)
                logger.info(f"Metrics saved successfully to: {filepath}")
            except Exception as e:
                logger.error(f"Failed to save metrics to {filepath}: {e}", exc_info=True)

        # Save Portfolio History
        if self.output_config.get("save_portfolio_history", True) and portfolio_history_df is not None and not portfolio_history_df.empty:
            filepath = os.path.join(self.results_dir, f"{prefix}_portfolio_history.csv")
            try:
                # Ensure index (timestamp) is saved
                portfolio_history_df.to_csv(filepath, index=True)
                logger.info(f"Portfolio history saved successfully to: {filepath}")
            except Exception as e:
                logger.error(f"Failed to save portfolio history to {filepath}: {e}", exc_info=True)

        # Save Trades Log
        if self.output_config.get("save_trades_log", True) and trades_list:
            filepath = os.path.join(self.results_dir, f"{prefix}_trades_log.csv")
            try:
                trades_df_data = []
                for fill in trades_list: # fill is expected to be a FillEvent object
                    event_dict = {
                        "timestamp": fill.timestamp.isoformat() if isinstance(fill.timestamp, (datetime, pd.Timestamp)) else fill.timestamp,
                        "symbol": fill.symbol,
                        "quantity": fill.quantity,
                        "direction": fill.direction.value if hasattr(fill.direction, 'value') else str(fill.direction),
                        "fill_price": fill.fill_price,
                        "gross_value": fill.gross_value,
                        "commission": fill.commission,
                        "cash_impact": fill.cash_impact,
                        "realized_pnl_for_this_fill": getattr(fill, 'realized_pnl_for_this_fill', None)
                    }
                    trades_df_data.append(event_dict)

                if trades_df_data:
                    pd.DataFrame(trades_df_data).to_csv(filepath, index=False)
                    logger.info(f"Trades log saved successfully to: {filepath}")
                else:
                    logger.info("No trade data to save for trades log.")
            except Exception as e:
                logger.error(f"Failed to save trades log to {filepath}: {e}", exc_info=True)
        elif self.output_config.get("save_trades_log", True) and not trades_list:
             logger.info("Trade logging enabled, but no trades were made or provided.")
