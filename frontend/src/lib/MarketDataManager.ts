/**
 * MarketDataManager - Singleton class for shared WebSocket connection management
 *
 * Implements:
 * - Single WebSocket connection across all components
 * - Ref-counted subscriptions (only unsubscribe when last consumer leaves)
 * - Callback registry for data fan-out to multiple subscribers
 * - Connection lifecycle management (connect, pause, resume, disconnect)
 * - REST API fallback when WebSocket is unavailable (e.g., after market hours)
 *
 * Fallback behavior:
 * - After 3 consecutive WebSocket connection failures, switches to REST API polling
 * - Polls /api/v1/multiquotes every 5 seconds for subscribed symbols
 * - Automatically switches back to WebSocket when connection is restored
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
    isFallbackMode: boolean
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

// REST API response types
interface QuotesApiData {
  ltp?: number
  open?: number
  high?: number
  low?: number
  prev_close?: number
  volume?: number
  bid?: number
  ask?: number
  oi?: number
}

interface MultiQuotesResult {
  symbol: string
  exchange: string
  data: QuotesApiData
}

interface MultiQuotesApiResponse {
  status: 'success' | 'error'
  results?: MultiQuotesResult[]
  message?: string
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
  private userDisconnected: boolean = false
  private connectAbortController: AbortController | null = null

  // REST API fallback properties
  private fallbackMode: boolean = false
  private fallbackPollingInterval: ReturnType<typeof setInterval> | null = null
  private fallbackPollingRate: number = 5000 // Poll every 5 seconds in fallback mode
  private apiKey: string | null = null
  private consecutiveFailures: number = 0
  private maxConsecutiveFailures: number = 3 // Switch to fallback after 3 consecutive connection failures

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
    rawSymbol: string,
    rawExchange: string,
    mode: SubscriptionMode,
    callback: DataCallback
  ): () => void {
    // Normalize to uppercase for consistent cache keys across WebSocket and REST
    const symbol = rawSymbol.toUpperCase()
    const exchange = rawExchange.toUpperCase()
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
      } else if (this.fallbackMode && this.apiKey) {
        // In fallback mode - start polling if not already running
        if (!this.fallbackPollingInterval) {
          this.startFallbackPolling()
        } else {
          // Fetch immediately for new subscription
          this.fetchMarketDataViaRest()
        }
      }
    }

    // Return unsubscribe function
    return () => {
      this.unsubscribe(symbol, exchange, mode, callback)
    }
  }

  private unsubscribe(
    rawSymbol: string,
    rawExchange: string,
    mode: SubscriptionMode,
    callback: DataCallback
  ): void {
    const symbol = rawSymbol.toUpperCase()
    const exchange = rawExchange.toUpperCase()
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

      // Stop fallback polling if no more subscriptions
      if (this.subscriptions.size === 0 && this.fallbackMode) {
        this.stopFallbackPolling()
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
      isFallbackMode: this.fallbackMode,
      error: this.error,
    }
  }

  /**
   * Check if currently in REST API fallback mode
   */
  isFallback(): boolean {
    return this.fallbackMode
  }

  /**
   * Get cached data for a symbol
   */
  getCachedData(symbol: string, exchange: string): SymbolData | undefined {
    return this.dataCache.get(`${exchange.toUpperCase()}:${symbol.toUpperCase()}`)
  }

  /**
   * Get all cached data
   */
  getAllCachedData(): Map<string, SymbolData> {
    return new Map(this.dataCache)
  }

  /**
   * Set auto-reconnect behavior
   */
  setAutoReconnect(enabled: boolean): void {
    this.autoReconnect = enabled
  }

  /**
   * Get current auto-reconnect setting
   */
  getAutoReconnect(): boolean {
    return this.autoReconnect
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

    // Clear user disconnect flag when starting a new connection
    this.userDisconnected = false

    // Abort any previous connect attempt
    this.connectAbortController?.abort()
    this.connectAbortController = new AbortController()
    const abortSignal = this.connectAbortController.signal

    this.setConnectionState('connecting')
    this.error = null

    try {
      const csrfToken = await fetchCSRFToken()

      // Check if disconnect was called during async operation
      if (this.userDisconnected || abortSignal.aborted) {
        this.setConnectionState('disconnected')
        return
      }

      // Get WebSocket config
      const configResponse = await fetch('/api/websocket/config', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
        signal: abortSignal,
      })
      const configData = await configResponse.json()

      if (configData.status !== 'success') {
        throw new Error('Failed to get WebSocket configuration')
      }

      // Check again after config fetch
      if (this.userDisconnected || abortSignal.aborted) {
        this.setConnectionState('disconnected')
        return
      }

      const wsUrl = configData.websocket_url
      const socket = new WebSocket(wsUrl)

      socket.onopen = async () => {
        // Check if disconnect was called before socket opened
        if (this.userDisconnected) {
          socket.close(1000, 'User disconnect during connection')
          return
        }

        this.setConnectionState('connected')
        this.reconnectAttempts = 0

        try {
          // Get API key for authentication
          const authCsrfToken = await fetchCSRFToken()

          // Check again after async operation
          if (this.userDisconnected) {
            socket.close(1000, 'User disconnect during authentication')
            return
          }

          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          })
          const apiKeyData = await apiKeyResponse.json()

          // Check again after API key fetch
          if (this.userDisconnected) {
            socket.close(1000, 'User disconnect during authentication')
            return
          }

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

        // Track consecutive failures for fallback trigger
        if (!event.wasClean) {
          this.consecutiveFailures++
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
        } else if (
          this.reconnectAttempts >= this.maxReconnectAttempts ||
          this.consecutiveFailures >= this.maxConsecutiveFailures
        ) {
          // Max reconnect attempts reached - switch to REST API fallback
          this.enableFallbackMode()
        }
      }

      socket.onerror = () => {
        this.consecutiveFailures++
        this.setError('WebSocket connection error')
      }

      socket.onmessage = (event) => this.handleMessage(event)

      this.socket = socket
    } catch (err) {
      this.consecutiveFailures++
      this.setError(`Connection failed: ${err}`)
      this.setConnectionState('disconnected')

      // Check if we should switch to fallback mode
      if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
        this.enableFallbackMode()
      }
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    // Mark as user-initiated disconnect to prevent zombie connections
    this.userDisconnected = true

    // Abort any in-progress connection attempt
    if (this.connectAbortController) {
      this.connectAbortController.abort()
      this.connectAbortController = null
    }

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    if (this.socket) {
      this.socket.close(1000, 'User disconnect')
      this.socket = null
    }

    // Stop fallback polling on disconnect
    this.stopFallbackPolling()
    this.fallbackMode = false
    this.consecutiveFailures = 0
    this.apiKey = null

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
            this.consecutiveFailures = 0 // Reset failure count on successful auth
            // Disable fallback mode now that WebSocket is working
            this.disableFallbackMode()
            // Resubscribe to all active subscriptions
            this.resubscribeAll()
          } else {
            this.setError(`Authentication failed: ${data.message}`)
          }
          break

        case 'market_data': {
          const symbol = (data.symbol as string).toUpperCase()
          const exchange = (data.exchange as string).toUpperCase()
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

  // ============================================================
  // REST API Fallback Methods
  // ============================================================

  /**
   * Switch to REST API fallback mode
   * Called when WebSocket connection repeatedly fails
   */
  private async enableFallbackMode(): Promise<void> {
    if (this.fallbackMode) return

    this.fallbackMode = true
    this.notifyStateListeners()

    // Fetch API key for REST calls
    await this.fetchApiKeyForFallback()

    // Start polling if we have subscriptions
    if (this.subscriptions.size > 0 && this.apiKey) {
      this.startFallbackPolling()
    }
  }

  /**
   * Disable REST API fallback mode (when WebSocket reconnects)
   */
  private disableFallbackMode(): void {
    if (!this.fallbackMode) return

    this.fallbackMode = false
    this.stopFallbackPolling()
    this.consecutiveFailures = 0
    this.notifyStateListeners()
  }

  /**
   * Fetch API key for REST API calls
   */
  private async fetchApiKeyForFallback(): Promise<void> {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/api/websocket/apikey', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success' && data.api_key) {
        this.apiKey = data.api_key
      }
    } catch (err) {
    }
  }

  /**
   * Start REST API polling for subscribed symbols
   */
  private startFallbackPolling(): void {
    if (this.fallbackPollingInterval) return


    // Fetch immediately
    this.fetchMarketDataViaRest()

    // Then poll at regular intervals
    this.fallbackPollingInterval = setInterval(() => {
      this.fetchMarketDataViaRest()
    }, this.fallbackPollingRate)
  }

  /**
   * Stop REST API polling
   */
  private stopFallbackPolling(): void {
    if (this.fallbackPollingInterval) {
      clearInterval(this.fallbackPollingInterval)
      this.fallbackPollingInterval = null
    }
  }

  /**
   * Fetch market data via REST API (multiquotes endpoint)
   */
  private async fetchMarketDataViaRest(): Promise<void> {
    if (!this.apiKey || this.subscriptions.size === 0) return

    try {
      // Collect unique symbols from subscriptions
      const uniqueSymbols = new Map<string, { symbol: string; exchange: string }>()
      this.subscriptions.forEach((entry) => {
        const key = `${entry.exchange}:${entry.symbol}`
        if (!uniqueSymbols.has(key)) {
          uniqueSymbols.set(key, { symbol: entry.symbol, exchange: entry.exchange })
        }
      })

      const symbolsArray = Array.from(uniqueSymbols.values())
      if (symbolsArray.length === 0) return

      // Call multiquotes API
      const response = await fetch('/api/v1/multiquotes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          apikey: this.apiKey,
          symbols: symbolsArray,
        }),
      })

      const data = await response.json() as MultiQuotesApiResponse

      if (data.status === 'success' && data.results) {
        // Process each result and update cache + notify subscribers
        for (const result of data.results) {
          const symbol = result.symbol.toUpperCase()
          const exchange = result.exchange.toUpperCase()
          const dataKey = `${exchange}:${symbol}`

          // Update cache
          const existing = this.dataCache.get(dataKey) || { symbol, exchange, data: {} }
          const newData = { ...existing.data }

          Object.assign(newData, {
            ltp: result.data.ltp ?? newData.ltp,
            open: result.data.open ?? newData.open,
            high: result.data.high ?? newData.high,
            low: result.data.low ?? newData.low,
            close: result.data.prev_close ?? newData.close,
            volume: result.data.volume ?? newData.volume,
            bid_price: result.data.bid ?? newData.bid_price,
            ask_price: result.data.ask ?? newData.ask_price,
          })

          const updatedSymbolData: SymbolData = {
            ...existing,
            data: newData,
            lastUpdate: Date.now(),
          }
          this.dataCache.set(dataKey, updatedSymbolData)

          // Fan out to all callbacks for this symbol (keys are already normalized to uppercase)
          this.subscriptions.forEach((entry) => {
            if (entry.symbol === symbol && entry.exchange === exchange) {
              entry.callbacks.forEach((callback) => {
                callback(updatedSymbolData)
              })
            }
          })
        }
      }
    } catch (err) {
    }
  }

  /**
   * Set fallback polling rate in milliseconds
   */
  setFallbackPollingRate(rate: number): void {
    this.fallbackPollingRate = rate
    // Restart polling if currently active
    if (this.fallbackPollingInterval) {
      this.stopFallbackPolling()
      this.startFallbackPolling()
    }
  }
}

export default MarketDataManager
