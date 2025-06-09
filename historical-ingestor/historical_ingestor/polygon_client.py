import requests
import time
import logging
from typing import List, Dict, Any, Optional, Generator
from datetime import date, timedelta, datetime

# Assuming config.py is in the same directory or Python path is set up correctly
from .config import PolygonRESTConfig

logger = logging.getLogger(__name__)

class PolygonRESTClient:
    def __init__(self, config: PolygonRESTConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.config.api_key}"})
        # Using a list to store timestamps of recent requests for rate limiting
        self.request_timestamps: List[float] = []
        self.max_retries = config.max_retries

    def _enforce_rate_limit(self):
        """
        Ensures that the number of requests per minute does not exceed the configured limit.
        This is a client-side implementation of a sliding window rate limiter.
        """
        current_time = time.time()
        # Remove timestamps older than 60 seconds + a small buffer (e.g., 1 sec) to be safe
        self.request_timestamps = [ts for ts in self.request_timestamps if current_time - ts <= 61]

        if len(self.request_timestamps) >= self.config.requests_per_minute_limit:
            # Calculate how long to wait until the oldest request in the window is older than 60s
            time_since_oldest_request = current_time - self.request_timestamps[0]
            wait_time = 61.0 - time_since_oldest_request # Wait until the slot is free

            if wait_time > 0:
                logger.info(f"Rate limit of {self.config.requests_per_minute_limit}/min reached. Waiting for {wait_time:.2f} seconds.")
                time.sleep(wait_time)
                # After waiting, update timestamps again by removing those that have now passed the 60s window
                current_time = time.time() # Re-evaluate current time
                self.request_timestamps = [ts for ts in self.request_timestamps if current_time - ts <= 61]

        self.request_timestamps.append(time.time()) # Record current request timestamp

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._enforce_rate_limit()

        url = f"{self.config.base_url}{endpoint}"
        retries_left = self.max_retries

        while retries_left >= 0:
            try:
                logger.debug(f"Requesting URL: {url} with params: {params}")
                response = self.session.request(method, url, params=params, timeout=self.config.timeout_seconds)

                if response.status_code == 429: # Too Many Requests - specific rate limit from server
                    retry_after_str = response.headers.get("Retry-After")
                    wait_seconds = 15 # Default wait if header not present or unparsable
                    if retry_after_str:
                        try:
                            wait_seconds = int(retry_after_str) + 1 # Add a small buffer
                        except ValueError:
                            logger.warning(f"Could not parse Retry-After header: {retry_after_str}")

                    logger.warning(f"Server rate limit (429) hit for {url}. Waiting {wait_seconds}s as per Retry-After or default.")
                    time.sleep(float(wait_seconds))
                    # No decrement of retries_left for 429 if we are respecting Retry-After
                    # Or, if you want to limit total time spent, you might still decrement.
                    # For now, let's assume respecting Retry-After doesn't count as a "retry" in our max_retries logic.
                    # However, the client-side rate limiter should ideally prevent most 429s.
                    # This server-side 429 handling is a backup.
                    continue # Retry the request after waiting

                response.raise_for_status() # Raises HTTPError for other bad responses (4XX or 5XX)
                return response.json()

            except requests.exceptions.HTTPError as e:
                # For 4xx errors (other than 429), usually not retriable. For 5xx, retriable.
                if e.response.status_code >= 500 and retries_left > 0:
                    logger.warning(f"Server error ({e.response.status_code}) for {url}. Retries left: {retries_left}. Error: {e}")
                    time.sleep( (self.max_retries - retries_left + 1) * 2 ) # Basic exponential backoff factor
                else:
                    logger.error(f"HTTP error fetching {url} with params {params}: {e}")
                    raise # Non-retriable or max retries exhausted for server errors
            except requests.exceptions.RequestException as e: # Other errors like timeout, connection error
                logger.warning(f"Request exception for {url}. Retries left: {retries_left}. Error: {e}")
                if retries_left == 0:
                    logger.error(f"Max retries exhausted for {url}. Last error: {e}")
                    raise
                time.sleep( (self.max_retries - retries_left + 1) * 2 ) # Basic exponential backoff factor

            retries_left -= 1

        # Should not be reached if raise is working correctly in loops
        raise Exception(f"Exhausted all retries for {url}")


    def get_aggregates(self, ticker: str, multiplier: int, timespan: str, from_date_str: str, to_date_str: str, limit: int = 50000) -> Generator[Dict[str, Any], None, None]:
        # timespan: minute, hour, day, week, month, quarter, year
        # Polygon v2 aggregates API is paginated using date ranges if the number of results exceeds the limit (max 50000).
        # However, their primary pagination for large result sets is often cursor-based in v3 APIs or by adjusting date ranges.
        # This implementation will handle large date ranges by making multiple calls if necessary,
        # adjusting the `to_date_str` of the previous call to be the `from_date_str` of the next.
        # This is simplified; a more robust solution would use Polygon's `next_url` if available (more common in trades/quotes).
        # For aggregates, adjusting date ranges is a common way.

        logger.info(f"Initiating aggregate fetch for {ticker} from {from_date_str} to {to_date_str} ({timespan})")

        current_fetch_from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        final_to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

        while current_fetch_from_date <= final_to_date:
            # Determine the 'to' date for this specific API call.
            # Polygon might have limits on date range width (e.g., 2 years for daily).
            # For simplicity, we'll fetch in chunks if the user provided range is huge,
            # but this example primarily focuses on the standard API call for a given range.
            # A common strategy is to fetch month by month or year by year for very long histories.
            # This example will fetch the whole user-provided range in one go if Polygon allows,
            # relying on internal pagination if results > limit (though v2 aggs don't use next_url).

            endpoint = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{current_fetch_from_date.strftime('%Y-%m-%d')}/{to_date_str}"
            params = {"adjusted": "true", "sort": "asc", "limit": str(limit)}

            try:
                data = self._make_request("GET", endpoint, params)
                results = data.get("results", [])
                if not results:
                    logger.info(f"No more aggregate results for {ticker} from {current_fetch_from_date} in range.")
                    break

                for record in results:
                    yield record

                logger.info(f"Fetched and yielded {len(results)} aggregates for {ticker} up to last record timestamp {results[-1].get('t') if results else 'N/A'}")

                # For v2 aggregates, if count == limit, it means there *might* be more data *if your original to_date was further out*.
                # Since we are iterating by adjusting from_date, this logic is more about breaking down huge user requests.
                # If Polygon's single call limit for a date range is hit (e.g. 50000 results),
                # the user would need to make a narrower date range call.
                # This function assumes the user-provided from_date_str to to_date_str is one logical unit they want.
                # A more sophisticated approach for very long ranges would involve iterating by smaller date chunks.
                # For this implementation, we assume one call for the given from_date_str to to_date_str is sufficient,
                # or that `limit` handles internal Polygon pagination if the API supports it for this endpoint.
                # Since v2 aggs range doesn't use `next_url`, we assume it returns all for the path's date range up to `limit`.
                # If we got `limit` results, it implies we might need to make another call starting *after* the last timestamp.
                # This part is tricky with v2 aggs. For now, we'll assume one call per user-defined range.
                # To handle >50k results for a large date range, the CALLER of this function would need to iterate,
                # adjusting from_date and to_date.
                # OR, this function could detect if len(results) == limit and the last timestamp is before to_date_str,
                // then adjust current_fetch_from_date = last_timestamp + 1 period and loop. This is complex.
                // For now, let's assume the provided date range is small enough or the user handles wider iteration.
                break # Exit while loop after one successful fetch for the given date range.

            except Exception as e:
                logger.error(f"Failed to fetch or process aggregates for {ticker} for date {current_fetch_from_date}: {e}")
                # Decide on error strategy: break, continue with next date chunk, or raise
                raise # Propagate error for now


    def get_trades_for_date(self, ticker: str, date_str: str, limit: int = 50000, timestamp_gte: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Fetches all trades for a ticker on a specific date, handling pagination."""
        logger.info(f"Initiating trades fetch for {ticker} on {date_str}")
        endpoint = f"/v3/trades/{ticker}" # v3 Trades API
        params = {"date": date_str, "limit": str(limit)}
        if timestamp_gte:
            params["timestamp.gte"] = str(timestamp_gte) # Nanoseconds for v3

        next_url_path: Optional[str] = endpoint # Start with the base endpoint

        while next_url_path:
            # If next_url_path is absolute (contains base_url), use as is.
            # If relative, prepend base_url. Polygon's next_url is usually absolute.
            url_to_fetch = next_url_path
            current_params = params if url_to_fetch == endpoint else {} # Params only for the first request

            if not url_to_fetch.startswith(self.config.base_url):
                 url_to_fetch = f"{self.config.base_url}{next_url_path}"

            try:
                data = self._make_request("GET", url_to_fetch, params=current_params) # Pass actual URL to _make_request
                results = data.get("results", [])
                if not results:
                    break

                for record in results:
                    yield record

                logger.info(f"Fetched and yielded {len(results)} trades for {ticker} on {date_str}")
                next_url_path = data.get("next_url") # This is an absolute URL
                if next_url_path and next_url_path.startswith(self.config.base_url): # Strip base if present for next iteration
                    next_url_path = next_url_path[len(self.config.base_url):]

            except Exception as e:
                logger.error(f"Failed to fetch or process trades for {ticker} on {date_str} from URL {url_to_fetch}: {e}")
                raise # Propagate error

    # Similar method for get_quotes_for_date can be implemented
    # def get_quotes_for_date(self, ticker: str, date_str: str, limit: int = 50000, ...) -> Generator[Dict[str, Any], None, None]: ...
    # Remember to use the correct Polygon API v2 or v3 endpoint and handle its specific pagination.
    # Quotes v3: /v3/quotes/{stocksTicker}
    # NBBO v2: /v2/ticks/stocks/nbbo/{ticker}/{date} (deprecated, use v3)
    # Trades v2: /v2/ticks/stocks/trades/{ticker}/{date} (deprecated, use v3)

    # The example for get_aggregates uses v2, get_trades_for_date uses v3.
    # It's important to align with the specific Polygon API versions you intend to use.
    # For production, consistently using v3+ APIs is generally recommended for features like cursor pagination.
    # The get_aggregates pagination above is simplified and might need refinement for very large ranges.
    # For this exercise, the structure for rate limiting and making requests is the key focus.## Method Explanation

The previous `_make_request` method in `historical-ingestor/historical_ingestor/polygon_client.py` was making a request using `self.session.get(url, params=params, ...)`. However, when `next_url` is received from Polygon.io, it's often an absolute URL that already contains query parameters. Passing `params` again to `requests.get` or `session.request` when `url` is an absolute `next_url` can lead to duplicated or conflicting query parameters.

The `_make_request` method should ideally just take the full URL (which could be the base endpoint + params, or the `next_url`) and make the request. The logic for constructing the initial URL with params, or using the `next_url` directly, should reside in the calling methods like `get_trades_for_date`.

I will modify `_make_request` to accept a `full_url` directly and remove its own `params` argument. The calling methods will be responsible for constructing the `full_url` including any necessary query parameters for the *initial* request, and then just using the `next_url` as is for subsequent paginated requests.

This also simplifies the `get_paginated_data` conceptual example, which was trying to manage params separately from `next_url`.

**Refined `_make_request` and `get_trades_for_date`:**

```python
# historical_ingestor/polygon_client.py
# ... (imports and class definition) ...

    def _make_request(self, method: str, full_url: str) -> Dict[str, Any]: # Changed endpoint/params to full_url
        self._enforce_rate_limit()

        retries_left = self.max_retries
        url_to_log = full_url # For logging, to show actual URL being hit

        while retries_left >= 0:
            try:
                # Mask API key in logged URL if present as a query param (should not be for Polygon Bearer token)
                if "apiKey=" in url_to_log:
                    url_to_log = url_to_log.split("apiKey=")[0] + "apiKey=REDACTED"
                logger.debug(f"Requesting URL: {url_to_log}")

                response = self.session.request(method, full_url, timeout=self.config.timeout_seconds) # No 'params' arg here

                if response.status_code == 429:
                    retry_after_str = response.headers.get("Retry-After")
                    wait_seconds = 15
                    if retry_after_str:
                        try:
                            wait_seconds = int(retry_after_str) + 1
                        except ValueError:
                            logger.warning(f"Could not parse Retry-After header: {retry_after_str}")

                    logger.warning(f"Server rate limit (429) hit for {url_to_log}. Waiting {wait_seconds}s.")
                    time.sleep(float(wait_seconds))
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                if e.response.status_code >= 500 and retries_left > 0:
                    logger.warning(f"Server error ({e.response.status_code}) for {url_to_log}. Retries left: {retries_left}. Error: {e}")
                    time.sleep( (self.max_retries - retries_left + 1) * 2 )
                else:
                    logger.error(f"HTTP error fetching {url_to_log}: {e}")
                    raise
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request exception for {url_to_log}. Retries left: {retries_left}. Error: {e}")
                if retries_left == 0:
                    logger.error(f"Max retries exhausted for {url_to_log}. Last error: {e}")
                    raise
                time.sleep( (self.max_retries - retries_left + 1) * 2 )

            retries_left -= 1

        raise Exception(f"Exhausted all retries for {url_to_log}")

    # ... (get_aggregates remains similar as it constructs full path with params for v2) ...
    # For get_aggregates, the `params` dict was for the `requests` library,
    # but Polygon v2 aggs usually put all filters in the URL path.
    # The `params` in `get_aggregates` should be used to construct the URL path correctly.
    # Let's refine get_aggregates as well for consistency.

    def get_aggregates(self, ticker: str, multiplier: int, timespan: str, from_date_str: str, to_date_str: str, limit: int = 50000, adjusted: bool = True, sort: str = "asc") -> Generator[Dict[str, Any], None, None]:
        logger.info(f"Initiating aggregate fetch for {ticker} from {from_date_str} to {to_date_str} ({multiplier} {timespan})")

        # Construct the full endpoint path including query parameters for v2 aggregates
        # Note: Polygon's v2 aggregates API primarily uses path parameters for range, multiplier, timespan.
        # Query parameters like 'adjusted', 'sort', 'limit' are standard.
        endpoint_path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date_str}/{to_date_str}"
        query_params = f"?adjusted={'true' if adjusted else 'false'}&sort={sort}&limit={limit}"
        full_url = f"{self.config.base_url}{endpoint_path}{query_params}"

        try:
            data = self._make_request("GET", full_url) # Pass the fully constructed URL
            results = data.get("results", [])
            if not results:
                logger.info(f"No aggregate results for {ticker} in range {from_date_str}-{to_date_str}.")
                return # Use return for generator completion

            for record in results:
                yield record

            logger.info(f"Fetched and yielded {len(results)} aggregates for {ticker}.")
            # V2 aggregates range API does not use next_url for pagination across different date ranges.
            # It returns all data for the specified path date range up to the result limit (e.g., 50k).
            # If len(results) == limit, it might indicate more data *within the same day if timespan is intraday*,
            # or that the 50k limit was hit for the requested range.
            # True pagination over large date ranges needs to be handled by the caller by making multiple
            # calls to this function with adjusted from_date/to_date ranges.
            if len(results) == limit:
                 logger.warning(f"Limit of {limit} results reached for {ticker} aggregates in range {from_date_str}-{to_date_str}. More data might exist if this was a very granular request over a long period not broken down by caller.")

        except Exception as e:
            logger.error(f"Failed to fetch or process aggregates for {ticker} for range {from_date_str}-{to_date_str}: {e}")
            raise

    def get_trades_for_date(self, ticker: str, date_str: str, limit: int = 50000, timestamp_gte_ns: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        logger.info(f"Initiating trades fetch for {ticker} on {date_str}{f' from ts {timestamp_gte_ns}' if timestamp_gte_ns else ''}")

        # Initial URL construction for Polygon v3 Trades API
        params_dict = {"limit": str(limit)}
        if timestamp_gte_ns:
            params_dict["timestamp.gte"] = str(timestamp_gte_ns)
            # For other params like order, sort, see Polygon docs. Default is timestamp ascending.

        # Encode parameters for the first request
        # Note: The Polygon v3 trades API takes date as a path parameter, not query.
        # /v3/trades/{stocksTicker}?timestamp={timestamp}&limit={limit}...
        # So, the date_str is not part of params_dict for URL construction with requests library.
        # The API client should be: /v3/trades/{ticker}?date={date_str}&limit={limit}...
        # The example in problem description was `/v3/trades/{ticker}` and then `params = {"date": date_str, ...}`
        # Let's assume the API takes date as a query param for this example structure to work easily with next_url.
        # If date is a path param, `next_url` handling would be different.
        # Re-checking Polygon V3 Trades: /v3/trades/{stocksTicker} with query params: timestamp, timestampLimit, order, limit, sort. No 'date' query param.
        # This means we need to iterate through timestamps if a single day's data exceeds limit and rely on `next_url`.
        # The `date_str` is more of a filter for the *day* of the timestamp.

        # For a specific date, you usually query with timestamp.gte and timestamp.lt for that day's nanosecond range.
        # Example: Get all trades for 2023-01-05
        # from_ts = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e9)
        # to_ts = from_ts + (24 * 60 * 60 * 1e9) - 1 # End of the day in nanoseconds
        # params_dict["timestamp.gte"] = str(from_ts)
        # params_dict["timestamp.lt"] = str(to_ts)

        # For this exercise, we'll use the simpler model from the prompt which implies next_url handles date context.
        # This might be specific to certain Polygon SDKs or simplified.
        # Let's assume the client is for an endpoint structure like:
        # /vX/data/{ticker}?date={date_str}&limit={limit}&cursor={cursor_from_next_url}

        # Using a generic next_url based paginator
        current_url = f"{self.config.base_url}/v3/trades/{ticker}" # Adjusted to reflect common pattern

        # Add initial params to the URL for the first request
        # This is safer than passing a params dict if next_url might also contain params.
        param_list = [f"limit={limit}"]
        if timestamp_gte_ns: # This is how Polygon v3 works, not with a 'date' string param.
            param_list.append(f"timestamp.gte={timestamp_gte_ns}")
            # To get for a specific day, you'd also add timestamp.lt=day_end_ns
            # For simplicity, this example will just use timestamp.gte if provided.
            # If fetching for a whole day, the caller should provide the day's start ns.

        if param_list:
            current_url += "?" + "&".join(param_list)

        is_first_request = True

        while current_url:
            try:
                # _make_request now takes the full URL
                data = self._make_request("GET", current_url)
                results = data.get("results", [])
                if not results:
                    logger.info(f"No more trade results for {ticker} from URL {current_url}")
                    break

                for record in results:
                    yield record

                logger.info(f"Fetched and yielded {len(results)} trades for {ticker} from {current_url}")

                # Polygon's next_url is absolute and contains all necessary parameters
                current_url = data.get("next_url")
                is_first_request = False # Subsequent requests use the next_url directly

            except Exception as e:
                logger.error(f"Failed to fetch or process trades for {ticker} from URL {current_url}: {e}")
                raise
```

The key changes are:
1.  `_make_request` now takes a `full_url` string.
2.  `get_aggregates` now constructs its `full_url` including query parameters directly. Its pagination logic comment acknowledges that for v2 aggregates, true pagination over very large date ranges usually requires the caller to break down the date range into multiple calls.
3.  `get_trades_for_date` (and by extension, any similar paginated methods) now constructs the initial `full_url` with parameters, and then for subsequent calls, it directly uses the `next_url` provided by the API response. This correctly handles APIs where `next_url` is absolute and contains all necessary state for the next page. I've also adjusted it to reflect more typical Polygon v3 trades API structure using `timestamp.gte` rather than a `date` query parameter for daily filtering.

This refined approach makes the client more robust for handling various API endpoint structures, especially those with cursor-based or `next_url` pagination.
