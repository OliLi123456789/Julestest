from typing import Optional, List
from sqlalchemy.orm import Session

from .db_models import OrderDB
from .models import Order, OrderStatus # Assuming OrderStatus might be used for updates or queries

class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, order: Order):
        """
        Adds a new domain Order to the repository by converting it to OrderDB.
        The actual commit to the database should be handled by a Unit of Work or service layer.
        """
        db_order = OrderDB.from_domain_model(order)
        self.session.add(db_order)
        # self.session.flush() # Optional: if you need order_id or other DB-generated values immediately

    def get_by_id(self, order_id: str) -> Optional[Order]:
        """Retrieves an Order by its ID."""
        db_order = self.session.query(OrderDB).filter_by(order_id=order_id).first()
        if db_order:
            return db_order.to_domain_model()
        return None

    def update(self, order: Order):
        """
        Updates an existing Order in the repository.
        Fetches the OrderDB instance and updates its attributes from the domain Order.
        Proper optimistic locking should check the version before updating.
        The actual commit to the database should be handled by a Unit of Work or service layer.
        """
        db_order = self.session.query(OrderDB).filter_by(order_id=order.order_id).first()
        if db_order:
            # Basic optimistic lock check (can be made more robust by Session and DB exceptions)
            if db_order.version != order.version -1 and order.version > 1 : # Check if version is as expected before update
                 # (order.version would have been incremented by domain logic before calling update)
                 # So, db_order.version should be order.version - 1.
                 # If order.version is 1, it's a new order being added, not updated via this method.
                 # This check is simplified; real optimistic locking is more involved.
                 # A more robust approach is to use SQLAlchemy's versioning features or catch StaleDataError.
                 # For now, this is a conceptual placeholder.
                 # raise StaleDataError(f"Order {order.order_id} has been modified by another transaction.")
                 pass # Placeholder for proper optimistic lock handling

            # Update attributes
            db_order.user_id = order.user_id # Should not change typically, but included for completeness
            db_order.symbol = order.symbol # Should not change typically
            db_order.quantity = order.quantity # Should not change typically
            db_order.order_type = order.order_type # Should not change typically
            db_order.limit_price = order.price # Should not change typically

            db_order.status = order.status
            db_order.broker_order_id = order.broker_order_id
            db_order.perm_id = order.perm_id
            db_order.filled_quantity = order.filled_quantity
            db_order.average_fill_price = order.average_fill_price
            db_order.updated_at = order.updated_at # Domain model should have updated this
            db_order.version = order.version # Domain model should have incremented this

            # self.session.flush() # Optional: to apply changes to session before commit (if needed by caller)
        else:
            # Handle case where order to update is not found, e.g., raise an exception
            # raise OrderNotFoundException(f"Order with ID {order.order_id} not found for update.")
            pass # For now, do nothing if not found; service layer should handle.


    def list_all(self) -> List[Order]:
        """Lists all orders. For real applications, pagination should be implemented."""
        db_orders = self.session.query(OrderDB).all()
        return [db_order.to_domain_model() for db_order in db_orders]

    # Potential future methods:
    # def list_by_user_id(self, user_id: str) -> List[Order]: ...
    # def list_by_status(self, status: OrderStatus) -> List[Order]: ...
    # def get_by_broker_order_id(self, broker_order_id: str) -> Optional[Order]: ...
