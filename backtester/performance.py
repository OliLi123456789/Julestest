import numpy as np
import pandas as pd
from typing import List, Dict, Any # Added Any
from backtester.portfolio import FillEvent
from backtester.strategy import SignalType
import logging # Added

logger = logging.getLogger(__name__) # Added

class PerformanceCalculator:
    def __init__(self, portfolio_value_history: List[Dict[str, any]], trades: List[FillEvent], initial_capital: float):
        if not portfolio_value_history: # Allow empty history if initial capital is present
             logger.warning("Portfolio value history is empty. Some metrics may be zero or N/A.")
             self.portfolio_df = pd.DataFrame(columns=['timestamp', 'value']).set_index('timestamp')
        else:
            if not all('timestamp' in x and 'value' in x for x in portfolio_value_history):
                raise ValueError("portfolio_value_history must be a list of dicts with 'timestamp' and 'value' keys.")
            self.portfolio_df = pd.DataFrame(portfolio_value_history)
            self.portfolio_df['timestamp'] = pd.to_datetime(self.portfolio_df['timestamp'])
            self.portfolio_df = self.portfolio_df.set_index('timestamp').sort_index()

        if not self.portfolio_df.empty:
            self.portfolio_df['returns'] = self.portfolio_df['value'].pct_change().fillna(0)
        else: # Still ensure 'returns' column exists even if DataFrame is empty from start
            self.portfolio_df['returns'] = []


        self.trades = trades # List of FillEvent objects
        self.initial_capital = initial_capital
        self.metrics: Dict[str, Any] = {}

    def calculate_metrics(self, risk_free_rate_annual: float = 0.0, periods_in_year: int = 252):
        if self.portfolio_df.empty and self.initial_capital == 0: # No way to calculate P&L
             logger.error("Portfolio history is empty and initial capital is zero. Cannot calculate metrics.")
             # Populate with default/error values
             self.metrics.update({
                'Total P&L': 0.0, 'Total P&L Pct': 0.0, 'Sharpe Ratio': 0.0,
                'Sortino Ratio': 0.0, 'Calmar Ratio': 0.0,
                'Max Drawdown': 0.0, 'Max Drawdown Pct': 0.0,
                'Total Closing Trades': 0, 'Winning Trades': 0, 'Losing Trades': 0,
                'Win Rate': 0.0, 'Average Win': 0.0, 'Average Loss': 0.0,
                'Profit Factor': 'N/A', 'Average Trade P&L': 0.0
             })
             return self.metrics

        if not self.portfolio_df.empty:
            self.metrics['Total P&L'] = self.portfolio_df['value'].iloc[-1] - self.initial_capital
            self.metrics['Total P&L Pct'] = (self.metrics['Total P&L'] / self.initial_capital) * 100 if self.initial_capital != 0 else 0.0
            self.metrics['Sharpe Ratio'] = self._calculate_sharpe_ratio(risk_free_rate_annual, periods_in_year)
            self.metrics['Max Drawdown'], self.metrics['Max Drawdown Pct'] = self._calculate_max_drawdown()
            self.metrics['Sortino Ratio'] = self._calculate_sortino_ratio(risk_free_rate_annual, periods_in_year)
            self.metrics['Calmar Ratio'] = self._calculate_calmar_ratio(periods_in_year)
        else: # Handle case where portfolio_df is empty but initial_capital might be set (e.g. no trades made)
            self.metrics['Total P&L'] = 0.0
            self.metrics['Total P&L Pct'] = 0.0
            self.metrics['Sharpe Ratio'] = 0.0
            self.metrics['Max Drawdown'], self.metrics['Max Drawdown Pct'] = 0.0, 0.0
            self.metrics['Sortino Ratio'] = 0.0
            self.metrics['Calmar Ratio'] = 0.0


        trade_stats = self._calculate_trade_statistics()
        self.metrics.update(trade_stats)
        return self.metrics

    def _calculate_sharpe_ratio(self, risk_free_rate_annual: float, periods_in_year: int) -> float:
        if self.portfolio_df['returns'].empty or self.portfolio_df['returns'].std() == 0:
            return 0.0
        excess_returns = self.portfolio_df['returns'] - (risk_free_rate_annual / periods_in_year)
        sharpe_ratio = excess_returns.mean() / excess_returns.std() * np.sqrt(periods_in_year)
        return sharpe_ratio if pd.notna(sharpe_ratio) and not np.isinf(sharpe_ratio) else 0.0

    def _calculate_max_drawdown(self) -> tuple[float, float]:
        if self.portfolio_df.empty: return 0.0, 0.0
        cumulative = self.portfolio_df['value']
        if cumulative.empty: return 0.0, 0.0

        peak = cumulative.cummax()
        drawdown = (cumulative - peak)
        max_drawdown_value = drawdown.min() if not drawdown.empty else 0.0

        if max_drawdown_value == 0: return 0.0, 0.0

        peak_at_max_drawdown_time = peak.loc[drawdown.idxmin()] if not drawdown.empty else self.initial_capital
        if peak_at_max_drawdown_time == 0: return abs(max_drawdown_value), 0.0 # Avoid division by zero if peak is 0

        max_drawdown_percent = (max_drawdown_value / peak_at_max_drawdown_time) * 100
        return abs(max_drawdown_value), abs(max_drawdown_percent)

    def _calculate_trade_statistics(self) -> Dict[str, Any]:
        default_stats = {
            'Total Closing Trades': 0, 'Winning Trades': 0, 'Losing Trades': 0,
            'Win Rate': 0.0, 'Average Win': 0.0, 'Average Loss': 0.0,
            'Gross Profit': 0.0, 'Gross Loss': 0.0,
            'Profit Factor': 0.0, 'Average Trade P&L': 0.0
        }
        if not self.trades:
            return default_stats

        closing_trades_pnl = []
        for fill_event in self.trades:
            # Consider a fill as part of a "closing" trade if it has realized P&L populated.
            # This means Portfolio.process_fill has identified it as closing/reducing a position.
            if hasattr(fill_event, 'realized_pnl_for_this_fill') and fill_event.realized_pnl_for_this_fill is not None:
                closing_trades_pnl.append(fill_event.realized_pnl_for_this_fill)

        if not closing_trades_pnl:
            return default_stats

        total_closing_trades = len(closing_trades_pnl)
        winning_trades_pnl = [pnl for pnl in closing_trades_pnl if pnl > 0]
        losing_trades_pnl = [pnl for pnl in closing_trades_pnl if pnl < 0]

        num_winning_trades = len(winning_trades_pnl)
        num_losing_trades = len(losing_trades_pnl)

        win_rate = (num_winning_trades / total_closing_trades) * 100 if total_closing_trades > 0 else 0.0

        avg_win = sum(winning_trades_pnl) / num_winning_trades if num_winning_trades > 0 else 0.0
        avg_loss = sum(losing_trades_pnl) / num_losing_trades if num_losing_trades > 0 else 0.0 # avg_loss is negative

        gross_profit = sum(winning_trades_pnl)
        gross_loss = abs(sum(losing_trades_pnl)) # abs to make it positive for ratio

        if gross_loss == 0:
            profit_factor = float('inf') if gross_profit > 0 else 0.0 # Or 'N/A'
        else:
            profit_factor = gross_profit / gross_loss

        avg_trade_pnl = sum(closing_trades_pnl) / total_closing_trades if total_closing_trades > 0 else 0.0

        return {
            'Total Closing Trades': total_closing_trades,
            'Winning Trades': num_winning_trades,
            'Losing Trades': num_losing_trades,
            'Win Rate': win_rate,
            'Average Win': avg_win,
            'Average Loss': avg_loss,
            'Gross Profit': gross_profit,
            'Gross Loss': gross_loss,
            'Profit Factor': profit_factor,
            'Average Trade P&L': avg_trade_pnl
        }

    def _calculate_sortino_ratio(self, risk_free_rate_annual: float, periods_in_year: int = 252) -> float:
        if self.portfolio_df['returns'].empty: return 0.0
        rfr_period = risk_free_rate_annual / periods_in_year
        excess_returns = self.portfolio_df['returns'] - rfr_period
        downside_returns = excess_returns[excess_returns < 0]

        if downside_returns.empty:
            return float('inf') if excess_returns.mean() > 1e-9 else 0.0

        downside_std = np.sqrt(np.mean(downside_returns**2))
        if downside_std == 0:
            return float('inf') if excess_returns.mean() > 1e-9 else 0.0

        sortino_ratio = excess_returns.mean() / downside_std * np.sqrt(periods_in_year)
        return sortino_ratio if pd.notna(sortino_ratio) and not np.isinf(sortino_ratio) else 0.0

    def _calculate_calmar_ratio(self, periods_in_year: int = 252) -> float:
        if self.portfolio_df.empty or self.initial_capital == 0 or len(self.portfolio_df) < 2: # Need at least 2 points for a duration
            return 0.0

        start_value = self.initial_capital
        end_value = self.portfolio_df['value'].iloc[-1]
        num_periods = len(self.portfolio_df)
        num_years = num_periods / periods_in_year

        if num_years == 0 or start_value == 0: return 0.0

        annualized_return = ((end_value / start_value) ** (1 / num_years)) - 1 if num_years > 0 else 0.0

        _, max_dd_pct_abs = self._calculate_max_drawdown()
        if max_dd_pct_abs == 0:
            return float('inf') if annualized_return > 1e-9 else 0.0

        calmar_ratio = annualized_return / (max_dd_pct_abs / 100.0) # max_dd_pct_abs is already %, so divide by 100
        return calmar_ratio if pd.notna(calmar_ratio) and not np.isinf(calmar_ratio) else 0.0

    def display_metrics(self, metrics_dict_to_display: Optional[Dict[str, Any]] = None):
        print("\n--- Performance Metrics ---")

        metrics_to_show = metrics_dict_to_display if metrics_dict_to_display is not None else self.metrics

        if not metrics_to_show:
            print("No metrics available to display.")
            return

        for key, value in metrics_to_show.items():
            if isinstance(value, float):
                display_value = "Inf" if np.isinf(value) else f"{value:.2f}"
                # Add % sign for specific keys
                if "Pct" in key or "Rate" in key or key == 'Max Drawdown Pct': # Ensure Max Drawdown Pct gets %
                     print(f"{key}: {display_value}%")
                else:
                     print(f"{key}: {display_value}")
            else: # For strings like Profit Factor 'N/A' or integer counts
                print(f"{key}: {value}")
        print("-------------------------")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Dummy portfolio value history
    history = [
        {'timestamp': pd.Timestamp('2023-01-01'), 'value': 100000.0},
        {'timestamp': pd.Timestamp('2023-01-02'), 'value': 101000.0},
        {'timestamp': pd.Timestamp('2023-01-03'), 'value': 99000.0}, # Drawdown here
        {'timestamp': pd.Timestamp('2023-01-04'), 'value': 102000.0},
        {'timestamp': pd.Timestamp('2023-01-05'), 'value': 101500.0}
    ]
    # Dummy trades (FillEvents) - now with realized_pnl_for_this_fill
    # FillEvent structure: timestamp, symbol, quantity, direction, fill_price, gross_value, commission, realized_pnl_for_this_fill
    dummy_trades = [
        # Buy 10 AAPL (Opening trade, no P&L yet on this event)
        FillEvent(pd.Timestamp('2023-01-02'), 'AAPL', 10, SignalType.BUY, 150.0, 1500.0, 1.0, None),
        # Sell 10 AAPL, assume avg entry was 150. Sell price 152. P&L = (152-150)*10 - 1.0_comm = 20 - 1 = 19
        FillEvent(pd.Timestamp('2023-01-03'), 'AAPL', 10, SignalType.SELL, 152.0, 1520.0, 1.0, 19.0),
        # Buy 5 GOOG (Opening)
        FillEvent(pd.Timestamp('2023-01-04'), 'GOOG', 5, SignalType.BUY, 2500.0, 12500.0, 1.0, None),
        # Sell 5 GOOG, assume avg entry was 2500. Sell price 2490. P&L = (2490-2500)*5 - 1.0_comm = -50 - 1 = -51
        FillEvent(pd.Timestamp('2023-01-05'), 'GOOG', 5, SignalType.SELL, 2490.0, 12450.0, 1.0, -51.0)
    ]

    calculator = PerformanceCalculator(portfolio_value_history=history, trades=dummy_trades, initial_capital=100000.0)
    all_metrics = calculator.calculate_metrics(risk_free_rate_annual=0.02)
    calculator.display_metrics()

    logger.info("\n--- Testing with Empty History ---")
    empty_history_calculator = PerformanceCalculator(portfolio_value_history=[], trades=[], initial_capital=100000.0)
    empty_metrics = empty_history_calculator.calculate_metrics()
    empty_history_calculator.display_metrics()

    logger.info("\n--- Testing with Single Point History (for returns calculation robustness) ---")
    single_point_history = [{'timestamp': pd.Timestamp('2023-01-01'), 'value': 100000.0}]
    single_point_calc = PerformanceCalculator(single_point_history, [], 100000.0)
    single_point_metrics = single_point_calc.calculate_metrics()
    single_point_calc.display_metrics()

    logger.info("\n--- Testing with trades but no P&L data (old FillEvent format) ---")
    trades_no_pnl = [
        FillEvent(pd.Timestamp('2023-01-02'), 'AAPL', 10, SignalType.BUY, 150.0, 1500.0, 1.0, None),
        FillEvent(pd.Timestamp('2023-01-03'), 'AAPL', 10, SignalType.SELL, 152.0, 1520.0, 1.0, None) # No P&L here
    ]
    calc_no_pnl_trades = PerformanceCalculator(history, trades_no_pnl, 100000.0)
    calc_no_pnl_trades.calculate_metrics()
    calc_no_pnl_trades.display_metrics() # Trade stats should show 0 closing trades with P&L

    logger.info("\n--- Testing with only winning trades for Profit Factor ---")
    winning_trades_only = [
        FillEvent(pd.Timestamp('2023-01-03'), 'AAPL', 10, SignalType.SELL, 152.0, 1520.0, 1.0, 19.0)
    ]
    calc_win_only = PerformanceCalculator(history, winning_trades_only, 100000.0)
    calc_win_only.calculate_metrics()
    calc_win_only.display_metrics() # Profit Factor should be Inf

    logger.info("\n--- Testing with only losing trades for Profit Factor ---")
    losing_trades_only = [
         FillEvent(pd.Timestamp('2023-01-05'), 'GOOG', 5, SignalType.SELL, 2490.0, 12450.0, 1.0, -51.0)
    ]
    calc_loss_only = PerformanceCalculator(history, losing_trades_only, 100000.0)
    calc_loss_only.calculate_metrics()
    calc_loss_only.display_metrics() # Profit Factor should be 0.0

    logger.info("\n--- Testing with no closing trades for Profit Factor ---")
    no_closing_trades = []
    calc_no_closing = PerformanceCalculator(history, no_closing_trades, 100000.0)
    calc_no_closing.calculate_metrics()
    calc_no_closing.display_metrics() # Profit Factor should be 0.0 (or N/A based on handling)File `backtester/performance.py` overwritten successfully.

Key changes in `PerformanceCalculator`:
-   `_calculate_trade_statistics` now correctly uses `fill_event.realized_pnl_for_this_fill` to sum P&L from actual closing trade events. It handles cases with no trades or no P&L data gracefully.
-   `_calculate_sortino_ratio` implemented, handling cases where downside deviation is zero or returns are empty.
-   `_calculate_calmar_ratio` implemented, using annualized return and max drawdown percentage. It also handles edge cases like zero max drawdown or insufficient data.
-   `calculate_metrics` now calls these new methods and incorporates their results into `self.metrics`.
-   `display_metrics` updated to handle potential `float('inf')` values for ratios.
-   The `if __name__ == '__main__':` example was updated to include `realized_pnl_for_this_fill` in dummy `FillEvent` data and added more test cases for trade statistics and ratios.
-   Added `logging` for warnings/errors.

All specified modifications for this subtask appear to be complete. The `PerformanceCalculator` is now significantly more comprehensive.

I am ready to submit the report.
