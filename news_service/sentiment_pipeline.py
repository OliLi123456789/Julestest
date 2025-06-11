# news_service/sentiment_pipeline.py
import logging
from sqlalchemy.orm import Session # For type hinting
from typing import Optional, List, Dict, Any # Added for type hints

# Attempt to import from data_persistence_service. This assumes it's in PYTHONPATH.
try:
    from data_persistence_service.repositories import NewsRepository
    from data_persistence_service.db_models import NewsArticleDB
    from data_persistence_service.db_models import initialize_database, get_db_session, DEFAULT_DB_URL
    DATA_PERSISTENCE_AVAILABLE = True
except ImportError as e_imp:
    logging.getLogger(__name__).error(f"Failed to import from data_persistence_service: {e_imp}. Pipeline cannot run.", exc_info=True)
    DATA_PERSISTENCE_AVAILABLE = False
    class NewsRepository: pass
    class NewsArticleDB: pass
    # Define dummies for main block if needed, or let it fail if components are critical
    def initialize_database(db_url,create_tables): pass
    def get_db_session(db_url=None): pass
    DEFAULT_DB_URL = ""


from .sentiment_analyzer import SentimentAnalyzer
from .event_protos_alerts import SignificantNewsAlert # Added
from .kafka_publishers import MockAlertKafkaProducer # Added
from .config_news import news_service_config # Using news_service_config for news-related alert settings

import time
import datetime
import sys
import os # Added for __main__ example DB URL
import sys

# Use hierarchical logger based on the new logging setup
try:
    from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME
    logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.sentiment_pipeline")
except ImportError: # Fallback if logging_setup is not available (e.g. standalone test)
    logger = logging.getLogger(__name__)


class NewsSentimentPipeline:
    def __init__(self, db_session: Session):
        if not DATA_PERSISTENCE_AVAILABLE:
            raise RuntimeError("Data persistence components are not available. NewsSentimentPipeline cannot operate.")
        self.session = db_session
        self.news_repo = NewsRepository(self.session)
        self.sentiment_analyzer = SentimentAnalyzer()

        # Initialize Kafka alert producer
        # Assuming bootstrap_servers is available in news_service_config from previous step
        self.alert_producer = MockAlertKafkaProducer(
            bootstrap_servers=getattr(news_service_config, 'kafka_bootstrap_servers', 'mock_kafka:9092')
        )
        self.news_alerts_topic = news_service_config.kafka_alerts_news_topic
        self.sentiment_threshold_pos = news_service_config.news_sentiment_alert_threshold_positive
        self.sentiment_threshold_neg = news_service_config.news_sentiment_alert_threshold_negative
        logger.info(f"NewsSentimentPipeline initialized. Alerting to topic '{self.news_alerts_topic}'. PosThreshold: {self.sentiment_threshold_pos}, NegThreshold: {self.sentiment_threshold_neg}")


    def process_articles_batch(self, batch_size: int = 100, max_articles_to_process: Optional[int] = None) -> int:
        if not self.sentiment_analyzer.analyzer:
            logger.error("Pipeline Error: VADER sentiment analyzer is not available. Cannot process articles.")
            return 0

        total_processed_in_run = 0 # Tracks articles processed in this entire call to process_articles_batch

        while True:
            articles_processed_in_current_batch = 0 # For commit logic within this specific batch
            try:
                articles_this_batch: List[NewsArticleDB] = self.session.query(NewsArticleDB)\
                    .filter(NewsArticleDB.sentiment_score_compound == None)\
                    .order_by(NewsArticleDB.published_at.asc()) # Process older articles first
                    .limit(batch_size)\
                    .all()

                if not articles_this_batch:
                    if total_processed_in_run == 0:
                         logger.info("No articles found needing sentiment analysis in the database.")
                    else:
                         logger.info(f"All available articles needing sentiment analysis processed. Total in this run: {total_processed_in_run}")
                    break

                logger.info(f"Fetched batch of {len(articles_this_batch)} articles for sentiment analysis.")

                for article_db in articles_this_batch:
                    text_to_analyze = f"{article_db.title or ''}. {article_db.description or ''}"
                    sentiment_scores_dict: Optional[Dict[str, float]] = None # To hold scores for alert

                    if not text_to_analyze.strip() or text_to_analyze == ". ":
                        logger.warning(f"Article ID {article_db.id} ('{article_db.title[:30]}...') has no usable text. Marking as neutral.")
                        self.news_repo.update_article_sentiment(article_id=article_db.id, compound_score=0.0, neg=0.0, neu=1.0, pos=0.0, provider="VADER_NO_TEXT")
                        sentiment_scores_dict = {'compound': 0.0, 'neg': 0.0, 'neu': 1.0, 'pos': 0.0} # For alert logic
                    else:
                        sentiment_scores = self.sentiment_analyzer.analyze_sentiment(text_to_analyze)
                        if sentiment_scores:
                            self.news_repo.update_article_sentiment(
                                article_id=article_db.id, compound_score=sentiment_scores['compound'],
                                neg=sentiment_scores['neg'], neu=sentiment_scores['neu'], pos=sentiment_scores['pos'],
                                provider="VADER"
                            )
                            sentiment_scores_dict = sentiment_scores
                            logger.debug(f"Sentiment for article ID {article_db.id}: Compound={sentiment_scores['compound']:.2f}")
                        else:
                            logger.warning(f"Sentiment analysis failed for article ID {article_db.id}. Marking with error provider.")
                            self.news_repo.update_article_sentiment(article_id=article_db.id, compound_score=0.0, neg=0.0, neu=0.0, pos=0.0, provider="VADER_ERROR")
                            sentiment_scores_dict = {'compound': 0.0, 'neg': 0.0, 'neu': 0.0, 'pos': 0.0} # For alert logic

                    articles_processed_in_current_batch += 1
                    total_processed_in_run +=1

                    # Check for significant sentiment and publish alert
                    if sentiment_scores_dict: # Ensure scores are available
                        alert_reason = None
                        compound_score = sentiment_scores_dict['compound']
                        if compound_score >= self.sentiment_threshold_pos:
                            alert_reason = "STRONG_POSITIVE_SENTIMENT"
                        elif compound_score <= self.sentiment_threshold_neg:
                            alert_reason = "STRONG_NEGATIVE_SENTIMENT"

                        if alert_reason:
                            try:
                                related_symbols_list = article_db.related_symbols.split(',') if article_db.related_symbols else []
                                news_alert = SignificantNewsAlert(
                                    article_url=article_db.url,
                                    related_symbols=related_symbols_list,
                                    published_at_iso=article_db.published_at.isoformat() if article_db.published_at else '',
                                    title_snippet=article_db.title[:100] if article_db.title else '',
                                    sentiment_score_compound=compound_score,
                                    alert_reason=alert_reason
                                )
                                self.alert_producer.produce(
                                    topic=self.news_alerts_topic,
                                    key=article_db.url, # Use article URL as Kafka key
                                    value=news_alert.SerializeToString()
                                )
                                logger.info(f"Published SignificantNewsAlert for article ID {article_db.id}, Reason: {alert_reason}")
                            except Exception as e_alert:
                                logger.error(f"Failed to publish SignificantNewsAlert for article ID {article_db.id}: {e_alert}", exc_info=True)

                    if max_articles_to_process and total_processed_in_run >= max_articles_to_process:
                        break

                if articles_processed_in_current_batch > 0:
                    try: self.session.commit(); logger.info(f"Committed sentiment updates for {articles_processed_in_current_batch} articles.")
                    except Exception as e_commit:
                        logger.error(f"Error committing sentiment updates: {e_commit}", exc_info=True)
                        self.session.rollback(); return total_processed_in_run - articles_processed_in_current_batch

                if not articles_this_batch or (max_articles_to_process and total_processed_in_run >= max_articles_to_process) or len(articles_this_batch) < batch_size:
                    break
            except Exception as e_batch:
                logger.error(f"Error processing sentiment batch: {e_batch}", exc_info=True)
                try: self.session.rollback()
                except: pass
                break

        logger.info(f"NewsSentimentPipeline finished. Total articles updated in this run: {total_processed_in_run}")
        return total_processed_in_run

    def close_producers(self): # Method to be called on graceful shutdown
        logger.info("Closing NewsSentimentPipeline's Kafka alert producer...")
        if self.alert_producer:
            self.alert_producer.flush()
            self.alert_producer.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
    main_logger = logging.getLogger(__name__)

    if not DATA_PERSISTENCE_AVAILABLE:
        main_logger.critical("Data persistence service components not available. Pipeline test cannot run."); sys.exit(1)

    TEST_DB_URL = os.getenv("SENTIMENT_PIPELINE_TEST_DB_URL", f"sqlite:///./sentiment_pipeline_test_db_{time.time()}.db")
    main_logger.info(f"Pipeline Test: Using DB URL: {TEST_DB_URL}")
    pipeline_instance = None # To ensure close_producers is called in finally

    try:
        engine, DBSessionLocal = initialize_database(db_url=TEST_DB_URL, create_tables=True)
        if not DBSessionLocal: main_logger.error("Failed to get DBSessionLocal factory. Exiting."); sys.exit(1)

        session = DBSessionLocal()
        if not session: main_logger.error("Failed to create DB session. Exiting."); sys.exit(1)

        news_repo_for_seeding = NewsRepository(session)
        main_logger.info("Seeding sample articles for pipeline test...")
        # ... (seeding logic from previous version, ensuring unique URLs per run if DB is persistent)
        ts_now = datetime.datetime.now(datetime.timezone.utc)
        sample_articles_data = [
            {"title": "Tech Stocks Rally on Positive Outlook", "description": "Major tech companies saw prices increase.", "url": f"http://example.com/news_pipeline_test1_{ts_now.timestamp()}", "publishedAt": ts_now.isoformat(), "related_symbols": "AAPL,MSFT,GOOG"},
            {"title": "Oil Prices Drop Sharply", "description": "Crude oil experienced a steep decline.", "url": f"http://example.com/news_pipeline_test2_{ts_now.timestamp()}", "publishedAt": (ts_now - datetime.timedelta(days=1)).isoformat(), "related_symbols": "XOM,CVX,OIL"},
            {"title": "Old News, Processed", "description": "This one has sentiment already.", "url": f"http://example.com/news_pipeline_test4_{ts_now.timestamp()}", "publishedAt": (ts_now - datetime.timedelta(days=3)).isoformat(), "sentiment_score_compound": 0.8, "sentiment_provider": "VADER_MANUAL", "related_symbols":"TSLA"},
            {"title": "", "description": "", "url": f"http://example.com/news_pipeline_test5_{ts_now.timestamp()}", "publishedAt": (ts_now - datetime.timedelta(days=4)).isoformat(), "related_symbols":"AMZN"}
        ]
        for article_content in sample_articles_data:
            existing = session.query(NewsArticleDB).filter_by(url=article_content['url']).first()
            if not existing:
                art = NewsArticleDB(title=article_content["title"], description=article_content["description"],
                                    url=article_content["url"], published_at=pd.to_datetime(article_content["publishedAt"]).to_pydatetime(warn=False),
                                    related_symbols=article_content.get("related_symbols"),
                                    sentiment_score_compound=article_content.get("sentiment_score_compound"),
                                    sentiment_provider=article_content.get("sentiment_provider"))
                session.add(art)
        session.commit()
        main_logger.info("Finished seeding.")

        pipeline_instance = NewsSentimentPipeline(session) # Assign to variable
        main_logger.info("Running NewsSentimentPipeline...")
        num_processed = pipeline_instance.process_articles_batch(batch_size=2, max_articles_to_process=10)
        main_logger.info(f"Pipeline run completed. Total articles processed for sentiment: {num_processed}")

        logger.info("\n--- Verifying results (all articles with sentiment) ---")
        processed_articles = session.query(NewsArticleDB).filter(NewsArticleDB.sentiment_provider != None).all()
        for art in processed_articles:
            main_logger.info(f"ID: {art.id}, Title: '{art.title[:30]}...', Compound: {art.sentiment_score_compound}, Provider: {art.sentiment_provider}")

    except Exception as e_main_pipeline:
        main_logger.error(f"Error in pipeline __main__ example: {e_main_pipeline}", exc_info=True)
        if 'session' in locals() and session and session.is_active: session.rollback()
    finally:
        if pipeline_instance: pipeline_instance.close_producers() # Close Kafka producer
        if 'session' in locals() and session: session.close(); main_logger.info("DB Session closed.")
        if TEST_DB_URL.startswith("sqlite:///") and ":memory:" not in TEST_DB_URL and os.path.exists(TEST_DB_URL.replace("sqlite:///", "")):
           os.remove(TEST_DB_URL.replace("sqlite:///", ""))
           logger.info(f"Cleaned up test database: {TEST_DB_URL}")
