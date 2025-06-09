from enum import Enum
import datetime

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

class Order:
    def __init__(self, user_id: str, symbol: str, quantity: int, order_type: OrderType, price: float = None, order_id: str = None):
        self.order_id = order_id if order_id else self._generate_order_id()
        self.user_id = user_id
        self.symbol = symbol
        self.quantity = quantity
        self.order_type = order_type
        self.price = price
        self.status = OrderStatus.PENDING
        self.created_at = datetime.datetime.now()
        self.updated_at = datetime.datetime.now()

    def _generate_order_id(self) -> str:
        # In a real system, this would be a more robust ID generation mechanism (e.g., UUID)
        return f"ORD-{datetime.datetime.now().timestamp()}"

    def update_status(self, status: OrderStatus):
        self.status = status
        self.updated_at = datetime.datetime.now()

    def __repr__(self):
        return f"<Order {self.order_id} ({self.symbol} {self.quantity} @ {self.price if self.price else 'MARKET'})>"
