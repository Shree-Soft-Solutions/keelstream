/**
 * KeelStream Frontend Attribution Dashboard Spec
 * Task 7.1: Executive Attribution & Revenue Reconciliation Dashboard
 * 
 * Verifies:
 * - Metric cards (Spend, Attributed Revenue, Blended ROAS, CAC)
 * - Missing data & stale connector feeds warning banner (FR-07)
 * - Multi-model attribution comparison table and visual chart
 * - Drill-down conversion record inspection drawer
 * - Fail-closed behavior when inputs are missing
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import AttributionDashboard from '../../frontend/src/components/AttributionDashboard.vue';
import { mockKPIs, mockConnectors, mockModelComparison, mockConversions } from '../../frontend/src/mock/attributionData';
import { AttributionKPIs } from '../../frontend/src/types/attribution';

describe('AttributionDashboard Component (Task 7.1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders executive header and multi-tenant tag', () => {
    const wrapper = mount(AttributionDashboard, {
      props: {
        tenantId: 'tenant_agency_01',
      },
    });

    expect(wrapper.text()).toContain('Executive Revenue Attribution & Reconciliation');
    expect(wrapper.text()).toContain('Tenant: tenant_agency_01');
  });

  it('displays all 4 executive metric cards with correct values and definitions', () => {
    const wrapper = mount(AttributionDashboard, {
      props: {
        initialKPIs: {
          ...mockKPIs,
          isSpendComplete: true,
          isRevenueComplete: true,
        },
      },
    });

    const cardsGrid = wrapper.find('[data-testid="metric-cards-grid"]');
    expect(cardsGrid.exists()).toBe(true);

    // Spend Card
    expect(wrapper.find('[data-testid="kpi-total-spend"]').text()).toContain('$48,500');
    expect(wrapper.text()).toContain('Definition: Net media spend');

    // Revenue Card
    expect(wrapper.find('[data-testid="kpi-total-revenue"]').text()).toContain('$198,850');
    expect(wrapper.text()).toContain('Definition: Verified Stripe/CRM cash');

    // ROAS Card (Calculated when inputs complete)
    expect(wrapper.find('[data-testid="kpi-blended-roas"]').text()).toContain('4.10x');

    // CAC Card
    expect(wrapper.find('[data-testid="kpi-cac"]').text()).toContain('$143');
  });

  it('enforces FR-07 fail-closed integrity: masks ROAS when revenue data is incomplete', async () => {
    const incompleteKPIs: AttributionKPIs = {
      ...mockKPIs,
      isRevenueComplete: false,
      missingInputsWarning: 'Stripe sync missing 48 hours of transaction records.',
      blendedRoas: null,
    };

    const wrapper = mount(AttributionDashboard, {
      props: {
        initialKPIs: incompleteKPIs,
      },
    });

    // ROAS should NOT display a speculative number; it must display INCOMPLETE DATA
    const maskedRoas = wrapper.find('[data-testid="kpi-blended-roas-masked"]');
    expect(maskedRoas.exists()).toBe(true);
    expect(maskedRoas.text()).toContain('INCOMPLETE DATA');
    expect(wrapper.find('[data-testid="kpi-blended-roas"]').exists()).toBe(false);
  });

  it('displays warning banner when stale connector feeds are detected', () => {
    const wrapper = mount(AttributionDashboard, {
      props: {
        initialConnectors: mockConnectors, // Includes HubSpot with 28h stale lag
      },
    });

    const banner = wrapper.find('[data-testid="warning-banner"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain('Data Freshness Warning: Stale Connector Feeds Detected');
    expect(banner.text()).toContain('HubSpot CRM');
    expect(banner.text()).toContain('28.0h lag');
  });

  it('hides warning banner when all connectors are healthy and inputs are complete', () => {
    const healthyConnectors = mockConnectors.map((c) => ({
      ...c,
      status: 'healthy' as const,
      hoursStale: 0.5,
    }));

    const completeKPIs: AttributionKPIs = {
      ...mockKPIs,
      isSpendComplete: true,
      isRevenueComplete: true,
      missingInputsWarning: null,
    };

    const wrapper = mount(AttributionDashboard, {
      props: {
        initialConnectors: healthyConnectors,
        initialKPIs: completeKPIs,
      },
    });

    expect(wrapper.find('[data-testid="warning-banner"]').exists()).toBe(false);
  });

  it('renders multi-model attribution comparison table and chart', () => {
    const wrapper = mount(AttributionDashboard, {
      props: {
        initialModelComparison: mockModelComparison,
      },
    });

    const section = wrapper.find('[data-testid="attribution-comparison-section"]');
    expect(section.exists()).toBe(true);

    const table = wrapper.find('[data-testid="comparison-table"]');
    expect(table.exists()).toBe(true);

    // Verify channel rows
    expect(table.text()).toContain('Google Search');
    expect(table.text()).toContain('Meta Paid Social');
    expect(table.text()).toContain('LinkedIn Sponsored');

    // Verify model columns
    expect(table.text()).toContain('First-Touch Rev');
    expect(table.text()).toContain('Last-Touch Rev');
    expect(table.text()).toContain('Multi-Touch Rev');
  });

  it('allows switching attribution model tabs', async () => {
    const wrapper = mount(AttributionDashboard);

    const firstTouchTab = wrapper.find('[data-testid="model-tab-FIRST_TOUCH"]');
    expect(firstTouchTab.exists()).toBe(true);

    await firstTouchTab.trigger('click');
    expect(firstTouchTab.classes()).toContain('bg-indigo-600');
  });

  it('opens drill-down drawer and displays underlying conversion records with journey touchpoints', async () => {
    const wrapper = mount(AttributionDashboard, {
      props: {
        initialConversions: mockConversions,
      },
    });

    // Drawer should initially be closed
    expect(wrapper.find('[data-testid="drilldown-drawer"]').exists()).toBe(false);

    // Click drill-down on Google Search
    const drillDownBtn = wrapper.find('[data-testid="btn-drilldown-google-search"]');
    expect(drillDownBtn.exists()).toBe(true);
    await drillDownBtn.trigger('click');

    // Drawer should now be visible
    const drawer = wrapper.find('[data-testid="drilldown-drawer"]');
    expect(drawer.exists()).toBe(true);
    expect(drawer.text()).toContain('Conversion Record Inspector');
    expect(drawer.text()).toContain('conv_8a91bf20');
    expect(drawer.text()).toContain('cust_acct_8421');
    expect(drawer.text()).toContain('Attribution Journey Timeline');

    // Close drawer
    const closeBtn = wrapper.find('[data-testid="close-drawer-btn"]');
    await closeBtn.trigger('click');
    expect(wrapper.find('[data-testid="drilldown-drawer"]').exists()).toBe(false);
  });
});
