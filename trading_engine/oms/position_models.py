import datetime
import uuid
from typing import Optional # Added for Optional type hint

class Position:
    def __init__(self,
                 position_id: Optional[str] = None, # Made Optional for default generation
                 user_id: Optional[str] = None,    # Made Optional, assuming it will be set
                 symbol: Optional[str] = None,     # Made Optional
                 sec_type: str = "STK",
                 exchange: str = "SMART",
                 currency: str = "USD",
                 con_id: Optional[int] = None,     # Made Optional
                 quantity: float = 0.0,
                 average_entry_price: float = 0.0,
                 created_at: Optional[datetime.datetime] = None,
                 updated_at: Optional[datetime.datetime] = None,
                 version: int = 1,
                 realized_pnl: float = 0.0,      # New P&L field
                 unrealized_pnl: float = 0.0,    # New P&L field
                 total_commission_paid: float = 0.0): # New commission field
        self.position_id = position_id if position_id else str(uuid.uuid4())
        self.user_id = user_id
        self.symbol = symbol
        self.sec_type = sec_type
        self.exchange = exchange
        self.currency = currency
        self.con_id = con_id
        self.quantity = quantity
        self.average_entry_price = average_entry_price
        self.created_at = created_at if created_at else datetime.datetime.utcnow()
        self.updated_at = updated_at if updated_at else datetime.datetime.utcnow()
        self.version = version
        self.realized_pnl = realized_pnl
        self.unrealized_pnl = unrealized_pnl
        self.total_commission_paid = total_commission_paid

    def __repr__(self):
        return (f"<Position {self.position_id} ({self.user_id} - {self.symbol}: {self.quantity} @ "
                f"{self.average_entry_price} {self.currency}, RealizedPnL: {self.realized_pnl:.2f})>")

    # The update_position method is removed as its logic will be handled by PositionManager
    # and directly on the attributes of the Position object fetched by PositionManager.

    def set_unrealized_pnl(self, new_unrealized_pnl: float) -> bool:
        """
        Sets the unrealized P&L for the position and updates metadata if changed.
        Returns True if the value was changed, False otherwise.
        """
        # Using a small tolerance for float comparison can be good practice
        # For simplicity, direct comparison is used here.
        if abs(self.unrealized_pnl - new_unrealized_pnl) > 1e-9: # Check if substantially different
            self.unrealized_pnl = new_unrealized_pnl
            self.updated_at = datetime.datetime.utcnow()
            self.version += 1
            return True
        return False
