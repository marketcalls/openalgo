import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Eye,
  Plus,
  RefreshCw,
  Settings,
  Webhook,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { chartinkApi } from '@/api/chartink'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { ChartinkStrategy } from '@/types/chartink'

export default function ChartinkIndex() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<ChartinkStrategy[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [hostConfig, setHostConfig] = useState<{ host_server: string; is_localhost: boolean } | null>(null)

  const fetchStrategies = async () => {
    try {
      setLoading(true)
      const data = await chartinkApi.getStrategies()
      setStrategies(data)
    } catch (error) {
      showToast.error('Failed to load Chartink strategies', 'chartink')
    } finally {
      setLoading(false)
    }
  }

  // Fetch host configuration on mount
  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch (error) {
        // Fallback to window.location.origin if config fetch fails
        setHostConfig({
          host_server: window.location.origin,
          is_localhost: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        })
      }
    }
    fetchHostConfig()
  }, [])

  useEffect(() => {
    fetchStrategies()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Get webhook URL using host config
  const getWebhookUrl = (webhookId: string): string => {
    const baseUrl = hostConfig?.host_server || window.location.origin
    return `${baseUrl}/chartink/webhook/${webhookId}`
  }

  const copyWebhookUrl = async (webhookId: string) => {
    const url = getWebhookUrl(webhookId)
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(webhookId)
      showToast.success('Webhook URL copied to clipboard', 'clipboard')
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      showToast.error('Failed to copy URL', 'clipboard')
    }
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <div className="flex justify-between items-center">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Chartink Strategies</h1>
          <p className="text-muted-foreground">Manage your Chartink webhook integrations</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchStrategies}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button onClick={() => navigate('/chartink/new')}>
            <Plus className="h-4 w-4 mr-2" />
            New Strategy
          </Button>
        </div>
      </div>

      {/* Localhost Warning - only show if HOST_SERVER is not configured to external URL */}
      {hostConfig?.is_localhost && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Webhook URL not accessible!</AlertTitle>
          <AlertDescription>
            Chartink cannot send alerts to localhost. Use <strong>ngrok</strong>,{' '}
            <strong>Cloudflare Tunnel</strong>, <strong>VS Code Dev Tunnel</strong>, or a{' '}
            <strong>custom domain</strong> to expose your OpenAlgo instance to the internet.
            Update <code>HOST_SERVER</code> in your <code>.env</code> file with your external URL.
          </AlertDescription>
        </Alert>
      )}

      {/* Webhook Info Alert */}
      <Alert>
        <Webhook className="h-4 w-4" />
        <AlertTitle>Chartink Webhook</AlertTitle>
        <AlertDescription>
          Receive alerts from Chartink screeners. Use these keywords in your alert name:
          <code className="bg-muted px-1 mx-1 rounded">BUY</code>,
          <code className="bg-muted px-1 mx-1 rounded">SELL</code>,
          <code className="bg-muted px-1 mx-1 rounded">SHORT</code>,
          <code className="bg-muted px-1 mx-1 rounded">COVER</code>
        </AlertDescription>
      </Alert>

      {/* Strategies Grid */}
      {strategies.length === 0 ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <Zap className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Chartink Strategies</h3>
            <p className="text-muted-foreground mb-4">
              Create your first Chartink strategy to receive screener alerts.
            </p>
            <Button onClick={() => navigate('/chartink/new')}>
              <Plus className="h-4 w-4 mr-2" />
              Create Strategy
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {strategies.map((strategy) => (
            <Card key={strategy.id} className="relative overflow-hidden">
              {/* Status indicator bar */}
              <div
                className={`absolute top-0 left-0 right-0 h-1 ${
                  strategy.is_active ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
                }`}
              />

              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">{strategy.name}</CardTitle>
                    <CardDescription>Chartink</CardDescription>
                  </div>
                  <Badge variant={strategy.is_active ? 'default' : 'secondary'}>
                    {strategy.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                {/* Strategy Info */}
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="font-normal">
                    {strategy.is_intraday ? 'Intraday' : 'Positional'}
                  </Badge>
                  <Badge variant="outline" className="font-normal">
                    NSE/BSE Only
                  </Badge>
                </div>

                {/* Trading Hours (if intraday) */}
                {strategy.is_intraday && strategy.start_time && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-4 w-4" />
                    <span>
                      {strategy.start_time} - {strategy.end_time}
                      {strategy.squareoff_time && ` (SqOff: ${strategy.squareoff_time})`}
                    </span>
                  </div>
                )}

                {/* Webhook URL Copy */}
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 justify-start text-xs font-mono truncate"
                    onClick={() => copyWebhookUrl(strategy.webhook_id)}
                  >
                    {copiedId === strategy.webhook_id ? (
                      <Check className="h-3 w-3 mr-2 text-green-500" />
                    ) : (
                      <Copy className="h-3 w-3 mr-2" />
                    )}
                    <span className="truncate">.../{strategy.webhook_id.slice(0, 8)}...</span>
                  </Button>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2 pt-2">
                  <Button variant="outline" size="sm" className="flex-1" asChild>
                    <Link to={`/chartink/${strategy.id}/configure`}>
                      <Settings className="h-4 w-4 mr-2" />
                      Symbols
                    </Link>
                  </Button>
                  <Button variant="default" size="sm" className="flex-1" asChild>
                    <Link to={`/chartink/${strategy.id}`}>
                      <Eye className="h-4 w-4 mr-2" />
                      View
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Keywords Reference */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Alert Keywords Reference</CardTitle>
          <CardDescription>
            Include these keywords in your Chartink alert name to trigger orders
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-1">
              <Badge className="bg-green-500">BUY</Badge>
              <p className="text-sm text-muted-foreground">Open long position</p>
            </div>
            <div className="space-y-1">
              <Badge className="bg-red-500">SELL</Badge>
              <p className="text-sm text-muted-foreground">Close long position</p>
            </div>
            <div className="space-y-1">
              <Badge className="bg-orange-500">SHORT</Badge>
              <p className="text-sm text-muted-foreground">Open short position</p>
            </div>
            <div className="space-y-1">
              <Badge className="bg-blue-500">COVER</Badge>
              <p className="text-sm text-muted-foreground">Close short position</p>
            </div>
          </div>
          <div className="mt-4 p-3 bg-muted rounded-lg">
            <p className="text-sm">
              <strong>Example Alert Names:</strong>
            </p>
            <ul className="text-sm text-muted-foreground mt-2 space-y-1">
              <li>• "BUY - RSI Oversold Stocks" → triggers BUY orders</li>
              <li>• "SELL Signal - Moving Average Cross" → triggers SELL orders</li>
              <li>• "SHORT - Bearish Breakout" → triggers SHORT orders</li>
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
