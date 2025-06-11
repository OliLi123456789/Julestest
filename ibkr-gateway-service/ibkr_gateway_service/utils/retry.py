import asyncio
import random
import logging
import functools
from typing import Callable, Any, List, TypeVar, Coroutine
from .exceptions import IBError # Assuming exceptions.py is in the same utils directory

logger = logging.getLogger(__name__)

# Type variable for the decorated function's return type
R = TypeVar('R')

def async_retry_on_ib_error(
    max_attempts: int,
    initial_backoff_seconds: float,
    max_backoff_seconds: float,
    retryable_error_codes: List[int]
) -> Callable[[Callable[..., Coroutine[Any, Any, R]]], Callable[..., Coroutine[Any, Any, R]]]:
    """
    Decorator factory for retrying asynchronous methods on specific IBError codes
    with exponential backoff and jitter.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if initial_backoff_seconds <= 0:
        raise ValueError("initial_backoff_seconds must be positive")
    if max_backoff_seconds < initial_backoff_seconds:
        raise ValueError("max_backoff_seconds must be >= initial_backoff_seconds")

    def decorator(func: Callable[..., Coroutine[Any, Any, R]]) -> Callable[..., Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            current_attempt = 0
            current_backoff = initial_backoff_seconds
            last_exception: Exception = Exception("Retry loop failed without an exception (should not happen)")

            while current_attempt < max_attempts:
                current_attempt += 1
                try:
                    return await func(*args, **kwargs)
                except IBError as e:
                    last_exception = e
                    if e.code in retryable_error_codes:
                        if current_attempt < max_attempts:
                            # Calculate jitter: up to 25% of current backoff
                            jitter = random.uniform(-current_backoff * 0.25, current_backoff * 0.25)
                            wait_time = current_backoff + jitter

                            logger.warning(
                                f"Retryable IBError (code: {e.code}) encountered on attempt {current_attempt}/{max_attempts} for {func.__name__}. "
                                f"Waiting {wait_time:.2f}s before retrying. Message: {e.message}"
                            )
                            await asyncio.sleep(wait_time)

                            # Exponential backoff
                            current_backoff = min(current_backoff * 2, max_backoff_seconds)
                        else:
                            logger.error(
                                f"Final attempt ({current_attempt}/{max_attempts}) failed for {func.__name__} with IBError (code: {e.code}). "
                                f"No more retries. Message: {e.message}"
                            )
                            raise  # Re-raise the last IBError if max_attempts reached
                    else:
                        logger.error(
                            f"Non-retryable IBError (code: {e.code}) encountered for {func.__name__}. "
                            f"No retry. Message: {e.message}"
                        )
                        raise  # Re-raise if error code is not in retryable_error_codes
                except Exception as e: # Catch other exceptions
                    logger.error(f"Non-IBError exception encountered during {func.__name__}: {e}", exc_info=True)
                    raise # Re-raise non-IBError exceptions immediately

            # This line should ideally not be reached if max_attempts >= 1
            # If it is, it means the loop exited without returning or raising, re-raise last known exception.
            raise last_exception

        return wrapper
    return decorator
