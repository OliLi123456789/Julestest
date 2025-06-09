import pandas as pd
from abc import ABC, abstractmethod
from typing import Generator, Dict, Optional

class MarketDataEvent:
    """
    Represents a new bar of market data.
    """
    def __init__(self, timestamp, symbol: str, data: Dict[str, float]):
        self.type = 'MARKET_DATA'
        self.timestamp = timestamp
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
    def stream_next_bar(self) -> Generator[MarketDataEvent, None, None]:
        """Generator that yields the next bar of data for all symbols."""
        raise NotImplementedError

class CsvDataHandler(AbstractDataHandler):
    """
    Reads historical data for multiple symbols from CSV files.
    Assumes CSV files are named like '{symbol}_data.csv'.
    Each CSV should have: Timestamp, Open, High, Low, Close, Volume
    """
    def __init__(self, csv_dir: str, symbols: list[str]):
        self.csv_dir = csv_dir
        self.symbols = symbols
        self.symbol_data = {}
        self.symbol_iterators = {}
        self._load_data()

    def _load_data(self):
        print(f"Loading data for symbols: {self.symbols} from {self.csv_dir}")
        for symbol in self.symbols:
            try:
                filepath = f"{self.csv_dir}/{symbol}_data.csv"
                df = pd.read_csv(filepath, parse_dates=['Timestamp'], index_col='Timestamp')
                # Ensure standard column names, case-insensitive loading
                df.columns = [col.upper() for col in df.columns]
                required_cols = {'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'}
                if not required_cols.issubset(df.columns):
                    raise ValueError(f"CSV for {symbol} missing one of required columns: {required_cols}")

                self.symbol_data[symbol] = df.sort_index() # Sort by timestamp
                self.symbol_iterators[symbol] = self.symbol_data[symbol].iterrows()
                print(f"Successfully loaded data for {symbol}: {len(df)} rows.")
            except FileNotFoundError:
                print(f"Error: Data file for {symbol} not found at {filepath}")
                raise
            except Exception as e:
                print(f"Error loading data for {symbol}: {e}")
                raise

        # For simplicity in this PoC, we'll assume all CSVs have aligned timestamps.
        # A more robust handler would need to merge and forward-fill data for multiple symbols
        # or provide data on a per-symbol basis and let the engine handle time synchronization.
        # For this PoC, stream_next_bar will yield one bar from each symbol's CSV per "tick"
        # assuming they are perfectly aligned. This is a simplification.

    def get_latest_bar(self, symbol: str) -> Optional[MarketDataEvent]:
        # This method is less relevant for a historical backtest that streams data,
        # but could be useful if the data handler was for live data.
        # For historical, it might return the "current" bar in the simulation.
        # This implementation is a placeholder or needs context of current simulation time.
        if symbol in self.symbol_data and not self.symbol_data[symbol].empty:
            # This is not really "latest" in a streaming context, but the last known.
            # In a true backtest stream, "latest" would be the current bar.
            # Let's assume it means the current bar from the iterator if available.
            # This method needs refinement based on how it's used by the engine.
            # For now, let's make it return the *last actual data point from the CSV*.
            last_row = self.symbol_data[symbol].iloc[-1]
            return MarketDataEvent(timestamp=last_row.name, symbol=symbol, data=last_row.to_dict())
        return None

    def stream_next_bar(self) -> Generator[MarketDataEvent, None, None]:
        """
        Yields the next bar of data for each symbol in sequence based on the CSVs.
        This simplified version assumes that for each timestamp, all symbol CSVs have an entry.
        It iterates through the first symbol's timestamps and attempts to get corresponding
        data for other symbols at that same timestamp.
        A more robust version would handle misaligned timestamps.
        """
        if not self.symbols:
            return

        # Use the first symbol's iterator to drive the timeline
        first_symbol = self.symbols[0]
        for timestamp, row in self.symbol_iterators[first_symbol]:
            # Yield data for the first symbol
            yield MarketDataEvent(timestamp=timestamp, symbol=first_symbol, data=row.to_dict())

            # For other symbols, try to get data at the same timestamp
            # This is a simplification: assumes perfect alignment or requires more complex logic
            for other_symbol in self.symbols[1:]:
                if other_symbol in self.symbol_data:
                    try:
                        # Try to get the row for the current timestamp
                        other_row = self.symbol_data[other_symbol].loc[timestamp]
                        yield MarketDataEvent(timestamp=timestamp, symbol=other_symbol, data=other_row.to_dict())
                    except KeyError:
                        # Handle cases where a symbol might not have data for this specific timestamp
                        # For PoC, we might skip or yield a special event. Here, we just print.
                        # print(f"Warning: No data for {other_symbol} at {timestamp}")
                        # Or, one could implement forward-filling logic here if desired.
                        pass # This means this symbol won't produce a bar for this "tick" if data is missing

        print("Data stream finished.")


if __name__ == '__main__':
    # Example Usage (Create dummy CSVs for this to run)
    # Create dummy CSVs
    dummy_data_aapl = {
        'Timestamp': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-01 10:01:00', '2023-01-01 10:02:00']),
        'Open': [150.0, 150.1, 150.2],
        'High': [150.5, 150.6, 150.7],
        'Low': [149.9, 150.0, 150.1],
        'Close': [150.1, 150.2, 150.3],
        'Volume': [1000, 1100, 1200]
    }
    df_aapl = pd.DataFrame(dummy_data_aapl)

    dummy_data_goog = {
        'Timestamp': pd.to_datetime(['2023-01-01 10:00:00', '2023-01-01 10:01:00', '2023-01-01 10:02:00']),
        'Open': [2500.0, 2501.0, 2502.0],
        'High': [2505.0, 2506.0, 2507.0],
        'Low': [2499.0, 2500.0, 2501.0],
        'Close': [2501.0, 2502.0, 2503.0],
        'Volume': [800, 850, 900]
    }
    df_goog = pd.DataFrame(dummy_data_goog)

    import os
    if not os.path.exists('temp_data'):
        os.makedirs('temp_data')
    df_aapl.to_csv('temp_data/AAPL_data.csv', index=False) # Save Timestamp as a column
    df_goog.to_csv('temp_data/GOOG_data.csv', index=False) # Save Timestamp as a column

    # Re-read with Timestamp as index
    handler = CsvDataHandler(csv_dir='temp_data', symbols=['AAPL', 'GOOG'])

    print("\nStreaming bars:")
    for bar_event in handler.stream_next_bar():
        print(f"Event: {bar_event.type}, Time: {bar_event.timestamp}, Symbol: {bar_event.symbol}, Close: {bar_event.get('CLOSE')}")

    # Clean up dummy files
    # os.remove('temp_data/AAPL_data.csv')
    # os.remove('temp_data/GOOG_data.csv')
    # os.rmdir('temp_data')
    print("Example finished.")
