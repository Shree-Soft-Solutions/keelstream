import { AttributionKPIs, ConnectorHealth, ModelComparisonRow, ConversionRecord } from '../types/attribution';

export const mockConnectors: ConnectorHealth[] = [
  {
    id: 'conn-meta-01',
    name: 'Meta Ads',
    type: 'ad_platform',
    status: 'healthy',
    lastSyncTime: new Date(Date.now() - 25 * 60 * 1000).toISOString(), // 25 mins ago
    hoursStale: 0.4,
    recordsIngestedLast24h: 14200,
    dataCoveragePct: 99.2,
  },
  {
    id: 'conn-google-01',
    name: 'Google Ads',
    type: 'ad_platform',
    status: 'healthy',
    lastSyncTime: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
    hoursStale: 0.75,
    recordsIngestedLast24h: 21850,
    dataCoveragePct: 98.8,
  },
  {
    id: 'conn-hubspot-01',
    name: 'HubSpot CRM',
    type: 'crm',
    status: 'stale',
    lastSyncTime: new Date(Date.now() - 28 * 3600 * 1000).toISOString(), // 28 hours ago!
    hoursStale: 28.0,
    recordsIngestedLast24h: 0,
    errorMessage: 'OAuth token refresh expired or rate limit encountered. Last successful checkpoint 28h ago.',
    dataCoveragePct: 82.5,
  },
  {
    id: 'conn-stripe-01',
    name: 'Stripe Payments',
    type: 'payment',
    status: 'healthy',
    lastSyncTime: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    hoursStale: 0.16,
    recordsIngestedLast24h: 340,
    dataCoveragePct: 100.0,
  },
];

export const mockKPIs: AttributionKPIs = {
  totalAdSpend: 48500.00,
  totalAttributedRevenue: 198850.00,
  blendedRoas: 4.10,
  cac: 142.65,
  totalConversions: 340,
  currency: 'USD',
  isSpendComplete: true,
  isRevenueComplete: false, // CRM sync is stale
  missingInputsWarning: 'HubSpot CRM feed is stale (>24h). Blended ROAS & CAC calculations are provisional and may omit un-synced deals.',
  dataCoveragePct: 88.4,
  lastUpdated: new Date().toISOString(),
};

export const mockModelComparison: ModelComparisonRow[] = [
  {
    channel: 'Google Search',
    campaign: 'Non-Brand Intent - RevOps',
    adSpend: 18500,
    firstTouchRev: 84200,
    lastTouchRev: 62400,
    multiTouchRev: 76800,
    conversionsCount: 128,
    variancePct: 9.6,
  },
  {
    channel: 'Meta Paid Social',
    campaign: 'B2B Retargeting - Video Creative A',
    adSpend: 14200,
    firstTouchRev: 29500,
    lastTouchRev: 68100,
    multiTouchRev: 52400,
    conversionsCount: 94,
    variancePct: -43.7, // First-touch severely undervalues retargeting
  },
  {
    channel: 'LinkedIn Sponsored',
    campaign: 'Director of RevOps Targeted InMail',
    adSpend: 11000,
    firstTouchRev: 52300,
    lastTouchRev: 21900,
    multiTouchRev: 41250,
    conversionsCount: 68,
    variancePct: 26.8, // First-touch captures initial discovery
  },
  {
    channel: 'Organic / Direct',
    campaign: 'Direct Navigation & Brand Search',
    adSpend: 4800,
    firstTouchRev: 32850,
    lastTouchRev: 46450,
    multiTouchRev: 28400,
    conversionsCount: 50,
    variancePct: 15.6,
  },
];

export const mockConversions: ConversionRecord[] = [
  {
    conversionId: 'conv_8a91bf20',
    timestamp: '2026-10-22T18:42:10Z',
    customerId: 'cust_acct_8421',
    revenue: 4500.00,
    currency: 'USD',
    channel: 'Google Search',
    campaign: 'Non-Brand Intent - RevOps',
    reconciliationStatus: 'RECONCILED',
    sourceSystem: 'stripe_charge_ch_3M8901',
    sourceRecordId: 'hubspot_deal_89012',
    tenantId: 'tenant_agency_01',
    touchpoints: [
      {
        touchpointId: 'tp_01',
        timestamp: '2026-10-15T09:12:00Z',
        channel: 'Google Search',
        campaign: 'Non-Brand Intent - RevOps',
        creative: 'Headline: Stop Wasting Ad Spend',
        clickId: 'gclid_99201481',
      },
      {
        touchpointId: 'tp_02',
        timestamp: '2026-10-18T14:35:22Z',
        channel: 'Meta Paid Social',
        campaign: 'B2B Retargeting - Video Creative A',
        creative: 'Video: 30s Product Walkthrough',
        clickId: 'fbclid_7731992',
      },
      {
        touchpointId: 'tp_03',
        timestamp: '2026-10-22T18:30:00Z',
        channel: 'Direct Navigation',
        campaign: 'Direct',
        landingPage: 'https://keelstream.io/checkout',
      },
    ],
  },
  {
    conversionId: 'conv_9c44da11',
    timestamp: '2026-10-22T16:15:33Z',
    customerId: 'cust_acct_5502',
    revenue: 12000.00,
    currency: 'USD',
    channel: 'LinkedIn Sponsored',
    campaign: 'Director of RevOps Targeted InMail',
    reconciliationStatus: 'RECONCILED',
    sourceSystem: 'stripe_charge_ch_3M8905',
    sourceRecordId: 'hubspot_deal_89045',
    tenantId: 'tenant_agency_01',
    touchpoints: [
      {
        touchpointId: 'tp_11',
        timestamp: '2026-10-10T11:20:00Z',
        channel: 'LinkedIn Sponsored',
        campaign: 'Director of RevOps Targeted InMail',
        creative: 'InMail: Enterprise Revenue Attribution Guide',
      },
      {
        touchpointId: 'tp_12',
        timestamp: '2026-10-22T16:00:00Z',
        channel: 'Google Search',
        campaign: 'Brand Search',
        creative: 'KeelStream Official Platform',
      },
    ],
  },
  {
    conversionId: 'conv_3f11e980',
    timestamp: '2026-10-22T14:02:45Z',
    customerId: 'cust_acct_9912',
    revenue: 2800.00,
    currency: 'USD',
    channel: 'Meta Paid Social',
    campaign: 'B2B Retargeting - Video Creative A',
    reconciliationStatus: 'DISCREPANCY',
    sourceSystem: 'stripe_charge_ch_3M8919',
    sourceRecordId: 'unmatched_stripe_event',
    tenantId: 'tenant_agency_01',
    touchpoints: [
      {
        touchpointId: 'tp_21',
        timestamp: '2026-10-22T13:40:00Z',
        channel: 'Meta Paid Social',
        campaign: 'B2B Retargeting - Video Creative A',
      },
    ],
  },
];
