/**
 * Strategy v2 Socket.IO hook — live updates for the run detail page.
 *
 * Connects a dedicated Socket.IO client (separate from the global useSocket
 * which handles toast/audio for orders), joins room=f"strategy_{strategy_id}"
 * via the server-side `strategy_v2_join` handler in subscribers/__init__.py,
 * and surfaces:
 *
 *   pnl: { agg_mtm, peak_mtm, drawdown, profit_locked }
 *   legs: Map<leg_id, { ltp, mtm, current_sl_price, sl_distance_pts, ... }>
 *   health: { feed_safe, order_channel_safe, reason }
 *   stateChange: latest StrategyStateChangedEvent
 *
 * Default debounce on the BACKEND is 200ms per run, so React re-renders are
 * naturally capped at ~5fps even without React Query / batching.
 */
import { useEffect, useRef, useState } from 'react'
import { io, type Socket } from 'socket.io-client'

// ---------------------------------------------------------------------------
// Payload types — match the backend realtime_broadcaster + socketio_subscriber
// ---------------------------------------------------------------------------

export interface PnlTickPayload {
  strategy_id: number
  run_id: number
  agg_mtm: number
  peak_mtm: number
  drawdown: number
  profit_locked: boolean
  leg_mtms: Array<{ leg_id: number; mtm: number }>
  ts_utc: number
  ts_ist: string
}

export interface LegUpdatePayload {
  strategy_id: number
  run_id: number
  leg_id: number
  symbol: string | null
  exchange: string | null
  ltp: number | null
  mtm: number
  current_sl_price: number | null
  sl_distance_pts: number | null
  target_distance_pts: number | null
  next_trail_at_pts: number | null
  trail_advances_count: number
  trail_to_entry_armed: boolean
  ts_utc: number
  ts_ist: string
}

export interface StrategyHealthPayload {
  feed_safe: boolean
  order_channel_safe: boolean
  reason: string
  ts_utc: number
  ts_ist: string
}

export interface StrategyStateChangePayload {
  strategy_id: number
  run_id: number
  old_state: string
  new_state: string
  reason: string
  ts_utc: number
  ts_ist: string
}

export interface StrategyV2LiveState {
  pnl: PnlTickPayload | null
  legs: Record<number, LegUpdatePayload>
  health: StrategyHealthPayload | null
  lastStateChange: StrategyStateChangePayload | null
  connected: boolean
}

const initialState: StrategyV2LiveState = {
  pnl: null,
  legs: {},
  health: null,
  lastStateChange: null,
  connected: false,
}

/**
 * Connect to the strategy room and surface live updates.
 *
 * Pass `enabled=false` (e.g. if the strategy_id isn't loaded yet) to skip
 * the connection entirely. Disconnects + leaves the room on unmount.
 */
export function useStrategyV2Socket(
  strategyId: number | null,
  enabled = true
): StrategyV2LiveState {
  const [state, setState] = useState<StrategyV2LiveState>(initialState)
  const socketRef = useRef<Socket | null>(null)

  useEffect(() => {
    if (!enabled || !strategyId) {
      // Reset state when disabled / id missing.
      setState(initialState)
      return
    }

    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    const socket = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: true,
    })
    socketRef.current = socket

    socket.on('connect', () => {
      setState((s) => ({ ...s, connected: true }))
      socket.emit('strategy_v2_join', { strategy_id: strategyId })
    })

    socket.on('disconnect', () => {
      setState((s) => ({ ...s, connected: false }))
    })

    socket.on('strategy_pnl_tick', (data: PnlTickPayload) => {
      if (data.strategy_id !== strategyId) return
      setState((s) => ({ ...s, pnl: data }))
    })

    socket.on('strategy_leg_update', (data: LegUpdatePayload) => {
      if (data.strategy_id !== strategyId) return
      setState((s) => ({
        ...s,
        legs: { ...s.legs, [data.leg_id]: data },
      }))
    })

    socket.on('strategy_health', (data: StrategyHealthPayload) => {
      // Health is global — accept regardless of strategy_id
      setState((s) => ({ ...s, health: data }))
    })

    socket.on('strategy_state_change', (data: StrategyStateChangePayload) => {
      if (data.strategy_id !== strategyId) return
      setState((s) => ({ ...s, lastStateChange: data }))
    })

    return () => {
      socket.emit('strategy_v2_leave', { strategy_id: strategyId })
      socket.disconnect()
      socketRef.current = null
    }
  }, [strategyId, enabled])

  return state
}

// ===========================================================================
// List-page hook — single Socket.IO connection that joins MANY rooms
// (one per active strategy) and surfaces a per-strategy P&L map. Used by
// StrategyV2List so each row updates without polling.
// ===========================================================================

export interface ListLivePnl {
  agg_mtm: number
  peak_mtm: number
  drawdown: number
  ts_ist: string
}

/**
 * Subscribe to P&L ticks for many strategies at once. Returns a map
 * keyed by strategy_id.
 *
 * The set of room subscriptions is recomputed when `strategyIds`
 * changes — joins new rooms, leaves rooms that fell off the list.
 * Uses a ref to track the previous set so we don't tear the socket
 * down between every parent render.
 */
export function useStrategyV2ListSocket(
  strategyIds: number[]
): Record<number, ListLivePnl> {
  const [pnlMap, setPnlMap] = useState<Record<number, ListLivePnl>>({})
  const socketRef = useRef<Socket | null>(null)
  const joinedRef = useRef<Set<number>>(new Set())

  useEffect(() => {
    if (strategyIds.length === 0) {
      // Tear down — nothing to listen to.
      if (socketRef.current) {
        socketRef.current.disconnect()
        socketRef.current = null
      }
      joinedRef.current = new Set()
      return
    }

    // Lazily open the socket on first non-empty list.
    if (!socketRef.current) {
      const protocol = window.location.protocol
      const host = window.location.hostname
      const port = window.location.port
      const socket = io(`${protocol}//${host}:${port}`, {
        transports: ['polling'],
        upgrade: false,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        timeout: 20000,
        forceNew: true,
      })
      socket.on('strategy_pnl_tick', (data: PnlTickPayload) => {
        setPnlMap((m) => ({
          ...m,
          [data.strategy_id]: {
            agg_mtm: data.agg_mtm,
            peak_mtm: data.peak_mtm,
            drawdown: data.drawdown,
            ts_ist: data.ts_ist,
          },
        }))
      })
      socket.on('connect', () => {
        // Re-issue every join after a reconnect — server-side rooms are
        // not persistent across socket disconnects.
        joinedRef.current.forEach((id) =>
          socket.emit('strategy_v2_join', { strategy_id: id })
        )
      })
      socketRef.current = socket
    }

    const socket = socketRef.current
    const want = new Set(strategyIds)

    // Join rooms we haven't joined yet.
    want.forEach((id) => {
      if (!joinedRef.current.has(id)) {
        socket.emit('strategy_v2_join', { strategy_id: id })
        joinedRef.current.add(id)
      }
    })
    // Leave rooms that fell off the list.
    Array.from(joinedRef.current).forEach((id) => {
      if (!want.has(id)) {
        socket.emit('strategy_v2_leave', { strategy_id: id })
        joinedRef.current.delete(id)
      }
    })
  }, [strategyIds])

  // Disconnect on unmount.
  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect()
        socketRef.current = null
      }
      joinedRef.current = new Set()
    }
  }, [])

  return pnlMap
}
