# user_strategy.py - Example user strategy using the SDK

# The 'sdk' module is expected to be in the PYTHONPATH when this script is run inside the Docker container.
import sdk

class MyMomentumStrategy:
    def __init__(self, symbols_to_trade, lookback_days=3):
        self.symbols = symbols_to_trade
        self.lookback_days = lookback_days
        sdk.log(f"MyMomentumStrategy initialized for symbols: {self.symbols}, lookback: {self.lookback_days} days.")
        self.portfolio = sdk.get_portfolio_summary() # Get initial portfolio state

    def run_logic_for_symbol(self, symbol):
        sdk.log(f"--- Running strategy logic for {symbol} ---")

        # 1. Get market data
        # For simplicity, using '1d' timeframe and a short lookback from sdk's mock data
        market_data = sdk.get_market_data(symbol=symbol, timeframe="1d", lookback_period=self.lookback_days)

        if not market_data or len(market_data) < 2: # Need at least 2 bars to check momentum
            sdk.log(f"Not enough market data for {symbol} to calculate momentum (need at least 2 bars). Skipping.")
            return

        # 2. Simple Momentum Logic:
        # If the close price of the latest bar is higher than the close price of the bar before it, consider it upward momentum.
        latest_bar = market_data[-1]
        previous_bar = market_data[-2]

        sdk.log(f"Latest bar for {symbol}: Close={latest_bar['close']} at {latest_bar['timestamp']}")
        sdk.log(f"Previous bar for {symbol}: Close={previous_bar['close']} at {previous_bar['timestamp']}")

        current_position_qty = self.portfolio.get("positions", {}).get(symbol, {}).get("quantity", 0)

        if latest_bar['close'] > previous_bar['close']:
            sdk.log(f"Upward momentum detected for {symbol}.")
            if current_position_qty == 0:
                sdk.log(f"No current position in {symbol}. Attempting to BUY 10 shares.")
                order_result = sdk.submit_order(symbol=symbol, order_type="MARKET", quantity=10)
                sdk.log(f"Order submission result for {symbol} BUY: {order_result}")
                if order_result.get("status") == "ACCEPTED":
                    # Update mock portfolio for this PoC. Real SDK might not need this.
                    self.portfolio["positions"].setdefault(symbol, {"quantity": 0, "average_price": 0})
                    self.portfolio["positions"][symbol]["quantity"] += 10
                    # Assume fill price for simplicity, real system would wait for fill event
            else:
                sdk.log(f"Already have a position of {current_position_qty} in {symbol}. Holding.")

        elif latest_bar['close'] < previous_bar['close']:
            sdk.log(f"Downward momentum detected for {symbol}.")
            if current_position_qty > 0:
                sdk.log(f"Currently holding {current_position_qty} shares of {symbol}. Attempting to SELL all.")
                order_result = sdk.submit_order(symbol=symbol, order_type="MARKET", quantity=current_position_qty)
                sdk.log(f"Order submission result for {symbol} SELL: {order_result}")
                if order_result.get("status") == "ACCEPTED":
                     self.portfolio["positions"][symbol]["quantity"] = 0 # Cleared position
            else:
                sdk.log(f"No current position in {symbol} to sell. Doing nothing.")
        else:
            sdk.log(f"No significant price change (flat momentum) for {symbol}. Holding.")

        sdk.log(f"--- Finished strategy logic for {symbol} ---")


    def run(self):
        sdk.log("MyMomentumStrategy run method started.")
        for symbol in self.symbols:
            self.run_logic_for_symbol(symbol)

        final_portfolio = sdk.get_portfolio_summary() # Get final (mocked) portfolio state
        sdk.log(f"MyMomentumStrategy run method finished. Final portfolio: {final_portfolio}")


if __name__ == "__main__":
    sdk.log("User_strategy.py script started directly.")

    # Define symbols the strategy will trade
    # These symbols need to have mock data in sdk.py for this PoC to be meaningful
    tradeable_symbols = ["AAPL", "GOOG"]

    strategy_instance = MyMomentumStrategy(symbols_to_trade=tradeable_symbols, lookback_days=3)
    strategy_instance.run()

    sdk.log("User_strategy.py script finished.")
