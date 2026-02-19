import { ArrowLeft, CheckCircle, Download, Gauge, RefreshCw, XCircle, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface LatencyLog {
  id: number
  timestamp: string
  order_id: string
  broker: string | null
  symbol: string | null
  order_type: string
  rtt_ms: number
  validation_latency_ms: number
  response_latency_ms: number
  overhead_ms: number
  total_latency_ms: number
  status: string
  error: string | null
}

interface BrokerStats {
  avg_total: number
  p50_total: number
  p99_total: number
  sla_150ms: number
  total_orders: number
}

interface LatencyStats {
  total_orders: number
  success_rate: number
  failed_orders: number
  avg_total: number
  sla_150ms: number
  broker_stats: Record<string, BrokerStats>
  broker_histograms?: Record<
    string,
    {
      bins: string[]
      counts: number[]
      avg_rtt: number
      min_rtt: number
      max_rtt: number
    }
  >
}

export default function LatencyDashboard() {
  const [isLoading, setIsLoading] = useState(true)
  const [logs, setLogs] = useState<LatencyLog[]>([])
  const [stats, setStats] = useState<LatencyStats | null>(null)
  const [selectedOrder, setSelectedOrder] = useState<LatencyLog | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    fetchData()
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = async () => {
    try {
      const [logsResponse, statsResponse] = await Promise.all([
        webClient.get<LatencyLog[]>('/latency/api/logs'),
        webClient.get<LatencyStats>('/latency/api/stats'),
      ])

      setLogs(Array.isArray(logsResponse.data) ? logsResponse.data : [])
      setStats(statsResponse.data)
    } catch (error) {
      showToast.error('Failed to load latency data', 'monitoring')
    } finally {
      setIsLoading(false)
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchData()
    setIsRefreshing(false)
    showToast.success('Data refreshed', 'monitoring')
  }

  const handleExport = () => {
    window.open('/latency/export', '_blank')
  }

  const getSpeedRating = (
    latency: number
  ): {
    label: string
    color: string
    variant: 'default' | 'secondary' | 'destructive' | 'outline'
  } => {
    if (latency < 150) return { label: 'Excellent', color: 'text-green-500', variant: 'secondary' }
    if (latency < 250) return { label: 'Good', color: 'text-yellow-500', variant: 'outline' }
    if (latency < 400) return { label: 'Acceptable', color: 'text-orange-500', variant: 'outline' }
    return { label: 'Slow', color: 'text-red-500', variant: 'destructive' }
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp)
      return date.toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      })
    } catch {
      return timestamp
    }
  }

  // Calculate distribution for chart-like display
  const getDistribution = () => {
    const excellent = logs.filter((l) => (l.total_latency_ms || 0) < 150).length
    const good = logs.filter(
      (l) => (l.total_latency_ms || 0) >= 150 && (l.total_latency_ms || 0) < 250
    ).length
    const acceptable = logs.filter(
      (l) => (l.total_latency_ms || 0) >= 250 && (l.total_latency_ms || 0) < 400
    ).length
    const slow = logs.filter((l) => (l.total_latency_ms || 0) >= 400).length
    const total = logs.length || 1
    return { excellent, good, acceptable, slow, total }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  const distribution = getDistribution()

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Gauge className="h-6 w-6" />
              Order Latency Monitor
            </h1>
          </div>
          <p className="text-muted-foreground">Track how fast brokers confirm your orders</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleRefresh} disabled={isRefreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" />
            Export to CSV
          </Button>
        </div>
      </div>

      {/* Key Performance Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Orders Tracked</p>
                <p className="text-2xl font-bold text-primary">{stats?.total_orders || 0}</p>
                <p className="text-xs text-muted-foreground">All time</p>
              </div>
              <Zap className="h-8 w-8 text-primary opacity-20" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Success Rate</p>
                <p className="text-2xl font-bold text-green-500">
                  {(stats?.success_rate || 0).toFixed(1)}%
                </p>
                <p className="text-xs text-muted-foreground">{stats?.failed_orders || 0} failed</p>
              </div>
              <CheckCircle className="h-8 w-8 text-green-500 opacity-20" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Average Confirmation Time</p>
                <p className={`text-2xl font-bold ${getSpeedRating(stats?.avg_total || 0).color}`}>
                  {(stats?.avg_total || 0).toFixed(2)}ms
                </p>
                <p className="text-xs text-muted-foreground">End-to-end order confirmation</p>
              </div>
              <Gauge
                className={`h-8 w-8 ${getSpeedRating(stats?.avg_total || 0).color} opacity-20`}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Fast Orders</p>
                <p
                  className={`text-2xl font-bold ${
                    (stats?.sla_150ms || 0) >= 95
                      ? 'text-green-500'
                      : (stats?.sla_150ms || 0) >= 85
                        ? 'text-yellow-500'
                        : 'text-red-500'
                  }`}
                >
                  {(stats?.sla_150ms || 0).toFixed(1)}%
                </p>
                <p className="text-xs text-muted-foreground">Under 150ms (Target: 95%)</p>
              </div>
              <div className="relative h-16 w-16">
                <Progress value={stats?.sla_150ms || 0} className="h-16 w-16 rounded-full" />
                <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">
                  {Math.round(stats?.sla_150ms || 0)}%
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Performance Levels Reference */}
      <Card>
        <CardHeader>
          <CardTitle>Performance Levels</CardTitle>
          <CardDescription>
            Total end-to-end time from order submission to confirmation
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="flex items-center gap-3">
              <Badge className="bg-green-500">Excellent</Badge>
              <span className="text-sm text-muted-foreground">Under 150ms</span>
            </div>
            <div className="flex items-center gap-3">
              <Badge className="bg-yellow-500">Good</Badge>
              <span className="text-sm text-muted-foreground">150-250ms</span>
            </div>
            <div className="flex items-center gap-3">
              <Badge className="bg-orange-500">Acceptable</Badge>
              <span className="text-sm text-muted-foreground">250-400ms</span>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant="destructive">Slow</Badge>
              <span className="text-sm text-muted-foreground">Over 400ms</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Latency Distribution */}
      <Card>
        <CardHeader>
          <CardTitle>Latency Distribution</CardTitle>
          <CardDescription>Breakdown of order speeds</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Excellent (&lt;150ms)</span>
                <span className="font-bold">{distribution.excellent}</span>
              </div>
              <div className="h-4 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500"
                  style={{ width: `${(distribution.excellent / distribution.total) * 100}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {((distribution.excellent / distribution.total) * 100).toFixed(1)}%
              </p>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Good (150-250ms)</span>
                <span className="font-bold">{distribution.good}</span>
              </div>
              <div className="h-4 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-yellow-500"
                  style={{ width: `${(distribution.good / distribution.total) * 100}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {((distribution.good / distribution.total) * 100).toFixed(1)}%
              </p>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Acceptable (250-400ms)</span>
                <span className="font-bold">{distribution.acceptable}</span>
              </div>
              <div className="h-4 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-orange-500"
                  style={{ width: `${(distribution.acceptable / distribution.total) * 100}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {((distribution.acceptable / distribution.total) * 100).toFixed(1)}%
              </p>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Slow (&gt;400ms)</span>
                <span className="font-bold">{distribution.slow}</span>
              </div>
              <div className="h-4 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-red-500"
                  style={{ width: `${(distribution.slow / distribution.total) * 100}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {((distribution.slow / distribution.total) * 100).toFixed(1)}%
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Broker Performance Comparison */}
      {stats?.broker_stats && Object.keys(stats.broker_stats).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Broker Performance Comparison</CardTitle>
            <CardDescription>Latency breakdown by broker</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="border rounded-md">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Broker</TableHead>
                    <TableHead>Avg Latency</TableHead>
                    <TableHead>Median (P50)</TableHead>
                    <TableHead>Worst 1% (P99)</TableHead>
                    <TableHead>Fast Orders %</TableHead>
                    <TableHead>Total Orders</TableHead>
                    <TableHead>Performance</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(stats.broker_stats).map(([broker, data]) => (
                    <TableRow key={broker}>
                      <TableCell className="font-semibold">{broker}</TableCell>
                      <TableCell>
                        <Badge variant={getSpeedRating(data.avg_total).variant}>
                          {data.avg_total?.toFixed(2)}ms
                        </Badge>
                      </TableCell>
                      <TableCell>{data.p50_total?.toFixed(2)}ms</TableCell>
                      <TableCell>{data.p99_total?.toFixed(2)}ms</TableCell>
                      <TableCell>{data.sla_150ms?.toFixed(1)}%</TableCell>
                      <TableCell>{data.total_orders}</TableCell>
                      <TableCell>
                        <div className="w-24 h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className={`h-full ${
                              data.avg_total < 150
                                ? 'bg-green-500'
                                : data.avg_total < 250
                                  ? 'bg-yellow-500'
                                  : 'bg-red-500'
                            }`}
                            style={{
                              width: `${Math.max(0, Math.min(100, ((400 - data.avg_total) / 400) * 100))}%`,
                            }}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Orders Table */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Orders</CardTitle>
          <CardDescription>{logs.length} orders tracked</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Order ID</TableHead>
                  <TableHead>Broker</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                      No order latency data available
                    </TableCell>
                  </TableRow>
                ) : (
                  logs.map((log) => {
                    const rating = getSpeedRating(log.total_latency_ms || 0)
                    return (
                      <TableRow key={log.id}>
                        <TableCell className="text-sm">{formatTimestamp(log.timestamp)}</TableCell>
                        <TableCell className="font-mono text-sm">{log.order_id}</TableCell>
                        <TableCell>{log.broker || 'N/A'}</TableCell>
                        <TableCell className="font-semibold">{log.symbol || 'N/A'}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{log.order_type}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={rating.variant}>
                            {(log.total_latency_ms || 0).toFixed(2)}ms
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {log.status === 'SUCCESS' ? (
                            <Badge className="bg-green-500">SUCCESS</Badge>
                          ) : (
                            <Badge variant="destructive">{log.status}</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Button size="sm" variant="ghost" onClick={() => setSelectedOrder(log)}>
                            Details
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Order Details Modal */}
      <Dialog open={!!selectedOrder} onOpenChange={() => setSelectedOrder(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Order Latency Breakdown</DialogTitle>
            <DialogDescription>
              Detailed latency analysis for order {selectedOrder?.order_id}
            </DialogDescription>
          </DialogHeader>

          {selectedOrder && (
            <div className="space-y-6">
              {/* Order Info */}
              <div className="grid grid-cols-2 gap-4">
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-muted-foreground">Order ID</p>
                    <p className="font-mono font-semibold">{selectedOrder.order_id}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-muted-foreground">Performance</p>
                    <p
                      className={`text-lg font-bold ${getSpeedRating(selectedOrder.total_latency_ms).color}`}
                    >
                      {getSpeedRating(selectedOrder.total_latency_ms).label}
                    </p>
                  </CardContent>
                </Card>
              </div>

              {/* Latency Breakdown */}
              <div className="space-y-4">
                <h4 className="font-semibold">Latency Breakdown</h4>

                {/* Total Confirmation Time */}
                <div className="bg-muted p-4 rounded-lg">
                  <div className="flex justify-between mb-2">
                    <div>
                      <span className="font-semibold">Total Confirmation Time</span>
                      <p className="text-xs text-muted-foreground">
                        What you experience end-to-end
                      </p>
                    </div>
                    <span className="text-lg font-bold">
                      {(selectedOrder.total_latency_ms || 0).toFixed(2)}ms
                    </span>
                  </div>
                  <Progress
                    value={Math.min(100, ((selectedOrder.total_latency_ms || 0) / 500) * 100)}
                  />
                </div>

                <p className="text-xs text-muted-foreground">This consists of:</p>

                {/* Broker API Call */}
                <div className="bg-secondary/50 p-3 rounded-lg ml-4">
                  <div className="flex justify-between items-start mb-1">
                    <div>
                      <span className="font-semibold text-sm">Broker API Call</span>
                      <Badge variant="outline" className="ml-2 text-xs">
                        HTTP
                      </Badge>
                      <p className="text-xs text-muted-foreground mt-1">
                        Network latency + broker processing
                      </p>
                    </div>
                    <span className="font-bold">{(selectedOrder.rtt_ms || 0).toFixed(2)}ms</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
                    <p>Network round-trip time</p>
                    <p>Broker risk checks & validation</p>
                    <p>Exchange order submission</p>
                  </div>
                </div>

                {/* Platform Processing */}
                <div className="bg-secondary/50 p-3 rounded-lg ml-4">
                  <div className="flex justify-between items-start mb-1">
                    <div>
                      <span className="font-semibold text-sm">Platform Processing</span>
                      <Badge variant="outline" className="ml-2 text-xs">
                        OpenAlgo
                      </Badge>
                      <p className="text-xs text-muted-foreground mt-1">
                        Authentication, validation & logging
                      </p>
                    </div>
                    <span className="font-bold">
                      {(selectedOrder.overhead_ms || 0).toFixed(2)}ms
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
                    <p>API key authentication (~5-10ms)</p>
                    <p>Request validation (~3-5ms)</p>
                    <p>Symbol lookup & transformation (~5-10ms)</p>
                    <p>Latency database logging (~10-15ms)</p>
                    <p>Response formatting (~5-10ms)</p>
                  </div>
                </div>

                {/* Total Summary */}
                <div className="bg-primary/10 p-4 rounded-lg border-2 border-primary">
                  <div className="flex justify-between">
                    <span className="font-bold">Total Latency</span>
                    <span className="text-xl font-bold text-primary">
                      {(selectedOrder.total_latency_ms || 0).toFixed(2)}ms
                    </span>
                  </div>
                </div>

                {/* Error Display */}
                {selectedOrder.error && (
                  <div className="bg-destructive/10 p-4 rounded-lg border border-destructive flex items-center gap-3">
                    <XCircle className="h-5 w-5 text-destructive" />
                    <span className="text-sm">{selectedOrder.error}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
