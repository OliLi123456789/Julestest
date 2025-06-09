import numpy as np
import pandas as pd
from typing import List, Dict
from backtester.portfolio import FillEvent # For trade analysis
from backtester.strategy import SignalType # Added import

class PerformanceCalculator:
    """
    Calculates various performance metrics from portfolio history.
    """
    def __init__(self, portfolio_value_history: List[Dict[str, any]], trades: List[FillEvent], initial_capital: float):
        # Ensure portfolio_value_history is a list of dicts with 'timestamp' and 'value'
        if not portfolio_value_history or not all('timestamp' in x and 'value' in x for x in portfolio_value_history):
            raise ValueError("portfolio_value_history must be a list of dicts with 'timestamp' and 'value' keys.")

        self.portfolio_df = pd.DataFrame(portfolio_value_history)
        if not self.portfolio_df.empty:
            self.portfolio_df['timestamp'] = pd.to_datetime(self.portfolio_df['timestamp'])
            self.portfolio_df = self.portfolio_df.set_index('timestamp').sort_index()
            self.portfolio_df['returns'] = self.portfolio_df['value'].pct_change().fillna(0)
        else:
            # Handle empty history: create empty DataFrame with expected columns
            self.portfolio_df = pd.DataFrame(columns=['value', 'returns']).set_index(pd.DatetimeIndex([]))


        self.trades = trades
        self.initial_capital = initial_capital
        self.metrics = {}

    def calculate_metrics(self, risk_free_rate_annual: float = 0.0):
        """
        Calculates all defined performance metrics.
        Risk-free rate is annualized (e.g., 0.02 for 2%).
        """
        if self.portfolio_df.empty:
            print("Warning: Portfolio history is empty. Cannot calculate metrics.")
            self.metrics = {
                'Total P&L': 0,
                'Total P&L Pct': 0,
                'Sharpe Ratio': 0,
                'Max Drawdown': 0,
                'Max Drawdown Pct': 0,
                'Win/Loss Ratio': 'N/A',
                'Total Trades': 0,
                'Winning Trades': 0,
                'Losing Trades': 0,
            }
            return self.metrics

        self.metrics['Total P&L'] = self.portfolio_df['value'].iloc[-1] - self.initial_capital
        self.metrics['Total P&L Pct'] = (self.metrics['Total P&L'] / self.initial_capital) * 100 if self.initial_capital else 0

        self.metrics['Sharpe Ratio'] = self._calculate_sharpe_ratio(risk_free_rate_annual)
        self.metrics['Max Drawdown'], self.metrics['Max Drawdown Pct'] = self._calculate_max_drawdown()

        win_loss_stats = self._calculate_win_loss_ratio()
        self.metrics.update(win_loss_stats)

        return self.metrics

    def _calculate_sharpe_ratio(self, risk_free_rate_annual: float) -> float:
        """
        Calculates the Sharpe Ratio.
        Assumes daily returns if not specified otherwise by data frequency.
        For PoC, assumes returns are per-bar and converts risk-free rate.
        Number of periods in a year (e.g., 252 for daily, 12 for monthly, 52 for weekly)
        This is a simplification; real Sharpe needs to know data frequency.
        Assuming 252 trading days for annualization if returns are daily-like.
        If returns are for a different frequency, this number should change.
        """
        if self.portfolio_df['returns'].empty or self.portfolio_df['returns'].std() == 0:
            return 0.0

        # Infer frequency or assume daily for PoC
        # This is a major simplification. A robust calculator would know the data's periodicity.
        # If we have less than a year of data, annualizing can be misleading.
        # For this PoC, let's assume the returns are "per period" and we annualize based on 252 periods/year.
        periods_in_year = 252 # Common assumption for daily stock data

        excess_returns = self.portfolio_df['returns'] - (risk_free_rate_annual / periods_in_year)
        sharpe_ratio = excess_returns.mean() / excess_returns.std() * np.sqrt(periods_in_year)
        return sharpe_ratio if pd.notna(sharpe_ratio) else 0.0


    def _calculate_max_drawdown(self) -> tuple[float, float]:
        """Calculates the Maximum Drawdown and its percentage."""
        cumulative = self.portfolio_df['value']
        peak = cumulative.cummax()
        drawdown = (cumulative - peak)
        max_drawdown_value = drawdown.min()

        # Get the peak value at the time of the max drawdown's occurrence
        peak_at_max_drawdown_time = peak.loc[drawdown.idxmin()]

        if max_drawdown_value == 0 or peak_at_max_drawdown_time == 0: # Avoid division by zero if peak is 0
             max_drawdown_percent = 0.0
        else:
            max_drawdown_percent = (max_drawdown_value / peak_at_max_drawdown_time) * 100

        return abs(max_drawdown_value), abs(max_drawdown_percent)


    def _calculate_win_loss_ratio(self) -> Dict[str, any]:
        """
        Calculates Win/Loss ratio based on individual trades.
        A trade is defined by a buy and a subsequent sell of the same symbol.
        This is a simplified P&L calculation per trade (doesn't handle partial sells complexly).
        """
        # This part is complex due to needing to pair buy/sell trades or analyze position P&L.
        # For PoC, let's simplify: iterate through FillEvents and try to define "trades".
        # A truly robust calculation requires careful management of positions and tax lots (FIFO/LIFO etc.).
        # Simplified: consider any SELL as realizing P&L on shares bought earlier at average cost.

        wins = 0
        losses = 0
        # This is a very basic way to look at trades. It doesn't perfectly match buys to sells.
        # It assumes each sell event realizes P&L against the average cost of current holdings.
        # This is not a standard way of calculating per-trade P&L but is simpler for PoC.

        # A better approach for PoC: Sum P&L from each FillEvent.
        # For BUY, P&L is 0 until sold. For SELL, P&L is (sell_price - avg_buy_price_of_sold_shares) * quantity.
        # The `Portfolio` class's `process_fill` would need to track cost basis more rigorously for this.
        # Let's assume `trades` (FillEvents) are already somewhat processed or we can infer.
        # The current `FillEvent.cost` is total transaction value. Not P&L.

        # Simplification: If a FillEvent is a SELL, we assume it generated profit if sell_price > some_cost_basis.
        # This is too simplistic. Let's count number of trades that were profitable.
        # For now, this part will be very basic or deferred if too complex for PoC scope.

        # Let's count profitable vs non-profitable closing trades (SELLS)
        # This requires knowing the cost basis for what was sold.
        # The current FillEvent doesn't store realized P&L.
        # Placeholder:
        profitable_sells = 0
        unprofitable_sells = 0
        neutral_sells = 0 # Sold at cost basis

        # This part is complex and depends on how `Portfolio` tracks cost basis and realized P&L.
        # Let's assume the `Portfolio` would need to log realized P&L for each SELL trade.
        # Since it's not there, we'll have a placeholder.
        # For now, this is a very rough estimate and not standard.
        # TODO: Enhance Portfolio to log realized P&L per trade for accurate win/loss.

        # Simplified: sum all cash changes that were positive from sells, and negative.
        # This is not standard.
        # For now, we'll just count total trades.
        total_trades = len([trade for trade in self.trades if trade.direction == SignalType.SELL]) # Count sell events as "closing" trades

        # This metric needs more work based on how P&L per trade is defined.
        # For now, returning placeholder values for win/loss.
        # A proper implementation would require pairing buy and sell trades or analyzing position P&L over time.

        stats = {
            'Total Trades': len(self.trades), # Counts every fill event. Could be half for round trips.
            'Winning Trades': 'N/A (Requires P&L per trade)',
            'Losing Trades': 'N/A (Requires P&L per trade)',
            'Win/Loss Ratio': 'N/A (Requires P&L per trade)'
        }
        return stats

    def display_metrics(self):
        print("\n--- Performance Metrics ---")
        if not self.metrics:
            print("Metrics not calculated yet.")
            return
        for key, value in self.metrics.items():
            if isinstance(value, float):
                print(f"{key}: {value:.2f}" + ("%" if "Pct" in key or "Ratio" in key else "")) # Basic formatting
            else:
                print(f"{key}: {value}")
        print("-------------------------")

if __name__ == '__main__':
    # Example Usage
    # Requires FillEvent from portfolio.py
    try:
        from backtester.portfolio import FillEvent, SignalType # For dummy trades
        import pandas as pd # For dummy timestamps
    except ImportError:
        print("Ensure pandas is installed and script is run in an environment where backtester module is found.")
        exit()

    # Dummy portfolio value history
    history = [
        {'timestamp': pd.Timestamp('2023-01-01'), 'value': 100000.0},
        {'timestamp': pd.Timestamp('2023-01-02'), 'value': 101000.0}, # +1%
        {'timestamp': pd.Timestamp('2023-01-03'), 'value': 100500.0}, # -0.495%
        {'timestamp': pd.Timestamp('2023-01-04'), 'value': 102000.0}, # +1.49%
        {'timestamp': pd.Timestamp('2023-01-05'), 'value': 101500.0}  # -0.49%
    ]
    # Dummy trades (FillEvents) - Win/Loss calculation needs more sophisticated trade objects or P&L logging
    dummy_trades = [
        FillEvent(pd.Timestamp('2023-01-02'), 'AAPL', 10, SignalType.BUY, 150.0, 1.0), # Cost 1501
        FillEvent(pd.Timestamp('2023-01-03'), 'AAPL', 10, SignalType.SELL, 152.0, 1.0), # Proceeds 1519. P&L = 1519 - 1501 = 18 (Win)
        FillEvent(pd.Timestamp('2023-01-04'), 'GOOG', 5, SignalType.BUY, 2500.0, 1.0), # Cost 12501
        FillEvent(pd.Timestamp('2023-01-05'), 'GOOG', 5, SignalType.SELL, 2490.0, 1.0) # Proceeds 12449. P&L = 12449 - 12501 = -52 (Loss)
    ] # This is simplified; actual FillEvent.cost is calculated differently.

    calculator = PerformanceCalculator(portfolio_value_history=history, trades=dummy_trades, initial_capital=100000.0)
    all_metrics = calculator.calculate_metrics(risk_free_rate_annual=0.02)
    calculator.display_metrics()

    print("\n--- Testing with Empty History ---")
    empty_history_calculator = PerformanceCalculator(portfolio_value_history=[], trades=[], initial_capital=100000.0)
    empty_metrics = empty_history_calculator.calculate_metrics()
    empty_history_calculator.display_metrics()

    print("\n--- Testing with Single Point History (for returns calculation robustness) ---")
    single_point_history = [{'timestamp': pd.Timestamp('2023-01-01'), 'value': 100000.0}]
    single_point_calc = PerformanceCalculator(single_point_history, [], 100000.0)
    single_point_metrics = single_point_calc.calculate_metrics()
    single_point_calc.display_metrics()
