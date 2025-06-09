import logging
from typing import List, Dict, Any, Optional, Union

# Assuming the generated protobuf files are accessible.
# The path might need adjustment based on your project structure and PYTHONPATH.
# E.g., if 'common' is a top-level dir and historical_ingestor is another:
# from ..common.gen.python.market_data import market_data_pb2 as pb
# For this flat structure, we'll use a direct import path, assuming common/ is in python path or installed.
# If common/gen/python is directly in historical_ingestor path or historical_ingestor is run from root:
from market_data import market_data_pb2 as pb # This import will be resolved if PYTHONPATH is set up correctly

logger = logging.getLogger(__name__)

# --- Mapping functions (Conceptual placeholders - require detailed Polygon documentation) ---
# These should be consistent with the Go version's mapping logic if data needs to be identical.

def map_exchange_id_to_string(id_val: Optional[Any], asset_class: str = "stocks") -> str:
    if id_val is None: return ""
    # This needs a comprehensive map from Polygon's integer IDs to string representations.
    # Placeholder:
    return str(id_val)

def map_condition_codes_to_strings(codes: Optional[List[Any]], asset_class: str = "stocks") -> List[str]:
    if not codes:
        return []
    # This needs a comprehensive map from Polygon's integer conditions to string representations.
    # Placeholder:
    return [str(c) for c in codes]

def map_tape_id_to_string(id_val: Optional[Any], asset_class: str = "stocks") -> str:
    if id_val is None: return ""
    # Specific to US stocks for Polygon usually.
    if asset_class == "stocks":
        tape_map = {1: "CTA_A", 2: "CTA_B", 3: "UTP_C"} # Example from Go version
        return tape_map.get(id_val, f"Tape{id_val}")
    return str(id_val)

def get_timeframe_label(multiplier: int, timespan_unit: str) -> str:
    """
    Creates a standardized timeframe label.
    Example: 1, "minute" -> "M1"
             5, "day"    -> "D5" (though D1 is more common)
    """
    unit_map = {
        "second": "S",
        "minute": "M",
        "hour": "H",
        "day": "D",
        "week": "W",
        "month": "Mo", # Using "Mo" to avoid conflict with Minute if just "M"
        "quarter": "Q",
        "year": "Y"
    }
    unit_short = unit_map.get(timespan_unit.lower(), timespan_unit.upper())
    return f"{unit_short}{multiplier}"


# --- Normalization Functions ---

def normalize_aggregate_record(record: Dict[str, Any], ticker: str, multiplier: int, timespan_unit: str) -> Optional[pb.Aggregate]:
    """
    Normalizes a single Polygon.io aggregate (bar) record (from REST API v2 /v2/aggs/...)
    to the canonical pb.Aggregate Protobuf message.
    """
    try:
        # Polygon /v2/aggs/ uses 't' for timestamp (start of window, milliseconds)
        # 'o', 'h', 'l', 'c', 'v', 'vw', 'n' (transactions)
        start_time_ms = record.get('t')
        if start_time_ms is None:
            logger.warning(f"Missing timestamp 't' in aggregate record for {ticker}: {record}")
            return None

        start_time_ns = int(start_time_ms * 1_000_000) # Milliseconds to Nanoseconds

        # Calculate end_time_ns (conceptual, Polygon v2 provides 'e' in WebSocket, but not always in REST /v2/aggs for range)
        # For REST /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}, the 't' is the start.
        # The duration needs to be inferred from 'multiplier' and 'timespan'.
        # This is a simplified calculation for end_time_ns.
        # A more robust way would be to parse from_date, to_date and timespan to determine exact bar end.
        # Or if Polygon's REST API for aggregates provides an end timestamp, use that.
        # For now, we'll assume 't' is the start and the bar duration is known.
        # The pb.Aggregate.end_time_ns is defined as "derived from start_time + duration".
        # This field might be better populated by a downstream service that understands interval arithmetic.
        # For now, let's leave it as 0 or calculate a rough estimate if possible.
        # Polygon's /v2/aggs (non-range) and WS aggs often provide 'e' (end time).
        # If this normalizer is only for /v2/aggs/range/... then 'e' is not present.

        end_time_ns = 0 # Placeholder, as REST v2 range aggs don't provide 'e' per bar.
                        # This should ideally be calculated based on timespan if needed downstream.

        return pb.Aggregate(
            ticker=ticker,
            open=record.get('o', 0.0),
            high=record.get('h', 0.0),
            low=record.get('l', 0.0),
            close=record.get('c', 0.0),
            volume=int(record.get('v', 0)),
            vwap=record.get('vw', 0.0), # Protobuf vwap is double
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns, # This is often start_time_ns + (duration of timeframe) - 1ns
            timeframe=get_timeframe_label(multiplier, timespan_unit),
            transactions=int(record.get('n', 0))
        )
    except Exception as e:
        logger.error(f"Error normalizing aggregate record {record} for {ticker}: {e}", exc_info=True)
        return None

def normalize_trade_record(record: Dict[str, Any], asset_class: str = "stocks") -> Optional[pb.Trade]:
    """
    Normalizes a single Polygon.io trade record (from REST API v3 /v3/trades/...)
    to the canonical pb.Trade Protobuf message.
    Polygon v3 trade timestamps ('participant_timestamp', 'sip_timestamp') are in nanoseconds.
    """
    try:
        # Fields for v3 trades: symbol(in path), price, size, participant_timestamp, exchange, conditions, tape, id
        # 'id' is the trade_id. 'sip_timestamp' is when Polygon received it. 'participant_timestamp' is from exchange.
        timestamp_ns = record.get('participant_timestamp') or record.get('sip_timestamp') # Prefer participant
        if timestamp_ns is None:
            logger.warning(f"Missing timestamp in trade record: {record}")
            return None

        return pb.Trade(
            ticker=record.get('ticker'), # Ticker usually comes from the request context, not in each trade record from /v3/trades/{ticker}
            price=record.get('price', 0.0),
            size=int(record.get('size', 0)),
            timestamp_ns=int(timestamp_ns), # Already in nanoseconds for v3
            exchange=map_exchange_id_to_string(record.get('exchange'), asset_class),
            conditions=map_condition_codes_to_strings(record.get('conditions'), asset_class),
            tape=map_tape_id_to_string(record.get('tape'), asset_class), # Tape primarily for US stocks
            id=record.get('id', "") # Trade ID
        )
    except Exception as e:
        logger.error(f"Error normalizing trade record {record}: {e}", exc_info=True)
        return None

def normalize_quote_record(record: Dict[str, Any], asset_class: str = "stocks") -> Optional[pb.Quote]:
    """
    Normalizes a single Polygon.io quote record (from REST API v3 /v3/quotes/...)
    to the canonical pb.Quote Protobuf message.
    Polygon v3 quote timestamps ('participant_timestamp', 'sip_timestamp') are in nanoseconds.
    """
    try:
        # Fields for v3 quotes: symbol(in path), bid_price, bid_size, bid_exchange, ask_price, ask_size, ask_exchange, participant_timestamp, tape
        timestamp_ns = record.get('participant_timestamp') or record.get('sip_timestamp')
        if timestamp_ns is None:
            logger.warning(f"Missing timestamp in quote record: {record}")
            return None

        # Polygon's quote sizes are often in "round lots" (e.g., 1 = 100 shares).
        # The Protobuf schema has int64 for size, implying actual share/contract count.
        # This normalization might need to multiply by 100 for stock quotes if not already actual size.
        # For this example, assume 'bid_size' and 'ask_size' from Polygon are actual share counts.
        # Consult Polygon documentation for specifics on how 'size' is reported for quotes.

        return pb.Quote(
            ticker=record.get('ticker'), # Ticker from request context
            bid_price=record.get('bid_price', 0.0),
            bid_size=int(record.get('bid_size', 0)),
            bid_exchange=map_exchange_id_to_string(record.get('bid_exchange'), asset_class),
            ask_price=record.get('ask_price', 0.0),
            ask_size=int(record.get('ask_size', 0)),
            ask_exchange=map_exchange_id_to_string(record.get('ask_exchange'), asset_class),
            timestamp_ns=int(timestamp_ns), # Already in nanoseconds for v3
            conditions=map_condition_codes_to_strings(record.get('conditions'), asset_class), # Conditions are rare for quotes
            tape=map_tape_id_to_string(record.get('tape'), asset_class) # Tape primarily for US stocks
        )
    except Exception as e:
        logger.error(f"Error normalizing quote record {record}: {e}", exc_info=True)
        return None

if __name__ == '__main__':
    # Example Usage (requires actual pb generated code to be importable)
    # And actual record examples from Polygon.io
    logging.basicConfig(level=logging.INFO)

    # Mock aggregate record from Polygon v2 /v2/aggs/
    mock_agg_record = {"t": 1672531200000, "o": 150.1, "h": 150.9, "l": 150.0, "c": 150.8, "v": 12000, "vw": 150.5, "n": 100}
    normalized_agg = normalize_aggregate_record(mock_agg_record, "AAPL", 1, "minute")
    if normalized_agg:
        logger.info(f"Normalized Aggregate: Ticker={normalized_agg.ticker}, Close={normalized_agg.close}, StartTimeNs={normalized_agg.start_time_ns}")

    # Mock trade record from Polygon v3 /v3/trades/
    mock_trade_record = {
        "ticker": "AAPL", # Manually added for this test, not in Polygon's list items
        "price": 150.25,
        "size": 100,
        "participant_timestamp": 1672531200123456789,
        "exchange": 4,
        "conditions": [14, 37],
        "tape": 1,
        "id": "some_trade_id"
    }
    normalized_trade = normalize_trade_record(mock_trade_record, asset_class="stocks")
    if normalized_trade:
         logger.info(f"Normalized Trade: Ticker={normalized_trade.ticker}, Price={normalized_trade.price}, ID={normalized_trade.id}")

    # Mock quote record from Polygon v3 /v3/quotes/
    mock_quote_record = {
        "ticker": "MSFT", # Manually added
        "bid_price": 250.50, "bid_size": 10, "bid_exchange": 10,
        "ask_price": 250.55, "ask_size": 5, "ask_exchange": 11,
        "participant_timestamp": 1672531200987654321,
        "tape": 3
    }
    normalized_quote = normalize_quote_record(mock_quote_record, asset_class="stocks")
    if normalized_quote:
        logger.info(f"Normalized Quote: Ticker={normalized_quote.ticker}, Bid={normalized_quote.bid_price}, Ask={normalized_quote.ask_price}")
