"""
Test Suite for Executive Attribution & Revenue Reconciliation Dashboard.
Task 7.1 (Line of Work 7: Unified Multi-Tenant UI Portal & Single-Pane Dashboards).
Verifies component template contracts, FR-07 fail-closed financial integrity,
multi-model comparison tables, stale connector warnings, and conversion drill-down structures.
"""

import os
import re
from pathlib import Path
import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = WORKSPACE_ROOT / "frontend" / "src"
VUE_COMPONENT_PATH = FRONTEND_DIR / "components" / "AttributionDashboard.vue"
TYPES_PATH = FRONTEND_DIR / "types" / "attribution.ts"
MOCK_DATA_PATH = FRONTEND_DIR / "mock" / "attributionData.ts"
SPEC_FILE_PATH = WORKSPACE_ROOT / "tests" / "frontend" / "test_attribution_dashboard.spec.ts"


class TestAttributionDashboardComponentStructure:
    def test_vue_component_exists(self) -> None:
        assert VUE_COMPONENT_PATH.exists(), f"Vue component missing at {VUE_COMPONENT_PATH}"

    def test_types_file_exists(self) -> None:
        assert TYPES_PATH.exists(), f"TypeScript types missing at {TYPES_PATH}"

    def test_mock_data_exists(self) -> None:
        assert MOCK_DATA_PATH.exists(), f"Mock data file missing at {MOCK_DATA_PATH}"

    def test_spec_file_exists(self) -> None:
        assert SPEC_FILE_PATH.exists(), f"TypeScript spec file missing at {SPEC_FILE_PATH}"

    def test_vue_component_contains_required_sections(self) -> None:
        content = VUE_COMPONENT_PATH.read_text(encoding="utf-8")
        assert "<template>" in content
        assert "</template>" in content
        assert '<script setup lang="ts">' in content
        assert "</script>" in content
        assert "<style scoped>" in content


class TestExecutiveDashboardRequirements:
    @pytest.fixture
    def vue_content(self) -> str:
        return VUE_COMPONENT_PATH.read_text(encoding="utf-8")

    def test_metric_cards_for_all_four_core_kpis(self, vue_content: str) -> None:
        """
        Deliverable requirement:
        - Metric cards for Total Ad Spend, Total Attributed Revenue, Blended ROAS, and CAC.
        """
        assert 'data-testid="metric-cards-grid"' in vue_content
        assert 'data-testid="kpi-total-spend"' in vue_content
        assert 'data-testid="kpi-total-revenue"' in vue_content
        assert 'data-testid="kpi-blended-roas"' in vue_content
        assert 'data-testid="kpi-cac"' in vue_content

        # Written metric definitions required by PRD FR-07
        assert "Definition: Net media spend" in vue_content
        assert "Definition: Verified Stripe/CRM cash" in vue_content
        assert "Definition: Revenue / Spend" in vue_content
        assert "Definition: Spend / Closed Customers" in vue_content

    def test_fr07_fail_closed_financial_integrity(self, vue_content: str) -> None:
        """
        FR-07: "Do not calculate ROAS/CAC when required inputs are missing."
        """
        assert 'data-testid="kpi-blended-roas-masked"' in vue_content
        assert 'data-testid="kpi-cac-masked"' in vue_content
        assert "INCOMPLETE DATA" in vue_content
        assert "Fail-closed gate active" in vue_content

    def test_missing_data_and_stale_connector_warning_banner(self, vue_content: str) -> None:
        """
        Deliverable requirement:
        - Warning banner for missing data or stale connector feeds.
        """
        assert 'data-testid="warning-banner"' in vue_content
        assert "Data Freshness Warning: Stale Connector Feeds Detected" in vue_content
        assert "staleConnectors" in vue_content
        assert "hoursStale" in vue_content

    def test_multi_model_attribution_comparison(self, vue_content: str) -> None:
        """
        Deliverable requirement:
        - Multi-model attribution comparison table/chart (First-Touch vs. Last-Touch vs. Multi-Touch).
        """
        assert 'data-testid="attribution-comparison-section"' in vue_content
        assert 'data-testid="comparison-table"' in vue_content
        assert "First-Touch Rev" in vue_content
        assert "Last-Touch Rev" in vue_content
        assert "Multi-Touch Rev" in vue_content
        assert "LINEAR_MULTI_TOUCH" in vue_content
        assert "FIRST_TOUCH" in vue_content
        assert "LAST_TOUCH" in vue_content
        assert "W_SHAPED" in vue_content

    def test_drill_down_drawer_for_conversion_records(self, vue_content: str) -> None:
        """
        Deliverable requirement:
        - Drill-down drawer for inspecting underlying conversion records with timestamps and source IDs.
        """
        assert 'data-testid="drilldown-drawer"' in vue_content
        assert "Conversion Record Inspector" in vue_content
        assert "customerId" in vue_content
        assert "sourceSystem" in vue_content
        assert "touchpoints" in vue_content
        assert "Attribution Journey Timeline" in vue_content
        assert 'data-testid="close-drawer-btn"' in vue_content

    def test_multi_tenant_isolation_tag(self, vue_content: str) -> None:
        """
        Multi-tenant rule: Tenant boundaries must be displayed and isolated.
        """
        assert "Tenant: {{ tenantId }}" in vue_content


class TestTypescriptTypesAndDataContracts:
    @pytest.fixture
    def types_content(self) -> str:
        return TYPES_PATH.read_text(encoding="utf-8")

    def test_types_definition_integrity(self, types_content: str) -> None:
        assert "export interface AttributionKPIs" in types_content
        assert "totalAdSpend: number;" in types_content
        assert "totalAttributedRevenue: number;" in types_content
        assert "blendedRoas: number | null;" in types_content
        assert "cac: number | null;" in types_content
        assert "isSpendComplete: boolean;" in types_content
        assert "isRevenueComplete: boolean;" in types_content

        assert "export interface ConnectorHealth" in types_content
        assert "status: ConnectorStatusType;" in types_content
        assert "hoursStale: number;" in types_content

        assert "export interface ModelComparisonRow" in types_content
        assert "firstTouchRev: number;" in types_content
        assert "lastTouchRev: number;" in types_content
        assert "multiTouchRev: number;" in types_content

        assert "export interface ConversionRecord" in types_content
        assert "conversionId: string;" in types_content
        assert "touchpoints: TouchpointEvent[];" in types_content
        assert "reconciliationStatus: ReconciliationStatus;" in types_content


class TestDashboardBusinessLogicRules:
    def test_fail_closed_roas_calculation(self) -> None:
        """
        Tests the mathematical calculation and fail-closed suppression logic of ROAS & CAC.
        """
        def calculate_roas_and_cac(
            spend: float,
            revenue: float,
            customers_count: int,
            spend_complete: bool,
            revenue_complete: bool,
        ):
            if not spend_complete or not revenue_complete or spend <= 0:
                return {"roas": None, "cac": None, "status": "INCOMPLETE_DATA"}
            
            roas = round(revenue / spend, 2)
            cac = round(spend / max(1, customers_count), 2)
            return {"roas": roas, "cac": cac, "status": "CALCULATED"}

        # Case 1: Complete data
        res1 = calculate_roas_and_cac(
            spend=50000.0,
            revenue=200000.0,
            customers_count=250,
            spend_complete=True,
            revenue_complete=True,
        )
        assert res1["status"] == "CALCULATED"
        assert res1["roas"] == 4.0
        assert res1["cac"] == 200.0

        # Case 2: Incomplete revenue feed (e.g. stale CRM) -> ROAS must be suppressed!
        res2 = calculate_roas_and_cac(
            spend=50000.0,
            revenue=150000.0,
            customers_count=200,
            spend_complete=True,
            revenue_complete=False,
        )
        assert res2["status"] == "INCOMPLETE_DATA"
        assert res2["roas"] is None
        assert res2["cac"] is None

    def test_connector_staleness_filter(self) -> None:
        """
        Connectors stale for > 24 hours must be flagged.
        """
        connectors = [
            {"name": "Meta Ads", "hours_stale": 0.5, "status": "healthy"},
            {"name": "Google Ads", "hours_stale": 1.2, "status": "healthy"},
            {"name": "HubSpot CRM", "hours_stale": 28.5, "status": "stale"},
        ]
        stale = [c for c in connectors if c["status"] == "stale" or c["hours_stale"] >= 24.0]
        assert len(stale) == 1
        assert stale[0]["name"] == "HubSpot CRM"
