import { useEffect, useRef, useCallback } from 'react'
import { useDashboardStore } from '@/stores/dashboardStore'
import type { DepthLevel, TickData } from '@/types/dashboard'

// ─────────────────────────────────────────────────────────────────────────────
// AAUM Institutional Dashboard — WebSocket Hook
// Singleton connection to OpenAlgo's WebSocket for real-time market data.
// ─────────────────────────────────────────────────────────────────────────────

const WS_URL = 'ws://localhost:8765'
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 30_000
const DEPTH_THROTTLE_MS = 100

interface WSMessage {
  type: 'tick' | 'depth' | 'candle' | 'alert' | 'error'
  symbol?: string
  data?: unknown
}

let globalWs: WebSocket | null = null
let globalRefCount = 0

export function useDashboardWebSocket(symbols: string[]) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttempts = useRef(0)
  const depthThrottleMap = useRef<Map<string, number>>(new Map())
  const subscribedSymbols = useRef<Set<string>>(new Set())

  const setConnection = useDashboardStore((s) => s.setConnection)
  const upsertTick = useDashboardStore((s) => s.upsertTick)
  const upsertDepth = useDashboardStore((s) => s.upsertDepth)
  const pushAlert = useDashboardStore((s) => s.pushAlert)

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WSMessage
        const sym = msg.symbol

        switch (msg.type) {
          case 'tick': {
            if (sym && msg.data) {
              upsertTick(sym, msg.data as TickData)
            }
            break
          }
          case 'depth': {
            if (sym && msg.data) {
              const now = Date.now()
              const lastUpdate = depthThrottleMap.current.get(sym) ?? 0
              if (now - lastUpdate < DEPTH_THROTTLE_MS) return
              depthThrottleMap.current.set(sym, now)
              const d = msg.data as { bids: DepthLevel[]; asks: DepthLevel[] }
              upsertDepth(sym, d.bids, d.asks)
            }
            break
          }
          case 'alert': {
            if (msg.data) {
              pushAlert(
                msg.data as {
                  id: string
                  type: 'danger' | 'warning' | 'info' | 'success'
                  priority: 'critical' | 'high' | 'medium' | 'low'
                  title: string
                  message: string
                  symbol?: string
                  timestamp: number
                  dismissed: boolean
                },
              )
            }
            break
          }
        }
      } catch {
        // Silently ignore malformed messages
      }
    },
    [upsertTick, upsertDepth, pushAlert],
  )

  const connect = useCallback(() => {
    // Reuse singleton if already open
    if (globalWs && globalWs.readyState === WebSocket.OPEN) {
      wsRef.current = globalWs
      globalRefCount++
      setConnection('open')
      return
    }

    setConnection('connecting')
    const ws = new WebSocket(WS_URL)
    globalWs = ws
    wsRef.current = ws
    globalRefCount++

    ws.onopen = () => {
      setConnection('open')
      reconnectAttempts.current = 0

      // Subscribe to current symbols
      for (const sym of subscribedSymbols.current) {
        ws.send(JSON.stringify({ action: 'subscribe', symbol: sym }))
      }
    }

    ws.onmessage = handleMessage

    ws.onclose = () => {
      setConnection('closed')
      globalWs = null

      // Exponential backoff reconnect
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** reconnectAttempts.current,
        RECONNECT_MAX_MS,
      )
      reconnectAttempts.current++
      reconnectTimer.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      // onerror is always followed by onclose, reconnect happens there
    }
  }, [setConnection, handleMessage])

  // Subscribe/unsubscribe based on symbol changes
  useEffect(() => {
    const ws = wsRef.current
    const prev = subscribedSymbols.current
    const next = new Set(symbols)

    // Unsubscribe removed symbols
    for (const sym of prev) {
      if (!next.has(sym) && ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'unsubscribe', symbol: sym }))
      }
    }

    // Subscribe new symbols
    for (const sym of next) {
      if (!prev.has(sym) && ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'subscribe', symbol: sym }))
      }
    }

    subscribedSymbols.current = next
  }, [symbols])

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
      }
      globalRefCount--
      if (globalRefCount <= 0 && globalWs) {
        globalWs.close()
        globalWs = null
        globalRefCount = 0
      }
      wsRef.current = null
    }
  }, [connect])
}
