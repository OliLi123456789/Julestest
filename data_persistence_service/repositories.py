# data_persistence_service/repositories.py
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from .db_models import NewsArticleDB, EarningsReportDB # Relative import from same package
import datetime
import pandas as pd # For pd.to_datetime and pd.isna

logger = logging.getLogger(__name__)

class NewsRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_article(self, article_data: Dict[str, Any], related_symbols_list: Optional[List[str]] = None) -> Optional[NewsArticleDB]:
        url = article_data.get("url")
        if not url:
            logger.warning("Article data missing URL. Cannot add. Data: %s", article_data.get("title", "N/A"))
            return None

        existing_article = self.session.query(NewsArticleDB).filter_by(url=url).first()
        if existing_article:
            logger.debug(f"Article with URL {url} already exists. ID: {existing_article.id}. Skipping add.")
            return existing_article

        try:
            published_at_str = article_data.get("publishedAt")
            published_dt: Optional[datetime.datetime] = None
            if published_at_str:
                try:
                    # pd.to_datetime is robust and can handle various ISO formats including those with 'Z'
                    # It converts to Timestamp; .to_pydatetime() converts to Python datetime.
                    # If tz-naive from string, it remains naive. If string has tz, it becomes tz-aware.
                    ts = pd.to_datetime(published_at_str)
                    published_dt = ts.to_pydatetime()
                    # Ensure UTC if it became timezone-aware but not UTC, or make naive UTC if that's the db expectation (not recommended)
                    # For DateTime(timezone=True), SQLAlchemy expects tz-aware datetime objects.
                    if published_dt.tzinfo is None: # If pd.to_datetime resulted in naive datetime
                        published_dt = published_dt.replace(tzinfo=datetime.timezone.utc) # Assume UTC
                    else: # If tz-aware, convert to UTC for storage consistency
                        published_dt = published_dt.astimezone(datetime.timezone.utc)

                except Exception as e_ts:
                    logger.warning(f"Could not parse 'publishedAt' timestamp '{published_at_str}': {e_ts}. Using current UTC time.")
                    published_dt = datetime.datetime.now(datetime.timezone.utc)
            else: # If publishedAt is missing, use current time as a fallback
                logger.warning(f"Article '{article_data.get('title', 'N/A')}' missing 'publishedAt'. Using current UTC time.")
                published_dt = datetime.datetime.now(datetime.timezone.utc)


            db_article = NewsArticleDB(
                source_id=article_data.get("source", {}).get("id"),
                source_name=article_data.get("source", {}).get("name"),
                author=article_data.get("author"),
                title=article_data.get("title"),
                description=article_data.get("description"),
                url=url,
                url_to_image=article_data.get("urlToImage"),
                published_at=published_dt,
                content_snippet=article_data.get("content"),
                related_symbols=",".join(sorted(list(set(s.upper() for s in related_symbols_list)))) if related_symbols_list else None
            )
            self.session.add(db_article)
            self.session.flush() # Get ID if needed before commit (caller handles commit)
            logger.debug(f"Added news article to session: ID {db_article.id} - {db_article.title[:50]}")
            return db_article
        except Exception as e:
            logger.error(f"Error adding news article '{article_data.get('title', 'N/A')}': {e}", exc_info=True)
            return None

    def get_news_by_symbol(self, symbol: str, limit: int = 10,
                              before_date: Optional[datetime.datetime] = None,
                              after_date: Optional[datetime.datetime] = None
                             ) -> List[NewsArticleDB]:
        try:
            query = self.session.query(NewsArticleDB).filter(NewsArticleDB.related_symbols.ilike(f"%{symbol.upper()}%"))
            if before_date: query = query.filter(NewsArticleDB.published_at < before_date)
            if after_date: query = query.filter(NewsArticleDB.published_at > after_date)
            return query.order_by(desc(NewsArticleDB.published_at)).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting news for symbol {symbol}: {e}", exc_info=True)
            return []

    def update_article_sentiment(self, article_id: int, compound_score: float,
                                 neg:float, neu:float, pos:float, provider: str) -> bool:
        try:
            article = self.session.query(NewsArticleDB).filter_by(id=article_id).first()
            if article:
                article.sentiment_score_compound = compound_score
                article.sentiment_score_neg = neg
                article.sentiment_score_neu = neu
                article.sentiment_score_pos = pos
                article.sentiment_provider = provider
                article.fetched_at = datetime.datetime.now(datetime.timezone.utc) # Update timestamp as it's processed
                self.session.flush()
                logger.debug(f"Updated sentiment for article ID {article_id}.")
                return True
            logger.warning(f"Article ID {article_id} not found for sentiment update.")
            return False
        except Exception as e:
            logger.error(f"Error updating sentiment for article ID {article_id}: {e}", exc_info=True)
            return False


class EarningsRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_report(self, report_data: Dict[str, Any], symbol_override: Optional[str] = None, source_api_override: Optional[str] = None) -> Optional[EarningsReportDB]:
        try:
            report_symbol = (symbol_override or report_data.get("symbol", "")).upper()
            report_date_str = report_data.get("date")
            fiscal_date_str = report_data.get("fiscalDateEnding")

            if not report_symbol or not report_date_str:
                logger.warning(f"Cannot add earnings report, missing essential 'symbol' or 'date'. Data: {report_data}")
                return None

            report_dt = pd.to_datetime(report_date_str).date() if pd.notna(report_date_str) else None
            fiscal_dt = pd.to_datetime(fiscal_date_str).date() if pd.notna(fiscal_date_str) else None

            if not report_dt: # After parsing, if still None
                 logger.warning(f"Cannot add earnings report for {report_symbol}, invalid 'date'. Data: {report_data}")
                 return None

            # Check for duplicates based on unique constraint (symbol, report_date, fiscal_period_ending)
            existing_report = self.session.query(EarningsReportDB).filter_by(
                symbol=report_symbol,
                report_date=report_dt,
                fiscal_period_ending=fiscal_dt
            ).first()
            if existing_report:
                logger.debug(f"Earnings report for {report_symbol} on {report_dt} (fiscal {fiscal_dt}) already exists. ID: {existing_report.id}. Skipping.")
                return existing_report

            db_report = EarningsReportDB(
                symbol=report_symbol,
                report_date=report_dt,
                fiscal_period_ending=fiscal_dt,
                time_of_day=str(report_data.get("time", "unspecified")).lower(),
                eps_actual=float(report_data["eps"]) if pd.notna(report_data.get("eps")) else None,
                eps_estimate=float(report_data["epsEstimated"]) if pd.notna(report_data.get("epsEstimated")) else None,
                revenue_actual=float(report_data["revenue"]) if pd.notna(report_data.get("revenue")) else None,
                revenue_estimate=float(report_data["revenueEstimated"]) if pd.notna(report_data.get("revenueEstimated")) else None,
                currency_id=str(report_data.get("currency", "USD")).upper(),
                source_api=source_api_override or "FMP" # Example
            )
            self.session.add(db_report)
            self.session.flush()
            logger.debug(f"Added earnings report to session: ID {db_report.id} - {db_report.symbol} {db_report.report_date}")
            return db_report
        except Exception as e:
            logger.error(f"Error adding earnings report for {report_data.get('symbol', 'N/A')}: {e}", exc_info=True)
            return None

    def get_historical_by_symbol(self, symbol: str, limit: int = 10) -> List[EarningsReportDB]:
        try:
            return self.session.query(EarningsReportDB).filter_by(symbol=symbol.upper()) \
                       .order_by(desc(EarningsReportDB.report_date), desc(EarningsReportDB.fiscal_period_ending)) \
                       .limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting historical earnings for {symbol}: {e}", exc_info=True)
            return []

    def get_calendar_by_date_range(self, from_date: datetime.date, to_date: datetime.date,
                                      symbols: Optional[List[str]] = None) -> List[EarningsReportDB]:
        try:
            query = self.session.query(EarningsReportDB).filter(
                EarningsReportDB.report_date >= from_date,
                EarningsReportDB.report_date <= to_date
            )
            if symbols:
                query = query.filter(EarningsReportDB.symbol.in_([s.upper() for s in symbols]))
            return query.order_by(EarningsReportDB.report_date, EarningsReportDB.symbol).all()
        except Exception as e:
            logger.error(f"Error getting earnings calendar from {from_date} to {to_date}: {e}", exc_info=True)
            return []

if __name__ == '__main__':
    # This block is for direct testing of repositories.
    # It requires db_models.initialize_database() to have been called.
    from .db_models import initialize_database, get_db_session, NewsArticleDB, EarningsReportDB # For testing

    logging.basicConfig(level=logging.DEBUG)
    logger_repo_main = logging.getLogger(__name__)

    engine, DBSessionLocal = initialize_database(db_url="sqlite:///:memory:") # Use in-memory for test

    if not DBSessionLocal:
        logger_repo_main.critical("Failed to initialize database for repository tests.")
        exit()

    db_session = get_db_session()
    if not db_session:
        logger_repo_main.critical("Failed to get DB session for repository tests.")
        exit()

    try:
        # Test NewsRepository
        news_repo = NewsRepository(db_session)
        news_data1 = {"url": "http://example.com/news1", "title": "News 1 Title", "publishedAt": "2023-01-01T12:00:00Z", "source": {"name": "Source1"}}
        news_repo.add_article(news_data1, ["AAPL", "TSLA"])
        news_data2 = {"url": "http://example.com/news2", "title": "News 2 Title", "publishedAt": "2023-01-02T12:00:00Z", "source": {"name": "Source2"}}
        news_repo.add_article(news_data2, ["MSFT"])
        db_session.commit() # Commit changes made by add_article

        aapl_news = news_repo.get_news_by_symbol("AAPL", limit=5)
        logger_repo_main.info(f"AAPL News ({len(aapl_news)}): {[n.title for n in aapl_news]}")
        if aapl_news:
            news_repo.update_article_sentiment(aapl_news[0].id, 0.5, 0.1,0.6,0.3, "TestVader")
            db_session.commit()
            updated_article = db_session.query(NewsArticleDB).filter_by(id=aapl_news[0].id).first()
            logger_repo_main.info(f"Updated AAPL article sentiment: {updated_article.sentiment_score_compound if updated_article else 'Not Found'}")


        # Test EarningsRepository
        earnings_repo = EarningsRepository(db_session)
        er_data1 = {"symbol": "NVDA", "date": "2023-03-01", "eps": 1.0, "epsEstimated": 0.9, "fiscalDateEnding": "2023-02-28"}
        earnings_repo.add_report(er_data1)
        er_data2 = {"symbol": "NVDA", "date": "2022-12-01", "eps": 0.8, "epsEstimated": 0.82, "fiscalDateEnding": "2022-11-30"}
        earnings_repo.add_report(er_data2)
        db_session.commit()

        nvda_earnings = earnings_repo.get_historical_by_symbol("NVDA", limit=5)
        logger_repo_main.info(f"NVDA Earnings ({len(nvda_earnings)}): {[f'{e.report_date}: EPS {e.eps_actual}' for e in nvda_earnings]}")

        cal_from = datetime.date(2023,3,1)
        cal_to = datetime.date(2023,3,1)
        calendar = earnings_repo.get_calendar_by_date_range(cal_from, cal_to, symbols=["NVDA"])
        logger_repo_main.info(f"Calendar for NVDA on {cal_from} ({len(calendar)}): {[e.symbol for e in calendar]}")


    except Exception as e_main:
        logger_repo_main.error(f"Error in repository __main__ example: {e_main}", exc_info=True)
        db_session.rollback()
    finally:
        db_session.close()
