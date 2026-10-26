"""Dead-Letter Queue (DLQ) service for managing and replaying failed ingestion records."""
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import traceback
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.session import TenantIsolationViolationError
from core.models.base import utc_now
from core.models.ingestion import DeadLetterRecord


class DLQService:
    """Service providing dead-letter queuing, tenant-isolated lookups, and replay."""

    @staticmethod
    def enqueue(
        db: Session,
        tenant_id: str,
        source_system: str,
        payload: Any,
        error_reason: str,
        stack_trace: Optional[str] = None,
        source_record_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> DeadLetterRecord:
        """Persist a failed payload to dead_letter_records table."""
        if not tenant_id:
            raise TenantIsolationViolationError("Tenant ID is required to enqueue dead-letter record")

        record = DeadLetterRecord(
            tenant_id=tenant_id,
            source_system=source_system,
            source_record_id=source_record_id,
            payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
            error_reason=error_reason,
            stack_trace=stack_trace,
            status="FAILED",
            retry_count=0,
            idempotency_key=idempotency_key,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def get_record(db: Session, tenant_id: str, dlq_id: str) -> Optional[DeadLetterRecord]:
        """Fetch a specific dead-letter record strictly within the tenant boundary."""
        if not tenant_id:
            raise TenantIsolationViolationError("Tenant ID is required for DLQ lookup")

        stmt = select(DeadLetterRecord).where(
            DeadLetterRecord.id == dlq_id,
            DeadLetterRecord.tenant_id == tenant_id,
        )
        return db.scalars(stmt).first()

    @staticmethod
    def list_records(
        db: Session,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[DeadLetterRecord]:
        """List dead-letter records for the tenant, optionally filtered by status."""
        if not tenant_id:
            raise TenantIsolationViolationError("Tenant ID is required for DLQ listing")

        stmt = select(DeadLetterRecord).where(DeadLetterRecord.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(DeadLetterRecord.status == status)
        stmt = stmt.order_by(DeadLetterRecord.created_at.desc()).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def replay(
        db: Session,
        tenant_id: str,
        dlq_id: str,
        handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Replay a failed record.

        Verifies tenant ownership, executes the replay handler, and updates record status.
        """
        if not tenant_id:
            raise TenantIsolationViolationError("Tenant ID is required for replay")

        # Security check: verify record exists and belongs to the specified tenant
        record = db.scalars(
            select(DeadLetterRecord).where(DeadLetterRecord.id == dlq_id)
        ).first()

        if record is None:
            raise LookupError(f"Dead letter record '{dlq_id}' not found")

        if record.tenant_id != tenant_id:
            raise TenantIsolationViolationError(
                f"Cross-tenant replay violation: record belongs to tenant '{record.tenant_id}', "
                f"access attempted by tenant '{tenant_id}'"
            )

        if record.status == "REPLAYED":
            return {
                "status": "already_replayed",
                "dlq_id": record.id,
                "replayed_at": record.replayed_at.isoformat() if record.replayed_at else None,
            }

        try:
            if handler:
                handler(record.payload)

            record.status = "REPLAYED"
            record.replayed_at = utc_now()
            db.commit()
            db.refresh(record)

            return {
                "status": "replayed",
                "dlq_id": record.id,
                "replayed_at": record.replayed_at.isoformat() if record.replayed_at else None,
                "retry_count": record.retry_count,
            }
        except Exception as exc:
            record.retry_count += 1
            record.error_reason = f"Replay failure: {str(exc)}"
            record.stack_trace = traceback.format_exc()
            db.commit()
            db.refresh(record)

            return {
                "status": "replay_failed",
                "dlq_id": record.id,
                "error": str(exc),
                "retry_count": record.retry_count,
            }
