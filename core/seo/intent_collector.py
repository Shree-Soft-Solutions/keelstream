"""
KeelStream Search Intent & Evidence Ingestion Engine
Part of Line of Work 6: SEO / AEO Content Intelligence Workflow (Task 6.1)

Ingests search query data (impressions, clicks, CTR, position),
clusters queries into search intent categories (Informational, Commercial, Transactional, Navigational),
identifies content gaps, and computes revenue opportunity scores.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class SearchIntent(str, Enum):
    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"


class ContentGapType(str, Enum):
    MISSING_CONTENT = "missing_content"
    STRIKING_DISTANCE = "striking_distance"
    LOW_CTR_HIGH_IMPRESSIONS = "low_ctr_high_impressions"
    UNDERPERFORMING = "underperforming"
    OPTIMIZED = "optimized"


@dataclass
class SearchQueryRecord:
    query: str
    impressions: int
    clicks: int
    ctr: float
    position: float
    url: Optional[str] = None
    tenant_id: str = "default"
    source: str = "google_search_console"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.query = self.query.strip().lower()
        if self.impressions < 0:
            raise ValueError(f"Impressions cannot be negative: {self.impressions}")
        if self.clicks < 0:
            raise ValueError(f"Clicks cannot be negative: {self.clicks}")
        if self.clicks > self.impressions:
            # Normalize clicks exceeding impressions due to reporting lags
            self.clicks = self.impressions
        if self.impressions > 0 and (self.ctr is None or self.ctr == 0.0 and self.clicks > 0):
            self.ctr = round(self.clicks / self.impressions, 4)
        elif self.impressions == 0:
            self.ctr = 0.0
        if self.position < 1.0:
            self.position = 1.0


@dataclass
class IntentClassificationResult:
    intent: SearchIntent
    confidence: float
    matched_patterns: List[str] = field(default_factory=list)
    secondary_intent: Optional[SearchIntent] = None


@dataclass
class ContentGapAnalysis:
    gap_type: ContentGapType
    severity: str  # "HIGH", "MEDIUM", "LOW", "NONE"
    reason: str
    recommended_action: str


@dataclass
class KeywordOpportunity:
    query: str
    tenant_id: str
    intent: SearchIntent
    intent_confidence: float
    current_position: float
    impressions: int
    clicks: int
    current_ctr: float
    content_gap: ContentGapType
    content_gap_severity: str
    content_gap_reason: str
    target_position: float
    projected_ctr: float
    projected_clicks: float
    incremental_clicks: float
    conversion_rate: float
    projected_conversions: float
    average_deal_value: float
    estimated_revenue_opportunity: float
    opportunity_score: float
    recommendations: List[str] = field(default_factory=list)


# Industry CTR benchmarks by SERP position
BENCHMARK_CTR_BY_POSITION: Dict[int, float] = {
    1: 0.320,  # ~32.0%
    2: 0.170,  # ~17.0%
    3: 0.105,  # ~10.5%
    4: 0.070,  # ~7.0%
    5: 0.050,  # ~5.0%
    6: 0.038,  # ~3.8%
    7: 0.028,  # ~2.8%
    8: 0.021,  # ~2.1%
    9: 0.016,  # ~1.6%
    10: 0.012, # ~1.2%
}

# Default conversion rate estimates by search intent
DEFAULT_CONVERSION_RATES: Dict[SearchIntent, float] = {
    SearchIntent.TRANSACTIONAL: 0.045,  # 4.5%
    SearchIntent.COMMERCIAL: 0.022,     # 2.2%
    SearchIntent.INFORMATIONAL: 0.008,  # 0.8%
    SearchIntent.NAVIGATIONAL: 0.015,   # 1.5%
}

# Regex pattern dictionaries for deterministic intent classification
INTENT_PATTERNS = {
    SearchIntent.TRANSACTIONAL: [
        r"\b(?:buy|purchase|order|shop|booking|book|checkout|coupon|discount|deal|promo code)\b",
        r"\b(?:pricing|pricing plan|quote|get quote|hire|download|get started|demo|request demo|schedule demo)\b",
        r"\b(?:free trial|subscription|subscribe|signup|sign up|membership|service cost)\b",
    ],
    SearchIntent.COMMERCIAL: [
        r"\b(?:best|top|vs|versus|review|reviews|comparison|compare|alternatives?)\b",
        r"\b(?:features|specs|ratings?|pros and cons|is it worth|cheapest|affordable)\b",
        r"\b(?:software|platform|provider|agency|solution|vendor|tools?)\b",
    ],
    SearchIntent.INFORMATIONAL: [
        r"\b(?:how to|what is|what are|why|guide|tutorial|learn|tips|examples?|ideas?)\b",
        r"\b(?:overview|definition|explained|checklist|template|strategy|best practices|difference between)\b",
        r"\b(?:calculate|step by step|diy|meaning|methods?|framework|faq)\b",
    ],
    SearchIntent.NAVIGATIONAL: [
        r"\b(?:login|log in|signin|sign in|portal|dashboard|support|contact us|official site|help center|app)\b",
    ],
}


class SearchIntentCollector:
    """
    Search Intent & Evidence Ingestion Engine.
    Handles ingestion of organic search performance data, intent clustering,
    content gap discovery, and revenue opportunity calculation.
    """

    def __init__(
        self,
        tenant_id: str = "default",
        brand_terms: Optional[List[str]] = None,
        custom_intent_rules: Optional[Dict[SearchIntent, List[str]]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.brand_terms = [b.lower() for b in (brand_terms or ["keelstream"])]
        self.custom_intent_rules = custom_intent_rules or {}

    def ingest_records(
        self,
        raw_records: List[Dict[str, Any] | SearchQueryRecord],
        enforce_tenant: bool = True,
    ) -> List[SearchQueryRecord]:
        """
        Validates, normalizes, and ingests search query records.
        Enforces tenant isolation by filtering or tagging records with the tenant_id.
        """
        ingested: List[SearchQueryRecord] = []
        for raw in raw_records:
            if isinstance(raw, SearchQueryRecord):
                rec = raw
            else:
                rec = SearchQueryRecord(
                    query=str(raw.get("query", "")),
                    impressions=int(raw.get("impressions", 0)),
                    clicks=int(raw.get("clicks", 0)),
                    ctr=float(raw.get("ctr", 0.0)),
                    position=float(raw.get("position", 100.0)),
                    url=raw.get("url"),
                    tenant_id=raw.get("tenant_id", self.tenant_id),
                    source=raw.get("source", "google_search_console"),
                    metadata=raw.get("metadata", {}),
                )

            if enforce_tenant and rec.tenant_id != self.tenant_id:
                # Multi-tenant isolation: drop records belonging to other tenants
                continue

            ingested.append(rec)
        return ingested

    def classify_intent(self, query: str) -> IntentClassificationResult:
        """
        Deterministically classifies a search query into an intent category
        (Informational, Commercial, Transactional, Navigational) with confidence score.
        """
        q = query.strip().lower()
        matched_patterns: List[str] = []

        # 1. Check for explicit Navigational keywords first (login, portal, support, app)
        has_nav_term = False
        for pattern in INTENT_PATTERNS[SearchIntent.NAVIGATIONAL]:
            if re.search(pattern, q):
                has_nav_term = True
                matched_patterns.append(pattern)

        # 2. Score Transactional vs Commercial vs Informational
        scores: Dict[SearchIntent, int] = {
            SearchIntent.TRANSACTIONAL: 0,
            SearchIntent.COMMERCIAL: 0,
            SearchIntent.INFORMATIONAL: 0,
            SearchIntent.NAVIGATIONAL: 0,
        }

        if has_nav_term:
            scores[SearchIntent.NAVIGATIONAL] += 4

        # Check custom rules if provided
        for intent, patterns in self.custom_intent_rules.items():
            for pat in patterns:
                if re.search(pat, q):
                    scores[intent] = scores.get(intent, 0) + 4
                    matched_patterns.append(f"custom:{pat}")

        # Transactional pattern matching
        for pattern in INTENT_PATTERNS[SearchIntent.TRANSACTIONAL]:
            if re.search(pattern, q):
                scores[SearchIntent.TRANSACTIONAL] += 3
                matched_patterns.append(pattern)

        # Commercial pattern matching
        for pattern in INTENT_PATTERNS[SearchIntent.COMMERCIAL]:
            if re.search(pattern, q):
                scores[SearchIntent.COMMERCIAL] += 2
                matched_patterns.append(pattern)

        # Informational pattern matching
        for pattern in INTENT_PATTERNS[SearchIntent.INFORMATIONAL]:
            if re.search(pattern, q):
                scores[SearchIntent.INFORMATIONAL] += 2
                matched_patterns.append(pattern)

        # 3. Check for brand terms
        has_brand = False
        for brand in self.brand_terms:
            if re.search(rf"\b{re.escape(brand)}\b", q):
                has_brand = True
                matched_patterns.append(f"brand:{brand}")
                break

        # If brand term is present and no strong transactional or commercial intent was found
        # OR if navigational term (login/portal/support) is present, classify as NAVIGATIONAL
        if has_brand and scores[SearchIntent.TRANSACTIONAL] == 0 and scores[SearchIntent.COMMERCIAL] == 0 and scores[SearchIntent.INFORMATIONAL] == 0:
            return IntentClassificationResult(
                intent=SearchIntent.NAVIGATIONAL,
                confidence=0.95,
                matched_patterns=matched_patterns,
            )

        # Disambiguate scores
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_intent, top_score = sorted_scores[0]
        second_intent, second_score = sorted_scores[1]

        if top_score == 0:
            if has_brand:
                return IntentClassificationResult(
                    intent=SearchIntent.NAVIGATIONAL,
                    confidence=0.90,
                    matched_patterns=matched_patterns,
                )
            # Fallback heuristic: Long-tail queries (>3 words) default to informational,
            # short-tail generic queries default to commercial research
            word_count = len(q.split())
            if word_count >= 4:
                return IntentClassificationResult(
                    intent=SearchIntent.INFORMATIONAL,
                    confidence=0.55,
                    matched_patterns=["heuristic:long_tail"],
                )
            else:
                return IntentClassificationResult(
                    intent=SearchIntent.COMMERCIAL,
                    confidence=0.50,
                    matched_patterns=["heuristic:short_tail"],
                )

        # Calculate confidence based on score margin
        confidence = min(0.95, 0.65 + (top_score * 0.10))
        secondary = second_intent if second_score > 0 else None

        return IntentClassificationResult(
            intent=top_intent,
            confidence=round(confidence, 2),
            matched_patterns=matched_patterns,
            secondary_intent=secondary,
        )

    def cluster_by_intent(
        self, records: List[SearchQueryRecord]
    ) -> Dict[SearchIntent, List[SearchQueryRecord]]:
        """
        Clusters a collection of search query records into their respective search intents.
        """
        clusters: Dict[SearchIntent, List[SearchQueryRecord]] = {
            intent: [] for intent in SearchIntent
        }
        for rec in records:
            classification = self.classify_intent(rec.query)
            clusters[classification.intent].append(rec)
        return clusters

    def detect_content_gap(
        self,
        record: SearchQueryRecord,
        known_site_urls: Optional[Set[str]] = None,
    ) -> ContentGapAnalysis:
        """
        Analyzes a query performance record to identify content gaps.
        Identifies:
        - MISSING_CONTENT: No URL ranking or ranking > 50 with high impressions.
        - STRIKING_DISTANCE: Ranking on page 2 (positions 11.0 - 20.0) with high potential.
        - LOW_CTR_HIGH_IMPRESSIONS: Ranking in top 10 but CTR is below benchmark.
        - UNDERPERFORMING: Positions 21.0 - 50.0.
        - OPTIMIZED: High ranking with healthy CTR.
        """
        pos = record.position
        imp = record.impressions
        ctr = record.ctr

        # 1. Missing Content / Unranked
        if not record.url or (known_site_urls and record.url not in known_site_urls):
            if pos >= 50.0 or imp >= 500:
                return ContentGapAnalysis(
                    gap_type=ContentGapType.MISSING_CONTENT,
                    severity="HIGH" if imp > 1000 else "MEDIUM",
                    reason=f"No dedicated URL ranking for query with {imp} impressions.",
                    recommended_action="Draft new targeted pillar content or brief addressing this exact search query.",
                )

        # 2. Striking Distance (Positions 11.0 to 20.0)
        if 11.0 <= pos <= 20.0:
            severity = "HIGH" if imp >= 1000 else "MEDIUM"
            return ContentGapAnalysis(
                gap_type=ContentGapType.STRIKING_DISTANCE,
                severity=severity,
                reason=f"Ranked on Page 2 (Pos {pos:.1f}) with {imp} impressions. Minor authority or content update can push to Page 1.",
                recommended_action="Optimize existing page headers (H2/H3), add contextual internal links, and refresh search intent proof points.",
            )

        # 3. Top 10 with Low CTR
        if pos <= 10.0:
            benchmark = BENCHMARK_CTR_BY_POSITION.get(int(math.floor(pos)), 0.02)
            if ctr < (benchmark * 0.60) and imp >= 300:
                return ContentGapAnalysis(
                    gap_type=ContentGapType.LOW_CTR_HIGH_IMPRESSIONS,
                    severity="HIGH" if imp >= 2000 else "MEDIUM",
                    reason=f"Ranked at position {pos:.1f} but CTR is {ctr:.1%} (benchmark: {benchmark:.1%}).",
                    recommended_action="Rewrite Title Tag and Meta Description with compelling value proposition and schema markup.",
                )
            else:
                return ContentGapAnalysis(
                    gap_type=ContentGapType.OPTIMIZED,
                    severity="NONE",
                    reason=f"Solid position {pos:.1f} with CTR {ctr:.1%}.",
                    recommended_action="Maintain current ranking with monitoring and freshness updates.",
                )

        # 4. Underperforming (Positions 21 to 50)
        if 21.0 <= pos <= 50.0:
            return ContentGapAnalysis(
                gap_type=ContentGapType.UNDERPERFORMING,
                severity="LOW" if imp < 500 else "MEDIUM",
                reason=f"Position {pos:.1f} is beyond striking distance with {imp} impressions.",
                recommended_action="Assess search intent depth and consider merging with comprehensive topic cluster.",
            )

        # 5. Default missing / weak ranking
        return ContentGapAnalysis(
            gap_type=ContentGapType.MISSING_CONTENT,
            severity="MEDIUM",
            reason=f"Position {pos:.1f} lacks top-tier organic visibility.",
            recommended_action="Build targeted sourced brief to address primary query intent.",
        )

    def calculate_opportunity(
        self,
        record: SearchQueryRecord,
        target_position: float = 3.0,
        average_deal_value: float = 500.0,
        conversion_rate_override: Optional[float] = None,
    ) -> KeywordOpportunity:
        """
        Calculates the revenue opportunity score for a given search query record.
        Formula:
        Incremental Clicks = Impressions * max(0, Benchmark_CTR(target_position) - current_ctr)
        Projected Conversions = Incremental Clicks * Conversion_Rate
        Estimated Revenue Opportunity = Projected Conversions * Average Deal Value
        Opportunity Score = Composite score (0 - 100) combining volume, feasibility, and intent value.
        """
        classification = self.classify_intent(record.query)
        gap = self.detect_content_gap(record)

        # Benchmark CTR for target position
        target_pos_int = max(1, min(10, int(round(target_position))))
        benchmark_ctr = BENCHMARK_CTR_BY_POSITION.get(target_pos_int, 0.10)

        # Current vs target CTR
        current_ctr = record.ctr
        incremental_ctr = max(0.0, benchmark_ctr - current_ctr)
        projected_ctr = max(current_ctr, benchmark_ctr)

        projected_clicks = round(record.impressions * projected_ctr, 1)
        incremental_clicks = round(record.impressions * incremental_ctr, 1)

        # Conversion rate
        if conversion_rate_override is not None:
            conv_rate = conversion_rate_override
        else:
            conv_rate = DEFAULT_CONVERSION_RATES.get(
                classification.intent, 0.015
            )

        projected_conversions = round(incremental_clicks * conv_rate, 2)
        revenue_opportunity = round(projected_conversions * average_deal_value, 2)

        # Opportunity Score calculation (0 to 100)
        # 1. Volume component (up to 35 pts)
        vol_score = min(35.0, (math.log10(max(10, record.impressions)) / 4.0) * 35.0)

        # 2. Intent commercial weight (up to 35 pts)
        intent_multipliers = {
            SearchIntent.TRANSACTIONAL: 1.0,
            SearchIntent.COMMERCIAL: 0.8,
            SearchIntent.INFORMATIONAL: 0.45,
            SearchIntent.NAVIGATIONAL: 0.3,
        }
        intent_score = 35.0 * intent_multipliers.get(classification.intent, 0.5)

        # 3. Feasibility / Proximity component (up to 30 pts)
        # Striking distance (11-20) gets highest feasibility; top 10 with low CTR also gets high feasibility
        if gap.gap_type == ContentGapType.STRIKING_DISTANCE:
            feasibility_score = 30.0
        elif gap.gap_type == ContentGapType.LOW_CTR_HIGH_IMPRESSIONS:
            feasibility_score = 28.0
        elif gap.gap_type == ContentGapType.MISSING_CONTENT:
            feasibility_score = 20.0
        elif gap.gap_type == ContentGapType.UNDERPERFORMING:
            feasibility_score = 15.0
        else:  # OPTIMIZED
            feasibility_score = 5.0

        raw_score = vol_score + intent_score + feasibility_score
        opportunity_score = round(max(0.0, min(100.0, raw_score)), 1)

        recommendations: List[str] = [gap.recommended_action]
        if classification.intent == SearchIntent.TRANSACTIONAL:
            recommendations.append("Include prominent Call-To-Action (CTA) and social proof on landing page.")
        elif classification.intent == SearchIntent.COMMERCIAL:
            recommendations.append("Add structured comparison table and third-party verified ratings.")
        elif classification.intent == SearchIntent.INFORMATIONAL:
            recommendations.append("Structure content with FAQ schema and answer engine citation anchors.")

        return KeywordOpportunity(
            query=record.query,
            tenant_id=record.tenant_id,
            intent=classification.intent,
            intent_confidence=classification.confidence,
            current_position=record.position,
            impressions=record.impressions,
            clicks=record.clicks,
            current_ctr=record.ctr,
            content_gap=gap.gap_type,
            content_gap_severity=gap.severity,
            content_gap_reason=gap.reason,
            target_position=target_position,
            projected_ctr=projected_ctr,
            projected_clicks=projected_clicks,
            incremental_clicks=incremental_clicks,
            conversion_rate=conv_rate,
            projected_conversions=projected_conversions,
            average_deal_value=average_deal_value,
            estimated_revenue_opportunity=revenue_opportunity,
            opportunity_score=opportunity_score,
            recommendations=recommendations,
        )

    def analyze_corpus(
        self,
        records: List[Dict[str, Any] | SearchQueryRecord],
        target_position: float = 3.0,
        average_deal_value: float = 500.0,
        conversion_rate_by_intent: Optional[Dict[SearchIntent, float]] = None,
    ) -> List[KeywordOpportunity]:
        """
        Processes a full batch of query records, computes intent, content gaps,
        and ranks revenue opportunities by opportunity score descending.
        """
        valid_records = self.ingest_records(records, enforce_tenant=True)
        opportunities: List[KeywordOpportunity] = []

        for rec in valid_records:
            conv_override = None
            if conversion_rate_by_intent:
                intent_res = self.classify_intent(rec.query)
                conv_override = conversion_rate_by_intent.get(intent_res.intent)

            opp = self.calculate_opportunity(
                record=rec,
                target_position=target_position,
                average_deal_value=average_deal_value,
                conversion_rate_override=conv_override,
            )
            opportunities.append(opp)

        # Sort by opportunity score descending
        opportunities.sort(key=lambda o: o.opportunity_score, reverse=True)
        return opportunities

    def generate_executive_summary(
        self, opportunities: List[KeywordOpportunity]
    ) -> Dict[str, Any]:
        """
        Produces an executive summary report of search intent and content gap findings.
        """
        total_queries = len(opportunities)
        total_impressions = sum(o.impressions for o in opportunities)
        total_clicks = sum(o.clicks for o in opportunities)
        total_revenue_opportunity = sum(o.estimated_revenue_opportunity for o in opportunities)
        total_incremental_clicks = sum(o.incremental_clicks for o in opportunities)

        by_intent: Dict[str, int] = {}
        by_gap: Dict[str, int] = {}
        high_priority: List[Dict[str, Any]] = []

        for o in opportunities:
            intent_val = o.intent.value
            by_intent[intent_val] = by_intent.get(intent_val, 0) + 1

            gap_val = o.content_gap.value
            by_gap[gap_val] = by_gap.get(gap_val, 0) + 1

            if o.opportunity_score >= 70.0:
                high_priority.append({
                    "query": o.query,
                    "intent": o.intent.value,
                    "current_position": o.current_position,
                    "opportunity_score": o.opportunity_score,
                    "estimated_revenue_opportunity": o.estimated_revenue_opportunity,
                    "recommended_action": o.recommendations[0] if o.recommendations else "",
                })

        return {
            "tenant_id": self.tenant_id,
            "total_queries_analyzed": total_queries,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "blended_ctr": round(total_clicks / total_impressions, 4) if total_impressions > 0 else 0.0,
            "total_incremental_clicks_potential": round(total_incremental_clicks, 1),
            "total_estimated_revenue_opportunity": round(total_revenue_opportunity, 2),
            "intent_distribution": by_intent,
            "content_gap_distribution": by_gap,
            "high_priority_opportunities_count": len(high_priority),
            "high_priority_opportunities": high_priority[:10],
        }
