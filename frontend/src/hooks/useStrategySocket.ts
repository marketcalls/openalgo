import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useAuthStore } from '@/stores/authStore'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'

/**
 * SocketIO hook for strategy dashboard real-time updates.
 *
 * Listens for:
 * - strategy_order_filled → update position in store
 * - strategy_position_opened → add position
 * - strategy_position_closed → remove position
 * - strategy_order_update → general order status update
 * - strategy_risk_event → add risk event
 */
export function useStrategySocket() {
  const { isAuthenticated } = useAuthStore()
  const socketRef = useRef<Socket | null>(null)
  const { updatePosition, removePosition, addRiskEvent } = useStrategyDashboardStore()

  useEffect(() => {
    if (!isAuthenticated) return

    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: false,
    })

    const socket = socketRef.current

    socket.on('strategy_position_opened', (data: { strategy_id: number; position: never }) => {
      if (data.position) {
        updatePosition(data.strategy_id, data.position)
      }
    })

    socket.on(
      'strategy_position_closed',
      (data: { strategy_id: number; position_id: number }) => {
        if (data.strategy_id && data.position_id) {
          removePosition(data.strategy_id, data.position_id)
        }
      }
    )

    socket.on(
      'strategy_order_filled',
      (data: { strategy_id: number; position?: never }) => {
        if (data.position) {
          updatePosition(data.strategy_id, data.position)
        }
      }
    )

    socket.on(
      'strategy_risk_event',
      (data: { strategy_id: number; event: never }) => {
        if (data.event) {
          addRiskEvent(data.strategy_id, data.event)
        }
      }
    )

    return () => {
      socket.disconnect()
    }
  }, [isAuthenticated, updatePosition, removePosition, addRiskEvent])

  return socketRef.current
}
