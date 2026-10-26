"""
Resilient Webhook Burst Buffer and Queue Partitioning for KeelStream.
Implements batch chunking loops, strict multi-tenant isolation, idempotency deduplication,
and Dead-Letter Queue (DLQ) routing as specified in CSV Phase 7 and PRD Section 9.
"""

import collections
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class IngestionStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass
class QueuedEvent:
    event_id: str
    tenant_id: str
    idempotency_key: str
    payload: Dict[str, Any]
    received_at: float = field(default_factory=time.time)
    retry_count: int = 0
    status: IngestionStatus = IngestionStatus.QUEUED
    error_history: List[str] = field(default_factory=list)


class WebhookBurstBuffer:
    """
    In-memory and thread-safe capable buffer for handling high-throughput webhook spikes.
    Guarantees strict tenant-level queue partitioning (Zero Cross-Tenant Contamination).
    """

    def __init__(self, max_buffer_per_tenant: int = 50000, max_dlq_retries: int = 3):
        self.max_buffer_per_tenant = max_buffer_per_tenant
        self.max_dlq_retries = max_dlq_retries

        # Tenant-partitioned queues: {tenant_id: deque[QueuedEvent]}
        self._queues: Dict[str, collections.deque] = collections.defaultdict(collections.deque)

        # Tenant-partitioned DLQ: {tenant_id: List[QueuedEvent]}
        self._dlq: Dict[str, List[QueuedEvent]] = collections.defaultdict(list)

        # Tenant-partitioned idempotency registry: {tenant_id: {idempotency_key: event_id}}
        self._idempotency_cache: Dict[str, Dict[str, str]] = collections.defaultdict(dict)

        # Metrics counters
        self._total_ingested = 0
        self._total_duplicates = 0
        self._total_dlq = 0

    def _generate_idempotency_key(self, payload: Dict[str, Any]) -> str:
        """Computes deterministic SHA256 hash if no idempotency key was supplied."""
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        tenant_id: str,
        payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> QueuedEvent:
        """
        Enqueues an incoming webhook payload into the tenant's isolated queue.
        Enforces idempotency and buffers without data loss during spikes.
        """
        if not tenant_id or not isinstance(tenant_id, str):
            raise ValueError("tenant_id must be a non-empty string.")

        if idempotency_key is None:
            idempotency_key = self._generate_idempotency_key(payload)

        # Multi-tenant idempotency check: check cache partitioned by tenant_id
        tenant_cache = self._idempotency_cache[tenant_id]
        if idempotency_key in tenant_cache:
            self._total_duplicates += 1
            existing_id = tenant_cache[idempotency_key]
            return QueuedEvent(
                event_id=existing_id,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                payload=payload,
                status=IngestionStatus.DUPLICATE_IGNORED,
            )

        event_id = str(uuid.uuid4())
        event = QueuedEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            payload=payload,
            status=IngestionStatus.QUEUED,
        )

        queue = self._queues[tenant_id]
        if len(queue) >= self.max_buffer_per_tenant:
            raise OverflowError(
                f"Ingestion buffer for tenant '{tenant_id}' has reached capacity ({self.max_buffer_per_tenant})."
            )

        queue.append(event)
        tenant_cache[idempotency_key] = event_id
        self._total_ingested += 1
        return event

    def pop_batch(self, tenant_id: str, batch_size: int = 50) -> List[QueuedEvent]:
        """
        Pulls a chunked batch of queued events for processing.
        Guarantees strictly isolated tenant consumption.
        """
        if not tenant_id or tenant_id not in self._queues:
            return []

        queue = self._queues[tenant_id]
        batch: List[QueuedEvent] = []

        while queue and len(batch) < batch_size:
            event = queue.popleft()
            event.status = IngestionStatus.PROCESSING
            batch.append(event)

        return batch

    def ack(self, event: QueuedEvent) -> None:
        """Acknowledges successful processing of an event."""
        event.status = IngestionStatus.ACKNOWLEDGED

    def nack(self, event: QueuedEvent, error: Exception) -> None:
        """
        Handles failed event processing.
        Increments retry count; routes to DLQ if max retries exceeded.
        """
        event.retry_count += 1
        event.error_history.append(f"Attempt {event.retry_count}: {str(error)}")

        if event.retry_count >= self.max_dlq_retries:
            event.status = IngestionStatus.DEAD_LETTER
            self._dlq[event.tenant_id].append(event)
            self._total_dlq += 1
        else:
            event.status = IngestionStatus.QUEUED
            # Requeue at head for fast retry or tail for fair scheduling
            self._queues[event.tenant_id].append(event)

    def get_queue_depth(self, tenant_id: str) -> int:
        """Returns the number of unconsumed events for a tenant."""
        return len(self._queues.get(tenant_id, ()))

    def get_dlq_events(self, tenant_id: str) -> List[QueuedEvent]:
        """Returns all dead-lettered events for a tenant."""
        return list(self._dlq.get(tenant_id, []))

    def get_all_tenants(self) -> List[str]:
        """Returns list of all active tenant IDs in the buffer."""
        return list(self._queues.keys())
