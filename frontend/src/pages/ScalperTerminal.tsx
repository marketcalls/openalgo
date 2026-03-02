import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useMarketData } from '@/hooks/useMarketData'
import { tradingApi } from '@/api/trading'
import { optionChainApi } from '@/api/option-chain'
import type { PlaceOrderRequest } from '@/types/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { showToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

// ==================== Constants ====================

const UNDERLYINGS = [
  { value: 'NIFTY', exchange: 'NFO', strikeGap: 50, lotSize: 75 },
  { value: 'BANKNIFTY', exchange: 'NFO', strikeGap: 100, lotSize: 15 },
  { value: 'FINNIFTY', exchange: 'NFO', strikeGap: 50, lotSize: 25 },
  { value: 'MIDCPNIFTY', exchange: 'NFO', strikeGap: 25, lotSize: 50 },
  { value: 'SENSEX', exchange: 'BFO', strikeGap: 100, lotSize: 10 },
  { value: 'BANKEX', exchange: 'BFO', strikeGap: 100, lotSize: 15 },
]

const LOT_PRESETS = [1, 2, 3, 5, 10]

const INDEX_EXCHANGE_MAP: Record<string, string> = {
  NIFTY: 'NSE',
  BANKNIFTY: 'NSE',
  FINNIFTY: 'NSE',
  MIDCPNIFTY: 'NSE',
  SENSEX: 'BSE',
  BANKEX: 'BSE',
}

// ==================== Helpers ====================

function formatPrice(price: number | null | undefined): string {
  if (price === null || price === undefined) return '0.00'
  return price.toFixed(2)
}

function convertExpiryToSymbol(expiry: string): string {
  // Expiry comes as "06-MAR-25" → "06MAR25" for symbol construction
  return expiry.replace(/-/g, '')
}

function buildOptionSymbol(underlying: string, expiry: string, strike: number, type: 'CE' | 'PE'): string {
  const exp = convertExpiryToSymbol(expiry)
  return `${underlying}${exp}${strike}${type}`
}

// ==================== Types ====================

interface ScalperPosition {
  symbol: string
  exchange: string
  product: string
  quantity: number
  averagePrice: number
  ltp: number
  pnl: number
}

// ==================== Component ====================

function ScalperTerminal() {
  const { apiKey } = useAuthStore()

  // Core state
  const [underlying, setUnderlying] = useState('NIFTY')
  const [expiry, setExpiry] = useState('')
  const [expiries, setExpiries] = useState<string[]>([])
  const [product, setProduct] = useState<'MIS' | 'NRML'>('MIS')
  const [lots, setLots] = useState(1)
  const [customLots, setCustomLots] = useState('')

  // Strike state
  const [spotLtp, setSpotLtp] = useState(0)
  const [atmStrike, setAtmStrike] = useState(0)
  const [strikeOffset, setStrikeOffset] = useState(0)

  // UI state
  const [isLoadingExpiries, setIsLoadingExpiries] = useState(false)
  const [isRefreshingLtp, setIsRefreshingLtp] = useState(false)
  const [orderInProgress, setOrderInProgress] = useState<string | null>(null) // null | 'BUY-CE' | 'BUY-PE' | 'SELL-CE' | 'SELL-PE'
  const [isExitingAll, setIsExitingAll] = useState(false)
  const [exitingPosition, setExitingPosition] = useState<string | null>(null)
  const [positions, setPositions] = useState<ScalperPosition[]>([])
  const [isLoadingPositions, setIsLoadingPositions] = useState(false)

  // Refs
  const positionTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const priceTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Derived values
  const underlyingConfig = useMemo(
    () => UNDERLYINGS.find((u) => u.value === underlying)!,
    [underlying]
  )
  const currentStrike = useMemo(
    () => atmStrike + strikeOffset * underlyingConfig.strikeGap,
    [atmStrike, strikeOffset, underlyingConfig.strikeGap]
  )
  const ceSymbol = useMemo(
    () => (expiry && currentStrike ? buildOptionSymbol(underlying, expiry, currentStrike, 'CE') : ''),
    [underlying, expiry, currentStrike]
  )
  const peSymbol = useMemo(
    () => (expiry && currentStrike ? buildOptionSymbol(underlying, expiry, currentStrike, 'PE') : ''),
    [underlying, expiry, currentStrike]
  )
  const quantity = lots * underlyingConfig.lotSize

  // WebSocket subscriptions for CE and PE prices
  const wsSymbols = useMemo(() => {
    const syms: Array<{ symbol: string; exchange: string }> = []
    if (ceSymbol) syms.push({ symbol: ceSymbol, exchange: underlyingConfig.exchange })
    if (peSymbol) syms.push({ symbol: peSymbol, exchange: underlyingConfig.exchange })
    return syms
  }, [ceSymbol, peSymbol, underlyingConfig.exchange])

  const { data: marketData, isConnected } = useMarketData({
    symbols: wsSymbols,
    mode: 'Quote',
    enabled: wsSymbols.length > 0,
  })

  const cePrice = useMemo(() => {
    if (!ceSymbol) return 0
    const key = `${underlyingConfig.exchange}:${ceSymbol}`
    return marketData.get(key)?.data?.ltp ?? 0
  }, [marketData, ceSymbol, underlyingConfig.exchange])

  const pePrice = useMemo(() => {
    if (!peSymbol) return 0
    const key = `${underlyingConfig.exchange}:${peSymbol}`
    return marketData.get(key)?.data?.ltp ?? 0
  }, [marketData, peSymbol, underlyingConfig.exchange])

  // Previous prices for flash animation
  const prevCePrice = useRef(0)
  const prevPePrice = useRef(0)
  const [ceFlash, setCeFlash] = useState<'up' | 'down' | null>(null)
  const [peFlash, setPeFlash] = useState<'up' | 'down' | null>(null)

  useEffect(() => {
    if (cePrice && prevCePrice.current && cePrice !== prevCePrice.current) {
      setCeFlash(cePrice > prevCePrice.current ? 'up' : 'down')
      const timer = setTimeout(() => setCeFlash(null), 500)
      return () => clearTimeout(timer)
    }
    prevCePrice.current = cePrice
  }, [cePrice])

  useEffect(() => {
    if (pePrice && prevPePrice.current && pePrice !== prevPePrice.current) {
      setPeFlash(pePrice > prevPePrice.current ? 'up' : 'down')
      const timer = setTimeout(() => setPeFlash(null), 500)
      return () => clearTimeout(timer)
    }
    prevPePrice.current = pePrice
  }, [pePrice])

  // ==================== API Calls ====================

  const loadExpiries = useCallback(async () => {
    if (!apiKey) return
    setIsLoadingExpiries(true)
    try {
      const response = await optionChainApi.getExpiries(apiKey, underlying, underlyingConfig.exchange)
      if (response.status === 'success' && response.data?.length > 0) {
        setExpiries(response.data)
        setExpiry(response.data[0])
      } else {
        showToast.error('Failed to load expiries')
        setExpiries([])
      }
    } catch {
      showToast.error('Failed to load expiries')
      setExpiries([])
    }
    setIsLoadingExpiries(false)
  }, [apiKey, underlying, underlyingConfig.exchange])

  const refreshLtp = useCallback(async () => {
    if (!apiKey) return
    setIsRefreshingLtp(true)
    try {
      const indexExchange = INDEX_EXCHANGE_MAP[underlying] || 'NSE'
      const symbol = `${underlying}`
      const response = await tradingApi.getQuotes(apiKey, symbol, indexExchange)
      if (response.status === 'success' && response.data) {
        const ltp = response.data.ltp
        setSpotLtp(ltp)
        const atm = Math.round(ltp / underlyingConfig.strikeGap) * underlyingConfig.strikeGap
        setAtmStrike(atm)
        setStrikeOffset(0)
      } else {
        showToast.error('Failed to fetch LTP')
      }
    } catch {
      showToast.error('Failed to fetch LTP')
    }
    setIsRefreshingLtp(false)
  }, [apiKey, underlying, underlyingConfig.strikeGap])

  const refreshPositions = useCallback(async () => {
    if (!apiKey) return
    setIsLoadingPositions(true)
    try {
      const response = await tradingApi.getPositions(apiKey)
      if (response.status === 'success' && response.data) {
        // Filter to only FnO positions with non-zero quantity
        const fnoPositions = response.data
          .filter((p) => {
            const isFnO = p.exchange === 'NFO' || p.exchange === 'BFO'
            return isFnO && p.quantity !== 0
          })
          .map((p) => ({
            symbol: p.symbol,
            exchange: p.exchange,
            product: p.product,
            quantity: p.quantity,
            averagePrice: p.average_price,
            ltp: p.ltp,
            pnl: p.pnl,
          }))
        setPositions(fnoPositions)
      }
    } catch {
      console.error('Failed to fetch positions')
    }
    setIsLoadingPositions(false)
  }, [apiKey])

  const placeOrder = useCallback(
    async (optionType: 'CE' | 'PE', action: 'BUY' | 'SELL') => {
      if (!apiKey || orderInProgress) return
      if (!expiry) {
        showToast.warning('Select an expiry first')
        return
      }

      const symbol = optionType === 'CE' ? ceSymbol : peSymbol
      if (!symbol) {
        showToast.error('Symbol not ready')
        return
      }

      const orderId = `${action}-${optionType}`
      setOrderInProgress(orderId)

      try {
        const orderReq: PlaceOrderRequest = {
          apikey: apiKey,
          strategy: 'Scalper',
          exchange: underlyingConfig.exchange,
          symbol,
          action,
          quantity,
          pricetype: 'MARKET',
          product,
        }

        const response = await tradingApi.placeOrder(orderReq)
        if (response.status === 'success') {
          showToast.success(`${action} ${optionType} order placed`, 'orders')
        } else {
          showToast.error(response.message || 'Order failed', 'orders')
        }

        // Refresh positions after order
        setTimeout(() => refreshPositions(), 1000)
      } catch (e) {
        showToast.error(`Order failed: ${e instanceof Error ? e.message : 'Unknown error'}`, 'orders')
      }

      setOrderInProgress(null)
    },
    [apiKey, expiry, ceSymbol, peSymbol, underlyingConfig.exchange, quantity, product, orderInProgress, refreshPositions]
  )

  const exitPosition = useCallback(
    async (pos: ScalperPosition) => {
      setExitingPosition(pos.symbol)
      try {
        const response = await tradingApi.closePosition(pos.symbol, pos.exchange, pos.product)
        if (response.status === 'success') {
          showToast.success(`Exited ${pos.symbol}`, 'orders')
        } else {
          showToast.error(response.message || 'Exit failed', 'orders')
        }
        setTimeout(() => refreshPositions(), 1000)
      } catch (e) {
        showToast.error(`Exit failed: ${e instanceof Error ? e.message : 'Unknown error'}`, 'orders')
      }
      setExitingPosition(null)
    },
    [refreshPositions]
  )

  const exitAllPositions = useCallback(async () => {
    if (positions.length === 0) {
      showToast.info('No positions to exit')
      return
    }
    setIsExitingAll(true)
    try {
      const response = await tradingApi.closeAllPositions()
      if (response.status === 'success') {
        showToast.success('All positions closed', 'orders')
      } else {
        showToast.error(response.message || 'Exit all failed', 'orders')
      }
      setTimeout(() => refreshPositions(), 1000)
    } catch (e) {
      showToast.error(`Exit all failed: ${e instanceof Error ? e.message : 'Unknown error'}`, 'orders')
    }
    setIsExitingAll(false)
  }, [positions.length, refreshPositions])

  // ==================== Effects ====================

  // Load expiries on underlying change
  useEffect(() => {
    loadExpiries()
  }, [loadExpiries])

  // Refresh LTP when expiry changes
  useEffect(() => {
    if (expiry) {
      refreshLtp()
    }
  }, [expiry, refreshLtp])

  // Auto-refresh positions periodically
  useEffect(() => {
    if (spotLtp > 0) {
      refreshPositions()
      positionTimerRef.current = setInterval(refreshPositions, 5000)
    }
    return () => {
      if (positionTimerRef.current) clearInterval(positionTimerRef.current)
    }
  }, [spotLtp, refreshPositions])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (positionTimerRef.current) clearInterval(positionTimerRef.current)
      if (priceTimerRef.current) clearInterval(priceTimerRef.current)
    }
  }, [])

  // ==================== Keyboard Shortcuts ====================

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'SELECT' || target.tagName === 'TEXTAREA') return

      switch (e.key) {
        case 'C': // Shift+C → Sell CE
          e.preventDefault()
          placeOrder('CE', 'SELL')
          break
        case 'P': // Shift+P → Sell PE
          e.preventDefault()
          placeOrder('PE', 'SELL')
          break
        case 'c': // c → Buy CE
          e.preventDefault()
          placeOrder('CE', 'BUY')
          break
        case 'p': // p → Buy PE
          e.preventDefault()
          placeOrder('PE', 'BUY')
          break
        case 'x':
          e.preventDefault()
          exitAllPositions()
          break
        case 'r':
          e.preventDefault()
          refreshLtp()
          break
        case 'ArrowLeft':
          e.preventDefault()
          setStrikeOffset((prev) => prev - 1)
          break
        case 'ArrowRight':
          e.preventDefault()
          setStrikeOffset((prev) => prev + 1)
          break
        case 'ArrowUp':
          e.preventDefault()
          setLots((prev) => {
            const idx = LOT_PRESETS.indexOf(prev)
            if (idx >= 0 && idx < LOT_PRESETS.length - 1) return LOT_PRESETS[idx + 1]
            return Math.max(1, prev + 1)
          })
          break
        case 'ArrowDown':
          e.preventDefault()
          setLots((prev) => {
            const idx = LOT_PRESETS.indexOf(prev)
            if (idx > 0) return LOT_PRESETS[idx - 1]
            return Math.max(1, prev - 1)
          })
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [placeOrder, exitAllPositions, refreshLtp])

  // ==================== Lot Selection ====================

  const handleLotPreset = useCallback((n: number) => {
    setLots(n)
    setCustomLots('')
  }, [])

  const handleCustomLots = useCallback((val: string) => {
    setCustomLots(val)
    const n = parseInt(val)
    if (n && n > 0) setLots(n)
  }, [])

  // ==================== Computed ====================

  const strikeLabel = useMemo(() => {
    if (strikeOffset === 0) return 'ATM'
    if (strikeOffset > 0) return `ATM + ${strikeOffset} (OTM CE / ITM PE)`
    return `ATM ${strikeOffset} (ITM CE / OTM PE)`
  }, [strikeOffset])

  const totalPnl = useMemo(
    () => positions.reduce((sum, p) => sum + p.pnl, 0),
    [positions]
  )

  // ==================== Render ====================

  return (
    <TooltipProvider>
      <div className="space-y-4">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-primary" />
            <h1 className="text-2xl font-bold">Scalper Terminal</h1>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={isConnected ? 'default' : 'destructive'} className="text-xs">
              {isConnected ? 'Live' : 'Offline'}
            </Badge>
          </div>
        </div>

        {/* Top Controls Bar */}
        <Card>
          <CardContent className="p-4">
            <div className="flex flex-wrap items-end gap-4">
              {/* Underlying */}
              <div className="w-44">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Underlying
                </label>
                <Select
                  value={underlying}
                  onValueChange={(val) => {
                    setUnderlying(val)
                    setStrikeOffset(0)
                    setSpotLtp(0)
                    setAtmStrike(0)
                  }}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {UNDERLYINGS.map((u) => (
                      <SelectItem key={u.value} value={u.value}>
                        {u.value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Expiry */}
              <div className="w-48">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Expiry
                </label>
                <Select
                  value={expiry}
                  onValueChange={setExpiry}
                  disabled={isLoadingExpiries || expiries.length === 0}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder={isLoadingExpiries ? 'Loading...' : 'Select expiry'} />
                  </SelectTrigger>
                  <SelectContent>
                    {expiries.map((exp) => (
                      <SelectItem key={exp} value={exp}>
                        {exp}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Product */}
              <div className="w-36">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1 block">
                  Product
                </label>
                <Select value={product} onValueChange={(v) => setProduct(v as 'MIS' | 'NRML')}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MIS">MIS (Intraday)</SelectItem>
                    <SelectItem value="NRML">NRML (Carry)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Refresh */}
              <Button
                variant="outline"
                size="sm"
                onClick={refreshLtp}
                disabled={isRefreshingLtp}
                className="h-9"
              >
                <RefreshCw className={cn('h-4 w-4 mr-1', isRefreshingLtp && 'animate-spin')} />
                Refresh
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Main Trading Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left: Strike & Order Panel */}
          <div className="lg:col-span-2 space-y-4">
            {/* Strike Selection & Prices */}
            <Card>
              <CardContent className="p-4">
                {/* LTP Row */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-muted-foreground uppercase">
                      {underlying}
                    </span>
                    <span className={cn('text-xl font-bold', isRefreshingLtp && 'opacity-50 animate-pulse')}>
                      {spotLtp > 0 ? formatPrice(spotLtp) : '--'}
                    </span>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    ATM: {atmStrike > 0 ? atmStrike : '--'}
                  </Badge>
                </div>

                {/* Strike Display */}
                <div className="flex items-center justify-center gap-4 py-4">
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-9 w-9 rounded-full"
                    onClick={() => setStrikeOffset((prev) => prev - 1)}
                  >
                    <ChevronLeft className="h-5 w-5" />
                  </Button>
                  <div className="text-center">
                    <div className="text-4xl font-extrabold tabular-nums tracking-tight">
                      {currentStrike > 0 ? currentStrike : '--'}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">{strikeLabel}</div>
                  </div>
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-9 w-9 rounded-full"
                    onClick={() => setStrikeOffset((prev) => prev + 1)}
                  >
                    <ChevronRight className="h-5 w-5" />
                  </Button>
                </div>

                {/* CE / PE Prices */}
                <div className="grid grid-cols-2 gap-4 mt-2">
                  <div className="rounded-lg p-3 text-center border bg-emerald-500/10 border-emerald-500/20">
                    <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 uppercase mb-1">
                      CE Price
                    </div>
                    <div
                      className={cn(
                        'text-lg font-semibold tabular-nums transition-colors duration-150',
                        ceFlash === 'up' && 'text-emerald-500',
                        ceFlash === 'down' && 'text-red-500'
                      )}
                    >
                      {cePrice > 0 ? `₹${formatPrice(cePrice)}` : '--'}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 truncate" title={ceSymbol}>
                      {ceSymbol || '--'}
                    </div>
                  </div>
                  <div className="rounded-lg p-3 text-center border bg-red-500/10 border-red-500/20">
                    <div className="text-xs font-semibold text-red-600 dark:text-red-400 uppercase mb-1">
                      PE Price
                    </div>
                    <div
                      className={cn(
                        'text-lg font-semibold tabular-nums transition-colors duration-150',
                        peFlash === 'up' && 'text-emerald-500',
                        peFlash === 'down' && 'text-red-500'
                      )}
                    >
                      {pePrice > 0 ? `₹${formatPrice(pePrice)}` : '--'}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 truncate" title={peSymbol}>
                      {peSymbol || '--'}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Lots & Action Buttons */}
            <Card>
              <CardContent className="p-4">
                {/* Lot Selector */}
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-sm font-semibold text-muted-foreground uppercase">Lots</span>
                  <div className="flex gap-2">
                    {LOT_PRESETS.map((n) => (
                      <Button
                        key={n}
                        variant={lots === n && !customLots ? 'default' : 'outline'}
                        size="sm"
                        className="h-8 w-10 tabular-nums"
                        onClick={() => handleLotPreset(n)}
                      >
                        {n}
                      </Button>
                    ))}
                    <Input
                      type="number"
                      placeholder="#"
                      className="h-8 w-16 text-center font-bold tabular-nums"
                      min={1}
                      max={500}
                      value={customLots}
                      onChange={(e) => handleCustomLots(e.target.value)}
                      onFocus={(e) => e.target.select()}
                    />
                  </div>
                  <div className="flex items-center gap-1 ml-auto">
                    <span className="text-xs text-muted-foreground">Qty:</span>
                    <span className="font-bold text-sm tabular-nums">{quantity}</span>
                  </div>
                </div>

                {/* BUY Buttons */}
                <div className="grid grid-cols-2 gap-4">
                  <Button
                    className="h-16 text-lg font-bold bg-emerald-500 hover:bg-emerald-600 text-white shadow-lg"
                    disabled={!!orderInProgress || !ceSymbol}
                    onClick={() => placeOrder('CE', 'BUY')}
                  >
                    {orderInProgress === 'BUY-CE' ? (
                      <RefreshCw className="h-5 w-5 animate-spin mr-2" />
                    ) : (
                      <TrendingUp className="h-5 w-5 mr-2" />
                    )}
                    <div className="flex flex-col items-center">
                      <span>BUY CE</span>
                      <span className="text-[10px] font-normal opacity-70">[C]</span>
                    </div>
                  </Button>
                  <Button
                    className="h-16 text-lg font-bold bg-red-500 hover:bg-red-600 text-white shadow-lg"
                    disabled={!!orderInProgress || !peSymbol}
                    onClick={() => placeOrder('PE', 'BUY')}
                  >
                    {orderInProgress === 'BUY-PE' ? (
                      <RefreshCw className="h-5 w-5 animate-spin mr-2" />
                    ) : (
                      <TrendingDown className="h-5 w-5 mr-2" />
                    )}
                    <div className="flex flex-col items-center">
                      <span>BUY PE</span>
                      <span className="text-[10px] font-normal opacity-70">[P]</span>
                    </div>
                  </Button>
                </div>

                {/* SELL Buttons */}
                <div className="grid grid-cols-2 gap-4 mt-3">
                  <Button
                    variant="outline"
                    className="h-14 text-base font-bold border-2 border-emerald-500 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
                    disabled={!!orderInProgress || !ceSymbol}
                    onClick={() => placeOrder('CE', 'SELL')}
                  >
                    {orderInProgress === 'SELL-CE' ? (
                      <RefreshCw className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <ArrowDown className="h-4 w-4 mr-2" />
                    )}
                    <div className="flex flex-col items-center">
                      <span>SELL CE</span>
                      <span className="text-[10px] font-normal opacity-70">[⇧C]</span>
                    </div>
                  </Button>
                  <Button
                    variant="outline"
                    className="h-14 text-base font-bold border-2 border-red-500 text-red-600 dark:text-red-400 hover:bg-red-500/10"
                    disabled={!!orderInProgress || !peSymbol}
                    onClick={() => placeOrder('PE', 'SELL')}
                  >
                    {orderInProgress === 'SELL-PE' ? (
                      <RefreshCw className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <ArrowDown className="h-4 w-4 mr-2" />
                    )}
                    <div className="flex flex-col items-center">
                      <span>SELL PE</span>
                      <span className="text-[10px] font-normal opacity-70">[⇧P]</span>
                    </div>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Right: Positions Panel */}
          <div className="space-y-4">
            <Card className="h-full">
              <CardHeader className="p-4 pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Open Positions
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-sm font-bold tabular-nums',
                        totalPnl >= 0 ? 'text-emerald-500' : 'text-red-500'
                      )}
                    >
                      {totalPnl >= 0 ? '+' : ''}₹{formatPrice(Math.abs(totalPnl))}
                    </span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={refreshPositions}
                          disabled={isLoadingPositions}
                        >
                          <RefreshCw
                            className={cn('h-3.5 w-3.5', isLoadingPositions && 'animate-spin')}
                          />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Refresh positions</TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                {/* Positions List */}
                <div className="space-y-2 overflow-y-auto max-h-[400px]">
                  {positions.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8 text-sm">
                      No open positions
                    </div>
                  ) : (
                    positions.map((pos) => {
                      const isCE = pos.symbol.endsWith('CE')
                      return (
                        <div
                          key={`${pos.symbol}-${pos.exchange}`}
                          className="rounded-lg p-3 border space-y-1 hover:bg-muted/50 transition-colors"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Badge
                                variant={isCE ? 'default' : 'destructive'}
                                className="text-[10px] px-1.5 py-0"
                              >
                                {isCE ? 'CE' : 'PE'}
                              </Badge>
                              <span className="text-sm font-semibold truncate max-w-[140px]" title={pos.symbol}>
                                {pos.symbol}
                              </span>
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 text-xs text-red-500 border-red-500/50 hover:bg-red-500/10"
                              onClick={() => exitPosition(pos)}
                              disabled={exitingPosition === pos.symbol}
                            >
                              {exitingPosition === pos.symbol ? (
                                <RefreshCw className="h-3 w-3 animate-spin" />
                              ) : (
                                'EXIT'
                              )}
                            </Button>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground">
                              {pos.quantity} qty · Avg {formatPrice(pos.averagePrice)}
                            </span>
                            <span
                              className={cn(
                                'font-bold tabular-nums',
                                pos.pnl >= 0 ? 'text-emerald-500' : 'text-red-500'
                              )}
                            >
                              {pos.pnl >= 0 ? '+' : ''}₹{formatPrice(Math.abs(pos.pnl))}
                            </span>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>

                {/* Exit All Button */}
                <div className="mt-4 pt-3 border-t">
                  <Button
                    variant="destructive"
                    className="w-full bg-orange-500 hover:bg-orange-600"
                    onClick={exitAllPositions}
                    disabled={isExitingAll || positions.length === 0}
                  >
                    {isExitingAll ? (
                      <RefreshCw className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <X className="h-4 w-4 mr-2" />
                    )}
                    EXIT ALL
                    <span className="text-[10px] font-normal opacity-70 ml-1">[X]</span>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Keyboard Shortcuts Info */}
        <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">C</kbd> Buy CE
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">P</kbd> Buy PE
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">⇧C</kbd> Sell CE
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">⇧P</kbd> Sell PE
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">X</kbd> Exit All
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">R</kbd> Refresh
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">←</kbd>
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">→</kbd> Strike
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">↑</kbd>
            <kbd className="px-1.5 py-0.5 bg-muted border rounded text-[10px] font-mono">↓</kbd> Lots
          </span>
        </div>
      </div>
    </TooltipProvider>
  )
}

export default ScalperTerminal
