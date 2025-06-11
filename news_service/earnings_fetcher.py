# news_service/earnings_fetcher.py
import requests
import logging
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from .config_news import earnings_config
import datetime
import pandas as pd
import copy
import os # For retry config from env vars
import json # For JSONDecodeError in _make_request

# Use hierarchical logger based on the new logging setup
try:
    from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.earnings_fetcher")
except ImportError:
    logger = logging.getLogger(__name__)


MOCK_EARNINGS_CALENDAR_RESPONSE = [
    {"date": (datetime.date.today() - datetime.timedelta(days=1)).isoformat(), "symbol": "AAPL", "epsEstimated": 1.50, "epsActual": 1.55, "time": "amc", "revenueEstimated": 89e9, "revenueActual": 90e9, "fiscalDateEnding": (datetime.date.today() - datetime.timedelta(days=15)).isoformat()},
    {"date": datetime.date.today().isoformat(), "symbol": "MSFT", "epsEstimated": 2.10, "epsActual": None, "time": "bmo", "revenueEstimated": 50e9, "revenueActual": None, "fiscalDateEnding": (datetime.date.today() - datetime.timedelta(days=10)).isoformat()},
    {"date": (datetime.date.today() + datetime.timedelta(days=1)).isoformat(), "symbol": "GOOG", "epsEstimated": 1.80, "epsActual": None, "time": "amc", "revenueEstimated": 70e9, "revenueActual": None, "fiscalDateEnding": (datetime.date.today() - datetime.timedelta(days=5)).isoformat()},
]
MOCK_HISTORICAL_EARNINGS_RESPONSE = {
    "AAPL": [
        {"date": "2023-12-15", "symbol": "AAPL", "eps": 1.40, "epsEstimated": 1.35, "time":"amc", "revenue": 90e9, "revenueEstimated": 88e9, "fiscalDateEnding": "2023-11-30"},
        {"date": "2023-09-15", "symbol": "AAPL", "eps": 1.20, "epsEstimated": 1.18, "time":"amc", "revenue": 85e9, "revenueEstimated": 85.5e9, "fiscalDateEnding": "2023-08-31"},
        {"date": "2023-06-15", "symbol": "AAPL", "eps": 1.10, "epsEstimated": 1.08, "time":"amc", "revenue": 82e9, "revenueEstimated": 81.5e9, "fiscalDateEnding": "2023-05-31"},
        {"date": "2023-03-15", "symbol": "AAPL", "eps": 1.00, "epsEstimated": 0.98, "time":"amc", "revenue": 80e9, "revenueEstimated": 79.5e9, "fiscalDateEnding": "2023-02-28"},
    ],
    "MSFT": [
        {"date": "2023-12-20", "symbol": "MSFT", "eps": 2.00, "epsEstimated": 1.95, "time":"bmo", "revenue": 52e9, "revenueEstimated": 51e9, "fiscalDateEnding": "2023-11-30"},
        {"date": "2023-09-20", "symbol": "MSFT", "eps": 1.80, "epsEstimated": 1.78, "time":"bmo", "revenue": 48e9, "revenueEstimated": 48.5e9, "fiscalDateEnding": "2023-08-31"},
    ]
}

class EarningsFetcher:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, use_mock_initially: bool = False):
        self.api_key = api_key if api_key is not None else earnings_config.api_key
        self.base_url = base_url if base_url is not None else earnings_config.base_url
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'TradingPlatformEarningsFetcher/1.0'})

        self.use_mock = use_mock_initially
        if not self.api_key:
            logger.warning("EarningsFetcher: No API key. Using MOCK data.")
            self.use_mock = True
        elif self.api_key.upper() == "MOCK_API_KEY_FOR_TESTING":
            logger.info("EarningsFetcher: Initialized with MOCK_API_KEY_FOR_TESTING. Using MOCK data.")
            self.use_mock = True
        else:
            logger.info(f"EarningsFetcher: Initialized for live API calls to {self.base_url}.")

        # Retry configuration
        try:
            self.max_retries: int = int(os.getenv("EARNINGS_FETCHER_MAX_RETRIES", "3"))
            self.retry_delay_seconds: int = int(os.getenv("EARNINGS_FETCHER_RETRY_DELAY_SECONDS", "10"))
        except ValueError:
            logger.warning("Invalid retry config env vars for EarningsFetcher. Using defaults (3 retries, 10s delay).")
            self.max_retries = 3
            self.retry_delay_seconds = 10

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        if self.use_mock: # This method should not be called if use_mock is True from the calling method
            logger.error(f"Live request to {endpoint} attempted in mock mode (this indicates an issue in calling code).")
            return None
        if not self.api_key:
            logger.error(f"API key missing for live request to {endpoint}.")
            return None

        base_api_url = self.base_url if self.base_url.endswith('/') else self.base_url + '/'
        full_url = urljoin(base_api_url, endpoint)

        request_params = params.copy() if params else {}
        request_params['apikey'] = self.api_key

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(f"EarningsFetcher: Attempt {attempt + 1} to request {full_url} with params (apikey hidden): {params}")
                response = self.session.get(full_url, params=request_params, timeout=15)

                if response.status_code == 429: # Rate limit
                    retry_after_header = response.headers.get("Retry-After")
                    try:
                        wait_time = int(retry_after_header) if retry_after_header else (self.retry_delay_seconds * (attempt + 1))
                    except ValueError: wait_time = (self.retry_delay_seconds * (attempt + 1))
                    logger.warning(f"Rate limit (429) for {full_url}. Retrying after {wait_time}s. Attempt {attempt + 1}/{self.max_retries + 1}")
                    if attempt < self.max_retries: time.sleep(wait_time); continue
                    else: response.raise_for_status()

                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as http_err:
                if isinstance(http_err.response, requests.Response) and \
                   (500 <= http_err.response.status_code < 600 or http_err.response.status_code == 408): # Server-side or timeout related
                    logger.warning(f"HTTP error {http_err.response.status_code} for {full_url}. Attempt {attempt + 1}/{self.max_retries + 1}. Retrying in {self.retry_delay_seconds}s...")
                    if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                logger.error(f"HTTP error for {full_url} with params {params}: {http_err.response.status_code} - {http_err.response.text}", exc_info=True)
                return None # Non-retryable HTTP error or retries exhausted

            except requests.exceptions.RequestException as req_err: # Connection, non-HTTP timeout etc.
                logger.warning(f"Request error for {full_url}: {req_err}. Attempt {attempt + 1}/{self.max_retries + 1}. Retrying in {self.retry_delay_seconds}s...")
                if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                logger.error(f"Request error for {full_url} with params {params} (final attempt): {req_err}", exc_info=True)
                return None

            except json.JSONDecodeError as json_err:
                logger.error(f"JSON decode error for {full_url} with params {params}: {json_err}. Response text: {response.text[:200] if response else 'No response object'}", exc_info=True)
                return None # Cannot parse response

            except Exception as e:
                logger.error(f"Unexpected error during API request to {full_url} with params {params} (attempt {attempt + 1}): {e}", exc_info=True)
                if attempt < self.max_retries: time.sleep(self.retry_delay_seconds); continue
                return None

        logger.error(f"Failed to fetch data from {full_url} after {self.max_retries + 1} attempts.")
        return None


    def fetch_earnings_calendar(self, from_date_str: Optional[str] = None, to_date_str: Optional[str] = None,
                                symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        logger.info(f"Fetching earnings calendar: From={from_date_str}, To={to_date_str}, Symbols={symbols}")
        if self.use_mock:
            logger.info(f"Using MOCK response for earnings_calendar.")
            data = copy.deepcopy(MOCK_EARNINGS_CALENDAR_RESPONSE)
            if from_date_str: data = [r for r in data if r['date'] >= from_date_str]
            if to_date_str: data = [r for r in data if r['date'] <= to_date_str]
            if symbols:
                upper_symbols = [s.upper() for s in symbols]
                data = [r for r in data if r['symbol'].upper() in upper_symbols]
            return data

        endpoint = "earning_calendar"
        params = {}
        if from_date_str: params['from'] = from_date_str
        if to_date_str: params['to'] = to_date_str

        api_data = self._make_request(endpoint, params)

        if isinstance(api_data, list):
            if symbols:
                upper_symbols = [s.upper() for s in symbols]
                return [r for r in api_data if r.get('symbol','').upper() in upper_symbols]
            return api_data
        return []

    def fetch_historical_earnings(self, symbol: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        symbol_upper = symbol.upper()
        limit_to_use = limit if limit is not None else earnings_config.history_limit_default
        logger.info(f"Fetching historical earnings for: {symbol_upper} (limit={limit_to_use})")

        if self.use_mock:
            logger.info(f"Using MOCK for historical_earnings: {symbol_upper}")
            return copy.deepcopy(MOCK_HISTORICAL_EARNINGS_RESPONSE.get(symbol_upper, []))[:limit_to_use]

        endpoint = f"historical/earning_calendar/{symbol_upper}"
        params = {'limit': str(limit_to_use)}

        api_data = self._make_request(endpoint, params)
        return api_data if isinstance(api_data, list) else []

if __name__ == '__main__':
    # Example of setting up the shared/root logger for external data services
    from .logging_setup import setup_external_data_logging, EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    setup_external_data_logging(log_level_str="DEBUG", service_name_override=EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME, force_reconfigure_root=True)

    logger.info("--- Testing EarningsFetcher in MOCK mode (forced) ---")
    mock_fetcher = EarningsFetcher(api_key="MOCK_API_KEY_FOR_TESTING")

    today_for_test = datetime.date(2024, 3, 17)
    cal_from = (today_for_test - datetime.timedelta(days=2)).isoformat()
    cal_to = (today_for_test + datetime.timedelta(days=2)).isoformat()

    logger.info(f"Fetching mock earnings calendar ({cal_from} to {cal_to}) for AAPL, MSFT")
    calendar_mock = mock_fetcher.fetch_earnings_calendar(from_date_str=cal_from, to_date_str=cal_to, symbols=['AAPL', 'MSFT'])
    if calendar_mock: logger.info(f"Found {len(calendar_mock)} mock announcements: {calendar_mock}")
    else: logger.info("No mock announcements found for AAPL, MSFT in range.")

    logger.info("\nFetching mock historical earnings for AAPL (limit 2)")
    aapl_hist_mock = mock_fetcher.fetch_historical_earnings(symbol="AAPL", limit=2)
    if aapl_hist_mock: logger.info(f"Found {len(aapl_hist_mock)} mock reports for AAPL: {aapl_hist_mock}")
    else: logger.info("No mock historical for AAPL.")

    logger.info("\n--- Testing EarningsFetcher with LIVE API (if EARNINGS_API_KEY is set in env and not 'MOCK_API_KEY_FOR_TESTING') ---")
    live_fetcher = EarningsFetcher()
    if live_fetcher.use_mock and os.getenv("EARNINGS_API_KEY") and os.getenv("EARNINGS_API_KEY").upper() != "MOCK_API_KEY_FOR_TESTING":
        logger.warning("EARNINGS_API_KEY is set for live, but fetcher defaulted to mock mode. Check __init__ or key value.")

    logger.info(f"Fetching live earnings calendar ({cal_from} to {cal_to}) for 'TSLA', 'NVDA'")
    calendar_live = live_fetcher.fetch_earnings_calendar(from_date_str=cal_from, to_date_str=cal_to, symbols=['TSLA', 'NVDA'])
    if calendar_live: logger.info(f"Found {len(calendar_live)} live announcements. First 3: {calendar_live[:3]}")
    else: logger.info("No live announcements found for TSLA, NVDA in range (or using mock / API error).")

    logger.info("\nFetching live historical earnings for NVDA (limit 3)")
    nvda_hist_live = live_fetcher.fetch_historical_earnings(symbol="NVDA", limit=3)
    if nvda_hist_live: logger.info(f"Found {len(nvda_hist_live)} live reports for NVDA: {nvda_hist_live}")
    else: logger.info("No live historical for NVDA (or using mock / API error).")

    logger.info("EarningsFetcher example finished.")
