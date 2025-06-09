import datetime
from typing import List, Dict, Optional

from backtester.data import AbstractDataHandler, MarketDataEvent
from backtester.strategy import AbstractStrategy, SignalEvent
from backtester.portfolio import Portfolio, OrderEvent, FillEvent
from backtester.performance import PerformanceCalculator

class BacktestEngine:
    """
    Orchestrates the backtesting process.
    """
    def __init__(self, data_handler: AbstractDataHandler, strategy: AbstractStrategy, portfolio: Portfolio, performance_calculator_class=PerformanceCalculator):
        self.data_handler = data_handler
        self.strategy = strategy
        self.portfolio = portfolio
        self.performance_calculator_class = performance_calculator_class

        self.events_queue: List[MarketDataEvent | SignalEvent | OrderEvent | FillEvent] = [] # Simple list as a queue for PoC
        self.current_market_data: Dict[str, MarketDataEvent] = {} # Stores the latest bar for each symbol for current loop iteration

    def _process_market_data_event(self, event: MarketDataEvent):
        """Handles a market data event."""
        if event.type != 'MARKET_DATA':
            return

        # Update current market state (used by portfolio for MTM and execution)
        self.current_market_data[event.symbol] = event

        # Let strategy process the bar
        # print(f"Engine: Strategy processing {event.symbol} bar for {event.timestamp}...")
        new_signals = self.strategy.calculate_signals(event)
        for signal in new_signals:
            self.events_queue.append(signal) # Add signal to queue

    def _process_signal_event(self, event: SignalEvent):
        """Handles a signal event by passing it to the portfolio."""
        if event.type != 'SIGNAL':
            return
        # print(f"Engine: Portfolio processing signal for {event.symbol} at {event.timestamp}...")
        order = self.portfolio.process_signal(event)
        if order:
            self.events_queue.append(order) # Add order to queue

    def _process_order_event(self, event: OrderEvent):
        """Handles an order event by simulating execution."""
        # This is where an ExecutionHandler would typically come in.
        # For PoC, Portfolio handles simulation directly, using current bar's data.
        # The crucial assumption is that the order generated from bar N's data
        # is executed using bar N+1's data (represented by current_market_data here,
        # assuming current_market_data is the "next" bar after signal generation).
        # This means the order execution simulation must happen *after* all market data for the current timestamp
        # has been processed by the strategy, and *before* the portfolio's MTM for this timestamp.
        # This is a common source of lookahead bias if not handled carefully.
        # For simplicity, we'll assume an order generated based on data up to T,
        # is executed at prices available at T (e.g. T's close or T+1's open).
        # Our portfolio.simulate_order_execution uses the OPEN of the *current* bar.
        # So, a signal from bar K, processed, order created.
        # Next bar K+1 arrives. Market data for K+1. Strategy runs on K+1.
        # Then, order from K is attempted to be filled using K+1 OPEN.
        if event.type != 'ORDER':
            return

        market_event_for_execution = self.current_market_data.get(event.symbol)
        if not market_event_for_execution:
            print(f"Engine: No market data for {event.symbol} to execute order. Order: {event.order_id if hasattr(event, 'order_id') else 'N/A'}")
            return

        # print(f"Engine: Simulating execution for order {event.symbol} using market data from {market_event_for_execution.timestamp}...")
        fill = self.portfolio.simulate_order_execution(event, market_event_for_execution)
        if fill:
            self.events_queue.append(fill)

    def _process_fill_event(self, event: FillEvent):
        """Handles a fill event by updating the portfolio."""
        if event.type != 'FILL':
            return
        # print(f"Engine: Portfolio processing fill for {event.symbol} at {event.timestamp}...")
        self.portfolio.process_fill(event)


    def run_backtest(self):
        print("Engine: Starting backtest...")

        # Main event loop
        for market_event in self.data_handler.stream_next_bar():
            # 1. Add market event to queue
            self.events_queue.append(market_event)

            # Store the latest market data for the current timestamp for all symbols
            # This is important because the data handler streams one symbol bar at a time.
            # We need to collect all market data for a given timestamp before processing signals/orders for that timestamp.
            # This PoC assumes CsvDataHandler yields all symbol data for one timestamp before moving to the next.
            # A more robust engine would handle this grouping explicitly.
            # For now, current_market_data gets updated iteratively by _process_market_data_event

            current_loop_timestamp = market_event.timestamp # Assuming this is consistent for a "tick"

            # Process all events in the queue
            # This loop processes events generated from previous bars and the current bar's market data.
            # Order of processing matters: Market -> Strategy (Signal) -> Portfolio (Order) -> Execution (Fill) -> Portfolio Update

            # Temporary queue for events generated in this iteration, to avoid modifying queue while iterating
            newly_generated_events = []

            # Process market data first for the current bar. This might generate signals.
            idx = 0
            while idx < len(self.events_queue):
                event = self.events_queue[idx]
                if event.type == 'MARKET_DATA':
                    # Update current market data view
                    self.current_market_data[event.symbol] = event
                    # Strategy processes this market bar
                    # print(f"Engine: Strategy processing {event.symbol} bar for {event.timestamp}...")
                    new_signals = self.strategy.calculate_signals(event)
                    newly_generated_events.extend(new_signals)
                idx += 1

            # Add newly generated signals to the main queue
            self.events_queue.extend(newly_generated_events)
            newly_generated_events.clear() # Reset for next type of event processing

            # Process signals (generated from current or previous bars)
            idx = 0
            while idx < len(self.events_queue):
                event = self.events_queue[idx]
                if event.type == 'SIGNAL':
                    # print(f"Engine: Portfolio processing signal for {event.symbol} at {event.timestamp}...")
                    order = self.portfolio.process_signal(event)
                    if order:
                        newly_generated_events.append(order)
                idx += 1
            self.events_queue.extend(newly_generated_events)
            newly_generated_events.clear()

            # Process orders (generated from current or previous signals)
            # These orders are candidates for execution using the *current* market data (e.g. current bar's open)
            idx = 0
            while idx < len(self.events_queue):
                event = self.events_queue[idx]
                if event.type == 'ORDER':
                    market_event_for_exec = self.current_market_data.get(event.symbol)
                    if market_event_for_exec:
                        # print(f"Engine: Simulating execution for order {event.symbol} using market data from {market_event_for_exec.timestamp}...")
                        fill = self.portfolio.simulate_order_execution(event, market_event_for_exec)
                        if fill:
                            newly_generated_events.append(fill)
                    else:
                        # print(f"Engine: No current market data for {event.symbol} to execute order. Order deferred or failed.")
                        pass # Order might be processed on a later bar if data arrives
                idx += 1
            self.events_queue.extend(newly_generated_events)
            newly_generated_events.clear()

            # Process fills (generated from current bar's executions)
            idx = 0
            while idx < len(self.events_queue):
                event = self.events_queue[idx]
                if event.type == 'FILL':
                    # print(f"Engine: Portfolio processing fill for {event.symbol} at {event.timestamp}...")
                    self.portfolio.process_fill(event)
                idx += 1

            # Clear processed events (market, signal, order, fill) from the queue.
            # Keep only events that couldn't be processed (e.g. orders waiting for data).
            # For PoC, we assume all events for a timestamp are processed or discarded if not possible.
            self.events_queue = [e for e in self.events_queue if e.type not in ['MARKET_DATA', 'SIGNAL', 'ORDER', 'FILL'] or \
                                (e.type == 'ORDER' and e.status == 'PENDING')] # Keep pending orders for retry

            # After all events for this "bar" (timestamp) are processed, update portfolio MTM
            # It's important that current_market_data reflects the state of the market *at* current_loop_timestamp
            # for all relevant symbols.
            # This is a simplification. A more robust system would ensure all symbols for a timestamp are collected
            # before this step.
            self.portfolio.update_timeindex(current_loop_timestamp, self.current_market_data)
            # print(f"Engine: Portfolio MTM updated for {current_loop_timestamp}")

        print("Engine: Backtest event loop finished.")

        # Final portfolio update for the very last timestamp
        if self.current_market_data:
             # Assuming current_loop_timestamp holds the last processed timestamp
             self.portfolio.update_timeindex(current_loop_timestamp, self.current_market_data)

        print("Engine: Calculating performance metrics...")
        calculator = self.performance_calculator_class(
            portfolio_value_history=self.portfolio.portfolio_value_over_time,
            trades=self.portfolio.trades,
            initial_capital=self.portfolio.initial_cash
        )
        metrics = calculator.calculate_metrics()
        calculator.display_metrics()

        print("Engine: Backtest complete.")
        return metrics

if __name__ == '__main__':
    # --- PoC Basic Implementation ---
    # 1. Create dummy CSV data
    import pandas as pd
    import os
    import numpy as np # Moved import numpy here

    if not os.path.exists('temp_bt_data'):
        os.makedirs('temp_bt_data')

    # Single symbol for simplicity in PoC engine test
    symbol = 'TESTSYM'
    timestamps = pd.to_datetime([f'2023-01-01 10:{i:02d}:00' for i in range(60)]) # 60 minutes of data
    data = {
        'Timestamp': timestamps,
        'Open': [100 + i*0.1 + np.random.normal(0,0.1) for i in range(60)],
        'High': [100 + i*0.1 + 0.5 + np.random.normal(0,0.1) for i in range(60)],
        'Low': [100 + i*0.1 - 0.5 + np.random.normal(0,0.1) for i in range(60)],
        'Close': [100 + i*0.1 + (np.random.rand()-0.5)*0.2 for i in range(60)],
        'Volume': [1000 + np.random.randint(0,100) for i in range(60)]
    }
    df_sym = pd.DataFrame(data)
    df_sym.to_csv(f'temp_bt_data/{symbol}_data.csv', index=False)
    print(f"Dummy CSV data created for {symbol} in temp_bt_data/")

    # 2. Setup components
    from backtester.data import CsvDataHandler
    from backtester.strategy import BuyAndHoldStrategy
    from backtester.portfolio import Portfolio

    data_handler = CsvDataHandler(csv_dir='temp_bt_data', symbols=[symbol])
    # BuyAndHoldStrategy buys on the first bar it sees for a symbol.
    strategy = BuyAndHoldStrategy(symbols=[symbol], initial_quantity=10)
    portfolio = Portfolio(initial_cash=100000.0, data_handler=data_handler) # Portfolio needs data_handler for MTM prices (not used in PoC)

    # 3. Run engine
    engine = BacktestEngine(data_handler, strategy, portfolio)
    results = engine.run_backtest()

    # Clean up dummy data (optional)
    # os.remove(f'temp_bt_data/{symbol}_data.csv')
    # os.rmdir('temp_bt_data')

    # For the example to run:
    # Needs numpy: pip install numpy
    # Run from parent directory: python -m backtester.engine
    # try: # Removed the try-except for numpy import as it's now at the top of __main__
        # import numpy as np # For dummy data generation
    # except ImportError:
        # print("Please install numpy to run this example: pip install numpy")
