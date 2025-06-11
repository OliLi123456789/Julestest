from trading_engine.oms.models import Order, OrderType, OrderStatus
import logging # Added for logger

logger = logging.getLogger(__name__) # Added logger

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

    def _reject_order(self, order: Order, reason: str):
        logger.warning(f"Order {order.order_id} rejected: {reason}")
        order.update_status(OrderStatus.REJECTED)
        # In a real system, you might store the rejection reason in the order object too,
        # if a field for it exists (e.g., order.rejection_reason = reason).

    def validate_order(self, order: Order) -> bool:
        """Validates an order based on various criteria."""
        if order.quantity <= 0:
            self._reject_order(order, f"Invalid quantity ({order.quantity})")
            return False

        # Common validations based on order type
        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                self._reject_order(order, "Price not specified for LIMIT order")
                return False
            if order.price <= 0:
                self._reject_order(order, f"Invalid price ({order.price}) for LIMIT order")
                return False

        elif order.order_type == OrderType.STOP:
            if order.stop_price is None or order.stop_price <= 0:
                self._reject_order(order, "Stop price required and must be positive for STOP order")
                return False
            if order.price is not None: # order.price is used for limit_price in domain model
                self._reject_order(order, "Limit price (order.price) should not be set for STOP (market) order")
                return False

        elif order.order_type == OrderType.STOP_LIMIT:
            if order.stop_price is None or order.stop_price <= 0:
                self._reject_order(order, "Stop price required and must be positive for STOP_LIMIT order")
                return False
            if order.price is None or order.price <= 0: # order.price is limit_price
                self._reject_order(order, "Limit price (order.price) required and must be positive for STOP_LIMIT order")
                return False
            # Optional: check if stop_price and limit_price are sensible relative to current market price or each other.
            # e.g., for a buy stop_limit, limit_price might be expected to be >= stop_price.
            # This can be complex and market-dependent, so omitted for now.

        elif order.order_type == OrderType.TRAIL:
            if order.trailing_percent is None and order.trailing_amount is None:
                self._reject_order(order, "Either trailing_percent or trailing_amount must be specified for TRAIL order")
                return False
            if order.trailing_percent is not None and order.trailing_amount is not None:
                self._reject_order(order, "Specify either trailing_percent or trailing_amount for TRAIL order, not both")
                return False
            if order.trailing_percent is not None and (order.trailing_percent <= 0 or order.trailing_percent >= 100):
                self._reject_order(order, "Trailing percent must be positive and typically less than 100 for TRAIL order")
                return False
            if order.trailing_amount is not None and order.trailing_amount <= 0:
                self._reject_order(order, "Trailing amount must be positive for TRAIL order")
                return False
            if order.price is not None: # order.price is limit_price
                self._reject_order(order, "Limit price (order.price) should not be set for TRAIL (market) order")
                return False
            if order.stop_price is not None: # Regular stop_price is not used for TRAIL
                self._reject_order(order, "Stop price should not be set for TRAIL order; use trail_stop_price for initial trigger if needed.")
            if order.trail_stop_price is not None and order.trail_stop_price <= 0:
                self._reject_order(order, "Initial trail_stop_price, if specified, must be positive for TRAIL order")
                return False


        # General validations (market open, max order size, funds)
        if not self.is_market_open(order.symbol):
            self._reject_order(order, f"Market for {order.symbol} is closed")
            return False

        max_size = self.get_max_order_size(order.symbol, order.user_id)
        if order.quantity > max_size:
            self._reject_order(order, f"Quantity {order.quantity} exceeds max allowed size {max_size}")
            return False

        # Pre-trade risk check: Sufficient funds (simplified)
        # For market orders, estimate cost using current price (mocked)
        # For limit orders, use the limit price
        estimated_cost = 0
        if order.order_type == OrderType.MARKET or order.order_type == OrderType.STOP or order.order_type == OrderType.TRAIL:
            # For market-like orders, estimate cost using current price or stop/trail_stop_price as reference
            # This is a rough estimation.
            price_ref = get_current_price(order.symbol) # Fallback to current market
            if order.order_type == OrderType.STOP and order.stop_price is not None:
                price_ref = order.stop_price
            elif order.order_type == OrderType.TRAIL and order.trail_stop_price is not None: # Use initial trigger if set
                price_ref = order.trail_stop_price

            if price_ref is None:
                 self._reject_order(order, f"Could not retrieve/determine reference price for {order.symbol} to estimate cost for {order.order_type.value} order")
                 return False
            estimated_cost = abs(order.quantity * price_ref) # abs for short sales value
        elif order.order_type == OrderType.LIMIT or order.order_type == OrderType.STOP_LIMIT:
            if order.price is None: # Should have been caught by specific validation already
                 self._reject_order(order, "Limit price not set for cost estimation")
                 return False
            estimated_cost = abs(order.quantity * order.price)

        user_balance = self.get_user_balance(order.user_id)
        if user_balance < estimated_cost:
            self._reject_order(order, f"Insufficient funds. Estimated cost: {estimated_cost}, Balance: {user_balance}")
            return False

        logger.info(f"Order {order.order_id} validated successfully.")
        return True
