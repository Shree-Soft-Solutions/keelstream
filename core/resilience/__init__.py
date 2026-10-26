"""
KeelStream Resiliency, Fault Tolerance, and Rate-Limiting Module.
Provides backoff, circuit breaking, token refresh interceptors, and burst queuing.
"""

from core.resilience.backoff import ExponentialBackoff, parse_retry_after
from core.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from core.resilience.retry import (
    execute_with_retry,
    retry_with_backoff,
    MaxRetriesExceededException,
    RateLimitExceededException,
    AuthenticationError,
)
from core.resilience.queue_buffer import WebhookBurstBuffer, QueuedEvent, IngestionStatus
from core.resilience.database import ResilientDatabaseSession, DatabaseConnectionError

__all__ = [
    "ExponentialBackoff",
    "parse_retry_after",
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenException",
    "execute_with_retry",
    "retry_with_backoff",
    "MaxRetriesExceededException",
    "RateLimitExceededException",
    "AuthenticationError",
    "WebhookBurstBuffer",
    "QueuedEvent",
    "IngestionStatus",
    "ResilientDatabaseSession",
    "DatabaseConnectionError",
]
