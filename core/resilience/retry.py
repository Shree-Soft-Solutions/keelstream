"""
Resilient retry execution engine for KeelStream.
Provides intelligent backoff, token auto-refresh on 401, rate-limiting adaptation on 429,
and circuit breaker integration.
"""

import functools
import time
from typing import Callable, Any, Optional, Tuple, Type, Union

from core.resilience.backoff import ExponentialBackoff, parse_retry_after
from core.resilience.circuit_breaker import CircuitBreaker


class ResiliencyException(Exception):
    """Base exception for KeelStream resiliency failures."""
    pass


class MaxRetriesExceededException(ResiliencyException):
    """Raised when an operation fails after reaching maximum retry attempts."""
    def __init__(self, attempts: int, last_exception: Exception):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(f"Operation failed after {attempts} attempts. Last error: {last_exception}")


class RateLimitExceededException(ResiliencyException):
    """Raised when rate limiting (HTTP 429) persists beyond maximum retry budget."""
    def __init__(self, attempts: int, retry_after: Optional[float]):
        self.attempts = attempts
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded (HTTP 429) across {attempts} retries. "
            f"Suggested retry delay: {retry_after}s"
        )


class AuthenticationError(ResiliencyException):
    """Raised when authentication credentials fail or token refresh fails."""
    pass


def is_rate_limit_error(exc: Exception) -> Tuple[bool, Optional[float]]:
    """
    Checks if an exception represents an HTTP 429 Rate Limit.
    Returns (is_rate_limited, retry_after_seconds).
    """
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code == 429:
        retry_after = None
        headers = getattr(exc, "headers", {})
        if isinstance(headers, dict):
            raw_retry = headers.get("Retry-After") or headers.get("retry-after")
            retry_after = parse_retry_after(raw_retry)
        return True, retry_after

    # Also inspect error message or attribute names
    msg = str(exc).lower()
    if "rate limit" in msg or "429" in msg or "too many requests" in msg:
        retry_after = getattr(exc, "retry_after", None)
        return True, parse_retry_after(retry_after)

    return False, None


def is_auth_expired_error(exc: Exception) -> bool:
    """
    Checks if an exception represents expired credentials or HTTP 401 Unauthorized.
    """
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code == 401:
        return True
    msg = str(exc).lower()
    if "token expired" in msg or "unauthorized" in msg or "invalid_token" in msg:
        return True
    return False


def execute_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    backoff: Optional[ExponentialBackoff] = None,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
    token_refresh_hook: Optional[Callable[[], Any]] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    sleep_func: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> Any:
    """
    Executes a callable with comprehensive fault tolerance:
      1. Exponential backoff + jitter on retryable failures.
      2. Rate limit (429) detection and Retry-After delay honoring.
      3. Automatic credential refresh on 401 / expired token.
      4. Circuit breaker protection and fast-failure.
    """
    if backoff is None:
        backoff = ExponentialBackoff()

    token_refreshed = False
    attempts = 0

    while True:
        attempts += 1

        # Check circuit breaker before execution
        if circuit_breaker is not None:
            circuit_breaker.allow_request()

        try:
            result = fn(*args, **kwargs)
            if circuit_breaker is not None:
                circuit_breaker.record_success()
            return result

        except non_retryable_exceptions as exc:
            if circuit_breaker is not None:
                circuit_breaker.record_failure()
            raise

        except Exception as exc:
            # 1. Check for token expiration / 401
            if is_auth_expired_error(exc) and token_refresh_hook is not None and not token_refreshed:
                token_refreshed = True
                try:
                    token_refresh_hook()
                    # Retry immediately with refreshed credentials
                    continue
                except Exception as refresh_err:
                    if circuit_breaker is not None:
                        circuit_breaker.record_failure()
                    raise AuthenticationError(
                        f"Failed to refresh authentication token: {refresh_err}"
                    ) from refresh_err

            # 2. Check for rate limiting 429
            is_429, retry_after = is_rate_limit_error(exc)

            # Record failure in circuit breaker (unless purely rate-limited client-side delay)
            if circuit_breaker is not None and not is_429:
                circuit_breaker.record_failure()

            # 3. Check retry budget
            if attempts > max_retries:
                if is_429:
                    raise RateLimitExceededException(attempts, retry_after) from exc
                raise MaxRetriesExceededException(attempts, exc) from exc

            # Verify that exception type is eligible for retry
            if not isinstance(exc, retry_exceptions):
                raise

            # 4. Compute backoff sleep duration
            delay = backoff.compute_delay(attempt=attempts - 1, retry_after=retry_after)
            sleep_func(delay)


def retry_with_backoff(
    max_retries: int = 3,
    backoff: Optional[ExponentialBackoff] = None,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
    token_refresh_hook: Optional[Callable[[], Any]] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> Callable:
    """Decorator version of execute_with_retry."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return execute_with_retry(
                func,
                *args,
                max_retries=max_retries,
                backoff=backoff,
                retry_exceptions=retry_exceptions,
                non_retryable_exceptions=non_retryable_exceptions,
                token_refresh_hook=token_refresh_hook,
                circuit_breaker=circuit_breaker,
                sleep_func=sleep_func,
                **kwargs,
            )
        return wrapper
    return decorator
