# webapp/backend/data_cache_service.py
import logging
from typing import Dict, List, Optional, Any
from threading import RLock # For thread-safe access to in-memory cache
from pydantic import BaseModel # Use Pydantic for PositionData as well

# Define a simple Position model for the cache.
# This will be used for responses in the new /portfolio/positions endpoint.
class PositionData(BaseModel):
    user_id: str
    symbol: str
    quantity: float
    average_price: float
    sec_type: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    con_id: Optional[int] = None # IBKR specific contract ID
    last_market_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    market_value: Optional[float] = None
    realized_pnl_from_event: Optional[float] = None # For any PNL reported directly by an event

logger = logging.getLogger(__name__)

class DataCacheService:
    def __init__(self):
        # Using Pydantic models from main.py for API responses
        # This import might need to be adjusted if models are moved.
        from .main import OrderResponse, PortfolioSummaryResponse # Import new model
        self.OrderResponseModel = OrderResponse
        self.PortfolioSummaryResponseModel = PortfolioSummaryResponse # Store for use

        # In-memory cache: {user_id: {order_id: OrderResponse_dict/Pydantic_model_dict}}
        self._orders_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # In-memory cache: {user_id: {symbol_key: PositionData_dict/Pydantic_model_dict}}
        self._positions_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # In-memory cache for account summary values: {user_id: {key: value}}
        self._account_summary_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock() # Thread-safe for concurrent updates/reads
        logger.info("DataCacheService initialized with in-memory stores for orders, positions, and account summary.")

    # --- Account Summary Cache Methods ---
    def update_account_summary_from_event(self, account_event_data: Dict[str, Any]):
        # Expects account_id, key, value, currency from event_dict
        user_id = account_event_data.get("account_id") or account_event_data.get("user_id") # Ensure user_id mapping
        key = account_event_data.get("key") or account_event_data.get("tag") # IBKR uses 'key' or 'tag'
        value = account_event_data.get("value")
        currency = account_event_data.get("currency", "USD").upper() # Default to USD if not specified

        if not user_id or not key or value is None:
            logger.warning(f"Account summary update skipped: missing user_id, key, or value. Event: {account_event_data}")
            return

        # For now, only process USD values or assume values are already in base currency USD
        if currency != "USD" and key not in ["AccountType", "AccountOrGroup"]: # Some keys are non-monetary
             # TODO: Implement currency conversion if values can be non-USD and need to be summed up
             logger.debug(f"Skipping non-USD account summary update for {key} in {currency}. Value: {value}")
             # return # Or store them if frontend can handle multiple currencies

        with self._lock:
            from datetime import datetime # Local import for timestamp
            user_summary = self._account_summary_cache.setdefault(user_id, {})

            try:
                # Attempt to convert value to float if it's a monetary value
                # Common keys that are not float: AccountType, AccountOrGroup, various flags
                if key not in ["AccountType", "AccountOrGroup", "TradingClass", "Category"] and isinstance(value, (str, int, float)):
                     processed_value = float(value)
                else:
                     processed_value = value # Keep as string or original type
            except ValueError:
                logger.warning(f"Could not convert account summary value to float for key {key}: {value}. Storing as is.")
                processed_value = value

            user_summary[key] = processed_value
            user_summary["last_update_utc"] = datetime.utcnow() # Timestamp the update for this user
            logger.info(f"Account summary cache updated for user {user_id}, key {key}: {processed_value} ({currency})")


    # --- Order Cache Methods ---
    def update_order_from_event(self, order_event_data: Dict[str, Any]):
        user_id = order_event_data.get("user_id")
        # platform_order_id is from NewOrderRequest, order_id is often from broker events
        order_id = order_event_data.get("platform_order_id") or order_event_data.get("order_id")

        if not user_id or not order_id:
            logger.warning(f"Order cache update skipped: missing user_id or order_id. Event: {order_event_data}")
            return

        with self._lock:
            user_orders = self._orders_cache.setdefault(user_id, {})
            existing_order_dict = user_orders.get(order_id, {})

            # Merge event data into existing order data
            existing_order_dict.update(order_event_data)

            # Ensure core fields are present and correctly typed for OrderResponse model
            # This is important if events provide partial data or different field names
            final_order_data = {
                'order_id': str(order_id),
                'user_id': str(user_id),
                'symbol': str(existing_order_dict.get('symbol', 'UNKNOWN')).upper(),
                'quantity': int(existing_order_dict.get('quantity', 0)),
                'order_type': str(existing_order_dict.get('order_type', 'UNKNOWN')).upper(),
                'price': float(existing_order_dict.get('price')) if existing_order_dict.get('price') is not None else None,
                'status': str(existing_order_dict.get('status', 'UNKNOWN')).upper(),
                # Add any other fields from OrderResponse that might be in the event
                'limit_price': float(existing_order_dict.get('limit_price')) if existing_order_dict.get('limit_price') is not None else None,
                'filled_quantity': float(existing_order_dict.get('filled_quantity', 0.0)),
                'average_fill_price': float(existing_order_dict.get('average_fill_price', 0.0)),
                'last_fill_price': float(existing_order_dict.get('last_fill_price', 0.0)),
                'commission': float(existing_order_dict.get('commission', 0.0)),
                'remaining_quantity': float(existing_order_dict.get('remaining_quantity', existing_order_dict.get('quantity', 0))),
                'broker_order_id': str(existing_order_dict.get('broker_order_id','N/A')) if existing_order_dict.get('broker_order_id') else None,
                'reason': str(existing_order_dict.get('reason','')) if existing_order_dict.get('reason') else None,
                'timestamp_utc': str(existing_order_dict.get('timestamp_utc', '')) # Assuming it's a string representation
            }
            # Filter out None values if OrderResponse model doesn't want them for Optional fields
            # final_order_data_cleaned = {k: v for k, v in final_order_data.items() if v is not None}

            user_orders[order_id] = final_order_data # Store as dict
            logger.info(f"Order cache updated: User {user_id}, Order {order_id}, Status {final_order_data.get('status')}")

    def get_order_by_id(self, user_id: str, order_id: str) -> Optional[Any]: # Returns Pydantic Model
        with self._lock:
            user_orders = self._orders_cache.get(user_id, {})
            order_data_dict = user_orders.get(order_id)
            if order_data_dict:
                # Re-validate with Pydantic model to ensure structure and types
                try:
                    return self.OrderResponseModel(**order_data_dict)
                except Exception as e: # Handle Pydantic validation error or other issues
                    logger.error(f"Error converting cached dict to OrderResponseModel for order {order_id}: {e}. Data: {order_data_dict}")
                    return None # Or raise error, or return dict
            return None

    def get_orders_by_user(self, user_id: str) -> List[Any]: # Returns List[Pydantic Model]
        with self._lock:
            user_orders_dict = self._orders_cache.get(user_id, {})
            valid_orders = []
            for order_id, data_dict in user_orders_dict.items():
                try:
                    valid_orders.append(self.OrderResponseModel(**data_dict))
                except Exception as e:
                    logger.error(f"Error converting cached dict to OrderResponseModel for order {order_id} (user {user_id}): {e}. Data: {data_dict}")
            return valid_orders

    # --- Position Cache Methods ---
    def update_position_from_event(self, position_event_data: Dict[str, Any]):
        # PortfolioUpdateEvent from IBKR gateway uses 'ib_account_id'
        user_id = position_event_data.get("ib_account_id") or position_event_data.get("user_id")
        instrument_data = position_event_data.get("instrument", {})
        symbol = instrument_data.get("symbol")

        if not user_id or not symbol:
            logger.warning(f"Position cache update skipped: missing user_id/ib_account_id or symbol. Event: {position_event_data}")
            return

        position_key = symbol # Using symbol as key for simplicity

        with self._lock:
            user_positions = self._positions_cache.setdefault(user_id, {})

            # Create or update position data (store as dict for Pydantic model creation on read)
            pos_data_dict = {
                'user_id': user_id,
                'symbol': symbol,
                'quantity': float(position_event_data.get("position", 0.0)),
                'average_price': float(position_event_data.get("average_cost", 0.0)),
                'sec_type': instrument_data.get("sec_type"),
                'exchange': instrument_data.get("exchange"),
                'currency': instrument_data.get("currency"),
                'con_id': instrument_data.get("con_id"),
                'last_market_price': float(position_event_data.get("market_price", 0.0)),
                'unrealized_pnl': float(position_event_data.get("unrealized_pnl", 0.0)),
                'market_value': float(position_event_data.get("market_value", 0.0)),
                'realized_pnl_from_event': float(position_event_data.get("realized_pnl", 0.0))
            }
            user_positions[position_key] = pos_data_dict
            logger.info(f"Position cache updated: User {user_id}, Symbol {symbol}, Qty={pos_data_dict['quantity']}")

    def get_position(self, user_id: str, symbol: str) -> Optional[PositionData]:
        with self._lock:
            user_positions = self._positions_cache.get(user_id, {})
            pos_dict = user_positions.get(symbol)
            if pos_dict:
                try:
                    return PositionData(**pos_dict)
                except Exception as e:
                    logger.error(f"Error converting cached dict to PositionData for symbol {symbol}: {e}. Data: {pos_dict}")
                    return None # Or raise
            return None

    def get_all_positions_by_user(self, user_id: str) -> List[PositionData]:
        with self._lock:
            user_positions_dict = self._positions_cache.get(user_id, {})
            valid_positions = []
            for symbol_key, data_dict in user_positions_dict.items():
                try:
                    valid_positions.append(PositionData(**data_dict))
                except Exception as e:
                    logger.error(f"Error converting cached dict to PositionData for key {symbol_key} (user {user_id}): {e}. Data: {data_dict}")
            return valid_positions

    # --- Portfolio Summary Method ---
    def get_portfolio_summary(self, user_id: str) -> Any: # Returns PortfolioSummaryResponse Pydantic model
        from datetime import datetime # Local import for timestamp

        with self._lock:
            user_account_summary = self._account_summary_cache.get(user_id, {})
            user_positions_list = self.get_all_positions_by_user(user_id=user_id) # This returns List[PositionData]

            total_positions_value = 0.0
            total_realized_pnl_on_positions = 0.0 # Sum of RPNL from cached PositionData items
            total_unrealized_pnl = 0.0

            for pos_model in user_positions_list: # pos_model is PositionData instance
                market_value = pos_model.market_value
                if market_value is None: # Fallback calculation if market_value not directly in PositionData
                    market_value = (pos_model.quantity or 0.0) * (pos_model.last_market_price or 0.0)

                total_positions_value += market_value
                total_realized_pnl_on_positions += pos_model.realized_pnl_from_event or 0.0
                total_unrealized_pnl += pos_model.unrealized_pnl or 0.0

            # Get overall portfolio values from account summary cache
            # These keys should match what IBKR gateway sends (e.g., NetLiquidation, TotalCashValue, BuyingPower)
            net_liquidation = float(user_account_summary.get("NetLiquidation", 0.0))
            total_cash = float(user_account_summary.get("TotalCashValue", 0.0)) # Or "AvailableFunds" / "CashBalance"
            buying_power = float(user_account_summary.get("BuyingPower", 0.0))

            # If NetLiquidation is missing, estimate (broker value is preferred)
            if net_liquidation == 0.0 and total_cash != 0.0: # Basic check
                 # Corrected simple estimation: NetLiq = Cash + MarketValueOfPositions
                 net_liquidation = total_cash + total_positions_value
                 # Note: Unrealized PNL is part of Market Value of positions if Market Value is (Entry Cost + UPL).
                 # Or, if Market Value is just (Qty * MktPrice), then NetLiq = Cash + MktValOfPositions.
                 # IBKR's NetLiquidation = Total cash value + Stock value + Option value + Futures P&L etc.

            # Total Realized PNL for the account (day) might be a separate key from account summary,
            # e.g., "RealizedPnL". The `total_realized_pnl_on_positions` is sum from individual position events.
            # For simplicity, we use sum from positions if no direct account summary field is available.
            account_realized_pnl = float(user_account_summary.get("RealizedPnL", total_realized_pnl_on_positions))

            summary_data = {
                "user_id": user_id,
                "total_portfolio_value_usd": net_liquidation,
                "total_positions_value_usd": total_positions_value,
                "total_cash_balance_usd": total_cash,
                "buying_power_usd": buying_power,
                "total_realized_pnl_usd": account_realized_pnl,
                "total_unrealized_pnl_usd": total_unrealized_pnl, # This is sum of UPNL from positions
                "timestamp_utc": user_account_summary.get("last_update_utc", datetime.utcnow())
            }
            try:
                return self.PortfolioSummaryResponseModel(**summary_data)
            except Exception as e:
                logger.error(f"Error creating PortfolioSummaryResponse for user {user_id}: {e}. Data: {summary_data}")
                # Fallback or raise error
                # Create a default response with error indication or re-raise
                return self.PortfolioSummaryResponseModel(
                    user_id=user_id, total_portfolio_value_usd=0,total_positions_value_usd=0,
                    total_cash_balance_usd=0, buying_power_usd=0, total_realized_pnl_usd=0,
                    total_unrealized_pnl_usd=0, timestamp_utc=datetime.utcnow()
                )
