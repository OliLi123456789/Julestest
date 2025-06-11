import logging
import datetime
from sqlalchemy.orm import Session
from typing import Optional, List

from .position_models import Position
from .position_repository import PositionRepository
# Assuming gen.python path is correctly added to PYTHONPATH or discoverable
from trading_engine.gen.python.broker_events.broker_events_pb2 import ExecutionReportEvent, BrokerInstrument

logger = logging.getLogger(__name__)

class PositionManager:
    def __init__(self, db_session: Session):
        self.session = db_session
        self.repository = PositionRepository(self.session)

    def update_position_from_fill(self, execution_event: ExecutionReportEvent, user_id: str):
        instrument: BrokerInstrument = execution_event.instrument

        # Ensure quantities and prices are floats for calculation
        fill_quantity = float(execution_event.filled_quantity)
        fill_price = float(execution_event.fill_price) # Price of this specific fill
        # Average price for the order so far, from execution report (usually provided by broker)
        order_avg_price = float(execution_event.average_price)
        # Cumulative filled quantity for the order so far
        order_cum_qty = float(execution_event.cumulative_quantity)

        side = execution_event.side.upper()

        if not instrument.symbol or not user_id:
            logger.error("Cannot update position: missing symbol or user_id in execution event.")
            return

        # Determine the change in quantity for the position based on this fill
        # Note: execution_event.filled_quantity is the quantity of *this specific fill*, not the order's total filled qty.
        quantity_change_for_this_fill = fill_quantity if side == "BOT" else -fill_quantity

        logger.info(
            f"Processing fill for position update: User={user_id}, Symbol={instrument.symbol}, "
            f"SecType={instrument.sec_type}, Exchange={instrument.exchange}, Currency={instrument.currency}, ConID={instrument.con_id}, "
            f"QuantityChangeForThisFill={quantity_change_for_this_fill}, FillPrice={fill_price}"
        )

        current_pos = self.repository.get_by_user_and_instrument(
            user_id=user_id,
            symbol=instrument.symbol,
            sec_type=instrument.sec_type,
            exchange=instrument.exchange, # Consider using a "primary_exchange" or routing exchange if different
            currency=instrument.currency,
            con_id=instrument.con_id if instrument.con_id != 0 else None
        )

        if current_pos:
            logger.debug(f"Found existing position for {user_id}/{instrument.symbol}: Qty={current_pos.quantity}, AvgPx={current_pos.average_entry_price}, RealizedPnL={current_pos.realized_pnl}, Commissions={current_pos.total_commission_paid}")

            old_qty = float(current_pos.quantity)
            old_avg_price = float(current_pos.average_entry_price)

            # P&L and Commission Calculation
            trade_pnl_component = 0.0
            commission_for_this_fill = float(execution_event.commission_data.commission) if execution_event.commission_data else 0.0

            is_closing_component = (old_qty > 0 and quantity_change_for_this_fill < 0) or \
                                 (old_qty < 0 and quantity_change_for_this_fill > 0)

            if is_closing_component:
                qty_closed_on_this_trade = min(abs(old_qty), abs(quantity_change_for_this_fill))
                if old_qty > 0: # Closing part of a long position
                    trade_pnl_component = (fill_price - old_avg_price) * qty_closed_on_this_trade
                else: # Closing part of a short position (old_qty < 0)
                    trade_pnl_component = (old_avg_price - fill_price) * qty_closed_on_this_trade

                current_pos.realized_pnl += (trade_pnl_component - commission_for_this_fill) # Net PnL for this closing portion
                logger.info(f"Realized P&L component from this trade ({instrument.symbol}): Gross {trade_pnl_component:.2f}, Commission {commission_for_this_fill:.2f}, Net {trade_pnl_component - commission_for_this_fill:.2f}. OrderID: {execution_event.broker_order_id}, ExecID: {execution_event.execution_id}")
            else: # Opening or increasing position, commission still applies
                current_pos.total_commission_paid += commission_for_this_fill

            # Update quantity and average price (logic from former Position.update_position)
            if old_qty == 0: # Opening a new position
                current_pos.average_entry_price = fill_price
                current_pos.quantity = quantity_change_for_this_fill
            elif (old_qty > 0 and quantity_change_for_this_fill > 0) or \
                 (old_qty < 0 and quantity_change_for_this_fill < 0): # Increasing position
                current_pos.average_entry_price = ((old_avg_price * abs(old_qty)) + (fill_price * abs(quantity_change_for_this_fill))) / abs(old_qty + quantity_change_for_this_fill)
                current_pos.quantity += quantity_change_for_this_fill
            elif abs(quantity_change_for_this_fill) >= abs(old_qty): # Closing out or flipping
                remaining_qty = old_qty + quantity_change_for_this_fill
                if remaining_qty == 0:
                    current_pos.average_entry_price = 0.0
                else: # Flipped
                    current_pos.average_entry_price = fill_price
                current_pos.quantity = remaining_qty
            else: # Reducing position
                current_pos.quantity += quantity_change_for_this_fill
                # Average entry price remains the same when reducing a position

            if abs(current_pos.quantity) < 1e-9: # Check for effective zero quantity due to float precision
                current_pos.quantity = 0.0
                current_pos.average_entry_price = 0.0 # Reset avg price if position is closed

            current_pos.updated_at = datetime.datetime.utcnow()
            current_pos.version += 1

            self.repository.save(current_pos)
            logger.info(f"Position for {user_id}/{instrument.symbol} updated: Qty={current_pos.quantity:.4f}, AvgPx={current_pos.average_entry_price:.5f}, RealizedPnL={current_pos.realized_pnl:.2f}, TotalComm={current_pos.total_commission_paid:.2f}")
        else:
            logger.debug(f"No existing position for {user_id}/{instrument.symbol}. Creating new.")
            commission_for_this_fill = float(execution_event.commission_data.commission) if execution_event.commission_data else 0.0
            new_pos = Position(
                user_id=user_id,
                symbol=instrument.symbol,
                sec_type=instrument.sec_type,
                exchange=instrument.exchange,
                currency=instrument.currency,
                con_id=instrument.con_id if instrument.con_id != 0 else None,
                quantity=quantity_change_for_this_fill,
                average_entry_price=fill_price,
                realized_pnl=0.0, # No realized PnL on opening trade
                unrealized_pnl=0.0,
                total_commission_paid=commission_for_this_fill
            )
            self.repository.add(new_pos)
            logger.info(f"New position created for {user_id}/{instrument.symbol}: Qty={new_pos.quantity:.4f}, AvgPx={new_pos.average_entry_price:.5f}, TotalComm={new_pos.total_commission_paid:.2f}")


    def get_position(self, user_id: str, symbol: str, sec_type: str, exchange: str, currency: str, con_id: Optional[int]) -> Optional[Position]:
        return self.repository.get_by_user_and_instrument(user_id, symbol, sec_type, exchange, currency, con_id)

    def get_all_user_positions(self, user_id: str) -> List[Position]:
        return self.repository.list_by_user(user_id)

    def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """ Gets a position by its unique position_id. """
        return self.repository.get_by_id(position_id)

    def update_unrealized_pnl_for_position(self, position_id: str, current_market_price: float) -> bool:
        """
        Updates the unrealized P&L for a single position.
        This method is synchronous and expects the caller (e.g., a portfolio monitoring service)
        to handle database session and commit.
        """
        if current_market_price <= 0:
            logger.warning(f"Invalid current_market_price ({current_market_price}) for position {position_id}. Cannot update UPL.")
            return False

        position = self.repository.get_by_id(position_id)

        if not position:
            logger.warning(f"Position {position_id} not found. Cannot update UPL.")
            return False

        new_upl = 0.0
        if position.quantity != 0: # Ensure quantity is not zero before calculation
            new_upl = (current_market_price - position.average_entry_price) * position.quantity

        # Use the domain model's method to set UPL, which handles version and updated_at
        updated = position.set_unrealized_pnl(new_upl)

        if updated:
            try:
                # The repository's save method will handle add or update.
                # Since we fetched the position, it exists, so this will be an update.
                self.repository.save(position)
                # Caller is responsible for session.commit()
                logger.info(f"Unrealized P&L for position {position.position_id} ({position.symbol}) updated to: {position.unrealized_pnl:.2f} (MarketPx: {current_market_price})")
                return True
            except Exception as e:
                logger.error(f"Failed to save updated UPL for position {position.position_id}: {e}", exc_info=True)
                # Caller should handle session.rollback()
                return False
        else:
            logger.debug(f"Unrealized P&L for position {position.position_id} ({position.symbol}) unchanged (current: {position.unrealized_pnl:.2f}, new_calc: {new_upl:.2f}).")
            return False
