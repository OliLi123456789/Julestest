from enum import Enum
import datetime
import uuid # Added for UUID generation

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"            # Market order triggered at stop_price
    STOP_LIMIT = "STOP_LIMIT"  # Becomes a Limit order at limit_price when stop_price is reached
    TRAIL = "TRAIL"          # Trailing Stop Market order
    # TRAIL_LIMIT = "TRAIL_LIMIT" # Can be added later

class OrderStatus(Enum):
    NEW = "NEW"  # Order created in OMS, not yet validated or sent
    PENDING_SUBMIT = "PENDING_SUBMIT" # OMS has sent to router, awaiting broker acknowledgement
    API_PENDING = "API_PENDING"      # Broker API received, not yet at exchange (IB: ApiPending)
    PRE_SUBMITTED = "PRE_SUBMITTED"  # Submitted to exchange, not yet live (IB: PreSubmitted)
    SUBMITTED = "SUBMITTED"          # Accepted by exchange (IB: Submitted)
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_CANCEL = "PENDING_CANCEL" # Cancel request sent to broker, awaiting confirmation
    API_CANCELLED = "API_CANCELLED"    # Broker API received cancel, not yet confirmed by exchange (IB: ApiCancelled)
    CANCELED = "CANCELED"            # Confirmed canceled (IB: Cancelled)
    REJECTED = "REJECTED"            # Rejected by OMS validator or by Broker
    INACTIVE = "INACTIVE"            # Order is not working (e.g., price condition, error)
    ERROR = "ERROR"                  # OMS internal error state for an order
    # PENDING_REPLACE = "PENDING_REPLACE" # If supporting order modifications


class Order:
    def __init__(self,
                 user_id: str,
                 symbol: str,
                 quantity: float, # Changed to float to align with db_models
                 order_type: OrderType,
                 price: Optional[float] = None,
                 order_id: Optional[str] = None,
                 broker_order_id: Optional[str] = None,
                 perm_id: Optional[int] = None,
                 filled_quantity: float = 0.0,
                 average_fill_price: Optional[float] = None,
                 version: int = 1,
                 stop_price: Optional[float] = None, # New field
                 trailing_percent: Optional[float] = None, # New field
                 trailing_amount: Optional[float] = None, # New field
                 trail_stop_price: Optional[float] = None): # New field
        self.order_id = order_id if order_id else self._generate_order_id()
        self.user_id = user_id
        self.symbol = symbol
        self.quantity = quantity
        self.order_type = order_type
        self.price = price # This is limit_price for LIMIT orders
        self.status = OrderStatus.NEW # Changed default status
        self.created_at = datetime.datetime.utcnow()
        self.updated_at = datetime.datetime.utcnow()

        # New attributes
        self.broker_order_id = broker_order_id
        self.perm_id = perm_id
        self.filled_quantity = filled_quantity
        self.average_fill_price = average_fill_price
        self.version = version
        self.stop_price = stop_price
        self.trailing_percent = trailing_percent
        self.trailing_amount = trailing_amount
        self.trail_stop_price = trail_stop_price


    def _generate_order_id(self) -> str:
        return str(uuid.uuid4()) # Changed to UUID

    def update_status(self, status: OrderStatus):
        self.status = status
        self.updated_at = datetime.datetime.utcnow() # Changed to utcnow
        self.version += 1 # Increment version

    def __repr__(self):
        details = f"Order {self.order_id} ({self.user_id} - {self.symbol} {self.quantity} {self.order_type.value}"
        if self.order_type == OrderType.LIMIT and self.price is not None:
            details += f" @ LMT {self.price}"
        if self.order_type == OrderType.STOP and self.stop_price is not None:
            details += f" @ STP {self.stop_price}"
        if self.order_type == OrderType.STOP_LIMIT and self.stop_price is not None and self.price is not None:
            details += f" @ STP {self.stop_price} LMT {self.price}"
        if self.order_type == OrderType.TRAIL:
            if self.trailing_percent is not None:
                details += f" TRAIL {self.trailing_percent}%"
            elif self.trailing_amount is not None:
                details += f" TRAIL ${self.trailing_amount}"
            if self.trail_stop_price is not None:
                details += f" (Initial STP: {self.trail_stop_price})"
        details += f") Status: {self.status.value}, V:{self.version}"
        return f"<{details}>"
