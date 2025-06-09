import os
import logging
from typing import List, Optional

# Assuming secrets.py is in historical_ingestor.utils
from .utils.secrets import get_secret

logger = logging.getLogger(__name__)

class PolygonRESTConfig:
    api_key: str
    base_url: str = "https://api.polygon.io"
    # Polygon's free tier limit is 5 requests/minute. Paid plans are higher.
    # For a production historical ingestor, we'd use a paid plan with higher limits.
    requests_per_minute_limit: int
    timeout_seconds: int = 30
    max_retries: int = 3 # For transient network errors

class KafkaConfig:
    bootstrap_servers: str
    trade_topic: str
    quote_topic: str
    aggregate_topic: str
    # Optional: Security settings (SASL/SSL)
    # security_protocol: Optional[str] = None
    # sasl_mechanism: Optional[str] = None
    # sasl_username_secret_name: Optional[str] = None # Name of secret for Kafka username
    # sasl_password_secret_name: Optional[str] = None # Name of secret for Kafka password
    # Actual username/password will be loaded if secret names are provided
    # sasl_username: Optional[str] = None
    # sasl_password: Optional[str] = None
    producer_linger_ms: int = 100
    producer_retries: int = 3


class Config:
    polygon_rest: PolygonRESTConfig
    kafka: KafkaConfig
    aws_region: str
    log_level: str = "INFO"

def load_config() -> Config:
    aws_region = os.getenv("AWS_REGION")
    if not aws_region:
        logger.warning("AWS_REGION environment variable not set, using default 'us-east-1'")
        aws_region = "us-east-1"

    polygon_api_key_secret_name = os.getenv("POLYGON_API_KEY_SECRET_NAME")
    if not polygon_api_key_secret_name:
        logger.error("POLYGON_API_KEY_SECRET_NAME environment variable must be set.")
        raise ValueError("POLYGON_API_KEY_SECRET_NAME env var not set")

    try:
        polygon_api_key = get_secret(polygon_api_key_secret_name, aws_region)
        if not polygon_api_key:
            raise ValueError(f"Polygon API key from secret '{polygon_api_key_secret_name}' is empty.")
    except Exception as e:
        logger.error(f"Failed to load Polygon API key from secret '{polygon_api_key_secret_name}': {e}")
        raise

    # --- Polygon REST Config ---
    polygon_config = PolygonRESTConfig(
        api_key=polygon_api_key,
        requests_per_minute_limit=int(os.getenv("POLYGON_REQUESTS_PER_MINUTE", "500")), # Default for paid plans
        timeout_seconds=int(os.getenv("POLYGON_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("POLYGON_MAX_RETRIES", "3"))
    )
    polygon_config.base_url = os.getenv("POLYGON_BASE_URL", "https://api.polygon.io")


    # --- Kafka Config ---
    kafka_cfg = KafkaConfig(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        trade_topic=os.getenv("KAFKA_TRADE_TOPIC", "marketdata.trades"),
        quote_topic=os.getenv("KAFKA_QUOTE_TOPIC", "marketdata.quotes"),
        aggregate_topic=os.getenv("KAFKA_AGGREGATE_TOPIC", "marketdata.aggregates"),
        producer_linger_ms=int(os.getenv("KAFKA_PRODUCER_LINGER_MS", "100")),
        producer_retries=int(os.getenv("KAFKA_PRODUCER_RETRIES", "3"))
    )

    # Example: Loading Kafka SASL credentials if configured via Secrets Manager
    # kafka_user_secret_name = os.getenv("KAFKA_SASL_USERNAME_SECRET_NAME")
    # if kafka_user_secret_name:
    #     kafka_cfg.sasl_username = get_secret(kafka_user_secret_name, aws_region)
    # kafka_pass_secret_name = os.getenv("KAFKA_SASL_PASSWORD_SECRET_NAME")
    # if kafka_pass_secret_name:
    #     kafka_cfg.sasl_password = get_secret(kafka_pass_secret_name, aws_region)
    # kafka_cfg.security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL")
    # kafka_cfg.sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM")

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level_str not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.warning(f"Invalid LOG_LEVEL '{log_level_str}', defaulting to INFO.")
        log_level_str = "INFO"

    logger.info(f"Polygon Config Loaded: BaseURL='{polygon_config.base_url}', RPM_Limit={polygon_config.requests_per_minute_limit}")
    logger.info(f"Kafka Config Loaded: Brokers='{kafka_cfg.bootstrap_servers}', TradeTopic='{kafka_cfg.trade_topic}'")

    return Config(
        aws_region=aws_region,
        polygon_rest=polygon_config,
        kafka=kafka_cfg,
        log_level=log_level_str
    )
