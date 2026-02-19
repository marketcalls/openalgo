import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useAuthStore } from '@/stores/authStore'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'
import type { DashboardPosition, DashboardOrder, PositionGroupData, RiskEvent } from '@/types/strategy-dashboard'

/**
 * SocketIO hook for strategy dashboard real-time updates.
 *
 * Listens for:
 * - strategy_position_opened → add position to store
 * - strategy_position_closed → remove position from store
 * - strategy_order_filled → update position in store
 * - strategy_order_update → update order status
 * - strategy_order_placed → new order placed
 * - strategy_order_cancelled → order cancelled
 * - strategy_risk_event → add risk event to log
 * - strategy_position_update → live LTP/PnL updates
 * - strategy_circuit_breaker → CB status change
 * - strategy_group_update → position group status change
 * - strategy_pnl_update → P&L snapshot update
 * - strategy_trailstop_moved → trailing stop moved
 * - builder_leg_update → builder leg fill status
 * - builder_execution_complete → all builder legs executed
 */
export function useStrategySocket() {
  const { isAuthenticated } = useAuthStore()
  const socketRef = useRef<Socket | null>(null)
  const storeRef = useRef(useStrategyDashboardStore.getState())

  // Keep ref in sync without triggering re-renders
  useEffect(() => {
    return useStrategyDashboardStore.subscribe((state) => {
      storeRef.current = state
    })
  }, [])

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
    const store = () => storeRef.current

    // Position opened — new position entry
    socket.on(
      'strategy_position_opened',
      (data: { strategy_id: number; position: DashboardPosition }) => {
        if (data.position) {
          store().updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Position closed — remove from active
    socket.on(
      'strategy_position_closed',
      (data: { strategy_id: number; position_id: number }) => {
        if (data.strategy_id && data.position_id) {
          store().removePosition(data.strategy_id, data.position_id)
        }
      }
    )

    // Order filled — update position with fill data
    socket.on(
      'strategy_order_filled',
      (data: { strategy_id: number; position?: DashboardPosition }) => {
        if (data.position) {
          store().updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Order status update — order state change (pending → open, rejected, etc.)
    socket.on(
      'strategy_order_update',
      (data: { strategy_id: number; order: DashboardOrder }) => {
        if (data.order) {
          store().updateOrder(data.strategy_id, data.order)
        }
      }
    )

    // Live position update — LTP, P&L, SL/TGT/TSL prices
    socket.on(
      'strategy_position_update',
      (data: { strategy_id: number; position: DashboardPosition }) => {
        if (data.position) {
          store().updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Risk event — SL/TGT/TSL trigger, breakeven, etc.
    socket.on(
      'strategy_risk_event',
      (data: { strategy_id: number; event: RiskEvent }) => {
        if (data.event) {
          store().addRiskEvent(data.strategy_id, data.event)
        }
      }
    )

    // Circuit breaker status change
    socket.on(
      'strategy_circuit_breaker',
      (data: { strategy_id: number; status: string; reason?: string }) => {
        store().updateCircuitBreaker(data.strategy_id, {
          status: data.status as 'active' | 'tripped' | 'cleared',
          reason: data.reason,
        })
      }
    )

    // Position group update
    socket.on(
      'strategy_group_update',
      (data: { strategy_id: number; group: PositionGroupData }) => {
        if (data.group) {
          store().updateGroup(data.strategy_id, data.group)
        }
      }
    )

    // P&L snapshot update
    socket.on(
      'strategy_pnl_update',
      (data: { strategy_id: number; summary: { total_unrealized_pnl: number; today_realized_pnl: number } }) => {
        if (data.summary) {
          const current = store().summary.get(data.strategy_id)
          if (current) {
            store().setSummary(data.strategy_id, {
              ...current,
              total_unrealized_pnl: data.summary.total_unrealized_pnl,
              today_realized_pnl: data.summary.today_realized_pnl,
            })
          }
        }
      }
    )

    // New order placed
    socket.on(
      'strategy_order_placed',
      (data: { strategy_id: number; order: DashboardOrder }) => {
        if (data.order) {
          store().updateOrder(data.strategy_id, data.order)
        }
      }
    )

    // Order cancelled
    socket.on(
      'strategy_order_cancelled',
      (data: { strategy_id: number; order: DashboardOrder }) => {
        if (data.order) {
          store().updateOrder(data.strategy_id, data.order)
        }
      }
    )

    // Trailing stop moved
    socket.on(
      'strategy_trailstop_moved',
      (data: { strategy_id: number; position: DashboardPosition }) => {
        if (data.position) {
          store().updatePosition(data.strategy_id, data.position)
        }
      }
    )

    // Builder leg fill status — informational, handled by position updates
    socket.on('builder_leg_update', () => {})

    // Builder execution complete — informational, signals all legs have been attempted
    socket.on('builder_execution_complete', () => {})

    return () => {
      socket.removeAllListeners()
      socket.disconnect()
    }
  }, [isAuthenticated])

  return socketRef.current
}
