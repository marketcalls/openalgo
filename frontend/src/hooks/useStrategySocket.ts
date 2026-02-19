import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useAuthStore } from '@/stores/authStore'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'
import type { DashboardPosition, DashboardOrder, RiskEvent } from '@/types/strategy-dashboard'

/**
 * SocketIO hook for strategy dashboard real-time updates.
 *
 * Listens for:
 * - strategy_position_opened → add position to store
 * - strategy_position_closed → remove position from store
 * - strategy_order_filled → update position in store
 * - strategy_order_update → update order status
 * - strategy_risk_event → add risk event to log
 * - strategy_position_update → live LTP/PnL updates
 * - strategy_circuit_breaker → CB status change
 */
export function useStrategySocket() {
  const { isAuthenticated } = useAuthStore()
  const socketRef = useRef<Socket | null>(null)
  const store = useStrategyDashboardStore()

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

    // Position opened — new position entry
    socket.on(
      'strategy_position_opened',
      (data: { strategy_id: number; position: DashboardPosition }) => {
        if (data.position) {
          store.updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Position closed — remove from active
    socket.on(
      'strategy_position_closed',
      (data: { strategy_id: number; position_id: number }) => {
        if (data.strategy_id && data.position_id) {
          store.removePosition(data.strategy_id, data.position_id)
        }
      }
    )

    // Order filled — update position with fill data
    socket.on(
      'strategy_order_filled',
      (data: { strategy_id: number; position?: DashboardPosition }) => {
        if (data.position) {
          store.updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Order status update — order state change (pending → open, rejected, etc.)
    socket.on(
      'strategy_order_update',
      (data: { strategy_id: number; order: DashboardOrder }) => {
        if (data.order) {
          store.updateOrder(data.strategy_id, data.order)
        }
      }
    )

    // Live position update — LTP, P&L, SL/TGT/TSL prices
    socket.on(
      'strategy_position_update',
      (data: { strategy_id: number; position: DashboardPosition }) => {
        if (data.position) {
          store.updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Risk event — SL/TGT/TSL trigger, breakeven, etc.
    socket.on(
      'strategy_risk_event',
      (data: { strategy_id: number; event: RiskEvent }) => {
        if (data.event) {
          store.addRiskEvent(data.strategy_id, data.event)
        }
      }
    )

    // Circuit breaker status change
    socket.on(
      'strategy_circuit_breaker',
      (data: { strategy_id: number; status: string; reason?: string }) => {
        store.updateCircuitBreaker(data.strategy_id, {
          status: data.status as 'active' | 'tripped' | 'cleared',
          reason: data.reason,
        })
      }
    )

    return () => {
      socket.disconnect()
    }
  }, [isAuthenticated, store])

  return socketRef.current
}
