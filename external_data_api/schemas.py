# external_data_api/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime, date

class NewsArticleResponse(BaseModel):
    id: int
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    author: Optional[str] = None
    title: str
    description: Optional[str] = None
    url: str
    url_to_image: Optional[str] = None
    published_at: datetime # Expecting timezone-aware datetime
    fetched_at: datetime   # Expecting timezone-aware datetime
    content_snippet: Optional[str] = None
    sentiment_score_compound: Optional[float] = None
    sentiment_score_neg: Optional[float] = None
    sentiment_score_neu: Optional[float] = None
    sentiment_score_pos: Optional[float] = None
    sentiment_provider: Optional[str] = None
    related_symbols: Optional[str] = None # Comma-separated string

    class Config:
        orm_mode = True # For easy conversion from SQLAlchemy model

class PaginatedNewsResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: List[NewsArticleResponse]


class EarningsReportResponse(BaseModel):
    id: int
    symbol: str
    report_date: date
    fiscal_period_ending: Optional[date] = None
    time_of_day: Optional[str] = None
    eps_actual: Optional[float] = None
    eps_estimate: Optional[float] = None
    revenue_actual: Optional[float] = None
    revenue_estimate: Optional[float] = None
    currency_id: Optional[str] = "USD"
    source_api: Optional[str] = None
    fetched_at: datetime # Expecting timezone-aware datetime

    class Config:
        orm_mode = True
