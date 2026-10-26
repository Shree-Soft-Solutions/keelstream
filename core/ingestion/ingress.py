"""Ingestion ingress API, provenance envelope validation, HMAC authentication, and DLQ routing."""
import hashlib
import hmac
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from core.db.session import (
    TenantIsolationViolationError,
    create_db_engine,
    create_session_factory,
    init_db,
)
from core.ingestion.dlq import DLQService
from core.models.base import utc_now


def compute_idempotency_key(
    tenant_id: str,
    source_system: str,
    source_record_id: str,
    event_time: Any,
) -> str:
    """Generate a deterministic SHA-256 idempotency key for an ingestion payload."""
    time_str = event_time.isoformat() if isinstance(event_time, datetime) else str(event_time)
    seed = f"{tenant_id}:{source_system}:{source_record_id}:{time_str}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class ProvenanceEnvelope(BaseModel):
    """Standardized metadata envelope wrapper tracking source provenance and data lineage."""

    source_system: str = Field(..., description="Originating provider (e.g. meta_ads, stripe, hubspot)")
    source_record_id: str = Field(..., description="Unique ID of record within source system")
    event_time: datetime = Field(..., description="Timestamp when the event occurred at source")
    ingestion_time: datetime = Field(
        default_factory=utc_now,
        description="Timestamp when payload was received by KeelStream",
    )
    tenant_id: str = Field(..., description="Tenant organization ID")
    schema_version: str = Field(default="1.0.0", description="Data schema contract version")
    idempotency_key: str = Field(..., description="Deterministic key for duplicate detection")
    payload: Dict[str, Any] = Field(..., description="Raw canonical payload data")

    @classmethod
    def create(
        cls,
        source_system: str,
        source_record_id: str,
        event_time: datetime,
        tenant_id: str,
        payload: Dict[str, Any],
        schema_version: str = "1.0.0",
        idempotency_key: Optional[str] = None,
    ) -> "ProvenanceEnvelope":
        """Factory helper computing idempotency_key if not provided."""
        if not idempotency_key:
            idempotency_key = compute_idempotency_key(
                tenant_id=tenant_id,
                source_system=source_system,
                source_record_id=source_record_id,
                event_time=event_time,
            )
        return cls(
            source_system=source_system,
            source_record_id=source_record_id,
            event_time=event_time,
            tenant_id=tenant_id,
            schema_version=schema_version,
            idempotency_key=idempotency_key,
            payload=payload,
        )


def compute_hmac_sha256(secret: str, data: bytes) -> str:
    """Compute HMAC SHA-256 hex digest for given secret and byte payload."""
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


def verify_hmac_signature(
    body: bytes,
    secret: str,
    signature_header: Optional[str],
) -> bool:
    """Validate webhook HMAC SHA-256 signature against raw request bytes."""
    if not signature_header or not secret:
        return False

    raw_signature = signature_header.strip()
    if raw_signature.startswith("sha256="):
        raw_signature = raw_signature.split("sha256=", 1)[1]
    elif raw_signature.startswith("sha1="):
        raw_signature = raw_signature.split("sha1=", 1)[1]

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(raw_signature.lower(), expected.lower())


class IngestionEngine:
    """Core ingestion engine managing secrets, deduplication, and pipeline execution."""

    def __init__(self):
        # Maps (tenant_id, source_type) -> webhook secret
        self.webhook_secrets: Dict[str, str] = {}
        # Stores processed idempotency keys: set of f"{tenant_id}:{idempotency_key}"
        self.processed_keys: Set[str] = set()
        # Source handlers registry: source_type -> callable(envelope)
        self.handlers: Dict[str, Callable[[ProvenanceEnvelope], Any]] = {}

    def configure_secret(self, tenant_id: str, source_type: str, secret: str) -> None:
        """Register a webhook HMAC secret for a tenant and source type."""
        key = f"{tenant_id}:{source_type}"
        self.webhook_secrets[key] = secret

    def get_secret(self, tenant_id: str, source_type: str) -> Optional[str]:
        """Retrieve registered secret for tenant and source type."""
        return self.webhook_secrets.get(f"{tenant_id}:{source_type}")

    def register_handler(
        self,
        source_type: str,
        handler: Callable[[ProvenanceEnvelope], Any],
    ) -> None:
        """Register a pipeline processing handler for a source type."""
        self.handlers[source_type] = handler

    def is_processed(self, tenant_id: str, idempotency_key: str) -> bool:
        """Check if an idempotency key has already been successfully processed."""
        return f"{tenant_id}:{idempotency_key}" in self.processed_keys

    def mark_processed(self, tenant_id: str, idempotency_key: str) -> None:
        """Record idempotency key as successfully processed."""
        self.processed_keys.add(f"{tenant_id}:{idempotency_key}")


def create_ingestion_app(
    db_session_factory,
    engine: Optional[IngestionEngine] = None,
) -> FastAPI:
    """Factory creating the FastAPI app with ingestion endpoints and DLQ management."""
    app = FastAPI(title="KeelStream Ingestion API", version="1.0.0")
    ingestion_engine = engine or IngestionEngine()

    def get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    @app.post("/api/v1/ingest/{source_type}", status_code=status.HTTP_201_CREATED)
    async def ingest_record(
        source_type: str,
        request: Request,
        response: Response,
        x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
        x_signature: Optional[str] = Header(None, alias="X-Signature"),
        x_hub_signature: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
        db: Session = Depends(get_db),
    ):
        """Standardized ingestion ingress endpoint with provenance tracking and DLQ fallback."""
        if not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required X-Tenant-ID header",
            )

        raw_body = await request.body()
        sig = x_signature or x_hub_signature

        # 1. HMAC Signature Verification if secret is configured
        secret = ingestion_engine.get_secret(x_tenant_id, source_type)
        if secret:
            if not sig or not verify_hmac_signature(raw_body, secret, sig):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing HMAC signature",
                )

        # 2. Parse and Validate Provenance Envelope
        try:
            body_json = json.loads(raw_body.decode("utf-8"))
            envelope = ProvenanceEnvelope(**body_json)
        except Exception as exc:
            # Enqueue unparseable payload directly to DLQ
            trace = traceback.format_exc()
            dlq_record = DLQService.enqueue(
                db=db,
                tenant_id=x_tenant_id,
                source_system=source_type,
                payload=body_json if "body_json" in locals() and isinstance(body_json, dict) else {"raw": raw_body.decode("utf-8", errors="replace")},
                error_reason=f"Envelope validation failed: {str(exc)}",
                stack_trace=trace,
            )
            return Response(
                content=json.dumps({
                    "status": "dlq_enqueued",
                    "detail": f"Envelope validation failed: {str(exc)}",
                    "dlq_id": dlq_record.id,
                }),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                media_type="application/json",
            )

        # 3. Tenant Boundary Verification
        if envelope.tenant_id != x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tenant mismatch: Header is '{x_tenant_id}', payload is '{envelope.tenant_id}'",
            )

        # 4. Idempotency Check
        if ingestion_engine.is_processed(x_tenant_id, envelope.idempotency_key):
            response.status_code = status.HTTP_200_OK
            return {
                "status": "duplicate_ignored",
                "idempotency_key": envelope.idempotency_key,
                "source_record_id": envelope.source_record_id,
            }

        # 5. Pipeline Processing Execution
        handler = ingestion_engine.handlers.get(source_type)
        if handler:
            try:
                handler(envelope)
            except Exception as exc:
                trace = traceback.format_exc()
                dlq_record = DLQService.enqueue(
                    db=db,
                    tenant_id=x_tenant_id,
                    source_system=source_type,
                    payload=envelope.model_dump(mode="json"),
                    error_reason=f"Processing exception: {str(exc)}",
                    stack_trace=trace,
                    source_record_id=envelope.source_record_id,
                    idempotency_key=envelope.idempotency_key,
                )
                return Response(
                    content=json.dumps({
                        "status": "dlq_enqueued",
                        "detail": f"Processing exception: {str(exc)}",
                        "dlq_id": dlq_record.id,
                    }),
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    media_type="application/json",
                )

        # Mark as processed
        ingestion_engine.mark_processed(x_tenant_id, envelope.idempotency_key)

        return {
            "status": "accepted",
            "idempotency_key": envelope.idempotency_key,
            "source_record_id": envelope.source_record_id,
            "ingestion_time": envelope.ingestion_time.isoformat(),
        }

    @app.post("/api/v1/ingest/dlq/{dlq_id}/replay")
    async def replay_dlq_record(
        dlq_id: str,
        x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
        db: Session = Depends(get_db),
    ):
        """Replay API: reprocess a failed record from the dead-letter queue."""
        if not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required X-Tenant-ID header",
            )

        try:
            # Use registered source handler during replay if available
            def replay_handler(payload: Dict[str, Any]):
                source = payload.get("source_system")
                handler = ingestion_engine.handlers.get(source)
                if handler:
                    envelope = ProvenanceEnvelope(**payload)
                    handler(envelope)

            result = DLQService.replay(
                db=db,
                tenant_id=x_tenant_id,
                dlq_id=dlq_id,
                handler=replay_handler,
            )
            return result
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )
        except TenantIsolationViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Replay failed: {str(exc)}",
            )

    @app.get("/api/v1/ingest/dlq")
    async def list_dlq_records(
        x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
        status_filter: Optional[str] = None,
        limit: int = 50,
        db: Session = Depends(get_db),
    ):
        """List dead-letter queue records for the calling tenant."""
        if not x_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required X-Tenant-ID header",
            )

        records = DLQService.list_records(
            db=db,
            tenant_id=x_tenant_id,
            status=status_filter,
            limit=limit,
        )
        return [
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "source_system": r.source_system,
                "source_record_id": r.source_record_id,
                "error_reason": r.error_reason,
                "status": r.status,
                "retry_count": r.retry_count,
                "replayed_at": r.replayed_at.isoformat() if r.replayed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]

    # Expose engine on app state
    app.state.engine = ingestion_engine
    return app
