# news_service/earnings_processor_service.py
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session # For type hinting

# Assuming data_persistence_service and local news_service components are in PYTHONPATH
try:
    from data_persistence_service.repositories import EarningsRepository
    from data_persistence_service.db_models import EarningsReportDB # For type hint if returning DB object
    DATA_PERSISTENCE_AVAILABLE = True
except ImportError as e_imp:
    logging.getLogger(__name__).error(f"Failed to import from data_persistence_service: {e_imp}. EarningsProcessorService may not function.", exc_info=True)
    DATA_PERSISTENCE_AVAILABLE = False
    class EarningsRepository: pass # Dummy for type hints
    class EarningsReportDB: pass # Dummy for type hints

from .config_news import earnings_config # Uses earnings_config for thresholds & Kafka topics
from .event_protos_alerts import SignificantEarningsAlert
from .kafka_publishers import MockAlertKafkaProducer # Re-use the same mock producer

logger = logging.getLogger(__name__)

class EarningsProcessorService:
    def __init__(self, db_session: Session):
        if not DATA_PERSISTENCE_AVAILABLE:
            raise RuntimeError("Data persistence components are not available. EarningsProcessorService cannot operate.")

        self.session = db_session
        self.earnings_repo = EarningsRepository(self.session)

        # Initialize Kafka alert producer using settings from earnings_config
        self.alert_producer = MockAlertKafkaProducer(
            bootstrap_servers=getattr(earnings_config, 'kafka_bootstrap_servers', 'mock_kafka_eps:9092') # Ensure this attr exists
        )
        self.earnings_alerts_topic = earnings_config.kafka_alerts_earnings_topic
        self.eps_surprise_threshold_pct = earnings_config.earnings_eps_surprise_pct_threshold

        logger.info(f"EarningsProcessorService initialized. Alerting to topic '{self.earnings_alerts_topic}'. "
                    f"EPS Surprise Threshold: {self.eps_surprise_threshold_pct}%.")

    def add_and_alert_earnings_report(self, report_data: Dict[str, Any],
                                      symbol_override: Optional[str] = None,
                                      source_api_override: Optional[str] = None) -> Optional[EarningsReportDB]:
        """
        Adds an earnings report to the database via EarningsRepository.
        If the report is significant (e.g., EPS surprise), publishes an alert to Kafka.
        Returns the saved EarningsReportDB object or None if saving failed.
        """

        # Add/update report in DB first
        # The add_report method in repository handles duplicate checks and returns existing if found.
        db_report = self.earnings_repo.add_report(report_data, symbol_override, source_api_override)

        if db_report: # If successfully added/retrieved (already exists is also a success for processing)
            # Check for significance to generate an alert
            eps_actual = db_report.eps_actual
            eps_estimate = db_report.eps_estimate
            alert_reason_str: Optional[str] = None
            calculated_surprise_pct: Optional[float] = None

            if eps_actual is not None and eps_estimate is not None:
                if eps_estimate != 0: # Avoid division by zero
                    calculated_surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100
                    if calculated_surprise_pct >= self.eps_surprise_threshold_pct:
                        alert_reason_str = "EPS_BEAT_SIGNIFICANT"
                    elif calculated_surprise_pct <= -self.eps_surprise_threshold_pct:
                        alert_reason_str = "EPS_MISS_SIGNIFICANT"
                elif eps_actual > 0: # Estimate was zero, actual is positive -> considered a beat
                     alert_reason_str = "EPS_BEAT_SIGNIFICANT (Estimate was zero)"
                     calculated_surprise_pct = float('inf') # Represent as large beat
                elif eps_actual < 0: # Estimate was zero, actual is negative -> considered a miss
                     alert_reason_str = "EPS_MISS_SIGNIFICANT (Estimate was zero)"
                     calculated_surprise_pct = float('-inf') # Represent as large miss


            if alert_reason_str:
                try:
                    earnings_alert = SignificantEarningsAlert(
                        symbol=db_report.symbol,
                        report_date_iso=db_report.report_date.isoformat() if db_report.report_date else '',
                        fiscal_period_ending_iso=db_report.fiscal_period_ending.isoformat() if db_report.fiscal_period_ending else None,
                        eps_actual=eps_actual,
                        eps_estimate=eps_estimate,
                        revenue_actual=db_report.revenue_actual,
                        revenue_estimate=db_report.revenue_estimate,
                        surprise_type=alert_reason_str,
                        surprise_magnitude_pct=calculated_surprise_pct,
                        time_of_day=db_report.time_of_day
                        # event_timestamp_utc is defaulted in SignificantEarningsAlert constructor
                    )
                    alert_key = f"{db_report.symbol}_{db_report.report_date.isoformat()}" if db_report.report_date else db_report.symbol
                    self.alert_producer.produce(
                        topic=self.earnings_alerts_topic,
                        key=alert_key,
                        value=earnings_alert.SerializeToString()
                    )
                    # self.alert_producer.flush() # Optional: flush per message, or batch at end of processing run
                    logger.info(f"Published SignificantEarningsAlert for {db_report.symbol} "
                                f"report date {db_report.report_date}, Reason: {alert_reason_str} "
                                f"(Surprise: {calculated_surprise_pct:.2f}% if numeric else 'N/A')")
                except Exception as e_alert:
                    logger.error(f"Failed to create or publish SignificantEarningsAlert for {db_report.symbol}: {e_alert}", exc_info=True)

            # The session commit for adding the db_report itself should be handled by the caller
            # of this service method, as part of a larger unit of work.
            # self.session.commit() # No, repository add_report calls flush, service using this commits.

        return db_report # Return the persisted/retrieved DB object or None

    def close_producer(self): # Call on service shutdown
        logger.info("Closing EarningsProcessorService's Kafka alert producer...")
        if self.alert_producer:
            self.alert_producer.flush(timeout=5.0) # Give some time to flush
            self.alert_producer.close()

if __name__ == '__main__':
    # Example usage for EarningsProcessorService
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
    main_logger = logging.getLogger(__name__)

    if not DATA_PERSISTENCE_AVAILABLE:
        main_logger.critical("Data persistence service components not available. EarningsProcessorService test cannot run.")
        sys.exit(1)

    # Use a specific test DB URL or the default from db_models
    TEST_DB_URL_EPS = os.getenv("EARNINGS_PROCESSOR_TEST_DB_URL", f"sqlite:///./earnings_processor_test_db_{time.time()}.db")
    main_logger.info(f"EarningsProcessorService Test: Using DB URL: {TEST_DB_URL_EPS}")

    processor_svc = None # To ensure close_producer is called in finally

    try:
        engine, DBSessionLocal = initialize_database(db_url=TEST_DB_URL_EPS, create_tables=True)
        if not DBSessionLocal: main_logger.error("Failed to get DBSessionLocal factory. Exiting."); sys.exit(1)

        session = DBSessionLocal()
        if not session: main_logger.error("Failed to create DB session. Exiting."); sys.exit(1)

        processor_svc = EarningsProcessorService(session)

        # Sample earnings data (some significant, some not)
        earnings_data_list = [
            {"date": "2024-03-15", "symbol": "NVDA", "eps": 2.50, "epsEstimated": 2.00, "revenue": 6.5e9, "revenueEstimated": 6e9, "time": "amc", "fiscalDateEnding": "2024-01-31"}, # Beat
            {"date": "2024-03-16", "symbol": "ADBE", "eps": 1.50, "epsEstimated": 1.80, "revenue": 4.0e9, "revenueEstimated": 4.2e9, "time": "bmo", "fiscalDateEnding": "2024-02-29"}, # Miss
            {"date": "2024-03-17", "symbol": "SMCI", "eps": 3.00, "epsEstimated": 3.01, "revenue": 2.0e9, "revenueEstimated": 2.0e9, "time": "amc", "fiscalDateEnding": "2024-02-29"}, # Minor miss, might not trigger
            {"date": "2024-03-17", "symbol": "SMCI", "eps": 3.00, "epsEstimated": 3.01, "revenue": 2.0e9, "revenueEstimated": 2.0e9, "time": "amc", "fiscalDateEnding": "2024-02-29"}, # Duplicate test
            {"date": "2024-03-18", "symbol": "TSLA", "eps": 0.50, "epsEstimated": 0.0, "revenue": 20e9, "revenueEstimated": 20e9, "time": "amc", "fiscalDateEnding": "2024-02-29"}, # Estimate is zero
        ]

        for report_item in earnings_data_list:
            main_logger.info(f"\nProcessing report for {report_item['symbol']} on {report_item['date']}")
            db_rep = processor_svc.add_and_alert_earnings_report(report_item, source_api_override="TestRun")
            if db_rep:
                 main_logger.info(f"  DB Report ID: {db_rep.id}, Symbol: {db_rep.symbol}, EPS Actual: {db_rep.eps_actual}")
            else:
                 main_logger.warning(f"  Failed to add/process report for {report_item['symbol']} on {report_item['date']}")

        session.commit() # Commit all reports and their potential alert publications (mocked for now)
        main_logger.info("Committed all processed earnings reports.")

    except Exception as e_main_svc:
        main_logger.error(f"Error in EarningsProcessorService __main__ example: {e_main_svc}", exc_info=True)
        if 'session' in locals() and session and session.is_active: session.rollback()
    finally:
        if processor_svc: processor_svc.close_producer() # Close Kafka producer
        if 'session' in locals() and session: session.close(); main_logger.info("DB Session closed.")
        # Clean up test DB file if it's a file-based SQLite and was created for this test
        if TEST_DB_URL_EPS.startswith("sqlite:///") and ":memory:" not in TEST_DB_URL_EPS:
            db_file_path = TEST_DB_URL_EPS.replace("sqlite:///", "")
            if os.path.exists(db_file_path) and f"earnings_processor_test_db_{time.time()}"[:-11] in db_file_path: # Safety check on name
                 try:
                    # Ensure session is closed before trying to remove file, might need small delay or retry
                    time.sleep(0.1)
                    os.remove(db_file_path)
                    logger.info(f"Cleaned up test database: {db_file_path}")
                 except Exception as e_del:
                    logger.error(f"Could not delete test DB {db_file_path}: {e_del}")
