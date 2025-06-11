# news_service/event_protos_alerts.py
import json
import time
from typing import Optional, List, Dict, Any # Added Dict, Any

class SignificantNewsAlert:
    def __init__(self, article_url: str,
                 related_symbols: Optional[List[str]] = None,
                 published_at_iso: str = '',
                 title_snippet: str = '',
                 sentiment_score_compound: float = 0.0,
                 alert_reason: str = '',
                 event_timestamp_utc: Optional[float] = None): # Made event_timestamp_utc optional
        self.article_url = article_url
        self.related_symbols = related_symbols if related_symbols is not None else []
        self.published_at_iso = published_at_iso
        self.title_snippet = title_snippet
        self.sentiment_score_compound = sentiment_score_compound
        self.alert_reason = alert_reason
        self.event_timestamp_utc = event_timestamp_utc if event_timestamp_utc is not None else time.time()

    def SerializeToString(self) -> bytes: # Dummy serialization
        # Ensure all members are serializable; datetime objects would need conversion
        payload = self.__dict__.copy()
        # Example: convert datetime if any were directly stored (not in this class for now)
        # for key, value in payload.items():
        # if isinstance(value, datetime.datetime):
        # payload[key] = value.isoformat()
        return json.dumps(payload).encode('utf-8')

    @classmethod
    def FromString(cls, s: bytes) -> Dict[str, Any]: # Dummy deserialization for testing/logging
        return json.loads(s.decode('utf-8'))


class SignificantEarningsAlert:
    def __init__(self, symbol: str, report_date_iso: str,
                 fiscal_period_ending_iso: Optional[str] = None,
                 eps_actual: Optional[float] = None, eps_estimate: Optional[float] = None,
                 revenue_actual: Optional[float] = None, revenue_estimate: Optional[float] = None,
                 surprise_type: str = '', # e.g., "EPS_BEAT", "REVENUE_MISS"
                 surprise_magnitude_pct: Optional[float] = None, # For EPS surprise %
                 time_of_day: Optional[str] = None, # e.g. "bmo", "amc"
                 event_timestamp_utc: Optional[float] = None): # Made event_timestamp_utc optional
        self.symbol = symbol
        self.report_date_iso = report_date_iso
        self.fiscal_period_ending_iso = fiscal_period_ending
        self.eps_actual = eps_actual
        self.eps_estimate = eps_estimate
        self.revenue_actual = revenue_actual
        self.revenue_estimate = revenue_estimate
        self.surprise_type = surprise_type
        self.surprise_magnitude_pct = surprise_magnitude_pct
        self.time_of_day = time_of_day
        self.event_timestamp_utc = event_timestamp_utc if event_timestamp_utc is not None else time.time()

    def SerializeToString(self) -> bytes: # Dummy serialization
        payload = self.__dict__.copy()
        return json.dumps(payload).encode('utf-8') # Corrected to utf-8

    @classmethod
    def FromString(cls, s: bytes) -> Dict[str, Any]: # Dummy deserialization for testing/logging
        return json.loads(s.decode('utf-8'))

if __name__ == '__main__':
    # Example Usage
    news_alert = SignificantNewsAlert(
        article_url="http://example.com/news/123",
        related_symbols=["AAPL", "MSFT"],
        published_at_iso="2023-10-26T10:00:00Z",
        title_snippet="Big Tech Rally Expected After Positive Inflation Report",
        sentiment_score_compound=0.85,
        alert_reason="STRONG_POSITIVE_SENTIMENT"
    )
    serialized_news = news_alert.SerializeToString()
    print(f"Serialized News Alert: {serialized_news}")
    print(f"Deserialized News Alert: {SignificantNewsAlert.FromString(serialized_news)}")

    earnings_alert = SignificantEarningsAlert(
        symbol="NVDA",
        report_date_iso="2023-11-21",
        fiscal_period_ending_iso="2023-10-31",
        eps_actual=5.02,
        eps_estimate=4.50,
        surprise_type="EPS_BEAT_SIGNIFICANT",
        surprise_magnitude_pct=11.56,
        time_of_day="amc"
    )
    serialized_earnings = earnings_alert.SerializeToString()
    print(f"\nSerialized Earnings Alert: {serialized_earnings}")
    print(f"Deserialized Earnings Alert: {SignificantEarningsAlert.FromString(serialized_earnings)}")
