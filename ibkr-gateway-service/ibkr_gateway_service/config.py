import os
import logging
from typing import Optional, List

# Assuming secrets.py is in .utils package relative to this file
from .utils.secrets import get_secret

logger = logging.getLogger(__name__)

class IBKRConfig:
    gateway_host: str
    gateway_port: int
    client_id: int  # For TWS API connection
    account_code: Optional[str]  # Trading account code, if needed

    # Names of secrets in AWS Secrets Manager for IBKR Gateway application login.
    # These are NOT used directly by EClient.connect() for the API socket connection,
    # but are intended for external tools (e.g., IBController, custom scripts)
    # that might automate the login process of the IBKR Gateway application itself.
    username_secret_name: str
    password_secret_name: str

    # 2FA / IB Key related configuration - depends heavily on chosen automation method
    # For example, if using ib_insync with IBController which handles TOTP:
    # ib_controller_url: Optional[str] = None # e.g., http://localhost:5000 for IBController API
    # ib_key_totp_secret_name: Optional[str] = None # Secret name for the TOTP key if IBController needs it

    connect_timeout_seconds: int = 20
    post_connect_error_grace_seconds: float = 3.0 # Grace period for critical errors after nextValidId
    max_reconnect_attempts: int = 0 # 0 for indefinite, >0 for specific count
    reconnect_interval_seconds: int = 10
    active_keepalive_interval_seconds: int = 30 # Interval for sending keepalive pings
    keepalive_activity_check_threshold_seconds: int = 25 # Threshold to skip ping if recent activity
    # Pacing/Rate limit config for requests sent TO IBKR
    max_requests_per_second: int = 40 # Stay under IBKR's typical 50 req/sec limit
    max_silence_duration_seconds: int = 90 # New for stale connection detection

class KafkaConfig:  # For publishing responses/events from IBKR
    bootstrap_servers: str
    order_updates_topic: str
    execution_reports_topic: str
    account_data_topic: str
    position_data_topic: str
    error_events_topic: str
    oms_order_requests_topic: str # Topic for receiving order requests from OMS

class LeaderElectionConfig:
    lease_name: str
    lease_namespace: str # Usually the pod's namespace
    lease_duration_seconds: int
    renew_deadline_seconds: int
    retry_period_seconds: int

class RedisConfig:
    host: str
    port: int
    db: int
    password_secret_name: Optional[str] = None

class Config:
    ibkr: IBKRConfig
    kafka: KafkaConfig
    leader_election: LeaderElectionConfig
    redis: RedisConfig # Added RedisConfig
    aws_region: str
    service_instance_id: str
    log_level: str = "INFO"

def load_config() -> Config:
    aws_region = os.getenv("AWS_REGION")
    if not aws_region:
        logger.warning("AWS_REGION environment variable not set, using default 'us-east-1'")
        aws_region = "us-east-1"

    ibkr_username_secret_name = os.getenv("IBKR_USERNAME_SECRET_NAME")
    ibkr_password_secret_name = os.getenv("IBKR_PASSWORD_SECRET_NAME")

    if not ibkr_username_secret_name:
        # Depending on Gateway auth setup, username/password might not be directly used by this Python client
        # if Gateway is pre-authenticated (e.g. manual login, IBController).
        # However, if an automated login system needs them, they'd be critical.
        logger.warning("IBKR_USERNAME_SECRET_NAME environment variable not set. Assuming Gateway is pre-authenticated or uses other methods.")
    if not ibkr_password_secret_name:
        logger.warning("IBKR_PASSWORD_SECRET_NAME environment variable not set. Assuming Gateway is pre-authenticated or uses other methods.")

    # Note: The actual fetching of username/password from secrets will happen in ConnectionManager
    # when it attempts to perform an automated login to Gateway, if such a mechanism is implemented.
    # The TWS API EClient.connect() itself doesn't use username/password.

    ibkr_config = IBKRConfig(
        gateway_host=os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1"), # Default to localhost if Gateway runs as sidecar/same host
        gateway_port=int(os.getenv("IBKR_GATEWAY_PORT", "4001")), # 4001 for live Gateway, 4002 for paper
                                                                # 7496 for live TWS, 7497 for paper TWS
        client_id=int(os.getenv("IBKR_CLIENT_ID", "101")), # Must be unique per connection if multiple clients
        account_code=os.getenv("IBKR_ACCOUNT_CODE"),
        username_secret_name=ibkr_username_secret_name or "", # Store name even if empty
        password_secret_name=ibkr_password_secret_name or "", # Store name even if empty
        connect_timeout_seconds=int(os.getenv("IBKR_CONNECT_TIMEOUT_SECONDS", "20")),
        post_connect_error_grace_seconds=float(os.getenv("IBKR_POST_CONNECT_GRACE_SECONDS", "3.0")),
        active_keepalive_interval_seconds=int(os.getenv("IBKR_ACTIVE_KEEPALIVE_INTERVAL_SECONDS", "30")),
        keepalive_activity_check_threshold_seconds=int(os.getenv("IBKR_KEEPALIVE_ACTIVITY_CHECK_THRESHOLD_SECONDS", "25")),
            max_reconnect_attempts=int(os.getenv("IBKR_MAX_RECONNECT_ATTEMPTS", "0")),
        reconnect_interval_seconds=int(os.getenv("IBKR_RECONNECT_INTERVAL_SECONDS", "15")),
        max_requests_per_second=int(os.getenv("IBKR_MAX_REQUESTS_PER_SECOND", "40")),
            max_silence_duration_seconds=int(os.getenv("IBKR_MAX_SILENCE_SECONDS", "90")) # Load new config
        # ib_controller_url=os.getenv("IB_CONTROLLER_URL"),
        # ib_key_totp_secret_name=os.getenv("IB_KEY_TOTP_SECRET_NAME")
    )

    kafka_config = KafkaConfig(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        order_updates_topic=os.getenv("KAFKA_ORDER_UPDATES_TOPIC", "ibkr.order-updates"),
        execution_reports_topic=os.getenv("KAFKA_EXECUTION_REPORTS_TOPIC", "ibkr.execution-reports"),
        account_data_topic=os.getenv("KAFKA_ACCOUNT_DATA_TOPIC", "ibkr.account-data"),
        position_data_topic=os.getenv("KAFKA_POSITION_DATA_TOPIC", "ibkr.position-data"),
        error_events_topic=os.getenv("KAFKA_ERROR_EVENTS_TOPIC", "ibkr.error-events"),
        oms_order_requests_topic=os.getenv("OMS_ORDER_REQUESTS_TOPIC", "oms.order-requests")
    )

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level_str not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.warning(f"Invalid LOG_LEVEL '{log_level_str}', defaulting to INFO.")
        log_level_str = "INFO"

    service_instance_id = os.getenv("HOSTNAME") # HOSTNAME is commonly set in containerized environments (e.g., Kubernetes pod name)
    if not service_instance_id:
        service_instance_id = f"ibkr-gateway-service-pid-{os.getpid()}"

    leader_election_config = LeaderElectionConfig(
        lease_name=os.getenv("LEADER_ELECTION_LEASE_NAME", "ibkr-gateway-service-leader"),
        # POD_NAMESPACE is a common env var in K8s Downward API
        lease_namespace=os.getenv("POD_NAMESPACE", "default"),
        lease_duration_seconds=int(os.getenv("LEADER_ELECTION_LEASE_DURATION_SECONDS", "15")),
        renew_deadline_seconds=int(os.getenv("LEADER_ELECTION_RENEW_DEADLINE_SECONDS", "10")),
        retry_period_seconds=int(os.getenv("LEADER_ELECTION_RETRY_PERIOD_SECONDS", "2"))
    )

    redis_config = RedisConfig(
        host=os.getenv("REDIS_HOST", ""), # Empty host string means Redis is disabled
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password_secret_name=os.getenv("REDIS_PASSWORD_SECRET_NAME")
    )

    logger.info(f"IBKR Config Loaded: Host={ibkr_config.gateway_host}:{ibkr_config.gateway_port}, ClientID={ibkr_config.client_id}")
    logger.info(f"Kafka Config Loaded: Brokers='{kafka_config.bootstrap_servers}'")
    logger.info(f"LeaderElection Config Loaded: LeaseName='{leader_election_config.lease_name}', Namespace='{leader_election_config.lease_namespace}'")
    if redis_config.host:
        logger.info(f"Redis Config Loaded: Host={redis_config.host}:{redis_config.port}, DB={redis_config.db}")
    else:
        logger.info("Redis Config: Host not set, Redis integration will be disabled for OrderIdMapper.")


    return Config(
        aws_region=aws_region,
        service_instance_id=service_instance_id,
        ibkr=ibkr_config,
        kafka=kafka_config,
        leader_election=leader_election_config,
        redis=redis_config,
        log_level=log_level_str
    )
