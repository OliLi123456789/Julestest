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

    # Names of secrets in AWS Secrets Manager
    username_secret_name: str # For IB Gateway login (often automated by IBController)
    password_secret_name: str # For IB Gateway login (often automated by IBController)

    # 2FA / IB Key related configuration - depends heavily on chosen automation method
    # For example, if using ib_insync with IBController which handles TOTP:
    # ib_controller_url: Optional[str] = None # e.g., http://localhost:5000 for IBController API
    # ib_key_totp_secret_name: Optional[str] = None # Secret name for the TOTP key if IBController needs it

    connect_timeout_seconds: int = 20
    max_reconnect_attempts: int = 0 # 0 for indefinite, >0 for specific count
    reconnect_interval_seconds: int = 10
    # Pacing/Rate limit config for requests sent TO IBKR
    max_requests_per_second: int = 40 # Stay under IBKR's typical 50 req/sec limit
    max_silence_duration_seconds: int = 90 # New for stale connection detection

    # New configurable parameters
    market_data_type: int
    default_contract_resolution_timeout_seconds: int
    default_order_placement_timeout_seconds: float
    default_account_data_timeout_seconds: int
    default_pnl_timeout_seconds: int
    default_position_timeout_seconds: int
    max_concurrent_api_requests: int

class KafkaConfig:  # For publishing responses/events from IBKR
    bootstrap_servers: str
    order_updates_topic: str
    execution_reports_topic: str
    account_data_topic: str
    position_data_topic: str
    error_events_topic: str

    # New configurable parameters
    processor_idle_sleep_ms: int
    processor_stop_timeout_seconds: int
    account_value_updates_topic: str
    market_data_ticks_topic: str
    market_data_bars_topic: str

class LeaderElectionConfig:
    lease_name: str
    lease_namespace: str # Usually the pod's namespace
    lease_duration_seconds: int
    renew_deadline_seconds: int
    retry_period_seconds: int

class Config:
    ibkr: IBKRConfig
    kafka: KafkaConfig
    leader_election: LeaderElectionConfig # Added LeaderElectionConfig
    aws_region: str
    service_instance_id: str
    log_level: str = "INFO"
    health_check_port: int

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
            max_reconnect_attempts=int(os.getenv("IBKR_MAX_RECONNECT_ATTEMPTS", "0")),
        reconnect_interval_seconds=int(os.getenv("IBKR_RECONNECT_INTERVAL_SECONDS", "15")),
        max_requests_per_second=int(os.getenv("IBKR_MAX_REQUESTS_PER_SECOND", "40")),
        max_silence_duration_seconds=int(os.getenv("IBKR_MAX_SILENCE_SECONDS", "90")), # Load new config
        # ib_controller_url=os.getenv("IB_CONTROLLER_URL"),
        # ib_key_totp_secret_name=os.getenv("IB_KEY_TOTP_SECRET_NAME")
        market_data_type=int(os.getenv("IBKR_MARKET_DATA_TYPE", "2")),
        default_contract_resolution_timeout_seconds=int(os.getenv("IBKR_DEFAULT_CONTRACT_RESOLUTION_TIMEOUT_SECONDS", "10")),
        default_order_placement_timeout_seconds=float(os.getenv("IBKR_DEFAULT_ORDER_PLACEMENT_TIMEOUT_SECONDS", "5.0")),
        default_account_data_timeout_seconds=int(os.getenv("IBKR_DEFAULT_ACCOUNT_DATA_TIMEOUT_SECONDS", "10")),
        default_pnl_timeout_seconds=int(os.getenv("IBKR_DEFAULT_PNL_TIMEOUT_SECONDS", "10")),
        default_position_timeout_seconds=int(os.getenv("IBKR_DEFAULT_POSITION_TIMEOUT_SECONDS", "10")),
        max_concurrent_api_requests=int(os.getenv("IBKR_MAX_CONCURRENT_REQUESTS", "10"))
    )

    kafka_config = KafkaConfig(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        order_updates_topic=os.getenv("KAFKA_ORDER_UPDATES_TOPIC", "ibkr.order-updates"),
        execution_reports_topic=os.getenv("KAFKA_EXECUTION_REPORTS_TOPIC", "ibkr.execution-reports"),
        account_data_topic=os.getenv("KAFKA_ACCOUNT_DATA_TOPIC", "ibkr.account-data"),
        position_data_topic=os.getenv("KAFKA_POSITION_DATA_TOPIC", "ibkr.position-data"),
        error_events_topic=os.getenv("KAFKA_ERROR_EVENTS_TOPIC", "ibkr.error-events"),
        processor_idle_sleep_ms=int(os.getenv("KAFKA_PROCESSOR_IDLE_SLEEP_MS", "10")),
        processor_stop_timeout_seconds=int(os.getenv("KAFKA_PROCESSOR_STOP_TIMEOUT_SECONDS", "10")),
        account_value_updates_topic=os.getenv("KAFKA_ACCOUNT_VALUE_UPDATES_TOPIC", "ibkr.account-value-updates"),
        market_data_ticks_topic=os.getenv("KAFKA_MARKET_DATA_TICKS_TOPIC", "ibkr.market-data.ticks"),
        market_data_bars_topic=os.getenv("KAFKA_MARKET_DATA_BARS_TOPIC", "ibkr.market-data.bars")
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

    logger.info(f"IBKR Config Loaded: Host={ibkr_config.gateway_host}:{ibkr_config.gateway_port}, ClientID={ibkr_config.client_id}, Account={ibkr_config.account_code}")
    logger.info(f"IBKR Market Data Type: {ibkr_config.market_data_type}")
    logger.info(f"IBKR Max Silence Duration: {ibkr_config.max_silence_duration_seconds}s")
    logger.info(f"IBKR Default Contract Resolution Timeout: {ibkr_config.default_contract_resolution_timeout_seconds}s")
    logger.info(f"IBKR Default Order Placement Timeout: {ibkr_config.default_order_placement_timeout_seconds}s")
    logger.info(f"IBKR Default Account Data Timeout: {ibkr_config.default_account_data_timeout_seconds}s")
    logger.info(f"IBKR Default PnL Timeout: {ibkr_config.default_pnl_timeout_seconds}s")
    logger.info(f"IBKR Default Position Timeout: {ibkr_config.default_position_timeout_seconds}s")
    logger.info(f"IBKR Max Concurrent API Requests: {ibkr_config.max_concurrent_api_requests}")

    logger.info(f"Kafka Config Loaded: Brokers='{kafka_config.bootstrap_servers}'")
    logger.info(f"Kafka Order Updates Topic: {kafka_config.order_updates_topic}")
    logger.info(f"Kafka Execution Reports Topic: {kafka_config.execution_reports_topic}")
    logger.info(f"Kafka Account Data Topic: {kafka_config.account_data_topic}")
    logger.info(f"Kafka Position Data Topic: {kafka_config.position_data_topic}")
    logger.info(f"Kafka Error Events Topic: {kafka_config.error_events_topic}")
    logger.info(f"Kafka Processor Idle Sleep: {kafka_config.processor_idle_sleep_ms}ms")
    logger.info(f"Kafka Processor Stop Timeout: {kafka_config.processor_stop_timeout_seconds}s")
    logger.info(f"Kafka Account Value Updates Topic: {kafka_config.account_value_updates_topic}")
    logger.info(f"Kafka Market Data Ticks Topic: {kafka_config.market_data_ticks_topic}")
    logger.info(f"Kafka Market Data Bars Topic: {kafka_config.market_data_bars_topic}")

    logger.info(f"LeaderElection Config Loaded: LeaseName='{leader_election_config.lease_name}', Namespace='{leader_election_config.lease_namespace}'")

    health_check_port=int(os.getenv("HEALTH_CHECK_PORT", "8080"))
    logger.info(f"Health Check Port: {health_check_port}")

    return Config(
        aws_region=aws_region,
        service_instance_id=service_instance_id,
        ibkr=ibkr_config,
        kafka=kafka_config,
        leader_election=leader_election_config,
        log_level=log_level_str,
        health_check_port=health_check_port
    )
