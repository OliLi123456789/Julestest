import logging
import logging
import datetime # For risk event timestamp
from typing import Dict, Any, List, Optional
from trading_engine.oms.models import Order, OrderType, OrderStatus
from trading_engine.oms.position_models import Position
from .risk_rules import AccountInfo, RiskRuleViolation # DEFAULT_RISK_CONFIG removed from here
from .risk_config_loader import load_risk_config_from_file # New import
from .external_data_providers import MockMarketDataClient, MockAccountInfoProvider, MockRiskEventPublisher # New import

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self,
                 config_file_path: str = "risk_config.json",
                 market_data_client: Optional[Any] = None,
                 account_info_provider: Optional[Any] = None,
                 risk_event_publisher: Optional[Any] = None):
        self.config = load_risk_config_from_file(config_file_path)

        # Use provided clients/providers or default to mocks
        self.market_data_client = market_data_client if market_data_client else MockMarketDataClient()
        self.account_info_provider = account_info_provider if account_info_provider else MockAccountInfoProvider()
        self.risk_event_publisher = risk_event_publisher if risk_event_publisher else MockRiskEventPublisher()

        logger.info(f"RiskManager initialized. Config loaded from '{config_file_path}'. Using provided or mock data providers/publishers.")

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Gets the current market price for a symbol.
        Uses the injected market_data_client if available, otherwise falls back to mocks.
        """
        if self.market_data_client and hasattr(self.market_data_client, 'get_last_trade_price'):
            price = self.market_data_client.get_last_trade_price(symbol)
            if price is not None:
                logger.debug(f"RiskManager: Fetched real price for {symbol} via MarketDataClient: {price}")
                return price
            else:
                logger.warning(f"RiskManager: MarketDataClient returned None for {symbol}. Falling back to internal mock for this call.")

        # Fallback to internal mock prices if client fails or not provided with the right method
        mock_prices = {"AAPL": 150.0, "GOOG": 2500.0, "MSFT": 300.0, "TSLA": 700.0,
                       "EUR.USD": 1.1, "BTC.USD": 40000.0, "TESTSYM": 90.0, "SOME_ILLIQUID_SYM": 5.0 }
        price = mock_prices.get(symbol, 100.0)
        logger.debug(f"RiskManager: Using internal mock price for {symbol}: {price}")
        return price

    def check_pre_trade_rules(self, order: Order,
                              current_positions: List[Position],
                              account_info: AccountInfo) -> bool: # account_info is passed in by OMS
        """
        Checks pre-trade risk rules for a given order.
        Updates order status to REJECTED or ERROR if a rule is violated or an error occurs.
        Returns True if all checks pass, False otherwise.
        """
        try:
            # Basic order sanity checks
            if order.quantity == 0:
                raise RiskRuleViolation("Order quantity cannot be zero.")
            # Ensure quantity sign matches intent if that's a system rule (e.g. BUY must be >0)
            # For now, assuming quantity is signed correctly by the strategy/caller.

            if order.order_type == OrderType.LIMIT:
                if order.price is None or order.price <= 0:
                    raise RiskRuleViolation("Limit price required and must be positive for LIMIT order.")
            elif order.order_type == OrderType.STOP:
                if order.stop_price is None or order.stop_price <= 0:
                    raise RiskRuleViolation("Stop price required and must be positive for STOP order.")
                if order.price is not None: # order.price is limit_price for domain model
                     raise RiskRuleViolation("Limit price (order.price) should not be set for STOP (market) order.")
            elif order.order_type == OrderType.STOP_LIMIT:
                if order.stop_price is None or order.stop_price <= 0:
                    raise RiskRuleViolation("Stop price required and must be positive for STOP_LIMIT order.")
                if order.price is None or order.price <= 0: # order.price is limit_price
                    raise RiskRuleViolation("Limit price (order.price) required and must be positive for STOP_LIMIT order.")
            elif order.order_type == OrderType.TRAIL:
                if order.trailing_percent is None and order.trailing_amount is None:
                    raise RiskRuleViolation("Either trailing_percent or trailing_amount must be specified for TRAIL order.")
                if order.trailing_percent is not None and order.trailing_amount is not None:
                    raise RiskRuleViolation("Specify either trailing_percent or trailing_amount for TRAIL order, not both.")
                if order.trailing_percent is not None and (order.trailing_percent <= 0 or order.trailing_percent >= 100):
                    raise RiskRuleViolation("Trailing percent must be positive and typically less than 100 for TRAIL order.")
                if order.trailing_amount is not None and order.trailing_amount <= 0:
                    raise RiskRuleViolation("Trailing amount must be positive for TRAIL order.")
                if order.price is not None: # order.price is limit_price
                    raise RiskRuleViolation("Limit price (order.price) should not be set for TRAIL (market) order.")
                if order.stop_price is not None:
                    raise RiskRuleViolation("Stop price should not be set for TRAIL order; use trail_stop_price for initial trigger if needed.")
                if order.trail_stop_price is not None and order.trail_stop_price <= 0:
                    raise RiskRuleViolation("Initial trail_stop_price, if specified, must be positive for TRAIL order.")

            # Symbol restrictions
            allowed_symbols = self.config.get("allowed_symbols")
            if allowed_symbols and order.symbol not in allowed_symbols:
                raise RiskRuleViolation(f"Symbol {order.symbol} is not allowed for trading.")

            # Max order quantity per symbol
            max_qty_config = self.config.get("max_order_quantity_per_symbol", {})
            max_qty = max_qty_config.get(order.symbol, max_qty_config.get("DEFAULT", float('inf')))
            if abs(order.quantity) > max_qty:
                raise RiskRuleViolation(f"Order quantity {abs(order.quantity)} for {order.symbol} exceeds maximum of {max_qty}.")

            # Market order restrictions for illiquid symbols
            if order.order_type == OrderType.MARKET and \
               order.symbol in self.config.get("block_market_orders_for_illiquid", []):
                raise RiskRuleViolation(f"Market orders for potentially illiquid symbol {order.symbol} are blocked.")

            # Value-based checks (requires current price)
            current_price = self._get_current_price(order.symbol)
            if current_price is None or current_price <= 0: # Price must be positive for value calculation
                raise RiskRuleViolation(f"Cannot get a valid current price for {order.symbol} to check order/position value.")

            estimated_order_value = abs(order.quantity) * current_price
            max_order_value = self.config.get("max_order_value_usd", float('inf'))
            if estimated_order_value > max_order_value:
                raise RiskRuleViolation(f"Estimated order value {estimated_order_value:.2f} USD for {order.symbol} exceeds maximum of {max_order_value:.2f} USD.")

            # Position value checks
            max_pos_value_config = self.config.get("max_position_value_usd_per_symbol", {})
            max_pos_value = max_pos_value_config.get(order.symbol, max_pos_value_config.get("DEFAULT", float('inf')))

            current_pos_qty = 0.0
            for pos in current_positions: # Assumes current_positions is for the same user_id and matching instrument details
                if (pos.symbol == order.symbol and
                    pos.sec_type == order.sec_type and # Assuming Order domain model has sec_type, etc. or these are passed
                    pos.currency == order.currency): # Need to ensure Order has these or they are passed
                    # TODO: Enhance Position and Order domain models to carry all necessary instrument fields for matching
                    current_pos_qty = pos.quantity
                    break

            # order.quantity is signed (+ for buy, - for sell)
            potential_pos_qty = current_pos_qty + order.quantity
            potential_pos_value = abs(potential_pos_qty) * current_price
            if potential_pos_value > max_pos_value:
                raise RiskRuleViolation(f"Potential position value {potential_pos_value:.2f} USD for {order.symbol} (qty: {potential_pos_qty}) exceeds maximum of {max_pos_value:.2f} USD.")

            # Buying power / Margin check (simplified)
            # For BUY orders (positive quantity) or SELL short orders (negative quantity, new short)
            order_cost_commitment = 0.0
            is_buy_or_new_short = (order.quantity > 0) or (order.quantity < 0 and current_pos_qty >= 0 and potential_pos_qty < 0)

            if is_buy_or_new_short:
                ref_price_for_cost = current_price # Default for market-like orders
                if order.order_type == OrderType.LIMIT and order.price is not None:
                    ref_price_for_cost = order.price
                elif order.order_type == OrderType.STOP and order.stop_price is not None: # Stop market uses stop price as trigger
                    ref_price_for_cost = order.stop_price
                elif order.order_type == OrderType.STOP_LIMIT and order.price is not None: # Stop-Limit uses limit price for execution
                    ref_price_for_cost = order.price
                # TRAIL order cost is harder to estimate; often full potential value or based on trail_stop_price if available
                elif order.order_type == OrderType.TRAIL and order.trail_stop_price is not None:
                    ref_price_for_cost = order.trail_stop_price

                order_cost_commitment = abs(order.quantity) * ref_price_for_cost

            if order_cost_commitment > 0 and account_info.buying_power < order_cost_commitment:
                raise RiskRuleViolation(f"Insufficient buying power for order {order.order_id}. Estimated cost: {order_cost_commitment:.2f}, Buying Power: {account_info.buying_power:.2f}.")

            logger.info(f"Order {order.order_id} passed all pre-trade risk checks.")
            return True

        except RiskRuleViolation as rrv:
            logger.warning(f"Order {order.order_id} REJECTED by RiskManager: {rrv.message}")
            order.update_status(OrderStatus.REJECTED)
            # Consider adding rrv.message to a rejection_reason field in order
            if self.risk_event_publisher and hasattr(self.risk_event_publisher, 'publish_risk_violation'):
                try:
                    violation_event_data = {
                        "order_id": order.order_id, "user_id": order.user_id, "symbol": order.symbol,
                        "rule_violated": "RiskRuleViolation", # Could be more specific if rules were classes/enums
                        "message": rrv.message, "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    self.risk_event_publisher.publish_risk_violation(violation_event_data)
                    logger.info(f"Published risk violation event for order {order.order_id}: {rrv.message}")
                except Exception as pub_e:
                    logger.error(f"Failed to publish risk violation event for order {order.order_id}: {pub_e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"RiskManager: Unexpected error during pre-trade check for order {order.order_id}: {e}", exc_info=True)
            order.update_status(OrderStatus.ERROR)
            if self.risk_event_publisher and hasattr(self.risk_event_publisher, 'publish_risk_check_failed_event'):
                try:
                    error_event_data = {
                        "order_id": order.order_id, "user_id": order.user_id, "symbol": order.symbol,
                        "error_type": type(e).__name__,
                        "message": str(e), "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    self.risk_event_publisher.publish_risk_check_failed_event(error_event_data)
                    logger.info(f"Published generic risk check failure event for order {order.order_id}")
                except Exception as pub_e:
                    logger.error(f"Failed to publish generic risk check failure event for order {order.order_id}: {pub_e}", exc_info=True)
            return False
