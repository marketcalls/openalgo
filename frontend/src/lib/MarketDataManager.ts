/**
 * MarketDataManager - Singleton class for shared WebSocket connection management
 *
 * Implements:
 * - Single WebSocket connection across all components
 * - Ref-counted subscriptions (only unsubscribe when last consumer leaves)
 * - Callback registry for data fan-out to multiple subscribers
 * - Connection lifecycle management (connect, pause, resume, disconnect)
 */

export interface DepthLevel {
  price: number
  quantity: number
  orders?: number
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
  bid_price?: number
  ask_price?: number
  bid_size?: number
  ask_size?: number
  depth?: {
    buy: DepthLevel[]
    sell: DepthLevel[]
  }
}

export interface SymbolData {
  symbol: string
  exchange: string
  data: MarketData
  lastUpdate?: number
}

export type SubscriptionMode = 'LTP' | 'Quote' | 'Depth'

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'authenticating' | 'authenticated' | 'paused'

export interface StateListener {
  (state: {
    connectionState: ConnectionState
    isConnected: boolean
    isAuthenticated: boolean
    isPaused: boolean
    error: string | null
  }): void
}

export type DataCallback = (data: SymbolData) => void

interface SubscriptionEntry {
  symbol: string
  exchange: string
  mode: SubscriptionMode
  callbacks: Set<DataCallback>
  refCount: number
}

// Fetch CSRF token for authenticated requests
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

export class MarketDataManager {
  private static instance: MarketDataManager | null = null

  private socket: WebSocket | null = null
  private subscriptions: Map<string, SubscriptionEntry> = new Map() // key: "EXCHANGE:SYMBOL:MODE"
  private dataCache: Map<string, SymbolData> = new Map() // key: "EXCHANGE:SYMBOL"
  private stateListeners: Set<StateListener> = new Set()

  private connectionState: ConnectionState = 'disconnected'
  private error: string | null = null
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  private autoReconnect: boolean = true
  private reconnectAttempts: number = 0
  private maxReconnectAttempts: number = 10

  private constructor() {
    // Private constructor for singleton pattern
  }

  static getInstance(): MarketDataManager {
    if (!MarketDataManager.instance) {
      MarketDataManager.instance = new MarketDataManager()
    }
    return MarketDataManager.instance
  }

  // For testing purposes only
  static resetInstance(): void {
    if (MarketDataManager.instance) {
      MarketDataManager.instance.disconnect()
      MarketDataManager.instance = null
    }
  }

  /**
   * Subscribe to market data for a symbol
   * Returns an unsubscribe function
   */
  subscribe(
    symbol: string,
    exchange: string,
    mode: SubscriptionMode,
    callback: DataCallback
  ): () => void {
    const key = `${exchange}:${symbol}:${mode}`
    const dataKey = `${exchange}:${symbol}`

    let entry = this.subscriptions.get(key)

    if (entry) {
      // Existing subscription - add callback and increment ref count
      entry.callbacks.add(callback)
      entry.refCount++

      // Send cached data immediately if available
      const cached = this.dataCache.get(dataKey)
      if (cached) {
        callback(cached)
      }
    } else {
      // New subscription
      entry = {
        symbol,
        exchange,
        mode,
        callbacks: new Set([callback]),
        refCount: 1,
      }
      this.subscriptions.set(key, entry)

      // Initialize cache entry
      if (!this.dataCache.has(dataKey)) {
        this.dataCache.set(dataKey, { symbol, exchange, data: {} })
      }

      // Send subscribe message if connected and authenticated
      if (this.connectionState === 'authenticated') {
        this.sendSubscribe([{ symbol, exchange }], mode)
      }
    }

    // Return unsubscribe function
    return () => {
      this.unsubscribe(symbol, exchange, mode, callback)
    }
  }

  private unsubscribe(
    symbol: string,
    exchange: string,
    mode: SubscriptionMode,
    callback: DataCallback
  ): void {
    const key = `${exchange}:${symbol}:${mode}`
    const entry = this.subscriptions.get(key)

    if (!entry) return

    entry.callbacks.delete(callback)
    entry.refCount--

    // Only send unsubscribe when last consumer leaves
    if (entry.refCount <= 0) {
      this.subscriptions.delete(key)

      // Check if any other mode still needs this symbol
      const symbolStillNeeded = Array.from(this.subscriptions.values()).some(
        (e) => e.symbol === symbol && e.exchange === exchange
      )

      if (!symbolStillNeeded) {
        // Clean up cache
        const dataKey = `${exchange}:${symbol}`
        this.dataCache.delete(dataKey)

        // Send unsubscribe if connected
        if (this.connectionState === 'authenticated') {
          this.sendUnsubscribe([{ symbol, exchange }])
        }
      }
    }
  }

  /**
   * Add a listener for connection state changes
   */
  addStateListener(listener: StateListener): () => void {
    this.stateListeners.add(listener)

    // Immediately notify with current state
    listener(this.getState())

    return () => {
      this.stateListeners.delete(listener)
    }
  }

  getState() {
    return {
      connectionState: this.connectionState,
      isConnected: this.connectionState === 'connected' || this.connectionState === 'authenticating' || this.connectionState === 'authenticated',
      isAuthenticated: this.connectionState === 'authenticated',
      isPaused: this.connectionState === 'paused',
      error: this.error,
    }
  }

  /**
   * Get cached data for a symbol
   */
  getCachedData(symbol: string, exchange: string): SymbolData | undefined {
    return this.dataCache.get(`${exchange}:${symbol}`)
  }

  /**
   * Get all cached data
   */
  getAllCachedData(): Map<string, SymbolData> {
    return new Map(this.dataCache)
  }

  /**
   * Connect to WebSocket server
   */
  async connect(): Promise<void> {
    // Guard against multiple connections - check all active/connecting states
    if (
      this.socket?.readyState === WebSocket.OPEN ||
      this.socket?.readyState === WebSocket.CONNECTING ||
      this.connectionState === 'connecting' ||
      this.connectionState === 'connected' ||
      this.connectionState === 'authenticating' ||
      this.connectionState === 'authenticated'
    ) {
      return
    }

    this.setConnectionState('connecting')
    this.error = null

    try {
      const csrfToken = await fetchCSRFToken()

      // Get WebSocket config
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
        this.setConnectionState('connected')
        this.reconnectAttempts = 0

        try {
          // Get API key for authentication
          const authCsrfToken = await fetchCSRFToken()
          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          })
          const apiKeyData = await apiKeyResponse.json()

          if (apiKeyData.status === 'success' && apiKeyData.api_key) {
            this.setConnectionState('authenticating')
            socket.send(JSON.stringify({ action: 'authenticate', api_key: apiKeyData.api_key }))
          } else {
            this.setError('No API key found - please generate one at /apikey')
          }
        } catch (err) {
          this.setError(`Authentication error: ${err}`)
        }
      }

      socket.onclose = (event) => {
        this.socket = null

        if (this.connectionState !== 'paused') {
          this.setConnectionState('disconnected')
        }

        // Auto-reconnect if not clean close and not paused
        if (
          this.autoReconnect &&
          !event.wasClean &&
          this.connectionState !== 'paused' &&
          this.reconnectAttempts < this.maxReconnectAttempts
        ) {
          this.reconnectAttempts++
          const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000) // Exponential backoff, max 30s
          this.reconnectTimeout = setTimeout(() => this.connect(), delay)
        }
      }

      socket.onerror = () => {
        this.setError('WebSocket connection error')
      }

      socket.onmessage = (event) => this.handleMessage(event)

      this.socket = socket
    } catch (err) {
      this.setError(`Connection failed: ${err}`)
      this.setConnectionState('disconnected')
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    if (this.socket) {
      this.socket.close(1000, 'User disconnect')
      this.socket = null
    }

    this.setConnectionState('disconnected')
  }

  /**
   * Pause connection (e.g., when tab is hidden)
   * Keeps subscriptions in memory for resume
   */
  pauseConnection(): void {
    if (this.connectionState === 'paused' || this.connectionState === 'disconnected') {
      return
    }

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    if (this.socket) {
      this.socket.close(1000, 'Paused')
      this.socket = null
    }

    this.setConnectionState('paused')
  }

  /**
   * Resume connection after pause
   * Resubscribes to all active subscriptions
   */
  async resumeConnection(): Promise<void> {
    if (this.connectionState !== 'paused') {
      return
    }

    await this.connect()
  }

  private handleMessage(event: MessageEvent): void {
    try {
      const data = JSON.parse(event.data)
      const type = (data.type || data.status) as string

      switch (type) {
        case 'auth':
          if (data.status === 'success') {
            this.setConnectionState('authenticated')
            this.error = null
            // Resubscribe to all active subscriptions
            this.resubscribeAll()
          } else {
            this.setError(`Authentication failed: ${data.message}`)
          }
          break

        case 'market_data': {
          const symbol = (data.symbol as string).toUpperCase()
          const exchange = data.exchange as string
          const marketDataPayload = (data.data || {}) as MarketData
          const dataKey = `${exchange}:${symbol}`

          // Update cache
          const existing = this.dataCache.get(dataKey) || { symbol, exchange, data: {} }
          const newData = { ...existing.data }

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
            bid_price: marketDataPayload.bid_price ?? newData.bid_price,
            ask_price: marketDataPayload.ask_price ?? newData.ask_price,
            bid_size: marketDataPayload.bid_size ?? newData.bid_size,
            ask_size: marketDataPayload.ask_size ?? newData.ask_size,
            depth: marketDataPayload.depth ?? newData.depth,
          })

          const updatedSymbolData: SymbolData = {
            ...existing,
            data: newData,
            lastUpdate: Date.now(),
          }
          this.dataCache.set(dataKey, updatedSymbolData)

          // Fan out to all callbacks for this symbol (across all modes)
          this.subscriptions.forEach((entry) => {
            if (entry.symbol === symbol && entry.exchange === exchange) {
              entry.callbacks.forEach((callback) => {
                callback(updatedSymbolData)
              })
            }
          })
          break
        }

        case 'subscribe':
          // Subscription confirmed - no action needed
          break

        case 'error':
          this.setError(`WebSocket error: ${data.message}`)
          break
      }
    } catch {
      // Ignore parse errors for non-JSON messages
    }
  }

  private sendSubscribe(symbols: Array<{ symbol: string; exchange: string }>, mode: SubscriptionMode): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return

    this.socket.send(
      JSON.stringify({
        action: 'subscribe',
        symbols,
        mode,
      })
    )
  }

  private sendUnsubscribe(symbols: Array<{ symbol: string; exchange: string }>): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return

    this.socket.send(
      JSON.stringify({
        action: 'unsubscribe',
        symbols,
      })
    )
  }

  private resubscribeAll(): void {
    // Group subscriptions by mode for efficient batching
    const byMode = new Map<SubscriptionMode, Array<{ symbol: string; exchange: string }>>()

    this.subscriptions.forEach((entry) => {
      const symbols = byMode.get(entry.mode) || []
      symbols.push({ symbol: entry.symbol, exchange: entry.exchange })
      byMode.set(entry.mode, symbols)
    })

    // Send subscribe for each mode
    byMode.forEach((symbols, mode) => {
      if (symbols.length > 0) {
        this.sendSubscribe(symbols, mode)
      }
    })
  }

  private setConnectionState(state: ConnectionState): void {
    this.connectionState = state
    this.notifyStateListeners()
  }

  private setError(error: string): void {
    this.error = error
    this.notifyStateListeners()
  }

  private notifyStateListeners(): void {
    const state = this.getState()
    this.stateListeners.forEach((listener) => listener(state))
  }
}

export default MarketDataManager
