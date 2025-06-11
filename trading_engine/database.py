import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # For actual async
import asyncio # For current mock of async session
from contextlib import asynccontextmanager # For async context manager

from trading_engine.oms.db_models import Base

# For this subtask, an in-memory SQLite database is used.
# In a production environment, this would be a configurable PostgreSQL or other robust DB URL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///:memory:")

engine = create_engine(
    DATABASE_URL,
    # For SQLite in-memory, connect_args might be needed for single connection behavior if used with threads.
    # For this basic setup, default is fine.
    # connect_args={"check_same_thread": False} # Only for SQLite if using threads and sharing engine/session
)

DBSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """
    Initializes the database by creating all tables defined in Base.metadata.
    This should be called once at application startup.
    For production, use migrations (e.g., Alembic).
    """
    # Import all modules here that define models so that
    # they are registered with Base.metadata - in this case, OrderDB is in oms.db_models
    # which is already imported to get Base.
    Base.metadata.create_all(bind=engine)

def get_db_session() -> Session:
    """
    Provides a database session.
    This is a simplified version. In a real application, session management
    would be more robust (e.g., scoped sessions, context managers, unit of work).
    """
    db = DBSessionLocal()
    return db

# ASYNC_DATABASE_URL = os.getenv("ASYNC_DATABASE_URL", "postgresql+asyncpg://user:pass@host:port/db")
# async_engine = create_async_engine(ASYNC_DATABASE_URL)
# AsyncDBSessionLocal = sessionmaker(
#     bind=async_engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
# )

@asynccontextmanager
async def async_get_db_session() -> Session: # Yields sync Session for now
    """
    Provides a database session within an async context.
    For this subtask, it wraps a synchronous session but provides an async interface.
    Commit/rollback should be handled by the caller within the 'async with' block.
    """
    db = DBSessionLocal()
    try:
        yield db
        # db.commit() # Commits are now expected to be explicit in the calling method
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Example of a context manager for session management (for future reference, not used in this subtask directly by OMS)
# from contextlib import contextmanager
# @contextmanager
# def session_scope():
#     """Provide a transactional scope around a series of operations."""
#     session = DBSessionLocal()
#     try:
#         yield session
#         session.commit()
#     except:
#         session.rollback()
#         raise
#     finally:
#         session.close()
