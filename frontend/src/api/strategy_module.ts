// api/strategy_module.ts
// Strategy module data layer: fetchers, query keys, the live-state hook, and
// the derivations that turn one endpoint's rows into another view's data.
//
// Base is `/strategy/api`, session-cookie authenticated. `webClient` carries the
// CSRF token on POST/PATCH/DELETE and rewrites an axios error's message to the
// server's own explanation, so callers read `error.message` and get the real
// reason rather than "Request failed with status code 409".
//
// Every response is `{status: "success", ...}` or `{status: "error", message}`.
// The fetchers below unwrap to the payload the caller actually wants, so no page
// repeats the envelope.

import { useQueries, useQuery } from '@tanstack/react-query'
import type {
  Checkpoint,
  LegState,
  Order,
  Run,
  RunMode,
  Strategy,
  StrategyConfigPayload,
  StrategyEvent,
  StrategyStatus,
  StrategySummary,
  StrategyUpdatePayload,
  WebhookEvent,
} from '@/types/strategy_module'
import { webClient } from './client'

const BASE = '/strategy/api'

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const strategyQueryKeys = {
  all: ['strategy-module'] as const,
  strategies: () => [...strategyQueryKeys.all, 'strategies'] as const,
  list: (filters: StrategyListFilters) => [...strategyQueryKeys.strategies(), filters] as const,
  strategy: (id: number) => [...strategyQueryKeys.strategies(), id] as const,
  runs: (id: number) => [...strategyQueryKeys.strategy(id), 'runs'] as const,
  orders: (id: number) => [...strategyQueryKeys.strategy(id), 'orders'] as const,
  events: (id: number) => [...strategyQueryKeys.strategy(id), 'events'] as const,
  webhookEvents: (id: number) => [...strategyQueryKeys.strategy(id), 'webhook-events'] as const,
  checkpoints: (id: number) => [...strategyQueryKeys.strategy(id), 'checkpoints'] as const,
}

/**
 * How often a running strategy's live view refreshes.
 *
 * The engine writes a checkpoint on its own cadence; 5s is the shortest poll
 * that is worth making against it. Nothing polls while a strategy is stopped:
 * its numbers cannot change until someone starts it.
 */
export const LIVE_POLL_MS = 5_000

/**
 * How often the supporting tables refresh while a run is active. Slower than
 * the live view because an order or an event is a discrete thing that appears
 * once, not a number that ticks.
 */
export const SAFETY_POLL_MS = 15_000

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

export interface StrategyListFilters {
  status?: StrategyStatus
  q?: string
}

export async function listStrategies(
  filters: StrategyListFilters = {}
): Promise<StrategySummary[]> {
  const response = await webClient.get<{ data: StrategySummary[] }>(`${BASE}/strategies`, {
    params: filters,
  })
  return response.data.data ?? []
}

export async function getStrategy(id: number): Promise<Strategy> {
  const response = await webClient.get<{ data: Strategy }>(`${BASE}/strategies/${id}`)
  return response.data.data
}

export interface CreatedStrategy {
  strategy: Strategy
  /** Shown once. The server stores only its digest and cannot show it again. */
  webhook_token: string
}

export async function createStrategy(payload: StrategyConfigPayload): Promise<CreatedStrategy> {
  const response = await webClient.post<{ data: Strategy; webhook_token: string }>(
    `${BASE}/strategies`,
    payload
  )
  return { strategy: response.data.data, webhook_token: response.data.webhook_token }
}

export async function updateStrategy(
  id: number,
  payload: StrategyUpdatePayload
): Promise<Strategy> {
  const response = await webClient.patch<{ data: Strategy }>(`${BASE}/strategies/${id}`, payload)
  return response.data.data
}

export async function deleteStrategy(id: number): Promise<void> {
  await webClient.delete(`${BASE}/strategies/${id}`)
}

export interface StartedRun {
  run_id: number
  mode: RunMode
  /** Per-leg outcome, so a caller can say which leg failed and why. */
  legs: Array<{
    leg_id?: number | null
    ok?: boolean
    symbol?: string
    exchange?: string
    status?: string
    error?: string | null
    broker_order_id?: string | null
  }>
}

export async function startRun(id: number, mode: RunMode): Promise<StartedRun> {
  const response = await webClient.post<StartedRun>(`${BASE}/strategies/${id}/start`, { mode })
  return response.data
}

export interface ExitOutcome {
  run_id: number
  exits: Array<Record<string, unknown>>
}

export async function stopRun(id: number): Promise<ExitOutcome> {
  const response = await webClient.post<ExitOutcome>(`${BASE}/strategies/${id}/stop`)
  return response.data
}

export async function closeAll(id: number): Promise<ExitOutcome> {
  const response = await webClient.post<ExitOutcome>(`${BASE}/strategies/${id}/close_all`)
  return response.data
}

export interface LegCloseOutcome extends ExitOutcome {
  leg_id: number | string
  /** True when that leg was the last one open and the run finalised with it. */
  run_stopped: boolean
}

export async function closeLeg(id: number, legId: number): Promise<LegCloseOutcome> {
  const response = await webClient.post<LegCloseOutcome>(
    `${BASE}/strategies/${id}/legs/${legId}/close`
  )
  return response.data
}

export async function rotateWebhookToken(id: number): Promise<string> {
  const response = await webClient.post<{ webhook_token: string }>(
    `${BASE}/strategies/${id}/webhook/rotate`
  )
  return response.data.webhook_token
}

export async function setLiveEnabled(id: number, enabled: boolean): Promise<boolean> {
  const response = await webClient.post<{ live_enabled: boolean }>(
    `${BASE}/strategies/${id}/live`,
    {
      enabled,
    }
  )
  return response.data.live_enabled
}

export interface KillSwitchOutcome {
  webhook_locked: boolean
  run_stopped: boolean
  message?: string
}

export async function killSwitch(id: number): Promise<KillSwitchOutcome> {
  const response = await webClient.post<KillSwitchOutcome>(`${BASE}/strategies/${id}/kill_switch`)
  return response.data
}

export async function unlockWebhook(id: number): Promise<void> {
  await webClient.post(`${BASE}/strategies/${id}/unlock_webhook`)
}

export async function listRuns(id: number): Promise<Run[]> {
  const response = await webClient.get<{ data: Run[] }>(`${BASE}/strategies/${id}/runs`)
  return response.data.data ?? []
}

export async function listOrders(id: number, runId?: number): Promise<Order[]> {
  const response = await webClient.get<{ data: Order[] }>(`${BASE}/strategies/${id}/orders`, {
    params: runId ? { run_id: runId } : {},
  })
  return response.data.data ?? []
}

export async function listEvents(id: number, limit = 500): Promise<StrategyEvent[]> {
  const response = await webClient.get<{ data: StrategyEvent[] }>(
    `${BASE}/strategies/${id}/events`,
    { params: { limit } }
  )
  return response.data.data ?? []
}

export async function listWebhookEvents(id: number): Promise<WebhookEvent[]> {
  const response = await webClient.get<{ data: WebhookEvent[] }>(
    `${BASE}/strategies/${id}/webhook_events`
  )
  return response.data.data ?? []
}

export interface CheckpointPage {
  /** Oldest first: the P&L curve of a session. */
  data: Checkpoint[]
  run_id: number | null
}

export async function listCheckpoints(id: number, runId?: number): Promise<CheckpointPage> {
  const response = await webClient.get<CheckpointPage>(`${BASE}/strategies/${id}/checkpoints`, {
    params: runId ? { run_id: runId } : {},
  })
  return { data: response.data.data ?? [], run_id: response.data.run_id ?? null }
}

// ---------------------------------------------------------------------------
// Live state
//
// The single seam between the pages and however live state arrives.
//
// Today it is a poll of the checkpoint the engine writes for the current run.
// When the module gets a push channel, this hook is the only thing that
// changes: it must keep returning a `StrategyLiveState`, and it must reach the
// socket through the app's shared `useSocketContext()` rather than opening one
// of its own. Every Socket.IO connection holds an HTTP connection against the
// browser's per-host limit, shared across every tab the user has open, so a
// second socket for this page would be spent from the same budget the order
// stream is already using.
// ---------------------------------------------------------------------------

export type StrategyLiveStatus = 'idle' | 'connecting' | 'live' | 'error'

export interface StrategyLiveState {
  /** Transport state, for the status badge on the Live tab. */
  status: StrategyLiveStatus
  /** The run these figures belong to: the current one, else the most recent. */
  runId: number | null
  /** The latest checkpoint, or null before the first one is written. */
  checkpoint: Checkpoint | null
  /** The latest checkpoint's legs, lowest leg id first. */
  legs: LegState[]
  /** When the latest checkpoint was written, as an ISO string. */
  updatedAt: string | null
  /** The whole curve, oldest first, for anything that wants the shape. */
  curve: Checkpoint[]
  isFetching: boolean
  error: Error | null
  refresh: () => void
}

/**
 * A strategy's live runtime state.
 *
 * Fetches once whatever the status, so a stopped strategy still shows the last
 * run's finalised P&L instead of an empty panel, and polls only while the run
 * is active.
 */
export function useStrategyLive(strategyId: number | null, isRunning: boolean): StrategyLiveState {
  const enabled = strategyId !== null && Number.isFinite(strategyId) && strategyId > 0

  const query = useQuery({
    queryKey: strategyQueryKeys.checkpoints(strategyId ?? 0),
    queryFn: () => listCheckpoints(strategyId as number),
    enabled,
    refetchInterval: isRunning ? LIVE_POLL_MS : false,
  })

  const page = query.data
  const checkpoint = page && page.data.length > 0 ? page.data[page.data.length - 1] : null

  let status: StrategyLiveStatus = 'idle'
  if (!enabled) {
    status = 'idle'
  } else if (query.isError) {
    status = 'error'
  } else if (isRunning) {
    status = query.isSuccess ? 'live' : 'connecting'
  }

  return {
    status,
    runId: page?.run_id ?? null,
    checkpoint,
    legs: checkpoint ? sortLegStates(checkpoint.leg_state) : [],
    updatedAt: checkpoint?.ts ?? null,
    curve: page?.data ?? [],
    isFetching: query.isFetching,
    error: (query.error as Error | null) ?? null,
    refresh: () => {
      void query.refetch()
    },
  }
}

function sortLegStates(legState: Record<string, LegState>): LegState[] {
  return Object.values(legState ?? {}).sort((a, b) => Number(a.leg_id) - Number(b.leg_id))
}

export interface StrategyPnl {
  realized: number
  unrealized: number
  total: number
}

/**
 * P&L for the list, one row at a time.
 *
 * The list endpoint carries configuration only, so the figures come from each
 * strategy's latest checkpoint: live for a running strategy, and the last run's
 * closing snapshot for a stopped one, which is exactly what the list claims to
 * show. Only running rows poll; a stopped row is fetched once and then sits in
 * the cache, so the fan-out costs one request per strategy on first paint and
 * nothing afterwards.
 *
 * A single summary endpoint would be cheaper, and this hook is where to delete
 * when one exists.
 */
export function useStrategyListPnl(rows: StrategySummary[]): Map<number, StrategyPnl> {
  const results = useQueries({
    queries: rows.map((row) => ({
      queryKey: strategyQueryKeys.checkpoints(row.id),
      queryFn: () => listCheckpoints(row.id),
      refetchInterval: row.status === 'running' ? (LIVE_POLL_MS as number | false) : false,
      staleTime: 30_000,
    })),
  })

  const byId = new Map<number, StrategyPnl>()
  rows.forEach((row, index) => {
    const page = results[index]?.data
    if (!page || page.data.length === 0) return
    const latest = page.data[page.data.length - 1]
    byId.set(row.id, {
      realized: latest.pnl_realized,
      unrealized: latest.pnl_unrealized,
      total: latest.pnl_total,
    })
  })
  return byId
}

// ---------------------------------------------------------------------------
// Derivations
//
// Positions and the tradebook have no endpoints of their own: both are views of
// the order history, and deriving them here keeps one definition of what a fill
// means rather than one per tab.
// ---------------------------------------------------------------------------

/** One completed entry-and-exit pair on a leg. */
export interface RoundTrip {
  run_id: number
  leg_id: number
  symbol: string
  exchange: string
  side: 'long' | 'short'
  qty: number
  entry_time: string
  entry_price: number
  exit_time: string
  exit_price: number
  exit_kind: string
  pnl: number
}

function isFilled(order: Order): boolean {
  if ((order.status || '').toLowerCase() !== 'complete') return false
  const qty = Number(order.filled_qty ?? order.qty ?? 0)
  const price = Number(order.avg_fill_price ?? 0)
  return qty > 0 && price > 0
}

function orderTime(order: Order): string {
  return order.filled_at ?? order.placed_at ?? ''
}

/**
 * Closed round-trips, newest first.
 *
 * Entries and exits are matched FIFO within a leg, and within a run: a leg that
 * enters and exits several times in one session produces one row per pair
 * rather than one row per leg. Scoping to the run as well as the leg keeps a
 * prior session's exit from being matched against today's entry.
 */
export function buildRoundTrips(orders: Order[]): RoundTrip[] {
  const byLeg = new Map<string, Order[]>()
  for (const order of orders) {
    if (!isFilled(order)) continue
    const key = `${order.run_id}:${order.leg_id}`
    const list = byLeg.get(key)
    if (list) list.push(order)
    else byLeg.set(key, [order])
  }

  const trips: RoundTrip[] = []
  for (const list of byLeg.values()) {
    list.sort((a, b) => orderTime(a).localeCompare(orderTime(b)))

    interface OpenLot {
      side: 'long' | 'short'
      qty: number
      entry: Order
    }
    const open: OpenLot[] = []

    for (const order of list) {
      const isEntry = order.kind === 'entry'
      const isExit = order.kind.startsWith('exit')
      const filled = Number(order.filled_qty ?? order.qty ?? 0)

      if (isEntry) {
        open.push({
          side: (order.action || '').toUpperCase() === 'BUY' ? 'long' : 'short',
          qty: filled,
          entry: order,
        })
        continue
      }
      if (!isExit) continue

      let remaining = filled
      while (remaining > 0 && open.length > 0) {
        const lot = open[0]
        const matched = Math.min(remaining, lot.qty)
        const entryPrice = Number(lot.entry.avg_fill_price ?? 0)
        const exitPrice = Number(order.avg_fill_price ?? 0)
        const sign = lot.side === 'long' ? 1 : -1
        trips.push({
          run_id: order.run_id,
          leg_id: order.leg_id,
          symbol: order.symbol,
          exchange: order.exchange,
          side: lot.side,
          qty: matched,
          entry_time: orderTime(lot.entry),
          entry_price: entryPrice,
          exit_time: orderTime(order),
          exit_price: exitPrice,
          exit_kind: order.kind,
          pnl: (exitPrice - entryPrice) * matched * sign,
        })
        lot.qty -= matched
        remaining -= matched
        if (lot.qty <= 0) open.shift()
      }
    }
  }

  trips.sort((a, b) => b.exit_time.localeCompare(a.exit_time))
  return trips
}

export interface DerivedPosition {
  symbol: string
  exchange: string
  product: string
  net_qty: number
  side: 'long' | 'short' | 'flat'
  avg_entry_price: number
  ltp: number | null
  unrealized_pnl: number
  /** Realized on this contract across every run of the strategy. */
  realized_pnl_lifetime: number
}

/**
 * Net positions per contract, derived from the fills.
 *
 * Lots are matched FIFO per contract rather than per leg, because that is what
 * a position is: two legs on the same strike net against each other in the
 * broker's book whatever the strategy calls them. What is left over after the
 * matching is the open position, and its average entry is the average of the
 * lots that are still open, not of every buy ever made.
 */
export function derivePositions(
  orders: Order[],
  product: string,
  legStates: LegState[] = []
): DerivedPosition[] {
  const liveByContract = new Map<string, LegState>()
  for (const leg of legStates) {
    const key = `${(leg.symbol ?? '').toUpperCase()}|${(leg.exchange ?? '').toUpperCase()}`
    if (leg.symbol && leg.exchange && leg.ltp != null) liveByContract.set(key, leg)
  }

  const byContract = new Map<string, Order[]>()
  for (const order of orders) {
    if (!isFilled(order)) continue
    const key = `${order.symbol}|${order.exchange}`
    const list = byContract.get(key)
    if (list) list.push(order)
    else byContract.set(key, [order])
  }

  const positions: DerivedPosition[] = []
  for (const [key, list] of byContract) {
    list.sort((a, b) => orderTime(a).localeCompare(orderTime(b)))
    const [symbol, exchange] = key.split('|')

    interface Lot {
      side: 1 | -1
      qty: number
      price: number
    }
    const open: Lot[] = []
    let realized = 0

    for (const order of list) {
      const side: 1 | -1 = (order.action || '').toUpperCase() === 'BUY' ? 1 : -1
      let remaining = Number(order.filled_qty ?? order.qty ?? 0)
      const price = Number(order.avg_fill_price ?? 0)

      while (remaining > 0 && open.length > 0 && open[0].side !== side) {
        const lot = open[0]
        const matched = Math.min(remaining, lot.qty)
        realized += (price - lot.price) * matched * lot.side
        lot.qty -= matched
        remaining -= matched
        if (lot.qty <= 0) open.shift()
      }
      if (remaining > 0) open.push({ side, qty: remaining, price })
    }

    const netQty = open.reduce((sum, lot) => sum + lot.qty * lot.side, 0)
    const grossQty = open.reduce((sum, lot) => sum + lot.qty, 0)
    const avgEntry =
      grossQty > 0 ? open.reduce((sum, lot) => sum + lot.qty * lot.price, 0) / grossQty : 0

    const live = liveByContract.get(`${symbol.toUpperCase()}|${exchange.toUpperCase()}`)
    const ltp = live?.ltp ?? null
    const unrealized =
      ltp != null && netQty !== 0 ? (ltp - avgEntry) * Math.abs(netQty) * (netQty > 0 ? 1 : -1) : 0

    positions.push({
      symbol,
      exchange,
      product,
      net_qty: netQty,
      side: netQty > 0 ? 'long' : netQty < 0 ? 'short' : 'flat',
      avg_entry_price: avgEntry,
      ltp,
      unrealized_pnl: unrealized,
      realized_pnl_lifetime: realized,
    })
  }

  positions.sort((a, b) => a.symbol.localeCompare(b.symbol))
  return positions
}

export interface DerivedTrade {
  order_id: number
  run_id: number
  leg_id: number
  kind: string
  symbol: string
  exchange: string
  action: string
  filled_qty: number
  avg_fill_price: number
  trade_value: number
  broker_order_id: string | null
  filled_at: string
}

/** Every fill this strategy produced, newest first. */
export function deriveTrades(orders: Order[]): DerivedTrade[] {
  return orders
    .filter(isFilled)
    .map((order) => {
      const qty = Number(order.filled_qty ?? order.qty ?? 0)
      const price = Number(order.avg_fill_price ?? 0)
      return {
        order_id: order.id,
        run_id: order.run_id,
        leg_id: order.leg_id,
        kind: order.kind,
        symbol: order.symbol,
        exchange: order.exchange,
        action: order.action,
        filled_qty: qty,
        avg_fill_price: price,
        trade_value: qty * price,
        broker_order_id: order.broker_order_id,
        filled_at: orderTime(order),
      }
    })
    .sort((a, b) => b.filled_at.localeCompare(a.filled_at))
}
