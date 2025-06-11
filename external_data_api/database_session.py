# external_data_api/database_session.py
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession # Rename to avoid conflict
from typing import Generator # For generator type hint on get_db

# Assuming data_persistence_service.db_models is accessible in PYTHONPATH
# This is where Base is defined and where the tables are created.
# It also defines DEFAULT_DB_URL which we can reuse if appropriate.
try:
    from data_persistence_service.db_models import Base, DEFAULT_DB_URL as SHARED_DEFAULT_DB_URL
    DATA_PERSISTENCE_MODELS_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).error("Failed to import Base from data_persistence_service.db_models. Ensure it's in PYTHONPATH.")
    # Define a dummy Base if import fails, so module can be imported, but DB operations will fail.
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()
    SHARED_DEFAULT_DB_URL = "sqlite:///./missing_default_db.db" # Fallback
    DATA_PERSISTENCE_MODELS_AVAILABLE = False


# DB_URL for this API service. Should point to the database populated by other services.
# Use the same default as data_persistence_service or an environment override.
DATABASE_URL = os.getenv("EXTERNAL_DATA_API_DB_URL", SHARED_DEFAULT_DB_URL)
logger = logging.getLogger(__name__)
logger.info(f"External Data API database URL: {DATABASE_URL}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

ExternalDataApiDBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_external_data_api_db():
    """
    Initializes the database. In a multi-service setup, table creation
    is typically handled by the service responsible for the models (data_persistence_service).
    This function can be called on app startup to ensure the engine is ready,
    but table creation might be skipped if already handled.
    """
    if not DATA_PERSISTENCE_MODELS_AVAILABLE:
        logger.error("Cannot initialize database; data_persistence_service.db_models.Base not available.")
        return
    try:
        # Base.metadata.create_all(bind=engine) # Typically only run once by one service
        logger.info("Database engine created. Table creation is assumed to be handled by data_persistence_service.")
    except Exception as e:
        logger.error(f"Error during (potential) table creation or engine check: {e}", exc_info=True)


def get_db() -> Generator[SQLAlchemySession, None, None]:
    """
    FastAPI dependency to get a DB session.
    Ensures the session is closed after the request.
    """
    if not DATA_PERSISTENCE_MODELS_AVAILABLE:
        # This situation should ideally prevent app startup or result in clear errors.
        raise RuntimeError("Data persistence models not available, cannot provide DB session.")

    db = ExternalDataApiDBSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Example usage for testing the session setup (optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing database session setup...")
    if DATA_PERSISTENCE_MODELS_AVAILABLE:
        # Call init_external_data_api_db if you want to ensure tables are created for a standalone test
        # from data_persistence_service.db_models import initialize_database as init_persistence_db
        # init_persistence_db(DATABASE_URL) # This would use the persistence service's init

        db_gen = get_db()
        test_session = next(db_gen)
        if test_session:
            logger.info("Successfully obtained a database session.")
            # You can try a simple query if tables exist, e.g.,
            # from data_persistence_service.db_models import NewsArticleDB
            # count = test_session.query(NewsArticleDB).count()
            # logger.info(f"Found {count} articles in news_articles table (if table exists and populated).")
            test_session.close()
        else:
            logger.error("Failed to obtain a database session.")
    else:
        logger.error("Cannot test DB session: data_persistence_service.db_models not available.")
