import {
  Cable,
  Link2,
  Link2Off,
  Radio,
  RefreshCw,
  Terminal,
  Trash2,
  Wifi,
  WifiOff,
  Zap,
  ZapOff,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

interface OrderUpdate {
  orderid: string
  symbol: string
  exchange: string
  action: string
  quantity: number
  pricetype: string
  product: string
  order_status: string
  filled_quantity: number
  pending_quantity: number
  average_price: number
  rejection_reason: string
  broker: string
  mode: string
  receivedAt: number
}

interface LogEntry {
  timestamp: string
  message: string
  type: 'info' | 'success' | 'error' | 'data' | 'warn'
}

function formatPrice(price: number): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(price)
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

export default function WebSocketOrder() {
  // Connection state - INDEPENDENT WebSocket (dedicated order-update stream)
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [autoReconnect, setAutoReconnect] = useState(true)
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Metrics
  const [messageCount, setMessageCount] = useState(0)
  const [lastMessageTime, setLastMessageTime] = useState<number | null>(null)

  // Order updates (account-level stream, no symbols)
  const [ordersSubscribed, setOrdersSubscribed] = useState(false)
  const [orderUpdates, setOrderUpdates] = useState<OrderUpdate[]>([])

  // UI state
  const [logs, setLogs] = useState<LogEntry[]>([])
  const logContainerRef = useRef<HTMLDivElement>(null)

  // Logging
  const logEvent = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    const timestamp = new Date().toLocaleTimeString('en-IN', { hour12: false })
    setLogs((prev) => [...prev.slice(-199), { timestamp, message, type }])
  }, [])

  // CSRF token
  const getCsrfToken = useCallback(async () => fetchCSRFToken(), [])

  const sendSubscribeOrders = useCallback(() => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return
    socketRef.current.send(JSON.stringify({ action: 'subscribe_orders' }))
    logEvent('Subscribing order updates...', 'info')
  }, [logEvent])

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

        case 'subscribe_orders':
          if (data.status === 'success') {
            setOrdersSubscribed(true)
            logEvent('Subscribed to order updates', 'success')
          } else {
            logEvent(`Order sub error: ${data.message}`, 'error')
          }
          break

        case 'unsubscribe_orders':
          setOrdersSubscribed(false)
          logEvent('Unsubscribed from order updates', 'info')
          break

        case 'order_update': {
          const update: OrderUpdate = {
            orderid: String(data.orderid ?? ''),
            symbol: String(data.symbol ?? ''),
            exchange: String(data.exchange ?? ''),
            action: String(data.action ?? ''),
            quantity: Number(data.quantity ?? 0),
            pricetype: String(data.pricetype ?? ''),
            product: String(data.product ?? ''),
            order_status: String(data.order_status ?? ''),
            filled_quantity: Number(data.filled_quantity ?? 0),
            pending_quantity: Number(data.pending_quantity ?? 0),
            average_price: Number(data.average_price ?? 0),
            rejection_reason: String(data.rejection_reason ?? ''),
            broker: String(data.broker ?? ''),
            mode: String(data.mode ?? ''),
            receivedAt: Date.now(),
          }
          setOrderUpdates((prev) => [update, ...prev].slice(0, 200))
          logEvent(
            `Order ${update.orderid} ${update.order_status}${update.symbol ? ` (${update.symbol})` : ''}`,
            update.order_status === 'rejected' ? 'error' : 'data'
          )
          break
        }

        case 'error':
          logEvent(`Error: ${data.message}`, 'error')
          break
      }
    },
    [logEvent]
  )

  // WebSocket connection
  const connectWebSocket = useCallback(async () => {
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
        setOrdersSubscribed(false)
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
  }, [autoReconnect, getCsrfToken, handleMessage, logEvent])

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
    setOrdersSubscribed(false)
    logEvent('Disconnected by user', 'info')
  }

  // Order-update stream toggle (account-level, no symbols)
  const toggleOrderUpdates = () => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      showToast.error('Not connected')
      return
    }
    if (ordersSubscribed) {
      socketRef.current.send(JSON.stringify({ action: 'unsubscribe_orders' }))
      logEvent('Unsubscribing order updates...', 'info')
    } else {
      sendSubscribeOrders()
    }
  }

  // Auto-scroll logs when new entries arrive
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentionally triggers on logs changes
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs])

  // Clean up socket on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      if (socketRef.current) {
        socketRef.current.close(1000, 'Page unmount')
        socketRef.current = null
      }
    }
  }, [])

  // Computed values
  const connectionStatus = isConnected
    ? isAuthenticated
      ? 'success'
      : 'warning'
    : isConnecting
      ? 'warning'
      : 'idle'

  const filledCount = useMemo(
    () => orderUpdates.filter((u) => u.order_status === 'complete').length,
    [orderUpdates]
  )
  const rejectedCount = useMemo(
    () => orderUpdates.filter((u) => u.order_status === 'rejected').length,
    [orderUpdates]
  )

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
                    <Radio className="w-6 h-6 text-cyan-400" />
                  </div>
                  <div className="absolute -bottom-0.5 -right-0.5">
                    <StatusOrb status={connectionStatus} />
                  </div>
                </div>
                <div>
                  <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
                    Order Stream
                    <Badge
                      variant="outline"
                      className="text-[9px] border-cyan-500/30 text-cyan-400 font-mono"
                    >
                      WS
                    </Badge>
                  </h1>
                  <p className="text-xs text-muted-foreground">
                    Real-time order status stream over WebSocket (independent connection)
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
            <StatCard label="Orders" value={orderUpdates.length} icon={Terminal} />
            <StatCard
              label="Filled"
              value={filledCount}
              icon={Zap}
              status={filledCount > 0 ? 'success' : 'idle'}
            />
            <StatCard
              label="Rejected"
              value={rejectedCount}
              icon={ZapOff}
              status={rejectedCount > 0 ? 'error' : 'idle'}
            />
          </div>

          {/* Order Updates (account-level stream) */}
          <div className="rounded-xl bg-card border border-border p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Radio className="w-4 h-4 text-cyan-400" />
                <h2 className="text-sm font-semibold text-foreground">Order Updates</h2>
                {ordersSubscribed && <StatusOrb status="success" size="sm" />}
                <span className="text-xs text-muted-foreground">
                  {ordersSubscribed
                    ? 'Live — fills, rejections and cancels stream here'
                    : 'Real-time order status stream (no symbols needed)'}
                </span>
              </div>
              <div className="flex items-center gap-3">
                {orderUpdates.length > 0 && (
                  <Button
                    onClick={() => setOrderUpdates([])}
                    variant="outline"
                    size="sm"
                    className="border-border/50 text-muted-foreground hover:bg-muted/50"
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> Clear
                  </Button>
                )}
                <Button
                  onClick={toggleOrderUpdates}
                  variant="outline"
                  disabled={!isAuthenticated}
                  size="sm"
                  className={cn(
                    'disabled:opacity-30',
                    ordersSubscribed
                      ? 'border-rose-500/30 text-rose-400 hover:bg-rose-500/10'
                      : 'border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10'
                  )}
                >
                  {ordersSubscribed ? (
                    <>
                      <ZapOff className="w-3.5 h-3.5 mr-1.5" /> Unsubscribe
                    </>
                  ) : (
                    <>
                      <Zap className="w-3.5 h-3.5 mr-1.5" /> Subscribe
                    </>
                  )}
                </Button>
              </div>
            </div>

            {orderUpdates.length === 0 ? (
              <p className="text-sm text-muted-foreground/60">
                {ordersSubscribed
                  ? 'Waiting for order events… place, fill, reject or cancel an order to see updates.'
                  : 'Connect and subscribe, then order status changes (from the broker feed or analyzer mode) appear here in real time.'}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted-foreground border-b border-border/50">
                      <th className="py-2 pr-3 font-medium">Time</th>
                      <th className="py-2 pr-3 font-medium">Order ID</th>
                      <th className="py-2 pr-3 font-medium">Symbol</th>
                      <th className="py-2 pr-3 font-medium">Action</th>
                      <th className="py-2 pr-3 font-medium">Type</th>
                      <th className="py-2 pr-3 font-medium">Status</th>
                      <th className="py-2 pr-3 font-medium text-right">Filled</th>
                      <th className="py-2 pr-3 font-medium text-right">Avg Price</th>
                      <th className="py-2 font-medium">Info</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderUpdates.map((u, i) => (
                      <tr
                        key={`${u.orderid}-${u.receivedAt}-${i}`}
                        className="border-b border-border/30 last:border-0"
                      >
                        <td className="py-2 pr-3 text-muted-foreground font-mono">
                          {new Date(u.receivedAt).toLocaleTimeString('en-IN', { hour12: false })}
                        </td>
                        <td className="py-2 pr-3 font-mono text-foreground/80">{u.orderid}</td>
                        <td className="py-2 pr-3 font-semibold text-foreground">
                          {u.symbol}
                          {u.exchange && (
                            <span className="ml-1 text-[10px] text-muted-foreground">
                              {u.exchange}
                            </span>
                          )}
                        </td>
                        <td
                          className={cn(
                            'py-2 pr-3 font-medium',
                            u.action === 'BUY' && 'text-emerald-400',
                            u.action === 'SELL' && 'text-rose-400'
                          )}
                        >
                          {u.action}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground">
                          {u.pricetype}
                          {u.product && ` · ${u.product}`}
                        </td>
                        <td className="py-2 pr-3">
                          <Badge
                            variant="outline"
                            className={cn(
                              'text-[10px] uppercase',
                              u.order_status === 'complete' &&
                                'border-emerald-500/30 text-emerald-400',
                              u.order_status === 'rejected' && 'border-rose-500/30 text-rose-400',
                              u.order_status === 'cancelled' &&
                                'border-amber-500/30 text-amber-400',
                              u.order_status === 'open' && 'border-cyan-500/30 text-cyan-400'
                            )}
                          >
                            {u.order_status}
                          </Badge>
                        </td>
                        <td className="py-2 pr-3 text-right font-mono text-foreground/80">
                          {u.filled_quantity}/{u.quantity}
                        </td>
                        <td className="py-2 pr-3 text-right font-mono text-foreground/80">
                          {u.average_price ? formatPrice(u.average_price) : '--'}
                        </td>
                        <td className="py-2 text-muted-foreground max-w-[200px] truncate">
                          {u.rejection_reason || (u.mode === 'analyze' ? 'sandbox' : u.broker)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Event Log */}
          <div className="rounded-xl bg-card border border-border overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
              <div className="flex items-center gap-3">
                <Terminal className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm font-medium text-muted-foreground">Console</span>
                <Badge variant="outline" className="text-[9px] border-border text-muted-foreground">
                  {logs.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setLogs([])}
                className="h-7 px-2 text-muted-foreground hover:text-foreground"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>

            <div
              ref={logContainerRef}
              className="h-56 overflow-y-auto p-4 font-mono text-xs space-y-0.5"
            >
              {logs.length === 0 ? (
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
