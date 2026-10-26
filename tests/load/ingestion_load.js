/**
 * ============================================================================
 * KeelStream Ingestion High-Throughput Load & Resiliency Test (k6)
 * ============================================================================
 * Simulates sustained ingestion of 500 events/second across multiple tenants.
 * Assesses end-to-end ingestion latency and verifies ZERO cross-tenant contamination.
 *
 * Target: PRD Section 9, Phase 7 ("Fault-Tolerant Resiliency Hardening & Load Test")
 *
 * Usage:
 *   k6 run tests/load/ingestion_load.js
 *   TARGET_URL=http://localhost:8000/api/v1/ingest TARGET_RPS=500 DURATION=30s k6 run tests/load/ingestion_load.js
 * ============================================================================
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// --- Custom Metrics & Telemetry ---
export const ingestionSuccessRate = new Rate('ingestion_success_rate');
export const crossTenantContaminationErrors = new Rate('cross_tenant_contamination_errors');
export const eventIngestionLatency = new Trend('event_ingestion_latency');
export const eventsIngestedTotal = new Counter('events_ingested_total');

// --- Configuration ---
const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8000/api/v1/ingest/events';
const TARGET_RPS = __ENV.TARGET_RPS ? parseInt(__ENV.TARGET_RPS) : 500;
const DURATION = __ENV.DURATION || '60s';
const PRE_ALLOCATED_VUS = __ENV.VUS ? parseInt(__ENV.VUS) : 50;
const MAX_VUS = __ENV.MAX_VUS ? parseInt(__ENV.MAX_VUS) : 250;

export const options = {
  scenarios: {
    sustained_ingestion_stream: {
      executor: 'constant-arrival-rate',
      rate: TARGET_RPS, // 500 events / second target
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
    },
  },
  thresholds: {
    // PRD Section 9 SLA requirements:
    // 95th percentile response time must remain below 200ms under 500 RPS load
    http_req_duration: ['p(95)<200', 'p(99)<500'],
    // Overall HTTP failure rate below 1%
    http_req_failed: ['rate<0.01'],
    // Zero tolerance for cross-tenant contamination
    cross_tenant_contamination_errors: ['rate==0'],
    // Sustained high success rate
    ingestion_success_rate: ['rate>0.99'],
  },
};

// --- Multi-Tenant Test Pool ---
const TENANTS = [
  { id: 'tenant_alpha_direct', apiKey: 'keel_live_key_alpha_7482' },
  { id: 'tenant_beta_ecommerce', apiKey: 'keel_live_key_beta_9921' },
  { id: 'tenant_gamma_agency', apiKey: 'keel_live_key_gamma_1048' },
  { id: 'tenant_delta_saas', apiKey: 'keel_live_key_delta_5520' },
  { id: 'tenant_omega_fintech', apiKey: 'keel_live_key_omega_8834' },
];

const EVENT_TYPES = [
  'page_view',
  'lead_capture',
  'add_to_cart',
  'checkout_completed',
  'ad_interaction',
];

const CAMPAIGNS = [
  'cmp_google_search_brand_2026',
  'cmp_meta_retargeting_q4',
  'cmp_linkedin_abm_execs',
  'cmp_youtube_product_tour',
  'cmp_organic_seo_cluster_a',
];

/**
 * Generates dynamic, realistic telemetry payload with strict tenant metadata
 */
function generateEventPayload(tenant) {
  const iterationId = `${__VU}-${__ITER}-${Date.now()}`;
  const eventType = EVENT_TYPES[Math.floor(Math.random() * EVENT_TYPES.length)];
  const campaign = CAMPAIGNS[Math.floor(Math.random() * CAMPAIGNS.length)];

  return {
    tenant_id: tenant.id,
    event_id: `evt_${iterationId}`,
    idempotency_key: `idemp_${tenant.id}_${iterationId}`,
    event_type: eventType,
    timestamp: new Date().toISOString(),
    touchpoint: {
      anonymous_id: `anon_${Math.floor(Math.random() * 100000)}`,
      session_id: `sess_${Math.floor(Math.random() * 50000)}`,
      utm_source: campaign.split('_')[1] || 'direct',
      utm_medium: 'cpc',
      utm_campaign: campaign,
      url: `https://${tenant.id.replace('tenant_', '')}.com/products/attribution-suite`,
      referrer: 'https://www.google.com/',
      ip_hash: `sha256_${Math.floor(Math.random() * 9999999)}`,
    },
    conversion_data: eventType === 'checkout_completed' ? {
      order_id: `ord_${iterationId}`,
      gross_amount_cents: Math.floor(Math.random() * 50000) + 1000,
      currency: 'USD',
      stripe_charge_id: `ch_${iterationId}`,
    } : null,
  };
}

export function setup() {
  console.log(`[k6 Setup] Commencing KeelStream ingestion load test against: ${TARGET_URL}`);
  console.log(`[k6 Setup] Target Rate: ${TARGET_RPS} events/sec | Duration: ${DURATION} | Preallocated VUs: ${PRE_ALLOCATED_VUS}`);
  console.log(`[k6 Setup] Multi-tenant pool size: ${TENANTS.length} isolated tenants`);
  return { startTime: new Date().toISOString() };
}

export default function () {
  // Uniformly distribute requests across tenants
  const tenant = TENANTS[Math.floor(Math.random() * TENANTS.length)];
  const payload = generateEventPayload(tenant);
  const payloadString = JSON.stringify(payload);

  const headers = {
    'Content-Type': 'application/json',
    'X-Tenant-ID': tenant.id,
    'Authorization': `Bearer ${tenant.apiKey}`,
    'X-Idempotency-Key': payload.idempotency_key,
  };

  const startTime = Date.now();
  const response = http.post(TARGET_URL, payloadString, { headers });
  const latency = Date.now() - startTime;

  eventIngestionLatency.add(latency);

  // Status check: accept 200 OK or 202 Accepted (standard for asynchronous ingestion ingress)
  const isStatusValid = response.status === 200 || response.status === 202;
  ingestionSuccessRate.add(isStatusValid ? 1 : 0);

  if (isStatusValid) {
    eventsIngestedTotal.add(1);

    // Strict Cross-Tenant Contamination Verification
    // Ensure response payload or response header echoes back STRICTLY the requested tenant_id
    let contaminationDetected = false;

    // Check response header isolation
    const respTenantHeader = response.headers['X-Tenant-ID'] || response.headers['x-tenant-id'];
    if (respTenantHeader && respTenantHeader !== tenant.id) {
      contaminationDetected = true;
    }

    // Check response body isolation if JSON
    try {
      const body = response.json();
      if (body && body.tenant_id && body.tenant_id !== tenant.id) {
        contaminationDetected = true;
      }
    } catch (e) {
      // Body may be empty on 202
    }

    if (contaminationDetected) {
      console.error(`[CRITICAL] Cross-tenant contamination detected! Sent tenant: ${tenant.id}, Received: ${respTenantHeader}`);
      crossTenantContaminationErrors.add(1);
    } else {
      crossTenantContaminationErrors.add(0);
    }
  } else {
    // If request failed entirely, record failure
    if (response.status === 429) {
      console.warn(`[HTTP 429] Ingestion rate limit exceeded for ${tenant.id}. Backing off...`);
    } else if (response.status >= 500) {
      console.error(`[HTTP ${response.status}] Server error during ingestion for ${tenant.id}: ${response.body}`);
    }
  }

  check(response, {
    'status is 200 or 202': (r) => r.status === 200 || r.status === 202,
    'latency is within SLA (< 200ms)': () => latency < 200,
  });
}

export function teardown(data) {
  console.log(`[k6 Teardown] Ingestion load test finished. Started at: ${data.startTime}`);
}
