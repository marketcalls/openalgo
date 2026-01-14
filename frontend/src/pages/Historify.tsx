import {
  BarChart3,
  Calendar,
  Database,
  Download,
  FileUp,
  Moon,
  Plus,
  RefreshCw,
  Sun,
  Upload,
  X,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'

interface WatchlistItem {
  id: number
  symbol: string
  exchange: string
  display_name?: string
  added_at: string
}

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

interface IntervalData {
  seconds: string[]
  minutes: string[]
  hours: string[]
  days: string[]
  weeks: string[]
  months: string[]
}

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

export default function Historify() {
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const isDarkMode = mode === 'dark'

  // State
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [intervals, setIntervals] = useState<IntervalData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)

  // Upload form state
  const [uploadSymbol, setUploadSymbol] = useState('')
  const [uploadExchange, setUploadExchange] = useState('NSE')
  const [uploadInterval, setUploadInterval] = useState('D')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Selected symbol state
  const [selectedSymbol, setSelectedSymbol] = useState<string>('')
  const [selectedExchange, setSelectedExchange] = useState<string>('')
  const [selectedInterval, setSelectedInterval] = useState<string>('D')

  // Add symbol state
  const [newSymbol, setNewSymbol] = useState('')
  const [newExchange, setNewExchange] = useState('NSE')

  // Download date range
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setMonth(d.getMonth() - 1)
    return d.toISOString().split('T')[0]
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0])

  // Chart data
  const [chartData, setChartData] = useState<OHLCVData[]>([])

  // Stats
  const [stats, setStats] = useState({
    database_size_mb: 0,
    total_records: 0,
    total_symbols: 0,
    watchlist_count: 0,
  })

  // Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  // Exchanges
  const exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NSE_INDEX', 'BSE_INDEX']

  // All intervals flattened
  const allIntervals = intervals
    ? [
        ...intervals.seconds,
        ...intervals.minutes,
        ...intervals.hours,
        ...intervals.days,
        ...intervals.weeks,
        ...intervals.months,
      ]
    : ['D']

  // Load data on mount
  useEffect(() => {
    loadWatchlist()
    loadCatalog()
    loadIntervals()
    loadStats()
  }, [])

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const container = chartContainerRef.current

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: 400,
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
      rightPriceScale: {
        borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
      },
      timeScale: {
        borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Handle resize
    const handleResize = () => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({ width: container.offsetWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [isDarkMode])

  // Update chart data when chartData changes
  useEffect(() => {
    if (seriesRef.current && chartData.length > 0) {
      const formattedData = chartData.map((d) => ({
        time: d.timestamp as unknown as Parameters<typeof seriesRef.current.setData>[0][0]['time'],
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }))
      seriesRef.current.setData(formattedData)
      chartRef.current?.timeScale().fitContent()
    }
  }, [chartData])

  const loadWatchlist = async () => {
    try {
      const response = await fetch('/historify/api/watchlist', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setWatchlist(data.data || [])
      }
    } catch (error) {
      console.error('Error loading watchlist:', error)
    }
  }

  const loadCatalog = async () => {
    try {
      const response = await fetch('/historify/api/catalog', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setCatalog(data.data || [])
      }
    } catch (error) {
      console.error('Error loading catalog:', error)
    }
  }

  const loadIntervals = async () => {
    try {
      const response = await fetch('/historify/api/intervals', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setIntervals(data.data)
      }
    } catch (error) {
      console.error('Error loading intervals:', error)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('/historify/api/stats', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setStats(data.data)
      }
    } catch (error) {
      console.error('Error loading stats:', error)
    }
  }

  const loadChartData = useCallback(async () => {
    if (!selectedSymbol || !selectedExchange) return

    setIsLoading(true)
    try {
      const params = new URLSearchParams({
        symbol: selectedSymbol,
        exchange: selectedExchange,
        interval: selectedInterval,
      })

      const response = await fetch(`/historify/api/data?${params}`, { credentials: 'include' })
      const data = await response.json()

      if (data.status === 'success') {
        setChartData(data.data || [])
        if (data.count === 0) {
          toast.info('No data available. Download data first.')
        }
      } else {
        toast.error(data.message || 'Failed to load chart data')
      }
    } catch (error) {
      console.error('Error loading chart data:', error)
      toast.error('Failed to load chart data')
    } finally {
      setIsLoading(false)
    }
  }, [selectedSymbol, selectedExchange, selectedInterval])

  // Load chart data when selection changes
  useEffect(() => {
    if (selectedSymbol && selectedExchange) {
      loadChartData()
    }
  }, [selectedSymbol, selectedExchange, selectedInterval, loadChartData])

  const addToWatchlist = async () => {
    if (!newSymbol.trim()) {
      toast.warning('Please enter a symbol')
      return
    }

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/watchlist', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          symbol: newSymbol.trim().toUpperCase(),
          exchange: newExchange,
        }),
      })

      const data = await response.json()
      if (data.status === 'success') {
        toast.success(data.message)
        setNewSymbol('')
        loadWatchlist()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to add symbol')
      }
    } catch (error) {
      console.error('Error adding to watchlist:', error)
      toast.error('Failed to add symbol')
    }
  }

  const removeFromWatchlist = async (symbol: string, exchange: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/watchlist', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ symbol, exchange }),
      })

      const data = await response.json()
      if (data.status === 'success') {
        toast.success(data.message)
        loadWatchlist()
        loadStats()
        if (selectedSymbol === symbol && selectedExchange === exchange) {
          setSelectedSymbol('')
          setSelectedExchange('')
          setChartData([])
        }
      } else {
        toast.error(data.message || 'Failed to remove symbol')
      }
    } catch (error) {
      console.error('Error removing from watchlist:', error)
      toast.error('Failed to remove symbol')
    }
  }

  const downloadData = async () => {
    if (!selectedSymbol || !selectedExchange) {
      toast.warning('Please select a symbol first')
      return
    }

    setIsDownloading(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/download', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          symbol: selectedSymbol,
          exchange: selectedExchange,
          interval: selectedInterval,
          start_date: startDate,
          end_date: endDate,
        }),
      })

      const data = await response.json()
      if (data.status === 'success') {
        toast.success(`Downloaded ${data.records} records`)
        loadCatalog()
        loadStats()
        loadChartData()
      } else {
        toast.error(data.message || 'Failed to download data')
      }
    } catch (error) {
      console.error('Error downloading data:', error)
      toast.error('Failed to download data')
    } finally {
      setIsDownloading(false)
    }
  }

  const exportData = async () => {
    if (!selectedSymbol || !selectedExchange) {
      toast.warning('Please select a symbol first')
      return
    }

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/export', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          symbol: selectedSymbol,
          exchange: selectedExchange,
          interval: selectedInterval,
        }),
      })

      const data = await response.json()
      if (data.status === 'success') {
        // Download the file
        window.location.href = '/historify/api/export/download'
        toast.success('Export started')
      } else {
        toast.error(data.message || 'Failed to export data')
      }
    } catch (error) {
      console.error('Error exporting data:', error)
      toast.error('Failed to export data')
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      if (!file.name.toLowerCase().endsWith('.csv')) {
        toast.error('Please select a CSV file')
        return
      }
      setUploadFile(file)
    }
  }

  const uploadCSVData = async () => {
    if (!uploadFile) {
      toast.warning('Please select a CSV file')
      return
    }
    if (!uploadSymbol.trim()) {
      toast.warning('Please enter a symbol')
      return
    }

    setIsUploading(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('symbol', uploadSymbol.trim().toUpperCase())
      formData.append('exchange', uploadExchange)
      formData.append('interval', uploadInterval)

      const response = await fetch('/historify/api/upload', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: formData,
      })

      const data = await response.json()
      if (data.status === 'success') {
        toast.success(`${data.message}`)
        setUploadDialogOpen(false)
        setUploadFile(null)
        setUploadSymbol('')
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
        loadCatalog()
        loadStats()
        // If the uploaded symbol matches selected, reload chart
        if (
          data.symbol === selectedSymbol &&
          data.exchange === selectedExchange &&
          data.interval === selectedInterval
        ) {
          loadChartData()
        }
      } else {
        toast.error(data.message || 'Failed to upload data')
      }
    } catch (error) {
      console.error('Error uploading CSV:', error)
      toast.error('Failed to upload CSV')
    } finally {
      setIsUploading(false)
    }
  }

  const selectSymbol = (symbol: string, exchange: string) => {
    setSelectedSymbol(symbol)
    setSelectedExchange(exchange)
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      toast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`)
    } else {
      toast.error(result.message || 'Failed to toggle mode')
    }
  }

  // Get catalog info for selected symbol
  const selectedCatalog = catalog.find(
    (c) =>
      c.symbol === selectedSymbol &&
      c.exchange === selectedExchange &&
      c.interval === selectedInterval
  )

  return (
    <div className="h-full flex flex-col bg-background text-foreground">
      {/* Top Header Bar */}
      <div className="h-12 border-b border-border flex items-center px-4 bg-card/50">
        <div className="flex items-center gap-3">
          <Database className="h-5 w-5 text-primary" />
          <span className="font-semibold">Historify</span>
          <Badge variant="outline" className="text-xs">
            {stats.total_records.toLocaleString()} records
          </Badge>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
            )}
          >
            {appMode === 'live' ? 'Live' : 'Analyze'}
          </Badge>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
            <Link to="/dashboard">Dashboard</Link>
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Watchlist */}
        <div className="w-64 border-r border-border bg-card/30 flex flex-col">
          <div className="p-3 border-b border-border">
            <div className="flex gap-2">
              <Input
                placeholder="Symbol"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                className="h-8 text-sm"
                onKeyDown={(e) => e.key === 'Enter' && addToWatchlist()}
              />
              <Select value={newExchange} onValueChange={setNewExchange}>
                <SelectTrigger className="h-8 w-20 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {exchanges.map((ex) => (
                    <SelectItem key={ex} value={ex} className="text-xs">
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="icon" className="h-8 w-8 shrink-0" onClick={addToWatchlist}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {watchlist.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm py-8">
                  <Database className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p>No symbols in watchlist</p>
                  <p className="text-xs mt-1">Add symbols to get started</p>
                </div>
              ) : (
                watchlist.map((item) => (
                  <div
                    key={`${item.symbol}-${item.exchange}`}
                    className={cn(
                      'flex items-center justify-between px-2 py-1.5 rounded cursor-pointer group',
                      'hover:bg-accent/50',
                      selectedSymbol === item.symbol &&
                        selectedExchange === item.exchange &&
                        'bg-accent'
                    )}
                    onClick={() => selectSymbol(item.symbol, item.exchange)}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-medium text-sm truncate">{item.symbol}</span>
                      <Badge variant="outline" className="text-[10px] px-1 py-0">
                        {item.exchange}
                      </Badge>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeFromWatchlist(item.symbol, item.exchange)
                      }}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </ScrollArea>

          {/* Stats Footer */}
          <div className="p-3 border-t border-border text-xs text-muted-foreground">
            <div className="flex justify-between">
              <span>Symbols:</span>
              <span>{stats.total_symbols}</span>
            </div>
            <div className="flex justify-between">
              <span>DB Size:</span>
              <span>{stats.database_size_mb} MB</span>
            </div>
          </div>
        </div>

        {/* Main Panel */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Toolbar */}
          <div className="h-12 border-b border-border flex items-center gap-3 px-4 bg-card/30">
            <Select value={selectedInterval} onValueChange={setSelectedInterval}>
              <SelectTrigger className="h-8 w-24">
                <SelectValue placeholder="Interval" />
              </SelectTrigger>
              <SelectContent>
                {allIntervals.map((int) => (
                  <SelectItem key={int} value={int}>
                    {int}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="h-8 w-36"
              />
              <span className="text-muted-foreground">to</span>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="h-8 w-36"
              />
            </div>

            <div className="flex-1" />

            <Button
              variant="outline"
              size="sm"
              onClick={downloadData}
              disabled={!selectedSymbol || isDownloading}
            >
              {isDownloading ? (
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Download className="h-4 w-4 mr-2" />
              )}
              Download
            </Button>

            <Button variant="outline" size="sm" onClick={exportData} disabled={!selectedSymbol}>
              <Download className="h-4 w-4 mr-2" />
              Export CSV
            </Button>

            <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm">
                  <Upload className="h-4 w-4 mr-2" />
                  Upload CSV
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <FileUp className="h-5 w-5 text-primary" />
                    Upload CSV Data
                  </DialogTitle>
                  <DialogDescription>
                    Import OHLCV data from a CSV file. The file should contain columns for timestamp
                    (or date/time), open, high, low, close, and volume.
                  </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="upload-symbol">Symbol</Label>
                      <Input
                        id="upload-symbol"
                        placeholder="e.g., RELIANCE"
                        value={uploadSymbol}
                        onChange={(e) => setUploadSymbol(e.target.value.toUpperCase())}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="upload-exchange">Exchange</Label>
                      <Select value={uploadExchange} onValueChange={setUploadExchange}>
                        <SelectTrigger id="upload-exchange">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {exchanges.map((ex) => (
                            <SelectItem key={ex} value={ex}>
                              {ex}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="upload-interval">Interval</Label>
                    <Select value={uploadInterval} onValueChange={setUploadInterval}>
                      <SelectTrigger id="upload-interval">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {allIntervals.map((int) => (
                          <SelectItem key={int} value={int}>
                            {int}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="upload-file">CSV File</Label>
                    <div
                      className={cn(
                        'border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors',
                        'hover:border-primary/50 hover:bg-accent/50',
                        uploadFile ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'
                      )}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <input
                        ref={fileInputRef}
                        id="upload-file"
                        type="file"
                        accept=".csv"
                        className="hidden"
                        onChange={handleFileChange}
                      />
                      {uploadFile ? (
                        <div className="flex items-center justify-center gap-2">
                          <FileUp className="h-5 w-5 text-primary" />
                          <span className="font-medium">{uploadFile.name}</span>
                          <Badge variant="secondary" className="text-xs">
                            {(uploadFile.size / 1024).toFixed(1)} KB
                          </Badge>
                        </div>
                      ) : (
                        <div className="text-muted-foreground">
                          <FileUp className="h-8 w-8 mx-auto mb-2 opacity-50" />
                          <p className="text-sm">Click to select a CSV file</p>
                          <p className="text-xs mt-1">or drag and drop</p>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
                    <p className="font-medium mb-1">Expected CSV format:</p>
                    <code className="block">timestamp, open, high, low, close, volume, oi</code>
                    <p className="mt-1">or</p>
                    <code className="block">date, time, open, high, low, close, volume</code>
                  </div>
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setUploadDialogOpen(false)
                      setUploadFile(null)
                      setUploadSymbol('')
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={uploadCSVData}
                    disabled={!uploadFile || !uploadSymbol || isUploading}
                  >
                    {isUploading ? (
                      <>
                        <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <Upload className="h-4 w-4 mr-2" />
                        Upload
                      </>
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={loadChartData}>
              <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
            </Button>
          </div>

          {/* Chart Area */}
          <div className="flex-1 p-4 overflow-hidden">
            {selectedSymbol ? (
              <Card className="h-full">
                <CardHeader className="py-3">
                  <CardTitle className="text-lg flex items-center gap-3">
                    <span>
                      {selectedSymbol} : {selectedExchange}
                    </span>
                    <Badge variant="outline">{selectedInterval}</Badge>
                    {selectedCatalog && (
                      <span className="text-sm font-normal text-muted-foreground">
                        {selectedCatalog.record_count.toLocaleString()} records ({' '}
                        {selectedCatalog.first_date} - {selectedCatalog.last_date})
                      </span>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent className="h-[calc(100%-60px)]">
                  <div ref={chartContainerRef} className="w-full h-full" />
                </CardContent>
              </Card>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center text-muted-foreground">
                  <BarChart3 className="h-16 w-16 mx-auto mb-4 opacity-30" />
                  <p className="text-lg font-medium">Select a symbol to view chart</p>
                  <p className="text-sm mt-2">
                    Add symbols to your watchlist and download historical data
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
