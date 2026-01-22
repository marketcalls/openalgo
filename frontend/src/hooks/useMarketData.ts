import { useCallback, useEffect, useRef, useState } from 'react'

// Fetch CSRF token for authenticated requests
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

export interface MarketData {
  ltp?: number
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  change?: number
  change_percent?: number
  timestamp?: string
}

export interface SymbolData {
  symbol: string
  exchange: string
  data: MarketData
  lastUpdate?: number
}

interface UseMarketDataOptions {
  symbols: Array<{ symbol: string; exchange: string }>
  mode?: 'LTP' | 'Quote' | 'Depth'
  enabled?: boolean
  autoReconnect?: boolean
}

interface UseMarketDataReturn {
  data: Map<string, SymbolData>
  isConnected: boolean
  isAuthenticated: boolean
  isConnecting: boolean
  error: string | null
  connect: () => Promise<void>
  disconnect: () => void
}

export function useMarketData({
  symbols,
  mode = 'LTP',
  enabled = true,
  autoReconnect = true,
}: UseMarketDataOptions): UseMarketDataReturn {
  const [marketData, setMarketData] = useState<Map<string, SymbolData>>(new Map())
  const [isConnected, setIsConnected] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const subscribedSymbolsRef = useRef<Set<string>>(new Set())
  const pendingSubscriptionsRef = useRef<Array<{ symbol: string; exchange: string }>>([])

  const getCsrfToken = useCallback(async () => fetchCSRFToken(), [])

  // Subscribe to symbols
  const subscribeToSymbols = useCallback(
    (symbolsToSubscribe: Array<{ symbol: string; exchange: string }>) => {
      if (
        !socketRef.current ||
        socketRef.current.readyState !== WebSocket.OPEN ||
        !isAuthenticated
      ) {
        // Queue for later when connected and authenticated
        pendingSubscriptionsRef.current = symbolsToSubscribe
        return
      }

      const newSymbols = symbolsToSubscribe.filter((s) => {
        const key = `${s.exchange}:${s.symbol}`
        return !subscribedSymbolsRef.current.has(key)
      })

      if (newSymbols.length === 0) return

      socketRef.current.send(
        JSON.stringify({
          action: 'subscribe',
          symbols: newSymbols,
          mode,
        })
      )

      // Track subscribed symbols
      newSymbols.forEach((s) => {
        const key = `${s.exchange}:${s.symbol}`
        subscribedSymbolsRef.current.add(key)

        // Initialize market data entry
        setMarketData((prev) => {
          const updated = new Map(prev)
          if (!updated.has(key)) {
            updated.set(key, { symbol: s.symbol, exchange: s.exchange, data: {} })
          }
          return updated
        })
      })
    },
    [isAuthenticated, mode]
  )

  // Handle incoming WebSocket messages
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        const type = (data.type || data.status) as string

        switch (type) {
          case 'auth':
            if (data.status === 'success') {
              setIsAuthenticated(true)
              setError(null)
              // Process any pending subscriptions
              if (pendingSubscriptionsRef.current.length > 0) {
                // Small delay to ensure auth is fully processed
                setTimeout(() => {
                  subscribeToSymbols(pendingSubscriptionsRef.current)
                  pendingSubscriptionsRef.current = []
                }, 100)
              }
            } else {
              setError(`Authentication failed: ${data.message}`)
            }
            break

          case 'market_data': {
            const symbol = (data.symbol as string).toUpperCase()
            const exchange = data.exchange as string
            const marketDataPayload = (data.data || {}) as MarketData
            const key = `${exchange}:${symbol}`

            setMarketData((prev) => {
              const existing = prev.get(key)
              if (!existing) return prev

              const updated = new Map(prev)
              const newData = { ...existing.data }

              // Update with new market data
              Object.assign(newData, {
                ltp: marketDataPayload.ltp ?? newData.ltp,
                open: marketDataPayload.open ?? newData.open,
                high: marketDataPayload.high ?? newData.high,
                low: marketDataPayload.low ?? newData.low,
                close: marketDataPayload.close ?? newData.close,
                volume: marketDataPayload.volume ?? newData.volume,
                change: marketDataPayload.change ?? newData.change,
                change_percent: marketDataPayload.change_percent ?? newData.change_percent,
                timestamp: marketDataPayload.timestamp ?? newData.timestamp,
              })

              updated.set(key, { ...existing, data: newData, lastUpdate: Date.now() })
              return updated
            })
            break
          }

          case 'subscribe':
            // Subscription confirmed
            break

          case 'error':
            setError(`WebSocket error: ${data.message}`)
            break
        }
      } catch {
        // Ignore parse errors for non-JSON messages
      }
    },
    [subscribeToSymbols]
  )

  // Connect to WebSocket
  const connect = useCallback(async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    setIsConnecting(true)
    setError(null)

    try {
      const csrfToken = await getCsrfToken()

      // Get WebSocket config (URL from .env)
      const configResponse = await fetch('/api/websocket/config', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const configData = await configResponse.json()

      if (configData.status !== 'success') {
        throw new Error('Failed to get WebSocket configuration')
      }

      const wsUrl = configData.websocket_url

      const socket = new WebSocket(wsUrl)

      socket.onopen = async () => {
        setIsConnected(true)
        setIsConnecting(false)

        try {
          // Get API key for authentication
          const authCsrfToken = await getCsrfToken()
          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          })
          const apiKeyData = await apiKeyResponse.json()

          if (apiKeyData.status === 'success' && apiKeyData.api_key) {
            socket.send(JSON.stringify({ action: 'authenticate', api_key: apiKeyData.api_key }))
          } else {
            setError('No API key found - please generate one at /apikey')
          }
        } catch (err) {
          setError(`Authentication error: ${err}`)
        }
      }

      socket.onclose = (event) => {
        setIsConnected(false)
        setIsConnecting(false)
        setIsAuthenticated(false)
        subscribedSymbolsRef.current.clear()

        if (autoReconnect && !event.wasClean && enabled) {
          reconnectTimeoutRef.current = setTimeout(connect, 3000)
        }
      }

      socket.onerror = () => {
        setError('WebSocket connection error')
        setIsConnecting(false)
      }

      socket.onmessage = handleMessage

      socketRef.current = socket
    } catch (err) {
      setError(`Connection failed: ${err}`)
      setIsConnecting(false)
    }
  }, [getCsrfToken, handleMessage, autoReconnect, enabled])

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (socketRef.current) {
      socketRef.current.close(1000, 'User disconnect')
      socketRef.current = null
    }
    setIsConnected(false)
    setIsAuthenticated(false)
    subscribedSymbolsRef.current.clear()
  }, [])

  // Auto-connect when enabled and symbols provided
  useEffect(() => {
    if (enabled && symbols.length > 0 && !isConnected && !isConnecting) {
      connect()
    }

    return () => {
      // Cleanup on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
    }
  }, [enabled, symbols.length, isConnected, isConnecting, connect])

  // Subscribe to new symbols when authenticated
  useEffect(() => {
    if (isAuthenticated && symbols.length > 0) {
      subscribeToSymbols(symbols)
    }
  }, [isAuthenticated, symbols, subscribeToSymbols])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    data: marketData,
    isConnected,
    isAuthenticated,
    isConnecting,
    error,
    connect,
    disconnect,
  }
}
