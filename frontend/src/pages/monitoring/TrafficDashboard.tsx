import { Activity, ArrowLeft, Download, Filter, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface TrafficLog {
  timestamp: string
  client_ip: string
  method: string
  path: string
  status_code: number
  duration_ms: number
  host: string
  error: string | null
}

interface TrafficStats {
  overall: {
    total_requests: number
    error_requests: number
    avg_duration: number
  }
  api: {
    total_requests: number
    error_requests: number
    avg_duration: number
  }
  endpoints: Record<
    string,
    {
      total: number
      errors: number
      avg_duration: number
    }
  >
}

export default function TrafficDashboard() {
  const [isLoading, setIsLoading] = useState(true)
  const [logs, setLogs] = useState<TrafficLog[]>([])
  const [stats, setStats] = useState<TrafficStats | null>(null)
  const [activeTab, setActiveTab] = useState<'all' | 'api'>('all')
  const [filter, setFilter] = useState<'all' | 'error' | 'success'>('all')
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
        webClient.get<TrafficLog[]>('/traffic/api/logs'),
        webClient.get<TrafficStats>('/traffic/api/stats'),
      ])

      setLogs(Array.isArray(logsResponse.data) ? logsResponse.data : [])
      setStats(statsResponse.data)
    } catch (error) {
      showToast.error('Failed to load traffic data', 'monitoring')
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
    // Open export URL in new tab
    window.open('/traffic/export', '_blank')
  }

  const filteredLogs = logs.filter((log) => {
    // Filter by tab
    if (activeTab === 'api' && !log.path.startsWith('/api/v1/')) {
      return false
    }
    // Filter by status
    if (filter === 'error') {
      return log.status_code >= 400
    } else if (filter === 'success') {
      return log.status_code < 400
    }
    return true
  })

  const currentStats = activeTab === 'api' ? stats?.api : stats?.overall

  const getMethodBadgeVariant = (
    method: string
  ): 'default' | 'secondary' | 'destructive' | 'outline' => {
    switch (method) {
      case 'GET':
        return 'default'
      case 'POST':
        return 'secondary'
      case 'DELETE':
        return 'destructive'
      default:
        return 'outline'
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

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
              <Activity className="h-6 w-6" />
              Traffic Dashboard
            </h1>
          </div>
          <p className="text-muted-foreground">Monitor HTTP traffic and API requests</p>
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

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{currentStats?.total_requests || 0}</p>
            <p className="text-sm text-muted-foreground">Total Requests</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-destructive">
              {currentStats?.error_requests || 0}
            </p>
            <p className="text-sm text-muted-foreground">Error Requests</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{currentStats?.avg_duration?.toFixed(2) || 0}ms</p>
            <p className="text-sm text-muted-foreground">Avg Duration</p>
          </CardContent>
        </Card>
      </div>

      {/* Traffic Logs */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Traffic Logs</CardTitle>
              <CardDescription>{filteredLogs.length} requests</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Select value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
                <SelectTrigger className="w-[140px]">
                  <Filter className="h-4 w-4 mr-2" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="error">Errors Only</SelectItem>
                  <SelectItem value="success">Success Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
            <TabsList className="mb-4">
              <TabsTrigger value="all">All Traffic</TabsTrigger>
              <TabsTrigger value="api">API Traffic</TabsTrigger>
            </TabsList>

            <TabsContent value={activeTab}>
              <div className="border rounded-md">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Timestamp</TableHead>
                      <TableHead>Method</TableHead>
                      <TableHead>Path</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Duration</TableHead>
                      <TableHead>Client IP</TableHead>
                      <TableHead>Host</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredLogs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                          No traffic logs found
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredLogs.map((log, index) => (
                        <TableRow key={index}>
                          <TableCell className="text-sm">{log.timestamp}</TableCell>
                          <TableCell>
                            <Badge variant={getMethodBadgeVariant(log.method)}>{log.method}</Badge>
                          </TableCell>
                          <TableCell className="max-w-xs truncate font-mono text-sm">
                            {log.path}
                          </TableCell>
                          <TableCell>
                            <Badge variant={log.status_code >= 400 ? 'destructive' : 'secondary'}>
                              {log.status_code}
                            </Badge>
                          </TableCell>
                          <TableCell>{log.duration_ms.toFixed(2)}ms</TableCell>
                          <TableCell className="font-mono text-sm">{log.client_ip}</TableCell>
                          <TableCell className="max-w-xs truncate text-sm">
                            {log.host || '-'}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Endpoint Stats */}
      {stats?.endpoints && Object.keys(stats.endpoints).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>API Endpoint Statistics</CardTitle>
            <CardDescription>Performance breakdown by endpoint</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="border rounded-md">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Endpoint</TableHead>
                    <TableHead>Total Requests</TableHead>
                    <TableHead>Errors</TableHead>
                    <TableHead>Avg Duration</TableHead>
                    <TableHead>Success Rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(stats.endpoints)
                    .filter(([, data]) => data.total > 0)
                    .sort((a, b) => b[1].total - a[1].total)
                    .map(([endpoint, data]) => (
                      <TableRow key={endpoint}>
                        <TableCell className="font-mono">/api/v1/{endpoint}</TableCell>
                        <TableCell>{data.total}</TableCell>
                        <TableCell>
                          {data.errors > 0 ? (
                            <Badge variant="destructive">{data.errors}</Badge>
                          ) : (
                            <span className="text-muted-foreground">0</span>
                          )}
                        </TableCell>
                        <TableCell>{data.avg_duration.toFixed(2)}ms</TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              data.total === 0
                                ? 'outline'
                                : (data.total - data.errors) / data.total >= 0.95
                                  ? 'secondary'
                                  : (data.total - data.errors) / data.total >= 0.8
                                    ? 'outline'
                                    : 'destructive'
                            }
                          >
                            {data.total === 0
                              ? 'N/A'
                              : (((data.total - data.errors) / data.total) * 100).toFixed(1)}
                            %
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
