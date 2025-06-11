import pandas as pd
from abc import ABC, abstractmethod
from typing import Generator, Dict, Optional, Any
import logging # Added
import os # Added for file operations in example

logger = logging.getLogger(__name__) # Added

class MarketDataEvent:
    """
    Represents a new bar of market data.
    """
    def __init__(self, timestamp, symbol: str, data: Dict[str, float]):
        self.type = 'MARKET_DATA'
        self.timestamp = timestamp # Should be pd.Timestamp
        self.symbol = symbol
        # data typically includes 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'
        self.data = data

    def get(self, key: str, default: Optional[float] = None) -> Optional[float]:
        return self.data.get(key, default)

class AbstractDataHandler(ABC):
    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        """Returns the last updated bar from the data feed."""
        raise NotImplementedError

    @abstractmethod
    def stream_next_bar(self) -> Generator[Tuple[pd.Timestamp, Dict[str, MarketDataEvent]], None, None]: # Corrected return type
        """Generator that yields (timestamp, {symbol: MarketDataEvent}) for the current timestamp."""
        raise NotImplementedError

class CsvDataHandler(AbstractDataHandler):
    """
    Reads historical data for multiple symbols from CSV files, combines them,
    and streams them as time-aligned bars.
    Assumes CSV files are named like '{symbol}_data.csv'.
    Each CSV should have: Timestamp, Open, High, Low, Close, Volume
    """
    def __init__(self, csv_dir: str, symbols: list[str], ffill: bool = True,
                 start_date: Optional[str] = None, end_date: Optional[str] = None): # Added date filters
        self.csv_dir = csv_dir
        self.symbols = symbols
        self.ffill = ffill
        self.start_date = pd.to_datetime(start_date) if start_date else None # Convert to datetime
        self.end_date = pd.to_datetime(end_date) if end_date else None     # Convert to datetime
        self.combined_data: Optional[pd.DataFrame] = None
        self._load_data()

    def _load_data(self):
        logger.info(f"Loading data for symbols: {self.symbols} from {self.csv_dir}. Ffill: {self.ffill}. "
                    f"Date range: {self.start_date} to {self.end_date}")
        individual_dfs: Dict[str, pd.DataFrame] = {}

        for symbol in self.symbols:
            try:
                filepath = os.path.join(self.csv_dir, f"{symbol}_data.csv")
                df = pd.read_csv(filepath, parse_dates=['Timestamp'], index_col='Timestamp')
                df.columns = [col.upper() for col in df.columns]
                required_cols = {'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'}
                if not required_cols.issubset(df.columns):
                    logger.error(f"CSV for {symbol} at {filepath} missing one of required columns: {required_cols}")
                    # Skip this symbol or raise error - for now, skip by not adding to individual_dfs
                    continue

                # Convert relevant columns to numeric, coercing errors
                for col in required_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                individual_dfs[symbol] = df.sort_index()
                logger.info(f"Successfully loaded and processed data for {symbol}: {len(df)} rows.")
            except FileNotFoundError:
                logger.error(f"Data file for {symbol} not found at {filepath}")
                # Continue to load other symbols
            except ValueError as ve:
                logger.error(f"ValueError loading data for {symbol} from {filepath}: {ve}")
            except Exception as e:
                logger.error(f"Generic error loading data for {symbol} from {filepath}: {e}", exc_info=True)

        if not individual_dfs:
            logger.warning("No data successfully loaded for any symbols.")
            self.combined_data = pd.DataFrame() # Empty DataFrame with Timestamp index if possible
            return

        # Combine into a single DataFrame with multi-index columns
        self.combined_data = pd.concat(
            {sym: df for sym, df in individual_dfs.items() if not df.empty}, # Filter out empty DFs
            axis=1,
            join='outer' # Keep all timestamps from all symbols
        )

        if self.combined_data.empty:
            logger.warning("Combined data is empty before sorting and ffill. This might happen if all symbol files were problematic.")
            return

        self.combined_data.index.name = 'Timestamp'
        self.combined_data = self.combined_data.sort_index() # Sort before date filtering

        # Apply date filtering
        if self.start_date:
            self.combined_data = self.combined_data[self.combined_data.index >= self.start_date]
        if self.end_date:
            # Ensure end_date is inclusive, so filter up to end of the day if only date is given
            # Or, if self.end_date already includes time, it will be used as is.
            # For simplicity, if end_date is just a date, this will include up to midnight of that date.
            # If specific end_time is needed, config should provide it.
            # To be strictly inclusive of the end_date itself (e.g. '2023-01-31' includes all data on that day):
            # self.combined_data = self.combined_data[self.combined_data.index <= (self.end_date + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1))]
            # Simpler: if end_date is '2023-01-31', it means up to '2023-01-31 00:00:00'.
            # If we want to include the whole day, the config should specify '2023-01-31 23:59:59' or similar.
            # For now, direct comparison:
            self.combined_data = self.combined_data[self.combined_data.index <= self.end_date]

        if self.combined_data.empty and (self.start_date or self.end_date):
            logger.warning(f"Data became empty after applying date filters: {self.start_date} to {self.end_date}")
            return # No further processing if empty

        if self.ffill:
            logger.info("Forward-filling missing data in combined DataFrame post date-filtering...")
            self.combined_data.fillna(method='ffill', inplace=True)

        # Drop rows at the beginning where all specified symbols might still be NaN for 'CLOSE'
        # This ensures we only start streaming when there's some usable data.
        if not self.combined_data.empty and self.symbols:
            close_columns_to_check = []
            for s in self.symbols:
                if (s, 'CLOSE') in self.combined_data.columns:
                    close_columns_to_check.append((s, 'CLOSE'))
                # else: # This symbol might not have loaded any data
                    # logger.debug(f"Symbol {s} not found in combined_data columns for dropna check, possibly due to load error.")

            if close_columns_to_check:
                self.combined_data.dropna(subset=close_columns_to_check, how='all', inplace=True)
            else:
                logger.warning("No 'CLOSE' columns found for any specified symbols in combined_data. Data might be unusable.")
                self.combined_data = pd.DataFrame() # Effectively empty


        if self.combined_data.empty:
            logger.warning("Combined data is empty after loading, processing, and NaN drop. No data to stream.")
        else:
            logger.info(f"Combined data prepared. Shape: {self.combined_data.shape}. Index from {self.combined_data.index.min()} to {self.combined_data.index.max()}")


    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        if self.combined_data is None or self.combined_data.empty or symbol not in self.symbols:
            return None
        try:
            # Ensure the multi-index column for the symbol exists
            if (symbol, 'CLOSE') not in self.combined_data.columns:
                # logger.debug(f"No data for symbol {symbol} in combined_data for get_latest_bar.")
                return None

            last_valid_idx = self.combined_data[(symbol, 'CLOSE')].last_valid_index()
            if last_valid_idx is None: # No valid 'CLOSE' data for this symbol
                return None

            # Access the multi-index column for the specific symbol
            last_symbol_data_series = self.combined_data.loc[last_valid_idx, symbol]

            bar_fields = {
                'OPEN': last_symbol_data_series.get('OPEN'),
                'HIGH': last_symbol_data_series.get('HIGH'),
                'LOW': last_symbol_data_series.get('LOW'),
                'CLOSE': last_symbol_data_series.get('CLOSE'),
                'VOLUME': last_symbol_data_series.get('VOLUME'),
            }
            # Check if critical data (like CLOSE) is NaN, which shouldn't happen if last_valid_index worked for CLOSE
            if pd.isna(bar_fields['CLOSE']):
                return None

            return MarketDataEvent(timestamp=last_valid_idx, symbol=symbol, data=bar_fields)
        except KeyError:
            logger.warning(f"KeyError in get_latest_bar for {symbol}. Symbol columns might not exist as expected.")
            return None
        except Exception as e:
            logger.error(f"Error in get_latest_bar for {symbol}: {e}", exc_info=True)
            return None

    def stream_next_bar(self) -> Generator[Dict[str, MarketDataEvent], None, None]:
        if self.combined_data is None or self.combined_data.empty:
            logger.warning("No combined data to stream in CsvDataHandler.")
            return # Yields an empty generator

        logger.info("Starting to stream bars from combined and processed data...")
        for timestamp, row_data in self.combined_data.iterrows():
            current_timestamp_events: Dict[str, MarketDataEvent] = {}
            for symbol_key in self.symbols: # Iterate over originally requested symbols
                try:
                    # Access symbol-specific data from the row using multi-index
                    # row_data is a Series with MultiIndex like (('AAPL', 'OPEN'), ('AAPL', 'HIGH'), ...)
                    # Accessing row_data[symbol_key] will give a Series for that symbol's columns
                    symbol_specific_data = row_data[symbol_key]

                    if not symbol_specific_data.isnull().all():
                        bar_fields = {
                            'OPEN': symbol_specific_data.get('OPEN'),
                            'HIGH': symbol_specific_data.get('HIGH'),
                            'LOW': symbol_specific_data.get('LOW'),
                            'CLOSE': symbol_specific_data.get('CLOSE'),
                            'VOLUME': symbol_specific_data.get('VOLUME'),
                        }

                        # Critical check: if 'CLOSE' is NaN after ffill and initial dropna, skip this symbol for this bar.
                        # This can happen if a symbol starts much later and ffill couldn't fill its initial NaNs.
                        if pd.isna(bar_fields['CLOSE']):
                            # logger.debug(f"Skipping {symbol_key} at {timestamp} due to NaN CLOSE price.")
                            continue

                        current_timestamp_events[symbol_key] = MarketDataEvent(
                            timestamp=timestamp,
                            symbol=symbol_key,
                            data=bar_fields
                        )
                except KeyError:
                    # This symbol might not be in combined_data.columns if its CSV was missing, empty, or all NaNs initially.
                    # logger.debug(f"No data columns for symbol {symbol_key} in combined_data at {timestamp}.")
                    pass

            if current_timestamp_events:
                yield timestamp, current_timestamp_events # Yield timestamp along with data bundle

        logger.info("CsvDataHandler: Finished streaming all bars.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Create dummy CSVs for testing, including some misalignments and missing data
    temp_data_dir = 'temp_csv_data_for_test'
    if not os.path.exists(temp_data_dir):
        os.makedirs(temp_data_dir)

    # AAPL Data - normal
    data_aapl = {
        'Timestamp': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-01 10:01:00', '2023-01-01 10:02:00', '2023-01-01 10:03:00']),
        'Open': [150.0, 150.1, 150.2, 150.5], 'High': [150.5, 150.6, 150.7, 150.8],
        'Low': [149.9, 150.0, 150.1, 150.2], 'Close': [150.1, 150.2, 150.3, 150.6],
        'Volume': [1000, 1100, 1200, 1050]
    }
    pd.DataFrame(data_aapl).to_csv(os.path.join(temp_data_dir, 'AAPL_data.csv'), index=False)

    # GOOG Data - starts one minute later, ends one minute earlier
    data_goog = {
        'Timestamp': pd.to_datetime(['2023-01-01 10:01:00', '2023-01-01 10:02:00']),
        'Open': [2501.0, 2502.0], 'High': [2506.0, 2507.0],
        'Low': [2500.0, 2501.0], 'Close': [2502.0, 2503.0],
        'Volume': [850, 900]
    }
    pd.DataFrame(data_goog).to_csv(os.path.join(temp_data_dir, 'GOOG_data.csv'), index=False)

    # MSFT Data - has a missing row in the middle
    data_msft = {
        'Timestamp': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-01 10:02:00', '2023-01-01 10:03:00']), # Missing 10:01
        'Open': [300.0, 300.2, 300.5], 'High': [300.5, 300.7, 300.9],
        'Low': [299.9, 300.1, 300.2], 'Close': [300.1, 300.3, 300.6],
        'Volume': [2000, 2200, 2050]
    }
    pd.DataFrame(data_msft).to_csv(os.path.join(temp_data_dir, 'MSFT_data.csv'), index=False)

    # FAKE symbol - to test missing file handling
    # No FAKE_data.csv will be created

    symbols_to_test = ['AAPL', 'GOOG', 'MSFT', 'FAKE']

    logger.info("\n--- Test Case 1: No date filtering ---")
    handler_no_filter = CsvDataHandler(csv_dir=temp_data_dir, symbols=symbols_to_test, ffill=True)
    print("\nStreaming bars (no filter - expecting all available from combined data):")
    bar_count_no_filter = 0
    for ts, event_bundle in handler_no_filter.stream_next_bar():
        bar_count_no_filter +=1
        # print(f"Timestamp: {ts}") # Can enable for verbose output
    print(f"Total timestamps streamed (no filter): {bar_count_no_filter}")
    # Expected: AAPL (4), GOOG (2 but ffilled to 4, then dropna might affect), MSFT (3 but ffilled to 4)
    # The dropna(how='all') for CLOSE columns means it should stream for the full range where any symbol has data.
    # After ffill, GOOG will have data from 10:00, MSFT will have data for 10:01.
    # So, all should effectively start from 10:00 if AAPL is present, and end at 10:03.
    # Expected timestamps: 10:00, 10:01, 10:02, 10:03. So, 4 timestamps.

    logger.info("\n--- Test Case 2: With start_date and end_date filtering ---")
    handler_with_filter = CsvDataHandler(csv_dir=temp_data_dir, symbols=symbols_to_test, ffill=True,
                                         start_date='2023-01-01 10:01:00', end_date='2023-01-01 10:02:00')
    print("\nStreaming bars (filtered '2023-01-01 10:01:00' to '2023-01-01 10:02:00'):")
    bar_count_filtered = 0
    for ts, timestamp_event_dict in handler_with_filter.stream_next_bar():
        bar_count_filtered += 1
        print(f"Timestamp: {ts}")
        for symbol, bar_event in timestamp_event_dict.items():
            print(f"  Symbol: {symbol}, Close: {bar_event.get('CLOSE')}")
    print(f"Total timestamps streamed (filtered): {bar_count_filtered}") # Expected: 10:01, 10:02. So, 2 timestamps.


    logger.info("\n--- Test Case 3: Filter resulting in no data ---")
    handler_empty_filter = CsvDataHandler(csv_dir=temp_data_dir, symbols=symbols_to_test, ffill=True,
                                         start_date='2024-01-01', end_date='2024-01-31')
    print("\nStreaming bars (filter '2024-01-01' to '2024-01-31' - expecting no data):")
    bar_count_empty = 0
    for _ in handler_empty_filter.stream_next_bar(): bar_count_empty +=1
    print(f"Total timestamps streamed (empty filter): {bar_count_empty}") # Expected: 0


    logger.info("Example finished. Manual cleanup of 'temp_csv_data_for_test' directory may be needed.")
