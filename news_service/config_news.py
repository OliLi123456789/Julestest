# news_service/config_news.py
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class BaseExternalServiceConfig:
    """
    Base configuration class for common settings like Kafka.
    """
    def __init__(self):
        self.kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        # Example: if a shared DB was used by multiple services defined here:
        # self.shared_db_url: str = os.getenv("SHARED_EXTERNAL_SERVICES_DB_URL", "sqlite:///./shared_external.db")

class NewsServiceConfig(BaseExternalServiceConfig): # Inherit from Base
    def __init__(self):
        super().__init__() # Initialize base configs like Kafka
        self.news_api_key: Optional[str] = os.getenv("NEWS_API_KEY")
        self.news_api_base_url: str = os.getenv("NEWS_API_BASE_URL", "https://newsapi.org/v2/")

        try:
            self.default_news_page_size: int = int(os.getenv("NEWS_DEFAULT_PAGE_SIZE", "100"))
        except ValueError:
            logger.warning(f"Invalid NEWS_DEFAULT_PAGE_SIZE: '{os.getenv('NEWS_DEFAULT_PAGE_SIZE')}'. Defaulting to 100.")
            self.default_news_page_size = 100

        self.default_news_sort_by: str = os.getenv("NEWS_DEFAULT_SORT_BY", "publishedAt")
        self.default_news_language: str = os.getenv("NEWS_DEFAULT_LANGUAGE", "en")

        if not self.news_api_key:
            logger.warning("NEWS_API_KEY environment variable not set. NewsFetcher may use mock data or fail live requests if not overridden.")

        self.kafka_alerts_news_topic: str = os.getenv("KAFKA_ALERTS_NEWS_TOPIC", "platform.alerts.news")
        try:
            self.news_sentiment_alert_threshold_positive: float = float(os.getenv("NEWS_SENTIMENT_ALERT_THRESHOLD_POSITIVE", "0.7"))
            self.news_sentiment_alert_threshold_negative: float = float(os.getenv("NEWS_SENTIMENT_ALERT_THRESHOLD_NEGATIVE", "-0.5"))
        except ValueError:
            logger.warning("Invalid news sentiment alert threshold env var. Using defaults.")
            self.news_sentiment_alert_threshold_positive = 0.7
            self.news_sentiment_alert_threshold_negative = -0.5
        # kafka_bootstrap_servers is inherited from BaseExternalServiceConfig

news_service_config = NewsServiceConfig()

class EarningsConfig(BaseExternalServiceConfig): # Inherit from Base
    def __init__(self):
        super().__init__() # Initialize base configs like Kafka
        # Renamed earnings_api_key to api_key for consistency if this class is used directly
        self.api_key: Optional[str] = os.getenv("EARNINGS_API_KEY")
        self.base_url: str = os.getenv("EARNINGS_API_BASE_URL", "https://financialmodelingprep.com/api/v3/")

        try:
            self.history_limit_default: int = int(os.getenv("EARNINGS_HISTORY_LIMIT_DEFAULT", "4"))
        except ValueError:
            logger.warning(f"Invalid EARNINGS_HISTORY_LIMIT_DEFAULT: '{os.getenv('EARNINGS_HISTORY_LIMIT_DEFAULT')}'. Defaulting to 4.")
            self.history_limit_default = 4

        if not self.api_key:
            logger.warning("EARNINGS_API_KEY environment variable not set. EarningsFetcher will use mock data if not overridden.")

        self.kafka_alerts_earnings_topic: str = os.getenv("KAFKA_ALERTS_EARNINGS_TOPIC", "platform.alerts.earnings")
        try:
            self.earnings_eps_surprise_pct_threshold: float = float(os.getenv("EARNINGS_EPS_SURPRISE_PCT_THRESHOLD", "5.0"))
        except ValueError:
            logger.warning("Invalid earnings EPS surprise threshold env var. Using default 5.0%.")
            self.earnings_eps_surprise_pct_threshold = 5.0
        # kafka_bootstrap_servers is inherited from BaseExternalServiceConfig

earnings_config = EarningsConfig()

# Optional: A single combined config instance if preferred by other modules for convenience.
# This would require ExternalDataPlatformConfig class as outlined in the prompt.
# For now, other modules can import news_service_config or earnings_config as needed.
# combined_external_data_config = ExternalDataPlatformConfig() # If that class was defined
# logger.info(f"Kafka Bootstrap Servers (via news_service_config): {news_service_config.kafka_bootstrap_servers}")
# logger.info(f"Kafka Bootstrap Servers (via earnings_config): {earnings_config.kafka_bootstrap_servers}")
# Note: The file name `config_news.py` might be better as `external_data_configs.py` now.
# This change is not made in this step but noted.
