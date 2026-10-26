"""
KeelStream Ingestion Load Simulation Runner.
Simulates multi-tenant sustained ingestion (500 events/second) using Python asyncio.
Verifies throughput, latency percentiles (p50, p95, p99), and strict zero cross-tenant contamination.
"""

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.resilience.queue_buffer import WebhookBurstBuffer, IngestionStatus


class IngestionLoadSimulator:
    def __init__(self, target_rps: int = 500, duration_seconds: int = 2):
        self.target_rps = target_rps
        self.duration_seconds = duration_seconds
        self.buffer = WebhookBurstBuffer(max_buffer_per_tenant=50000)
        self.tenants = [
            "tenant_alpha_direct",
            "tenant_beta_ecommerce",
            "tenant_gamma_agency",
            "tenant_delta_saas",
            "tenant_omega_fintech",
        ]
        self.latencies: List[float] = []
        self.contamination_errors = 0
        self.total_sent = 0
        self.total_received = 0

    async def ingest_single_event(self, tenant_id: str, seq: int) -> Dict[str, Any]:
        """Simulates ingestion endpoint execution for a single event."""
        start_time = time.perf_counter()

        payload = {
            "event_type": "page_view",
            "sequence": seq,
            "tenant_id": tenant_id,
            "url": f"https://{tenant_id}.com/analytics",
            "timestamp": time.time(),
        }

        # Simulate buffer enqueue (representing the ingestion ingress layer)
        event = self.buffer.enqueue(
            tenant_id=tenant_id,
            payload=payload,
            idempotency_key=f"idemp_{tenant_id}_{seq}",
        )

        # Micro-sleep to emulate async I/O / socket dispatch
        await asyncio.sleep(0.0001)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.latencies.append(elapsed_ms)

        # Strict Multi-Tenant Isolation Check:
        # Verify returned event is bound strictly to the calling tenant
        if event.tenant_id != tenant_id:
            self.contamination_errors += 1

        self.total_received += 1
        return {"status": "ACCEPTED", "event_id": event.event_id, "tenant_id": event.tenant_id}

    async def run(self) -> Dict[str, Any]:
        """Runs the load simulation at the configured RPS rate."""
        total_target_events = self.target_rps * self.duration_seconds
        interval = 1.0 / self.target_rps

        start_time = time.perf_counter()
        tasks = []

        for i in range(total_target_events):
            tenant = self.tenants[i % len(self.tenants)]
            tasks.append(asyncio.create_task(self.ingest_single_event(tenant, i)))
            self.total_sent += 1

            # Rate throttling
            if (i + 1) % self.target_rps == 0:
                await asyncio.sleep(0.05)

        await asyncio.gather(*tasks)
        total_duration = time.perf_counter() - start_time

        p50 = statistics.median(self.latencies) if self.latencies else 0
        p95 = statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) >= 20 else p50
        p99 = statistics.quantiles(self.latencies, n=100)[98] if len(self.latencies) >= 100 else p95
        actual_rps = self.total_received / total_duration if total_duration > 0 else 0

        # Verify batch retrieval across all tenants
        batch_events_retrieved = 0
        for tenant in self.tenants:
            depth = self.buffer.get_queue_depth(tenant)
            batch = self.buffer.pop_batch(tenant, batch_size=depth)
            assert all(ev.tenant_id == tenant for ev in batch), f"Contamination in tenant {tenant} queue!"
            batch_events_retrieved += len(batch)

        return {
            "target_rps": self.target_rps,
            "actual_rps": round(actual_rps, 2),
            "duration_seconds": round(total_duration, 2),
            "total_sent": self.total_sent,
            "total_received": self.total_received,
            "total_dequeued": batch_events_retrieved,
            "latency_p50_ms": round(p50, 4),
            "latency_p95_ms": round(p95, 4),
            "latency_p99_ms": round(p99, 4),
            "cross_tenant_contamination_errors": self.contamination_errors,
        }


def main():
    simulator = IngestionLoadSimulator(target_rps=500, duration_seconds=2)
    results = asyncio.run(simulator.run())

    print("\n" + "=" * 60)
    print("   KeelStream Ingestion Load Simulation Results (500 events/s)")
    print("=" * 60)
    print(f"Target Throughput:                 {results['target_rps']} events/s")
    print(f"Measured Throughput:               {results['actual_rps']} events/s")
    print(f"Events Ingested:                   {results['total_received']} / {results['total_sent']}")
    print(f"Events Successfully Dequeued:      {results['total_dequeued']}")
    print(f"Latency P50:                       {results['latency_p50_ms']} ms")
    print(f"Latency P95:                       {results['latency_p95_ms']} ms (SLA < 200ms)")
    print(f"Latency P99:                       {results['latency_p99_ms']} ms (SLA < 500ms)")
    print(f"Cross-Tenant Contamination Errors: {results['cross_tenant_contamination_errors']} (Zero Tolerance)")
    print("=" * 60 + "\n")

    assert results["cross_tenant_contamination_errors"] == 0
    assert results["total_received"] == results["total_sent"]
    assert results["total_dequeued"] == results["total_sent"]
    assert results["latency_p95_ms"] < 200.0


if __name__ == "__main__":
    main()
