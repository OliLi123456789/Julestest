from .base_tool import BaseTool
from typing import Any, Dict, List, Optional
import httpx
import logging
import datetime # Added for date parsing
# Import config from the llm_chatbot_service package level
from ..config_llm import llm_service_config

# Setup logger for this tool
# Using hierarchical logging based on a potential root logger for the service
logger = logging.getLogger(f"LLMChatbotService.tools.{__name__}")


class NewsAnalysisTool(BaseTool):
    name: str = "get_news_analysis"
    description: str = (
        "Retrieves recent news articles and their sentiment analysis for a given stock symbol or topic. "
        "Parameters: query (str, e.g., stock symbol 'AAPL' or topic 'market trends'), "
        "limit (int, optional, default 3, max 10, number of articles to return)."
    )

    async def execute(self, query: str, limit: int = 3, **kwargs: Any) -> Dict[str, Any]:
        """
        Fetches news articles and their sentiment from the External Data API.
        Returns a dictionary with summary_text, structured_data, and data_type.
        """
        logger.info(f"NewsAnalysisTool: Executing for query='{query}', limit='{limit}'")

        # Ensure limit is within a reasonable range for tool summarization
        actual_limit = max(1, min(limit, 10)) # Cap limit between 1 and 10 for this tool

        api_base_url = llm_service_config.external_data_api_base_url
        # Ensure the base URL ends with a slash if not already, for proper joining with endpoint path
        if not api_base_url.endswith('/'):
            api_base_url += '/'

        # The news articles endpoint in external_data_api is /news/articles
        # It expects 'symbol' as a query param for symbol-specific news.
        # For general query, we can use the same 'symbol' param, or adapt if API changes.
        # Let's assume 'symbol' param in the API can take a general query string too for news.
        endpoint = f"{api_base_url}news/articles"

        params = {
            "symbol": query, # API's 'symbol' param used for the query/symbol
            "limit": actual_limit,
            "page": 1, # Get the first page
            # "min_sentiment_compound": -1.0 # Fetch all, or apply a threshold here
        }

        # Conceptual: Add API key header if external_data_api itself is protected by a key
        # that this LLM service (as a client) needs to use.
        # headers = {}
        # if llm_service_config.external_data_api_key_for_llm_service: # If such a key is configured
        #     headers["X-Internal-Service-Key"] = llm_service_config.external_data_api_key_for_llm_service
        # For now, assuming external_data_api is not protected by a key from this service's perspective.

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.debug(f"NewsAnalysisTool: Calling GET {endpoint} with params {params}")
                response = await client.get(endpoint, params=params) # headers=headers
                response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

                data = response.json() # Expects PaginatedNewsResponse schema

            articles = data.get("items", [])
            if not articles:
                return {
                    "summary_text": f"No news articles found for '{query}' via the External Data API.",
                    "structured_data": [],
                    "data_type": "news_articles"
                }

            summary_parts = [f"Found {data.get('total_items', len(articles))} news articles related to '{query}' (showing up to {actual_limit}):"]
            # Using actual_limit for summarizing, as API might return more if its internal limit is higher than tool's actual_limit
            for i, article in enumerate(articles[:actual_limit]):
                title = article.get('title', 'N/A')
                source = article.get('source_name', 'N/A')
                pub_date_str = article.get('published_at', 'N/A')
                formatted_pub_date = pub_date_str[:10] # Default to simple slice
                try:
                    # Using datetime.datetime directly as it's imported at the top
                    pub_date_dt_obj = datetime.datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    formatted_pub_date = pub_date_dt_obj.strftime('%Y-%m-%d')
                except Exception:
                    logger.debug(f"Could not parse date string {pub_date_str} for news article, using slice.", exc_info=False)


                sentiment_score = article.get('sentiment_score_compound')
                sentiment_str = f"Sentiment (Compound): {sentiment_score:.2f}" if sentiment_score is not None else "Sentiment: N/A"

                summary_parts.append(f"{i+1}. '{title}' (Source: {source}, Published: {formatted_pub_date}) - {sentiment_str}.")

            return {
                "summary_text": "\n".join(summary_parts),
                "structured_data": articles, # Return all fetched articles based on API's own limit
                "data_type": "news_articles"
            }

        except httpx.HTTPStatusError as e:
            err_content = e.response.text
            logger.error(f"NewsAnalysisTool: HTTP error calling External Data API for news query '{query}': {e.response.status_code} - {err_content}", exc_info=True)
            return {
                "summary_text": f"Error: Could not fetch news for '{query}'. The data service responded with status {e.response.status_code}.",
                "structured_data": None,
                "data_type": "error"
            }
        except httpx.RequestError as e:
            logger.error(f"NewsAnalysisTool: Request error calling External Data API for news query '{query}': {e}", exc_info=True)
            return {
                "summary_text": f"Error: Could not connect to the news data service for query '{query}'.",
                "structured_data": None,
                "data_type": "error"
            }
        except Exception as e:
            logger.error(f"NewsAnalysisTool: Unexpected error during news analysis for query '{query}': {e}", exc_info=True)
            return {
                "summary_text": f"An unexpected error occurred while trying to fetch news for '{query}'.",
                "structured_data": None,
                "data_type": "error"
            }

if __name__ == '__main__':
    # Setup basic logging for tool testing
    if not logger.handlers:
        logging.basicConfig(level=logging.DEBUG)
        logger.addHandler(logging.StreamHandler())
        logger.propagate = False

    import asyncio

    async def test_news_tool():
        tool = NewsAnalysisTool()
        logger.info(f"Tool Name: {tool.name}")
        logger.info(f"Tool Description: {tool.description}")

        # This test will try to call http://localhost:8002 by default.
        # Ensure the External Data API is running on that port for this test to succeed live.
        # If not, it should gracefully return an error message from the tool.
        logger.info("\n--- Testing with 'AAPL' ---")
        output_aapl = await tool.execute(query="AAPL", limit=2)
        logger.info(f"Tool Output for AAPL:\n{output_aapl}")

        logger.info("\n--- Testing with 'market opening' ---")
        output_market = await tool.execute(query="market opening", limit=3)
        logger.info(f"Tool Output for market opening:\n{output_market}")

        logger.info("\n--- Testing with non-existent query (expecting 'No news articles found' or error) ---")
        output_nonexistent = await tool.execute(query="asdfqwerzxcvnonexistent", limit=3)
        logger.info(f"Tool Output for non-existent query:\n{output_nonexistent}")

    asyncio.run(test_news_tool())
