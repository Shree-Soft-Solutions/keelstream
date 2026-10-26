"""Ingestion models including Dead-Letter Queue (DLQ) records."""
from typing import Any, Dict, Optional
from datetime import datetime
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TenantScopedMixin, TimestampMixin, generate_uuid


class DeadLetterRecord(Base, TenantScopedMixin, TimestampMixin):
    """Dead-letter record storing failed ingestion events for debugging and replay."""
    __tablename__ = "dead_letter_records"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    source_system: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    source_record_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    error_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    stack_trace: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="FAILED",
        nullable=False,
        index=True,
    )
    replayed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index("ix_dlq_tenant_status", "tenant_id", "status"),
        Index("ix_dlq_tenant_idempotency", "tenant_id", "idempotency_key"),
    )

    def __repr__(self) -> str:
        return f"<DeadLetterRecord id={self.id} tenant_id={self.tenant_id} source={self.source_system} status={self.status}>"
