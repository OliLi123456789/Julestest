from .base_tool import BaseTool # BaseTool already imports logger
from typing import Any, Dict, List, Union # Union is not used, can be removed
import json
import random
import datetime
from loguru import logger # Explicit import for clarity, though BaseTool might make it available

# Custom mock exceptions
class InternalAPITimeoutError(Exception):
    """Simulates a timeout from the internal market data API."""
    pass

class SymbolNotFoundError(Exception):
    """Simulates an error when a symbol is not found by the internal API."""
    pass

class InvalidParameterError(Exception):
    """Simulates an error for invalid parameters passed to the internal API."""
    pass


class ChartDataTool(BaseTool):
    name: str = "get_chart_data"
    description: str = (
        "Retrieves historical market data to generate a chart for a given stock symbol, timeframe, and lookback period. "
        "Parameters: symbol (str, e.g., 'AAPL', 'MSFT'), "
        "timeframe (str, e.g., '1D', '1W', '1M'), "
        "lookback_period (str, e.g., '1M', '3M', '1Y', '5Y'). "
        "Returns a JSON string with chart data points or an error message."
    )

    parameter_schema: Dict[str, Dict[str, Any]] = {
        "symbol": {
            "type": "string",
            "description": "The stock symbol for which to retrieve chart data (e.g., 'AAPL', 'MSFT')."
        },
        "timeframe": {
            "type": "string",
            "description": "The timeframe for each data point of the chart.",
            "enum": ["1Min", "5Min", "15Min", "1H", "1D", "1W", "1M"]
        },
        "lookback_period": {
            "type": "string",
            "description": "The total duration for which to retrieve chart data (e.g., '1M' for one month, '1Y' for one year).",
            "enum": ["1D", "5D", "1M", "3M", "6M", "1Y", "2Y", "5Y", "YTD"]
        }
    }
    required_parameters: List[str] = ["symbol", "timeframe", "lookback_period"]


    async def _generate_mock_data_point(self, base_price: float, timestamp: datetime.datetime) -> Dict[str, Any]:
        """Generates a single mock data point."""
        open_price = round(base_price + random.uniform(-0.5, 0.5), 2)
        close_price = round(open_price + random.uniform(-0.5, 0.5), 2)
        high_price = round(max(open_price, close_price) + random.uniform(0, 0.3), 2)
        low_price = round(min(open_price, close_price) - random.uniform(0, 0.3), 2)
        volume = random.randint(100000, 5000000)
        return {
            "time": timestamp.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume
        }

    async def _fetch_market_data_from_internal_api(self, symbol: str, timeframe: str, lookback_period: str) -> Dict[str, Any]:
        """
        Simulates fetching data from an internal market data API.
        This function can return a predefined dictionary structure or raise a mock exception.
        """
        logger.debug(f"ChartDataTool: Attempting to fetch internal market data for symbol='{symbol}', timeframe='{timeframe}', lookback='{lookback_period}'",
                     symbol=symbol, timeframe=timeframe, lookback_period=lookback_period)

        # Parameter validation simulation (already defined in parameter_schema enums, but good for internal consistency)
        # For a real API, you might re-validate or trust the schema validation by the LLM
        if timeframe not in self.parameter_schema["timeframe"]["enum"]:
            raise InvalidParameterError(f"Invalid timeframe: {timeframe}. Valid options are: {', '.join(self.parameter_schema['timeframe']['enum'])}")
        if lookback_period not in self.parameter_schema["lookback_period"]["enum"]:
            raise InvalidParameterError(f"Invalid lookback_period: {lookback_period}. Valid options are: {', '.join(self.parameter_schema['lookback_period']['enum'])}")


        # Simulate API errors based on symbol
        if symbol.upper() == "TIMEOUT":
            raise InternalAPITimeoutError("Internal market data API timed out.")
        if symbol.upper() == "NOTFOUND":
            raise SymbolNotFoundError(f"Symbol '{symbol}' not found in the market data system.")
        if symbol.upper() == "ERROR": # Generic error
            raise Exception("An unexpected internal API error occurred.")

        # Simulate successful data fetching
        num_data_points = 0
        time_delta = datetime.timedelta()
        base_price = random.uniform(50, 500) # Base price for the stock

        if timeframe == "1D": time_delta = datetime.timedelta(days=1); num_data_points = 30 if lookback_period == "1M" else 90 if lookback_period == "3M" else 252 if lookback_period == "1Y" else 252*5
        elif timeframe == "1W": time_delta = datetime.timedelta(weeks=1); num_data_points = 12 if lookback_period == "3M" else 52 if lookback_period == "1Y" else 52*5
        elif timeframe == "1M": time_delta = datetime.timedelta(days=30); num_data_points = 6 if lookback_period == "6M" else 12 if lookback_period == "1Y" else 24
        else: # Default to daily for simplicity in mock
            time_delta = datetime.timedelta(days=1); num_data_points = 30

        # Ensure num_data_points is reasonable for mock
        num_data_points = min(num_data_points, 50) # Limit mock data points to avoid overly large JSON strings

        data_points: List[Dict[str, Any]] = []
        current_time = datetime.datetime.now(datetime.timezone.utc) - (num_data_points * time_delta)

        for _ in range(num_data_points):
            # _generate_mock_data_point is async but doesn't do real I/O, direct await is fine.
            data_points.append(await self._generate_mock_data_point(base_price, current_time))
            base_price = data_points[-1]["close"] # Next price fluctuates around previous close
            current_time += time_delta

        logger.debug(f"ChartDataTool: Successfully fetched {len(data_points)} mock data points for {symbol}",
                     symbol=symbol, num_points=len(data_points))
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "lookback_period": lookback_period,
            "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "data_points": data_points,
            "notes": "This is mock data generated by ChartDataTool._fetch_market_data_from_internal_api"
        }

    async def execute(self, symbol: str, timeframe: str = "1D", lookback_period: str = "1Y", **kwargs: Any) -> str:
        """
        Queries an internal market data system to fetch data suitable for generating a chart.
        Formats the data as a JSON string or returns an error message.
        This method is now async to allow for non-blocking I/O if the internal API call were real.
        """
        # Using logger with structured logging for key parameters
        logger.info(f"ChartDataTool: Async Execute.",
                    symbol=symbol, timeframe=timeframe, lookback_period=lookback_period, kwargs=kwargs)

        # Parameters from function calling will be passed as direct arguments by name.
        # If called via old keyword method, they might be in kwargs or direct.
        # For consistency, we can extract them if they are in kwargs (though Gemini direct call won't use kwargs for defined params)
        _symbol = kwargs.get('symbol', symbol)
        _timeframe = kwargs.get('timeframe', timeframe)
        _lookback_period = kwargs.get('lookback_period', lookback_period)

        try:
            # 1. Validate parameters
            if not _symbol: # Should be caught by 'required' in schema, but good to double check
                return "Error: Stock symbol must be provided."
            # Timeframe and lookback_period are validated by schema enums if called by Gemini.
            # If called manually or by old method, internal API mock will validate.

            # 2. Fetch data using the internal (mocked) client
            # In a real async implementation, this call would be awaited if it performed actual I/O.
            # For this mock, the internal method is also marked async for structural consistency,
            # but it doesn't perform real async I/O.
            chart_data = await self._fetch_market_data_from_internal_api(_symbol, _timeframe, _lookback_period)

            # 3. Format data as JSON string
            # In a real scenario, we might return a more complex object or a specific chart ID.
            # For LLM consumption, JSON is often a good choice.
            logger.debug(f"ChartDataTool: Successfully processed data for symbol '{_symbol}'. Returning JSON string.", symbol=_symbol)
            return json.dumps(chart_data, indent=2)

        except InvalidParameterError as e:
            logger.warning(f"ChartDataTool: Invalid parameter error for symbol='{_symbol}'. Error: {e}", symbol=_symbol, error=str(e))
            return f"Error: Invalid parameters for chart data. {str(e)}"
        except SymbolNotFoundError as e:
            logger.warning(f"ChartDataTool: Symbol not found error for symbol='{_symbol}'. Error: {e}", symbol=_symbol, error=str(e))
            return f"Error: Could not retrieve chart data. Symbol '{_symbol}' not found."
        except InternalAPITimeoutError as e:
            logger.error(f"ChartDataTool: API timeout error for symbol='{_symbol}'. Error: {e}", symbol=_symbol, error=str(e))
            return f"Error: Could not retrieve chart data for '{_symbol}'. The data service timed out."
        except Exception as e:
            logger.exception(f"ChartDataTool: An unexpected error occurred for symbol='{_symbol}'. Error: {e}", symbol=_symbol)
            return f"Error: An unexpected issue occurred while fetching chart data for '{_symbol}'. Details: {str(e)}"

if __name__ == '__main__':
    # Basic Loguru setup for testing this module directly
    import sys
    logger.remove() # Remove default handler
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message} | {extra}")

    tool = ChartDataTool()
    logger.info(f"Tool Name: {tool.name}")
    logger.info(f"Tool Description: {tool.description}")

    import asyncio

    async def main():
        tool_instance = ChartDataTool() # Create instance inside async main for clarity
        logger.info(f"Tool Name (async test): {tool_instance.name}")
        logger.info(f"Tool Description (async test): {tool_instance.description}")

        logger.info("\n--- Gemini Function Declaration Schema ---")
        gemini_schema = tool_instance.get_description_for_llm()
        logger.info(f"Schema: {json.dumps(gemini_schema, indent=2)}")


        logger.info("\n--- Test Case 1: Successful Fetch (AAPL) ---")
        output_aapl = await tool_instance.execute(symbol="AAPL", timeframe="1D", lookback_period="1M")
        logger.info(f"Output (AAPL):\n{output_aapl}\n")

        logger.info("\n--- Test Case 2: Symbol Not Found (NOTFOUND) ---")
        output_notfound = await tool_instance.execute(symbol="NOTFOUND", timeframe="1D", lookback_period="1M")
        logger.info(f"Output (NOTFOUND):\n{output_notfound}\n")

        logger.info("\n--- Test Case 3: API Timeout (TIMEOUT) ---")
        output_timeout = await tool_instance.execute(symbol="TIMEOUT", timeframe="1W", lookback_period="3M")
        logger.info(f"Output (TIMEOUT):\n{output_timeout}\n")

        logger.info("\n--- Test Case 4: Invalid Timeframe (via direct call, Gemini would use enum) ---")
        output_invalid_tf = await tool_instance.execute(symbol="MSFT", timeframe="BADTF", lookback_period="1M")
        logger.info(f"Output (Invalid TF):\n{output_invalid_tf}\n")

        logger.info("\n--- Test Case 5: Missing Symbol (should be caught by schema if from Gemini) ---")
        output_missing_symbol = await tool_instance.execute(symbol="", timeframe="1D", lookback_period="1M")
        logger.info(f"Output (Missing Symbol):\n{output_missing_symbol}\n")

        logger.info("\n--- Test Case 6: Generic Error (ERROR) ---")
        output_error_symbol = await tool_instance.execute(symbol="ERROR", timeframe="1D", lookback_period="1M")
        logger.info(f"Output (Error Symbol):\n{output_error_symbol}\n")

    if __name__ == '__main__':
        asyncio.run(main())
