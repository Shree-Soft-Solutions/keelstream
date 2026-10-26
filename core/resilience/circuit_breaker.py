"""
Circuit Breaker pattern implementation for isolating downstream failures.
Protects KeelStream against cascading outages when third-party APIs (Meta, Google, HubSpot, Stripe) fail.
"""

import time
from enum import Enum
from typing import Callable, Any, Optional


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: requests pass through
    OPEN = "OPEN"            # Tripped: requests fail fast without hitting downstream
    HALF_OPEN = "HALF_OPEN"  # Testing recovery: allows single canary trial request


class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is in OPEN state."""

    def __init__(self, service_name: str, retry_after: float):
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker for service '{service_name}' is OPEN. "
            f"Downstream service is degraded. Try again after {retry_after:.2f}s."
        )


class CircuitBreaker:
    """
    Standard three-state Circuit Breaker.
    """

    def __init__(
        self,
        service_name: str = "default_service",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1.")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be > 0.")

        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self.last_failure_time: Optional[float] = None

    def allow_request(self) -> bool:
        """
        Determines whether a request should be permitted to execute.
        Throws CircuitBreakerOpenException if OPEN and timeout hasn't elapsed.
        """
        now = time.time()

        if self.state == CircuitState.OPEN:
            elapsed = now - self.last_state_change
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                self.success_count = 0
                return True
            else:
                remaining = self.recovery_timeout - elapsed
                raise CircuitBreakerOpenException(self.service_name, remaining)

        return True

    def record_success(self) -> None:
        """Records a successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.last_state_change = time.time()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self) -> None:
        """Records a failed operation."""
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Canary test failed: immediately re-trip to OPEN
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            self.failure_count = self.failure_threshold
        elif self.state == CircuitState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_state_change = time.time()

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Executes a callable through the circuit breaker guard.
        """
        self.allow_request()
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def reset(self) -> None:
        """Manually forces the circuit breaker back to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
