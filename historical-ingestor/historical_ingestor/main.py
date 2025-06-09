import argparse
import logging
from datetime import datetime, timedelta, timezone # Added timezone

from .config import load_config, Config
from .polygon_client import PolygonRESTClient
from .normalizer import (
    normalize_aggregate_record,
    normalize_trade_record,
    normalize_quote_record,
    # Ensure these are correctly imported relative to where market_data_pb2 is.
    # If common/gen/python is in PYTHONPATH, then:
    # from market_data import market_data_pb2 as pb
    # For now, using a mock as defined in the prompt, to be replaced by actual import.
)
from .kafka_producer import MarketDataProducer

# --- Mock Protobuf for conceptual structure ---
# This section should be replaced by actual imports from the generated Protobuf files.
# from market_data import market_data_pb2 as pb # This is the target import
class MockProtoMessage:
    def SerializeToString(self) -> bytes:
        return b"mock_proto_bytes"

class MockPb:
    class Trade(MockProtoMessage):
        def __init__(self, ticker=None, price=None, size=None, timestamp_ns=None, exchange=None, conditions=None, tape=None, id=None): pass
    class Quote(MockProtoMessage):
        def __init__(self, ticker=None, bid_price=None, bid_size=None, bid_exchange=None, ask_price=None, ask_size=None, ask_exchange=None, timestamp_ns=None, conditions=None, tape=None): pass
    class Aggregate(MockProtoMessage):
        def __init__(self, ticker=None, open=None, high=None, low=None, close=None, volume=None, vwap=None, start_time_ns=None, end_time_ns=None, timeframe=None, transactions=None): pass
pb = MockPb()
# --- End Mock Protobuf ---


def setup_logging(log_level_str: str):
    level = logging.getLevelName(log_level_str.upper())
    if not isinstance(level, int):
        level = logging.INFO # Default if invalid
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Quieten overly verbose libraries if necessary
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)


def main():
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Polygon.io Historical Data Ingestor")
    parser.add_argument("--tickers", required=True, help="Comma-separated list of ticker symbols (e.g., AAPL,MSFT,X:BTCUSD)")
    parser.add_argument("--data-type", required=True, choices=["aggregates", "trades", "quotes"], help="Type of data to fetch")
    parser.add_argument("--from-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", required=True, help="End date (YYYY-MM-DD)")

    # Args for aggregates
    parser.add_argument("--multiplier", type=int, default=1, help="Multiplier for timespan (e.g., 1 for 1 minute)")
    parser.add_argument("--timespan", default="minute", help="Timespan for aggregates (second, minute, hour, day, week, month, quarter, year)")

    # Args for trades/quotes (daily iteration)
    # No specific args here, iterate day by day between from_date and to_date

    args = parser.parse_args()

    # --- Configuration & Logging Setup ---
    try:
        cfg = load_config()
        setup_logging(cfg.log_level) # Use log level from config
    except Exception as e:
        logging.fatal(f"Failed to load configuration or setup logging: {e}", exc_info=True)
        return

    logger = logging.getLogger(__name__) # Get logger after basicConfig is set

    # --- Initialize Clients ---
    try:
        poly_client = PolygonRESTClient(cfg.polygon_rest)
        kafka_prod = MarketDataProducer(cfg.kafka)
    except Exception as e:
        logger.fatal(f"Failed to initialize clients: {e}", exc_info=True)
        return

    processed_total_records = 0
    start_global_time = time.time()

    try:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(',')]
        from_date_obj = datetime.strptime(args.from_date, "%Y-%m-%d").date()
        to_date_obj = datetime.strptime(args.to_date, "%Y-%m-%d").date()

        for ticker in tickers:
            logger.info(f"--- Processing ticker: {ticker} ---")

            if args.data_type == "aggregates":
                logger.info(f"Fetching aggregates for {ticker} from {args.from_date} to {args.to_date}")
                # For aggregates, Polygon's range API is efficient for date ranges.
                # The client method already handles potential iteration if we were to make it more granular.
                # For now, it makes one call per ticker for the full date range.
                try:
                    for record in poly_client.get_aggregates(
                        ticker, args.multiplier, args.timespan, args.from_date, args.to_date
                    ):
                        timespan_label = f"{args.multiplier}{args.timespan.capitalize()}" # Consistent with normalizer
                        normalized_agg = normalize_aggregate_record(record, ticker, args.multiplier, args.timespan)
                        if normalized_agg:
                            kafka_prod.publish_message(normalized_agg, ticker, "aggregate")
                            processed_total_records += 1
                    logger.info(f"Finished fetching aggregates for {ticker}.")
                except Exception as e:
                    logger.error(f"Error processing aggregates for {ticker}: {e}", exc_info=True)
                    continue # Move to next ticker

            elif args.data_type == "trades" or args.data_type == "quotes":
                # Iterate day by day for trades and quotes
                current_date = from_date_obj
                while current_date <= to_date_obj:
                    date_str = current_date.strftime("%Y-%m-%d")
                    logger.info(f"Fetching {args.data_type} for {ticker} on {date_str}")

                    try:
                        if args.data_type == "trades":
                            for record in poly_client.get_trades_for_day(ticker, date_str):
                                # The 'ticker' is often not in each trade record from Polygon's list results,
                                # so we pass it to the normalizer from the context.
                                record['ticker'] = ticker # Ensure ticker is available for normalizer
                                normalized_trade = normalize_trade_record(record, asset_class="stocks") # Assuming stocks for now
                                if normalized_trade:
                                    kafka_prod.publish_message(normalized_trade, ticker, "trade")
                                    processed_total_records += 1
                        elif args.data_type == "quotes":
                            # Placeholder for get_quotes_for_day - assuming similar structure to trades
                            # for record in poly_client.get_quotes_for_day(ticker, date_str):
                            #     record['ticker'] = ticker
                            #     normalized_quote = normalize_quote_record(record, asset_class="stocks")
                            #     if normalized_quote:
                            #         kafka_prod.publish_message(normalized_quote, ticker, "quote")
                            #         processed_total_records += 1
                            logger.warning(f"Quote fetching for {ticker} on {date_str} not fully implemented in this PoC main loop.")
                            pass # Skip quotes for now in main loop until client method is fleshed out

                    except Exception as e:
                        logger.error(f"Error processing {args.data_type} for {ticker} on {date_str}: {e}", exc_info=True)
                        # Continue to next day or ticker based on error strategy

                    current_date += timedelta(days=1)
                logger.info(f"Finished fetching {args.data_type} for {ticker} up to {to_date_obj.strftime('%Y-%m-%d')}.")

            # Poll Kafka producer periodically per ticker or rely on linger.ms and final flush
            kafka_prod.producer.poll(0)

    except Exception as e:
        logger.fatal(f"A critical error occurred during data ingestion process: {e}", exc_info=True)
    finally:
        if 'kafka_prod' in locals() and kafka_prod is not None:
            logger.info("Flushing Kafka producer...")
            kafka_prod.flush()

        end_global_time = time.time()
        logger.info(f"Historical Ingestor finished. Total records processed: {processed_total_records}. Total time: {end_global_time - start_global_time:.2f} seconds.")

if __name__ == "__main__":
    # This is where you would ensure actual generated pb files are importable.
    # For conceptual execution, we need to ensure the mock pb object is replaced
    # if this script were to be run directly for testing.
    try:
        from market_data import market_data_pb2 as actual_pb
        pb.Trade = actual_pb.Trade
        pb.Quote = actual_pb.Quote
        pb.Aggregate = actual_pb.Aggregate
        logger.info("Successfully imported actual protobuf messages.")
    except ImportError:
        logger.warning("Could not import actual protobuf messages, using mock. Ensure common/gen/python is in PYTHONPATH.")

    main()
