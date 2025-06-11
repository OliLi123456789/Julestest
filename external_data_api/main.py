# external_data_api/main.py
import logging
from fastapi import FastAPI, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional, Any # Added Any
from datetime import date, datetime, time # Added time

# Attempt to import from data_persistence_service.
# These components are crucial for the API to function.
try:
    from data_persistence_service.repositories import NewsRepository, EarningsRepository
    from data_persistence_service.db_models import NewsArticleDB, EarningsReportDB
    DATA_PERSISTENCE_AVAILABLE = True
except ImportError as e_imp:
    logging.getLogger(__name__).critical(f"Failed to import from data_persistence_service: {e_imp}. API cannot function.", exc_info=True)
    DATA_PERSISTENCE_AVAILABLE = False
    # Define dummy classes for type hints if needed for the rest of the file to be parsable,
    # but the app should not start if these imports fail.
    class NewsRepository: pass
    class EarningsRepository: pass
    class NewsArticleDB: pass
    class EarningsReportDB: pass


from .schemas import NewsArticleResponse, EarningsReportResponse, PaginatedNewsResponse
   from .database_session import get_db, init_external_data_api_db
   from news_service.logging_setup import setup_external_data_logging, EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME # Import shared logging setup

# Configure logging using the shared setup function
# Pass a specific service name override if desired, or it defaults to EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
# For an API service, it's good to have its own root within the shared system.
API_LOGGER_ROOT_NAME = f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.ExternalDataAPI"
setup_external_data_logging(service_name_override=API_LOGGER_ROOT_NAME) # Configures logger named "ExternalDataServices.ExternalDataAPI"
logger = logging.getLogger(f"{API_LOGGER_ROOT_NAME}.main") # Child logger for this specific file

# Application startup event (optional)
# @app.on_event("startup")
# async def startup_event():
#     logger.info("External Data API starting up...")
#     init_external_data_api_db() # Ensures engine is ready, table creation handled by persistence service

app = FastAPI(
    title="External Data API (News & Earnings)",
    version="1.0.0",
    description="Provides access to stored news articles (with sentiment) and company earnings data."
)

if not DATA_PERSISTENCE_AVAILABLE:
    logger.fatal("Data persistence service components not available. API endpoints will not function.")
    # FastAPI app will still load, but endpoints will fail if they rely on these.
    # A more robust approach for production might be to prevent app startup.

# --- News Endpoints ---
@app.get("/news/articles", response_model=PaginatedNewsResponse, summary="Get News Articles")
async def get_news_articles(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by a specific stock symbol (e.g., AAPL). Checks 'related_symbols' field for a case-insensitive match."),
    limit: int = Query(10, ge=1, le=100, description="Number of articles per page."),
    page: int = Query(1, ge=1, description="Page number."),
    since_date: Optional[date] = Query(None, description="Filter articles published on or after this date (YYYY-MM-DD)."),
    until_date: Optional[date] = Query(None, description="Filter articles published on or before this date (YYYY-MM-DD)."),
    min_sentiment_compound: Optional[float] = Query(None, ge=-1.0, le=1.0, description="Minimum compound sentiment score (-1.0 to 1.0)."),
    max_sentiment_compound: Optional[float] = Query(None, ge=-1.0, le=1.0, description="Maximum compound sentiment score (-1.0 to 1.0).")
):
    if not DATA_PERSISTENCE_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data persistence service is unavailable.")

    repo = NewsRepository(db)

    # Convert date to datetime for repository if needed, or ensure repo handles date objects
    # For published_at which is DateTime, we need to ensure the range covers the whole day(s).
    since_datetime: Optional[datetime] = None
    if since_date:
        since_datetime = datetime.combine(since_date, time.min) # Start of the day

    until_datetime: Optional[datetime] = None
    if until_date:
        until_datetime = datetime.combine(until_date, time.max) # End of the day

    # Build query filters dynamically
    filters = []
    if symbol:
        filters.append(NewsArticleDB.related_symbols.ilike(f"%{symbol.upper()}%"))
    if since_datetime:
        filters.append(NewsArticleDB.published_at >= since_datetime)
    if until_datetime:
        filters.append(NewsArticleDB.published_at <= until_datetime)
    if min_sentiment_compound is not None:
        filters.append(NewsArticleDB.sentiment_score_compound >= min_sentiment_compound)
    if max_sentiment_compound is not None:
        filters.append(NewsArticleDB.sentiment_score_compound <= max_sentiment_compound)

    query = db.query(NewsArticleDB)
    if filters:
        query = query.filter(*filters) # Unpack list of filters

    total_items = query.count()

    offset = (page - 1) * limit
    db_articles = query.order_by(NewsArticleDB.published_at.desc()).offset(offset).limit(limit).all()

    items_response = [NewsArticleResponse.from_orm(art) for art in db_articles]
    total_pages = (total_items + limit - 1) // limit if limit > 0 else 0

    return PaginatedNewsResponse(
        page=page, page_size=limit, total_items=total_items,
        total_pages=total_pages, items=items_response
    )

@app.get("/news/articles/{article_id}", response_model=NewsArticleResponse, summary="Get Specific News Article by ID")
async def get_news_article_by_id(article_id: int, db: Session = Depends(get_db)):
    if not DATA_PERSISTENCE_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data persistence service is unavailable.")

    # NewsRepository doesn't have get_by_id, use session query directly
    db_article = db.query(NewsArticleDB).filter(NewsArticleDB.id == article_id).first()
    if not db_article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News article not found")
    return NewsArticleResponse.from_orm(db_article)


# --- Earnings Endpoints ---
@app.get("/earnings/calendar", response_model=List[EarningsReportResponse], summary="Get Earnings Calendar for a Date Range")
async def get_earnings_calendar(
    db: Session = Depends(get_db),
    from_date: date = Query(..., description="Start date for calendar (YYYY-MM-DD). Example: 2023-10-01"),
    to_date: date = Query(..., description="End date for calendar (YYYY-MM-DD). Example: 2023-10-31"),
    symbols: Optional[List[str]] = Query(None, description="Optional list of symbols to filter for (e.g., ['AAPL', 'MSFT']).")
):
    if not DATA_PERSISTENCE_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data persistence service is unavailable.")

    repo = EarningsRepository(db)
    db_reports = repo.get_calendar_by_date_range(from_date=from_date, to_date=to_date, symbols=symbols)
    return [EarningsReportResponse.from_orm(rep) for rep in db_reports]


@app.get("/earnings/reports/{symbol}", response_model=List[EarningsReportResponse], summary="Get Historical Earnings Reports for a Symbol")
async def get_historical_earnings_for_symbol(
    symbol: str,
    db: Session = Depends(get_db),
    limit: int = Query(4, ge=1, le=20, description="Number of past reports to retrieve (most recent first).")
):
    if not DATA_PERSISTENCE_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data persistence service is unavailable.")

    repo = EarningsRepository(db)
    db_reports = repo.get_historical_by_symbol(symbol=symbol.upper(), limit=limit)
    # No HTTPException for not found, just return empty list as per repository behavior
    return [EarningsReportResponse.from_orm(rep) for rep in db_reports]

@app.get("/")
async def root():
    return {"message": "External Data API (News & Earnings) running. Visit /docs for interactive API documentation."}

# To run this FastAPI app (example):
# Ensure data_persistence_service is in PYTHONPATH or installed.
# Set EXTERNAL_DATA_API_DB_URL if not using default SQLite.
# uvicorn external_data_api.main:app --reload --port 8002 --host 0.0.0.0
# (Assuming this service runs on a different port, e.g., 8002, than the main webapp backend)
