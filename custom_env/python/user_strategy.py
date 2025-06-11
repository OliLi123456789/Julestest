# user_strategy.py - Example user strategy using the SDK, designed for event-driven backtesting.

import sdk # SDK must be in PYTHONPATH
import datetime # For type hinting and objects
from typing import Dict, List, Any, Optional # For type hints

# Attempt to import a user-installed package to verify strategy_requirements.txt worked.
try:
    import simplejson
    sdk_user_strategy_simplejson_version = simplejson.__version__
except ImportError:
    sdk_user_strategy_simplejson_version = "Not Found"


class MyMomentumStrategy(sdk.BaseStrategy):
    """
    Example event-driven strategy:
    - Buys on upward momentum based on previous bar.
    - Sells on downward momentum based on previous bar.
    - Uses sdk.get_market_data for initial history if needed, but primarily acts on on_bar data.
    """
    def __init__(self, strategy_id: str, symbols_of_interest: List[str], **strategy_params):
        super().__init__(strategy_id, symbols_of_interest, **strategy_params)
        # Parameters from config are in self.strategy_params
        self.lookback_days = self.strategy_params.get("lookback_days", 3) # Default if not in config
        self.trade_quantity = self.strategy_params.get("trade_quantity", 10) # Default if not in config

        # Store historical data fetched in on_start or on_bar if needed across calls
        self.historical_data_cache: Dict[str, List[Dict[str, Any]]] = {sym: [] for sym in self.symbols_of_interest}
        sdk.log(f"Strategy '{self.strategy_id}' initialized. Symbols: {self.symbols_of_interest}, "
                f"Lookback: {self.lookback_days}, Trade Qty: {self.trade_quantity}", level="INFO")
        sdk.log(f"User dependency 'simplejson' version: {sdk_user_strategy_simplejson_version}", level="INFO")

    def on_start(self):
        """Called once when the backtest starts."""
        super().on_start() # Calls BaseStrategy's on_start (which logs)
        # Example: Pre-fetch some historical data to warm up indicators, if any.
        # For this momentum strategy, we need at least lookback_days + 1 bars before making a decision.
        # The on_bar logic will handle accumulating enough data or using sdk.get_market_data carefully.
        sdk.log(f"Strategy '{self.strategy_id}': on_start called. Pre-loading initial data if necessary...", level="INFO")
        for symbol in self.symbols_of_interest:
            # Get enough data to satisfy lookback for the very first on_bar call.
            # end_date for this initial fetch should be *before* the first bar the strategy will receive in on_bar.
            # This is complex if on_bar receives the first bar of the configured backtest range.
            # Simpler: let on_bar handle initial data accumulation or use sdk.get_market_data with care.
            # For now, on_start can just log. on_bar will fetch if its cache is empty.
            pass

    def on_stop(self):
        """Called once when the backtest ends."""
        super().on_stop()
        sdk.log(f"Strategy '{self.strategy_id}': on_stop called. Final portfolio state:", level="INFO",
                extra_fields={"portfolio": sdk.get_portfolio_summary()}) # Get final summary

    def on_fill(self, fill_info: Dict[str, Any]):
        """Called by the CDE runner when an order submitted by this strategy is filled."""
        super().on_fill(fill_info) # Logs basic fill info
        # Custom strategy logic on fill:
        sdk.log(f"Strategy '{self.strategy_id}': Custom on_fill logic. Symbol: {fill_info.get('symbol')}, "
                f"Qty: {fill_info.get('quantity')}, Price: {fill_info.get('fill_price')}", level="INFO")
        # e.g., update internal trade tracking, adjust targets, etc.

    def on_bar(self, timestamp: datetime.datetime, current_bar_data_bundle: Dict[str, Dict[str, Any]]):
        """
        Called for each new bar of data for all subscribed symbols.
        current_bar_data_bundle: {'AAPL': {'OPEN': ..., 'CLOSE': ...}, 'GOOG': ...}
        """
        super().on_bar(timestamp, current_bar_data_bundle) # Logs basic info

        current_portfolio = sdk.get_portfolio_summary() # Get current portfolio state
        if not current_portfolio or "error" in current_portfolio:
            sdk.log(f"{self.strategy_id}: Could not get portfolio summary in on_bar. Skipping.", level="ERROR"); return

        for symbol in self.symbols_of_interest:
            if symbol not in current_bar_data_bundle:
                sdk.log(f"{self.strategy_id}: No data for symbol {symbol} in current_bar_data_bundle for {timestamp}. Skipping.", level="DEBUG"); continue

            # Update local cache of historical data
            current_bar_for_symbol = current_bar_data_bundle[symbol]
            self.historical_data_cache[symbol].append(current_bar_for_symbol)
            if len(self.historical_data_cache[symbol]) > (self.lookback_days + 1): # Keep cache size manageable
                self.historical_data_cache[symbol].pop(0)

            if len(self.historical_data_cache[symbol]) < (self.lookback_days + 1): # Need enough data
                sdk.log(f"{self.strategy_id}: Not enough cached data for {symbol} ({len(self.historical_data_cache[symbol])} bars) "
                        f"to meet lookback {self.lookback_days}+1. Skipping logic.", level="DEBUG")
                continue

            # Momentum logic using the cached historical data
            # Latest bar is current_bar_for_symbol (equivalent to self.historical_data_cache[symbol][-1])
            # Previous bar for momentum check is self.historical_data_cache[symbol][-2]
            latest_bar_from_cache = self.historical_data_cache[symbol][-1]
            previous_bar_from_cache = self.historical_data_cache[symbol][-2]

            sdk.log(f"{self.strategy_id} Data for {symbol}: Latest bar {latest_bar_from_cache['timestamp']} Close={latest_bar_from_cache['CLOSE']}; "
                    f"Prev bar {previous_bar_from_cache['timestamp']} Close={previous_bar_from_cache['CLOSE']}", level="DEBUG")

            current_position_qty = 0
            for pos in current_portfolio.get("positions", []):
                if pos["symbol"] == symbol: current_position_qty = pos["quantity"]; break

            sdk.log(f"{self.strategy_id} Current position for {symbol}: {current_position_qty}", level="DEBUG")

            # Trading Logic
            if latest_bar_from_cache['CLOSE'] > previous_bar_from_cache['CLOSE']: # Upward momentum
                if current_position_qty == 0:
                    sdk.log(f"{self.strategy_id}: Upward momentum for {symbol}, no position. Attempting BUY {self.trade_quantity} shares.", level="INFO")
                    sdk.submit_order(symbol=symbol, order_type="MARKET", quantity=self.trade_quantity)
            elif latest_bar_from_cache['CLOSE'] < previous_bar_from_cache['CLOSE']: # Downward momentum
                if current_position_qty > 0: # Only sell if holding a long position
                    sdk.log(f"{self.strategy_id}: Downward momentum for {symbol}, holding {current_position_qty}. Attempting SELL all.", level="INFO")
                    sdk.submit_order(symbol=symbol, order_type="MARKET", quantity=-current_position_qty)
            # else: Flat momentum, do nothing


if __name__ == "__main__":
    # This block is now primarily for basic testing of the strategy class in isolation,
    # or to show how it might be instantiated.
    # Full backtest execution is handled by cde_runner.py.

    sdk.setup_sdk_logging(level=logging.DEBUG, json_format=False) # Basic for local test

    logger = logging.getLogger(__name__) # For messages from this __main__ block
    logger.info("user_strategy.py __main__ block: For isolated strategy testing.")
    logger.info(f"Simplejson version (if installed by user): {sdk_user_strategy_simplejson_version}")

    # Example: Instantiate the strategy
    # Note: sdk.CURRENT_TIMESTAMP and other context globals are NOT set here.
    # Calls to sdk.submit_order or sdk.get_portfolio_summary will use their "not in context" fallbacks.

    test_symbols = ["AAPL", "MSFT"]
    strategy_params_example = {
        "lookback_days": 5,
        "trade_quantity": 25,
        "strategy_id": "TestMomentumRun"
        # custom parameters defined by strategy can go here
    }

    # To test methods, one would need to mock the SDK context or parts of it.
    # For example, to test on_bar, you'd need to provide mock timestamp and data.

    # strategy_instance = MyMomentumStrategy(
    #     strategy_id="my_test_strat_01",
    #     symbols_of_interest=test_symbols,
    #     **strategy_params_example
    # )

    # strategy_instance.on_start()

    # # Simulate an on_bar call
    # dummy_ts = datetime.datetime.now(datetime.timezone.utc)
    # dummy_bar_data = {
    #     "AAPL": {"OPEN": 150, "HIGH": 152, "LOW": 149, "CLOSE": 151, "VOLUME": 100000, "timestamp": dummy_ts.isoformat()+"Z"},
    #     "MSFT": {"OPEN": 250, "HIGH": 252, "LOW": 249, "CLOSE": 251, "VOLUME": 80000, "timestamp": dummy_ts.isoformat()+"Z"}
    # }
    # # To properly test on_bar that uses sdk.get_portfolio_summary(), one would need to mock sdk.CURRENT_PORTFOLIO_INSTANCE etc.
    # # strategy_instance.on_bar(dummy_ts, dummy_bar_data)

    # # Simulate an on_fill call
    # dummy_fill = {
    #     "timestamp": dummy_ts.isoformat()+"Z", "symbol": "AAPL", "quantity": 10, "direction": "BUY",
    #     "fill_price": 151.0, "commission": 1.0, "realized_pnl": None
    # }
    # # strategy_instance.on_fill(dummy_fill)

    # strategy_instance.on_stop()

    logger.info("user_strategy.py __main__ block finished. Run cde_runner.py for full backtest.")
