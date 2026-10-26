"""Tests for ingestion ingress, provenance envelope validation, HMAC authentication, and DLQ handling."""
import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from core.db.session import (
    TenantIsolationViolationError,
    create_db_engine,
    create_session_factory,
    init_db,
)
from core.ingestion.dlq import DLQService
from core.ingestion.ingress import (
    IngestionEngine,
    ProvenanceEnvelope,
    compute_hmac_sha256,
    compute_idempotency_key,
    create_ingestion_app,
    verify_hmac_signature,
)
from core.models.ingestion import DeadLetterRecord
from core.models.tenants import Tenant


@pytest.fixture
def engine():
    """In-memory SQLite engine for ingestion testing."""
    eng = create_db_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    """Session factory."""
    return create_session_factory(engine)


@pytest.fixture
def db(session_factory):
    """DB session fixture."""
    session = session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_tenant(db):
    """Setup a sample tenant in the test DB."""
    tenant = Tenant(
        id="tenant-test-001",
        name="Test Ingestion Agency",
        slug="test-ingest-agency",
        tier="growth",
        status="active",
        settings={},
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def client(session_factory):
    """FastAPI TestClient with isolated engine."""
    ingestion_engine = IngestionEngine()
    app = create_ingestion_app(db_session_factory=session_factory, engine=ingestion_engine)
    return TestClient(app)


class TestProvenanceEnvelopeAndHMAC:
    """Tests for envelope structure, idempotency key generation, and cryptographic signatures."""

    def test_idempotency_key_deterministic(self):
        t1 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        key1 = compute_idempotency_key("tenant-1", "stripe", "evt_123", t1)
        key2 = compute_idempotency_key("tenant-1", "stripe", "evt_123", t1)
        key_different = compute_idempotency_key("tenant-2", "stripe", "evt_123", t1)

        assert key1 == key2
        assert key1 != key_different
        assert len(key1) == 64  # SHA-256 hex string

    def test_provenance_envelope_creation(self):
        event_time = datetime(2026, 10, 23, 10, 30, 0, tzinfo=timezone.utc)
        payload = {"ad_id": "ad_999", "spend": 450.50, "currency": "USD"}

        envelope = ProvenanceEnvelope.create(
            source_system="meta_ads",
            source_record_id="rec_meta_001",
            event_time=event_time,
            tenant_id="tenant-alpha",
            payload=payload,
            schema_version="1.0.0",
        )

        assert envelope.source_system == "meta_ads"
        assert envelope.source_record_id == "rec_meta_001"
        assert envelope.tenant_id == "tenant-alpha"
        assert envelope.schema_version == "1.0.0"
        assert envelope.payload["spend"] == 450.50
        assert envelope.ingestion_time is not None
        assert envelope.idempotency_key is not None

    def test_hmac_signature_verification(self):
        secret = "super-secret-webhook-key-42"
        body = b'{"event": "charge.succeeded", "amount": 10000}'

        signature = compute_hmac_sha256(secret, body)
        # Direct hex match
        assert verify_hmac_signature(body, secret, signature) is True
        # Match with sha256= prefix
        assert verify_hmac_signature(body, secret, f"sha256={signature}") is True
        # Mismatched signature
        assert verify_hmac_signature(body, secret, "wrong_signature") is False
        # Empty or missing
        assert verify_hmac_signature(body, secret, "") is False
        assert verify_hmac_signature(body, secret, None) is False


class TestDeadLetterQueueService:
    """Tests for DLQ queuing, isolation, and replay state transitions."""

    def test_dlq_enqueue_and_retrieval(self, db, test_tenant):
        record = DLQService.enqueue(
            db=db,
            tenant_id=test_tenant.id,
            source_system="hubspot",
            payload={"contact_id": "c_404", "lifecycle_stage": "lead"},
            error_reason="Contact email was missing",
            stack_trace="Traceback: ValueError",
            source_record_id="c_404",
        )

        assert record.id is not None
        assert record.tenant_id == test_tenant.id
        assert record.source_system == "hubspot"
        assert record.status == "FAILED"
        assert record.retry_count == 0
        assert record.replayed_at is None

        fetched = DLQService.get_record(db, test_tenant.id, record.id)
        assert fetched is not None
        assert fetched.id == record.id
        assert fetched.error_reason == "Contact email was missing"

    def test_dlq_strict_tenant_isolation(self, db, test_tenant):
        other_tenant = Tenant(id="tenant-test-002", name="Other", slug="other", tier="starter")
        db.add(other_tenant)
        db.commit()

        record = DLQService.enqueue(
            db=db,
            tenant_id=test_tenant.id,
            source_system="stripe",
            payload={"charge_id": "ch_123"},
            error_reason="Webhook timeout",
        )

        # Other tenant querying test_tenant's record must receive None
        assert DLQService.get_record(db, other_tenant.id, record.id) is None

        # Cross-tenant replay attempt must be blocked
        with pytest.raises(TenantIsolationViolationError):
            DLQService.replay(db, tenant_id=other_tenant.id, dlq_id=record.id)

    def test_dlq_successful_replay_lifecycle(self, db, test_tenant):
        record = DLQService.enqueue(
            db=db,
            tenant_id=test_tenant.id,
            source_system="meta_ads",
            payload={"campaign_id": "camp_1", "processed": False},
            error_reason="Transient network timeout",
        )

        replayed_payloads = []

        def sample_replay_handler(payload):
            replayed_payloads.append(payload)

        result = DLQService.replay(
            db=db,
            tenant_id=test_tenant.id,
            dlq_id=record.id,
            handler=sample_replay_handler,
        )

        assert result["status"] == "replayed"
        assert len(replayed_payloads) == 1
        assert replayed_payloads[0]["campaign_id"] == "camp_1"

        updated = DLQService.get_record(db, test_tenant.id, record.id)
        assert updated.status == "REPLAYED"
        assert updated.replayed_at is not None

        # Replaying an already replayed record returns already_replayed status
        re_result = DLQService.replay(db, test_tenant.id, record.id, handler=sample_replay_handler)
        assert re_result["status"] == "already_replayed"

    def test_dlq_failed_replay_increments_retry_count(self, db, test_tenant):
        record = DLQService.enqueue(
            db=db,
            tenant_id=test_tenant.id,
            source_system="meta_ads",
            payload={"bad": "data"},
            error_reason="Initial error",
        )

        def failing_handler(payload):
            raise RuntimeError("Database deadlocked again")

        result = DLQService.replay(db, test_tenant.id, record.id, handler=failing_handler)
        assert result["status"] == "replay_failed"
        assert "Database deadlocked again" in result["error"]
        assert result["retry_count"] == 1

        updated = DLQService.get_record(db, test_tenant.id, record.id)
        assert updated.status == "FAILED"
        assert updated.retry_count == 1
        assert "Replay failure: Database deadlocked again" in updated.error_reason


class TestIngestionAPIEndpoints:
    """Tests for POST /api/v1/ingest/{source_type} and DLQ replay APIs."""

    def test_missing_tenant_header_rejected(self, client):
        resp = client.post("/api/v1/ingest/stripe", json={"dummy": "value"})
        assert resp.status_code == 400
        assert "X-Tenant-ID" in resp.json()["detail"]

    def test_hmac_signature_enforcement(self, client, test_tenant):
        engine = client.app.state.engine
        secret = "stripe_test_secret_xyz"
        engine.configure_secret(test_tenant.id, "stripe", secret)

        envelope_data = {
            "source_system": "stripe",
            "source_record_id": "evt_001",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "tenant_id": test_tenant.id,
            "schema_version": "1.0.0",
            "idempotency_key": "stripe_evt_001_key",
            "payload": {"amount": 5000},
        }
        body_bytes = json.dumps(envelope_data).encode("utf-8")

        # 1. Missing signature when secret is configured -> 401
        resp_no_sig = client.post(
            "/api/v1/ingest/stripe",
            content=body_bytes,
            headers={"X-Tenant-ID": test_tenant.id, "Content-Type": "application/json"},
        )
        assert resp_no_sig.status_code == 401

        # 2. Invalid signature -> 401
        resp_bad_sig = client.post(
            "/api/v1/ingest/stripe",
            content=body_bytes,
            headers={
                "X-Tenant-ID": test_tenant.id,
                "X-Signature": "bad_sig",
                "Content-Type": "application/json",
            },
        )
        assert resp_bad_sig.status_code == 401

        # 3. Valid signature -> 201 Created
        valid_sig = compute_hmac_sha256(secret, body_bytes)
        resp_valid = client.post(
            "/api/v1/ingest/stripe",
            content=body_bytes,
            headers={
                "X-Tenant-ID": test_tenant.id,
                "X-Signature": f"sha256={valid_sig}",
                "Content-Type": "application/json",
            },
        )
        assert resp_valid.status_code == 201
        data = resp_valid.json()
        assert data["status"] == "accepted"
        assert data["idempotency_key"] == "stripe_evt_001_key"

    def test_idempotent_duplicate_submission(self, client, test_tenant):
        envelope_data = {
            "source_system": "hubspot",
            "source_record_id": "deal_55",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "tenant_id": test_tenant.id,
            "schema_version": "1.0.0",
            "idempotency_key": "deal_55_unique_key",
            "payload": {"stage": "Closed-Won"},
        }
        headers = {"X-Tenant-ID": test_tenant.id, "Content-Type": "application/json"}

        # First request
        resp1 = client.post("/api/v1/ingest/hubspot", json=envelope_data, headers=headers)
        assert resp1.status_code == 201
        assert resp1.json()["status"] == "accepted"

        # Duplicate request with same idempotency key
        resp2 = client.post("/api/v1/ingest/hubspot", json=envelope_data, headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "duplicate_ignored"

    def test_tenant_mismatch_in_envelope_rejected(self, client, test_tenant):
        envelope_data = {
            "source_system": "meta_ads",
            "source_record_id": "ad_10",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "tenant_id": "different-tenant-id",
            "schema_version": "1.0.0",
            "idempotency_key": "ad_10_key",
            "payload": {},
        }
        resp = client.post(
            "/api/v1/ingest/meta_ads",
            json=envelope_data,
            headers={"X-Tenant-ID": test_tenant.id},
        )
        assert resp.status_code == 403
        assert "Tenant mismatch" in resp.json()["detail"]

    def test_malformed_envelope_auto_routed_to_dlq(self, client, test_tenant, session_factory):
        # Missing required fields like source_system and idempotency_key
        bad_payload = {"random_field": "corrupted_json", "foo": 123}

        resp = client.post(
            "/api/v1/ingest/google_ads",
            json=bad_payload,
            headers={"X-Tenant-ID": test_tenant.id},
        )
        assert resp.status_code == 422
        res_data = resp.json()
        assert res_data["status"] == "dlq_enqueued"
        dlq_id = res_data["dlq_id"]
        assert dlq_id is not None

        # Verify record exists in DLQ table
        with session_factory() as s:
            record = DLQService.get_record(s, test_tenant.id, dlq_id)
            assert record is not None
            assert record.source_system == "google_ads"
            assert "Envelope validation failed" in record.error_reason

    def test_processing_failure_routed_to_dlq(self, client, test_tenant, session_factory):
        engine = client.app.state.engine

        def failing_processor(envelope):
            raise ValueError("Upstream analytics warehouse unreachable")

        engine.register_handler("webhook_failing", failing_processor)

        envelope_data = {
            "source_system": "webhook_failing",
            "source_record_id": "fail_123",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "tenant_id": test_tenant.id,
            "schema_version": "1.0.0",
            "idempotency_key": "fail_123_unique",
            "payload": {"data": 42},
        }

        resp = client.post(
            "/api/v1/ingest/webhook_failing",
            json=envelope_data,
            headers={"X-Tenant-ID": test_tenant.id},
        )
        assert resp.status_code == 500
        res_data = resp.json()
        assert res_data["status"] == "dlq_enqueued"
        dlq_id = res_data["dlq_id"]

        with session_factory() as s:
            record = DLQService.get_record(s, test_tenant.id, dlq_id)
            assert record is not None
            assert "Upstream analytics warehouse unreachable" in record.error_reason

    def test_dlq_replay_endpoint(self, client, test_tenant, session_factory):
        with session_factory() as s:
            record = DLQService.enqueue(
                db=s,
                tenant_id=test_tenant.id,
                source_system="stripe",
                payload={"invoice_id": "inv_123"},
                error_reason="Initial processing glitch",
            )
            record_id = record.id

        # Replay via API
        resp = client.post(
            f"/api/v1/ingest/dlq/{record_id}/replay",
            headers={"X-Tenant-ID": test_tenant.id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "replayed"

        # Cross tenant replay attempt via API
        resp_cross = client.post(
            f"/api/v1/ingest/dlq/{record_id}/replay",
            headers={"X-Tenant-ID": "unauthorized-tenant"},
        )
        assert resp_cross.status_code == 403

    def test_dlq_list_endpoint(self, client, test_tenant, session_factory):
        with session_factory() as s:
            DLQService.enqueue(
                db=s,
                tenant_id=test_tenant.id,
                source_system="meta_ads",
                payload={"ad": "1"},
                error_reason="Err 1",
            )
            DLQService.enqueue(
                db=s,
                tenant_id=test_tenant.id,
                source_system="hubspot",
                payload={"contact": "2"},
                error_reason="Err 2",
            )

        resp = client.get(
            "/api/v1/ingest/dlq",
            headers={"X-Tenant-ID": test_tenant.id},
        )
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) >= 2
        assert all(r["tenant_id"] == test_tenant.id for r in records)
