# webapp/backend/config_web.py
import os

class AppConfig:
    PROJECT_NAME: str = "Trading Platform Web API"
    VERSION: str = "0.1.0"

    # JWT Settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-for-dev-webapp-change-me") # Ensure unique secret
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # CORS Settings
    ALLOWED_CORS_ORIGINS_STR: str = os.getenv("ALLOWED_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000") # Frontend dev server
    ALLOWED_CORS_ORIGINS: list[str] = [origin.strip() for origin in ALLOWED_CORS_ORIGINS_STR.split(",") if origin.strip()]

    # Rate Limiting default
    DEFAULT_RATE_LIMIT: str = os.getenv("DEFAULT_RATE_LIMIT", "100/minute")

    # Kafka Settings (merged from previous kafka_config_web.py)
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    # Producer topic
    KAFKA_NEW_ORDERS_TOPIC: str = os.getenv("KAFKA_NEW_ORDERS_TOPIC", "trading.new-orders")

    # Consumer topics (previously in event_consumer_service.py, now centralized)
    KAFKA_ORDER_STATUS_UPDATES_TOPIC: str = os.getenv("KAFKA_ORDER_STATUS_UPDATES_TOPIC", "ibkr.order-updates")
    KAFKA_EXECUTION_REPORTS_TOPIC: str = os.getenv("KAFKA_EXECUTION_REPORTS_TOPIC", "ibkr.execution-reports")
    KAFKA_POSITION_DATA_TOPIC: str = os.getenv("KAFKA_POSITION_DATA_TOPIC", "ibkr.position-data")
    KAFKA_ACCOUNT_DATA_TOPIC: str = os.getenv("KAFKA_ACCOUNT_DATA_TOPIC", "ibkr.account-data") # New topic for account summary/value updates
    KAFKA_WEBAPP_CONSUMER_GROUP: str = os.getenv("KAFKA_WEBAPP_CONSUMER_GROUP", "webapp_backend_event_group_1")


app_config = AppConfig() # Singleton instance for easy import

# Note: KafkaWebBackendConfig class is no longer needed as its settings are merged here.
# Services (WebOrderProducer, WebAppEventConsumerService) will be updated to use app_config directly.
