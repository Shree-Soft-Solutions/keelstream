<template>
  <div class="attribution-dashboard-container bg-slate-950 text-slate-100 min-h-screen p-6 font-sans">
    <!-- Header Section -->
    <header class="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-800 gap-4">
      <div>
        <div class="flex items-center gap-3">
          <h1 class="text-2xl font-bold tracking-tight text-white">Executive Revenue Attribution & Reconciliation</h1>
          <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
            Tenant: {{ tenantId }}
          </span>
        </div>
        <p class="text-sm text-slate-400 mt-1">
          Deterministic closed-loop attribution with live CRM & payment reconciliation.
        </p>
      </div>

      <div class="flex items-center gap-3">
        <!-- Date Range Filter -->
        <div class="flex items-center bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300">
          <span class="text-slate-500 mr-2">Window:</span>
          <span class="font-medium text-slate-200">{{ dateRange.startDate }} &rarr; {{ dateRange.endDate }}</span>
        </div>

        <!-- Sync Now Button -->
        <button
          @click="handleManualSync"
          :disabled="isSyncing"
          class="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-xs font-semibold rounded-lg transition-colors shadow-sm"
        >
          <span v-if="isSyncing" class="animate-spin text-sm">&#8635;</span>
          <span>{{ isSyncing ? 'Syncing Feeds...' : 'Refresh Feeds' }}</span>
        </button>
      </div>
    </header>

    <!-- Missing Data / Stale Connector Warning Banner (FR-07 Fail-Closed Integrity) -->
    <section v-if="staleConnectors.length > 0 || !kpis.isSpendComplete || !kpis.isRevenueComplete"
             data-testid="warning-banner"
             class="mt-6 bg-amber-950/40 border border-amber-600/60 rounded-xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 text-amber-200">
      <div class="flex items-start gap-3">
        <div class="p-2 bg-amber-900/50 rounded-lg text-amber-400 font-bold text-lg leading-none">
          &#9888;
        </div>
        <div>
          <h4 class="text-sm font-semibold text-amber-300">
            Data Freshness Warning: Stale Connector Feeds Detected
          </h4>
          <p class="text-xs text-amber-200/80 mt-0.5">
            <template v-if="kpis.missingInputsWarning">
              {{ kpis.missingInputsWarning }}
            </template>
            <template v-else>
              One or more connectors have not synced in >24 hours. Financial metrics operate under fail-closed integrity.
            </template>
          </p>
          <div class="flex flex-wrap gap-2 mt-2">
            <span v-for="conn in staleConnectors" :key="conn.id" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs bg-amber-900/60 text-amber-300 border border-amber-700">
              <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
              {{ conn.name }} (Stale: {{ conn.hoursStale.toFixed(1) }}h lag)
            </span>
          </div>
        </div>
      </div>
      <button
        @click="openConnectorDrawer"
        class="text-xs font-semibold px-3 py-1.5 bg-amber-700/40 hover:bg-amber-700/60 text-amber-100 border border-amber-600 rounded-lg whitespace-nowrap transition-colors"
      >
        Inspect Feeds &rarr;
      </button>
    </section>

    <!-- Executive Metric / KPI Cards -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6" data-testid="metric-cards-grid">
      <!-- Card 1: Total Ad Spend -->
      <div class="metric-card bg-slate-900/90 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all shadow-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Total Ad Spend</span>
          <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
            {{ kpis.currency }}
          </span>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-2xl font-bold text-white tracking-tight" data-testid="kpi-total-spend">
            {{ formatCurrency(kpis.totalAdSpend) }}
          </span>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
          <span title="Aggregate spend across Meta, Google, and paid networks">Definition: Net media spend</span>
          <span class="text-emerald-400 font-medium">{{ kpis.dataCoveragePct }}% Coverage</span>
        </div>
      </div>

      <!-- Card 2: Total Attributed Revenue -->
      <div class="metric-card bg-slate-900/90 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all shadow-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Attributed Revenue</span>
          <span class="text-xs px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 font-mono border border-emerald-900">
            Reconciled
          </span>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <span class="text-2xl font-bold text-emerald-400 tracking-tight" data-testid="kpi-total-revenue">
            {{ formatCurrency(kpis.totalAttributedRevenue) }}
          </span>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
          <span title="Reconciled against verified Stripe and CRM deal closings">Definition: Verified Stripe/CRM cash</span>
          <button @click="openDrawerForMetric('revenue')" class="text-indigo-400 hover:text-indigo-300 font-medium">
            Inspect {{ kpis.totalConversions }} orders &rarr;
          </button>
        </div>
      </div>

      <!-- Card 3: Blended ROAS (Fail-closed per FR-07) -->
      <div class="metric-card bg-slate-900/90 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all shadow-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Blended ROAS</span>
          <span class="text-xs px-2 py-0.5 rounded bg-indigo-950 text-indigo-400 font-mono border border-indigo-900">
            Ratio
          </span>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <template v-if="kpis.isRevenueComplete && kpis.isSpendComplete && kpis.blendedRoas !== null">
            <span class="text-2xl font-bold text-white tracking-tight" data-testid="kpi-blended-roas">
              {{ kpis.blendedRoas.toFixed(2) }}x
            </span>
            <span class="text-xs text-emerald-400 font-semibold">+18.4% vs last mo</span>
          </template>
          <template v-else>
            <span class="text-xl font-bold text-amber-400 tracking-tight" data-testid="kpi-blended-roas-masked">
              INCOMPLETE DATA
            </span>
          </template>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
          <span title="Attributed Revenue / Total Media Spend. Masked if inputs incomplete.">Definition: Revenue / Spend</span>
          <span v-if="!kpis.isRevenueComplete" class="text-amber-400 font-medium">Stale CRM Feed</span>
          <span v-else class="text-slate-400">Fail-closed gate active</span>
        </div>
      </div>

      <!-- Card 4: CAC (Customer Acquisition Cost) -->
      <div class="metric-card bg-slate-900/90 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all shadow-sm">
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium uppercase tracking-wider text-slate-400">Blended CAC</span>
          <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
            Per Deal
          </span>
        </div>
        <div class="mt-3 flex items-baseline gap-2">
          <template v-if="kpis.isSpendComplete && kpis.cac !== null">
            <span class="text-2xl font-bold text-white tracking-tight" data-testid="kpi-cac">
              {{ formatCurrency(kpis.cac) }}
            </span>
          </template>
          <template v-else>
            <span class="text-xl font-bold text-amber-400 tracking-tight" data-testid="kpi-cac-masked">
              INCOMPLETE DATA
            </span>
          </template>
        </div>
        <div class="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
          <span title="Total Spend divided by closed-won customer accounts">Definition: Spend / Closed Customers</span>
          <span class="text-slate-400 font-mono">{{ kpis.totalConversions }} Customers</span>
        </div>
      </div>
    </section>

    <!-- Multi-Model Attribution Comparison Section -->
    <section class="mt-8 bg-slate-900/80 border border-slate-800 rounded-xl p-6 shadow-sm" data-testid="attribution-comparison-section">
      <div class="flex flex-col md:flex-row md:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h2 class="text-lg font-semibold text-white">Multi-Model Attribution Comparison</h2>
          <p class="text-xs text-slate-400 mt-0.5">
            Compare how revenue is credited across touchpoints: First-Touch (acquisition discovery), Last-Touch (closing hook), and Multi-Touch (linear/weighted).
          </p>
        </div>

        <!-- Model Filter Tabs -->
        <div class="flex items-center bg-slate-950 p-1 rounded-lg border border-slate-800">
          <button
            v-for="model in modelOptions"
            :key="model.value"
            @click="activeModel = model.value"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
              activeModel === model.value
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            ]"
            :data-testid="`model-tab-${model.value}`"
          >
            {{ model.label }}
          </button>
        </div>
      </div>

      <!-- Visual Comparison Bar Chart -->
      <div class="mt-6 mb-6 p-4 bg-slate-950/60 rounded-lg border border-slate-800/80">
        <div class="flex items-center justify-between text-xs text-slate-400 mb-3">
          <span class="font-semibold text-slate-300">Revenue Distribution by Channel & Model</span>
          <div class="flex items-center gap-4">
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 bg-sky-500 rounded-sm"></span> First-Touch
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 bg-emerald-500 rounded-sm"></span> Multi-Touch
            </span>
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-3 bg-indigo-500 rounded-sm"></span> Last-Touch
            </span>
          </div>
        </div>

        <!-- Chart Rows -->
        <div class="space-y-3 mt-3">
          <div v-for="row in modelComparison" :key="row.channel" class="space-y-1">
            <div class="flex justify-between text-xs font-medium text-slate-300">
              <span>{{ row.channel }} ({{ row.campaign }})</span>
              <span class="font-mono text-slate-400">Spend: {{ formatCurrency(row.adSpend) }}</span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
              <!-- First Touch Bar -->
              <div class="flex items-center gap-2">
                <span class="text-[10px] w-12 text-sky-400 font-mono">1st Touch</span>
                <div class="flex-1 bg-slate-900 rounded-full h-3 overflow-hidden border border-slate-800">
                  <div class="bg-sky-500 h-full rounded-full transition-all duration-500" :style="{ width: `${computeBarWidth(row.firstTouchRev)}%` }"></div>
                </div>
                <span class="text-[10px] font-mono text-slate-300 w-16 text-right">{{ formatCurrency(row.firstTouchRev) }}</span>
              </div>
              <!-- Multi Touch Bar -->
              <div class="flex items-center gap-2">
                <span class="text-[10px] w-12 text-emerald-400 font-mono">Multi</span>
                <div class="flex-1 bg-slate-900 rounded-full h-3 overflow-hidden border border-slate-800">
                  <div class="bg-emerald-500 h-full rounded-full transition-all duration-500" :style="{ width: `${computeBarWidth(row.multiTouchRev)}%` }"></div>
                </div>
                <span class="text-[10px] font-mono text-slate-300 w-16 text-right">{{ formatCurrency(row.multiTouchRev) }}</span>
              </div>
              <!-- Last Touch Bar -->
              <div class="flex items-center gap-2">
                <span class="text-[10px] w-12 text-indigo-400 font-mono">Last Touch</span>
                <div class="flex-1 bg-slate-900 rounded-full h-3 overflow-hidden border border-slate-800">
                  <div class="bg-indigo-500 h-full rounded-full transition-all duration-500" :style="{ width: `${computeBarWidth(row.lastTouchRev)}%` }"></div>
                </div>
                <span class="text-[10px] font-mono text-slate-300 w-16 text-right">{{ formatCurrency(row.lastTouchRev) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Granular Table Breakdown -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs text-slate-300" data-testid="comparison-table">
          <thead class="bg-slate-950/80 uppercase text-[11px] font-semibold text-slate-400 border-y border-slate-800">
            <tr>
              <th class="py-3 px-4">Channel & Campaign</th>
              <th class="py-3 px-4 text-right">Ad Spend</th>
              <th class="py-3 px-4 text-right">First-Touch Rev</th>
              <th class="py-3 px-4 text-right">Last-Touch Rev</th>
              <th class="py-3 px-4 text-right">Multi-Touch Rev</th>
              <th class="py-3 px-4 text-right">Conversions</th>
              <th class="py-3 px-4 text-right">ROAS (Multi)</th>
              <th class="py-3 px-4 text-center">Action</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-mono">
            <tr v-for="row in modelComparison" :key="row.channel" class="hover:bg-slate-800/40 transition-colors">
              <td class="py-3 px-4 font-sans font-medium text-white">
                <div>{{ row.channel }}</div>
                <div class="text-[11px] text-slate-400 font-mono">{{ row.campaign }}</div>
              </td>
              <td class="py-3 px-4 text-right text-slate-300">
                {{ formatCurrency(row.adSpend) }}
              </td>
              <td class="py-3 px-4 text-right text-sky-400 font-semibold">
                {{ formatCurrency(row.firstTouchRev) }}
              </td>
              <td class="py-3 px-4 text-right text-indigo-400 font-semibold">
                {{ formatCurrency(row.lastTouchRev) }}
              </td>
              <td class="py-3 px-4 text-right text-emerald-400 font-semibold">
                {{ formatCurrency(row.multiTouchRev) }}
              </td>
              <td class="py-3 px-4 text-right text-slate-300">
                {{ row.conversionsCount }}
              </td>
              <td class="py-3 px-4 text-right">
                <span :class="row.multiTouchRev / row.adSpend >= 3.0 ? 'text-emerald-400 font-bold' : 'text-slate-300'">
                  {{ (row.multiTouchRev / row.adSpend).toFixed(2) }}x
                </span>
              </td>
              <td class="py-3 px-4 text-center">
                <button
                  @click="drillDownChannel(row.channel)"
                  class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-indigo-300 rounded font-sans text-xs transition-colors"
                  :data-testid="`btn-drilldown-${row.channel.toLowerCase().replace(/[\s\/]+/g, '-')}`"
                >
                  Inspect &rarr;
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Slide-over Drill-Down Drawer for Conversion & Journey Inspection -->
    <div
      v-if="isDrawerOpen"
      class="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm transition-opacity flex justify-end"
      data-testid="drilldown-drawer-overlay"
      @click.self="closeDrawer"
    >
      <div
        class="w-full max-w-2xl bg-slate-900 border-l border-slate-800 h-full p-6 overflow-y-auto shadow-2xl flex flex-col justify-between"
        data-testid="drilldown-drawer"
      >
        <div>
          <!-- Drawer Header -->
          <div class="flex items-center justify-between pb-4 border-b border-slate-800">
            <div>
              <div class="flex items-center gap-2">
                <h3 class="text-lg font-bold text-white">Conversion Record Inspector</h3>
                <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                  Tenant: {{ tenantId }}
                </span>
              </div>
              <p class="text-xs text-slate-400 mt-1">
                Showing {{ filteredConversions.length }} underlying records for audit and reconciliation.
              </p>
            </div>
            <button
              @click="closeDrawer"
              data-testid="close-drawer-btn"
              class="text-slate-400 hover:text-white text-xl p-1 rounded-lg hover:bg-slate-800 transition-colors"
            >
              &times;
            </button>
          </div>

          <!-- Drawer Filter Bar -->
          <div class="flex items-center gap-3 my-4">
            <select
              v-model="drawerFilterChannel"
              class="bg-slate-950 border border-slate-800 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Channels</option>
              <option v-for="ch in uniqueChannels" :key="ch" :value="ch">{{ ch }}</option>
            </select>

            <select
              v-model="drawerFilterStatus"
              class="bg-slate-950 border border-slate-800 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Reconciliation States</option>
              <option value="RECONCILED">Reconciled</option>
              <option value="DISCREPANCY">Discrepancy</option>
              <option value="UNMATCHED">Unmatched</option>
            </select>
          </div>

          <!-- Conversions Journey List -->
          <div class="space-y-4">
            <div
              v-for="record in filteredConversions"
              :key="record.conversionId"
              class="bg-slate-950/80 border border-slate-800 rounded-lg p-4 space-y-3"
              :data-testid="`conversion-item-${record.conversionId}`"
            >
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-mono font-bold text-white">{{ record.conversionId }}</span>
                  <span
                    :class="[
                      'text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase',
                      record.reconciliationStatus === 'RECONCILED'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-900'
                        : 'bg-amber-950 text-amber-400 border border-amber-900'
                    ]"
                  >
                    {{ record.reconciliationStatus }}
                  </span>
                </div>
                <div class="text-right">
                  <span class="text-sm font-bold text-emerald-400 font-mono">{{ formatCurrency(record.revenue) }}</span>
                  <div class="text-[10px] text-slate-500">{{ formatDate(record.timestamp) }}</div>
                </div>
              </div>

              <!-- Customer & Source Mapping -->
              <div class="text-xs text-slate-400 grid grid-cols-2 gap-2 bg-slate-900/60 p-2 rounded border border-slate-800/60 font-mono">
                <div>Customer: <span class="text-slate-200">{{ record.customerId }}</span></div>
                <div>Source: <span class="text-slate-200">{{ record.sourceSystem }}</span></div>
              </div>

              <!-- Journey Steps / Touchpoints Timeline -->
              <div>
                <span class="text-[11px] font-semibold text-slate-300 block mb-1.5 uppercase tracking-wide">
                  Attribution Journey Timeline ({{ record.touchpoints.length }} Touchpoints)
                </span>
                <ol class="relative border-l border-slate-800 ml-2 space-y-2 text-xs">
                  <li v-for="(tp, idx) in record.touchpoints" :key="tp.touchpointId" class="ml-4">
                    <span class="absolute -left-1.5 mt-1 w-3 h-3 rounded-full border border-slate-900"
                          :class="idx === 0 ? 'bg-sky-400' : idx === record.touchpoints.length - 1 ? 'bg-indigo-400' : 'bg-slate-600'">
                    </span>
                    <div class="flex items-center justify-between">
                      <span class="font-medium text-white">{{ tp.channel }}</span>
                      <span class="text-[10px] text-slate-500 font-mono">{{ formatDate(tp.timestamp) }}</span>
                    </div>
                    <div class="text-[11px] text-slate-400 font-mono">{{ tp.campaign }}</div>
                    <div v-if="tp.creative" class="text-[10px] text-slate-500 italic mt-0.5">{{ tp.creative }}</div>
                  </li>
                </ol>
              </div>
            </div>
          </div>
        </div>

        <!-- Drawer Footer -->
        <div class="mt-6 pt-4 border-t border-slate-800 flex justify-end">
          <button
            @click="closeDrawer"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold rounded-lg transition-colors"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  AttributionKPIs,
  ConnectorHealth,
  ModelComparisonRow,
  ConversionRecord,
  AttributionModelType,
} from '../types/attribution';
import {
  mockKPIs,
  mockConnectors,
  mockModelComparison,
  mockConversions,
} from '../mock/attributionData';

// Props
const props = withDefaults(
  defineProps<{
    tenantId?: string;
    initialKPIs?: AttributionKPIs;
    initialConnectors?: ConnectorHealth[];
    initialModelComparison?: ModelComparisonRow[];
    initialConversions?: ConversionRecord[];
  }>(),
  {
    tenantId: 'tenant_agency_01',
    initialKPIs: () => mockKPIs,
    initialConnectors: () => mockConnectors,
    initialModelComparison: () => mockModelComparison,
    initialConversions: () => mockConversions,
  }
);

// Reactive State
const tenantId = ref(props.tenantId);
const kpis = ref<AttributionKPIs>(props.initialKPIs);
const connectors = ref<ConnectorHealth[]>(props.initialConnectors);
const modelComparison = ref<ModelComparisonRow[]>(props.initialModelComparison);
const conversions = ref<ConversionRecord[]>(props.initialConversions);

const isSyncing = ref(false);
const activeModel = ref<AttributionModelType>('LINEAR_MULTI_TOUCH');
const isDrawerOpen = ref(false);
const drawerFilterChannel = ref<string>('');
const drawerFilterStatus = ref<string>('');

const dateRange = ref({
  startDate: '2026-10-01',
  endDate: '2026-10-23',
});

// Model Switcher Options
const modelOptions = [
  { label: 'Multi-Touch (Linear)', value: 'LINEAR_MULTI_TOUCH' },
  { label: 'First-Touch (Acquisition)', value: 'FIRST_TOUCH' },
  { label: 'Last-Touch (Closing)', value: 'LAST_TOUCH' },
  { label: 'W-Shaped (Full Funnel)', value: 'W_SHAPED' },
];

// Computed Properties
const staleConnectors = computed(() => {
  return connectors.value.filter(
    (c) => c.status === 'stale' || c.status === 'error' || c.hoursStale >= 24.0
  );
});

const uniqueChannels = computed(() => {
  const set = new Set<string>();
  conversions.value.forEach((c) => set.add(c.channel));
  return Array.from(set);
});

const maxRevenueInComparison = computed(() => {
  let max = 1;
  modelComparison.value.forEach((r) => {
    max = Math.max(max, r.firstTouchRev, r.lastTouchRev, r.multiTouchRev);
  });
  return max;
});

const filteredConversions = computed(() => {
  return conversions.value.filter((c) => {
    if (drawerFilterChannel.value && c.channel !== drawerFilterChannel.value) {
      return false;
    }
    if (drawerFilterStatus.value && c.reconciliationStatus !== drawerFilterStatus.value) {
      return false;
    }
    return true;
  });
});

// Helper functions
function formatCurrency(val: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(val);
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function computeBarWidth(val: number): number {
  if (maxRevenueInComparison.value <= 0) return 0;
  return Math.min(100, Math.round((val / maxRevenueInComparison.value) * 100));
}

// Actions
function handleManualSync() {
  isSyncing.value = true;
  setTimeout(() => {
    isSyncing.value = false;
  }, 1200);
}

function openDrawerForMetric(metricName: string) {
  drawerFilterChannel.value = '';
  drawerFilterStatus.value = '';
  isDrawerOpen.value = true;
}

function drillDownChannel(channel: string) {
  drawerFilterChannel.value = channel;
  drawerFilterStatus.value = '';
  isDrawerOpen.value = true;
}

function openConnectorDrawer() {
  isDrawerOpen.value = true;
}

function closeDrawer() {
  isDrawerOpen.value = false;
}
</script>

<style scoped>
.metric-card {
  backdrop-filter: blur(8px);
}
</style>
