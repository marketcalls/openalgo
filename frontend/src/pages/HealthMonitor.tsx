/**
 * Health Monitor Dashboard
 *
 * Real-time infrastructure health monitoring:
 * - File Descriptors
 * - Memory Usage
 * - Database Connections
 * - WebSocket Connections
 * - Thread Usage
 *
 * Auto-refreshes every 10 seconds
 */

import {
  Activity,
  AlertCircle,
  CheckCircle,
  Database,
  Download,
  HardDrive,
  Loader2,
  MemoryStick,
  Network,
  RefreshCw,
  Server,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import {
  acknowledgeAlert,
  exportMetricsCSV,
  getActiveAlerts,
  getCurrentMetrics,
  getHealthStats,
  getMetricsHistory,
  type CurrentMetrics,
  type HealthAlert,
  type HealthStats,
  type HistoricalMetric,
} from '@/api/health'
// Alert components removed - using custom styled divs for theme compatibility
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  ColorType,
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'

const AUTO_REFRESH_INTERVAL = 10000 // 10 seconds
const HISTORY_HOURS = 24
const CHART_HOURS = 6
const MAX_CHART_POINTS = 1200

interface MetricCardProps {
  title: string
  icon: React.ElementType
  value: string | number
  subtitle?: string
  status: 'pass' | 'warn' | 'fail' | 'unknown'
  loading?: boolean
}

function MetricCard({ title, icon: Icon, value, subtitle, status, loading }: MetricCardProps) {
  // Color mappings matching Latency Dashboard style
  const valueColors = {
    pass: 'text-green-500',
    warn: 'text-yellow-500',
    fail: 'text-red-500',
    unknown: 'text-primary',
  }

  const iconColors = {
    pass: 'text-green-500 opacity-20',
    warn: 'text-yellow-500 opacity-20',
    fail: 'text-red-500 opacity-20',
    unknown: 'text-primary opacity-20',
  }

  return (
    <Card>
      <CardContent className="p-4">
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">{title}</p>
              <p className={cn('text-2xl font-bold', valueColors[status])}>{value}</p>
              {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
            </div>
            <Icon className={cn('h-8 w-8', iconColors[status])} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function StatusIcon({ status }: { status: 'pass' | 'warn' | 'fail' | 'unknown' }) {
  if (status === 'pass') return <CheckCircle className="h-4 w-4 text-green-500" />
  if (status === 'warn') return <AlertCircle className="h-4 w-4 text-yellow-500" />
  if (status === 'fail') return <XCircle className="h-4 w-4 text-red-500" />
  return <WifiOff className="h-4 w-4 text-muted-foreground" />
}

const IST_TIME_ZONE = 'Asia/Kolkata'

function formatIstDateTime(timestamp: string, options?: Intl.DateTimeFormatOptions): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: IST_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    ...options,
  }).format(date)
}

function formatIstTime(timestamp: string): string {
  return formatIstDateTime(timestamp, { year: undefined, month: undefined, day: undefined })
}

// Check if dark mode is active
function isDarkMode(): boolean {
  return document.documentElement.classList.contains('dark')
}

export default function HealthMonitor() {
  const [currentMetrics, setCurrentMetrics] = useState<CurrentMetrics | null>(null)
  const [historicalMetrics, setHistoricalMetrics] = useState<HistoricalMetric[]>([])
  const [stats, setStats] = useState<HealthStats | null>(null)
  const [alerts, setAlerts] = useState<HealthAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [tabVisible, setTabVisible] = useState(true)

  // Chart refs
  const fdChartContainerRef = useRef<HTMLDivElement>(null)
  const memoryChartContainerRef = useRef<HTMLDivElement>(null)
  const fdChartRef = useRef<IChartApi | null>(null)
  const memoryChartRef = useRef<IChartApi | null>(null)
  const fdSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const memorySeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  // Fetch all data
  const fetchData = async (displayToast = false) => {
    try {
      setRefreshing(true)

      const [metricsData, historyData, statsData, alertsData] = await Promise.all([
        getCurrentMetrics(),
        getMetricsHistory(CHART_HOURS),
        getHealthStats(HISTORY_HOURS),
        getActiveAlerts(),
      ])

      setCurrentMetrics(metricsData)
      setHistoricalMetrics(historyData)
      setStats(statsData)
      setAlerts(alertsData)

      if (displayToast) {
        showToast.success('Metrics refreshed', 'monitoring')
      }
    } catch (error) {
      showToast.error('Failed to fetch health metrics', 'monitoring')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  // Initial load
  useEffect(() => {
    fetchData()
  }, [])

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh || !tabVisible) return

    const interval = setInterval(() => {
      fetchData()
    }, AUTO_REFRESH_INTERVAL)

    return () => clearInterval(interval)
  }, [autoRefresh, tabVisible])

  // Pause refresh when tab is hidden
  useEffect(() => {
    const handleVisibility = () => {
      setTabVisible(!document.hidden)
    }

    handleVisibility()
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [])

  // Initialize charts with theme-aware colors
  useEffect(() => {
    if (!historicalMetrics.length) return

    // Use simple hex colors that work with lightweight-charts
    // Dark mode: lighter text, subtle grid
    // Light mode: darker text, subtle grid
    const dark = isDarkMode()
    const textColor = dark ? '#9ca3af' : '#6b7280'  // gray-400 / gray-500
    const gridColor = dark ? '#374151' : '#e5e7eb'  // gray-700 / gray-200
    const borderColor = dark ? '#4b5563' : '#d1d5db' // gray-600 / gray-300

    // IST offset in milliseconds (5 hours 30 minutes)
    const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000

    // Helper to convert UTC timestamp to IST formatted string
    const formatTimeIST = (time: number): string => {
      const date = new Date(time * 1000)
      const istDate = new Date(date.getTime() + IST_OFFSET_MS)
      const hours = istDate.getUTCHours().toString().padStart(2, '0')
      const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
      return `${hours}:${minutes}`
    }

    // Helper to format date and time for crosshair tooltip in IST
    const formatDateTimeIST = (time: number): string => {
      const date = new Date(time * 1000)
      const istDate = new Date(date.getTime() + IST_OFFSET_MS)
      const day = istDate.getUTCDate().toString().padStart(2, '0')
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
      const month = months[istDate.getUTCMonth()]
      const year = istDate.getUTCFullYear().toString().slice(-2)
      const hours = istDate.getUTCHours().toString().padStart(2, '0')
      const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
      const seconds = istDate.getUTCSeconds().toString().padStart(2, '0')
      return `${day} ${month} '${year} ${hours}:${minutes}:${seconds}`
    }

    // Create chart options - no grid lines for clean look
    const chartOptions = {
      height: 300,
      layout: {
        background: { type: ColorType.Solid as const, color: 'transparent' },
        textColor: textColor,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      timeScale: {
        borderColor: borderColor,
        timeVisible: true,
        tickMarkFormatter: (time: number) => formatTimeIST(time),
      },
      rightPriceScale: {
        borderColor: borderColor,
      },
      crosshair: {
        vertLine: { color: gridColor },
        horzLine: { color: gridColor },
      },
      localization: {
        timeFormatter: (time: number) => formatDateTimeIST(time),
      },
    }

    // FD Chart - integers only on Y-axis
    if (fdChartContainerRef.current && !fdChartRef.current) {
      const chart = createChart(fdChartContainerRef.current, {
        ...chartOptions,
        width: fdChartContainerRef.current.clientWidth,
        localization: {
          ...chartOptions.localization,
          priceFormatter: (price: number) => Math.round(price).toString(),
        },
      })

      const series = chart.addSeries(LineSeries, {
        color: '#3b82f6',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => Math.round(price).toString(),
        },
      })

      fdChartRef.current = chart
      fdSeriesRef.current = series
    }

    // Memory Chart
    if (memoryChartContainerRef.current && !memoryChartRef.current) {
      const chart = createChart(memoryChartContainerRef.current, {
        ...chartOptions,
        width: memoryChartContainerRef.current.clientWidth,
      })

      const series = chart.addSeries(LineSeries, {
        color: '#10b981',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      })

      memoryChartRef.current = chart
      memorySeriesRef.current = series
    }

    // Update chart data
    if (fdSeriesRef.current && memorySeriesRef.current) {
      const rawData = historicalMetrics.map((m) => ({
        time: Math.floor(new Date(m.timestamp).getTime() / 1000) as UTCTimestamp,
        fd: m.fd_count,
        mem: m.memory_rss_mb,
      }))

      const downsampleFactor =
        rawData.length > MAX_CHART_POINTS
          ? Math.ceil(rawData.length / MAX_CHART_POINTS)
          : 1

      const fdData = []
      const memoryData = []
      for (let i = 0; i < rawData.length; i += downsampleFactor) {
        const point = rawData[i]
        fdData.push({ time: point.time, value: point.fd })
        memoryData.push({ time: point.time, value: point.mem })
      }

      fdSeriesRef.current.setData(fdData)
      memorySeriesRef.current.setData(memoryData)
    }

    // Handle resize
    const handleResize = () => {
      if (fdChartRef.current && fdChartContainerRef.current) {
        fdChartRef.current.applyOptions({
          width: fdChartContainerRef.current.clientWidth,
        })
      }
      if (memoryChartRef.current && memoryChartContainerRef.current) {
        memoryChartRef.current.applyOptions({
          width: memoryChartContainerRef.current.clientWidth,
        })
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [historicalMetrics])

  // Cleanup charts
  useEffect(() => {
    return () => {
      if (fdChartRef.current) {
        fdChartRef.current.remove()
        fdChartRef.current = null
      }
      if (memoryChartRef.current) {
        memoryChartRef.current.remove()
        memoryChartRef.current = null
      }
    }
  }, [])

  const handleAcknowledgeAlert = async (alertId: number) => {
    try {
      await acknowledgeAlert(alertId)
      showToast.success('Alert acknowledged', 'monitoring')
      fetchData()
    } catch (error) {
      showToast.error('Failed to acknowledge alert', 'monitoring')
    }
  }

  const handleExport = () => {
    window.open(exportMetricsCSV(24), '_blank')
    showToast.success('Exporting metrics to CSV', 'monitoring')
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">System Health Monitor</h1>
          <p className="text-muted-foreground mt-1">
            Real-time infrastructure monitoring • Updates every 10 seconds
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchData(true)}
            disabled={refreshing}
          >
            <RefreshCw className={cn('h-4 w-4 mr-2', refreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button
            variant={autoRefresh ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            <Activity className="h-4 w-4 mr-2" />
            Auto: {autoRefresh ? 'ON' : 'OFF'}
          </Button>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" />
            Export CSV
          </Button>
        </div>
      </div>

      {/* Overall Status Banner */}
      {currentMetrics && (
        <div
          className={cn(
            'rounded-lg border p-4 flex items-center gap-4',
            currentMetrics.overall_status === 'pass' && 'border-green-500/50 bg-green-500/10',
            currentMetrics.overall_status === 'warn' && 'border-yellow-500/50 bg-yellow-500/10',
            currentMetrics.overall_status === 'fail' && 'border-red-500/50 bg-red-500/10'
          )}
        >
          <StatusIcon status={currentMetrics.overall_status} />
          <div>
            <p className="font-semibold">
              System Status: {currentMetrics.overall_status.toUpperCase()}
            </p>
            <p className="text-sm text-muted-foreground">
              Last updated (IST): {formatIstDateTime(currentMetrics.timestamp)}
            </p>
          </div>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <MetricCard
          title="File Descriptors"
          icon={HardDrive}
          value={currentMetrics ? `${currentMetrics.fd.count} / ${currentMetrics.fd.limit}` : '-'}
          subtitle={currentMetrics ? `${currentMetrics.fd.usage_percent.toFixed(1)}% used` : undefined}
          status={currentMetrics?.fd.status || 'unknown'}
          loading={!currentMetrics}
        />
        <MetricCard
          title="Memory Usage"
          icon={MemoryStick}
          value={currentMetrics ? `${currentMetrics.memory.rss_mb.toFixed(1)} MB` : '-'}
          subtitle={currentMetrics ? `${currentMetrics.memory.percent.toFixed(1)}% of system` : undefined}
          status={currentMetrics?.memory.status || 'unknown'}
          loading={!currentMetrics}
        />
        <MetricCard
          title="Database Connections"
          icon={Database}
          value={currentMetrics?.database.total || 0}
          subtitle="Active connections"
          status={currentMetrics?.database.status || 'unknown'}
          loading={!currentMetrics}
        />
        <MetricCard
          title="WebSocket Connections"
          icon={Network}
          value={currentMetrics?.websocket.total || 0}
          subtitle={currentMetrics ? `${currentMetrics.websocket.total_symbols} symbols` : undefined}
          status={currentMetrics?.websocket.status || 'unknown'}
          loading={!currentMetrics}
        />
        <MetricCard
          title="Active Threads"
          icon={Server}
          value={currentMetrics?.threads.count || 0}
          subtitle={currentMetrics && currentMetrics.threads.stuck > 0 ? `${currentMetrics.threads.stuck} stuck` : 'None stuck'}
          status={currentMetrics?.threads.status || 'unknown'}
          loading={!currentMetrics}
        />
      </div>

      {/* Charts - Placed above Top Memory Processes */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">File Descriptors (6h)</CardTitle>
            <CardDescription>Historical FD usage over the last 6 hours</CardDescription>
          </CardHeader>
          <CardContent>
            <div ref={fdChartContainerRef} className="w-full h-[300px]" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Memory Usage (6h)</CardTitle>
            <CardDescription>Historical memory consumption in MB over the last 6 hours</CardDescription>
          </CardHeader>
          <CardContent>
            <div ref={memoryChartContainerRef} className="w-full h-[300px]" />
          </CardContent>
        </Card>
      </div>

      {/* Statistics - 2x2 grid for balanced layout */}
      {stats && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">File Descriptor Stats</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Current:</dt>
                  <dd className="font-medium">{stats.fd.current}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Average:</dt>
                  <dd className="font-medium">{stats.fd.avg.toFixed(1)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Min / Max:</dt>
                  <dd className="font-medium">{stats.fd.min} / {stats.fd.max}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Warnings:</dt>
                  <dd className="font-medium text-yellow-600 dark:text-yellow-400">{stats.fd.warn_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Failures:</dt>
                  <dd className="font-medium text-red-600 dark:text-red-400">{stats.fd.fail_count}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Memory Stats</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Current:</dt>
                  <dd className="font-medium">{stats.memory.current_mb.toFixed(1)} MB</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Average:</dt>
                  <dd className="font-medium">{stats.memory.avg_mb.toFixed(1)} MB</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Min / Max:</dt>
                  <dd className="font-medium">{stats.memory.min_mb.toFixed(1)} / {stats.memory.max_mb.toFixed(1)} MB</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Warnings:</dt>
                  <dd className="font-medium text-yellow-600 dark:text-yellow-400">{stats.memory.warn_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Failures:</dt>
                  <dd className="font-medium text-red-600 dark:text-red-400">{stats.memory.fail_count}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Connection Stats</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">DB Current:</dt>
                  <dd className="font-medium">{stats.database.current}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">DB Average:</dt>
                  <dd className="font-medium">{stats.database.avg.toFixed(1)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">WS Current:</dt>
                  <dd className="font-medium">{stats.websocket.current}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">WS Average:</dt>
                  <dd className="font-medium">{stats.websocket.avg.toFixed(1)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Threads:</dt>
                  <dd className="font-medium">{stats.threads.current}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Status Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Overall (Pass/Warn/Fail):</dt>
                  <dd className="font-medium">
                    {stats.status?.overall
                      ? `${stats.status.overall.pass}/${stats.status.overall.warn}/${stats.status.overall.fail}`
                      : '-'}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">DB Warn/Fail:</dt>
                  <dd className="font-medium">
                    {stats.status?.database
                      ? `${stats.status.database.warn}/${stats.status.database.fail}`
                      : '-'}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">WS Warn/Fail:</dt>
                  <dd className="font-medium">
                    {stats.status?.websocket
                      ? `${stats.status.websocket.warn}/${stats.status.websocket.fail}`
                      : '-'}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Threads Warn/Fail:</dt>
                  <dd className="font-medium">
                    {stats.status?.threads
                      ? `${stats.status.threads.warn}/${stats.status.threads.fail}`
                      : '-'}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Top Memory Processes */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Top Memory Processes</CardTitle>
          <CardDescription>Highest RSS memory usage across the host</CardDescription>
        </CardHeader>
        <CardContent>
          {currentMetrics?.processes && currentMetrics.processes.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Process</TableHead>
                  <TableHead className="text-right">PID</TableHead>
                  <TableHead className="text-right">RSS (MB)</TableHead>
                  <TableHead className="text-right">VMS (MB)</TableHead>
                  <TableHead className="text-right">Mem %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {currentMetrics.processes.map((proc) => (
                  <TableRow key={`${proc.pid}-${proc.name}`}>
                    <TableCell className="font-medium">{proc.name}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{proc.pid ?? '-'}</TableCell>
                    <TableCell className="text-right">{proc.rss_mb.toFixed(1)}</TableCell>
                    <TableCell className="text-right">{proc.vms_mb.toFixed(1)}</TableCell>
                    <TableCell className="text-right">{proc.memory_percent.toFixed(2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-sm text-muted-foreground">No process data available.</div>
          )}
        </CardContent>
      </Card>

      {/* Thread Details */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Thread Details</CardTitle>
          <CardDescription>Recent thread snapshot from the application</CardDescription>
        </CardHeader>
        <CardContent>
          {currentMetrics?.threads.details && currentMetrics.threads.details.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thread</TableHead>
                  <TableHead className="text-right">ID</TableHead>
                  <TableHead className="text-right">Daemon</TableHead>
                  <TableHead className="text-right">Alive</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {currentMetrics.threads.details.map((thread) => (
                  <TableRow key={`${thread.id}-${thread.name}`}>
                    <TableCell className="font-medium">{thread.name}</TableCell>
                    <TableCell className="text-right font-mono text-xs">{thread.id ?? '-'}</TableCell>
                    <TableCell className="text-right">{thread.daemon ? 'Yes' : 'No'}</TableCell>
                    <TableCell className="text-right">{thread.alive ? 'Yes' : 'No'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-sm text-muted-foreground">No thread details available.</div>
          )}
        </CardContent>
      </Card>

      {/* Active Alerts */}
      {alerts.length > 0 && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertCircle className="h-5 w-5" />
              Active Alerts ({alerts.length})
            </CardTitle>
            <CardDescription>System health alerts requiring attention</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {alerts.map((alert) => (
                <div
                  key={alert.id}
                  className={cn(
                    'rounded-lg border p-3 flex items-start justify-between gap-4',
                    alert.severity === 'fail' && 'border-red-500/50 bg-red-500/10',
                    alert.severity === 'warn' && 'border-yellow-500/50 bg-yellow-500/10'
                  )}
                >
                  <div className="flex items-start gap-3">
                    <StatusIcon status={alert.severity} />
                    <div>
                      <p className="font-medium">{alert.alert_type.replace(/_/g, ' ').toUpperCase()}</p>
                      <p className="text-sm text-muted-foreground">{alert.message}</p>
                    </div>
                  </div>
                  {!alert.acknowledged && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleAcknowledgeAlert(alert.id)}
                    >
                      Acknowledge
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Metrics Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Metrics</CardTitle>
          <CardDescription>Last 20 samples from the monitoring system</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead className="text-right">FDs</TableHead>
                <TableHead className="text-right">Memory (MB)</TableHead>
                <TableHead className="text-right">DB Conns</TableHead>
                <TableHead className="text-right">WS Conns</TableHead>
                <TableHead className="text-right">Threads</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {historicalMetrics.slice(-20).reverse().map((metric, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-mono text-xs">
                    {formatIstTime(metric.timestamp)}
                  </TableCell>
                  <TableCell className="text-right">{metric.fd_count}</TableCell>
                  <TableCell className="text-right">{metric.memory_rss_mb.toFixed(1)}</TableCell>
                  <TableCell className="text-right">{metric.db_connections}</TableCell>
                  <TableCell className="text-right">{metric.ws_connections}</TableCell>
                  <TableCell className="text-right">{metric.threads}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        metric.overall_status === 'pass'
                          ? 'default'
                          : metric.overall_status === 'warn'
                            ? 'secondary'
                            : 'destructive'
                      }
                    >
                      {metric.overall_status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
