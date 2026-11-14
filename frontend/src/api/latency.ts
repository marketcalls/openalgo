// The latency monitor at /logs/latency.
//
// Every /api/v1 call is timed. The monitor reports them one group of endpoints
// at a time (orders, account and books, market data and so on), because one
// average across an order and a history download describes neither.
//
// The groups, their names and which endpoint is in which are decided on the
// server (database/latency_groups.py) and arrive with the figures. Nothing
// here keeps a list of them.

import { webClient } from './client'

/** The group the page opens on, and the one the server answers for by default. */
export const DEFAULT_LATENCY_GROUP = 'orders'

/** One group in the selector, with how many calls it holds. */
export interface LatencyGroup {
  key: string
  label: string
  description: string
  count: number
  /** Whether the Excellent to Slow scale applies. Only orders are rated. */
  rated: boolean
}

/** The figures every row of a table shares. */
export interface LatencyFigures {
  /** How many calls. The name is from when only orders were recorded. */
  total_orders: number
  failed_orders: number
  success_rate: number
  /** Time spent waiting on the broker. */
  avg_rtt: number
  /** Time spent inside OpenAlgo. */
  avg_overhead: number
  avg_total: number
  p50_total: number
  p99_total: number
}

/** One endpoint of the group. */
export interface LatencyEndpoint extends LatencyFigures {
  /** The tag the call is stored under, such as PLACE or HISTORY. */
  type: string | null
  label: string
}

export interface LatencyBroker extends LatencyFigures {
  /** Share of calls under 150 ms. */
  sla_150ms: number
}

export interface LatencyDistribution {
  excellent: number
  good: number
  acceptable: number
  slow: number
}

export interface LatencyStats extends LatencyFigures {
  group: string
  groups: LatencyGroup[]
  label: string
  description: string
  rated: boolean
  /** Days a record is kept, or null when it is kept forever. */
  retention_days: number | null
  /** Percentiles cover this many days; counts and averages cover everything. */
  percentile_window_days: number
  p90_total: number
  p95_total: number
  sla_100ms: number
  sla_150ms: number
  sla_200ms: number
  distribution: LatencyDistribution
  endpoints: LatencyEndpoint[]
  broker_stats: Record<string, LatencyBroker>
}

export interface LatencyLog {
  id: number
  timestamp: string
  order_id: string
  broker: string | null
  symbol: string | null
  order_type: string | null
  /** The endpoint's name, such as "Place order". */
  endpoint: string
  group: string
  rtt_ms: number
  validation_latency_ms: number
  response_latency_ms: number
  overhead_ms: number
  total_latency_ms: number
  status: string
  error: string | null
}

/** Query keys, so a refresh reaches the figures and the records together. */
export const latencyKeys = {
  all: ['latency'] as const,
  stats: (group: string) => ['latency', 'stats', group] as const,
  logs: (group: string) => ['latency', 'logs', group] as const,
}

/**
 * The figures as the page reads them, whatever the server left out.
 *
 * The page files are replaced the moment an update is pulled, and the server
 * only changes when it restarts. In between, this page talks to a server that
 * knows nothing of groups and answers with the old figures alone. Those are
 * shown as they come, with no selector, and the page works; without this it
 * would fail on the first list it expected.
 */
function completeStats(group: string, raw: Partial<LatencyStats> | null | undefined): LatencyStats {
  const stats = raw ?? {}
  return {
    total_orders: 0,
    failed_orders: 0,
    success_rate: 0,
    avg_rtt: 0,
    avg_overhead: 0,
    avg_total: 0,
    p50_total: 0,
    p90_total: 0,
    p95_total: 0,
    p99_total: 0,
    sla_100ms: 0,
    sla_150ms: 0,
    sla_200ms: 0,
    label: 'Orders',
    description: '',
    retention_days: null,
    percentile_window_days: 30,
    ...stats,
    group: stats.group ?? group,
    rated: stats.rated ?? true,
    groups: stats.groups ?? [],
    endpoints: stats.endpoints ?? [],
    broker_stats: stats.broker_stats ?? {},
    distribution: stats.distribution ?? { excellent: 0, good: 0, acceptable: 0, slow: 0 },
  }
}

export const latencyApi = {
  stats: async (group: string): Promise<LatencyStats> => {
    const response = await webClient.get<Partial<LatencyStats>>('/latency/api/stats', {
      params: { group },
    })
    return completeStats(group, response.data)
  },

  logs: async (group: string): Promise<LatencyLog[]> => {
    const response = await webClient.get<LatencyLog[]>('/latency/api/logs', { params: { group } })
    const logs = Array.isArray(response.data) ? response.data : []
    // An older server names neither the endpoint nor its group.
    return logs.map((log) => ({
      ...log,
      endpoint: log.endpoint ?? log.order_type ?? 'Unknown',
      group: log.group ?? group,
    }))
  },

  /** Where the CSV of one group is downloaded from. */
  exportUrl: (group: string): string => `/latency/export?group=${encodeURIComponent(group)}`,
}
