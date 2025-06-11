from .base_tool import BaseTool
from typing import Any, Dict, List, Optional # Added Dict, List, Optional
import httpx # Added
import logging # Added
import datetime # Added
# Import config from the llm_chatbot_service package level
from ..config_llm import llm_service_config # Adjusted import path

# Setup logger for this tool
logger = logging.getLogger(f"LLMChatbotService.tools.{__name__}")


class EarningsAnalysisTool(BaseTool):
    name: str = "get_earnings_data"
    description: str = (
        "Retrieves past (historical) or future (upcoming) earnings calendar information for a given stock symbol, or a general upcoming calendar. "
        "Parameters: symbol (str, optional for upcoming calendar, required for historical), "
        "event_type (str, 'upcoming' or 'historical', default 'upcoming'), "
        "limit (int, optional, for historical, default 4)."
    )

    async def execute(self, symbol: Optional[str] = None, event_type: str = "upcoming", limit: int = 4, **kwargs: Any) -> Dict[str, Any]:
        """
        Fetches earnings data from the External Data API.
        Returns a dictionary with summary_text, structured_data, and data_type.
        """
        logger.info(f"EarningsAnalysisTool: Executing for symbol='{symbol}', event_type='{event_type}', limit='{limit}'")

        api_base_url = llm_service_config.external_data_api_base_url
        if not api_base_url.endswith('/'):
            api_base_url += '/'

        params = {}
        # headers = {} # For potential internal API key as in NewsAnalysisTool

        if event_type.lower() == "upcoming":
            endpoint = f"{api_base_url}earnings/calendar"
            # Default to a 1-month range for upcoming, can be made configurable
            today = datetime.date.today()
            params['from_date'] = today.isoformat()
            params['to_date'] = (today + datetime.timedelta(days=30)).isoformat()
            if symbol and symbol.upper() != "UNKNOWN_SYMBOL": # API takes list of symbols
                params['symbols'] = [symbol.upper()] # External API expects list for symbols query param
        elif event_type.lower() == "historical":
            if not symbol or symbol.upper() == "UNKNOWN_SYMBOL":
                return {
                    "summary_text": "Error: A specific stock symbol is required for historical earnings.",
                    "structured_data": None,
                    "data_type": "error"
                }
            endpoint = f"{api_base_url}earnings/reports/{symbol.upper()}"
            params['limit'] = max(1, min(limit, 20)) # Cap limit for historical reports
        else:
            return {
                "summary_text": f"Error: Invalid event_type '{event_type}'. Please use 'upcoming' or 'historical'.",
                "structured_data": None,
                "data_type": "error"
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client: # Slightly longer timeout for earnings
                logger.debug(f"EarningsAnalysisTool: Calling GET {endpoint} with params {params}")
                response = await client.get(endpoint, params=params) # headers=headers
                response.raise_for_status()
                data = response.json() # Expects List[EarningsReportResponse]

            if not data:
                return {
                    "summary_text": f"No {event_type} earnings data found for '{symbol if symbol else 'any symbols in the period'}' via the External Data API.",
                    "structured_data": [],
                    "data_type": "earnings_reports"
                }

            # Summarize the data for the LLM
            summary_parts = [f"Found {len(data)} {event_type} earnings reports for '{symbol if symbol else 'the specified period'}':"]
            # Limit the number of reports in the summary to avoid overly long text
            # Use the original 'limit' for historical, or a fixed small number (e.g., 5) for upcoming for summary
            num_to_summarize = limit if event_type.lower() == "historical" else 5
            reports_to_summarize = data[:min(len(data), num_to_summarize)]

            for i, report in enumerate(reports_to_summarize):
                rpt_symbol = report.get('symbol', symbol if symbol else 'N/A').upper()
                report_date = report.get('report_date', 'N/A')
                eps_act = report.get('eps_actual', 'N/A')
                eps_est = report.get('eps_estimate', 'N/A')
                rev_act = report.get('revenue_actual', 'N/A') # Convert to human-readable if large number
                rev_est = report.get('revenue_estimate', 'N/A')
                time_of_day = report.get('time_of_day', '').upper()

                # Simple formatting for revenue numbers
                def format_revenue(val):
                    if isinstance(val, (int, float)):
                        if val >= 1e9: return f"${val/1e9:.2f}B"
                        if val >= 1e6: return f"${val/1e6:.2f}M"
                        return f"${val:.0f}"
                    return "N/A"

                summary_parts.append(
                    f"{i+1}. {rpt_symbol} on {report_date} ({time_of_day if time_of_day else 'N/A'}): "
                    f"EPS Act: {eps_act if eps_act is not None else 'N/A'}, Est: {eps_est if eps_est is not None else 'N/A'}. "
                    f"Rev Act: {format_revenue(rev_act)}, Est: {format_revenue(rev_est)}."
                )
            if len(data) > len(reports_to_summarize):
                summary_parts.append(f"... (and {len(data) - len(reports_to_summarize)} more reports not shown in summary)")

            return {
                "summary_text": "\n".join(summary_parts),
                "structured_data": data, # Return all fetched data
                "data_type": "earnings_reports"
            }

        except httpx.HTTPStatusError as e:
            err_content = e.response.text
            logger.error(f"EarningsAnalysisTool: HTTP error for '{symbol}', type '{event_type}': {e.response.status_code} - {err_content}", exc_info=True)
            return {
                "summary_text": f"Error: Could not fetch {event_type} earnings for '{symbol}'. API responded with {e.response.status_code}.",
                "structured_data": None,
                "data_type": "error"
            }
        except httpx.RequestError as e:
            logger.error(f"EarningsAnalysisTool: Request error for '{symbol}', type '{event_type}': {e}", exc_info=True)
            return {
                "summary_text": f"Error: Could not connect to the earnings data service for '{symbol}'.",
                "structured_data": None,
                "data_type": "error"
            }
        except Exception as e:
            logger.error(f"EarningsAnalysisTool: Unexpected error for '{symbol}', type '{event_type}': {e}", exc_info=True)
            return {
                "summary_text": f"An unexpected error occurred while trying to fetch {event_type} earnings for '{symbol}'.",
                "structured_data": None,
                "data_type": "error"
            }

if __name__ == '__main__':
    if not logger.handlers:
        logging.basicConfig(level=logging.DEBUG)
        logger.addHandler(logging.StreamHandler())
        logger.propagate = False

    import asyncio

    async def test_earnings_tool():
        tool = EarningsAnalysisTool()
        logger.info(f"Tool Name: {tool.name}")
        logger.info(f"Tool Description: {tool.description}")

        logger.info("\n--- Testing Upcoming Earnings for AAPL ---")
        # This will use default date range (today to +30 days)
        output_upcoming_aapl = await tool.execute(symbol="AAPL", event_type="upcoming")
        logger.info(f"Tool Output (Upcoming AAPL):\n{output_upcoming_aapl}")

        logger.info("\n--- Testing Upcoming Earnings (General, no symbol) ---")
        output_upcoming_general = await tool.execute(event_type="upcoming")
        logger.info(f"Tool Output (Upcoming General):\n{output_upcoming_general}")

        logger.info("\n--- Testing Historical Earnings for MSFT (limit 2) ---")
        output_historical_msft = await tool.execute(symbol="MSFT", event_type="historical", limit=2)
        logger.info(f"Tool Output (Historical MSFT):\n{output_historical_msft}")

        logger.info("\n--- Testing Historical Earnings for NonExistentSymbol ---")
        output_historical_nonexistent = await tool.execute(symbol="NONEXISTENTSYMBOLXYZ", event_type="historical")
        logger.info(f"Tool Output (Historical NonExistentSymbol):\n{output_historical_nonexistent}")

    asyncio.run(test_earnings_tool())
