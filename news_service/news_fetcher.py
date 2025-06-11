# news_service/news_fetcher.py
import requests
import logging
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from .config_news import news_service_config
import datetime
import copy
import pandas as pd
import os # For retry config from env vars

# Use hierarchical logger based on the new logging setup
try:
    from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.news_fetcher")
except ImportError: # Fallback if logging_setup is not available (e.g. standalone test)
    logger = logging.getLogger(__name__)


# Default mock response, can be updated by tests or specific mock setups
MOCK_NEWSAPI_ORG_RESPONSE = {
    "status": "ok",
    "totalResults": 1,
    "articles": [{
        "source": {"id": "mock-source", "name": "Mock Source"},
        "author": "Mock Author",
        "title": "Mock Article: Stock XYZ Surges on AI News from MockLand",
        "description": "Stock XYZ saw a significant increase today after announcing new AI initiatives. This is mock data.",
        "url": "http://mock.example.com/news/1",
        "urlToImage": None,
        "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "content": "Full mock content here detailing the AI initiatives and market reaction..."
    }]
}

class NewsFetcher:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, use_mock_initially: bool = False):
        self.api_key = api_key if api_key is not None else news_service_config.news_api_key
        self.base_url = base_url if base_url is not None else news_service_config.news_api_base_url
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'TradingPlatformNewsFetcher/1.0'})

        self.use_mock = use_mock_initially
        if not self.api_key:
            logger.warning("NewsFetcher: No API key. Using MOCK data.")
            self.use_mock = True
        elif self.api_key.upper() == "MOCK_API_KEY_FOR_TESTING":
            logger.info("NewsFetcher: Initialized with MOCK_API_KEY_FOR_TESTING. Using MOCK data.")
            self.use_mock = True
        elif "newsapi.org" in self.base_url :
             self.session.headers.update({'X-Api-Key': self.api_key})
             logger.info("NewsFetcher: Initialized with live API key for NewsAPI.org.")
        else:
             logger.info(f"NewsFetcher: Initialized for custom base_url '{self.base_url}'.")

        # Retry configuration
        try:
            self.max_retries: int = int(os.getenv("NEWS_FETCHER_MAX_RETRIES", "3"))
            self.retry_delay_seconds: int = int(os.getenv("NEWS_FETCHER_RETRY_DELAY_SECONDS", "5"))
        except ValueError:
            logger.warning("Invalid retry config env vars. Using defaults (3 retries, 5s delay).")
            self.max_retries = 3
            self.retry_delay_seconds = 5


    def _perform_api_request(self, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """ Helper method to perform API request with retry logic. """
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=10)

                if response.status_code == 429: # Rate limit
                    # Respect Retry-After header if present, else use configured delay with exponential backoff principle
                    retry_after_header = response.headers.get("Retry-After")
                    try:
                        wait_time = int(retry_after_header) if retry_after_header else (self.retry_delay_seconds * (attempt + 1))
                    except ValueError: # If Retry-After is not an int (e.g. a date string)
                        wait_time = (self.retry_delay_seconds * (attempt + 1)) # Default backoff
                        # TODO: Parse date string from Retry-After if that's what API sends

                    logger.warning(f"Rate limit hit (429) for {url}. Retrying after {wait_time}s. Attempt {attempt + 1}/{self.max_retries + 1}")
                    if attempt < self.max_retries: time.sleep(wait_time); continue
                    else: response.raise_for_status() # Raise to fail after max retries

                response.raise_for_status() # For other 4xx/5xx errors
                return response.json()

            except requests.exceptions.HTTPError as http_err:
                # For 5xx server errors or specific 4xx that might be transient (e.g., 408 Timeout from server side)
                if isinstance(http_err.response, requests.Response) and \
                   (500 <= http_err.response.status_code < 600 or http_err.response.status_code == 408):
                    logger.warning(f"HTTP error {http_err.response.status_code} fetching {url}. Attempt {attempt + 1}/{self.max_retries + 1}. Retrying in {self.retry_delay_seconds}s...")
                    if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                logger.error(f"HTTP error for {url} with params {params}: {http_err.response.status_code} - {http_err.response.text}", exc_info=True)
                return None # Return None for HTTP errors that are not retried or after retries exhausted

            except requests.exceptions.RequestException as req_err: # Connection, timeout etc.
                logger.warning(f"Request error for {url}: {req_err}. Attempt {attempt + 1}/{self.max_retries + 1}. Retrying in {self.retry_delay_seconds}s...")
                if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                logger.error(f"Request error for {url} with params {params} (final attempt): {req_err}", exc_info=True)
                return None # Return None after retries exhausted

            except json.JSONDecodeError as json_err: # Handle non-JSON responses if API sometimes fails that way
                logger.error(f"JSON decode error for {url} with params {params}: {json_err}. Response text: {response.text[:200] if response else 'No response object'}", exc_info=True)
                return None

            except Exception as e: # Catch-all for other unexpected errors during request/parsing
                logger.error(f"Unexpected error during API request to {url} with params {params} (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                return None # Return None after retries exhausted

        logger.error(f"Failed to fetch data from {url} after {self.max_retries + 1} attempts.")
        return None


    def fetch_news(self, query: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
                     page_size: Optional[int] = None, max_pages: int = 1, sort_by: Optional[str] = None,
                     language: Optional[str] = None, sources: Optional[str] = None,
                     domains: Optional[str] = None) -> List[Dict[str, Any]]:

        if self.use_mock:
            logger.info(f"Using MOCK response for NewsAPI query: '{query}'")
            mock_articles = copy.deepcopy(MOCK_NEWSAPI_ORG_RESPONSE.get("articles", []))
            if mock_articles:
                ref_date_str = to_date or from_date or datetime.datetime.now(datetime.timezone.utc).isoformat()
                try: # Ensure pd.to_datetime is used correctly
                    mock_articles[0]['publishedAt'] = pd.to_datetime(ref_date_str).isoformat() + "Z"
                    mock_articles[0]['title'] = f"Mock Article ({query}): Stock {query} News on {pd.to_datetime(ref_date_str).strftime('%Y-%m-%d')}"
                except Exception as e_mock_date: logger.error(f"Error formatting mock date: {e_mock_date}")
            return mock_articles

        page_size_to_use = page_size if page_size is not None else news_service_config.default_news_page_size
        sort_by_to_use = sort_by if sort_by is not None else news_service_config.default_news_sort_by
        language_to_use = language if language is not None else news_service_config.default_news_language

        params = {'q': query, 'pageSize': min(page_size_to_use, 100),
                  'sortBy': sort_by_to_use, 'language': language_to_use}
        if from_date: params['from'] = from_date
        if to_date: params['to'] = to_date
        if sources: params['sources'] = sources
        if domains: params['domains'] = domains

        all_articles: List[Dict[str, Any]] = []
        endpoint = "everything"
        base_api_url = self.base_url if self.base_url.endswith('/') else self.base_url + '/'
        full_endpoint_url = urljoin(base_api_url, endpoint)

        logger.info(f"Fetching news: query='{query}', endpoint='{full_endpoint_url}', max_pages={max_pages}, params_subset={{{'from':from_date, 'to':to_date, 'pageSize':params['pageSize']}}}")

        current_page_num = 1
        while current_page_num <= max_pages:
            params['page'] = current_page_num
            data = self._perform_api_request(full_endpoint_url, params) # Use new request method

            if data is None: # Request failed after retries or other critical error
                logger.error(f"Failed to fetch data for page {current_page_num} of query '{query}'. Stopping pagination for this query.")
                break

            if data.get("status") == "error":
                logger.error(f"NewsAPI returned error status on page {current_page_num} for '{query}': {data.get('code')} - {data.get('message')}")
                break

            articles_on_this_page = data.get("articles", [])
            all_articles.extend(articles_on_this_page)
            logger.debug(f"Fetched page {current_page_num} for '{query}', {len(articles_on_this_page)} articles. Total now: {len(all_articles)}.")

            if not articles_on_this_page or len(articles_on_this_page) < params['pageSize']:
                logger.info(f"Last page for '{query}' at page {current_page_num} or no more articles.")
                break

            current_page_num += 1
            if current_page_num <= max_pages: # Only sleep if there are more pages to fetch
                time.sleep(0.25) # Shorter delay, retry logic handles longer waits for rate limits

        logger.info(f"Finished fetching for '{query}'. Total articles: {len(all_articles)} after {current_page_num-1} page(s) attempt(s).")
        return all_articles

if __name__ == '__main__':
    # Example of setting up the shared/root logger for external data services
    from .logging_setup import setup_external_data_logging, EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    setup_external_data_logging(log_level_str="DEBUG", service_name_override=EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME, force_reconfigure_root=True)

    # Test with default config (might use mock if key not set)
    fetcher_default = NewsFetcher()
    logger.info("\n--- Fetching 'Market Crash' news (default fetcher, max 1 page, default page size) ---")
    # ... (rest of __main__ from previous version) ...
    market_news = fetcher_default.fetch_news(query="Market Crash", max_pages=1)
    if market_news:
        logger.info(f"Found {len(market_news)} articles for 'Market Crash'.")
        for i, article in enumerate(market_news[:2]):
            logger.info(f"  Article {i+1}: {article.get('title')} (Source: {article.get('source',{}).get('name')}, Pub: {article.get('publishedAt')})")
    else:
        logger.info("No articles found for 'Market Crash' (or using mock response).")

    fetcher_mock = NewsFetcher(api_key="MOCK_API_KEY_FOR_TESTING")
    logger.info("\n--- Fetching 'AI Stocks' news (explicit mock mode) ---")
    ai_news = fetcher_mock.fetch_news(query="AI Stocks")
    if ai_news:
        logger.info(f"Found {len(ai_news)} mock articles for 'AI Stocks'. Title: {ai_news[0].get('title')}")

    today_str = datetime.date.today().isoformat()
    one_week_ago_str = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    logger.info(f"\n--- Fetching 'Federal Reserve' news from {one_week_ago_str} to {today_str} (max 2 pages, size 5) ---")
    fed_news = fetcher_default.fetch_news(query="Federal Reserve", from_date=one_week_ago_str, to_date=today_str, page_size=5, max_pages=2)
    if fed_news:
        logger.info(f"Found {len(fed_news)} articles for 'Federal Reserve'.")
        for i, article in enumerate(fed_news[:3]):
             logger.info(f"  Article {i+1}: {article.get('title')} (Pub: {article.get('publishedAt')})")
    else:
        logger.info("No articles found for 'Federal Reserve' (or using mock response).")

    logger.info("\n--- Fetching 'Technology' news from 'bbc-news' (max 1 page, size 3) ---")
    tech_news_source = fetcher_default.fetch_news(query="Technology", sources="bbc-news", page_size=3, max_pages=1)
    if tech_news_source:
        logger.info(f"Found {len(tech_news_source)} articles for 'Technology' from 'bbc-news'.")
        for article in tech_news_source: logger.info(f"  Title: {article.get('title')}")
    else:
        logger.info("No articles found for 'Technology' from 'bbc-news' (or using mock response / API key issue).")

    logger.info("NewsFetcher example finished.")
