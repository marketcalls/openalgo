import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'
import type {
  StrategyPositionUpdatePayload,
  PnLUpdatePayload,
} from '@/types/strategy-dashboard'

/**
 * SocketIO hook for the Strategy Dashboard.
 *
 * Connects to strategy rooms, dispatches position/PnL updates to the Zustand store.
 * Toast notifications for user-facing events (exits, opens, closes, rejections)
 * are handled globally by useSocket.ts to avoid duplicates.
 */
export function useStrategySocket(strategyIds: number[]) {
  const socketRef = useRef<Socket | null>(null)
  const joinedRoomsRef = useRef<Set<string>>(new Set())

  // Stable reference to store actions (no re-render on store changes)
  const storeRef = useRef(useStrategyDashboardStore.getState())
  useEffect(() => {
    return useStrategyDashboardStore.subscribe((state) => {
      storeRef.current = state
    })
  }, [])

  useEffect(() => {
    if (strategyIds.length === 0) return

    // Build Socket.IO URL from current location
    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    const socket = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
    })
    socketRef.current = socket

    socket.on('connect', () => {
      storeRef.current.setConnectionStatus('connected')

      // Join strategy rooms
      const rooms = strategyIds.map((id) => `strategy_${id}`)
      for (const room of rooms) {
        socket.emit('join_strategy_room', { room })
        joinedRoomsRef.current.add(room)
      }
    })

    socket.on('disconnect', () => {
      storeRef.current.setConnectionStatus('disconnected')
    })

    // ── Silent data events → Zustand store ────────────

    socket.on('strategy_position_update', (data: StrategyPositionUpdatePayload) => {
      storeRef.current.updatePositions(data.strategy_id, data.positions)
    })

    socket.on('strategy_pnl_update', (data: PnLUpdatePayload) => {
      storeRef.current.updateStrategyPnL(data)
    })

    // ── Connection status events ──────────────────────

    socket.on('strategy_risk_paused', () => {
      storeRef.current.setConnectionStatus('stale')
    })

    socket.on('strategy_risk_resumed', () => {
      storeRef.current.setConnectionStatus('connected')
    })

    // Cleanup: leave rooms, disconnect
    return () => {
      for (const room of joinedRoomsRef.current) {
        socket.emit('leave_strategy_room', { room })
      }
      joinedRoomsRef.current.clear()
      socket.disconnect()
      socketRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyIds.join(',')])

  return { socket: socketRef.current }
}
