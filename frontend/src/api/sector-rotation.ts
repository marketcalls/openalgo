import { apiClient } from './client'

/** 'db' reads the local Historify store; 'api' asks the broker. */
export type PriceSource = 'db' | 'api'
export type RotationTimeframe = 'daily' | 'weekly'
export type Quadrant = 'leading' | 'weakening' | 'lagging' | 'improving'

export interface RotationInstrument {
  symbol: string
  exchange: string
  label: string
}

export interface RotationOptions {
  benchmarks: RotationInstrument[]
  timeframes: RotationTimeframe[]
  /** Exchanges a symbol on the map may come from: cash equity and indices. */
  exchanges: string[]
  max_instruments: number
  /** The default map: the NSE sector indices brokers commonly publish. */
  sectors: RotationInstrument[]
  /** Sector indices left off the default map; named like sectors when added from search. */
  optional_sectors: RotationInstrument[]
  max_tail: number
}

export interface RotationPoint {
  date: string
  rs_ratio: number
  rs_momentum: number
}

export interface RotationEntry extends RotationInstrument {
  quadrant: Quadrant
  rs_ratio: number
  rs_momentum: number
  /** Consecutive bars, ending with the latest, spent in the current quadrant. */
  bars_in_quadrant: number
  /** Oldest first, ending with the latest bar. Trimmed by the page to the tail slider. */
  tail: RotationPoint[]
}

export interface RotationResult {
  benchmark: string
  benchmark_exchange: string
  benchmark_label: string
  timeframe: RotationTimeframe
  source: PriceSource
  as_of: string | null
  max_tail: number
  instruments: RotationEntry[]
  /** Symbols that could not be placed, each with a reason a trader can act on. */
  unavailable: (RotationInstrument & { reason: string })[]
}

export interface RotationRequest {
  apikey: string
  benchmark: string
  timeframe: RotationTimeframe
  source: PriceSource
  /** The symbols to place. Empty means the default sector set. */
  instruments: RotationInstrument[]
}

export async function getRotationOptions(): Promise<RotationOptions> {
  const { data } = await apiClient.get<{ data: RotationOptions }>('/sectorrotation/options')
  return data.data
}

export async function getSectorRotation(request: RotationRequest): Promise<RotationResult> {
  const { data } = await apiClient.post<{ data: RotationResult }>('/sectorrotation', request)
  return data.data
}
