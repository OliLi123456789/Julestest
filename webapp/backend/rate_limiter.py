# webapp/backend/rate_limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from .config_web import app_config

limiter = Limiter(key_func=get_remote_address, default_limits=[app_config.DEFAULT_RATE_LIMIT])
