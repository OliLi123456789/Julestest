from typing import Optional, List
from sqlalchemy.orm import Session
from .db_models import PositionDB
from .position_models import Position # Domain model

class PositionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, position: Position):
        """
        Adds a new domain Position to the repository by converting it to PositionDB.
        The actual commit to the database should be handled by a Unit of Work or service layer.
        """
        db_position = PositionDB.from_domain_model(position)
        self.session.add(db_position)
        # self.session.flush() # Optional

    def get_by_id(self, position_id: str) -> Optional[Position]:
        """Retrieves a Position by its primary ID."""
        db_position = self.session.query(PositionDB).filter_by(position_id=position_id).first()
        return db_position.to_domain_model() if db_position else None

    def get_by_user_and_instrument(self,
                                   user_id: str,
                                   symbol: str,
                                   sec_type: str = "STK",
                                   exchange: str = "SMART",
                                   currency: str = "USD",
                                   con_id: Optional[int] = None) -> Optional[Position]:
        """
        Retrieves a Position based on user and unique instrument identifiers.
        ConID is prioritized if available. Otherwise, combination of symbol, sec_type, exchange, currency.
        Note: For options/futures, other fields like lastTradeDateOrContractMonth, strike, right might be needed
        for true uniqueness if con_id is not available. This method is simplified for now.
        """
        query = self.session.query(PositionDB).filter_by(user_id=user_id)

        if con_id is not None and con_id != 0: # IBKR often uses 0 for unassigned conId
            query = query.filter_by(con_id=con_id)
        else:
            # Fallback to other instrument details if con_id is not definitive
            query = query.filter_by(
                symbol=symbol,
                sec_type=sec_type,
                exchange=exchange,
                currency=currency
            )
            # Add more specific fields for derivatives if con_id is None, e.g.:
            # if sec_type in ["OPT", "FOP"]:
            #    query = query.filter_by(last_trade_date_or_contract_month=contract.lastTradeDateOrContractMonth, ...)
            # This requires these fields on PositionDB and Position models.

        db_position = query.first()
        return db_position.to_domain_model() if db_position else None

    def update(self, position: Position):
        """
        Updates an existing Position in the repository.
        Fetches the PositionDB instance by position_id and updates its attributes.
        """
        db_position = self.session.query(PositionDB).filter_by(position_id=position.position_id).first()
        if db_position:
            # Update attributes from the domain model
            db_position.quantity = position.quantity
            db_position.average_entry_price = position.average_entry_price
            db_position.sec_type = position.sec_type # In case it can change, though unlikely for a position
            db_position.exchange = position.exchange
            db_position.currency = position.currency
            db_position.con_id = position.con_id
            db_position.updated_at = position.updated_at
            db_position.version = position.version
            # Update new P&L fields
            db_position.realized_pnl = position.realized_pnl
            db_position.unrealized_pnl = position.unrealized_pnl
            db_position.total_commission_paid = position.total_commission_paid
            # self.session.flush() # Optional
        else:
            # Or raise an exception if position not found
            logger.warning(f"Position with ID {position.position_id} not found for update.")


    def list_by_user(self, user_id: str) -> List[Position]:
        """Lists all positions for a given user."""
        db_positions = self.session.query(PositionDB).filter_by(user_id=user_id).all()
        return [p.to_domain_model() for p in db_positions]

    def save(self, position: Position):
        """
        Convenience method to add a new position or update an existing one.
        Checks if a position with the same position_id exists.
        If specific instrument uniqueness is required (user_id, symbol, con_id etc.),
        it's better to use get_by_user_and_instrument then decide to add or update.
        This 'save' assumes position_id is the primary key for identifying existing record.
        """
        # Ensure logger is defined if used, e.g. import logging; logger = logging.getLogger(__name__) at top
        existing_db_pos = self.session.query(PositionDB).filter_by(position_id=position.position_id).first()
        if existing_db_pos:
            # Update existing
            existing_db_pos.quantity = position.quantity
            existing_db_pos.average_entry_price = position.average_entry_price
            existing_db_pos.updated_at = position.updated_at
            existing_db_pos.version = position.version
            # Ensure all relevant fields are updated from domain model
            existing_db_pos.user_id = position.user_id # Should not change if position_id is PK
            existing_db_pos.symbol = position.symbol
            existing_db_pos.sec_type = position.sec_type
            existing_db_pos.exchange = position.exchange
            existing_db_pos.currency = position.currency
            existing_db_pos.con_id = position.con_id
            # Update new P&L fields
            existing_db_pos.realized_pnl = position.realized_pnl
            existing_db_pos.unrealized_pnl = position.unrealized_pnl
            existing_db_pos.total_commission_paid = position.total_commission_paid
            # self.session.flush()
        else:
            # Add new
            db_position = PositionDB.from_domain_model(position)
            self.session.add(db_position)
            # self.session.flush()

# Example of logger setup if needed within this file (though usually configured globally)
import logging
logger = logging.getLogger(__name__)
