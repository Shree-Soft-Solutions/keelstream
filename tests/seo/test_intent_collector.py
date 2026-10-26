"""
Unit tests for Search Intent & Evidence Ingestion Engine.
Task 6.1 (Line of Work 6: SEO / AEO Content Intelligence Workflow).
"""

import pytest
from core.seo.intent_collector import (
    ContentGapType,
    KeywordOpportunity,
    SearchIntent,
    SearchIntentCollector,
    SearchQueryRecord,
)


class TestSearchQueryRecord:
    def test_valid_record_creation(self) -> None:
        rec = SearchQueryRecord(
            query="  Revenue Attribution Tool  ",
            impressions=1000,
            clicks=50,
            ctr=0.05,
            position=4.2,
            url="https://keelstream.io/features/attribution",
            tenant_id="tenant_alpha",
        )
        assert rec.query == "revenue attribution tool"
        assert rec.impressions == 1000
        assert rec.clicks == 50
        assert rec.ctr == 0.05
        assert rec.position == 4.2
        assert rec.tenant_id == "tenant_alpha"

    def test_auto_compute_ctr_when_zero(self) -> None:
        rec = SearchQueryRecord(
            query="ad spend tracking",
            impressions=200,
            clicks=10,
            ctr=0.0,
            position=5.0,
        )
        assert rec.ctr == 0.05

    def test_negative_impressions_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Impressions cannot be negative"):
            SearchQueryRecord(
                query="test negative imp",
                impressions=-10,
                clicks=0,
                ctr=0.0,
                position=1.0,
            )

    def test_negative_clicks_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Clicks cannot be negative"):
            SearchQueryRecord(
                query="test negative clicks",
                impressions=100,
                clicks=-5,
                ctr=0.0,
                position=1.0,
            )

    def test_clicks_exceeding_impressions_normalized(self) -> None:
        rec = SearchQueryRecord(
            query="high clicks anomaly",
            impressions=10,
            clicks=15,
            ctr=0.0,
            position=1.0,
        )
        assert rec.clicks == 10
        assert rec.ctr == 1.0


class TestIntentClassification:
    @pytest.fixture
    def collector(self) -> SearchIntentCollector:
        return SearchIntentCollector(
            tenant_id="tenant_agency_01",
            brand_terms=["keelstream"],
            custom_intent_rules={
                SearchIntent.COMMERCIAL: [r"\broas audit\b"],
            },
        )

    def test_transactional_intent_queries(self, collector: SearchIntentCollector) -> None:
        queries = [
            "buy multi touch attribution software",
            "keelstream pricing plan",
            "order revops marketing suite",
            "schedule demo for revenue attribution",
            "get quote ad tracking platform",
            "free trial agency attribution tool",
        ]
        for q in queries:
            result = collector.classify_intent(q)
            assert result.intent == SearchIntent.TRANSACTIONAL, f"Expected TRANSACTIONAL for '{q}', got {result.intent}"
            assert result.confidence >= 0.70

    def test_commercial_intent_queries(self, collector: SearchIntentCollector) -> None:
        queries = [
            "best attribution software for digital agencies",
            "keelstream vs rockerbox comparison",
            "top marketing attribution tools 2026",
            "revenue reconciliation platform reviews",
            "attribution tool features and alternatives",
            "free roas audit checklist agency",  # Matches custom rule
        ]
        for q in queries:
            result = collector.classify_intent(q)
            assert result.intent == SearchIntent.COMMERCIAL, f"Expected COMMERCIAL for '{q}', got {result.intent}"
            assert result.confidence >= 0.65

    def test_informational_intent_queries(self, collector: SearchIntentCollector) -> None:
        queries = [
            "how to calculate customer acquisition cost",
            "what is first touch attribution model",
            "why marketing attribution is broken in 2026",
            "guide to multi-touch revenue attribution",
            "marketing attribution step by step tutorial",
            "difference between first touch and last touch",
        ]
        for q in queries:
            result = collector.classify_intent(q)
            assert result.intent == SearchIntent.INFORMATIONAL, f"Expected INFORMATIONAL for '{q}', got {result.intent}"
            assert result.confidence >= 0.65

    def test_navigational_intent_queries(self, collector: SearchIntentCollector) -> None:
        queries = [
            "keelstream login",
            "keelstream portal",
            "keelstream app dashboard",
            "keelstream support contact",
        ]
        for q in queries:
            result = collector.classify_intent(q)
            assert result.intent == SearchIntent.NAVIGATIONAL, f"Expected NAVIGATIONAL for '{q}', got {result.intent}"
            assert result.confidence >= 0.90

    def test_fallback_heuristics(self, collector: SearchIntentCollector) -> None:
        # Long tail without explicit keywords defaults to informational
        long_query = "exploring the modern pipeline attribution landscape"
        res_long = collector.classify_intent(long_query)
        assert res_long.intent == SearchIntent.INFORMATIONAL

        # Short tail defaults to commercial
        short_query = "attribution software"
        res_short = collector.classify_intent(short_query)
        assert res_short.intent == SearchIntent.COMMERCIAL


class TestMultiTenantIngestionAndClustering:
    def test_tenant_isolation_filter(self) -> None:
        collector = SearchIntentCollector(tenant_id="tenant_123")
        records = [
            {"query": "agency attribution", "impressions": 100, "clicks": 5, "position": 2.0, "tenant_id": "tenant_123"},
            {"query": "competitor analysis", "impressions": 500, "clicks": 20, "position": 1.0, "tenant_id": "tenant_999"},  # Other tenant
            {"query": "buy attribution", "impressions": 300, "clicks": 15, "position": 3.0, "tenant_id": "tenant_123"},
        ]
        ingested = collector.ingest_records(records, enforce_tenant=True)
        assert len(ingested) == 2
        assert all(r.tenant_id == "tenant_123" for r in ingested)

    def test_clustering_by_intent(self) -> None:
        collector = SearchIntentCollector(tenant_id="tenant_123")
        records = [
            SearchQueryRecord(query="buy ad attribution", impressions=100, clicks=10, ctr=0.1, position=2.0),
            SearchQueryRecord(query="how to track roas", impressions=200, clicks=5, ctr=0.025, position=8.0),
            SearchQueryRecord(query="best roas tracker", impressions=150, clicks=12, ctr=0.08, position=4.0),
            SearchQueryRecord(query="keelstream login", impressions=50, clicks=25, ctr=0.5, position=1.0),
        ]
        clusters = collector.cluster_by_intent(records)
        assert len(clusters[SearchIntent.TRANSACTIONAL]) == 1
        assert len(clusters[SearchIntent.INFORMATIONAL]) == 1
        assert len(clusters[SearchIntent.COMMERCIAL]) == 1
        assert len(clusters[SearchIntent.NAVIGATIONAL]) == 1


class TestContentGapDetection:
    @pytest.fixture
    def collector(self) -> SearchIntentCollector:
        return SearchIntentCollector(tenant_id="tenant_test")

    def test_missing_content_gap(self, collector: SearchIntentCollector) -> None:
        rec = SearchQueryRecord(
            query="multi touch attribution whitepaper",
            impressions=1200,
            clicks=0,
            ctr=0.0,
            position=65.0,
            url=None,
        )
        gap = collector.detect_content_gap(rec)
        assert gap.gap_type == ContentGapType.MISSING_CONTENT
        assert gap.severity == "HIGH"
        assert "No dedicated URL" in gap.reason

    def test_striking_distance_gap(self, collector: SearchIntentCollector) -> None:
        rec = SearchQueryRecord(
            query="b2b revops attribution",
            impressions=1500,
            clicks=20,
            ctr=0.013,
            position=14.2,  # Page 2
            url="https://keelstream.io/blog/b2b-revops",
        )
        gap = collector.detect_content_gap(rec)
        assert gap.gap_type == ContentGapType.STRIKING_DISTANCE
        assert gap.severity == "HIGH"
        assert "Page 2" in gap.reason

    def test_low_ctr_high_impressions_gap(self, collector: SearchIntentCollector) -> None:
        rec = SearchQueryRecord(
            query="best revenue attribution tool",
            impressions=3000,
            clicks=15,
            ctr=0.005,  # 0.5% CTR is much lower than ~17% benchmark for pos 2
            position=2.0,
            url="https://keelstream.io/tools/attribution",
        )
        gap = collector.detect_content_gap(rec)
        assert gap.gap_type == ContentGapType.LOW_CTR_HIGH_IMPRESSIONS
        assert gap.severity == "HIGH"
        assert "benchmark" in gap.reason.lower()

    def test_optimized_content_status(self, collector: SearchIntentCollector) -> None:
        rec = SearchQueryRecord(
            query="keelstream attribution features",
            impressions=500,
            clicks=80,
            ctr=0.16,  # Healthy CTR for position 2
            position=2.1,
            url="https://keelstream.io/features",
        )
        gap = collector.detect_content_gap(rec)
        assert gap.gap_type == ContentGapType.OPTIMIZED
        assert gap.severity == "NONE"


class TestOpportunityAndExecutiveSummary:
    @pytest.fixture
    def collector(self) -> SearchIntentCollector:
        return SearchIntentCollector(tenant_id="tenant_summary")

    def test_opportunity_calculation(self, collector: SearchIntentCollector) -> None:
        rec = SearchQueryRecord(
            query="buy enterprise roas attribution",
            impressions=2000,
            clicks=10,
            ctr=0.005,
            position=13.5,  # Striking distance
            url="https://keelstream.io/enterprise",
            tenant_id="tenant_summary",
        )
        opp = collector.calculate_opportunity(
            record=rec,
            target_position=3.0,
            average_deal_value=1200.0,
        )

        assert isinstance(opp, KeywordOpportunity)
        assert opp.intent == SearchIntent.TRANSACTIONAL
        assert opp.content_gap == ContentGapType.STRIKING_DISTANCE
        assert opp.incremental_clicks > 0
        assert opp.projected_conversions > 0
        assert opp.estimated_revenue_opportunity > 0
        assert 0.0 <= opp.opportunity_score <= 100.0
        assert opp.opportunity_score >= 60.0  # High score due to high intent and striking distance
        assert len(opp.recommendations) >= 2

    def test_analyze_corpus_and_summary(self, collector: SearchIntentCollector) -> None:
        records = [
            {
                "query": "buy marketing attribution tool",
                "impressions": 5000,
                "clicks": 50,
                "ctr": 0.01,
                "position": 12.0,
                "url": "https://keelstream.io/pricing",
                "tenant_id": "tenant_summary",
            },
            {
                "query": "how to build marketing attribution model",
                "impressions": 3000,
                "clicks": 60,
                "ctr": 0.02,
                "position": 7.5,
                "url": "https://keelstream.io/blog/guide",
                "tenant_id": "tenant_summary",
            },
            {
                "query": "keelstream dashboard login",
                "impressions": 800,
                "clicks": 400,
                "ctr": 0.50,
                "position": 1.0,
                "url": "https://keelstream.io/login",
                "tenant_id": "tenant_summary",
            },
        ]

        opportunities = collector.analyze_corpus(
            records=records,
            average_deal_value=1500.0,
        )

        assert len(opportunities) == 3
        # Should be sorted by opportunity score descending
        assert opportunities[0].opportunity_score >= opportunities[1].opportunity_score
        assert opportunities[1].opportunity_score >= opportunities[2].opportunity_score

        summary = collector.generate_executive_summary(opportunities)
        assert summary["tenant_id"] == "tenant_summary"
        assert summary["total_queries_analyzed"] == 3
        assert summary["total_impressions"] == 8800
        assert summary["total_clicks"] == 510
        assert summary["total_estimated_revenue_opportunity"] > 0
        assert "transactional" in summary["intent_distribution"]
        assert "informational" in summary["intent_distribution"]
        assert "navigational" in summary["intent_distribution"]
