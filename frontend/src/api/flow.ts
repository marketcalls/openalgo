// api/flow.ts
// Flow Workflow API module

import type { Edge, Node } from '@xyflow/react'
import { webClient } from './client'

// =============================================================================
// Types
// =============================================================================

export interface Workflow {
  id: number
  name: string
  description: string | null
  nodes: Node[]
  edges: Edge[]
  is_active: boolean
  schedule_job_id: string | null
  webhook_token: string | null
  webhook_secret: string | null
  webhook_enabled: boolean
  webhook_auth_type: 'payload' | 'url'
  created_at: string
  updated_at: string
}

export interface WorkflowListItem {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  last_execution_status: string | null
}

export interface WorkflowExecution {
  id: number
  workflow_id: number
  status: string
  started_at: string | null
  completed_at: string | null
  logs: ExecutionLog[]
  error: string | null
}

export interface ExecutionLog {
  time: string
  message: string
  level: string
}

export interface WebhookInfo {
  webhook_token: string
  webhook_secret: string
  webhook_enabled: boolean
  webhook_auth_type: 'payload' | 'url'
  webhook_url: string
  webhook_url_with_symbol: string
  webhook_url_with_secret: string | null
}

export interface WorkflowExportData {
  version: string
  name: string
  description: string | null
  nodes: Node[]
  edges: Edge[]
  exported_at: string
}

// =============================================================================
// API Functions
// =============================================================================

const FLOW_API_BASE = '/flow/api'

/**
 * List all workflows
 */
export async function listWorkflows(): Promise<WorkflowListItem[]> {
  const response = await webClient.get(`${FLOW_API_BASE}/workflows`)
  return response.data
}

/**
 * Get a single workflow by ID
 */
export async function getWorkflow(id: number): Promise<Workflow> {
  const response = await webClient.get(`${FLOW_API_BASE}/workflows/${id}`)
  return response.data
}

/**
 * Create a new workflow
 */
export async function createWorkflow(data: {
  name: string
  description?: string
  nodes?: Node[]
  edges?: Edge[]
}): Promise<Workflow> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows`, data)
  return response.data
}

/**
 * Update an existing workflow
 */
export async function updateWorkflow(
  id: number,
  data: {
    name?: string
    description?: string
    nodes?: Node[]
    edges?: Edge[]
  }
): Promise<Workflow & { needs_reactivate?: boolean }> {
  // needs_reactivate is set when the saved graph changed the trigger config of a
  // workflow that is currently active: the scheduler and monitors registered the
  // old configuration at activation time and will keep using it until the
  // workflow is deactivated and reactivated.
  const response = await webClient.put(`${FLOW_API_BASE}/workflows/${id}`, data)
  return response.data
}

/**
 * Delete a workflow
 */
export async function deleteWorkflow(id: number): Promise<{ status: string; message: string }> {
  const response = await webClient.delete(`${FLOW_API_BASE}/workflows/${id}`)
  return response.data
}

/**
 * Activate a workflow
 */
export async function activateWorkflow(id: number): Promise<{
  status: string
  message: string
  job_id?: string
  next_run?: string
}> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/activate`)
  return response.data
}

/**
 * Deactivate a workflow
 */
export async function deactivateWorkflow(id: number): Promise<{ status: string; message: string }> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/deactivate`)
  return response.data
}

/**
 * Execute a workflow manually
 */
export async function executeWorkflow(id: number): Promise<{
  status: string
  message: string
  execution_id?: number
  logs?: ExecutionLog[]
}> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/execute`)
  return response.data
}

/**
 * Get workflow execution history
 */
export async function getWorkflowExecutions(id: number, limit = 20): Promise<WorkflowExecution[]> {
  const response = await webClient.get(`${FLOW_API_BASE}/workflows/${id}/executions?limit=${limit}`)
  return response.data
}

/**
 * Get webhook configuration for a workflow
 */
export async function getWebhookInfo(id: number): Promise<WebhookInfo> {
  const response = await webClient.get(`${FLOW_API_BASE}/workflows/${id}/webhook`)
  return response.data
}

/**
 * Enable webhook for a workflow
 */
export async function enableWebhook(
  id: number
): Promise<WebhookInfo & { status: string; message: string }> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/webhook/enable`)
  return response.data
}

/**
 * Disable webhook for a workflow
 */
export async function disableWebhook(id: number): Promise<{ status: string; message: string }> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/webhook/disable`)
  return response.data
}

/**
 * Regenerate webhook token
 */
export async function regenerateWebhook(id: number): Promise<{
  status: string
  message: string
  webhook_token: string
  webhook_secret: string
  webhook_url: string
  webhook_url_with_symbol: string
}> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/webhook/regenerate`)
  return response.data
}

/**
 * Regenerate webhook secret only
 */
export async function regenerateWebhookSecret(id: number): Promise<{
  status: string
  message: string
  webhook_secret: string
}> {
  const response = await webClient.post(
    `${FLOW_API_BASE}/workflows/${id}/webhook/regenerate-secret`
  )
  return response.data
}

/**
 * Update webhook authentication type
 */
export async function updateWebhookAuthType(
  id: number,
  authType: 'payload' | 'url'
): Promise<{
  status: string
  message: string
  webhook_auth_type: 'payload' | 'url'
  webhook_url: string
  webhook_url_with_secret: string | null
}> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/webhook/auth-type`, {
    auth_type: authType,
  })
  return response.data
}

/**
 * Export workflow for sharing
 */
export async function exportWorkflow(id: number): Promise<WorkflowExportData> {
  const response = await webClient.get(`${FLOW_API_BASE}/workflows/${id}/export`)
  return response.data
}

/**
 * Import workflow from JSON
 * Backend returns { status, workflow_id } so we transform it to { id, name }
 */
export async function importWorkflow(
  data: WorkflowExportData
): Promise<{ id: number; name: string }> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/import`, data)
  return {
    id: response.data.workflow_id,
    name: data.name || 'Imported Workflow',
  }
}

/**
 * Replace an existing workflow's graph from JSON, in place.
 *
 * Import always creates a new workflow, which leaves a trail of copies and a
 * new webhook URL each time you iterate on a strategy as JSON. This keeps the
 * workflow's id, webhook token and active state and swaps only the graph.
 */
export interface ReplaceWorkflowResult {
  status: string
  workflow_id: number
  /** Legacy fields that were upgraded on the way in, if any. */
  migrations?: string[]
  /** True when the trigger changed on an active workflow, which needs a reactivate. */
  needs_reactivate?: boolean
  message?: string
}

export async function replaceWorkflow(
  id: number,
  data: WorkflowExportData
): Promise<ReplaceWorkflowResult> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/${id}/replace`, data)
  return response.data
}

// =============================================================================
// Index Symbols Types & API
// =============================================================================

export interface IndexSymbolInfo {
  value: string
  label: string
  exchange: string
  lotSize: number
}

/**
 * Get lot sizes for index symbols from master contract database
 * Returns dynamic lot sizes instead of hardcoded values
 */
export async function getIndexSymbolsLotSizes(): Promise<IndexSymbolInfo[]> {
  const response = await webClient.get(`${FLOW_API_BASE}/index-symbols`)
  return response.data.data || []
}

export interface SymbolRef {
  symbol: string
  exchange: string
}

/** Keyed `EXCHANGE:SYMBOL` -> lot size, null where the contract has none. */
export type LotSizeMap = Record<string, number | null>

interface SymbolLotSizesResponse {
  status: 'success'
  lotSizes: LotSizeMap
}

/**
 * Lot sizes for a bounded set of exact contracts, so derivative quantities can
 * be entered in lots. Batched because a margin basket holds up to 50 legs and
 * one request per leg is pure overhead.
 *
 * A pair resolves to null - not a rejection - when the master contract has no
 * usable lot size, letting the caller fall back to units. A rejected promise
 * means the lookup itself failed, which is a different state the caller must
 * not present as "no lot size".
 */
export async function getSymbolLotSizes(symbols: SymbolRef[]): Promise<LotSizeMap> {
  if (!symbols.length) return {}
  const response = await webClient.post<SymbolLotSizesResponse>(
    `${FLOW_API_BASE}/symbol-lotsizes`,
    { symbols }
  )
  const raw = response.data?.lotSizes
  if (!raw || typeof raw !== 'object') return {}
  // Guard the values rather than trusting the payload: a non-positive or
  // non-integer lot size would silently multiply a basket by a wrong factor.
  const clean: LotSizeMap = {}
  for (const [key, value] of Object.entries(raw)) {
    clean[key] = Number.isInteger(value) && (value as number) > 0 ? (value as number) : null
  }
  return clean
}

export interface ListedStrike {
  strike: number
  /** The contract this strike resolves to, e.g. GOLDM28AUG26163000CE. */
  symbol: string | null
  /** ATM / ITMn / OTMn. Differs per side at the same strike. */
  label: string | null
}

export interface OptionStrikesResponse {
  underlying: string
  exchange: string
  /** The expiry the strikes belong to, in DDMMMYY. */
  expiry: string
  /** Every listed expiry for this underlying, nearest first. */
  expiries: string[]
  /** What each relative expiry type resolves to right now, e.g.
   * `{ current_week: '28AUG26' }`. Resolved server-side with the selector the
   * executor uses, so the panel can name the contract a leg will trade. */
  resolved: Record<string, string | null>
  optionType: 'CE' | 'PE'
  strikes: ListedStrike[]
  /** Nearest listed strike to the underlying LTP, or null when the quote failed. */
  atm: number | null
  underlyingLtp: number | null
  /** What the ATM was priced against - the index, or the near-month future on
   * an exchange with no spot. */
  underlyingSymbol: string | null
}

/**
 * Listed expiries and strikes for one underlying, for the manual leg builder.
 *
 * A leg that names an absolute strike and its own expiry should pick contracts
 * the exchange actually lists, so the builder offers the master contract's own
 * list rather than a free number and a typed date. `atm` is a convenience
 * marker and may be null - a strike list is still usable when the underlying
 * quote fails.
 */
export async function getOptionStrikes(params: {
  underlying: string
  expiry?: string
  expiryType?: string
  optionType?: 'CE' | 'PE'
}): Promise<OptionStrikesResponse> {
  const response = await webClient.get(`${FLOW_API_BASE}/option-strikes`, { params })
  return response.data.data
}

// =============================================================================
// React Query Keys
// =============================================================================

export const flowQueryKeys = {
  all: ['flow'] as const,
  workflows: () => [...flowQueryKeys.all, 'workflows'] as const,
  workflow: (id: number) => [...flowQueryKeys.workflows(), id] as const,
  executions: (id: number) => [...flowQueryKeys.workflow(id), 'executions'] as const,
  webhook: (id: number) => [...flowQueryKeys.workflow(id), 'webhook'] as const,
  indexSymbols: () => [...flowQueryKeys.all, 'index-symbols'] as const,
  // Keyed on the exact triple the response describes, so switching expiry or
  // option type refetches instead of showing another expiry's strikes.
  optionStrikes: (underlying: string, expiry: string, optionType: string) =>
    [...flowQueryKeys.all, 'option-strikes', underlying, expiry, optionType] as const,
  // Keyed on the sorted pair list, so reopening an unchanged basket reuses its
  // entry. This key cannot give incremental reuse on its own - any change to
  // the set is a different key, and would re-request the whole basket - so the
  // caller keeps its own per-contract map and asks only for what is missing.
  symbolLotSizes: (keys: string[]) => [...flowQueryKeys.all, 'symbol-lotsizes', keys] as const,
}
