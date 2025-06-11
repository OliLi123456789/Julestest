# data_persistence_service/db_models.py
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Date, Text, Index, UniqueConstraint, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
# from sqlalchemy.dialects.postgresql import JSONB # Example for PostgreSQL specific JSON type
from typing import Optional, List, Dict, Any # For type hints in conversion methods
import os # For DB_URL example

Base = declarative_base()

class NewsArticleDB(Base):
    __tablename__ = "news_articles"
    id = Column(Integer, primary_key=True, autoincrement=True)

    source_id = Column(String(100), nullable=True)
    source_name = Column(String(255), nullable=True)
    author = Column(String(255), nullable=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String(1024), nullable=False, unique=True, index=True) # Ensure URL is unique and indexed
    url_to_image = Column(String(1024), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, index=True) # Store as timezone-aware UTC
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    content_snippet = Column(Text, nullable=True)

    sentiment_score_compound = Column(Float, nullable=True, index=True)
    sentiment_score_neg = Column(Float, nullable=True)
    sentiment_score_neu = Column(Float, nullable=True)
    sentiment_score_pos = Column(Float, nullable=True)
    sentiment_provider = Column(String(50), nullable=True)

    related_symbols = Column(Text, nullable=True, index=True) # e.g., "AAPL,MSFT"

    __table_args__ = (
        Index('ix_news_articles_published_at_desc', published_at.desc()),
        # Potentially add index on (related_symbols, published_at) if querying by symbol and date often
    )

    def __repr__(self):
        return f"<NewsArticleDB(id={self.id}, title='{self.title[:50]}...', url='{self.url}')>"

    def to_dict(self) -> Dict[str, Any]: # Helper for API responses or logging
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        # Convert datetime objects to ISO format strings
        for key, value in data.items():
            if isinstance(value, (datetime.datetime, datetime.date)):
                data[key] = value.isoformat()
        return data


class EarningsReportDB(Base):
    __tablename__ = "earnings_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False, index=True)
    report_date = Column(Date, nullable=False, index=True) # Actual date of report/announcement
    fiscal_period_ending = Column(Date, nullable=True)
    time_of_day = Column(String(10), nullable=True) # "bmo", "amc", "market", "unspecified"

    eps_actual = Column(Float, nullable=True)
    eps_estimate = Column(Float, nullable=True)
    revenue_actual = Column(Float, nullable=True)
    revenue_estimate = Column(Float, nullable=True)
    currency_id = Column(String(10), nullable=True, default="USD")

    source_api = Column(String(100), nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint('symbol', 'report_date', 'fiscal_period_ending', name='uq_symbol_report_fperiod'),
        Index('ix_earnings_reports_symbol_report_date_desc', symbol, report_date.desc()),
    )

    def __repr__(self):
        return f"<EarningsReportDB(id={self.id}, symbol='{self.symbol}', report_date='{self.report_date}', eps_actual={self.eps_actual})>"

    def to_dict(self) -> Dict[str, Any]:
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        for key, value in data.items():
            if isinstance(value, (datetime.datetime, datetime.date)):
                data[key] = value.isoformat()
        return data

# --- Database Setup (example, usually in a central db_setup.py or app initialization) ---
# Example using SQLite in memory for quick testing, or a file-based DB.
# For PostgreSQL, connection string would be different e.g. "postgresql://user:password@host:port/database"
DEFAULT_DB_URL = "sqlite:///./data_persistence_service.db" # File in current dir of execution
DB_URL = os.getenv("PERSISTENCE_DB_URL", DEFAULT_DB_URL)

# Global engine and session factory - can be initialized by the application.
# For simplicity in this module, they can be defined here but ideally managed by an app context.
engine = None
DBSessionLocal = None

def get_db_session() -> Optional[Session]: # Added type hint for Session
    from sqlalchemy.orm import Session # Local import for type hint
    if DBSessionLocal:
        return DBSessionLocal()
    return None # Or raise exception if not initialized

def initialize_database(db_url: str = DB_URL, create_tables: bool = True):
    """Initializes the database engine and session, and optionally creates tables."""
    global engine, DBSessionLocal
    if engine is not None and str(engine.url) == db_url and DBSessionLocal is not None:
        # logging.getLogger(__name__).info(f"Database already initialized with URL: {db_url}")
        return

    logging.getLogger(__name__).info(f"Initializing database with URL: {db_url}")
    engine = create_engine(db_url) #, connect_args={"check_same_thread": False} for SQLite)
    DBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    if create_tables:
        try:
            Base.metadata.create_all(bind=engine)
            logging.getLogger(__name__).info("Database tables created (if they didn't exist).")
        except Exception as e:
            logging.getLogger(__name__).error(f"Error creating database tables: {e}", exc_info=True)
            # Depending on severity, might want to raise this
    return engine, DBSessionLocal


if __name__ == '__main__':
    # Example of initializing and using the models
    logging.basicConfig(level=logging.INFO)
    logger_main = logging.getLogger(__name__)

    # Initialize DB (creates sqlite file in current dir if it doesn't exist)
    initialize_database() # Use default DB_URL

    session = get_db_session()
    if session:
        try:
            # Example: Add a news article
            sample_article_data = {
                "source": {"id": "test-src", "name": "Test Source"},
                "author": "Test Author",
                "title": "SQLAlchemy Models Test Article",
                "description": "Testing the NewsArticleDB model.",
                "url": "http://example.com/sqlalchemy_test_article_" + datetime.datetime.now().isoformat(), # Unique URL
                "urlToImage": "http://example.com/image.jpg",
                "publishedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), # ISO string
                "content": "This is the full content snippet."
            }

            # Convert publishedAt to datetime object
            pub_dt = datetime.datetime.fromisoformat(sample_article_data["publishedAt"].replace("Z", "+00:00"))

            new_article = NewsArticleDB(
                source_id=sample_article_data["source"]["id"],
                source_name=sample_article_data["source"]["name"],
                author=sample_article_data["author"],
                title=sample_article_data["title"],
                description=sample_article_data["description"],
                url=sample_article_data["url"],
                url_to_image=sample_article_data["urlToImage"],
                published_at=pub_dt,
                content_snippet=sample_article_data["content"],
                related_symbols="TEST,EXAMPLE"
            )
            session.add(new_article)
            session.commit()
            logger_main.info(f"Added sample news article: {new_article.id} - {new_article.title}")

            # Example: Add an earnings report
            sample_earnings_data = {
                "symbol": "TEST",
                "date": datetime.date.today().isoformat(),
                "fiscalDateEnding": (datetime.date.today() - datetime.timedelta(days=90)).isoformat(),
                "time": "amc",
                "eps": 1.25,
                "epsEstimated": 1.20,
                "revenue": 1e9,
                "revenueEstimated": 0.98e9
            }
            new_earnings = EarningsReportDB(
                symbol=sample_earnings_data["symbol"],
                report_date=datetime.date.fromisoformat(sample_earnings_data["date"]),
                fiscal_period_ending=datetime.date.fromisoformat(sample_earnings_data["fiscalDateEnding"]),
                time_of_day=sample_earnings_data["time"],
                eps_actual=sample_earnings_data["eps"],
                eps_estimate=sample_earnings_data["epsEstimated"],
                revenue_actual=sample_earnings_data["revenue"],
                revenue_estimate=sample_earnings_data["revenueEstimated"],
                source_api="TestFramework"
            )
            session.add(new_earnings)
            session.commit()
            logger_main.info(f"Added sample earnings report: {new_earnings.id} - {new_earnings.symbol}")

            # Query back
            retrieved_article = session.query(NewsArticleDB).filter_by(id=new_article.id).first()
            logger_main.info(f"Retrieved: {retrieved_article.to_dict()}")
            retrieved_earnings = session.query(EarningsReportDB).filter_by(id=new_earnings.id).first()
            logger_main.info(f"Retrieved: {retrieved_earnings.to_dict()}")

        except Exception as e:
            logger_main.error(f"Error in __main__ example: {e}", exc_info=True)
            session.rollback()
        finally:
            session.close()
    else:
        logger_main.error("Could not get DB session.")
