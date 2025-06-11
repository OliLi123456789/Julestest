# This file makes the 'data_persistence_service' directory a Python package.

# You can optionally expose parts of the package's API here for easier imports, e.g.:
# from .db_models import NewsArticleDB, EarningsReportDB, initialize_database, get_db_session
# from .repositories import NewsRepository, EarningsRepository

# Example of how one might structure for easy access if a default session is managed:
#
# _default_session = None
# def get_default_session():
#     global _default_session
#     if _default_session is None:
#         # This would require some global DB initialization logic to be called first
#         # from .db_models import initialize_database, DBSessionLocal
#         # if DBSessionLocal is None:
#         #     initialize_database() # Initialize with default DB_URL
#         # if DBSessionLocal:
#         #     _default_session = DBSessionLocal()
#         # else:
#         #     raise RuntimeError("Database not initialized. Call initialize_database() first.")
#         pass # For now, session management is explicit
#     return _default_session

# news_repo = NewsRepository(get_default_session())
# earnings_repo = EarningsRepository(get_default_session())
