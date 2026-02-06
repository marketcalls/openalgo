import { useCallback, useEffect, useRef, useState } from 'react'
import { io, type Socket } from 'socket.io-client'
import type {
  CircuitBreakerEvent,
  CircuitBreakerStatus,
  StrategyPnlUpdate,
} from '@/types/strategy'

interface UseCircuitBreakerReturn {
  statuses: Map<number, CircuitBreakerStatus>
  getStatus: (strategyId: number) => CircuitBreakerStatus | undefined
}

export function useCircuitBreaker(enabled = true): UseCircuitBreakerReturn {
  const socketRef = useRef<Socket | null>(null)
  const [statuses, setStatuses] = useState<Map<number, CircuitBreakerStatus>>(new Map())

  useEffect(() => {
    if (!enabled) return

    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
    })

    const socket = socketRef.current

    // Handle P&L updates (high-frequency, every 300ms per strategy)
    socket.on('strategy_pnl_update', (data: StrategyPnlUpdate) => {
      setStatuses((prev) => {
        const next = new Map(prev)
        next.set(data.strategy_id, {
          isTripped: data.circuit_breaker_active,
          reason: data.circuit_breaker_reason || '',
          dailyRealizedPnl: data.daily_realized_pnl,
          dailyTotalPnl: data.daily_total_pnl,
          totalUnrealizedPnl: data.total_unrealized_pnl,
          positionCount: data.position_count,
          lastUpdate: Date.now(),
        })
        return next
      })
    })

    // Handle circuit breaker trip/reset events
    socket.on('strategy_circuit_breaker', (data: CircuitBreakerEvent) => {
      if (data.action === 'daily_reset') {
        // Clear all tripped states on daily reset
        setStatuses(new Map())
      } else if (data.action === 'tripped' && data.strategy_id) {
        setStatuses((prev) => {
          const next = new Map(prev)
          const existing = next.get(data.strategy_id!)
          next.set(data.strategy_id!, {
            isTripped: true,
            reason: data.reason || '',
            dailyRealizedPnl: existing?.dailyRealizedPnl ?? 0,
            dailyTotalPnl: data.daily_pnl ?? existing?.dailyTotalPnl ?? 0,
            totalUnrealizedPnl: existing?.totalUnrealizedPnl ?? 0,
            positionCount: existing?.positionCount ?? 0,
            lastUpdate: Date.now(),
          })
          return next
        })
      }
    })

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [enabled])

  const getStatus = useCallback(
    (strategyId: number): CircuitBreakerStatus | undefined => {
      return statuses.get(strategyId)
    },
    [statuses]
  )

  return { statuses, getStatus }
}
