# sdk.py - Proof-of-Concept SDK for user strategies

import json
import datetime

# --- Mocked Data and Services ---
# In a real system, these would interact with the trading platform's core services.

MOCK_MARKET_DATA = {
    "AAPL": {
        "1d": [
            {"timestamp": "2023-01-01T10:00:00Z", "open": 150.0, "high": 151.0, "low": 149.0, "close": 150.5, "volume": 10000},
            {"timestamp": "2023-01-02T10:00:00Z", "open": 150.6, "high": 152.0, "low": 150.0, "close": 151.5, "volume": 12000},
            {"timestamp": "2023-01-03T10:00:00Z", "open": 151.6, "high": 153.0, "low": 151.0, "close": 152.5, "volume": 11000},
        ]
    },
    "GOOG": {
        "1d": [
            {"timestamp": "2023-01-01T10:00:00Z", "open": 2500.0, "high": 2510.0, "low": 2490.0, "close": 2505.0, "volume": 5000},
            {"timestamp": "2023-01-02T10:00:00Z", "open": 2506.0, "high": 2520.0, "low": 2500.0, "close": 2515.0, "volume": 6000},
        ]
    }
}

MOCK_PORTFOLIO = {
    "cash": 100000.0,
    "positions": {
        "AAPL": {"quantity": 50, "average_price": 140.0}
    }
}

# --- SDK Functions ---

def log(message):
    """Logs a message. In a real system, this would go to a structured logger."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[USER LOG] {timestamp}: {message}") # Simple print for PoC

def get_market_data(symbol: str, timeframe: str = "1d", lookback_period: int = 10) -> list:
    """
    Retrieves historical market data for a symbol.
    In PoC, returns mocked data.
    """
    log(f"SDK: get_market_data called for {symbol}, timeframe {timeframe}, lookback {lookback_period}")
    if symbol in MOCK_MARKET_DATA and timeframe in MOCK_MARKET_DATA[symbol]:
        data = MOCK_MARKET_DATA[symbol][timeframe]
        # Respect lookback_period by returning the tail of the data
        return data[-lookback_period:]
    log(f"SDK: No data found for {symbol} with timeframe {timeframe}")
    return []

def submit_order(symbol: str, order_type: str, quantity: int, price: float = None, tif: str = "GTC") -> dict:
    """
    Submits a trading order.
    In PoC, logs the order and returns a mock confirmation.
    'order_type' can be "MARKET", "LIMIT".
    'tif' (Time In Force) e.g., "GTC" (Good 'Til Canceled), "IOC" (Immediate or Cancel), "FOK" (Fill or Kill).
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    order_id = f"ORD-{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)}" # Mock order ID

    log(f"SDK: submit_order called: Symbol={symbol}, Type={order_type}, Qty={quantity}, Price={price}, TIF={tif}")

    if quantity <= 0:
        log("SDK: Order quantity must be positive.")
        return {"status": "REJECTED", "order_id": None, "reason": "Invalid quantity"}

    # Mock order processing logic (e.g., basic validation)
    if order_type.upper() == "LIMIT" and price is None:
        log("SDK: Price must be specified for LIMIT orders.")
        return {"status": "REJECTED", "order_id": None, "reason": "Price not specified for LIMIT order"}

    confirmation = {
        "status": "ACCEPTED", # In a real system, this might be PENDING initially
        "order_id": order_id,
        "symbol": symbol,
        "order_type": order_type.upper(),
        "quantity": quantity,
        "price": price,
        "timestamp": timestamp,
        "tif": tif
    }
    log(f"SDK: Order {order_id} for {symbol} accepted (mock).")
    # In a real system, this would be sent to the OMS.
    # For backtesting, it would go to the backtest portfolio.
    return confirmation

def get_portfolio_summary() -> dict:
    """
    Retrieves a summary of the current portfolio (cash, positions).
    In PoC, returns mocked data.
    """
    log("SDK: get_portfolio_summary called.")
    return MOCK_PORTFOLIO

# --- Strategy Interface (Conceptual) ---
# User strategies would typically implement a class with methods like these.

class BaseStrategy:
    def __init__(self, sdk_context):
        self.sdk = sdk_context # Provides access to log, get_market_data, etc.
        self.sdk.log("BaseStrategy initialized.")

    def on_bar(self, symbol: str, current_bar_data: dict):
        """
        Called for each new bar of data for a subscribed symbol.
        'current_bar_data' is a dictionary like one entry from MOCK_MARKET_DATA.
        """
        self.sdk.log(f"BaseStrategy on_bar called for {symbol}. Data: {current_bar_data}")
        # Strategy logic would go here.

    def on_tick(self, symbol: str, tick_data: dict):
        """
        Called for each new tick (if strategy subscribes to tick data).
        'tick_data' would contain information like last price, bid, ask.
        """
        self.sdk.log(f"BaseStrategy on_tick called for {symbol}. Data: {tick_data}")
        # Strategy logic for tick data.

    def on_shutdown(self):
        """
        Called when the strategy is being stopped or the system is shutting down.
        Useful for cleanup, saving state, etc.
        """
        self.sdk.log("BaseStrategy on_shutdown called.")

if __name__ == "__main__":
    # Example of how the SDK functions might be used directly (outside a strategy class)
    log("SDK direct usage example started.")

    aapl_data = get_market_data("AAPL", "1d", lookback_period=2)
    log(f"Received AAPL data: {json.dumps(aapl_data, indent=2)}")

    goog_data = get_market_data("GOOG", "1d", lookback_period=1)
    log(f"Received GOOG data: {json.dumps(goog_data, indent=2)}")

    non_existent_data = get_market_data("XYZ", "1d")
    log(f"Received XYZ data: {json.dumps(non_existent_data, indent=2)}")

    order_conf_1 = submit_order("AAPL", "MARKET", 10)
    log(f"Order 1 Conf: {json.dumps(order_conf_1, indent=2)}")

    order_conf_2 = submit_order("GOOG", "LIMIT", 5, price=2500.0)
    log(f"Order 2 Conf: {json.dumps(order_conf_2, indent=2)}")

    order_conf_3 = submit_order("TSLA", "LIMIT", 0, price=300.0) # Invalid quantity
    log(f"Order 3 Conf: {json.dumps(order_conf_3, indent=2)}")

    portfolio = get_portfolio_summary()
    log(f"Portfolio Summary: {json.dumps(portfolio, indent=2)}")

    log("SDK direct usage example finished.")
