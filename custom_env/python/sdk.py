# sdk.py - SDK for user strategies, adaptable for backtesting or standalone mode.

import json
import datetime
import pandas as pd
import os
from typing import List, Dict, Optional, Any
import logging
from abc import ABC, abstractmethod

# --- SDK Logger Setup ---
SDK_LOGGER_NAME = "CUSTOM_ENV_SDK"
sdk_logger = logging.getLogger(SDK_LOGGER_NAME)
_sdk_logger_configured_by_sdk = False

def setup_sdk_logging(level: int = logging.INFO, json_format: bool = True, force_setup: bool = False):
    global _sdk_logger_configured_by_sdk
    if sdk_logger.handlers and not force_setup: return
    if force_setup:
        for handler in sdk_logger.handlers[:]: sdk_logger.removeHandler(handler); handler.close()
    sdk_logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter_str_json = '%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s'
    formatter_str_basic = '%(asctime)s - SDK - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    if json_format:
        try:
            from python_json_logger import jsonlogger
            formatter = jsonlogger.JsonFormatter(formatter_str_json)
            handler.setFormatter(formatter)
        except ImportError:
            formatter = logging.Formatter(formatter_str_basic)
            handler.setFormatter(formatter)
            sdk_logger.warning("python-json-logger not found. SDK falling back to basic logging format.")
    else:
        formatter = logging.Formatter(formatter_str_basic)
        handler.setFormatter(formatter)
    sdk_logger.addHandler(handler)
    sdk_logger.propagate = False
    _sdk_logger_configured_by_sdk = True
    sdk_logger.info(f"SDK logger '{SDK_LOGGER_NAME}' configured (json={json_format}, level={logging.getLevelName(level)}).")

# --- Backtester Integration Globals & Fallback Mocks ---
CURRENT_PORTFOLIO_INSTANCE: Optional[Any] = None
CURRENT_ENGINE_INSTANCE: Optional[Any] = None
CURRENT_TIMESTAMP: Optional[datetime.datetime] = None
BACKTESTER_COMPONENTS_AVAILABLE = False
try:
    from backtester.strategy import SignalEvent, SignalType
    from backtester.portfolio import OrderType as BacktesterOrderType, OrderStatus as BacktesterOrderStatus
    from backtester.portfolio import Portfolio
    from backtester.engine import BacktestEngine
    from backtester.data import MarketDataEvent
    BACKTESTER_COMPONENTS_AVAILABLE = True
except ImportError:
    SignalEvent, SignalType, BacktesterOrderType, BacktesterOrderStatus = None, None, None, None
    Portfolio, BacktestEngine, MarketDataEvent = None, None, None

HISTORICAL_DATA_DIR = os.getenv("CDE_HISTORICAL_DATA_PATH", "/app/historical_data")

# Default mock portfolio for standalone mode
DEFAULT_MOCK_PORTFOLIO_STANDALONE = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
    "cash": 100000.0,
    "total_portfolio_value": 100000.0,
    "positions_value": 0.0,
    "positions": [] # List of position dicts like {"symbol": "XYZ", "quantity": 0, ...}
}
_current_mock_portfolio_standalone = copy.deepcopy(DEFAULT_MOCK_PORTFOLIO_STANDALONE) # Modifiable copy
_mock_order_id_counter_standalone = 0
import copy # For deepcopy

# --- SDK Logging Function ---
def log(message: Any, level: str = "INFO", **extra_fields):
    global _sdk_logger_configured_by_sdk, sdk_logger
    if not sdk_logger.handlers and not logging.getLogger().handlers and not _sdk_logger_configured_by_sdk :
        print(f"SDK_LOG_INIT_NOTE: SDK logger '{SDK_LOGGER_NAME}' has no handlers. Attempting default SDK setup.")
        setup_sdk_logging()
    log_level_int = getattr(logging, level.upper(), logging.INFO)
    if extra_fields:
        is_json_formatter = any('jsonlogger.JsonFormatter' in str(type(h.formatter)) for h in sdk_logger.handlers)
        if not is_json_formatter and sdk_logger.handlers:
             sdk_logger.log(log_level_int, f"{message} (Details: {json.dumps(extra_fields)})")
        else:
             sdk_logger.log(log_level_int, message, extra=extra_fields)
    else:
        sdk_logger.log(log_level_int, message)

# --- SDK Market Data Function ---
def get_market_data(symbol: str, timeframe: str = "1d",
                    start_date: Optional[str] = None, end_date: Optional[str] = None,
                    lookback_rows: Optional[int] = None) -> List[Dict[str, Any]]:
    if CURRENT_TIMESTAMP is not None:
       log("SDK: get_market_data called during active backtest event loop. Prefer data from on_bar for current bar.", level="WARNING")
    # ... (rest of get_market_data implementation from 7.6 - remains unchanged) ...
    log(f"get_market_data call", level="DEBUG", symbol=symbol, timeframe=timeframe, start_date=start_date, end_date=end_date, lookback_rows=lookback_rows)
    if timeframe != "1d": log(f"Warning: timeframe '{timeframe}' not directly used by CSV reader.", level="WARNING", symbol=symbol)
    filepath = os.path.join(HISTORICAL_DATA_DIR, f"{symbol.upper()}_data.csv")
    if not os.path.exists(filepath): log(f"Data file not found: {filepath}", level="ERROR", symbol=symbol); return []
    try:
        df = pd.read_csv(filepath, parse_dates=['Timestamp'])
        df.columns = [str(col).upper() for col in df.columns]; required_cols = {'TIMESTAMP', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'}
        if not required_cols.issubset(set(df.columns)): log(f"CSV {filepath} missing required columns.", level="ERROR", symbol=symbol); return []
        df = df.set_index('TIMESTAMP').sort_index(); processed_df = df.copy()
        if end_date:
            actual_end_date = pd.to_datetime(end_date);
            if actual_end_date.time() == datetime.time(0,0): actual_end_date = actual_end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            processed_df = processed_df[processed_df.index <= actual_end_date]
        if lookback_rows is not None:
            if not processed_df.empty: processed_df = processed_df.tail(lookback_rows)
            if start_date and lookback_rows is not None: log("Warning: Both lookback_rows and start_date provided.", level="WARNING", symbol=symbol)
        if start_date and (lookback_rows is None or (lookback_rows is not None and processed_df.empty and not df.empty) ) :
            original_target_df = df if processed_df.empty and not df.empty else processed_df
            actual_start_date = pd.to_datetime(start_date); processed_df = original_target_df[original_target_df.index >= actual_start_date]
            if original_target_df is df and end_date and not processed_df.empty:
                actual_end_date = pd.to_datetime(end_date)
                if actual_end_date.time() == datetime.time(0,0): actual_end_date = actual_end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                processed_df = processed_df[processed_df.index <= actual_end_date]
        if processed_df.empty: log(f"No data for {symbol} in range/lookback.", level="DEBUG", symbol=symbol); return []
        output_data = []
        for ts_val, row in processed_df.iterrows():
            bar_data = row.to_dict()
            py_ts = ts_val.to_pydatetime() if isinstance(ts_val, pd.Timestamp) else ts_val
            bar_data['timestamp'] = py_ts.isoformat() + "Z"
            for k, v in bar_data.items():
                if k.upper() == 'TIMESTAMP': continue
                if isinstance(v, (pd.Timestamp, datetime.datetime)): bar_data[k] = v.isoformat() + "Z"
                elif pd.api.types.is_integer_dtype(type(v)) and hasattr(v, 'item'): bar_data[k] = v.item()
                elif pd.api.types.is_float_dtype(type(v)) and hasattr(v, 'item'): bar_data[k] = v.item()
                elif pd.isna(v): bar_data[k] = None
            output_data.append(bar_data)
        log(f"Retrieved {len(output_data)} bars for {symbol}.", level="DEBUG", symbol=symbol, count=len(output_data)); return output_data
    except Exception as e: log(f"Error processing data for {symbol}: {e}", level="ERROR", symbol=symbol, exc_info=True); return []


def set_backtest_context(engine_instance, portfolio_instance, bar_timestamp):
    global CURRENT_ENGINE_INSTANCE, CURRENT_PORTFOLIO_INSTANCE, CURRENT_TIMESTAMP
    CURRENT_ENGINE_INSTANCE = engine_instance; CURRENT_PORTFOLIO_INSTANCE = portfolio_instance; CURRENT_TIMESTAMP = bar_timestamp

def submit_order(symbol: str, order_type: str, quantity: float, price: Optional[float] = None, tif: str = "GTC") -> Dict[str, Any]:
    global _mock_order_id_counter_standalone, _current_mock_portfolio_standalone

    log_message_core = f"submit_order call: Symbol={symbol}, Type={order_type}, Qty={quantity}, Price={price}, TIF={tif}"

    actual_quantity_abs = abs(quantity)
    if quantity == 0: # quantity is float, direct comparison is fine
        log(f"SDK: {log_message_core} - REJECTED: Quantity is zero.", level="WARNING")
        return {"status": "REJECTED", "order_id": None, "reason": "Quantity is zero"}

    # --- Backtest Mode Logic ---
    if CURRENT_PORTFOLIO_INSTANCE is not None and \
       CURRENT_ENGINE_INSTANCE is not None and \
       CURRENT_TIMESTAMP is not None and \
       BACKTESTER_COMPONENTS_AVAILABLE:

        log(f"SDK (BacktestMode): {log_message_core}", level="INFO")
        trade_direction = SignalType.BUY if quantity > 0 else SignalType.SELL

        # Map SDK order_type string to backtester's OrderType enum for process_signal
        # Portfolio.process_signal infers LIMIT from price, otherwise MARKET
        limit_price_for_signal = None
        if order_type.upper() == "LIMIT":
            if price is None or price <= 0:
                log(f"SDK (BacktestMode): Invalid price {price} for LIMIT order. Order REJECTED.", level="ERROR")
                return {"status": "REJECTED", "order_id": None, "reason": "Invalid price for LIMIT order."}
            limit_price_for_signal = price
        elif order_type.upper() != "MARKET":
            log(f"SDK (BacktestMode): Unsupported order_type '{order_type}'. Order REJECTED.", level="ERROR")
            return {"status": "REJECTED", "order_id": None, "reason": f"Unsupported order type '{order_type}' for backtester."}

        signal = SignalEvent(
            timestamp=CURRENT_TIMESTAMP, symbol=symbol.upper(), signal_type=trade_direction,
            quantity=actual_quantity_abs, price=limit_price_for_signal, # Pass price for LIMIT type inference
            details=f"SDK Order: {order_type.upper()}"
        )

        order_event = CURRENT_PORTFOLIO_INSTANCE.process_signal(signal)

        if order_event:
            # Backtester OrderEvent does not have a persistent ID itself, it's transient to FillEvent
            # We create a mock ID for the SDK response consistency.
            mock_sdk_order_id = f"{order_event.symbol}_{order_event.timestamp.strftime('%Y%m%d%H%M%S%f')}"
            log(f"SDK (BacktestMode): Portfolio generated OrderEvent (ID_proxy={mock_sdk_order_id}), Status={order_event.status.value}", level="INFO")
            CURRENT_ENGINE_INSTANCE.pending_execution_orders.append(order_event)
            confirmation = {"status": order_event.status.value, "order_id": mock_sdk_order_id,
                            "symbol": order_event.symbol, "order_type": order_event.order_type.value,
                            "quantity": quantity, "price": order_event.limit_price,
                            "timestamp": order_event.timestamp.isoformat() + "Z", "tif": tif}
        else:
            log(f"SDK (BacktestMode): Portfolio rejected signal: {signal}", level="WARNING")
            confirmation = {"status": "REJECTED_BY_PORTFOLIO", "order_id": None, "reason": "Portfolio rejected signal."}
        return confirmation
    else: # --- Standalone Mode Logic ---
        log(f"SDK (StandaloneMode): {log_message_core}", level="INFO")
        if order_type.upper() == "LIMIT" and (price is None or price <= 0):
            log("SDK (StandaloneMode): Price must be specified and positive for LIMIT orders.", level="WARNING")
            return {"status": "REJECTED", "order_id": None, "reason": "Price not specified or invalid for LIMIT order"}

        _mock_order_id_counter_standalone += 1
        mock_order_id = f"SDK_MOCK_ORD_{_mock_order_id_counter_standalone}"

        # Simulate very basic portfolio update for standalone mock
        symbol_upper = symbol.upper()
        _current_mock_portfolio_standalone["positions"].sort(key=lambda x: x["symbol"]) # Ensure consistent order for finding
        pos_idx = -1
        for i, p in enumerate(_current_mock_portfolio_standalone["positions"]):
            if p["symbol"] == symbol_upper: pos_idx = i; break

        est_fill_price = price if price and price > 0 else (pd.Series([100,101,99]).sample(1).iloc[0] if BACKTESTER_COMPONENTS_AVAILABLE else 100.0) # Dummy price if market

        if quantity > 0: # Buy
            _current_mock_portfolio_standalone["cash"] -= est_fill_price * actual_quantity_abs
            if pos_idx != -1:
                old_qty = _current_mock_portfolio_standalone["positions"][pos_idx]["quantity"]
                old_avg_px = _current_mock_portfolio_standalone["positions"][pos_idx]["average_price"]
                new_qty = old_qty + actual_quantity_abs
                _current_mock_portfolio_standalone["positions"][pos_idx]["average_price"] = \
                    ((old_avg_px * old_qty) + (est_fill_price * actual_quantity_abs)) / new_qty if new_qty !=0 else 0
                _current_mock_portfolio_standalone["positions"][pos_idx]["quantity"] = new_qty
            else:
                _current_mock_portfolio_standalone["positions"].append({
                    "symbol":symbol_upper, "quantity": actual_quantity_abs, "average_price": est_fill_price
                })
        else: # Sell
            _current_mock_portfolio_standalone["cash"] += est_fill_price * actual_quantity_abs
            if pos_idx != -1:
                _current_mock_portfolio_standalone["positions"][pos_idx]["quantity"] -= actual_quantity_abs
                if _current_mock_portfolio_standalone["positions"][pos_idx]["quantity"] == 0:
                    _current_mock_portfolio_standalone["positions"].pop(pos_idx)
            # Assuming can't go short in this simple mock

        _current_mock_portfolio_standalone["total_portfolio_value"] = _current_mock_portfolio_standalone["cash"]
        _current_mock_portfolio_standalone["positions_value"] = 0
        for p in _current_mock_portfolio_standalone["positions"]:
             _current_mock_portfolio_standalone["positions_value"] += p["quantity"] * p.get("average_price", est_fill_price) # MTM at avg price for mock
        _current_mock_portfolio_standalone["total_portfolio_value"] += _current_mock_portfolio_standalone["positions_value"]
        _current_mock_portfolio_standalone["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"


        confirmation = {"status": "ACCEPTED_MOCK", "order_id": mock_order_id, "symbol": symbol.upper(),
                        "order_type": order_type.upper(), "quantity": quantity, "price": price,
                        "timestamp": _current_mock_portfolio_standalone["timestamp"], "tif": tif}
        log(f"SDK (StandaloneMode): Order {mock_order_id} mock-accepted. Mock portfolio updated.", level="INFO")
        return confirmation

def get_portfolio_summary() -> Dict[str, Any]:
    log("SDK: get_portfolio_summary called.", level="DEBUG")
    if CURRENT_PORTFOLIO_INSTANCE and CURRENT_ENGINE_INSTANCE and CURRENT_TIMESTAMP and BACKTESTER_COMPONENTS_AVAILABLE:
        current_cash = CURRENT_PORTFOLIO_INSTANCE.current_cash
        holdings_value = 0.0; positions_sdk = []
        current_portfolio_value_mtm = current_cash
        active_market_data = CURRENT_ENGINE_INSTANCE.current_market_data if hasattr(CURRENT_ENGINE_INSTANCE, 'current_market_data') else {}

        for sym, pos_details in CURRENT_PORTFOLIO_INSTANCE.current_holdings.items():
            if pos_details['quantity'] != 0:
                market_event = active_market_data.get(sym)
                current_price = pos_details['average_price']
                price_source_log = "avg_price"
                if market_event and market_event.get('CLOSE') is not None and pd.notna(market_event.get('CLOSE')):
                    current_price = market_event.get('CLOSE'); price_source_log = "market_close"
                elif market_event and market_event.get('OPEN') is not None and pd.notna(market_event.get('OPEN')):
                    current_price = market_event.get('OPEN'); price_source_log = "market_open"

                if price_source_log == "avg_price" and market_event : # Log only if market_event was present but no usable price
                     log(f"SDK:get_portfolio_summary - Using avg_price for MTM of {sym} as live market price not found/NaN in current bar data ({market_event.data if market_event else 'no event'}). Qty: {pos_details['quantity']}", level="DEBUG")

                symbol_market_value = pos_details['quantity'] * current_price
                holdings_value += symbol_market_value
                positions_sdk.append({"symbol": sym, "quantity": pos_details['quantity'], "average_price": pos_details['average_price'],
                                      "market_value": symbol_market_value, "cost_basis": pos_details.get('cost_basis', 0.0)})
        current_portfolio_value_mtm += holdings_value
        summary = {"timestamp": CURRENT_TIMESTAMP.isoformat() + "Z", "cash": current_cash,
                   "total_portfolio_value": current_portfolio_value_mtm, "positions_value": holdings_value,
                   "positions": positions_sdk }
        log(f"SDK (BacktestMode): Portfolio Summary: Cash={summary['cash']:.2f}, TotalVal={summary['total_portfolio_value']:.2f}", level="DEBUG")
        return summary
    else:
        log("SDK (StandaloneMode): get_portfolio_summary called.", level="INFO")
        # Update timestamp of the mock before returning
        _current_mock_portfolio_standalone["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
        return copy.deepcopy(_current_mock_portfolio_standalone)

def get_position(symbol: str) -> Optional[Dict[str, Any]]:
    log(f"SDK: get_position called for {symbol}.", level="DEBUG")
    target_symbol_upper = symbol.upper()
    if CURRENT_PORTFOLIO_INSTANCE and CURRENT_ENGINE_INSTANCE and CURRENT_TIMESTAMP and BACKTESTER_COMPONENTS_AVAILABLE:
        pos_details = CURRENT_PORTFOLIO_INSTANCE.current_holdings.get(target_symbol_upper)
        if pos_details and pos_details['quantity'] != 0:
            current_price = pos_details['average_price']
            active_market_data = CURRENT_ENGINE_INSTANCE.current_market_data if hasattr(CURRENT_ENGINE_INSTANCE, 'current_market_data') else {}
            market_event = active_market_data.get(target_symbol_upper)
            if market_event and market_event.get('CLOSE') is not None and pd.notna(market_event.get('CLOSE')):
                current_price = market_event.get('CLOSE')
            elif market_event and market_event.get('OPEN') is not None and pd.notna(market_event.get('OPEN')):
                 current_price = market_event.get('OPEN')
            position_sdk = {"symbol": target_symbol_upper, "quantity": pos_details['quantity'],
                            "average_price": pos_details['average_price'], "cost_basis": pos_details.get('cost_basis', 0.0),
                            "current_market_price": current_price, "market_value": pos_details['quantity'] * current_price,
                            "timestamp": CURRENT_TIMESTAMP.isoformat() + "Z"}
            return position_sdk
        return None
    else:
        log(f"SDK (StandaloneMode): get_position for {symbol} called.", level="INFO")
        mock_positions = _current_mock_portfolio_standalone.get("positions", [])
        for pos in mock_positions:
            if pos["symbol"] == target_symbol_upper:
                # Add some mock market value if desired for standalone
                pos_copy = pos.copy()
                pos_copy["current_market_price"] = pos.get('average_price', 0) + pd.Series([0,1,-1,0.5,-0.5]).sample(1).iloc[0] # some jitter
                pos_copy["market_value"] = pos_copy["quantity"] * pos_copy["current_market_price"]
                pos_copy["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
                return pos_copy
        return None

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, symbols_of_interest: List[str], **strategy_params):
        self.strategy_id = strategy_id; self.symbols_of_interest = symbols_of_interest; self.strategy_params = strategy_params
        self._oms_interface = None; self._sdk_context_ref = None
        log(f"BaseStrategy '{self.strategy_id}' initialized. Symbols: {self.symbols_of_interest}, Params: {self.strategy_params}", level="INFO")
    def _set_sdk_internals(self, oms_interface: Optional[Any], sdk_context_ref: Optional[Any]):
        self._oms_interface = oms_interface; self._sdk_context_ref = sdk_context_ref
        log(f"BaseStrategy '{self.strategy_id}': SDK internals set.", level="DEBUG")
    @abstractmethod
    def on_start(self): pass
    @abstractmethod
    def on_stop(self): pass
    @abstractmethod
    def on_bar(self, timestamp: datetime.datetime, current_bar_data_bundle: Dict[str, Dict[str, Any]]): pass
    def on_fill(self, fill_info: Dict[str, Any]):
        log(f"BaseStrategy '{self.strategy_id}' received on_fill: Symbol {fill_info.get('symbol')}", level="DEBUG", fill_data=fill_info)

if __name__ == "__main__":
    setup_sdk_logging(level=logging.DEBUG, json_format=False)
    log("SDK direct usage example started (with dual mode functions).", level="INFO")

    # Test standalone mode (no backtest context set)
    log("\n--- Testing SDK functions in Standalone Mode ---", level="INFO")
    CURRENT_PORTFOLIO_INSTANCE = None; CURRENT_ENGINE_INSTANCE = None; CURRENT_TIMESTAMP = None # Ensure context is clear

    summary1 = get_portfolio_summary()
    log(f"Initial Standalone Summary: {json.dumps(summary1, indent=2)}")

    order1 = submit_order("PYPL", "MARKET", 100) # Buy 100 PYPL (mock)
    log(f"Standalone Order 1: {json.dumps(order1, indent=2)}")

    order2 = submit_order("SQ", "LIMIT", 50, price=75.50) # Buy 50 SQ (mock)
    log(f"Standalone Order 2: {json.dumps(order2, indent=2)}")

    summary2 = get_portfolio_summary()
    log(f"Standalone Summary after orders: {json.dumps(summary2, indent=2)}")

    pos_pypl = get_position("PYPL")
    log(f"Standalone PYPL Position: {json.dumps(pos_pypl, indent=2)}")
    pos_tsla = get_position("TSLA") # Should be None
    log(f"Standalone TSLA Position: {json.dumps(pos_tsla, indent=2)}")

    # Test selling some PYPL
    order3 = submit_order("PYPL", "MARKET", -30)
    log(f"Standalone Order 3 (Sell PYPL): {json.dumps(order3, indent=2)}")
    summary3 = get_portfolio_summary()
    log(f"Standalone Summary after selling PYPL: {json.dumps(summary3, indent=2)}")


    log("\n--- Testing get_market_data (still uses CSVs) ---", level="INFO")
    test_data_dir = "sdk_test_data_sdk_main_v4"
    os.makedirs(test_data_dir, exist_ok=True)
    original_data_dir = HISTORICAL_DATA_DIR
    HISTORICAL_DATA_DIR = os.path.abspath(test_data_dir)
    log(f"SDK Test: Overriding HISTORICAL_DATA_DIR to: {HISTORICAL_DATA_DIR}", level="DEBUG")
    aapl_timestamps = pd.to_datetime(["2023-01-01T10:00:00Z", "2023-01-02T10:00:00Z"])
    df_aapl = pd.DataFrame({'Timestamp': aapl_timestamps, 'OPEN': [150.0, 150.6], 'HIGH': [151.0, 152.0],
                            'LOW': [149.0, 150.0], 'CLOSE': [150.5, 151.5], 'VOLUME': [10000, 12000]})
    aapl_filepath = os.path.join(HISTORICAL_DATA_DIR, "AAPL_data.csv")
    df_aapl.to_csv(aapl_filepath, index=False)
    log(f"SDK Test: Created dummy data at {aapl_filepath}", level="DEBUG")
    aapl_data = get_market_data("AAPL")
    log(f"Received AAPL data from CSV (count: {len(aapl_data)})", level="INFO")
    try:
        if os.path.exists(aapl_filepath): os.remove(aapl_filepath)
        if os.path.exists(test_data_dir) and not os.listdir(test_data_dir): os.rmdir(test_data_dir)
        log("SDK Test: Cleaned up dummy data and directory.", level="DEBUG")
    except OSError as e: log(f"SDK Test: Error cleaning up test data: {e}", level="ERROR")
    HISTORICAL_DATA_DIR = original_data_dir
    log(f"SDK Test: Restored HISTORICAL_DATA_DIR to: {HISTORICAL_DATA_DIR}", level="DEBUG")

    log("SDK direct usage example finished.", level="INFO")
