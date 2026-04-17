"""
Retry Handler for MStock API
Implements exponential backoff and fallback mechanisms for handling MStock API failures.
"""

import time
from functools import wraps
from typing import Any, Callable

from utils.logging import get_logger

logger = get_logger(__name__)


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 10.0,
):
    """
    Decorator to retry a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay after each retry
        max_delay: Maximum delay between retries
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_msg = str(e).lower()

                    # Check if error is retryable (502, 503, 504, timeout, connection errors)
                    is_retryable = any(
                        code in error_msg
                        for code in ["502", "503", "504", "timeout", "connection", "gateway"]
                    )

                    if not is_retryable or attempt == max_retries:
                        logger.error(
                            f"MStock API call failed after {attempt + 1} attempts: {e}"
                        )
                        raise

                    # Log retry attempt
                    logger.warning(
                        f"MStock API error (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Should never reach here, but just in case
            raise last_exception

        return wrapper
    return decorator


def with_fallback_data(fallback_value: Any = None):
    """
    Decorator to return fallback data when API call fails.

    Args:
        fallback_value: Value to return on failure (default: None)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"MStock API call failed, using fallback data: {e}"
                )
                return fallback_value

        return wrapper
    return decorator
