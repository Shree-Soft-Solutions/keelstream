"""
KeelStream Fault Tolerance & Resiliency Test Suite.
Validates exponential backoff, rate limiting (HTTP 429), expired credential refresh (HTTP 401),
database disconnects, webhook burst buffering, and circuit breaker fault isolation.
"""

import time
import pytest
from unittest.mock import Mock, call

from core.resilience.backoff import ExponentialBackoff, parse_retry_after
from core.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from core.resilience.retry import (
    execute_with_retry,
    retry_with_backoff,
    MaxRetriesExceededException,
    RateLimitExceededException,
    AuthenticationError,
)
from core.resilience.queue_buffer import WebhookBurstBuffer, IngestionStatus
from core.resilience.database import ResilientDatabaseSession, DatabaseConnectionError


# =============================================================================
# Helper Custom Exception Mock Classes
# =============================================================================

class MockHTTPRateLimitError(Exception):
    def __init__(self, message="Too Many Requests", retry_after=2.0):
        super().__init__(message)
        self.status_code = 429
        self.headers = {"Retry-After": str(retry_after)}
        self.retry_after = retry_after


class MockHTTPUnauthorizedError(Exception):
    def __init__(self, message="Token Expired"):
        super().__init__(message)
        self.status_code = 401


class MockHTTPForbiddenError(Exception):
    def __init__(self, message="Forbidden"):
        super().__init__(message)
        self.status_code = 403


# =============================================================================
# 1. Exponential Backoff & Retry-After Unit Tests
# =============================================================================

def test_exponential_backoff_progression():
    """Verify delays scale exponentially with attempts: base * (multiplier ** attempt)."""
    backoff = ExponentialBackoff(base_delay=1.0, multiplier=2.0, max_delay=60.0, jitter=False)

    assert backoff.compute_delay(attempt=0) == 1.0   # 1 * 2^0
    assert backoff.compute_delay(attempt=1) == 2.0   # 1 * 2^1
    assert backoff.compute_delay(attempt=2) == 4.0   # 1 * 2^2
    assert backoff.compute_delay(attempt=3) == 8.0   # 1 * 2^3
    assert backoff.compute_delay(attempt=4) == 16.0  # 1 * 2^4


def test_exponential_backoff_max_delay_cap():
    """Verify delays are strictly bounded by max_delay."""
    backoff = ExponentialBackoff(base_delay=1.0, multiplier=2.0, max_delay=10.0, jitter=False)

    assert backoff.compute_delay(attempt=5) == 10.0  # 32 capped to 10
    assert backoff.compute_delay(attempt=10) == 10.0 # 1024 capped to 10


def test_retry_after_header_parsing():
    """Verify parsing of integer seconds and HTTP-Date strings."""
    assert parse_retry_after("60") == 60.0
    assert parse_retry_after(15) == 15.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("invalid-string") is None

    # HTTP-date format (future date)
    future_date_str = "Fri, 31 Dec 2030 23:59:59 GMT"
    delay = parse_retry_after(future_date_str)
    assert delay is not None
    assert delay > 0


def test_retry_after_overrides_exponential_delay():
    """Verify that an explicit Retry-After header overrides the computed exponential delay."""
    backoff = ExponentialBackoff(base_delay=1.0, multiplier=2.0, max_delay=30.0, jitter=False)

    # Attempt 0 would normally be 1.0s, but Retry-After=5.5 overrides it
    delay = backoff.compute_delay(attempt=0, retry_after=5.5)
    assert delay == 5.5

    # Retry-After exceeding max_delay is safely capped
    delay_capped = backoff.compute_delay(attempt=0, retry_after=120.0)
    assert delay_capped == 30.0


def test_jitter_distribution():
    """Verify full jitter distributes delays in range [0, raw_delay]."""
    backoff = ExponentialBackoff(base_delay=10.0, max_delay=10.0, jitter=True, jitter_mode="full")
    samples = [backoff.compute_delay(attempt=0) for _ in range(50)]

    assert all(0.0 <= s <= 10.0 for s in samples)
    # Check that not all samples are identical (dispersion)
    assert len(set(samples)) > 1


# =============================================================================
# 2. HTTP 429 Rate Limiting Simulation & Recovery
# =============================================================================

def test_rate_limit_transient_recovery():
    """
    Simulate an external API (e.g. Meta Ads API) returning 429 on first 2 calls,
    then recovering and returning 200 OK on attempt 3.
    """
    mock_api = Mock(side_effect=[
        MockHTTPRateLimitError("Rate limit hit", retry_after=1.5),
        MockHTTPRateLimitError("Rate limit hit", retry_after=2.0),
        {"status": "ok", "campaigns": ["camp_123"]},
    ])

    slept_delays = []
    mock_sleep = lambda d: slept_delays.append(d)

    result = execute_with_retry(
        mock_api,
        max_retries=3,
        sleep_func=mock_sleep,
    )

    assert result == {"status": "ok", "campaigns": ["camp_123"]}
    assert mock_api.call_count == 3
    assert len(slept_delays) == 2
    # First sleep honored retry_after=1.5, second honored retry_after=2.0
    assert slept_delays[0] == 1.5
    assert slept_delays[1] == 2.0


def test_rate_limit_max_retries_exceeded():
    """
    Simulate persistent 429 rate limiting exceeding max retry budget.
    Should raise RateLimitExceededException with telemetry details.
    """
    mock_api = Mock(side_effect=MockHTTPRateLimitError("Rate limited", retry_after=3.0))
    slept_delays = []

    with pytest.raises(RateLimitExceededException) as exc_info:
        execute_with_retry(
            mock_api,
            max_retries=2,
            sleep_func=lambda d: slept_delays.append(d),
        )

    assert exc_info.value.attempts == 3 # Initial attempt + 2 retries
    assert exc_info.value.retry_after == 3.0
    assert len(slept_delays) == 2


def test_thundering_herd_prevention_with_jitter():
    """
    Simulate 50 parallel workers all hitting 429 at the exact same moment.
    Verify that jitter disperses retry backoff schedules across the timeline.
    """
    backoff = ExponentialBackoff(base_delay=2.0, multiplier=2.0, max_delay=10.0, jitter=True, jitter_mode="full")
    scheduled_times = [backoff.compute_delay(attempt=1) for _ in range(50)]

    # Statistical variance must be significant (std deviation > 0)
    variance = sum((x - (sum(scheduled_times) / len(scheduled_times))) ** 2 for x in scheduled_times) / len(scheduled_times)
    assert variance > 0.1
    assert min(scheduled_times) >= 0.0
    assert max(scheduled_times) <= 4.0


# =============================================================================
# 3. Expired Credentials & Token Refresh (HTTP 401)
# =============================================================================

def test_expired_token_auto_refresh_success():
    """
    Simulate expired Keycloak / OIDC Bearer token returning 401 Unauthorized.
    The interceptor calls the refresh hook, updates auth headers, and succeeds.
    """
    token_store = {"token": "expired_jwt_token"}
    refresh_hook = Mock(side_effect=lambda: token_store.update({"token": "fresh_jwt_token_valid"}))

    def mock_protected_endpoint():
        if token_store["token"] == "expired_jwt_token":
            raise MockHTTPUnauthorizedError("Token expired")
        return {"user": "analyst@keelstream.com", "role": "admin"}

    result = execute_with_retry(
        mock_protected_endpoint,
        max_retries=2,
        token_refresh_hook=refresh_hook,
    )

    assert result["user"] == "analyst@keelstream.com"
    assert refresh_hook.call_count == 1
    assert token_store["token"] == "fresh_jwt_token_valid"


def test_expired_token_refresh_failure():
    """
    If the refresh hook fails (e.g. revoked client credentials or IdP down),
    AuthenticationError should be raised immediately without loop.
    """
    failing_refresh = Mock(side_effect=RuntimeError("Keycloak unreachable"))
    mock_endpoint = Mock(side_effect=MockHTTPUnauthorizedError("Token expired"))

    with pytest.raises(AuthenticationError) as exc_info:
        execute_with_retry(
            mock_endpoint,
            max_retries=3,
            token_refresh_hook=failing_refresh,
        )

    assert "Failed to refresh authentication token" in str(exc_info.value)
    assert failing_refresh.call_count == 1


def test_non_retryable_auth_forbidden_403():
    """HTTP 403 Forbidden is non-retryable and must abort immediately without wasting retries."""
    mock_api = Mock(side_effect=MockHTTPForbiddenError("Tenant access denied"))

    with pytest.raises(MockHTTPForbiddenError):
        execute_with_retry(
            mock_api,
            max_retries=3,
            non_retryable_exceptions=(MockHTTPForbiddenError,),
        )

    assert mock_api.call_count == 1


# =============================================================================
# 4. Database Disconnect & Transient Failover Simulation
# =============================================================================

def test_database_disconnect_idempotent_query_retry():
    """
    Simulate database connection dropping mid-transaction during an idempotent read/upsert.
    Verify transaction rollback, auto-reconnect, and successful recovery.
    """
    db = ResilientDatabaseSession()
    db.begin()

    # Drop connection abruptly
    db.simulate_disconnect()
    assert not db.is_connected

    # Execute idempotent query
    result = db.execute_query("SELECT * FROM attribution_touchpoints WHERE tenant_id = 't1'", is_idempotent=True)

    assert result["status"] == "SUCCESS"
    assert db.is_connected
    assert db.reconnect_count == 1


def test_database_disconnect_non_idempotent_failsafe():
    """
    Non-idempotent operations must NOT automatically retry upon unknown connection state
    to prevent duplicate financial ledger postings or double charges.
    """
    db = ResilientDatabaseSession()
    db.simulate_disconnect()

    with pytest.raises(DatabaseConnectionError):
        db.execute_query(
            "INSERT INTO financial_ledger (amount, tenant_id) VALUES (500, 't1')",
            is_idempotent=False
        )

    assert db.reconnect_count == 0


# =============================================================================
# 5. Webhook Ingestion Bursts & Queue Buffering (Zero Data Loss)
# =============================================================================

def test_webhook_burst_buffering_and_zero_data_loss():
    """
    Simulate a traffic spike: 1,000 incoming webhook events arriving in a burst.
    Verify:
      1. Zero data loss during queuing.
      2. Events are successfully chunked into batches of 50.
      3. Total acknowledged matches total enqueued.
    """
    buffer = WebhookBurstBuffer(max_buffer_per_tenant=5000)
    tenant_id = "tenant_enterprise_beta"
    burst_count = 1000

    # 1. Enqueue burst
    for i in range(burst_count):
        payload = {
            "event_type": "conversion",
            "order_id": f"ord_{i}",
            "amount": 49.99,
            "timestamp": time.time(),
        }
        event = buffer.enqueue(tenant_id=tenant_id, payload=payload, idempotency_key=f"idemp_{i}")
        assert event.status == IngestionStatus.QUEUED

    assert buffer.get_queue_depth(tenant_id) == burst_count

    # 2. Batch chunking consumption (batch_size=50)
    processed_count = 0
    batch_size = 50

    while buffer.get_queue_depth(tenant_id) > 0:
        batch = buffer.pop_batch(tenant_id, batch_size=batch_size)
        assert len(batch) <= batch_size
        for event in batch:
            buffer.ack(event)
            assert event.status == IngestionStatus.ACKNOWLEDGED
            processed_count += 1

    assert processed_count == burst_count
    assert buffer.get_queue_depth(tenant_id) == 0


def test_webhook_idempotency_deduplication():
    """Duplicate payloads with the same idempotency key must be cleanly ignored without duplicate records."""
    buffer = WebhookBurstBuffer()
    tenant_id = "tenant_alpha"
    payload = {"action": "payment_succeeded", "stripe_event_id": "evt_998877"}

    first = buffer.enqueue(tenant_id, payload, idempotency_key="stripe_evt_998877")
    second = buffer.enqueue(tenant_id, payload, idempotency_key="stripe_evt_998877")

    assert first.status == IngestionStatus.QUEUED
    assert second.status == IngestionStatus.DUPLICATE_IGNORED
    assert second.event_id == first.event_id
    assert buffer.get_queue_depth(tenant_id) == 1


def test_webhook_poison_pill_routing_to_dlq():
    """
    Malformed payloads that throw persistent exceptions must be routed to the Dead-Letter Queue (DLQ)
    after max_dlq_retries, while regular events continue unhindered.
    """
    buffer = WebhookBurstBuffer(max_dlq_retries=3)
    tenant_id = "tenant_beta"

    # Enqueue 1 toxic event and 1 healthy event
    bad_event = buffer.enqueue(tenant_id, {"corrupted": True}, idempotency_key="bad_1")
    good_event = buffer.enqueue(tenant_id, {"corrupted": False}, idempotency_key="good_1")

    # Simulate processing failure for bad_event 3 times
    for attempt in range(3):
        batch = buffer.pop_batch(tenant_id, batch_size=10)
        for ev in batch:
            if ev.payload.get("corrupted"):
                buffer.nack(ev, error=ValueError("Unparseable schema format"))
            else:
                buffer.ack(ev)

    assert bad_event.status == IngestionStatus.DEAD_LETTER
    assert good_event.status == IngestionStatus.ACKNOWLEDGED

    dlq_events = buffer.get_dlq_events(tenant_id)
    assert len(dlq_events) == 1
    assert dlq_events[0].event_id == bad_event.event_id
    assert len(dlq_events[0].error_history) == 3


def test_strict_multi_tenant_queue_isolation():
    """
    Guarantees Zero Cross-Tenant Contamination:
    Events for Tenant A must never be accessible or returned in Tenant B batches.
    """
    buffer = WebhookBurstBuffer()
    tenant_a = "tenant_meta_agency"
    tenant_b = "tenant_google_agency"

    buffer.enqueue(tenant_a, {"tenant": "A", "val": 1})
    buffer.enqueue(tenant_a, {"tenant": "A", "val": 2})
    buffer.enqueue(tenant_b, {"tenant": "B", "val": 3})

    # Pull batch specifically for tenant_a
    batch_a = buffer.pop_batch(tenant_a, batch_size=10)
    assert len(batch_a) == 2
    assert all(e.tenant_id == tenant_a for e in batch_a)

    # Pull batch specifically for tenant_b
    batch_b = buffer.pop_batch(tenant_b, batch_size=10)
    assert len(batch_b) == 1
    assert batch_b[0].tenant_id == tenant_b

    # Verify queues are empty
    assert buffer.get_queue_depth(tenant_a) == 0
    assert buffer.get_queue_depth(tenant_b) == 0


# =============================================================================
# 6. Circuit Breaker State Transitions & Fault Isolation
# =============================================================================

def test_circuit_breaker_trips_to_open_on_consecutive_failures():
    """Circuit breaker transitions CLOSED -> OPEN after reaching failure threshold."""
    cb = CircuitBreaker(service_name="hubspot_api", failure_threshold=3, recovery_timeout=5.0)

    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure() # 3rd failure trips the breaker
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_fast_fails_when_open():
    """When OPEN, any call attempt must raise CircuitBreakerOpenException immediately."""
    cb = CircuitBreaker(service_name="stripe_api", failure_threshold=2, recovery_timeout=10.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    mock_fn = Mock()
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        cb.call(mock_fn)

    assert "stripe_api" in str(exc_info.value)
    assert mock_fn.call_count == 0  # Downstream was never hit (fast fail)


def test_circuit_breaker_half_open_recovery():
    """
    After recovery timeout, OPEN breaker transitions to HALF_OPEN.
    A successful canary trial transitions it back to CLOSED.
    """
    cb = CircuitBreaker(service_name="meta_api", failure_threshold=1, recovery_timeout=0.1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Wait past recovery timeout
    time.sleep(0.12)

    # Calling allow_request transitions state to HALF_OPEN
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Successful canary probe recovers the breaker
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
