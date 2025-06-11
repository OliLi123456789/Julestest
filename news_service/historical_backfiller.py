# news_service/historical_backfiller.py
import logging
import datetime
import time
import pandas as pd
from typing import List, Optional, Dict, Any, Callable
import os
import sys

# Assuming services and configs are accessible in PYTHONPATH
from .config_news import news_service_config, earnings_config # Import both configs
from .news_fetcher import NewsFetcher
from .sentiment_pipeline import NewsSentimentPipeline
from .earnings_fetcher import EarningsFetcher # Added

try:
    from data_persistence_service.repositories import NewsRepository, EarningsRepository # Added EarningsRepository
    from data_persistence_service.db_models import initialize_database, get_db_session, DEFAULT_DB_URL
    DATA_PERSISTENCE_AVAILABLE = True
except ImportError as e:
    logging.getLogger(__name__).error(f"Failed to import from data_persistence_service: {e}. Backfiller cannot run.", exc_info=True)
    DATA_PERSISTENCE_AVAILABLE = False
    class NewsRepository: pass
    class EarningsRepository: pass # Dummy for type hints
    def initialize_database(db_url,create_tables): pass
    def get_db_session(db_url=None): pass
    DEFAULT_DB_URL = "sqlite:///./dummy_backfill_db.db"

# Use hierarchical logger based on the new logging setup
try:
    from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.historical_backfiller")
except ImportError: # Fallback if logging_setup is not available
    logger = logging.getLogger(__name__)


class HistoricalNewsBackfiller:
    def __init__(self, db_session_provider: Callable[[], Optional[Any]], config: Optional[Any] = None):
        if not DATA_PERSISTENCE_AVAILABLE:
            raise RuntimeError("Data persistence components not available. HistoricalNewsBackfiller cannot operate.")
        self.get_session = db_session_provider
        self.config = config if config else news_service_config
        self.news_fetcher = NewsFetcher(
            api_key=self.config.news_api_key,
            base_url=self.config.news_api_base_url
        )
        logger.info(f"HistoricalNewsBackfiller initialized. NewsFetcher using API key: {'Set' if self.config.news_api_key else 'Not Set'}")

    def backfill_news(self, queries_or_symbols: List[str],
                      start_date_str: str, end_date_str: str,
                      articles_per_query_per_day_limit: int = 10,
                      days_per_step: int = 1):
        try:
            start_date_overall = pd.to_datetime(start_date_str, errors='coerce').tz_localize('UTC')
            end_date_overall = pd.to_datetime(end_date_str, errors='coerce').tz_localize('UTC')
            if pd.NaT in [start_date_overall, end_date_overall]:
                logger.error(f"Invalid start_date '{start_date_str}' or end_date '{end_date_str}'. Aborting news backfill.")
                return
        except Exception as e_date:
            logger.error(f"Error parsing date strings for news backfill '{start_date_str}', '{end_date_str}': {e_date}", exc_info=True)
            return

        logger.info(f"Starting historical news backfill for {len(queries_or_symbols)} queries/symbols from {start_date_overall.date()} to {end_date_overall.date()}.")
        for query_or_symbol in queries_or_symbols:
            logger.info(f"News Backfill - Processing query/symbol: '{query_or_symbol}'")
            current_period_start = start_date_overall
            while current_period_start <= end_date_overall:
                current_period_end = current_period_start + pd.Timedelta(days=days_per_step -1)
                if current_period_end > end_date_overall: current_period_end = end_date_overall
                period_start_api_str = current_period_start.strftime('%Y-%m-%d')
                period_end_api_str = current_period_end.strftime('%Y-%m-%d')
                logger.info(f"  Fetching news for period: {period_start_api_str} to {period_end_api_str} for '{query_or_symbol}'")
                num_pages_to_fetch = (articles_per_query_per_day_limit + 99) // 100
                page_size_api = min(articles_per_query_per_day_limit, 100)
                fetched_articles = self.news_fetcher.fetch_news(
                    query=query_or_symbol, from_date=period_start_api_str, to_date=period_end_api_str,
                    page_size=page_size_api, max_pages=num_pages_to_fetch, sort_by="publishedAt"
                )
                if fetched_articles:
                    logger.info(f"    Fetched {len(fetched_articles)} articles for '{query_or_symbol}'.")
                    session = self.get_session()
                    if not session: logger.error("Could not get DB session for saving articles."); continue
                    news_repo = NewsRepository(session)
                    for article_data in fetched_articles:
                        related_syms = [query_or_symbol.upper()] if query_or_symbol.isalnum() and not any(c in query_or_symbol for c in [' ', '&', '|']) else None
                        news_repo.add_article(article_data, related_symbols_list=related_syms)
                    try: session.commit(); logger.info(f"    Committed {len(fetched_articles)} fetched articles for '{query_or_symbol}'.")
                    except Exception as e_commit: logger.error(f"    Error committing articles: {e_commit}", exc_info=True); session.rollback()
                    finally: session.close()
                else: logger.info(f"    No articles found for '{query_or_symbol}' in period.")
                current_period_start = current_period_end + pd.Timedelta(days=1)
                if current_period_start > end_date_overall: break
                if self.config.news_api_key and not self.news_fetcher.use_mock : time.sleep(1)
            if self.config.news_api_key and not self.news_fetcher.use_mock and len(queries_or_symbols) > 1 : time.sleep(3)
        logger.info("Historical news backfill process finished.")

class HistoricalEarningsBackfiller:
    def __init__(self, db_session_provider: Callable[[], Optional[Any]], config: Optional[Any] = None):
        if not DATA_PERSISTENCE_AVAILABLE:
            raise RuntimeError("Data persistence components not available. HistoricalEarningsBackfiller cannot operate.")
        self.get_session = db_session_provider
        self.config = config if config else earnings_config # Use earnings_config by default
        self.earnings_fetcher = EarningsFetcher(
            api_key=self.config.api_key, # Uses EARNINGS_API_KEY from earnings_config
            base_url=self.config.base_url
        )
        logger.info(f"HistoricalEarningsBackfiller initialized. EarningsFetcher using API key: {'Set' if self.config.api_key else 'Not Set'}")

    def backfill_earnings(self, symbols: List[str], history_limit_per_symbol: Optional[int] = None):
        limit_to_fetch = history_limit_per_symbol if history_limit_per_symbol is not None \
                         else self.config.history_limit_default

        logger.info(f"Starting historical earnings backfill for {len(symbols)} symbols (limit: {limit_to_fetch} reports each).")

        for symbol_upper in [s.upper() for s in symbols]: # Standardize to uppercase
            logger.info(f"  Fetching historical earnings for symbol: {symbol_upper}")

            fetched_reports = self.earnings_fetcher.fetch_historical_earnings(
                symbol=symbol_upper,
                limit=limit_to_fetch
            )

            if fetched_reports:
                logger.info(f"    Fetched {len(fetched_reports)} earnings reports for {symbol_upper}.")
                session = self.get_session()
                if not session:
                    logger.error(f"Could not get DB session for saving earnings for {symbol_upper}. Skipping this symbol."); continue

                earnings_repo = EarningsRepository(session)
                # from .earnings_processor_service import EarningsProcessorService # Optional: If alerts needed
                # earnings_processor = EarningsProcessorService(session) # If using processor

                processed_count_for_symbol = 0
                for report_data in fetched_reports:
                    # add_report checks for duplicates. Pass symbol_override for consistency.
                    db_report = earnings_repo.add_report(report_data, symbol_override=symbol_upper)
                    # Or use processor:
                    # db_report = earnings_processor.add_and_alert_earnings_report(report_data, symbol_override=symbol_upper)

                    if db_report: # add_report returns instance if added or existing
                        processed_count_for_symbol +=1

                try:
                    session.commit()
                    logger.info(f"    Committed {processed_count_for_symbol} processed (new/existing) earnings reports for {symbol_upper} to DB.")
                except Exception as e_commit:
                    logger.error(f"    Error committing earnings reports for {symbol_upper}: {e_commit}", exc_info=True)
                    session.rollback()
                finally:
                    session.close()
            else:
                logger.info(f"    No historical earnings reports found (or fetched) for {symbol_upper}.")

            # Courtesy delay between symbols if hitting a live API
            if self.config.api_key and not self.earnings_fetcher.use_mock and len(symbols) > 1:
                time.sleep(1) # Adjust as per API rate limits

        logger.info("Historical earnings backfill process finished.")


if __name__ == "__main__":
    # Setup logging using the new centralized setup function
    try:
        from .logging_setup import setup_external_data_logging
        # Configure root "ExternalDataServices" logger; child loggers will inherit if not explicitly configured.
        setup_external_data_logging(log_level_str="DEBUG", force_reconfigure_root=True)
    except ImportError:
        # Fallback to basicConfig if setup function is not found (e.g. testing file in isolation)
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')

    # This script's own logger will now use the above configuration if EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME was used in getLogger
    # or it will use the basicConfig if __name__ was used for the logger instance.
    # For consistency, ensure this main_logger uses the hierarchy if possible.
    main_logger_name = f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.__main_backfiller__" if 'EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME' in globals() else __name__
    main_logger = logging.getLogger(main_logger_name)


    if not DATA_PERSISTENCE_AVAILABLE:
        main_logger.critical("Data persistence service components not available. Backfiller script cannot run.")
        sys.exit(1)

    db_url_to_use = os.getenv("BACKFILL_DB_URL", DEFAULT_DB_URL) # Use default from db_models
    pipeline_instance = None
    session_for_pipeline = None
    earnings_backfill_instance = None # For closing producer if it were part of it

    try:
        engine, DBSessionLocal_from_init = initialize_database(db_url=db_url_to_use, create_tables=True)
        if not DBSessionLocal_from_init:
            logger.critical(f"Failed to get DBSessionLocal factory from initialize_database({db_url_to_use}). Exiting."); sys.exit(1)
        logger.info(f"Database initialized/checked at {db_url_to_use}")

        def session_provider_main() -> Optional[Any]: return DBSessionLocal_from_init()

        # --- Run News Backfill (Example) ---
        news_backfiller = HistoricalNewsBackfiller(session_provider_main, config=news_service_config)
        news_start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
        news_end = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        if news_service_config.news_api_key is None: # Use wider range for mock
            news_start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).strftime('%Y-%m-%d')

        logger.info(f"\n--- Starting Historical News Backfill ({news_start} to {news_end}) ---")
        news_backfiller.backfill_news(
            queries_or_symbols=["NVDA", "semiconductor industry"],
            start_date_str=news_start, end_date_str=news_end,
            articles_per_query_per_day_limit=5, days_per_step=3
        )

        # --- Trigger Sentiment Analysis ---
        logger.info("\n--- Starting Sentiment Analysis Pipeline ---")
        session_for_pipeline = session_provider_main()
        if session_for_pipeline:
            try:
                pipeline_instance = NewsSentimentPipeline(session_for_pipeline)
                processed_sentiment_count = pipeline_instance.process_articles_batch(batch_size=50, max_articles_to_process=200)
                logger.info(f"Sentiment pipeline processed {processed_sentiment_count} articles.")
            except Exception as e_sentiment: logger.error(f"Error in sentiment pipeline: {e_sentiment}", exc_info=True); session_for_pipeline.rollback()
            finally:
                if pipeline_instance: pipeline_instance.close_producers()
                if session_for_pipeline: session_for_pipeline.close()
        else: logger.error("Failed to get DB session for sentiment pipeline.")

        # --- Run Earnings Backfill (Example) ---
        logger.info("\n--- Starting Historical Earnings Backfill ---")
        # Pass earnings_config specifically to use its API key and defaults
        earnings_backfiller = HistoricalEarningsBackfiller(session_provider_main, config=earnings_config)
        symbols_for_earnings = ["AAPL", "MSFT", "NVDA", "AMD"]
        earnings_backfiller.backfill_earnings(
            symbols=symbols_for_earnings,
            history_limit_per_symbol=earnings_config.history_limit_default # Use configured default limit
        )
        # If EarningsProcessorService was used, it would have its own producer to close:
        # if earnings_backfiller.earnings_processor: earnings_backfiller.earnings_processor.close_producer()


    except Exception as e_main_backfill:
        logger.critical(f"Critical error in historical backfilling script: {e_main_backfill}", exc_info=True)
    finally:
        logger.info("Historical backfilling script (__main__) finished execution.")
        # Clean up test DB if it's a uniquely named file-based SQLite for this test run
        if db_url_to_use.startswith("sqlite:///") and ":memory:" not in db_url_to_use:
            db_file_path = db_url_to_use.replace("sqlite:///", "")
            # Add a check if it was a test-specific DB before removing, e.g. by name pattern
            # if "backfill_test_db_" in db_file_path and os.path.exists(db_file_path):
            #    os.remove(db_file_path)
            #    logger.info(f"Cleaned up test database: {db_file_path}")
