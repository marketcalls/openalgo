import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Database,
  Download,
  FileStack,
  Loader2,
  RefreshCw,
  Server,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

interface SmartDownload {
  should_download: boolean
  reason: string
  cutoff_time: string
  cutoff_timezone: string
}

interface ExchangeStats {
  [exchange: string]: number
}

interface MasterContractStatus {
  broker: string
  status: 'pending' | 'downloading' | 'success' | 'error' | 'unknown'
  message: string
  last_updated: string | null
  total_symbols: string
  is_ready: boolean
  last_download_time: string | null
  download_date: string | null
  exchange_stats: ExchangeStats | null
  download_duration_seconds: number | null
  smart_download?: SmartDownload
}

interface CacheHealth {
  health_score: number
  status: string
  message?: string
  cache_loaded?: boolean
  cache_valid?: boolean
  hit_rate?: string
  total_symbols?: number
  memory_usage_mb?: string
  recommendations?: string[]
  stats?: {
    total_symbols: number
    symbols_by_exchange: ExchangeStats
    cache_age_seconds: number
    hits?: number
    misses?: number
  }
}

function formatDateTime(isoString: string | null): string {
  if (!isoString) return 'Never'
  const date = new Date(isoString)
  return date.toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Asia/Kolkata',
  })
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return 'N/A'
  if (seconds < 60) return `${seconds} seconds`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'success':
      return 'text-green-500'
    case 'downloading':
      return 'text-blue-500'
    case 'error':
      return 'text-red-500'
    case 'pending':
      return 'text-yellow-500'
    default:
      return 'text-muted-foreground'
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'success':
      return <CheckCircle2 className="h-5 w-5 text-green-500" />
    case 'downloading':
      return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
    case 'error':
      return <AlertCircle className="h-5 w-5 text-red-500" />
    case 'pending':
      return <Clock className="h-5 w-5 text-yellow-500" />
    default:
      return <AlertCircle className="h-5 w-5 text-muted-foreground" />
  }
}

export default function MasterContract() {
  const [status, setStatus] = useState<MasterContractStatus | null>(null)
  const [cacheHealth, setCacheHealth] = useState<CacheHealth | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isReloadingCache, setIsReloadingCache] = useState(false)
  const [pollingInterval, setPollingInterval] = useState<ReturnType<typeof setInterval> | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/master-contract/smart-status', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setStatus(data)

        // If downloading, continue polling
        if (data.status === 'downloading' && !pollingInterval) {
          const interval = setInterval(fetchStatus, 2000)
          setPollingInterval(interval)
        } else if (data.status !== 'downloading' && pollingInterval) {
          clearInterval(pollingInterval)
          setPollingInterval(null)
        }
      }
    } catch (error) {
    } finally {
      setIsLoading(false)
    }
  }, [pollingInterval])

  const fetchCacheHealth = useCallback(async () => {
    try {
      const response = await fetch('/api/cache/health', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setCacheHealth(data)
      }
    } catch (error) {
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchCacheHealth()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval)
      }
    }
  }, [pollingInterval])

  const handleForceDownload = async () => {
    setIsDownloading(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/api/master-contract/download', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ force: true }),
      })

      const data = await response.json()

      if (data.status === 'success' || data.started) {
        showToast.success('Master contract download started')
        // Start polling
        const interval = setInterval(fetchStatus, 2000)
        setPollingInterval(interval)
        fetchStatus()
      } else if (data.status === 'skipped') {
        showToast.info(data.message)
      } else {
        showToast.error(data.message || 'Failed to start download')
      }
    } catch (error) {
      showToast.error('Failed to start download')
    } finally {
      setIsDownloading(false)
    }
  }

  const handleReloadCache = async () => {
    setIsReloadingCache(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/api/cache/reload', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success') {
        showToast.success('Cache reloaded successfully')
        fetchCacheHealth()
      } else {
        showToast.error(data.message || 'Failed to reload cache')
      }
    } catch (error) {
      showToast.error('Failed to reload cache')
    } finally {
      setIsReloadingCache(false)
    }
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-6 px-4">
        <div className="mb-8">
          <Skeleton className="h-10 w-64 mb-2" />
          <Skeleton className="h-5 w-96" />
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 px-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Database className="h-8 w-8" />
            Master Contract
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage master contract data and symbol cache
          </p>
        </div>
        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={handleReloadCache}
            disabled={isReloadingCache || status?.status === 'downloading'}
          >
            {isReloadingCache ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Reload Cache
          </Button>
          <Button
            onClick={handleForceDownload}
            disabled={isDownloading || status?.status === 'downloading'}
          >
            {isDownloading || status?.status === 'downloading' ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Download className="h-4 w-4 mr-2" />
            )}
            Force Download
          </Button>
        </div>
      </div>

      {/* Smart Download Info */}
      {status?.smart_download && !status.smart_download.should_download && (
        <Alert className="mb-6">
          <CheckCircle2 className="h-4 w-4" />
          <AlertDescription>
            <strong>Smart Download:</strong> {status.smart_download.reason}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Status Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              Download Status
            </CardTitle>
            <CardDescription>
              Current master contract download status
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status</span>
              <div className="flex items-center gap-2">
                {getStatusIcon(status?.status || 'unknown')}
                <span className={`font-medium capitalize ${getStatusColor(status?.status || 'unknown')}`}>
                  {status?.status || 'Unknown'}
                </span>
              </div>
            </div>

            {status?.status === 'downloading' && (
              <div className="space-y-2">
                <Progress value={undefined} className="h-2" />
                <p className="text-sm text-muted-foreground text-center">
                  Downloading master contract data...
                </p>
              </div>
            )}

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Broker</span>
              <Badge variant="outline">{status?.broker || 'N/A'}</Badge>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Ready</span>
              <Badge variant={status?.is_ready ? 'default' : 'secondary'}>
                {status?.is_ready ? 'Yes' : 'No'}
              </Badge>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Total Symbols</span>
              <span className="font-mono">
                {status?.total_symbols ? Number(status.total_symbols).toLocaleString() : 'N/A'}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Last Updated</span>
              <span className="text-sm">{formatDateTime(status?.last_updated || null)}</span>
            </div>

            {status?.message && (
              <div className="pt-2 border-t">
                <p className="text-sm text-muted-foreground">{status.message}</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Download History Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-5 w-5" />
              Download History
            </CardTitle>
            <CardDescription>
              Last successful download information
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Last Download</span>
              <span className="text-sm">
                {formatDateTime(status?.last_download_time || null)}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Download Date</span>
              <span className="text-sm">
                {status?.download_date || 'N/A'}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Download Duration</span>
              <span className="font-mono text-sm">
                {formatDuration(status?.download_duration_seconds || null)}
              </span>
            </div>

            <div className="pt-2 border-t">
              <div className="flex items-center gap-2 mb-3">
                <FileStack className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Smart Download Cutoff</span>
              </div>
              <p className="text-sm text-muted-foreground">
                Downloads after{' '}
                <span className="font-medium">
                  {status?.smart_download?.cutoff_time || '08:00'} IST
                </span>{' '}
                are cached for the day. Login after cutoff reuses cached data.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Exchange Stats Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileStack className="h-5 w-5" />
              Exchange Statistics
            </CardTitle>
            <CardDescription>
              Symbol count per exchange
            </CardDescription>
          </CardHeader>
          <CardContent>
            {status?.exchange_stats && Object.keys(status.exchange_stats).length > 0 ? (
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(status.exchange_stats)
                  .sort(([, a], [, b]) => b - a)
                  .map(([exchange, count]) => (
                    <div
                      key={exchange}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50"
                    >
                      <span className="font-medium">{exchange}</span>
                      <Badge variant="secondary">
                        {count.toLocaleString()}
                      </Badge>
                    </div>
                  ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-center py-4">
                No exchange statistics available
              </p>
            )}
          </CardContent>
        </Card>

        {/* Cache Health Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              Cache Health
            </CardTitle>
            <CardDescription>
              In-memory symbol cache status
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Health Score</span>
              <div className="flex items-center gap-2">
                <Progress
                  value={cacheHealth?.health_score || 0}
                  className="w-24 h-2"
                />
                <span className="font-mono text-sm">
                  {cacheHealth?.health_score || 0}%
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge
                variant={
                  cacheHealth?.status === 'healthy'
                    ? 'default'
                    : cacheHealth?.status === 'degraded'
                      ? 'secondary'
                      : 'destructive'
                }
              >
                {cacheHealth?.status || 'Unknown'}
              </Badge>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Cached Symbols</span>
              <span className="font-mono">
                {cacheHealth?.total_symbols?.toLocaleString() || 'N/A'}
              </span>
            </div>

            {cacheHealth?.hit_rate && (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Hit Rate</span>
                <span className="font-mono text-sm">{cacheHealth.hit_rate}</span>
              </div>
            )}

            {cacheHealth?.memory_usage_mb && (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Memory Usage</span>
                <span className="font-mono text-sm">{cacheHealth.memory_usage_mb} MB</span>
              </div>
            )}

            {cacheHealth?.recommendations && cacheHealth.recommendations.length > 0 && (
              <div className="pt-2 border-t">
                <p className="text-sm text-muted-foreground">
                  {cacheHealth.recommendations[0]}
                </p>
              </div>
            )}

            {cacheHealth?.message && (
              <div className="pt-2 border-t">
                <p className="text-sm text-muted-foreground">{cacheHealth.message}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
