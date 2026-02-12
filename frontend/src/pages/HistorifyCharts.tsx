import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  Calendar,
  Database,
  Home,
  Loader2,
  LogOut,
  Maximize2,
  Minimize2,
  Moon,
  RefreshCw,
  Search,
  Sun,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { authApi } from '@/api/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { profileMenuItems } from '@/config/navigation'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'

interface CatalogItem {
  symbol: string
  exchange: string
  interval: string
  first_timestamp: number
  last_timestamp: number
  record_count: number
  first_date?: string
  last_date?: string
}

interface OHLCVData {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export default function HistorifyCharts() {
  const navigate = useNavigate()
  const { mode, toggleMode, appMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()
  const isDarkMode = mode === 'dark' || appMode === 'analyzer'
  const { symbol: urlSymbol } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully', 'historify')
    } catch {
      logout()
      navigate('/login')
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`, 'historify')
    } else {
      showToast.error(result.message || 'Failed to toggle mode', 'historify')
    }
  }

  // State
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Symbol selection
  const [selectedSymbol, setSelectedSymbol] = useState(urlSymbol || '')
  const [selectedExchange, setSelectedExchange] = useState(searchParams.get('exchange') || 'NSE')
  const [selectedInterval, setSelectedInterval] = useState(searchParams.get('interval') || 'D')
  const [symbolSearchOpen, setSymbolSearchOpen] = useState(false)
  const [symbolSearch, setSymbolSearch] = useState('')

  // Custom interval state
  const [isCustomInterval, setIsCustomInterval] = useState(false)
  const [customIntervalValue, setCustomIntervalValue] = useState('25')
  const [customIntervalUnit, setCustomIntervalUnit] = useState<'m' | 'h' | 'W' | 'M' | 'Q' | 'Y'>('m')

  // Date range
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setMonth(d.getMonth() - 6)
    return d.toISOString().split('T')[0]
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0])

  // Chart data
  const [chartData, setChartData] = useState<OHLCVData[]>([])
  const [dataInfo, setDataInfo] = useState<CatalogItem | null>(null)

  // Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  // Standard chart timeframes (not broker-specific)
  const CHART_TIMEFRAMES = [
    '1m', '2m', '3m', '5m', '10m', '15m', '30m',
    '1h', '2h', '4h',
    'D', 'W', 'M', 'Q', 'Y'
  ]

  // Effective interval (either selected standard interval or custom)
  const effectiveInterval = useMemo(() => {
    if (isCustomInterval) {
      // For W, MO, Q, Y with value 1, just use the unit (e.g., 'W', 'M')
      // For values > 1, use value + unit (e.g., '2W', '3MO')
      if (['W', 'M', 'Q', 'Y'].includes(customIntervalUnit)) {
        const val = parseInt(customIntervalValue, 10) || 1
        return val === 1 ? customIntervalUnit : `${val}${customIntervalUnit}`
      }
      return `${customIntervalValue}${customIntervalUnit}`
    }
    return selectedInterval
  }, [isCustomInterval, customIntervalValue, customIntervalUnit, selectedInterval])

  // Check if current interval is intraday (for chart display)
  const isIntradayInterval = useMemo(() => {
    const intradayPatterns = ['1s', '5s', '10s', '15s', '30s', '1m', '2m', '3m', '5m', '10m', '15m', '30m', '1h', '2h', '4h']
    if (intradayPatterns.includes(effectiveInterval)) return true
    // Custom intervals with 'm' or 'h' are intraday
    if (isCustomInterval && ['m', 'h'].includes(customIntervalUnit)) return true
    // W, MO, Q, Y are NOT intraday
    return false
  }, [effectiveInterval, isCustomInterval, customIntervalUnit])

  // Unique symbols from catalog
  const uniqueSymbols = useMemo(() => {
    const symbolMap = new Map<string, { symbol: string; exchange: string; intervals: string[] }>()
    catalog.forEach((item) => {
      const key = `${item.symbol}:${item.exchange}`
      if (!symbolMap.has(key)) {
        symbolMap.set(key, { symbol: item.symbol, exchange: item.exchange, intervals: [item.interval] })
      } else {
        symbolMap.get(key)!.intervals.push(item.interval)
      }
    })
    return Array.from(symbolMap.values())
  }, [catalog])

  // Filtered symbols for search
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch) return uniqueSymbols
    const search = symbolSearch.toLowerCase()
    return uniqueSymbols.filter(
      (s) => s.symbol.toLowerCase().includes(search) || s.exchange.toLowerCase().includes(search)
    )
  }, [uniqueSymbols, symbolSearch])

  // Load catalog on mount
  useEffect(() => {
    loadCatalog()
  }, [])

  // Update URL when selection changes
  useEffect(() => {
    if (selectedSymbol && selectedExchange && selectedInterval) {
      setSearchParams({ exchange: selectedExchange, interval: selectedInterval })
    }
  }, [selectedSymbol, selectedExchange, selectedInterval, setSearchParams])

  // Load chart data when selection changes
  useEffect(() => {
    if (selectedSymbol && selectedExchange && effectiveInterval) {
      loadChartData()
      updateDataInfo()
    }
  }, [selectedSymbol, selectedExchange, effectiveInterval])

  // Initialize/update chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    // Small delay for container sizing
    const initTimer = setTimeout(() => {
      if (!chartContainerRef.current) return

      // Clean up existing chart
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }

      const container = chartContainerRef.current
      const containerWidth = container.offsetWidth || 800
      const containerHeight = container.offsetHeight || 600

      // Use the computed isIntradayInterval for chart formatting
      const isIntraday = isIntradayInterval

      // Check if this is a daily-aggregated interval (W, MO, Q, Y)
      // These intervals return timestamps that already represent IST dates
      const isDailyAggregated = isCustomInterval &&
        ['W', 'M', 'Q', 'Y'].includes(customIntervalUnit)

      // Helper to format time/date in IST based on interval
      const formatTimeIST = (time: number) => {
        const date = new Date(time * 1000)
        // For daily-aggregated intervals (W, MO, Q, Y), timestamps already represent IST dates
        // For intraday and daily, we need to add IST offset
        const istOffset = isDailyAggregated ? 0 : 5.5 * 60 * 60 * 1000
        const istDate = new Date(date.getTime() + istOffset)
        const day = istDate.getUTCDate().toString().padStart(2, '0')
        const month = (istDate.getUTCMonth() + 1).toString().padStart(2, '0')
        const year = istDate.getUTCFullYear().toString().slice(-2)
        const hours = istDate.getUTCHours().toString().padStart(2, '0')
        const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')

        if (isIntraday) {
          return `${day}/${month}/${year} ${hours}:${minutes}`
        } else {
          return `${day}/${month}/${year}`
        }
      }

      const chart = createChart(container, {
        width: containerWidth,
        height: Math.max(containerHeight, 500),
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: isDarkMode ? '#a6adbb' : '#333',
        },
        grid: {
          vertLines: {
            color: isDarkMode ? 'rgba(166, 173, 187, 0.1)' : 'rgba(0, 0, 0, 0.1)',
          },
          horzLines: {
            color: isDarkMode ? 'rgba(166, 173, 187, 0.1)' : 'rgba(0, 0, 0, 0.1)',
          },
        },
        localization: {
          timeFormatter: formatTimeIST,
        },
        rightPriceScale: {
          borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
          scaleMargins: {
            top: 0.1,
            bottom: 0.25,
          },
        },
        timeScale: {
          borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
          timeVisible: isIntraday,
          secondsVisible: false,
          tickMarkFormatter: (time: number, tickMarkType: number) => {
            // Convert Unix timestamp to IST (UTC+5:30)
            // For daily-aggregated intervals (W, MO, Q, Y), timestamps already represent IST dates
            const date = new Date(time * 1000)
            const offset = isDailyAggregated ? 0 : 5.5 * 60 * 60 * 1000
            const istDate = new Date(date.getTime() + offset)

            if (isIntraday) {
              // For intraday: show time HH:MM
              const hours = istDate.getUTCHours().toString().padStart(2, '0')
              const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
              return `${hours}:${minutes}`
            } else {
              // For daily and above: TradingView-style tick marks
              // tickMarkType: 0=Year, 1=Month, 2=DayOfMonth, 3=Time, 4=TimeWithSeconds
              const day = istDate.getUTCDate()
              const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
              const month = istDate.getUTCMonth()
              const year = istDate.getUTCFullYear()

              if (tickMarkType === 0) {
                // Year tick - show year
                return year.toString()
              } else if (tickMarkType === 1) {
                // Month tick - show month name
                return monthNames[month]
              } else {
                // Day tick - show just day number
                return day.toString()
              }
            }
          },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: {
            width: 1,
            color: isDarkMode ? 'rgba(166, 173, 187, 0.5)' : 'rgba(0, 0, 0, 0.3)',
            style: 2,
            labelVisible: true,
            labelBackgroundColor: isDarkMode ? '#1f2937' : '#374151',
          },
          horzLine: {
            width: 1,
            color: isDarkMode ? 'rgba(166, 173, 187, 0.5)' : 'rgba(0, 0, 0, 0.3)',
            style: 2,
            labelBackgroundColor: isDarkMode ? '#1f2937' : '#374151',
          },
        },
      })

      // Add candlestick series
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      })

      // Add volume series
      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: '#26a69a',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: '',
      })
      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      })

      chartRef.current = chart
      candleSeriesRef.current = candleSeries
      volumeSeriesRef.current = volumeSeries

      // Set data if available
      if (chartData.length > 0) {
        const candleData = chartData.map((d) => ({
          time: d.timestamp as unknown as Parameters<typeof candleSeries.setData>[0][0]['time'],
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
        candleSeries.setData(candleData)

        const volumeData = chartData.map((d) => ({
          time: d.timestamp as unknown as Parameters<typeof volumeSeries.setData>[0][0]['time'],
          value: d.volume,
          color: d.close >= d.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)',
        }))
        volumeSeries.setData(volumeData)

        chart.timeScale().fitContent()
      }
    }, 100)

    // Handle resize with ResizeObserver for better flex layout support
    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        const container = chartContainerRef.current
        const width = container.offsetWidth
        const height = container.offsetHeight
        if (width > 0 && height > 0) {
          chartRef.current.applyOptions({ width, height })
        }
      }
    }

    const resizeObserver = new ResizeObserver(handleResize)
    if (chartContainerRef.current) {
      resizeObserver.observe(chartContainerRef.current)
    }
    window.addEventListener('resize', handleResize)

    return () => {
      clearTimeout(initTimer)
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleResize)
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [isDarkMode, chartData, isFullscreen, isIntradayInterval, isCustomInterval, customIntervalUnit])

  const loadCatalog = async () => {
    try {
      const response = await fetch('/historify/api/catalog', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setCatalog(data.data || [])
      }
    } catch (error) {
    }
  }

  const loadChartData = useCallback(async () => {
    if (!selectedSymbol || !selectedExchange) return

    setIsLoading(true)
    try {
      const params = new URLSearchParams({
        symbol: selectedSymbol,
        exchange: selectedExchange,
        interval: effectiveInterval,
        start_date: startDate,
        end_date: endDate,
      })

      const response = await fetch(`/historify/api/data?${params}`, { credentials: 'include' })
      const data = await response.json()

      if (data.status === 'success') {
        setChartData(data.data || [])
        if (data.count === 0) {
          showToast.info('No data available for this range. Make sure 1m data is downloaded for custom intervals.', 'historify')
        }
      } else {
        showToast.error(data.message || 'Failed to load chart data', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to load chart data', 'historify')
    } finally {
      setIsLoading(false)
    }
  }, [selectedSymbol, selectedExchange, effectiveInterval, startDate, endDate])

  const updateDataInfo = useCallback(() => {
    const info = catalog.find(
      (c) =>
        c.symbol === selectedSymbol &&
        c.exchange === selectedExchange &&
        c.interval === selectedInterval
    )
    setDataInfo(info || null)
  }, [catalog, selectedSymbol, selectedExchange, selectedInterval])

  const handleSymbolSelect = (symbol: string, exchange: string) => {
    setSelectedSymbol(symbol)
    setSelectedExchange(exchange)
    setSymbolSearchOpen(false)
    setSymbolSearch('')
  }

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen()
      setIsFullscreen(true)
    } else {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  return (
    <div
      className={cn(
        'h-full flex flex-col bg-background text-foreground',
        isFullscreen && 'fixed inset-0 z-50'
      )}
    >
      {/* Header */}
      <div className="h-14 border-b border-border flex items-center px-4 bg-card/50">
        <Button variant="ghost" size="icon" className="mr-2" asChild>
          <Link to="/historify">
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>

        <div className="flex items-center gap-3">
          <Database className="h-5 w-5 text-primary" />
          <span className="font-semibold">Historify Charts</span>
        </div>

        <div className="flex items-center gap-3 ml-6">
          {/* Symbol Selector */}
          <Popover open={symbolSearchOpen} onOpenChange={setSymbolSearchOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-64 justify-between">
                {selectedSymbol ? (
                  <span>
                    {selectedSymbol}:{selectedExchange}
                  </span>
                ) : (
                  <span className="text-muted-foreground">Select symbol...</span>
                )}
                <Search className="h-4 w-4 ml-2" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-0" align="start">
              <Command>
                <CommandInput
                  placeholder="Search symbols..."
                  value={symbolSearch}
                  onValueChange={setSymbolSearch}
                />
                <CommandList>
                  <CommandEmpty>No symbols found</CommandEmpty>
                  <CommandGroup>
                    {filteredSymbols.slice(0, 20).map((s) => (
                      <CommandItem
                        key={`${s.symbol}:${s.exchange}`}
                        value={`${s.symbol}:${s.exchange}`}
                        onSelect={() => handleSymbolSelect(s.symbol, s.exchange)}
                      >
                        <span className="font-medium">{s.symbol}</span>
                        <Badge variant="outline" className="ml-2 text-[10px]">
                          {s.exchange}
                        </Badge>
                        <span className="text-xs text-muted-foreground ml-auto">
                          {s.intervals.length} intervals
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>

          {/* Interval Selector */}
          <Select
            value={isCustomInterval ? 'custom' : selectedInterval}
            onValueChange={(val) => {
              if (val === 'custom') {
                setIsCustomInterval(true)
              } else {
                setIsCustomInterval(false)
                setSelectedInterval(val)
              }
            }}
          >
            <SelectTrigger className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHART_TIMEFRAMES.map((int) => (
                <SelectItem key={int} value={int}>
                  {int}
                </SelectItem>
              ))}
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>

          {/* Custom Interval Input */}
          {isCustomInterval && (
            <div className="flex items-center gap-1">
              <Input
                type="number"
                min="1"
                max="999"
                value={customIntervalValue}
                onChange={(e) => setCustomIntervalValue(e.target.value)}
                className="h-9 w-14 text-center"
                placeholder="1"
              />
              <Select value={customIntervalUnit} onValueChange={(v) => setCustomIntervalUnit(v as 'm' | 'h' | 'W' | 'M' | 'Q' | 'Y')}>
                <SelectTrigger className="w-20 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="m">min</SelectItem>
                  <SelectItem value="h">hr</SelectItem>
                  <SelectItem value="W">Week</SelectItem>
                  <SelectItem value="MO">Month</SelectItem>
                  <SelectItem value="Q">Qtr</SelectItem>
                  <SelectItem value="Y">Year</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Date Range */}
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            <Input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="h-9 w-36"
            />
            <span className="text-muted-foreground">-</span>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="h-9 w-36"
            />
          </div>

          <Button variant="outline" size="icon" onClick={loadChartData} disabled={isLoading}>
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          </Button>
        </div>

        <div className="flex-1" />

        {/* Right actions */}
        <div className="flex items-center gap-2">
          {/* Broker Badge */}
          {user?.broker && (
            <Badge variant="outline" className="text-xs">
              {user.broker.toUpperCase()}
            </Badge>
          )}

          {/* Mode Badge */}
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cn(
              'text-xs cursor-pointer',
              appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
            )}
            onClick={handleModeToggle}
          >
            {appMode === 'live' ? <Zap className="h-3 w-3 mr-1" /> : <BarChart3 className="h-3 w-3 mr-1" />}
            {appMode === 'live' ? 'Live' : 'Analyze'}
          </Badge>

          {/* Mode Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
          >
            {isTogglingMode ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          <Button variant="ghost" size="icon" onClick={toggleFullscreen}>
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" asChild>
            <Link to="/dashboard">
              <Home className="h-4 w-4 mr-1.5" />
              Dashboard
            </Link>
          </Button>

          {/* Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
              >
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || 'O'}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {profileMenuItems.map((item) => (
                <DropdownMenuItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  className="cursor-pointer"
                >
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Chart Area */}
      <div className="flex-1 flex flex-col overflow-hidden p-4">
        {selectedSymbol ? (
          <div className="h-full flex flex-col">
            {/* Symbol Info Bar */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className="text-xl font-bold">
                  {selectedSymbol}:{selectedExchange}
                </span>
                <Badge variant="outline">{selectedInterval}</Badge>
                {chartData.length > 0 && (
                  <span className="text-sm text-muted-foreground">
                    {chartData.length.toLocaleString()} candles
                  </span>
                )}
              </div>

              {dataInfo && (
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  <span>
                    Data: {dataInfo.first_date} - {dataInfo.last_date}
                  </span>
                  <span>{dataInfo.record_count.toLocaleString()} records stored</span>
                </div>
              )}
            </div>

            {/* Chart Container */}
            <div className="flex-1 min-h-0 border rounded-lg bg-card overflow-hidden relative">
              <div ref={chartContainerRef} className="absolute inset-0" />
            </div>

            {/* Price Info */}
            {chartData.length > 0 && (
              <div className="mt-3 grid grid-cols-5 gap-4">
                <Card>
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground">Open</div>
                    <div className="text-lg font-medium">
                      {chartData[chartData.length - 1]?.open?.toFixed(2)}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground">High</div>
                    <div className="text-lg font-medium text-green-600">
                      {chartData[chartData.length - 1]?.high?.toFixed(2)}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground">Low</div>
                    <div className="text-lg font-medium text-red-600">
                      {chartData[chartData.length - 1]?.low?.toFixed(2)}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground">Close</div>
                    <div className="text-lg font-medium">
                      {chartData[chartData.length - 1]?.close?.toFixed(2)}
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground">Volume</div>
                    <div className="text-lg font-medium">
                      {chartData[chartData.length - 1]?.volume?.toLocaleString()}
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-muted-foreground">
              <Database className="h-16 w-16 mx-auto mb-4 opacity-30" />
              <p className="text-xl font-medium">Select a Symbol</p>
              <p className="text-sm mt-2">
                Choose a symbol from your data catalog to view its chart
              </p>
              {catalog.length === 0 && (
                <p className="text-sm mt-4">
                  No data in catalog.{' '}
                  <Link to="/historify" className="text-primary underline">
                    Download data first
                  </Link>
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
