# Platform FAQ

## How do I place a market order?
Use the `sdk.submit_order(symbol="XYZ", order_type="MARKET", quantity=100)` function.
Market orders execute at the best available price. Remember that quantity should be positive for a BUY and negative for a SELL if your SDK's submit_order expects signed quantity. Consult `sdk.submit_order` documentation for exact quantity conventions.

## What about limit orders?
For limit orders, specify a price: `sdk.submit_order(symbol="ABC", order_type="LIMIT", quantity=50, price=120.50)`.
It will fill at your limit price or better. Ensure the price is positive.

## How do I check my current positions?
Use `sdk.get_portfolio_summary()` to get an overview of all positions and cash.
To get details for a specific symbol, use `sdk.get_position(symbol="XYZ")`.

## How does the SDK handle historical data?
The `sdk.get_market_data(symbol, timeframe, lookback_rows, start_date, end_date)` function can be used.
It typically reads from CSV files provided in a configured data directory.
For ongoing strategies in an event-driven backtest (`on_bar`), use the data bundle passed to `on_bar` for the current bar, and use `get_market_data` primarily for initial history loading or supplemental data.

## What are the main strategy lifecycle methods?
Strategies inheriting from `sdk.BaseStrategy` should implement:
- `__init__(self, strategy_id, symbols_of_interest, **strategy_params)`: For initialization.
- `on_start(self)`: Called at the beginning of the backtest.
- `on_bar(self, timestamp, current_bar_data_bundle)`: Called for each new market data bar.
- `on_fill(self, fill_info)`: Called when one of your orders is filled.
- `on_stop(self)`: Called at the end of the backtest.
