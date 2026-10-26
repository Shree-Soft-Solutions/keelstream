/**
 * KeelStream Frontend Attribution & Revenue Types
 * Line of Work 7: Unified Multi-Tenant UI Portal (Task 7.1)
 */

export type AttributionModelType = 'FIRST_TOUCH' | 'LAST_TOUCH' | 'LINEAR_MULTI_TOUCH' | 'W_SHAPED';

export type ReconciliationStatus = 'RECONCILED' | 'UNMATCHED' | 'DISCREPANCY' | 'PENDING';

export type ConnectorStatusType = 'healthy' | 'stale' | 'error' | 'syncing';

export interface ConnectorHealth {
  id: string;
  name: string; // e.g., 'Meta Ads', 'Google Ads', 'Stripe', 'HubSpot'
  type: 'ad_platform' | 'crm' | 'payment';
  status: ConnectorStatusType;
  lastSyncTime: string; // ISO 8601
  hoursStale: number;
  recordsIngestedLast24h: number;
  errorMessage?: string;
  dataCoveragePct: number;
}

export interface AttributionKPIs {
  totalAdSpend: number;
  totalAttributedRevenue: number;
  blendedRoas: number | null; // null if spend or revenue data is missing/stale per FR-07
  cac: number | null;         // null if spend or customer data is missing/stale per FR-07
  totalConversions: number;
  currency: string;
  isSpendComplete: boolean;
  isRevenueComplete: boolean;
  missingInputsWarning: string | null;
  dataCoveragePct: number;
  lastUpdated: string;
}

export interface ModelComparisonRow {
  channel: string;
  campaign: string;
  adSpend: number;
  firstTouchRev: number;
  lastTouchRev: number;
  multiTouchRev: number;
  conversionsCount: number;
  variancePct: number; // Variance between First-Touch and Multi-Touch
}

export interface TouchpointEvent {
  touchpointId: string;
  timestamp: string;
  channel: string;
  campaign: string;
  creative?: string;
  adGroup?: string;
  landingPage?: string;
  clickId?: string;
}

export interface ConversionRecord {
  conversionId: string;
  timestamp: string;
  customerId: string;
  revenue: number;
  currency: string;
  channel: string;
  campaign: string;
  reconciliationStatus: ReconciliationStatus;
  sourceSystem: string; // e.g., 'stripe_ch_3Nkd92', 'hubspot_deal_9921'
  sourceRecordId: string;
  tenantId: string;
  touchpoints: TouchpointEvent[];
}

export interface DashboardState {
  tenantId: string;
  dateRange: {
    startDate: string;
    endDate: string;
  };
  kpis: AttributionKPIs;
  connectors: ConnectorHealth[];
  modelComparison: ModelComparisonRow[];
  conversions: ConversionRecord[];
  selectedModel: AttributionModelType;
  isDrawerOpen: boolean;
  selectedFilterChannel: string | null;
  selectedFilterRecord: ConversionRecord | null;
}
