// API client for Strategy State endpoints

import type {
  StrategyState,
  StrategyStateResponse,
  OverrideType,
  StrategyOverrideResponse
} from '@/types/strategy-state'
import { webClient } from './client'

/**
 * Fetch all strategy execution states with positions and trade history
 */
export async function getStrategyStates(): Promise<StrategyState[]> {
  const response = await webClient.get<StrategyStateResponse>('/api/strategy-state')
  if (response.data.status === 'error') {
    throw new Error(response.data.message || 'Failed to fetch strategy states')
  }
  return response.data.data
}

/**
 * Fetch a specific strategy state by instance ID
 */
export async function getStrategyStateById(instanceId: string): Promise<StrategyState> {
  const response = await webClient.get<{ status: string; message?: string; data: StrategyState }>(
    `/api/strategy-state/${encodeURIComponent(instanceId)}`
  )
  if (response.data.status === 'error') {
    throw new Error(response.data.message || 'Failed to fetch strategy state')
  }
  return response.data.data
}

/**
 * Delete a strategy state by instance ID
 * Note: webClient interceptor automatically handles CSRF token
 */
export async function deleteStrategyState(instanceId: string): Promise<void> {
  const response = await webClient.delete<{ status: string; message?: string }>(
    `/api/strategy-state/${encodeURIComponent(instanceId)}`
  )
  if (response.data.status === 'error') {
    throw new Error(response.data.message || 'Failed to delete strategy state')
  }
}

/**
 * Create a strategy override for SL or Target price modification.
 * The running strategy will poll for and apply these overrides.
 */
export async function createStrategyOverride(
  instanceId: string,
  legKey: string,
  overrideType: OverrideType,
  newValue: number
): Promise<{ message: string }> {
  const response = await webClient.post<StrategyOverrideResponse>(
    `/api/strategy-state/${encodeURIComponent(instanceId)}/override`,
    {
      leg_key: legKey,
      override_type: overrideType,
      new_value: newValue
    }
  )
  if (response.data.status === 'error') {
    throw new Error(response.data.message || 'Failed to create strategy override')
  }
  return { message: response.data.message || 'Override created successfully' }
}

export interface ManualLegRequest {
  leg_key: string
  symbol: string
  exchange: string
  product: string
  quantity: number
  side: 'BUY' | 'SELL'
  entry_price?: number
  sl_percent?: number | null
  target_percent?: number | null
  leg_pair_name?: string | null
  is_main_leg: boolean
  reentry_limit?: number | null
  reexecute_limit?: number | null
  mode?: 'TRACK' | 'NEW'
  wait_trade_percent?: number | null
  wait_baseline_price?: number | null
}

export async function createManualStrategyLeg(
  instanceId: string,
  payload: ManualLegRequest
): Promise<{ message: string }> {
  const response = await webClient.post<{ status: string; message?: string }>(
    `/api/strategy-state/${encodeURIComponent(instanceId)}/manual-leg`,
    payload
  )
  if (response.data.status === 'error') {
    throw new Error(response.data.message || 'Failed to add manual position')
  }
  return { message: response.data.message || 'Manual position added successfully' }
}
