from trading_engine.oms.models import Order, OrderStatus
from trading_engine.oms.validator import OrderValidator

class OrderManagementSystem:
    def __init__(self, validator: OrderValidator):
        self.orders = {} # In-memory store for orders, keyed by order_id
        self.validator = validator
        # In a real system, you'd likely have a dedicated IBKR integration module
        # self.ibkr_router = IbkrOrderRouter()

    def submit_order(self, order: Order) -> str:
        """
        Submits a new order to the OMS.
        Validates the order and if valid, processes it.
        Returns the order_id.
        """
        print(f"Received new order: {order.order_id} for {order.symbol}")

        # Store the order first, regardless of validation outcome initially
        # This helps in tracking even rejected orders.
        self.orders[order.order_id] = order

        if self.validator.validate_order(order):
            print(f"Order {order.order_id} is valid. Proceeding to routing...")
            # Simulate routing to IBKR
            # In a real system, this would involve calling:
            # self.ibkr_router.route_order(order)
            # And then based on IBKR's initial ack/nack, the status might change.
            # For now, we assume it's pending until an external update.
            order.update_status(OrderStatus.PENDING)
            print(f"Order {order.order_id} routed (simulated). Current status: {order.status.value}")
        else:
            # Validator already updated order status to REJECTED and printed reason
            print(f"Order {order.order_id} was rejected during validation. Status: {order.status.value}")
            # No routing for rejected orders

        self.orders[order.order_id] = order # Re-store to capture status update by validator
        return order.order_id

    def get_order_status(self, order_id: str) -> OrderStatus | None:
        """Retrieves the status of an order by its ID."""
        order = self.orders.get(order_id)
        if order:
            return order.status
        return None

    def cancel_order(self, order_id: str) -> bool:
        """
        Requests cancellation of an order.
        In a real system, this would send a cancel request to IBKR.
        """
        order = self.orders.get(order_id)
        if not order:
            print(f"Cancel request failed: Order {order_id} not found.")
            return False

        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED]:
            print(f"Cancel request for order {order_id} denied: Order is already {order.status.value}.")
            return False

        # Simulate sending cancel request to IBKR
        # self.ibkr_router.request_cancel_order(order)
        # For now, directly update status to CANCELED if it's PENDING.
        # In reality, we'd wait for confirmation from IBKR.
        if order.status == OrderStatus.PENDING:
            order.update_status(OrderStatus.CANCELED)
            print(f"Order {order_id} cancellation processed (simulated). Status: {order.status.value}")
            self.orders[order.order_id] = order
            return True
        else:
            # This case might occur if the order got filled just before cancel request was processed
            print(f"Cancel request for order {order_id} could not be processed as it's not in a cancelable state ({order.status.value}).")
            return False

    def _handle_ibkr_fill_update(self, order_id: str, fill_price: float, fill_quantity: int):
        """
        Callback method to be invoked by the IBKR integration layer when an order is filled.
        This is a placeholder for how the OMS would receive updates.
        """
        order = self.orders.get(order_id)
        if order:
            # In a real scenario, you'd handle partial fills, average fill price, etc.
            # For simplicity, we'll assume full fill for now.
            order.update_status(OrderStatus.FILLED)
            order.price = fill_price # Update order price to actual fill price
            order.quantity = fill_quantity # Update quantity if partially filled (though not fully handled here)
            print(f"Order {order_id} filled. Price: {fill_price}, Quantity: {fill_quantity}. Status: {order.status.value}")
            self.orders[order.order_id] = order
            # Here, you might trigger notifications or update position tracking.
        else:
            print(f"Received fill update for unknown order {order_id}")

    def _handle_ibkr_cancel_confirm(self, order_id: str):
        """
        Callback method for when IBKR confirms an order is canceled.
        """
        order = self.orders.get(order_id)
        if order:
            if order.status != OrderStatus.CANCELED: # Avoid re-processing if already marked canceled
                order.update_status(OrderStatus.CANCELED)
                print(f"Order {order_id} confirmed canceled by IBKR. Status: {order.status.value}")
                self.orders[order.order_id] = order
        else:
            print(f"Received cancel confirmation for unknown order {order_id}")

    def _handle_ibkr_rejection_update(self, order_id: str, reason: str):
        """
        Callback method for when IBKR rejects an order after initial acceptance (e.g., due to exchange rejection).
        """
        order = self.orders.get(order_id)
        if order:
            order.update_status(OrderStatus.REJECTED)
            print(f"Order {order_id} rejected by IBKR. Reason: {reason}. Status: {order.status.value}")
            self.orders[order.order_id] = order
        else:
            print(f"Received rejection for unknown order {order_id}")

    def get_all_orders(self) -> list[Order]:
        """Returns a list of all orders in the system."""
        return list(self.orders.values())

# Example Usage (for demonstration purposes, would typically be in a main application file)
if __name__ == '__main__':
    from trading_engine.oms.models import Order, OrderType # Added import

    validator = OrderValidator()
    oms = OrderManagementSystem(validator)

    # Create and submit a valid market order
    valid_market_order = Order(user_id="user_with_funds", symbol="AAPL", quantity=10, order_type=OrderType.MARKET)
    oms.submit_order(valid_market_order)
    print(f"Status of {valid_market_order.order_id}: {oms.get_order_status(valid_market_order.order_id)}")
    print("-" * 20)

    # Create and submit a valid limit order
    valid_limit_order = Order(user_id="user_with_funds", symbol="GOOG", quantity=5, order_type=OrderType.LIMIT, price=2400.0)
    oms.submit_order(valid_limit_order)
    print(f"Status of {valid_limit_order.order_id}: {oms.get_order_status(valid_limit_order.order_id)}")
    print("-" * 20)

    # Create and submit an order that will be rejected (insufficient funds)
    insufficient_funds_order = Order(user_id="user_with_insufficient_funds", symbol="AAPL", quantity=100, order_type=OrderType.LIMIT, price=150.0) # Cost = 15000
    oms.submit_order(insufficient_funds_order)
    print(f"Status of {insufficient_funds_order.order_id}: {oms.get_order_status(insufficient_funds_order.order_id)}")
    print("-" * 20)

    # Create and submit an order for a closed market
    closed_market_order = Order(user_id="user_with_funds", symbol="FX_CLOSED_MARKET", quantity=10, order_type=OrderType.MARKET)
    oms.submit_order(closed_market_order)
    print(f"Status of {closed_market_order.order_id}: {oms.get_order_status(closed_market_order.order_id)}")
    print("-" * 20)

    # Create and submit an order that exceeds max order size
    large_order = Order(user_id="user_test", symbol="AAPL", quantity=2000, order_type=OrderType.MARKET)
    oms.submit_order(large_order)
    print(f"Status of {large_order.order_id}: {oms.get_order_status(large_order.order_id)}")
    print("-" * 20)

    # Simulate an order fill update from IBKR
    if valid_market_order.status == OrderStatus.PENDING:
        oms._handle_ibkr_fill_update(valid_market_order.order_id, fill_price=150.50, fill_quantity=10)
    print(f"Status of {valid_market_order.order_id} after fill: {oms.get_order_status(valid_market_order.order_id)}")
    print("-" * 20)

    # Try to cancel a pending order (the limit order)
    print(f"Attempting to cancel order {valid_limit_order.order_id}...")
    cancel_success = oms.cancel_order(valid_limit_order.order_id)
    print(f"Cancellation successful: {cancel_success}. Status of {valid_limit_order.order_id}: {oms.get_order_status(valid_limit_order.order_id)}")
    print("-" * 20)

    # Try to cancel an already filled order
    print(f"Attempting to cancel already filled order {valid_market_order.order_id}...")
    cancel_success_filled = oms.cancel_order(valid_market_order.order_id)
    print(f"Cancellation successful: {cancel_success_filled}. Status of {valid_market_order.order_id}: {oms.get_order_status(valid_market_order.order_id)}")
    print("-" * 20)

    print("\nAll Orders in OMS:")
    for o in oms.get_all_orders():
        print(f"  - {o} - Status: {o.status.value} - Updated: {o.updated_at}")
