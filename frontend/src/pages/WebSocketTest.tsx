import {
  Activity,
  ArrowDown,
  ArrowUp,
  Cable,
  ChevronDown,
  ChevronRight,
  Layers,
  Link2,
  Link2Off,
  Radio,
  RefreshCw,
  Search,
  Settings2,
  Terminal,
  Trash2,
  TrendingDown,
  TrendingUp,
  Wifi,
  WifiOff,
  X,
  Zap,
  ZapOff,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

interface SearchResult {
  symbol: string
  name: string
  exchange: string
  token: string
}

interface MarketData {
  ltp?: number
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  change?: number
  change_percent?: number
  timestamp?: string
  depth?: {
    buy: Array<{ price: number; quantity: number; orders?: number }>
    sell: Array<{ price: number; quantity: number; orders?: number }>
  }
}

interface SymbolData {
  symbol: string
  exchange: string
  data: MarketData
  subscriptions: Set<string>
  lastUpdate?: number
}

interface LogEntry {
  timestamp: string
  message: string
  type: 'info' | 'success' | 'error' | 'data' | 'warn'
}

const EXCHANGES = ['NSE', 'NFO', 'BSE', 'BFO', 'CDS', 'MCX']

function formatPrice(price: number): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(price)
}

function formatVolume(volume: number): string {
  if (volume >= 10000000) return `${(volume / 10000000).toFixed(2)}Cr`
  if (volume >= 100000) return `${(volume / 100000).toFixed(2)}L`
  if (volume >= 1000) return `${(volume / 1000).toFixed(1)}K`
  return volume.toString()
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return '--:--:--'
  return new Date(timestamp).toLocaleTimeString('en-IN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// Glowing status indicator
function StatusOrb({
  status,
  size = 'md',
}: {
  status: 'success' | 'warning' | 'error' | 'idle'
  size?: 'sm' | 'md'
}) {
  const sizeClasses = size === 'sm' ? 'w-2 h-2' : 'w-3 h-3'
  return (
    <div className="relative">
      <div
        className={cn(
          sizeClasses,
          'rounded-full transition-all duration-500',
          status === 'success' && 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]',
          status === 'warning' && 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]',
          status === 'error' && 'bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.8)]',
          status === 'idle' && 'bg-muted'
        )}
      />
      {status !== 'idle' && (
        <div
          className={cn(
            'absolute inset-0 rounded-full animate-ping opacity-40',
            status === 'success' && 'bg-emerald-400',
            status === 'warning' && 'bg-amber-400',
            status === 'error' && 'bg-rose-400'
          )}
        />
      )}
    </div>
  )
}

// Stat card component
function StatCard({
  label,
  value,
  icon: Icon,
  status,
  subtitle,
}: {
  label: string
  value: string | number
  icon: React.ElementType
  status?: 'success' | 'warning' | 'error' | 'idle'
  subtitle?: string
}) {
  return (
    <div className="relative group">
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 to-transparent rounded-lg opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="relative px-4 py-3 rounded-lg bg-card border border-border hover:border-border/60 transition-colors">
        <div className="flex items-center justify-between mb-1.5">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
          {status && <StatusOrb status={status} size="sm" />}
        </div>
        <div className="text-lg font-bold font-mono text-foreground tracking-tight">{value}</div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-0.5">
          {label}
        </div>
        {subtitle && <div className="text-[9px] text-muted-foreground/60 mt-1">{subtitle}</div>}
      </div>
    </div>
  )
}

// Depth bar visualization
function DepthLevel({
  price,
  quantity,
  maxQty,
  side,
}: {
  price: number
  quantity: number
  maxQty: number
  side: 'buy' | 'sell'
}) {
  const pct = Math.min((quantity / maxQty) * 100, 100)
  return (
    <div className="relative flex items-center gap-2 py-1">
      <div className="absolute inset-0 rounded overflow-hidden">
        <div
          className={cn(
            'absolute top-0 bottom-0 transition-all duration-300',
            side === 'buy'
              ? 'left-0 bg-gradient-to-r from-emerald-500/20 to-transparent'
              : 'right-0 bg-gradient-to-l from-rose-500/20 to-transparent'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="relative z-10 flex-1 font-mono text-xs text-muted-foreground">
        {formatPrice(price)}
      </span>
      <span
        className={cn(
          'relative z-10 font-mono text-xs font-medium',
          side === 'buy' ? 'text-emerald-400' : 'text-rose-400'
        )}
      >
        {quantity.toLocaleString()}
      </span>
    </div>
  )
}

interface WebSocketTestProps {
  depthLevel?: number
}

export default function WebSocketTest({ depthLevel = 5 }: WebSocketTestProps) {
  // Connection state - INDEPENDENT WebSocket (not shared with MarketDataManager)
  // This page needs its own connection for testing/debugging purposes
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [autoReconnect, setAutoReconnect] = useState(true)
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Metrics
  const [messageCount, setMessageCount] = useState(0)
  const [lastMessageTime, setLastMessageTime] = useState<number | null>(null)

  // Symbol management
  const [activeSymbols, setActiveSymbols] = useState<Map<string, SymbolData>>(new Map())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchExchange, setSearchExchange] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [showSearchResults, setShowSearchResults] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [expandedDepths, setExpandedDepths] = useState<Set<string>>(new Set())
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set())

  // UI state
  const [showRawLogs, setShowRawLogs] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [rawMessages, setRawMessages] = useState<string[]>([])
  const logContainerRef = useRef<HTMLDivElement>(null)
  const searchInputRef = useRef<HTMLDivElement>(null)

  // Logging
  const logEvent = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    const timestamp = new Date().toLocaleTimeString('en-IN', { hour12: false })
    setLogs((prev) => [...prev.slice(-199), { timestamp, message, type }])
  }, [])

  const logRaw = useCallback((data: string) => {
    const timestamp = new Date().toLocaleTimeString('en-IN', { hour12: false })
    setRawMessages((prev) => [...prev.slice(-99), `[${timestamp}] ${data}`])
  }, [])

  // CSRF token
  const getCsrfToken = useCallback(async () => fetchCSRFToken(), [])

  // WebSocket connection
  const connectWebSocket = async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      logEvent('Already connected', 'warn')
      return
    }

    setIsConnecting(true)
    logEvent('Initiating connection...', 'info')

    try {
      const csrfToken = await getCsrfToken()
      const configResponse = await fetch('/api/websocket/config', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const configData = await configResponse.json()

      if (configData.status !== 'success') throw new Error('Config fetch failed')

      const wsUrl = configData.websocket_url
      logEvent(`Connecting to ${wsUrl}`, 'info')

      const socket = new WebSocket(wsUrl)

      socket.onopen = async () => {
        logEvent('Connection established', 'success')
        setIsConnected(true)
        setIsConnecting(false)

        try {
          const authCsrfToken = await getCsrfToken()
          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          })
          const apiKeyData = await apiKeyResponse.json()

          if (apiKeyData.status === 'success' && apiKeyData.api_key) {
            socket.send(JSON.stringify({ action: 'authenticate', api_key: apiKeyData.api_key }))
            logEvent('Auth request sent', 'info')
          } else {
            logEvent('No API key found - visit /apikey', 'error')
          }
        } catch (err) {
          logEvent(`Auth error: ${err}`, 'error')
        }
      }

      socket.onclose = (event) => {
        setIsConnected(false)
        setIsConnecting(false)
        setIsAuthenticated(false)
        logEvent(`Disconnected (code: ${event.code})`, event.wasClean ? 'info' : 'error')

        if (autoReconnect && !event.wasClean) {
          logEvent('Auto-reconnect in 3s...', 'warn')
          reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000)
        }
      }

      socket.onerror = () => {
        logEvent('Connection error', 'error')
        setIsConnecting(false)
      }

      socket.onmessage = (event) => {
        setMessageCount((c) => c + 1)
        setLastMessageTime(Date.now())
        logRaw(event.data)
        try {
          const data = JSON.parse(event.data)
          handleMessage(data)
        } catch {
          logEvent('Parse error', 'error')
        }
      }

      socketRef.current = socket
    } catch (err) {
      logEvent(`Connection failed: ${err}`, 'error')
      setIsConnecting(false)
    }
  }

  const disconnectWebSocket = () => {
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
    logEvent('Disconnected by user', 'info')
  }

  // Message handler
  const handleMessage = useCallback(
    (data: Record<string, unknown>) => {
      const type = (data.type || data.status) as string

      switch (type) {
        case 'auth':
          if (data.status === 'success') {
            setIsAuthenticated(true)
            logEvent(`Authenticated: ${data.user_id} @ ${data.broker}`, 'success')
          } else {
            logEvent(`Auth failed: ${data.message}`, 'error')
          }
          break

        case 'market_data': {
          // Normalize symbol by removing :50/:30/:20 suffix for matching
          let symbol = (data.symbol as string).toUpperCase()
          // Strip depth level suffix (e.g., RELIANCE:50 -> RELIANCE)
          symbol = symbol.replace(/:(?:50|30|20)$/, '')
          const exchange = data.exchange as string
          const mode = data.mode as number
          const marketData = (data.data || {}) as MarketData

          setActiveSymbols((prev) => {
            const key = `${exchange}:${symbol}`
            const existing = prev.get(key)
            if (!existing) return prev

            const updated = new Map(prev)
            const newData = { ...existing.data }

            if (mode === 1 || mode === 2) {
              Object.assign(newData, {
                ltp: marketData.ltp ?? newData.ltp,
                open: marketData.open ?? newData.open,
                high: marketData.high ?? newData.high,
                low: marketData.low ?? newData.low,
                close: marketData.close ?? newData.close,
                volume: marketData.volume ?? newData.volume,
                change: marketData.change ?? newData.change,
                change_percent: marketData.change_percent ?? newData.change_percent,
                timestamp: marketData.timestamp ?? newData.timestamp,
              })
            }

            if (mode === 3 && marketData.depth) {
              newData.depth = marketData.depth
            }

            updated.set(key, { ...existing, data: newData, lastUpdate: Date.now() })
            return updated
          })
          break
        }

        case 'subscribe':
          logEvent(
            data.status === 'success' ? 'Subscribed' : `Sub error: ${data.message}`,
            data.status === 'success' ? 'success' : 'error'
          )
          break

        case 'unsubscribe':
          logEvent('Unsubscribed', 'info')
          break

        case 'error':
          logEvent(`Error: ${data.message}`, 'error')
          break
      }
    },
    [logEvent]
  )

  // Subscription controls
  const subscribe = (symbol: string, exchange: string, mode: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      showToast.error('Not connected')
      return
    }

    // Build subscription message
    const subscribeMessage: Record<string, unknown> = {
      action: 'subscribe',
      symbols: [{ symbol: mode === 'Depth' && depthLevel === 50 ? `${symbol}:50` : symbol, exchange }],
      mode,
    }

    // Add depth level for Depth mode
    if (mode === 'Depth' && depthLevel > 5) {
      subscribeMessage.depth = depthLevel
    }

    socketRef.current.send(JSON.stringify(subscribeMessage))

    setActiveSymbols((prev) => {
      const key = `${exchange}:${symbol}`
      const existing = prev.get(key)
      if (!existing) return prev
      const updated = new Map(prev)
      const newSubs = new Set(existing.subscriptions)
      newSubs.add(mode)
      updated.set(key, { ...existing, subscriptions: newSubs })
      return updated
    })

    logEvent(`Sub: ${exchange}:${symbol} [${mode}]`, 'info')
  }

  const unsubscribe = (symbol: string, exchange: string, mode: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return

    const modeMap: Record<string, number> = { LTP: 1, Quote: 2, Depth: 3 }
    const unsubscribeMessage: Record<string, unknown> = {
      action: 'unsubscribe',
      symbols: [{ symbol: mode === 'Depth' && depthLevel === 50 ? `${symbol}:50` : symbol, exchange, mode: modeMap[mode] }],
      mode,
    }

    // Add depth level for Depth mode
    if (mode === 'Depth' && depthLevel > 5) {
      unsubscribeMessage.depth = depthLevel
    }

    socketRef.current.send(JSON.stringify(unsubscribeMessage))

    setActiveSymbols((prev) => {
      const key = `${exchange}:${symbol}`
      const existing = prev.get(key)
      if (!existing) return prev
      const updated = new Map(prev)
      const newSubs = new Set(existing.subscriptions)
      newSubs.delete(mode)
      updated.set(key, { ...existing, subscriptions: newSubs })
      return updated
    })
  }

  const subscribeAll = (mode: string) => {
    if (activeSymbols.size === 0) {
      showToast.error('Add symbols first')
      return
    }
    activeSymbols.forEach((_, key) => {
      const [exchange, symbol] = key.split(':')
      subscribe(symbol, exchange, mode)
    })
  }

  const unsubscribeAll = () => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ action: 'unsubscribe_all' }))
    setActiveSymbols((prev) => {
      const updated = new Map(prev)
      updated.forEach((v, k) => updated.set(k, { ...v, subscriptions: new Set() }))
      return updated
    })
    logEvent('Unsubscribed all', 'info')
  }

  // Search
  const performSearch = useCallback(async (query: string, exchange: string) => {
    if (query.length < 2) {
      setSearchResults([])
      setShowSearchResults(false)
      return
    }

    setIsSearching(true)
    try {
      const params = new URLSearchParams({ q: query })
      if (exchange && exchange !== '_all') params.append('exchange', exchange)

      const response = await fetch(`/search/api/search?${params}`, { credentials: 'include' })
      const data = await response.json()
      setSearchResults((data.results || []).slice(0, 8))
      setShowSearchResults(true)
    } catch (err) {
      setSearchResults([])
    } finally {
      setIsSearching(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery.length >= 2) performSearch(searchQuery, searchExchange)
    }, 200)
    return () => clearTimeout(timer)
  }, [searchQuery, searchExchange, performSearch])

  // Symbol management
  const addSymbol = (symbol: string, exchange: string) => {
    const key = `${exchange}:${symbol}`
    if (activeSymbols.has(key)) {
      showToast.error('Already added')
      return
    }
    setActiveSymbols((prev) =>
      new Map(prev).set(key, { symbol, exchange, data: {}, subscriptions: new Set() })
    )
    setSearchQuery('')
    setShowSearchResults(false)
    logEvent(`Added: ${key}`, 'success')
  }

  const removeSymbol = (symbol: string, exchange: string) => {
    const key = `${exchange}:${symbol}`
    const existing = activeSymbols.get(key)
    existing?.subscriptions.forEach((mode) => unsubscribe(symbol, exchange, mode))
    setActiveSymbols((prev) => {
      const updated = new Map(prev)
      updated.delete(key)
      return updated
    })
    logEvent(`Removed: ${key}`, 'info')
  }

  const clearAllSymbols = () => {
    unsubscribeAll()
    setActiveSymbols(new Map())
    logEvent('Cleared all symbols', 'info')
  }

  // Toggle helpers
  const toggleDepth = (key: string) => {
    setExpandedDepths((prev) => {
      const newSet = new Set(prev)
      newSet.has(key) ? newSet.delete(key) : newSet.add(key)
      return newSet
    })
  }

  const toggleCard = (key: string) => {
    setExpandedCards((prev) => {
      const newSet = new Set(prev)
      newSet.has(key) ? newSet.delete(key) : newSet.add(key)
      return newSet
    })
  }

  // Click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchInputRef.current && !searchInputRef.current.contains(e.target as Node)) {
        setShowSearchResults(false)
      }
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  // Auto-scroll logs when new entries arrive
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentionally triggers on logs/rawMessages changes
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs, rawMessages])

  // Load/save symbols
  useEffect(() => {
    const saved = localStorage.getItem('ws_test_symbols')
    if (saved) {
      try {
        const symbols = JSON.parse(saved)
        const newMap = new Map<string, SymbolData>()
        symbols.forEach((key: string) => {
          const [exchange, symbol] = key.split(':')
          newMap.set(key, { symbol, exchange, data: {}, subscriptions: new Set() })
        })
        setActiveSymbols(newMap)
      } catch (err) {
      }
    }
  }, [])

  useEffect(() => {
    localStorage.setItem('ws_test_symbols', JSON.stringify(Array.from(activeSymbols.keys())))
  }, [activeSymbols])

  // Computed values
  const connectionStatus = isConnected
    ? isAuthenticated
      ? 'success'
      : 'warning'
    : isConnecting
      ? 'warning'
      : 'idle'

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Background texture */}
      <div
        className="fixed inset-0 opacity-[0.015] pointer-events-none"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
        }}
      />

      <div className="relative">
        {/* Header */}
        <header className="border-b border-border bg-background/80 backdrop-blur-xl sticky top-0 z-40">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 via-cyan-500/10 to-transparent border border-cyan-500/30 flex items-center justify-center">
                    <Terminal className="w-6 h-6 text-cyan-400" />
                  </div>
                  <div className="absolute -bottom-0.5 -right-0.5">
                    <StatusOrb status={connectionStatus} />
                  </div>
                </div>
                <div>
                  <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
                    WebSocket Console
                    <Badge
                      variant="outline"
                      className="text-[9px] border-cyan-500/30 text-cyan-400 font-mono"
                    >
                      {depthLevel > 5 ? `DEPTH ${depthLevel}` : 'TEST'}
                    </Badge>
                  </h1>
                  <p className="text-xs text-muted-foreground">
                    {depthLevel > 5
                      ? `${depthLevel}-level market depth testing (broker dependent)`
                      : 'Real-time market data testing interface (independent connection)'}
                  </p>
                </div>
              </div>

              {/* Connection controls */}
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Switch checked={autoReconnect} onCheckedChange={setAutoReconnect} />
                  <span>Auto-reconnect</span>
                </div>

                <div className="flex items-center gap-2">
                  {!isConnected ? (
                    <Button
                      onClick={connectWebSocket}
                      disabled={isConnecting}
                      className="gap-2 bg-gradient-to-r from-cyan-600 to-cyan-500 hover:from-cyan-500 hover:to-cyan-400 text-white font-semibold shadow-lg shadow-cyan-500/20"
                    >
                      {isConnecting ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                      ) : (
                        <Link2 className="w-4 h-4" />
                      )}
                      {isConnecting ? 'Connecting' : 'Connect'}
                    </Button>
                  ) : (
                    <Button
                      onClick={disconnectWebSocket}
                      variant="outline"
                      className="gap-2 border-rose-500/30 text-rose-400 hover:bg-rose-500/10"
                    >
                      <Link2Off className="w-4 h-4" />
                      Disconnect
                    </Button>
                  )}
                </div>

                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/50 border border-border">
                  {isAuthenticated ? (
                    <Wifi className="w-4 h-4 text-emerald-400" />
                  ) : isConnected ? (
                    <Cable className="w-4 h-4 text-amber-400" />
                  ) : (
                    <WifiOff className="w-4 h-4 text-muted-foreground" />
                  )}
                  <span
                    className={cn(
                      'text-sm font-medium',
                      isAuthenticated
                        ? 'text-emerald-400'
                        : isConnected
                          ? 'text-amber-400'
                          : 'text-muted-foreground'
                    )}
                  >
                    {isAuthenticated ? 'Authenticated' : isConnected ? 'Connected' : 'Offline'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </header>

        <main className="container mx-auto px-4 py-6 space-y-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <StatCard
              label="Messages"
              value={messageCount}
              icon={Radio}
              subtitle={
                lastMessageTime
                  ? `${((Date.now() - lastMessageTime) / 1000).toFixed(1)}s ago`
                  : '--'
              }
            />
            <StatCard
              label="Symbols"
              value={activeSymbols.size}
              icon={Layers}
              subtitle={`${Array.from(activeSymbols.values()).filter((s) => s.subscriptions.size > 0).length} subscribed`}
            />
            <StatCard
              label="Status"
              value={isAuthenticated ? 'Ready' : isConnected ? 'Pending' : 'Offline'}
              icon={isAuthenticated ? Wifi : isConnected ? Cable : WifiOff}
              status={connectionStatus}
            />
          </div>

          {/* Symbol Search & Bulk Controls */}
          <div className="rounded-xl bg-card border border-border p-5">
            <div className="flex flex-col lg:flex-row gap-4 mb-4">
              {/* Search */}
              <div className="flex-1 relative" ref={searchInputRef}>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    type="text"
                    placeholder="Search symbols..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onFocus={() => searchQuery.length >= 2 && setShowSearchResults(true)}
                    className="pl-10 bg-muted/50 border-border/50 text-foreground placeholder:text-muted-foreground/60 focus:border-cyan-500/50 focus:ring-cyan-500/20"
                  />
                  {isSearching && (
                    <RefreshCw className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground animate-spin" />
                  )}
                </div>

                {showSearchResults && searchResults.length > 0 && (
                  <div className="absolute z-50 w-full mt-2 rounded-lg border border-border/50 bg-card backdrop-blur-xl shadow-2xl overflow-hidden">
                    {searchResults.map((result, i) => (
                      <div
                        key={i}
                        className="px-4 py-3 border-b border-border/50 last:border-0 hover:bg-cyan-500/5 cursor-pointer transition-colors"
                        onClick={() => addSymbol(result.symbol, result.exchange)}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-semibold text-foreground">{result.symbol}</span>
                            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                              {result.name}
                            </p>
                          </div>
                          <Badge
                            variant="outline"
                            className="text-[10px] border-border text-muted-foreground"
                          >
                            {result.exchange}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Exchange filter */}
              <Select value={searchExchange} onValueChange={setSearchExchange}>
                <SelectTrigger className="w-full lg:w-40 bg-muted/50 border-border/50 text-foreground/80">
                  <SelectValue placeholder="All Exchanges" />
                </SelectTrigger>
                <SelectContent className="bg-card border-border">
                  <SelectItem value="_all">All Exchanges</SelectItem>
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex} value={ex}>
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Active symbols */}
            <div className="flex flex-wrap gap-2 mb-4">
              {Array.from(activeSymbols.entries()).map(([key, data]) => (
                <Badge
                  key={key}
                  variant="secondary"
                  className={cn(
                    'gap-1.5 py-1.5 px-3 border transition-colors',
                    data.subscriptions.size > 0
                      ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300'
                      : 'bg-muted/50 border-border/50 text-muted-foreground'
                  )}
                >
                  <span className="font-mono text-xs">{key}</span>
                  {data.subscriptions.size > 0 && <StatusOrb status="success" size="sm" />}
                  <button
                    type="button"
                    onClick={() => removeSymbol(data.symbol, data.exchange)}
                    className="ml-1 hover:text-rose-400 transition-colors"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
              {activeSymbols.size === 0 && (
                <span className="text-sm text-muted-foreground/60">No symbols. Search to add.</span>
              )}
            </div>

            {/* Bulk controls */}
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => subscribeAll('LTP')}
                variant="outline"
                disabled={!isConnected}
                size="sm"
                className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10 disabled:opacity-30"
              >
                <Zap className="w-3.5 h-3.5 mr-1.5" /> LTP All
              </Button>
              <Button
                onClick={() => subscribeAll('Quote')}
                variant="outline"
                disabled={!isConnected}
                size="sm"
                className="border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 disabled:opacity-30"
              >
                <Activity className="w-3.5 h-3.5 mr-1.5" /> Quote All
              </Button>
              <Button
                onClick={() => subscribeAll('Depth')}
                variant="outline"
                disabled={!isConnected}
                size="sm"
                className="border-violet-500/30 text-violet-400 hover:bg-violet-500/10 disabled:opacity-30"
              >
                <Layers className="w-3.5 h-3.5 mr-1.5" /> Depth {depthLevel > 5 ? depthLevel : ''} All
              </Button>
              <Button
                onClick={unsubscribeAll}
                variant="outline"
                disabled={!isConnected}
                size="sm"
                className="border-rose-500/30 text-rose-400 hover:bg-rose-500/10 disabled:opacity-30"
              >
                <ZapOff className="w-3.5 h-3.5 mr-1.5" /> Unsub All
              </Button>
              <Button
                onClick={clearAllSymbols}
                variant="outline"
                size="sm"
                className="border-border/50 text-muted-foreground hover:bg-muted/50"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Clear All
              </Button>
            </div>
          </div>

          {/* Market Data Cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {Array.from(activeSymbols.entries()).map(([key, symbolData]) => {
              const change = symbolData.data.change ?? 0
              const changePct = symbolData.data.change_percent ?? 0
              const isPositive = change >= 0
              const hasLtp = symbolData.data.ltp !== undefined
              const isLive = !!(symbolData.lastUpdate && Date.now() - symbolData.lastUpdate < 5000)
              const isExpanded = expandedCards.has(key)
              const isDepthExpanded = expandedDepths.has(key)

              return (
                <div
                  key={key}
                  className={cn(
                    'rounded-xl border bg-card overflow-hidden transition-all',
                    isLive ? 'border-cyan-500/40' : 'border-border'
                  )}
                >
                  {/* Live indicator */}
                  {isLive && (
                    <div className="h-0.5 bg-gradient-to-r from-cyan-500 via-emerald-500 to-cyan-500" />
                  )}

                  {/* Card header */}
                  <div className="flex items-center justify-between p-4 border-b border-border/40">
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => toggleCard(key)}
                        className="hover:text-cyan-400 transition-colors"
                      >
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                      <span className="font-bold font-mono text-lg">{key}</span>
                      {isLive && <StatusOrb status="success" size="sm" />}
                    </div>

                    {/* Per-symbol subscription toggles */}
                    <div className="flex gap-1">
                      {(['LTP', 'Quote', 'Depth'] as const).map((mode) => {
                        const isActive = symbolData.subscriptions.has(mode)
                        const displayLabel = mode === 'Depth' && depthLevel > 5 ? `D${depthLevel}` : mode
                        return (
                          <button
                            type="button"
                            key={mode}
                            onClick={() =>
                              isActive
                                ? unsubscribe(symbolData.symbol, symbolData.exchange, mode)
                                : subscribe(symbolData.symbol, symbolData.exchange, mode)
                            }
                            className={cn(
                              'px-2.5 py-1 text-[10px] font-bold rounded-md transition-all',
                              isActive
                                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                                : 'bg-muted/50 text-muted-foreground border border-border/50 hover:text-foreground'
                            )}
                          >
                            {displayLabel}
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  {/* Card content */}
                  <div className="p-4">
                    {/* LTP + Change */}
                    <div className="flex items-end justify-between mb-4">
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                          LTP
                        </div>
                        <div className="text-3xl font-bold font-mono tracking-tight">
                          {hasLtp ? `₹${formatPrice(symbolData.data.ltp!)}` : '---'}
                        </div>
                      </div>
                      {hasLtp && (
                        <div
                          className={cn(
                            'flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm font-semibold',
                            isPositive
                              ? 'bg-emerald-500/10 text-emerald-400'
                              : 'bg-rose-500/10 text-rose-400'
                          )}
                        >
                          {isPositive ? (
                            <TrendingUp className="w-4 h-4" />
                          ) : (
                            <TrendingDown className="w-4 h-4" />
                          )}
                          {isPositive ? '+' : ''}
                          {changePct.toFixed(2)}%
                        </div>
                      )}
                    </div>

                    {/* OHLCV */}
                    {(isExpanded || hasLtp) && (
                      <div className="grid grid-cols-5 gap-2 mb-4">
                        {[
                          { label: 'Open', value: symbolData.data.open },
                          { label: 'High', value: symbolData.data.high, color: 'text-emerald-400' },
                          { label: 'Low', value: symbolData.data.low, color: 'text-rose-400' },
                          { label: 'Close', value: symbolData.data.close },
                          { label: 'Vol', value: symbolData.data.volume, format: 'volume' },
                        ].map((item) => (
                          <div key={item.label} className="bg-muted/50 rounded-lg px-2 py-1.5">
                            <div className="text-[8px] uppercase tracking-wider text-muted-foreground">
                              {item.label}
                            </div>
                            <div
                              className={cn(
                                'text-xs font-mono font-semibold mt-0.5',
                                item.color || 'text-foreground/80'
                              )}
                            >
                              {item.value !== undefined
                                ? item.format === 'volume'
                                  ? formatVolume(item.value)
                                  : formatPrice(item.value)
                                : '--'}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Market Depth */}
                    {symbolData.data.depth && (
                      <div>
                        <button
                          type="button"
                          onClick={() => toggleDepth(key)}
                          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
                        >
                          <ChevronDown
                            className={cn(
                              'w-3 h-3 transition-transform',
                              isDepthExpanded && 'rotate-180'
                            )}
                          />
                          Market Depth ({symbolData.data.depth.buy.length}/
                          {symbolData.data.depth.sell.length})
                        </button>

                        {isDepthExpanded && (
                          <div className="grid grid-cols-2 gap-4 p-3 bg-muted/30 rounded-lg border border-border/40 max-h-[400px] overflow-y-auto">
                            <div>
                              <div className="text-[9px] uppercase tracking-wider text-emerald-400 mb-2 flex items-center gap-1 sticky top-0 bg-muted/30 py-1">
                                <ArrowUp className="w-3 h-3" /> Bids
                              </div>
                              {symbolData.data.depth.buy.slice(0, depthLevel).map((level, i) => (
                                <DepthLevel
                                  key={i}
                                  price={level.price}
                                  quantity={level.quantity}
                                  maxQty={Math.max(
                                    1,
                                    ...symbolData.data.depth!.buy.map((l) => l.quantity)
                                  )}
                                  side="buy"
                                />
                              ))}
                            </div>
                            <div>
                              <div className="text-[9px] uppercase tracking-wider text-rose-400 mb-2 flex items-center gap-1 sticky top-0 bg-muted/30 py-1">
                                <ArrowDown className="w-3 h-3" /> Asks
                              </div>
                              {symbolData.data.depth.sell.slice(0, depthLevel).map((level, i) => (
                                <DepthLevel
                                  key={i}
                                  price={level.price}
                                  quantity={level.quantity}
                                  maxQty={Math.max(
                                    1,
                                    ...symbolData.data.depth!.sell.map((l) => l.quantity)
                                  )}
                                  side="sell"
                                />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Timestamp */}
                    <div className="text-[10px] text-muted-foreground/60 mt-3 font-mono">
                      {formatTime(symbolData.data.timestamp)}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Event Log */}
          <div className="rounded-xl bg-card border border-border overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
              <div className="flex items-center gap-3">
                <Terminal className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm font-medium text-muted-foreground">Console</span>
                <Badge variant="outline" className="text-[9px] border-border text-muted-foreground">
                  {showRawLogs ? rawMessages.length : logs.length}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowRawLogs(!showRawLogs)}
                  className={cn(
                    'h-7 px-2 text-xs',
                    showRawLogs ? 'text-cyan-400' : 'text-muted-foreground'
                  )}
                >
                  <Settings2 className="w-3.5 h-3.5 mr-1" />
                  {showRawLogs ? 'Parsed' : 'Raw'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setLogs([])
                    setRawMessages([])
                  }}
                  className="h-7 px-2 text-muted-foreground hover:text-foreground"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>

            <div
              ref={logContainerRef}
              className="h-56 overflow-y-auto p-4 font-mono text-xs space-y-0.5"
            >
              {showRawLogs ? (
                rawMessages.length === 0 ? (
                  <div className="text-muted-foreground/60">No raw messages...</div>
                ) : (
                  rawMessages.map((msg, i) => (
                    <div key={i} className="text-muted-foreground break-all">
                      {msg}
                    </div>
                  ))
                )
              ) : logs.length === 0 ? (
                <div className="text-muted-foreground/60">Waiting for events...</div>
              ) : (
                logs.map((log, i) => (
                  <div
                    key={i}
                    className={cn(
                      'py-0.5',
                      log.type === 'success' && 'text-emerald-400',
                      log.type === 'error' && 'text-rose-400',
                      log.type === 'warn' && 'text-amber-400',
                      log.type === 'data' && 'text-cyan-400',
                      log.type === 'info' && 'text-muted-foreground'
                    )}
                  >
                    <span className="text-muted-foreground/60">[{log.timestamp}]</span>{' '}
                    {log.message}
                  </div>
                ))
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
