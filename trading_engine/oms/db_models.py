import datetime
from typing import Optional # Added for type hinting
from sqlalchemy import Column, String, Integer, Float, DateTime, Enum as DBEnum, Index
from sqlalchemy.ext.declarative import declarative_base

# Assuming models.py is in the same directory for Order, OrderStatus, OrderType
from .models import Order, OrderStatus, OrderType
from .position_models import Position # Import Position domain model

Base = declarative_base()

class OrderDB(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    order_type = Column(DBEnum(OrderType), nullable=False)
    limit_price = Column(Float, nullable=True) # For LIMIT orders
    stop_price = Column(Float, nullable=True) # New field for STOP and STOP_LIMIT
    trailing_percent = Column(Float, nullable=True) # New field for TRAIL
    trailing_amount = Column(Float, nullable=True) # New field for TRAIL
    trail_stop_price = Column(Float, nullable=True) # New field for TRAIL initial stop price

    status = Column(DBEnum(OrderStatus), nullable=False, index=True, default=OrderStatus.NEW) # Default changed to NEW

    broker_order_id = Column(String, nullable=True, index=True)
    perm_id = Column(Integer, nullable=True, index=True) # IBKR specific permanent ID

    filled_quantity = Column(Float, default=0.0)
    average_fill_price = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    version = Column(Integer, nullable=False, default=1) # For optimistic locking

    # Example of a composite index if needed, e.g. for querying user's orders by status
    # __table_args__ = (Index('ix_user_orders_status', "user_id", "status"), )

    def __repr__(self):
        return (f"<OrderDB(order_id='{self.order_id}', user_id='{self.user_id}', symbol='{self.symbol}', "
                f"quantity={self.quantity}, type='{self.order_type.value}', status='{self.status.value}', "
                f"broker_order_id='{self.broker_order_id}', version={self.version})>")

    def to_domain_model(self) -> Order:
        """Converts this SQLAlchemy model instance to a domain model instance."""
        return Order(
            order_id=self.order_id,
            user_id=self.user_id,
            symbol=self.symbol,
            quantity=self.quantity,
            order_type=self.order_type, # SQLAlchemy Enum directly maps to Python Enum here
            price=self.limit_price, # Domain model 'price' is used as 'limit_price'
            status=self.status,
            broker_order_id=self.broker_order_id,
            perm_id=self.perm_id,
            filled_quantity=self.filled_quantity,
            average_fill_price=self.average_fill_price,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            # New fields for domain model
            stop_price=self.stop_price,
            trailing_percent=self.trailing_percent,
            trailing_amount=self.trailing_amount,
            trail_stop_price=self.trail_stop_price
        )

    @classmethod
    def from_domain_model(cls, domain_order: Order) -> 'OrderDB':
        """Converts a domain model instance to a SQLAlchemy model instance."""
        return cls(
            order_id=domain_order.order_id,
            user_id=domain_order.user_id,
            symbol=domain_order.symbol,
            quantity=domain_order.quantity,
            order_type=domain_order.order_type,
            limit_price=domain_order.price,
            status=domain_order.status,
            broker_order_id=domain_order.broker_order_id,
            perm_id=domain_order.perm_id,
            filled_quantity=domain_order.filled_quantity,
            average_fill_price=domain_order.average_fill_price,
            created_at=domain_order.created_at,
            updated_at=domain_order.updated_at,
            version=domain_order.version,
            # New fields from domain model
            stop_price=domain_order.stop_price,
            trailing_percent=domain_order.trailing_percent,
            trailing_amount=domain_order.trailing_amount,
            trail_stop_price=domain_order.trail_stop_price
        )

# Example of how to add indexes after class definition if preferred
# Index('ix_user_id_status', OrderDB.user_id, OrderDB.status)
# Index('ix_broker_order_id', OrderDB.broker_order_id)
# Index('ix_perm_id', OrderDB.perm_id)
# These are already added via index=True in Column definitions for single-column indexes.
# Use __table_args__ for composite indexes.


class PositionDB(Base):
    __tablename__ = "positions"
    position_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    sec_type = Column(String, nullable=False, default="STK")
    exchange = Column(String, nullable=False, default="SMART")
    currency = Column(String, nullable=False, default="USD")
    con_id = Column(Integer, nullable=True, index=True) # IBKR Contract ID

    quantity = Column(Float, nullable=False, default=0.0)
    average_entry_price = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)      # New P&L field
    unrealized_pnl = Column(Float, nullable=False, default=0.0)    # New P&L field
    total_commission_paid = Column(Float, nullable=False, default=0.0) # New commission field

    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    version = Column(Integer, nullable=False, default=1)

    # Optional: Composite unique constraint for a user's position in a specific instrument
    # from sqlalchemy import UniqueConstraint
    # __table_args__ = (UniqueConstraint('user_id', 'symbol', 'sec_type', 'exchange', 'currency', 'con_id', name='_user_instrument_uc'),)


    def __repr__(self):
        return (f"<PositionDB {self.position_id} ({self.user_id} - {self.symbol}: {self.quantity} @ "
                f"{self.average_entry_price})>")

    def to_domain_model(self) -> Position:
        return Position(
            position_id=self.position_id,
            user_id=self.user_id,
            symbol=self.symbol,
            sec_type=self.sec_type,
            exchange=self.exchange,
            currency=self.currency,
            con_id=self.con_id,
            quantity=self.quantity,
            average_entry_price=self.average_entry_price,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
            total_commission_paid=self.total_commission_paid
        )

    @classmethod
    def from_domain_model(cls, domain_position: Position) -> 'PositionDB':
        return cls(
            position_id=domain_position.position_id,
            user_id=domain_position.user_id,
            symbol=domain_position.symbol,
            sec_type=domain_position.sec_type,
            exchange=domain_position.exchange,
            currency=domain_position.currency,
            con_id=domain_position.con_id,
            quantity=domain_position.quantity,
            average_entry_price=domain_position.average_entry_price,
            created_at=domain_position.created_at,
            updated_at=domain_position.updated_at,
            version=domain_position.version,
            realized_pnl=domain_position.realized_pnl,
            unrealized_pnl=domain_position.unrealized_pnl,
            total_commission_paid=domain_position.total_commission_paid
        )
