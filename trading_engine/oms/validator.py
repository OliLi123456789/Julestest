from trading_engine.oms.models import Order, OrderType, OrderStatus

# Mocked functions for dependencies - replace with actual implementations
def get_user_balance(user_id: str) -> float:
    """Mocked function to get user's account balance."""
    # In a real system, this would query a database or another service
    print(f"Checking balance for user {user_id}...")
    if user_id == "user_with_funds":
        return 100000.0  # Sufficient funds
    elif user_id == "user_with_insufficient_funds":
        return 100.0 # Insufficient funds for most orders
    return 5000.0 # Default for other users

def is_market_open(symbol: str) -> bool:
    """Mocked function to check if the market for the symbol is open."""
    # In a real system, this would check against actual market hours
    print(f"Checking market hours for {symbol}...")
    if symbol == "FX_CLOSED_MARKET":
        return False
    return True

def get_max_order_size(symbol: str, user_id: str) -> int:
    """Mocked function to get max order size allowed for a symbol and user."""
    print(f"Checking max order size for {symbol} for user {user_id}...")
    return 1000 # Default max order size

def get_current_price(symbol: str) -> float:
    """Mocked function to get current market price for a symbol."""
    # In a real system, this would fetch from a market data feed
    if symbol == "AAPL":
        return 150.0
    elif symbol == "GOOG":
        return 2500.0
    return 100.0 # Default price

class OrderValidator:
    def __init__(self, balance_service=get_user_balance, market_service=is_market_open, risk_service=get_max_order_size):
        self.get_user_balance = balance_service
        self.is_market_open = market_service
        self.get_max_order_size = risk_service

    def validate_order(self, order: Order) -> bool:
        """Validates an order based on various criteria."""
        if order.quantity <= 0:
            print(f"Order rejected: Invalid quantity ({order.quantity})")
            order.update_status(OrderStatus.REJECTED)
            return False

        if order.order_type == OrderType.LIMIT and order.price is None:
            print(f"Order rejected: Price not specified for LIMIT order")
            order.update_status(OrderStatus.REJECTED)
            return False

        if order.order_type == OrderType.LIMIT and order.price <= 0:
            print(f"Order rejected: Invalid price ({order.price}) for LIMIT order")
            order.update_status(OrderStatus.REJECTED)
            return False

        if not self.is_market_open(order.symbol):
            print(f"Order rejected: Market for {order.symbol} is closed")
            order.update_status(OrderStatus.REJECTED)
            return False

        # Pre-trade risk check: Max order size
        max_size = self.get_max_order_size(order.symbol, order.user_id)
        if order.quantity > max_size:
            print(f"Order rejected: Quantity {order.quantity} exceeds max allowed size {max_size}")
            order.update_status(OrderStatus.REJECTED)
            return False

        # Pre-trade risk check: Sufficient funds
        # For market orders, estimate cost using current price (mocked)
        # For limit orders, use the limit price
        estimated_cost = 0
        if order.order_type == OrderType.MARKET:
            current_price = get_current_price(order.symbol)
            if current_price is None: # Could happen if market data is unavailable
                 print(f"Order rejected: Could not retrieve current price for {order.symbol} to estimate cost")
                 order.update_status(OrderStatus.REJECTED)
                 return False
            estimated_cost = order.quantity * current_price
        elif order.order_type == OrderType.LIMIT:
            estimated_cost = order.quantity * order.price

        user_balance = self.get_user_balance(order.user_id)
        if user_balance < estimated_cost:
            print(f"Order rejected: Insufficient funds. Estimated cost: {estimated_cost}, Balance: {user_balance}")
            order.update_status(OrderStatus.REJECTED)
            return False

        print(f"Order {order.order_id} validated successfully.")
        return True
