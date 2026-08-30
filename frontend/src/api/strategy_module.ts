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

import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { normalizeExpiryCode } from '@/lib/strategyContracts'
import { useAuthStore } from '@/stores/authStore'
import type {
  Checkpoint,
  LegPosition,
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
import { derivativeExchangeFor, type ExpiryRank, resolveExpiryRank } from '@/types/strategy_module'
import { apiClient, webClient } from './client'
import { optionChainApi } from './option-chain'

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
  // The broker's own books, narrowed to this strategy. Keyed separately from
  // the local order rows because they answer a different question: what the
  // broker says happened, rather than what the engine asked for.
  brokerBook: (id: number, book: string) =>
    [...strategyQueryKeys.strategy(id), 'broker-book', book] as const,
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
 * How long a joined socket may stay silent before the REST fallback resumes.
 *
 * The engine pushes a delta on every tick it evaluates and a checkpoint every
 * few seconds, so a run that is alive has no reason to be quiet for this long.
 * A socket that is connected and silent is the failure this whole fallback
 * exists for, and treating the first frame as proof of life forever is how the
 * page ends up showing a stopped clock while claiming to be live.
 */
export const SOCKET_STALE_MS = 20_000

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

/**
 * The broker's own view of one strategy, for the books tabs.
 *
 * `rows` is the broker's answer when it gave one and null when it did not, so
 * a page can say which it is showing rather than quietly presenting derived
 * numbers as the broker's. Polls only while the run is live, on the same
 * cadence as everything else on the page.
 */
export function useBrokerBook<T>(
  strategyId: number | null,
  book: 'orderbook' | 'tradebook' | 'positions',
  fetcher: (id: number, runId?: number) => Promise<T | null>,
  isRunning: boolean
) {
  const query = useQuery({
    queryKey: strategyQueryKeys.brokerBook(strategyId ?? 0, book),
    queryFn: () => fetcher(strategyId as number),
    enabled: strategyId !== null,
    refetchInterval: strategyId !== null && isRunning ? LIVE_POLL_MS : false,
  })
  return {
    rows: query.data ?? null,
    isLoading: query.isLoading,
    // A null payload is the broker refusing, which the fetcher already turned
    // into a value rather than a throw.
    unavailable: !query.isLoading && query.data === null,
  }
}

/**
 * The three broker-backed books.
 *
 * These read the broker's own orderbook, tradebook and position book and
 * narrow them to this strategy, rather than deriving from the order rows the
 * engine wrote. The rows record what was asked for; the broker knows what
 * happened to it, and for money that difference is the whole point: a fill or
 * a cancellation whose update never arrived leaves the local rows wrong.
 *
 * Each returns null rather than throwing when the broker refuses, so the page
 * can fall back to the derived view and say which one it is showing. One
 * failing tab must not take out the detail page.
 */
export interface BrokerOrderbook {
  orders: Record<string, unknown>[]
  statistics: Record<string, unknown> | null
}

async function readBook<T>(
  id: number,
  path: string,
  runId: number | undefined,
  pick: (payload: Record<string, unknown>) => T
): Promise<T | null> {
  try {
    const response = await webClient.get<Record<string, unknown>>(
      `${BASE}/strategies/${id}/${path}`,
      { params: runId ? { run_id: runId } : {} }
    )
    if (response.data?.status !== 'success') return null
    return pick(response.data)
  } catch {
    return null
  }
}

export function fetchStrategyOrderbook(
  id: number,
  runId?: number
): Promise<BrokerOrderbook | null> {
  return readBook(id, 'orderbook', runId, (payload) => {
    const data = (payload.data ?? {}) as Record<string, unknown>
    return {
      orders: Array.isArray(data.orders) ? (data.orders as Record<string, unknown>[]) : [],
      statistics: (data.statistics ?? null) as Record<string, unknown> | null,
    }
  })
}

export function fetchStrategyTradebook(
  id: number,
  runId?: number
): Promise<Record<string, unknown>[] | null> {
  return readBook(id, 'tradebook', runId, (payload) =>
    Array.isArray(payload.data) ? (payload.data as Record<string, unknown>[]) : []
  )
}

export function fetchStrategyPositions(
  id: number,
  runId?: number
): Promise<Record<string, unknown>[] | null> {
  return readBook(id, 'positions', runId, (payload) =>
    Array.isArray(payload.data) ? (payload.data as Record<string, unknown>[]) : []
  )
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
// The transport is the strategy room on the app's shared Socket.IO connection,
// with the checkpoint poll kept underneath it as a fallback. It reaches the
// socket through `useSocketContext()` rather than opening one of its own:
// every Socket.IO connection holds an HTTP connection against the browser's
// roughly six-per-host limit, shared across every tab the user has open, so a
// second socket here would be spent from the same budget the account-level
// order stream is already using.
//
// The fallback is not a leftover. A socket that has dropped looks exactly like
// a strategy whose numbers have stopped moving, and a page that quietly shows
// stale P&L is worse than one that polls, so the poll runs whenever the socket
// is not delivering and the badge says which of the two is feeding the page.
// ---------------------------------------------------------------------------

/**
 * Where the numbers on screen are coming from.
 *
 * `polling` is a real answer, not a degraded one: the REST fallback is
 * authoritative, just slower. It is distinct from `live` so the badge can say
 * which is running rather than implying a push channel that is not there.
 */
export type StrategyLiveStatus = 'idle' | 'connecting' | 'live' | 'polling' | 'error'

/** The envelope every strategy frame carries. */
interface StrategyFrameEnvelope {
  strategy_id: number
  run_id: number | null
  /** IST ISO 8601 with the offset, for display. */
  ts: string
  /** Epoch ms, for ordering. */
  ts_ms: number
}

/** One leg as the socket sends it. Non-finite numbers arrive as null. */
export interface StrategyWireLeg {
  leg_id: number
  symbol: string
  exchange: string
  position: LegPosition
  lots: number
  qty: number
  status: string
  entry_status: string
  exit_kind: string | null
  ltp: number | null
  entry_avg: number
  mtm: number
  realized_pnl: number
  effective_sl: number | null
  effective_target: number | null
  trail_active: boolean
  favorable_points: number
  tick_source: string
}

/** A `strategy_snapshot` or `strategy_delta` frame. */
export interface StrategyStateFrame extends StrategyFrameEnvelope {
  type: 'snapshot' | 'delta'
  mtm_realized: number
  mtm_unrealized: number
  mtm_total: number
  peak: number
  trough: number
  lock_armed: boolean
  lock_floor: number | null
  trail_to_entry_active: boolean
  tick_source_degraded: boolean
  legs: StrategyWireLeg[]
}

interface StrategyEventFrame extends StrategyFrameEnvelope {
  type: 'event'
  event: StrategyEvent
}

interface StrategyOrderFrame extends StrategyFrameEnvelope {
  type: 'order_update'
  order: Order
}

interface StrategyRunFrame extends StrategyFrameEnvelope {
  type: 'run_update'
  run: Run
}

interface StrategyTerminalFrame extends StrategyFrameEnvelope {
  type: 'terminal'
  stop_reason: string | null
  pnl_realized: number
}

interface SubscribeAck {
  status: 'success' | 'error'
  message?: string
}

/** One wire leg in the shape the pages already read. */
export function wireLegToLegState(leg: StrategyWireLeg): LegState {
  return {
    leg_id: leg.leg_id,
    position: leg.position,
    symbol: leg.symbol,
    exchange: leg.exchange,
    lots: leg.lots,
    qty: leg.qty,
    entry_order_id: null,
    entry_status: leg.entry_status,
    entry_avg: leg.entry_avg,
    exit_order_id: null,
    exit_kind: leg.exit_kind,
    exit_avg: null,
    ltp: leg.ltp,
    mtm: leg.mtm,
    realized_pnl: leg.realized_pnl,
    status: leg.status,
    tick_source: leg.tick_source,
    sl_pts: null,
    target_pts: null,
    trail_x: 0,
    trail_y: 0,
    effective_sl: leg.effective_sl,
    effective_target: leg.effective_target,
    trail_active: leg.trail_active,
    // The socket sends the favourable excursion already measured, so the price
    // ratchet it was derived from is not repeated on the wire.
    favorable_points: leg.favorable_points,
    highest_price: null,
    lowest_price: null,
  }
}

/**
 * Fold a state frame into what is already on screen.
 *
 * A snapshot carries every leg and replaces the map. A delta carries only the
 * open ones, so it is merged: a leg that is not open cannot have moved, and
 * dropping it would blank a closed leg's final numbers on the next tick.
 */
export function foldStrategyFrame(
  previous: Checkpoint | null,
  frame: StrategyStateFrame
): Checkpoint {
  const incoming: Record<string, LegState> = {}
  for (const leg of frame.legs ?? []) {
    incoming[String(leg.leg_id)] = wireLegToLegState(leg)
  }
  const legState =
    frame.type === 'snapshot' ? incoming : { ...(previous?.leg_state ?? {}), ...incoming }

  return {
    // Synthetic: a frame is not a checkpoint row and has no id of its own.
    id: 0,
    run_id: frame.run_id ?? previous?.run_id ?? 0,
    ts: frame.ts,
    pnl_realized: frame.mtm_realized,
    pnl_unrealized: frame.mtm_unrealized,
    pnl_total: frame.mtm_total,
    pnl_peak: frame.peak,
    pnl_trough: frame.trough,
    lock_floor: frame.lock_floor ?? null,
    trail_to_entry_active: Boolean(frame.trail_to_entry_active),
    leg_state: legState,
  }
}

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
 * Joins the strategy's room while the run is active and folds the frames it
 * receives; falls back to the checkpoint poll whenever the socket is not
 * delivering. The REST read also runs once whatever the status, so a stopped
 * strategy still shows the last run's finalised P&L instead of an empty panel.
 */
export function useStrategyLive(strategyId: number | null, isRunning: boolean): StrategyLiveState {
  const enabled = strategyId !== null && Number.isFinite(strategyId) && strategyId > 0
  const queryClient = useQueryClient()
  const { socket } = useSocketContext()

  const [connected, setConnected] = useState(false)
  const [joined, setJoined] = useState(false)
  const [joinError, setJoinError] = useState<string | null>(null)
  const [frame, setFrame] = useState<Checkpoint | null>(null)
  // When the last accepted frame arrived, and a clock that advances so the
  // staleness check is re-evaluated rather than only recomputed on a render
  // that happens to occur.
  const [lastFrameAt, setLastFrameAt] = useState<number | null>(null)
  const [clock, setClock] = useState(() => Date.now())
  // Frames are ordered by the server clock, so a delivery that arrives out of
  // order is dropped rather than winding the numbers backwards.
  const lastTsRef = useRef(0)

  const wantSocket = enabled && isRunning && socket != null

  // Connection state, tracked separately from the room so a drop shows up as a
  // transport change even before the rejoin is attempted.
  useEffect(() => {
    if (!socket) {
      setConnected(false)
      return
    }
    setConnected(socket.connected)
    const onConnect = () => setConnected(true)
    const onDisconnect = () => {
      setConnected(false)
      setJoined(false)
    }
    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    return () => {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
    }
  }, [socket])

  // Room membership and the frame handlers. Keyed on the strategy id, so
  // navigating to another strategy leaves the old room on the way out rather
  // than accumulating memberships on the shared connection.
  useEffect(() => {
    if (!wantSocket || !socket || strategyId === null) return

    let active = true
    setJoined(false)
    setJoinError(null)
    setFrame(null)
    setLastFrameAt(null)
    lastTsRef.current = 0

    const mine = (payload: { strategy_id?: number } | null | undefined) =>
      Boolean(payload) && payload?.strategy_id === strategyId

    const join = () => {
      socket.emit('strategy_subscribe', { strategy_id: strategyId }, (ack?: SubscribeAck) => {
        if (!active) return
        if (ack?.status === 'success') {
          setJoined(true)
          setJoinError(null)
        } else {
          // A strategy that is not yours acknowledges an error rather than
          // joining, so this is a real answer, not a timeout.
          setJoined(false)
          setJoinError(ack?.message ?? 'Could not subscribe to this strategy')
        }
      })
    }

    const onState = (payload: StrategyStateFrame) => {
      if (!mine(payload)) return
      const ts = Number(payload.ts_ms ?? 0)
      if (ts && ts < lastTsRef.current) return
      lastTsRef.current = ts
      setLastFrameAt(Date.now())
      setFrame((previous) => foldStrategyFrame(previous, payload))
    }

    const onOrder = (payload: StrategyOrderFrame) => {
      if (!mine(payload) || !payload.order) return
      queryClient.setQueryData<Order[]>(strategyQueryKeys.orders(strategyId), (previous) => {
        const list = previous ? [...previous] : []
        const index = list.findIndex((row) => row.id === payload.order.id)
        if (index >= 0) list[index] = payload.order
        else list.unshift(payload.order)
        return list
      })
      // Positions and the tradebook are derived from this same array inside the
      // Detail page, so splicing it is what refreshes them. There is no second
      // cache to invalidate.
    }

    const onRun = (payload: StrategyRunFrame) => {
      if (!mine(payload) || !payload.run) return
      queryClient.setQueryData<Run[]>(strategyQueryKeys.runs(strategyId), (previous) => {
        const list = previous ? [...previous] : []
        const index = list.findIndex((row) => row.id === payload.run.id)
        if (index >= 0) list[index] = payload.run
        else list.unshift(payload.run)
        return list
      })
    }

    const onEvent = (payload: StrategyEventFrame) => {
      if (!mine(payload) || !payload.event) return
      queryClient.setQueryData<StrategyEvent[]>(
        strategyQueryKeys.events(strategyId),
        (previous) => {
          const list = previous ? [...previous] : []
          if (list.some((row) => row.id === payload.event.id)) return list
          return [payload.event, ...list]
        }
      )
    }

    const onTerminal = (payload: StrategyTerminalFrame) => {
      if (!mine(payload)) return
      // The run is over. Drop the live frame so the page stops presenting it as
      // current, and refetch the rows that now carry the finalised numbers.
      setFrame(null)
      setLastFrameAt(null)
      lastTsRef.current = 0
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.strategy(strategyId) })
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.runs(strategyId) })
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.checkpoints(strategyId) })
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.orders(strategyId) })
    }

    if (socket.connected) join()
    // Rejoin after a reconnect: the server does not remember the room.
    socket.on('connect', join)
    socket.on('strategy_snapshot', onState)
    socket.on('strategy_delta', onState)
    socket.on('strategy_event', onEvent)
    socket.on('strategy_order_update', onOrder)
    socket.on('strategy_run_update', onRun)
    socket.on('strategy_terminal', onTerminal)

    return () => {
      active = false
      socket.off('connect', join)
      socket.off('strategy_snapshot', onState)
      socket.off('strategy_delta', onState)
      socket.off('strategy_event', onEvent)
      socket.off('strategy_order_update', onOrder)
      socket.off('strategy_run_update', onRun)
      socket.off('strategy_terminal', onTerminal)
      // Never disconnect the shared socket - only leave this room.
      if (socket.connected) {
        socket.emit('strategy_unsubscribe', { strategy_id: strategyId })
      }
      setJoined(false)
    }
  }, [wantSocket, socket, strategyId, queryClient])

  // Advance the clock only while a socket is in play, so a page with no
  // subscription does no timer work at all.
  useEffect(() => {
    if (!wantSocket) return
    const id = window.setInterval(() => setClock(Date.now()), LIVE_POLL_MS)
    return () => window.clearInterval(id)
  }, [wantSocket])

  // Live means frames are arriving, not that one arrived once. Without the
  // recency test this stayed true for the life of the page after the first
  // frame, so a socket that fell silent left the poll disabled and the page
  // showed indefinitely stale P&L, legs and run state while reporting itself
  // live.
  const socketLive =
    wantSocket &&
    connected &&
    joined &&
    frame !== null &&
    lastFrameAt !== null &&
    clock - lastFrameAt < SOCKET_STALE_MS

  const query = useQuery({
    queryKey: strategyQueryKeys.checkpoints(strategyId ?? 0),
    queryFn: () => listCheckpoints(strategyId as number),
    enabled,
    // The poll stands down only while frames are actually arriving. A socket
    // that is connected but silent still gets the fallback underneath it.
    refetchInterval: enabled && isRunning && !socketLive ? LIVE_POLL_MS : false,
  })

  const page = query.data
  const restCheckpoint = page && page.data.length > 0 ? page.data[page.data.length - 1] : null
  // The socket frame wins only while the socket is live. Once it has gone
  // stale the REST fallback is the fresher of the two, and preferring the
  // frame regardless meant resuming the poll changed nothing an operator could
  // see: the page kept rendering the last frame it received before the silence
  // while quietly fetching newer numbers it never showed. The frame is still
  // the fallback's fallback, for the moment before the first REST answer.
  const checkpoint = socketLive ? (frame ?? restCheckpoint) : (restCheckpoint ?? frame)

  let status: StrategyLiveStatus = 'idle'
  if (!enabled) {
    status = 'idle'
  } else if (joinError) {
    status = 'error'
  } else if (socketLive) {
    status = 'live'
  } else if (wantSocket && connected && frame === null) {
    // Connected and waiting for the first frame. Once one has arrived and then
    // gone stale this must not read as "connecting" again: the connection is
    // fine, it is the delivery that stopped, and the page is on the fallback.
    status = 'connecting'
  } else if (isRunning) {
    status = query.isError ? 'error' : 'polling'
  } else if (query.isError) {
    status = 'error'
  }

  const refresh = useCallback(() => {
    void query.refetch()
  }, [query])

  return {
    status,
    // Follows the same precedence as `checkpoint` above, and for the same
    // reason. Preferring the frame's run id unconditionally meant a stale
    // socket could label freshly polled state with the run that had already
    // ended, so the page attributed one run's numbers to another.
    runId: socketLive
      ? (frame?.run_id ?? page?.run_id ?? null)
      : (page?.run_id ?? frame?.run_id ?? null),
    checkpoint,
    legs: checkpoint ? sortLegStates(checkpoint.leg_state) : [],
    updatedAt: checkpoint?.ts ?? null,
    // History only ever comes from REST: the socket carries the current state,
    // not the curve behind it.
    curve: page?.data ?? [],
    isFetching: query.isFetching,
    error: joinError ? new Error(joinError) : ((query.error as Error | null) ?? null),
    refresh,
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

// ---------------------------------------------------------------------------
// Contract resolution
//
// A leg stores an expiry rank, and when its strike is named directly it stores
// a number. Neither can be checked without asking the platform what is actually
// listed, so the wizard resolves both against the endpoints the option chain
// and the strategy builder already use: POST /api/v1/expiry for the dates and
// POST /api/v1/optionchain for the strikes. Both are /api/v1 routes carrying
// the user's API key in the body, which is why they go through `apiClient` and
// `optionChainApi` rather than the session-cookie `webClient` above.
//
// The two endpoints disagree about which exchange they are keyed on, and both
// are right: expiries live on the derivative exchange (NIFTY's options are in
// NFO), while the chain is keyed on the underlying's own exchange (NSE_INDEX).
// `derivativeExchangeFor` is the only place that difference is spelled out.
//
// Every hook here reports a failure instead of an empty list. "Nothing is
// listed" and "the master contract was never downloaded" look identical in an
// empty dropdown, and only one of them is something the user can fix.
// ---------------------------------------------------------------------------

/**
 * Strikes either side of ATM to request.
 *
 * 100 is the endpoint's maximum and yields around 201 strikes, which covers
 * every offset the wizard can name with room to spare. Omitting the field
 * returns the entire chain, which on a liquid index is far more than a picker
 * needs to show.
 */
const STRIKE_COUNT = 100

const SEARCH_MIN_LENGTH = 2
const SEARCH_RESULT_LIMIT = 25

export const contractQueryKeys = {
  all: ['strategy-module', 'contracts'] as const,
  expiries: (symbol: string, exchange: string, instrument: string) =>
    [...contractQueryKeys.all, 'expiries', symbol, exchange, instrument] as const,
  strikes: (underlying: string, exchange: string, expiry: string) =>
    [...contractQueryKeys.all, 'strikes', underlying, exchange, expiry] as const,
  search: (query: string, exchange: string) =>
    [...contractQueryKeys.all, 'search', exchange, query] as const,
  lotSize: (symbol: string, exchange: string) =>
    [...contractQueryKeys.all, 'lot-size', exchange, symbol] as const,
}

function errorMessage(error: unknown, fallback: string): string {
  const message = (error as { message?: string } | null)?.message
  return message?.trim() ? message : fallback
}

export interface ExpiryResolution {
  /** Listed expiries as the platform returned them: `DD-MMM-YY`, ascending. */
  expiries: string[]
  /** The contract a rank names, or null when the list cannot answer. */
  resolve: (rank: ExpiryRank) => string | null
  isLoading: boolean
  error: string | null
}

/**
 * The listed expiries for an underlying, and a resolver from rank to date.
 *
 * Cached for five minutes: the expiry list changes when the master contract is
 * refreshed, which is a daily event, not a per-keystroke one.
 */
export function useExpiryResolution(
  symbol: string,
  underlyingExchange: string,
  instrument: 'options' | 'futures',
  enabled = true
): ExpiryResolution {
  const { apiKey } = useAuthStore()
  const exchange = derivativeExchangeFor(underlyingExchange)
  const active = enabled && Boolean(apiKey) && Boolean(symbol)

  const query = useQuery({
    queryKey: contractQueryKeys.expiries(symbol, exchange, instrument),
    queryFn: async () => {
      const response = await optionChainApi.getExpiries(
        apiKey as string,
        symbol,
        exchange,
        instrument
      )
      if (response.status !== 'success') {
        throw new Error(
          response.message || `No ${instrument} expiries are listed for ${symbol} on ${exchange}.`
        )
      }
      return response.data ?? []
    },
    enabled: active,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const expiries = query.data ?? []
  return {
    expiries,
    resolve: (rank: ExpiryRank) => resolveExpiryRank(rank, expiries),
    isLoading: active && query.isLoading,
    error: query.isError
      ? errorMessage(
          query.error,
          'Could not load expiries. The master contract may not be downloaded.'
        )
      : null,
  }
}

export interface OptionStrikes {
  /** Listed strikes for the expiry, ascending. */
  strikes: number[]
  atmStrike: number | null
  /** The expiry the platform resolved the request to. */
  resolvedExpiry: string | null
  exchange: string
  isLoading: boolean
  error: string | null
}

/**
 * The strikes listed for one underlying and expiry.
 *
 * `expiryDate` is a `DD-MMM-YY` date, already resolved from the leg's rank.
 * The chain endpoint wants it without separators, and `normalizeExpiryCode` is
 * the conversion the rest of the app already uses.
 */
export function useOptionStrikes(
  underlying: string,
  underlyingExchange: string,
  expiryDate: string | null,
  enabled = true
): OptionStrikes {
  const { apiKey } = useAuthStore()
  const active = enabled && Boolean(apiKey) && Boolean(underlying) && Boolean(expiryDate)

  const query = useQuery({
    queryKey: contractQueryKeys.strikes(underlying, underlyingExchange, expiryDate ?? ''),
    queryFn: async () => {
      const response = await optionChainApi.getOptionChain(
        apiKey as string,
        underlying,
        underlyingExchange,
        normalizeExpiryCode(expiryDate as string),
        STRIKE_COUNT
      )
      if (response.status !== 'success') {
        throw new Error(response.message || 'The option chain came back empty.')
      }
      return response
    },
    enabled: active,
    staleTime: 60_000,
    retry: false,
  })

  const chain = query.data?.chain ?? []
  return {
    strikes: Array.from(new Set(chain.map((row) => row.strike)))
      .filter((strike) => Number.isFinite(strike))
      .sort((a, b) => a - b),
    atmStrike: query.data?.atm_strike ?? null,
    resolvedExpiry: query.data?.expiry_date ?? null,
    exchange: query.data?.underlying_exchange || underlyingExchange,
    isLoading: active && query.isLoading,
    error: query.isError
      ? errorMessage(query.error, 'Failed to load strikes. Master contract may not be downloaded.')
      : null,
  }
}

interface SearchRow {
  symbol: string
  name: string
  exchange: string
  instrumenttype: string
  lotsize?: number
}

export interface UnderlyingSearchResult {
  /** The base an underlying is named by: RELIANCE, CRUDEOIL. */
  symbol: string
  /** Which instrument types the search saw for it, e.g. "CE, FUT, PE". */
  instruments: string
}

export interface UnderlyingSearch {
  results: UnderlyingSearchResult[]
  isLoading: boolean
  error: string | null
}

/**
 * Underlyings matching a typed query.
 *
 * Searched on the derivative exchange rather than the cash one, so what comes
 * back is underlyings that actually have contracts to trade: a stock with no
 * F&O cannot carry an options leg, and offering it would only produce a
 * strategy that fails to resolve when it starts.
 *
 * Search rows are contracts, so they are collapsed onto their `name` - one row
 * per underlying, carrying the instrument types seen for it.
 */
async function searchSymbols(apiKey: string, term: string, exchange: string): Promise<SearchRow[]> {
  const response = await apiClient.post<{
    status: 'success' | 'error'
    message?: string
    data?: SearchRow[]
  }>('/search', { apikey: apiKey, query: term, exchange })
  if (response.data.status !== 'success') {
    throw new Error(response.data.message || 'Search failed.')
  }
  return response.data.data ?? []
}

export function useUnderlyingSearch(
  term: string,
  searchExchange: string,
  enabled = true
): UnderlyingSearch {
  const { apiKey } = useAuthStore()
  const trimmed = term.trim()
  const active = enabled && Boolean(apiKey) && trimmed.length >= SEARCH_MIN_LENGTH

  const query = useQuery({
    queryKey: contractQueryKeys.search(trimmed.toUpperCase(), searchExchange),
    queryFn: () => searchSymbols(apiKey as string, trimmed, searchExchange),
    enabled: active,
    staleTime: 5 * 60_000,
    retry: false,
  })

  return {
    results: collapseToUnderlyings(query.data ?? [], trimmed),
    isLoading: active && query.isLoading,
    error: query.isError
      ? errorMessage(query.error, 'Search failed. The master contract may not be downloaded.')
      : null,
  }
}

/** Contract rows reduced to the underlyings behind them, best match first. */
export function collapseToUnderlyings(rows: SearchRow[], term: string): UnderlyingSearchResult[] {
  const byName = new Map<string, Set<string>>()
  for (const row of rows) {
    const base = (row.name || row.symbol || '').trim().toUpperCase()
    if (!base) continue
    const kinds = byName.get(base) ?? new Set<string>()
    if (row.instrumenttype) kinds.add(row.instrumenttype.toUpperCase())
    byName.set(base, kinds)
  }

  const needle = term.trim().toUpperCase()
  const rank = (symbol: string) => (symbol === needle ? 0 : symbol.startsWith(needle) ? 1 : 2)

  return Array.from(byName.entries())
    .map(([symbol, kinds]) => ({ symbol, instruments: Array.from(kinds).sort().join(', ') }))
    .sort((a, b) => {
      // Exact match, then prefix match, then alphabetical. Typing RELIANCE
      // should not put RELIANCEPP above RELIANCE.
      const byRank = rank(a.symbol) - rank(b.symbol)
      return byRank !== 0 ? byRank : a.symbol.localeCompare(b.symbol)
    })
    .slice(0, SEARCH_RESULT_LIMIT)
}

/**
 * The lot size for a contract family, for display beside a lots-mode quantity.
 *
 * Read off `POST /api/v1/search`, which already carries `lotsize` on every row
 * and is the client this module uses for the symbol picker, so the lookup adds
 * no new endpoint and no second HTTP client.
 *
 * The obvious candidate, `/api/v1/optionsymbol`, is option-shaped: it wants an
 * expiry and an option type in order to resolve a strike, neither of which a
 * cash or futures signal leg has. `/api/v1/symbol` wants a fully-resolved
 * contract name (`NIFTY25AUG26FUT`), which would mean constructing broker
 * symbols in the browser. Searching by root symbol asks for what the leg
 * actually stores.
 *
 * This is display only. The server checks the lot boundary itself at save, and
 * the engine checks again at entry against the real contract.
 */
export function useLotSize(
  symbol: string | null | undefined,
  exchange: string | null | undefined,
  enabled = true
): { lotSize: number | null; isLoading: boolean; error: string | null } {
  const { apiKey } = useAuthStore()
  const root = (symbol ?? '').trim().toUpperCase()
  const venue = (exchange ?? '').trim().toUpperCase()
  const active = enabled && Boolean(apiKey) && root.length > 0 && venue.length > 0

  const query = useQuery({
    queryKey: contractQueryKeys.lotSize(root, venue),
    queryFn: () => searchSymbols(apiKey as string, root, venue),
    enabled: active,
    staleTime: 30 * 60_000,
    retry: false,
  })

  return {
    lotSize: lotSizeFromRows(query.data ?? [], root),
    isLoading: active && query.isLoading,
    error: query.isError
      ? errorMessage(
          query.error,
          'Could not read the lot size. The master contract may not be downloaded.'
        )
      : null,
  }
}

/**
 * The lot size for a root symbol, out of a page of search rows.
 *
 * Futures rows are preferred because a futures leg is what asks: every expiry
 * of one underlying carries the same lot size, so any FUT row answers for the
 * family. Anything else with a usable lot size is the fallback.
 */
export function lotSizeFromRows(rows: SearchRow[], root: string): number | null {
  const needle = root.trim().toUpperCase()
  const mine = rows.filter((row) => (row.name || '').trim().toUpperCase() === needle)
  const usable = (row: SearchRow) => typeof row.lotsize === 'number' && row.lotsize > 0
  const futures = mine.find(
    (row) => (row.instrumenttype || '').toUpperCase() === 'FUT' && usable(row)
  )
  if (futures) return futures.lotsize as number
  const any = mine.find(usable)
  return any ? (any.lotsize as number) : null
}
