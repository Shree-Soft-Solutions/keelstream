"""
Unit & Integration Tests for Creative Performance & Revenue Join Service
(Line of Work 5: Task 5.1)
"""

from datetime import datetime, timedelta, timezone
import pytest

from core.attribution.identity import Touchpoint
from core.analytics.creative_join import (
    CreativeVersion,
    Ad,
    AdSpendMetric,
    PaymentEvent,
    MaturityStatus,
    SampleSizeStatus,
    CreativeJoinService,
)


@pytest.fixture
def base_eval_time():
    return datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def test_creative_join_end_to_end_mature_cohort(base_eval_time):
    """Verify full join and mature metrics calculation when cohort meets maturity and sample size."""
    tenant = "tenant-saas"
    service = CreativeJoinService(maturity_delay_days=14, min_clicks=100, min_conversions=10)

    # 1. Creative Version
    creative = CreativeVersion(
        id="cv-101",
        tenant_id=tenant,
        version_name="Hero Variant A - Direct ROI",
        headline="Cut Attribution Guesswork",
    )

    # 2. Ads
    ad1 = Ad(id="ad-1", tenant_id=tenant, creative_version_id="cv-101", name="Google Search - Brand")
    ad2 = Ad(id="ad-2", tenant_id=tenant, creative_version_id="cv-101", name="Meta - Retargeting")

    # 3. Spend Metrics (meets 100 clicks threshold)
    spends = [
        AdSpendMetric(tenant_id=tenant, ad_id="ad-1", date="2026-09-20", spend_amount=500.0, impressions=10000, clicks=80),
        AdSpendMetric(tenant_id=tenant, ad_id="ad-2", date="2026-09-21", spend_amount=400.0, impressions=6000, clicks=50),
    ]

    # 4. Touchpoints (occurred 25 days ago -> mature)
    t_25d_ago = base_eval_time - timedelta(days=25)
    tp1 = Touchpoint(id="tp-1", tenant_id=tenant, visitor_id="visitor-alpha", ad_id="ad-1", timestamp=t_25d_ago)
    tp2 = Touchpoint(id="tp-2", tenant_id=tenant, visitor_id="visitor-beta", ad_id="ad-2", timestamp=t_25d_ago)

    # 5. Mature Payment Events (occurred 20 days ago)
    p_20d_ago = base_eval_time - timedelta(days=20)
    payments = [
        PaymentEvent(
            id="pay-1",
            tenant_id=tenant,
            source_id="ch_1",
            amount=2000.0,
            status="SUCCEEDED",
            refunded_amount=200.0,
            timestamp=p_20d_ago,
            visitor_id="visitor-alpha",
        ),
        PaymentEvent(
            id="pay-2",
            tenant_id=tenant,
            source_id="ch_2",
            amount=1500.0,
            status="SUCCEEDED",
            refunded_amount=0.0,
            timestamp=p_20d_ago,
            visitor_id="visitor-beta",
        ),
    ]

    results = service.join_and_evaluate(
        tenant_id=tenant,
        creative_versions=[creative],
        ads=[ad1, ad2],
        touchpoints=[tp1, tp2],
        payment_events=payments,
        spend_metrics=spends,
        as_of_date=base_eval_time,
    )

    metric = results["cv-101"]
    assert metric.creative_version_id == "cv-101"
    assert set(metric.ad_ids) == {"ad-1", "ad-2"}
    assert metric.clicks == 130  # 80 + 50
    assert metric.impressions == 16000
    assert metric.spend == 900.0
    assert metric.gross_revenue == 3500.0
    assert metric.net_revenue == 3300.0  # 3500 - 200 refund
    assert metric.mature_net_revenue == 3300.0
    assert metric.immature_net_revenue == 0.0
    assert metric.total_conversions == 2
    assert metric.mature_conversions == 2
    assert metric.maturity_status == MaturityStatus.MATURE
    assert metric.sample_size_status == SampleSizeStatus.SUFFICIENT
    assert metric.is_statistically_actionable is True
    assert metric.actionable_recommendation_allowed is True
    # ROAS = 3300 / 900 = 3.6667
    assert metric.roas == 3.6667
    assert metric.mature_roas == 3.6667
    # CAC = 900 / 2 = 450.0
    assert metric.cac == 450.0


def test_conversion_maturity_delay_blocks_premature_optimization(base_eval_time):
    """Verify conversions within the maturity delay window (e.g. 5 days ago) are marked IMMATURE."""
    tenant = "tenant-ecom"
    service = CreativeJoinService(maturity_delay_days=14, min_clicks=100, min_conversions=10)

    creative = CreativeVersion(id="cv-recent", tenant_id=tenant, version_name="Flash Promo Variant")
    ad = Ad(id="ad-recent", tenant_id=tenant, creative_version_id="cv-recent", name="TikTok Ad")

    # Meets click threshold
    spends = [
        AdSpendMetric(tenant_id=tenant, ad_id="ad-recent", date="2026-10-18", spend_amount=300.0, clicks=150)
    ]

    # Touchpoint and conversion occurred 5 days ago (< 14 days maturity delay)
    t_5d_ago = base_eval_time - timedelta(days=5)
    tp = Touchpoint(id="tp-rec", tenant_id=tenant, visitor_id="vis-recent", ad_id="ad-recent", timestamp=t_5d_ago)
    payment = PaymentEvent(
        id="pay-rec",
        tenant_id=tenant,
        source_id="ch_rec",
        amount=500.0,
        status="SUCCEEDED",
        timestamp=t_5d_ago,
        visitor_id="vis-recent",
    )

    results = service.join_and_evaluate(
        tenant_id=tenant,
        creative_versions=[creative],
        ads=[ad],
        touchpoints=[tp],
        payment_events=[payment],
        spend_metrics=spends,
        as_of_date=base_eval_time,
    )

    metric = results["cv-recent"]
    assert metric.maturity_status == MaturityStatus.IMMATURE
    assert metric.immature_conversions == 1
    assert metric.mature_conversions == 0
    assert metric.immature_net_revenue == 500.0
    assert metric.mature_net_revenue == 0.0
    # Premature optimization must be blocked
    assert metric.is_statistically_actionable is False
    assert metric.actionable_recommendation_allowed is False
    assert "Conversion cohort is immature" in metric.explanation


def test_insufficient_sample_size_flagging(base_eval_time):
    """Verify sample size below threshold is marked INSUFFICIENT and suppresses actuation."""
    tenant = "tenant-b2b"
    service = CreativeJoinService(maturity_delay_days=14, min_clicks=100, min_conversions=10)

    creative = CreativeVersion(id="cv-low-vol", tenant_id=tenant, version_name="Niche Variant")
    ad = Ad(id="ad-niche", tenant_id=tenant, creative_version_id="cv-low-vol", name="LinkedIn Niche")

    # Only 25 clicks and 1 conversion
    spends = [
        AdSpendMetric(tenant_id=tenant, ad_id="ad-niche", date="2026-09-01", spend_amount=100.0, clicks=25)
    ]

    t_40d_ago = base_eval_time - timedelta(days=40)
    tp = Touchpoint(id="tp-old", tenant_id=tenant, visitor_id="vis-1", ad_id="ad-niche", timestamp=t_40d_ago)
    payment = PaymentEvent(
        id="pay-old",
        tenant_id=tenant,
        source_id="ch_old",
        amount=250.0,
        status="SUCCEEDED",
        timestamp=t_40d_ago,
        visitor_id="vis-1",
    )

    results = service.join_and_evaluate(
        tenant_id=tenant,
        creative_versions=[creative],
        ads=[ad],
        touchpoints=[tp],
        payment_events=[payment],
        spend_metrics=spends,
        as_of_date=base_eval_time,
    )

    metric = results["cv-low-vol"]
    # Although mature (40 days old), sample size is insufficient
    assert metric.maturity_status == MaturityStatus.MATURE
    assert metric.sample_size_status == SampleSizeStatus.INSUFFICIENT
    assert metric.is_statistically_actionable is False
    assert metric.actionable_recommendation_allowed is False
    assert "Insufficient sample size" in metric.explanation


def test_fail_closed_financial_data_integrity_missing_spend(base_eval_time):
    """Verify that when spend data is missing, ROAS and CAC are NOT calculated (no fake ROAS/CAC)."""
    tenant = "tenant-audit"
    service = CreativeJoinService(maturity_delay_days=14, min_clicks=100, min_conversions=10)

    creative = CreativeVersion(id="cv-no-spend", tenant_id=tenant, version_name="Missing Spend Test")
    ad = Ad(id="ad-audit", tenant_id=tenant, creative_version_id="cv-no-spend", name="Test Ad")

    t_30d_ago = base_eval_time - timedelta(days=30)
    tp = Touchpoint(id="tp-aud", tenant_id=tenant, visitor_id="vis-aud", ad_id="ad-audit", timestamp=t_30d_ago)
    payment = PaymentEvent(
        id="pay-aud",
        tenant_id=tenant,
        source_id="ch_aud",
        amount=1000.0,
        status="SUCCEEDED",
        timestamp=t_30d_ago,
        visitor_id="vis-aud",
    )

    # Spend metrics is None (or empty for this ad)
    results = service.join_and_evaluate(
        tenant_id=tenant,
        creative_versions=[creative],
        ads=[ad],
        touchpoints=[tp],
        payment_events=[payment],
        spend_metrics=None,
        as_of_date=base_eval_time,
    )

    metric = results["cv-no-spend"]
    assert metric.spend is None
    assert metric.roas is None
    assert metric.cac is None
    assert "SPEND_DATA_MISSING" in metric.data_gaps
    assert metric.is_statistically_actionable is False


def test_strict_multi_tenant_isolation_in_creative_join(base_eval_time):
    """Verify Tenant A never aggregates or joins Tenant B ads, touchpoints, or revenue."""
    service = CreativeJoinService()
    tenant_a = "tenant-alpha"
    tenant_b = "tenant-beta"

    creative_a = CreativeVersion(id="cv-a", tenant_id=tenant_a, version_name="Tenant A Creative")
    creative_b = CreativeVersion(id="cv-b", tenant_id=tenant_b, version_name="Tenant B Creative")

    ad_a = Ad(id="ad-a", tenant_id=tenant_a, creative_version_id="cv-a", name="Ad A")
    ad_b = Ad(id="ad-b", tenant_id=tenant_b, creative_version_id="cv-b", name="Ad B")

    t_20d = base_eval_time - timedelta(days=20)
    tp_a = Touchpoint(id="tp-a", tenant_id=tenant_a, visitor_id="v-a", ad_id="ad-a", timestamp=t_20d)
    tp_b = Touchpoint(id="tp-b", tenant_id=tenant_b, visitor_id="v-b", ad_id="ad-b", timestamp=t_20d)

    pay_a = PaymentEvent(id="p-a", tenant_id=tenant_a, source_id="ch-a", amount=100.0, status="SUCCEEDED", timestamp=t_20d, visitor_id="v-a")
    pay_b = PaymentEvent(id="p-b", tenant_id=tenant_b, source_id="ch-b", amount=9999.0, status="SUCCEEDED", timestamp=t_20d, visitor_id="v-b")

    # Evaluate strictly as Tenant A
    results_a = service.join_and_evaluate(
        tenant_id=tenant_a,
        creative_versions=[creative_a, creative_b],
        ads=[ad_a, ad_b],
        touchpoints=[tp_a, tp_b],
        payment_events=[pay_a, pay_b],
        spend_metrics=[],
        as_of_date=base_eval_time,
    )

    # Only Tenant A's creative is returned
    assert "cv-a" in results_a
    assert "cv-b" not in results_a
    assert results_a["cv-a"].gross_revenue == 100.0
    # Tenant B's $9999 is completely excluded
    assert results_a["cv-a"].net_revenue == 100.0
