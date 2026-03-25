/**
 * Expired F&O API Client
 * Provides access to expired options and futures historical data via Upstox.
 */

import { webClient } from './client'

export interface ExpiredFnoCapability {
  supported: boolean
  broker: string | null
  note: string | null
  supported_underlyings: string[]
  supports_custom_underlying?: boolean
}

export interface ExpiredExpiry {
  id: number
  upstox_key: string
  openalgo_symbol: string
  exchange: string
  expiry_date: string
  is_weekly: boolean
  contracts_fetched: boolean
  data_fetched: boolean
  fetched_at: string | null
  total_contracts?: number
  downloaded_contracts?: number
}

export interface ExpiredContract {
  expired_instrument_key: string
  upstox_key: string
  openalgo_symbol: string
  exchange: string
  expiry_date: string
  contract_type: 'CE' | 'PE' | 'FUT'
  strike_price: number | null
  trading_symbol: string
  lot_size: number | null
  data_fetched: boolean
  candle_count: number
  created_at: string
}

export interface ExpiredFnoJob {
  id: string
  underlying: string
  exchange: string
  expiry_date: string | null
  contract_types: string
  interval: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_contracts: number
  completed_contracts: number
  failed_contracts: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  error_message: string | null
}

export interface ExpiredFnoStats {
  total_expiries: number
  total_contracts: number
  downloaded_contracts: number
  total_candles: number
}

/** Check if the user's active broker supports expired F&O data. */
export async function getExpiredFnoCapability(): Promise<ExpiredFnoCapability> {
  const response = await webClient.get<{ status: string } & ExpiredFnoCapability>(
    '/historify/api/expired/capability'
  )
  return response.data
}

/** Phase 1: Fetch and cache expiry dates from Upstox for an underlying. */
export async function fetchExpiries(
  underlying: string
): Promise<{ expiry_count: number; expiries: string[] }> {
  const response = await webClient.post<{
    status: string
    underlying: string
    expiry_count: number
    expiries: string[]
  }>('/historify/api/expired/expiries', { underlying })
  return response.data
}

/** Get cached expiry dates for an underlying from DuckDB. */
export async function getExpiries(
  underlying: string
): Promise<{ expiries: ExpiredExpiry[]; count: number }> {
  const response = await webClient.get<{
    status: string
    expiries: ExpiredExpiry[]
    count: number
  }>('/historify/api/expired/expiries', { params: { underlying } })
  return response.data
}

/** Phase 2: Fetch and cache contracts for one or more expiries from Upstox. */
export async function fetchContracts(
  underlying: string,
  expiry_dates: string[],
  contract_types: string[]
): Promise<{ contract_count: number }> {
  const response = await webClient.post<{
    status: string
    contract_count: number
  }>('/historify/api/expired/contracts', { underlying, expiry_dates, contract_types })
  return response.data
}

/** Get cached contracts for an underlying + one or more expiries from DuckDB. */
export async function getContracts(
  underlying: string,
  expiry_dates: string[]
): Promise<{ contracts: ExpiredContract[]; count: number }> {
  const response = await webClient.get<{
    status: string
    contracts: ExpiredContract[]
    count: number
  }>('/historify/api/expired/contracts', {
    params: { underlying, expiry_dates: expiry_dates.join(',') },
  })
  return response.data
}

export type LookBack = '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y'

/** Phase 3: Start a background download job for expired F&O contracts. */
export async function startDownloadJob(
  underlying: string,
  expiry_dates: string[] | null,
  contract_types: string[],
  look_back: LookBack = '6M',
  incremental: boolean = true
): Promise<{ job_id: string; total_contracts: number }> {
  const response = await webClient.post<{
    status: string
    job_id: string
    total_contracts: number
  }>('/historify/api/expired/jobs', {
    underlying,
    expiry_dates,
    contract_types,
    look_back,
    incremental,
  })
  return response.data
}

/** Get status and progress of an expired F&O download job. */
export async function getJobStatus(jobId: string): Promise<{ job: ExpiredFnoJob; percent: number }> {
  const response = await webClient.get<{
    status: string
    job: ExpiredFnoJob
    percent: number
  }>(`/historify/api/expired/jobs/${jobId}`)
  return response.data
}

/** Request cancellation of a running expired F&O download job. */
export async function cancelJob(jobId: string): Promise<void> {
  await webClient.post(`/historify/api/expired/jobs/${jobId}/cancel`)
}

export interface BrokerCapabilities {
  futures_historical: 'full' | 'limited' | 'none'
  options_historical: 'full' | 'limited' | 'none'
  expired_contracts: 'full' | 'limited' | 'none'
}

export interface BrokerCapabilityRow {
  broker: string
  capabilities: BrokerCapabilities
}

/** Get historify capability matrix for all supported brokers. */
export async function getBrokerCapabilities(): Promise<BrokerCapabilityRow[]> {
  const response = await webClient.get<{ status: string; brokers: BrokerCapabilityRow[] }>(
    '/historify/api/broker/capabilities'
  )
  return response.data.brokers
}

/** List recent expired F&O download jobs. */
export async function listExpiredFnoJobs(
  status?: string,
  limit = 20
): Promise<{ jobs: ExpiredFnoJob[]; count: number }> {
  const response = await webClient.get<{
    status: string
    jobs: ExpiredFnoJob[]
    count: number
  }>('/historify/api/expired/jobs', {
    params: { ...(status ? { status } : {}), limit },
  })
  return response.data
}

/** Get summary statistics for all expired F&O data stored in DuckDB. */
export async function getExpiredFnoStats(): Promise<ExpiredFnoStats> {
  const response = await webClient.get<{ status: string; data: ExpiredFnoStats }>(
    '/historify/api/expired/stats'
  )
  return response.data.data
}
