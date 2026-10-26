"""
KeelStream Creative Performance & Revenue Join Service
======================================================
Line of Work 5: Task 5.1

Joins creative versions to ads, touchpoints, and payment events.
Computes mature metrics by enforcing conversion maturity delay rules and
minimum sample size thresholds to eliminate premature optimization signals.

Adheres strictly to core architectural principles:
1. Strict multi-tenant isolation.
2. Fail-closed financial data integrity (no speculative ROAS/CAC when spend is missing).
3. Deterministic maturity window calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class MaturityStatus(str, Enum):
    MATURE = "MATURE"
    IMMATURE = "IMMATURE"
    PARTIALLY_MATURE = "PARTIALLY_MATURE"
    NO_DATA = "NO_DATA"


class SampleSizeStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass
class CreativeVersion:
    """Represents a specific variant of a creative asset."""
    id: str
    tenant_id: str
    version_name: str
    creative_asset_id: Optional[str] = None
    headline: Optional[str] = None
    body_copy: Optional[str] = None
    asset_url: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("CreativeVersion must have a non-empty tenant_id.")
        if not self.id or not self.id.strip():
            raise ValueError("CreativeVersion must have a non-empty id.")
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=timezone.utc)


@dataclass
class Ad:
    """Represents an ad unit linked to a creative version."""
    id: str
    tenant_id: str
    creative_version_id: str
    name: str
    ad_group_id: Optional[str] = None
    campaign_id: Optional[str] = None
    external_ad_id: Optional[str] = None
    status: str = "ACTIVE"

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("Ad must have a non-empty tenant_id.")
        if not self.id or not self.id.strip():
            raise ValueError("Ad must have a non-empty id.")
        if not self.creative_version_id or not self.creative_version_id.strip():
            raise ValueError("Ad must reference a non-empty creative_version_id.")


@dataclass
class AdSpendMetric:
    """Recorded spend and impression metrics for an ad on a given date."""
    tenant_id: str
    ad_id: str
    date: str  # YYYY-MM-DD
    spend_amount: float
    currency: str = "USD"
    impressions: int = 0
    clicks: int = 0

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("AdSpendMetric must have a non-empty tenant_id.")
        if not self.ad_id or not self.ad_id.strip():
            raise ValueError("AdSpendMetric must reference a non-empty ad_id.")


@dataclass
class PaymentEvent:
    """Represents a financial transaction from a payment connector (e.g. Stripe)."""
    id: str
    tenant_id: str
    source_id: str
    amount: float  # gross payment amount
    currency: str = "USD"
    status: str = "SUCCEEDED"  # SUCCEEDED, REFUNDED, DISPUTED, FAILED
    refunded_amount: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    visitor_id: Optional[str] = None
    touchpoint_id: Optional[str] = None

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("PaymentEvent must have a non-empty tenant_id.")
        if not self.id or not self.id.strip():
            raise ValueError("PaymentEvent must have a non-empty id.")
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    @property
    def net_amount(self) -> float:
        if self.status != "SUCCEEDED":
            return 0.0
        return max(0.0, self.amount - self.refunded_amount)


@dataclass
class CreativePerformanceMetric:
    """Aggregated mature performance and revenue metrics for a creative version."""
    tenant_id: str
    creative_version_id: str
    version_name: str
    ad_ids: List[str]
    impressions: int
    clicks: int
    spend: Optional[float]
    currency: str
    touchpoint_count: int
    total_conversions: int
    mature_conversions: int
    immature_conversions: int
    gross_revenue: float
    net_revenue: float
    mature_net_revenue: float
    immature_net_revenue: float
    cvr: Optional[float]
    roas: Optional[float]
    mature_roas: Optional[float]
    cac: Optional[float]
    maturity_status: MaturityStatus
    sample_size_status: SampleSizeStatus
    is_statistically_actionable: bool
    data_gaps: List[str]
    actionable_recommendation_allowed: bool
    explanation: str


class CreativeJoinService:
    """
    Service to join creative versions to ads, touchpoints, and payment events,
    incorporating maturity delay and sample size gates.
    """

    def __init__(
        self,
        maturity_delay_days: int = 14,
        min_clicks: int = 100,
        min_conversions: int = 10,
    ):
        if maturity_delay_days < 0:
            raise ValueError("maturity_delay_days cannot be negative.")
        if min_clicks < 0 or min_conversions < 0:
            raise ValueError("Sample size thresholds cannot be negative.")

        self.maturity_delay_days = maturity_delay_days
        self.min_clicks = min_clicks
        self.min_conversions = min_conversions

    def join_and_evaluate(
        self,
        tenant_id: str,
        creative_versions: List[CreativeVersion],
        ads: List[Ad],
        touchpoints: List[Any],  # Touchpoint objects from core.attribution.identity or similar
        payment_events: List[PaymentEvent],
        spend_metrics: Optional[List[AdSpendMetric]] = None,
        as_of_date: Optional[datetime] = None,
    ) -> Dict[str, CreativePerformanceMetric]:
        """
        Executes tenant-isolated join and evaluation.
        Returns a dictionary mapping creative_version_id -> CreativePerformanceMetric.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must be provided and non-empty.")

        eval_time = as_of_date or datetime.now(timezone.utc)
        if eval_time.tzinfo is None:
            eval_time = eval_time.replace(tzinfo=timezone.utc)

        # 1. Tenant boundary enforcement: filter all inputs strictly by tenant_id
        t_creatives = [c for c in creative_versions if c.tenant_id == tenant_id]
        t_ads = [a for a in ads if a.tenant_id == tenant_id]
        t_touchpoints = [tp for tp in touchpoints if tp.tenant_id == tenant_id]
        t_payments = [p for p in payment_events if p.tenant_id == tenant_id]
        t_spends = [s for s in (spend_metrics or []) if s.tenant_id == tenant_id]

        # 2. Build indexes for efficient deterministic joining
        # creative_version_id -> list of ads
        creatives_to_ads: Dict[str, List[Ad]] = {c.id: [] for c in t_creatives}
        ad_to_creative: Dict[str, str] = {}
        for a in t_ads:
            if a.creative_version_id in creatives_to_ads:
                creatives_to_ads[a.creative_version_id].append(a)
                ad_to_creative[a.id] = a.creative_version_id

        # ad_id -> list of spend metrics
        ad_spends: Dict[str, List[AdSpendMetric]] = {}
        for s in t_spends:
            ad_spends.setdefault(s.ad_id, []).append(s)

        # ad_id -> list of touchpoints
        ad_touchpoints: Dict[str, List[Any]] = {}
        touchpoint_map: Dict[str, Any] = {}
        for tp in t_touchpoints:
            touchpoint_map[tp.id] = tp
            if getattr(tp, "ad_id", None) and tp.ad_id in ad_to_creative:
                ad_touchpoints.setdefault(tp.ad_id, []).append(tp)

        # Map payments to touchpoints / ads
        # A payment can be linked directly by touchpoint_id or visitor_id
        payment_to_tp: Dict[str, Any] = {}
        visitor_to_tps: Dict[str, List[Any]] = {}
        for tp in t_touchpoints:
            visitor_to_tps.setdefault(tp.visitor_id, []).append(tp)

        # Group payments by ad_id
        ad_payments: Dict[str, List[PaymentEvent]] = {}
        for p in t_payments:
            linked_tp = None
            if p.touchpoint_id and p.touchpoint_id in touchpoint_map:
                linked_tp = touchpoint_map[p.touchpoint_id]
            elif p.visitor_id and p.visitor_id in visitor_to_tps:
                # Find touchpoint prior to or at payment timestamp
                matching_tps = [
                    tp for tp in visitor_to_tps[p.visitor_id]
                    if tp.timestamp <= p.timestamp and getattr(tp, "ad_id", None) in ad_to_creative
                ]
                if matching_tps:
                    # Deterministic attribution: closest prior touchpoint
                    matching_tps.sort(key=lambda x: x.timestamp, reverse=True)
                    linked_tp = matching_tps[0]

            if linked_tp and getattr(linked_tp, "ad_id", None):
                ad_payments.setdefault(linked_tp.ad_id, []).append(p)

        # 3. Aggregate metrics per creative version
        results: Dict[str, CreativePerformanceMetric] = {}

        for creative in t_creatives:
            linked_ads = creatives_to_ads.get(creative.id, [])
            linked_ad_ids = [a.id for a in linked_ads]

            # Aggregate impressions, clicks, spend
            total_impressions = 0
            total_clicks = 0
            total_spend: Optional[float] = 0.0 if spend_metrics is not None else None
            currency = "USD"
            data_gaps: List[str] = []

            if spend_metrics is None:
                total_spend = None
                data_gaps.append("SPEND_DATA_MISSING")
            else:
                has_ad_spend_record = False
                for aid in linked_ad_ids:
                    for sm in ad_spends.get(aid, []):
                        has_ad_spend_record = True
                        total_spend += sm.spend_amount
                        total_impressions += sm.impressions
                        total_clicks += sm.clicks
                        currency = sm.currency

                if linked_ad_ids and not has_ad_spend_record:
                    total_spend = None
                    data_gaps.append("SPEND_DATA_MISSING")

            # Gather touchpoints and evaluate maturity
            creative_tps: List[Any] = []
            for aid in linked_ad_ids:
                creative_tps.extend(ad_touchpoints.get(aid, []))

            # Gather payments
            creative_payments: List[PaymentEvent] = []
            for aid in linked_ad_ids:
                creative_payments.extend(ad_payments.get(aid, []))

            gross_revenue = 0.0
            net_revenue = 0.0
            mature_net_revenue = 0.0
            immature_net_revenue = 0.0

            mature_conversions = 0
            immature_conversions = 0

            # Evaluate each payment conversion against conversion maturity delay
            for p in creative_payments:
                if p.status == "SUCCEEDED":
                    gross_revenue += p.amount
                    p_net = p.net_amount
                    net_revenue += p_net

                    # Check delay relative to eval_time
                    days_elapsed = (eval_time - p.timestamp).total_seconds() / 86400.0
                    if days_elapsed >= self.maturity_delay_days:
                        mature_conversions += 1
                        mature_net_revenue += p_net
                    else:
                        immature_conversions += 1
                        immature_net_revenue += p_net

            total_conversions = mature_conversions + immature_conversions

            # Maturity Status Determination
            if not creative_tps and not creative_payments:
                maturity_status = MaturityStatus.NO_DATA
            elif immature_conversions > 0 and mature_conversions == 0:
                maturity_status = MaturityStatus.IMMATURE
            elif immature_conversions > 0 and mature_conversions > 0:
                maturity_status = MaturityStatus.PARTIALLY_MATURE
            else:
                # If there are touchpoints within the maturity window, check if overall cohort is mature
                newest_tp_age = None
                if creative_tps:
                    newest_tp = max(creative_tps, key=lambda x: x.timestamp)
                    newest_tp_age = (eval_time - newest_tp.timestamp).total_seconds() / 86400.0

                if newest_tp_age is not None and newest_tp_age < self.maturity_delay_days and total_conversions == 0:
                    maturity_status = MaturityStatus.IMMATURE
                else:
                    maturity_status = MaturityStatus.MATURE

            # Sample Size Status Determination
            if total_clicks >= self.min_clicks or total_conversions >= self.min_conversions:
                sample_size_status = SampleSizeStatus.SUFFICIENT
            else:
                sample_size_status = SampleSizeStatus.INSUFFICIENT

            # Conversion Rate (CVR)
            cvr = (total_conversions / total_clicks) if total_clicks > 0 else None

            # ROAS & CAC (Fail-closed: None if spend is missing or zero)
            roas: Optional[float] = None
            mature_roas: Optional[float] = None
            cac: Optional[float] = None

            if total_spend is not None and total_spend > 0:
                roas = round(net_revenue / total_spend, 4)
                mature_roas = round(mature_net_revenue / total_spend, 4)
                if total_conversions > 0:
                    cac = round(total_spend / total_conversions, 2)

            # Actionability & Explanations
            is_statistically_actionable = (
                sample_size_status == SampleSizeStatus.SUFFICIENT
                and maturity_status == MaturityStatus.MATURE
                and "SPEND_DATA_MISSING" not in data_gaps
            )

            explanation_parts = []
            if maturity_status == MaturityStatus.IMMATURE:
                explanation_parts.append(
                    f"Conversion cohort is immature (< {self.maturity_delay_days} days maturity delay window). "
                    "Premature optimization signals suppressed."
                )
            elif maturity_status == MaturityStatus.PARTIALLY_MATURE:
                explanation_parts.append(
                    f"Cohort is partially mature ({immature_conversions} recent conversions still within maturity window)."
                )

            if sample_size_status == SampleSizeStatus.INSUFFICIENT:
                explanation_parts.append(
                    f"Insufficient sample size (clicks={total_clicks} < {self.min_clicks}, "
                    f"conversions={total_conversions} < {self.min_conversions})."
                )

            if "SPEND_DATA_MISSING" in data_gaps:
                explanation_parts.append("Spend data missing or incomplete; ROAS/CAC suppressed.")

            if not explanation_parts:
                explanation = "Statistical threshold and conversion maturity met. Metrics ready for actuation."
            else:
                explanation = " ".join(explanation_parts)

            metric = CreativePerformanceMetric(
                tenant_id=tenant_id,
                creative_version_id=creative.id,
                version_name=creative.version_name,
                ad_ids=linked_ad_ids,
                impressions=total_impressions,
                clicks=total_clicks,
                spend=total_spend,
                currency=currency,
                touchpoint_count=len(creative_tps),
                total_conversions=total_conversions,
                mature_conversions=mature_conversions,
                immature_conversions=immature_conversions,
                gross_revenue=gross_revenue,
                net_revenue=net_revenue,
                mature_net_revenue=mature_net_revenue,
                immature_net_revenue=immature_net_revenue,
                cvr=cvr,
                roas=roas,
                mature_roas=mature_roas,
                cac=cac,
                maturity_status=maturity_status,
                sample_size_status=sample_size_status,
                is_statistically_actionable=is_statistically_actionable,
                data_gaps=data_gaps,
                actionable_recommendation_allowed=is_statistically_actionable,
                explanation=explanation,
            )

            results[creative.id] = metric

        return results
