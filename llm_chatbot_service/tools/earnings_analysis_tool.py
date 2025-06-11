from .base_tool import BaseTool
from typing import Any, Dict, List # Added List for required_parameters
import json
import random
import datetime
from loguru import logger # Import Loguru

# Custom mock exceptions
class InternalEarningsServiceError(Exception):
    """Simulates a generic error from the internal earnings data service."""
    pass

class NoEarningsDataFoundError(Exception):
    """Simulates an error when no earnings data is found for a given symbol or event type."""
    pass

class InvalidEarningsSymbolError(Exception):
    """Simulates an error for an invalid or unsupported symbol for earnings."""
    pass


class EarningsAnalysisTool(BaseTool):
    name: str = "get_earnings_data"
    description: str = (
        "Retrieves past or upcoming earnings information for a given stock symbol. "
        "Parameters: symbol (str, e.g., 'AAPL', 'MSFT'), event_type (str, must be 'upcoming' or 'historical'). "
        "Returns a JSON string with earnings data or an error message."
    )

    parameter_schema: Dict[str, Dict[str, Any]] = {
        "symbol": {
            "type": "string",
            "description": "The stock symbol for which to retrieve earnings data (e.g., 'AAPL', 'MSFT')."
        },
        "event_type": {
            "type": "string",
            "description": "The type of earnings event to retrieve data for. Must be 'upcoming' or 'historical'.",
            "enum": ["upcoming", "historical"]
        }
    }
    required_parameters: List[str] = ["symbol", "event_type"] # Type List needs to be imported from typing

    async def _generate_mock_upcoming_earnings(self, symbol: str) -> Dict[str, Any]:
        days_ahead = random.randint(1, 90)
        event_date = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        return {
            "symbol": symbol.upper(),
            "event_type": "upcoming",
            "date": event_date,
            "time_of_day": random.choice(["Before Market Open", "After Market Close", "During Market Hours"]),
            "eps_estimate": f"${round(random.uniform(0.50, 5.00), 2)}",
            "revenue_estimate": f"${round(random.uniform(1, 20), 1)}B",
            "conference_call_scheduled": random.choice([True, False]),
            "notes": "This is mock data for upcoming earnings."
        }

    async def _generate_mock_historical_earnings(self, symbol: str) -> Dict[str, Any]:
        days_ago = random.randint(10, 90) # Last quarter's earnings
        event_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)).strftime('%Y-%m-%d')
        eps_actual = round(random.uniform(0.40, 5.50), 2)
        eps_estimate = round(eps_actual + random.uniform(-0.20, 0.20), 2) # Estimate can be higher or lower
        surprise_pct = round(((eps_actual - eps_estimate) / abs(eps_estimate) if abs(eps_estimate) > 0 else 0) * 100, 2) if eps_estimate else 0

        return {
            "symbol": symbol.upper(),
            "event_type": "historical",
            "date": event_date,
            "quarter": f"Q{ (datetime.datetime.strptime(event_date, '%Y-%m-%d').month -1) // 3 + 1 } {datetime.datetime.strptime(event_date, '%Y-%m-%d').year}",
            "eps_actual": f"${eps_actual}",
            "eps_estimate": f"${eps_estimate}",
            "eps_surprise_pct": f"{surprise_pct}%",
            "revenue_actual": f"${round(random.uniform(0.8, 22), 1)}B",
            "revenue_estimate": f"${round(random.uniform(0.7, 21), 1)}B",
            "notes": "This is mock data for historical earnings."
        }

    async def _fetch_earnings_data_from_internal_api(self, symbol: str, event_type: str) -> Dict[str, Any]:
        """
        Simulates fetching earnings data from an internal API.
        """
        logger.debug(f"EarningsAnalysisTool: Attempting to fetch earnings from internal API.",
                     symbol=symbol, event_type=event_type)

        if symbol.upper() == "SERVICE_ERROR":
            raise InternalEarningsServiceError("The internal earnings data service is experiencing issues.")
        if symbol.upper() == "NO_DATA":
            raise NoEarningsDataFoundError(f"No {event_type} earnings data found for symbol '{symbol}'.")
        if not symbol.isalpha() or len(symbol) > 5 : # Simple mock validation
             raise InvalidEarningsSymbolError(f"Symbol '{symbol}' appears invalid for earnings lookup.")

        if event_type == "upcoming":
            data = await self._generate_mock_upcoming_earnings(symbol) # await if these were true async
        elif event_type == "historical":
            data = await self._generate_mock_historical_earnings(symbol) # await if these were true async
        else:
            # This case should ideally be caught by prior validation in execute()
            # but as a safeguard in the internal API mock:
            raise ValueError(f"Internal API error: Invalid event_type '{event_type}' specified.") # This should remain ValueError

        logger.debug(f"EarningsAnalysisTool: Successfully fetched mock {event_type} earnings for {symbol}",
                     symbol=symbol, event_type=event_type)
        return data

    async def execute(self, symbol: str, event_type: str = "upcoming", **kwargs: Any) -> str:
        """
        Queries an internal earnings data service for past or upcoming earnings.
        Formats the data as a JSON string or returns an error message.
        This method is now async.
        """
        logger.info(f"EarningsAnalysisTool: Async Execute.",
                    symbol=symbol, event_type=event_type, kwargs=kwargs)

        _symbol = kwargs.get('symbol', symbol)
        _event_type = kwargs.get('event_type', event_type)

        try:
            if not _symbol: # Should be caught by 'required' in schema
                return "Error: A stock symbol must be provided."

            _event_type_lower = _event_type.lower()
            if _event_type_lower not in self.parameter_schema["event_type"]["enum"]: # Validate against schema enum
                return "Error: Invalid event_type. Must be 'upcoming' or 'historical'."

            earnings_data = await self._fetch_earnings_data_from_internal_api(_symbol, _event_type_lower)

            logger.debug(f"EarningsAnalysisTool: Successfully processed {_event_type_lower} earnings data for '{_symbol}'. Returning JSON string.",
                         symbol=_symbol, event_type=_event_type_lower)
            return json.dumps(earnings_data, indent=2)

        except InvalidEarningsSymbolError as e:
            logger.warning(f"EarningsAnalysisTool: Invalid symbol error for symbol='{_symbol}'. Error: {e}", symbol=_symbol, error=str(e))
            return f"Error: Invalid symbol for earnings data. {str(e)}"
        except NoEarningsDataFoundError as e:
            logger.warning(f"EarningsAnalysisTool: No earnings data found for symbol='{_symbol}', event_type='{_event_type_lower}'. Error: {e}",
                           symbol=_symbol, event_type=_event_type_lower, error=str(e))
            return f"Error: No {_event_type_lower} earnings data found for '{_symbol}'."
        except InternalEarningsServiceError as e:
            logger.error(f"EarningsAnalysisTool: Internal service error for symbol='{_symbol}'. Error: {e}", symbol=_symbol, error=str(e))
            return f"Error: Could not retrieve earnings data for '{_symbol}'. The data service reported an error: {str(e)}"
        except Exception as e:
            logger.exception(f"EarningsAnalysisTool: An unexpected error occurred for symbol='{_symbol}'. Error: {e}", symbol=_symbol)
            return f"Error: An unexpected issue occurred while fetching earnings data for '{_symbol}'. Details: {str(e)}"

if __name__ == '__main__':
    # Basic Loguru setup for testing this module directly
    import sys
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message} | {extra}")

    tool = EarningsAnalysisTool() # For top-level name/desc
    logger.info(f"Tool Name: {tool.name}")
    logger.info(f"Tool Description: {tool.description}")

    import asyncio
    # from typing import List # This was for the required_parameters, already imported at top level

    async def main():
        tool_instance = EarningsAnalysisTool() # Instance for async tests
        logger.info(f"Tool Name (async test): {tool_instance.name}")
        logger.info(f"Tool Description (async test): {tool_instance.description}")

        logger.info("\n--- Gemini Function Declaration Schema ---")
        gemini_schema = tool_instance.get_description_for_llm()
        logger.info(f"Schema: {json.dumps(gemini_schema, indent=2)}")

        logger.info("\n--- Test Case 1: Successful Upcoming Earnings (AAPL) ---")
        output_upcoming_aapl = await tool_instance.execute(symbol="AAPL", event_type="upcoming")
        logger.info(f"Output (Upcoming AAPL):\n{output_upcoming_aapl}\n")

        logger.info("\n--- Test Case 2: Successful Historical Earnings (MSFT) ---")
        output_historical_msft = await tool_instance.execute(symbol="MSFT", event_type="historical")
        logger.info(f"Output (Historical MSFT):\n{output_historical_msft}\n")

        logger.info("\n--- Test Case 3: No Earnings Data (NO_DATA symbol) ---")
        output_no_data = await tool_instance.execute(symbol="NO_DATA", event_type="upcoming")
        logger.info(f"Output (No Data):\n{output_no_data}\n")

        logger.info("\n--- Test Case 4: Service Error (SERVICE_ERROR symbol) ---")
        output_service_error = await tool_instance.execute(symbol="SERVICE_ERROR", event_type="historical")
        logger.info(f"Output (Service Error):\n{output_service_error}\n")

        logger.info("\n--- Test Case 5: Invalid Symbol (123INVALID) ---")
        output_invalid_symbol = await tool_instance.execute(symbol="123INVALID", event_type="upcoming")
        logger.info(f"Output (Invalid Symbol):\n{output_invalid_symbol}\n")

        logger.info("\n--- Test Case 6: Invalid Event Type (past_performance) ---")
        output_invalid_event = await tool_instance.execute(symbol="GOOG", event_type="past_performance")
        logger.info(f"Output (Invalid Event Type):\n{output_invalid_event}\n")

        logger.info("\n--- Test Case 7: Missing Symbol ---")
        output_missing_symbol = await tool_instance.execute(symbol="", event_type="upcoming")
        logger.info(f"Output (Missing Symbol):\n{output_missing_symbol}\n")

    if __name__ == '__main__':
        asyncio.run(main())
