// api/flow.ts
// Flow Workflow API module

import { webClient } from './client'
import type { Node, Edge } from '@xyflow/react'

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
): Promise<Workflow> {
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
export async function deactivateWorkflow(
  id: number
): Promise<{ status: string; message: string }> {
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
export async function getWorkflowExecutions(
  id: number,
  limit = 20
): Promise<WorkflowExecution[]> {
  const response = await webClient.get(
    `${FLOW_API_BASE}/workflows/${id}/executions?limit=${limit}`
  )
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
export async function enableWebhook(id: number): Promise<WebhookInfo & { status: string; message: string }> {
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
export async function importWorkflow(data: WorkflowExportData): Promise<{ id: number; name: string }> {
  const response = await webClient.post(`${FLOW_API_BASE}/workflows/import`, data)
  return {
    id: response.data.workflow_id,
    name: data.name || 'Imported Workflow'
  }
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
}
