import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
from backtester.strategy import SignalEvent, SignalType
from backtester.data import MarketDataEvent
import logging
import pandas as pd # Added for __main__ example and type hinting

logger = logging.getLogger(__name__)

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

class OrderEvent:
    def __init__(self, timestamp: datetime.datetime, symbol: str, order_type: OrderType,
                 quantity: int, direction: SignalType, limit_price: Optional[float] = None):
        self.type = 'ORDER'
        self.timestamp = timestamp
        self.symbol = symbol
        self.order_type = order_type
        self.quantity = quantity
        self.direction = direction
        self.limit_price = limit_price
        self.status = OrderStatus.PENDING

    def __str__(self):
        details = f"Order: {self.timestamp} {self.direction.value} {self.quantity} {self.symbol} Type: {self.order_type.value}"
        if self.order_type == OrderType.LIMIT and self.limit_price is not None:
            details += f" @Limit={self.limit_price:.2f}"
        details += f" Status: {self.status.value}"
        return details

class FillEvent:
    def __init__(self, timestamp: datetime.datetime, symbol: str, quantity: int, direction: SignalType,
                 fill_price: float, gross_value: float, commission: float = 0.0,
                 realized_pnl_for_this_fill: Optional[float] = None): # Added realized_pnl
        self.type = 'FILL'
        self.timestamp = timestamp
        self.symbol = symbol
        self.quantity = quantity
        self.direction = direction
        self.fill_price = fill_price
        self.gross_value = gross_value
        self.commission = commission
        self.realized_pnl_for_this_fill = realized_pnl_for_this_fill # Store it

        if direction == SignalType.BUY:
            self.cash_impact = -(self.gross_value + self.commission)
        else: # SELL
            self.cash_impact = self.gross_value - self.commission

    def __str__(self):
        pnl_str = f", RealizedPnl={self.realized_pnl_for_this_fill:.2f}" if self.realized_pnl_for_this_fill is not None else ""
        return (f"Fill: {self.timestamp} {self.direction.value} {self.quantity} {self.symbol} "
                f"@ {self.fill_price:.2f} (GrossVal:{self.gross_value:.2f}, Comm:{self.commission:.2f}, "
                f"CashImpact:{self.cash_impact:.2f}{pnl_str})")


class Portfolio:
    def __init__(self, initial_cash: float = 100000.0, data_handler=None,
                 slippage_model: str = "none",
                 slippage_fixed_amount: float = 0.01,
                 slippage_percentage: float = 0.0005,
                 commission_model: str = "fixed_per_trade",
                 commission_fixed_amount: float = 1.00,
                 commission_per_share: float = 0.005,
                 commission_percentage_value: float = 0.001,
                 commission_min_per_trade: float = 0.50
                ):
        self.initial_cash = initial_cash
        self.current_cash = initial_cash
        self.current_holdings: Dict[str, Dict] = {}
        self.all_positions_over_time: List[Dict] = []
        self.all_cash_over_time: List[float] = []
        self.portfolio_value_over_time: List[Dict] = []
        self.trades: List[FillEvent] = [] # This will store FillEvents including their P&L

        self.slippage_model = slippage_model.lower()
        self.slippage_fixed_amount = slippage_fixed_amount
        self.slippage_percentage = slippage_percentage

        self.commission_model = commission_model.lower()
        self.commission_fixed_amount = commission_fixed_amount
        self.commission_per_share = commission_per_share
        self.commission_percentage_value = commission_percentage_value
        self.commission_min_per_trade = commission_min_per_trade

        logger.info(f"Portfolio initialized. Initial Cash: {initial_cash:.2f}, Slippage: {self.slippage_model}, Commission: {self.commission_model}")

    def update_timeindex(self, current_timestamp: datetime.datetime, current_market_data: Dict[str, MarketDataEvent]):
        portfolio_value = self.current_cash
        for symbol, position in self.current_holdings.items():
            if position['quantity'] == 0: # Skip if no holding for this symbol
                continue

            market_event = current_market_data.get(symbol)
            market_price_for_mtm = None

            if market_event and market_event.get('CLOSE') is not None and pd.notna(market_event.get('CLOSE')):
                market_price_for_mtm = market_event.get('CLOSE')
            elif position['quantity'] != 0: # Fallback only if position exists and CLOSE is missing/NaN
                market_price_for_mtm = position['average_price']
                logger.warning(
                    f"Portfolio MTM for {symbol} at {current_timestamp}: CLOSE price missing or NaN. "
                    f"Falling back to average_price ({market_price_for_mtm:.2f}) for valuation. "
                    f"Quantity: {position['quantity']}."
                )

            if market_price_for_mtm is not None:
                portfolio_value += position['quantity'] * market_price_for_mtm
            elif position['quantity'] != 0: # Position exists but no valid price found (CLOSE or average_price)
                logger.error(
                    f"Portfolio MTM for {symbol} at {current_timestamp}: Cannot determine market value. "
                    f"No CLOSE price and average_price is {position['average_price']:.2f} (or invalid). Quantity: {position['quantity']}. "
                    f"This position's value will not be added to current MTM portfolio value."
                )
                # If you want to value at cost_basis in this extreme case:
                # portfolio_value += position['cost_basis']
                # However, not adding it is more conservative if price is truly unknown.

        self.portfolio_value_over_time.append({'timestamp': current_timestamp, 'value': portfolio_value})
        self.all_positions_over_time.append({'timestamp': current_timestamp, 'holdings': {k: v.copy() for k, v in self.current_holdings.items()}}) # Store a deep copy
        self.all_cash_over_time.append({'timestamp': current_timestamp, 'cash': self.current_cash})

    def get_current_position_details(self, symbol: str) -> Optional[Dict]:
        """Helper to get current details of a position."""
        if symbol in self.current_holdings and self.current_holdings[symbol]['quantity'] != 0:
            return self.current_holdings[symbol].copy() # Return a copy
        return None

    def process_signal(self, signal: SignalEvent) -> Optional[OrderEvent]:
        if signal.type != 'SIGNAL': return None

        if signal.signal_type == SignalType.SELL:
            current_quantity = self.current_holdings.get(signal.symbol, {}).get('quantity', 0)
            if current_quantity < signal.quantity:
                logger.warning(f"Portfolio: Cannot process SELL signal for {signal.quantity} {signal.symbol}. "
                               f"Not enough holdings. Have {current_quantity}, need {signal.quantity}")
                return None

        order_type_to_create = OrderType.MARKET
        order_limit_price = None
        if signal.price is not None and signal.price > 0:
            order_type_to_create = OrderType.LIMIT
            order_limit_price = signal.price

        order = OrderEvent(
            timestamp=signal.timestamp, symbol=signal.symbol, order_type=order_type_to_create,
            quantity=signal.quantity, direction=signal.signal_type, limit_price=order_limit_price
        )
        logger.info(f"Portfolio: Generated {order}")
        return order

    def process_fill(self, fill: FillEvent):
        if fill.type != 'FILL': return

        symbol = fill.symbol
        if symbol not in self.current_holdings: # Ensure entry exists for the symbol
            self.current_holdings[symbol] = {'quantity': 0, 'average_price': 0.0, 'cost_basis': 0.0}

        current_qty = self.current_holdings[symbol]['quantity']
        current_avg_price = self.current_holdings[symbol]['average_price'] # This is average acquisition cost
        current_cost_basis = self.current_holdings[symbol]['cost_basis']

        qty_being_closed = fill.quantity # For both BUY to cover and SELL to close long
        realized_pnl_for_this_fill = None

        if fill.direction == SignalType.SELL: # Selling a long position
            if current_qty > 0: # It's a closing or reducing trade
                # P&L = (Exit Price - Entry Avg Price) * Quantity Sold - Commission for this fill
                gross_pnl_component = (fill.fill_price - current_avg_price) * qty_being_closed
                realized_pnl_for_this_fill = gross_pnl_component - fill.commission
                logger.info(f"SELL Fill P&L for {fill.symbol}: Qty={qty_being_closed}, EntryAvgPx={current_avg_price:.2f}, "
                            f"ExitPx={fill.fill_price:.2f}, GrossPnlComp={gross_pnl_component:.2f}, Comm={fill.commission:.2f}, NetPnl={realized_pnl_for_this_fill:.2f}")

        elif fill.direction == SignalType.BUY: # Potentially covering a short position
            if current_qty < 0: # It's a closing or reducing short trade
                # P&L = (Entry Avg Short Price - Exit Price) * Quantity Covered - Commission for this fill
                # current_avg_price here is the average price at which the short position was entered.
                gross_pnl_component = (current_avg_price - fill.fill_price) * qty_being_closed
                realized_pnl_for_this_fill = gross_pnl_component - fill.commission
                logger.info(f"BUY_TO_COVER Fill P&L for {fill.symbol}: Qty={qty_being_closed}, EntryAvgShortPx={current_avg_price:.2f}, "
                            f"ExitPx={fill.fill_price:.2f}, GrossPnlComp={gross_pnl_component:.2f}, Comm={fill.commission:.2f}, NetPnl={realized_pnl_for_this_fill:.2f}")

        # Update the fill event object itself with the calculated P&L
        fill.realized_pnl_for_this_fill = realized_pnl_for_this_fill
        self.trades.append(fill) # Now trades list contains FillEvents with P&L

        # Update cash
        self.current_cash += fill.cash_impact

        # Update holdings
        if fill.direction == SignalType.BUY:
            new_cost_for_this_lot = fill.gross_value + fill.commission
            new_total_cost_basis = current_cost_basis + new_cost_for_this_lot
            new_total_quantity = current_qty + fill.quantity

            self.current_holdings[symbol]['quantity'] = new_total_quantity
            if new_total_quantity != 0: # Avoid division by zero if qty becomes zero (e.g. closing short)
                self.current_holdings[symbol]['average_price'] = new_total_cost_basis / abs(new_total_quantity) if new_total_quantity != 0 else 0
            else: # Position is flat
                self.current_holdings[symbol]['average_price'] = 0.0
            self.current_holdings[symbol]['cost_basis'] = new_total_cost_basis if new_total_quantity != 0 else 0.0


        elif fill.direction == SignalType.SELL:
            cost_of_shares_sold = fill.quantity * current_avg_price
            new_total_cost_basis = current_cost_basis - cost_of_shares_sold
            new_total_quantity = current_qty - fill.quantity

            self.current_holdings[symbol]['quantity'] = new_total_quantity
            self.current_holdings[symbol]['cost_basis'] = new_total_cost_basis
            if new_total_quantity == 0:
                self.current_holdings[symbol]['average_price'] = 0.0
                self.current_holdings[symbol]['cost_basis'] = 0.0
            # Average price of remaining shares (if any) does not change for SELLs under average cost basis accounting.

        logger.info(f"Portfolio: Processed {fill}")
        logger.info(f"Portfolio: Cash: {self.current_cash:.2f}, Holdings for {symbol}: Qty={self.current_holdings[symbol]['quantity']} @AvgPx={self.current_holdings[symbol]['average_price']:.2f}, CostBasis={self.current_holdings[symbol]['cost_basis']:.2f}")


    def simulate_order_execution(self, order: OrderEvent, market_event: MarketDataEvent) -> Optional[FillEvent]:
        if order.type != 'ORDER' or order.status != OrderStatus.PENDING:
            return None
        if order.symbol != market_event.symbol:
            logger.warning(f"Order symbol {order.symbol} and market event {market_event.symbol} mismatch.")
            return None

        base_execution_price: Optional[float] = None
        if order.order_type == OrderType.MARKET:
            base_execution_price = market_event.get('OPEN')
            if base_execution_price is None:
                logger.warning(f"MARKET order {order.symbol}: No OPEN price. Order PENDING.")
                return None
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= 0:
                logger.error(f"LIMIT order {order.symbol} invalid limit price {order.limit_price}. Order REJECTED.")
                order.status = OrderStatus.REJECTED
                return None
            bar_low, bar_high, bar_open = market_event.get('LOW'), market_event.get('HIGH'), market_event.get('OPEN')
            if bar_low is None or bar_high is None or bar_open is None:
                logger.warning(f"LIMIT order {order.symbol}: Missing OHLC data. Order PENDING.")
                return None
            if order.direction == SignalType.BUY:
                if bar_low <= order.limit_price: base_execution_price = min(bar_open, order.limit_price)
            elif order.direction == SignalType.SELL:
                if bar_high >= order.limit_price: base_execution_price = max(bar_open, order.limit_price)
            if base_execution_price is None:
                order.status = OrderStatus.PENDING; return None
        else:
            logger.error(f"Unknown order type {order.order_type}. Order REJECTED."); order.status = OrderStatus.REJECTED; return None

        actual_fill_price = base_execution_price
        slippage_applied_per_share = 0.0
        if self.slippage_model == "fixed_per_share": slippage_applied_per_share = self.slippage_fixed_amount
        elif self.slippage_model == "percentage": slippage_applied_per_share = base_execution_price * self.slippage_percentage
        if order.direction == SignalType.BUY: actual_fill_price += slippage_applied_per_share
        elif order.direction == SignalType.SELL: actual_fill_price -= slippage_applied_per_share
        actual_fill_price = max(0, actual_fill_price)
        logger.debug(f"{order.symbol} {order.direction.value} Qty {order.quantity}: BasePxSlippage={base_execution_price:.2f}, SlippageM='{self.slippage_model}', SlipPS={slippage_applied_per_share:.4f}, FillPx={actual_fill_price:.2f}")

        gross_trade_value = actual_fill_price * order.quantity
        calculated_commission = 0.0
        if self.commission_model == "fixed_per_trade": calculated_commission = self.commission_fixed_amount
        elif self.commission_model == "per_share": calculated_commission = self.commission_per_share * order.quantity
        elif self.commission_model == "percentage_value": calculated_commission = self.commission_percentage_value * gross_trade_value
        final_commission = abs(calculated_commission)
        if self.commission_model != "none" and self.commission_min_per_trade > 0 and self.commission_model != "fixed_per_trade":
            final_commission = max(final_commission, self.commission_min_per_trade)
        logger.debug(f"{order.symbol} {order.direction.value} Qty {order.quantity}: CommM='{self.commission_model}', GrossValComm={gross_trade_value:.2f}, CalcComm={calculated_commission:.2f}, FinalComm={final_commission:.2f}")

        if order.direction == SignalType.BUY:
            total_cost_with_commission = gross_trade_value + final_commission
            if self.current_cash < total_cost_with_commission:
                logger.warning(f"Insufficient cash for {order.order_type.value} BUY {order.symbol} post-comm. Have {self.current_cash:.2f}, Need {total_cost_with_commission:.2f}. Order { 'REJECTED' if order.order_type == OrderType.MARKET else 'PENDING' }.")
                order.status = OrderStatus.REJECTED if order.order_type == OrderType.MARKET else OrderStatus.PENDING
                return None

        # Realized P&L for this fill will be calculated in process_fill when context of existing position is available
        fill = FillEvent(
            timestamp=market_event.timestamp, symbol=order.symbol, quantity=order.quantity,
            direction=order.direction, fill_price=actual_fill_price,
            gross_value=gross_trade_value, commission=final_commission,
            realized_pnl_for_this_fill=None # Will be set by process_fill
        )
        order.status = OrderStatus.FILLED
        logger.info(f"Portfolio: Simulated execution for {order.symbol} -> {fill} (P&L to be updated in process_fill)")
        return fill

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    dummy_ts = pd.Timestamp('2023-01-01 09:30:00')
    market_event_aapl = MarketDataEvent(dummy_ts, 'AAPL', {'OPEN':150.00, 'HIGH': 152.00, 'LOW': 148.00, 'CLOSE':151.00})

    logger.info("\n--- Testing P&L on Fills ---")
    pnl_portfolio = Portfolio(initial_cash=50000)

    # BUY 10 AAPL @ 150 (Open price of market_event_aapl after slippage/comm)
    buy_signal = SignalEvent(dummy_ts, 'AAPL', SignalType.BUY, quantity=10)
    buy_order = pnl_portfolio.process_signal(buy_signal)
    if buy_order:
        buy_fill = pnl_portfolio.simulate_order_execution(buy_order, market_event_aapl)
        if buy_fill:
            pnl_portfolio.process_fill(buy_fill) # process_fill will calculate P&L (which is None for an opening trade)
            logger.info(f"Post-BUY FillEvent: {buy_fill}")

    # Assume market moves, next bar for selling
    dummy_ts_sell = pd.Timestamp('2023-01-01 09:35:00')
    market_event_aapl_sell = MarketDataEvent(dummy_ts_sell, 'AAPL', {'OPEN':155.00, 'HIGH': 157.00, 'LOW': 154.00, 'CLOSE':156.00})

    # SELL 5 AAPL @ 155 (Open price of market_event_aapl_sell after slippage/comm)
    sell_signal = SignalEvent(dummy_ts_sell, 'AAPL', SignalType.SELL, quantity=5)
    sell_order = pnl_portfolio.process_signal(sell_signal)
    if sell_order:
        sell_fill = pnl_portfolio.simulate_order_execution(sell_order, market_event_aapl_sell)
        if sell_fill:
            pnl_portfolio.process_fill(sell_fill) # process_fill will calculate P&L for this closing part
            logger.info(f"Post-SELL FillEvent: {sell_fill}")

    # SELL remaining 5 AAPL @ 155
    sell_all_signal = SignalEvent(dummy_ts_sell, 'AAPL', SignalType.SELL, quantity=5)
    sell_all_order = pnl_portfolio.process_signal(sell_all_signal)
    if sell_all_order:
        sell_all_fill = pnl_portfolio.simulate_order_execution(sell_all_order, market_event_aapl_sell)
        if sell_all_fill:
            pnl_portfolio.process_fill(sell_all_fill)
            logger.info(f"Post-SELL-ALL FillEvent: {sell_all_fill}")

    logger.info("\n--- P&L Test Finished. Check logs for P&L calculations on FillEvents. ---")
    logger.info(f"Final Cash: {pnl_portfolio.current_cash:.2f}")
    logger.info(f"Final Holdings: {pnl_portfolio.current_holdings}")
    logger.info("All Trades with P&L:")
    for t in pnl_portfolio.trades:
        print(t)
