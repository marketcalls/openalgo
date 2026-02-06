import {
  ArrowLeftRight,
  Check,
  Clock,
  Code,
  Copy,
  ExternalLink,
  TrendingDown,
  TrendingUp,
  Webhook,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import type { Strategy } from '@/types/strategy'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface WebhookConfigSectionProps {
  strategy: Strategy | null
  dashStrategy: DashboardStrategy
}

const PLATFORM_LABELS: Record<string, string> = {
  tradingview: 'TradingView',
  amibroker: 'Amibroker',
  python: 'Python',
  metatrader: 'Metatrader',
  excel: 'Excel',
  others: 'Others',
}

function getTradingModeIcon(mode: string) {
  switch (mode) {
    case 'LONG':
      return <TrendingUp className="h-4 w-4 text-green-500" />
    case 'SHORT':
      return <TrendingDown className="h-4 w-4 text-red-500" />
    case 'BOTH':
      return <ArrowLeftRight className="h-4 w-4 text-blue-500" />
    default:
      return null
  }
}

export function WebhookConfigSection({ strategy, dashStrategy }: WebhookConfigSectionProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [showCredentials, setShowCredentials] = useState(false)
  const [hostConfig, setHostConfig] = useState<{ host_server: string } | null>(null)

  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch {
        setHostConfig({ host_server: window.location.origin })
      }
    }
    fetchHostConfig()
  }, [])

  const copyToClipboard = async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(field)
      showToast.success('Copied to clipboard', 'clipboard')
      setTimeout(() => setCopiedField(null), 2000)
    } catch {
      showToast.error('Failed to copy', 'clipboard')
    }
  }

  const baseUrl = hostConfig?.host_server || window.location.origin
  const webhookId = dashStrategy.webhook_id || strategy?.webhook_id || ''
  const webhookUrl = webhookId ? `${baseUrl}/strategy/webhook/${webhookId}` : ''

  // Use strategy detail if loaded, otherwise fall back to dashboard data
  const s = strategy || dashStrategy
  const platform = ('platform' in s ? s.platform : dashStrategy.platform) || ''

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Strategy Details */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Strategy Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Status</p>
              <Badge variant={dashStrategy.is_active ? 'default' : 'secondary'} className="mt-1">
                {dashStrategy.is_active ? 'Active' : 'Inactive'}
              </Badge>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Type</p>
              <Badge variant="outline" className="mt-1">
                {dashStrategy.is_intraday ? 'Intraday' : 'Positional'}
              </Badge>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Trading Mode</p>
              <div className="flex items-center gap-1.5 mt-1">
                {getTradingModeIcon(dashStrategy.trading_mode)}
                <span>{dashStrategy.trading_mode}</span>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Platform</p>
              <p className="mt-1">{PLATFORM_LABELS[platform] || platform}</p>
            </div>
          </div>

          {/* Trading Hours (intraday only) */}
          {strategy?.is_intraday && strategy.start_time && (
            <>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground flex items-center gap-1.5 mb-2">
                  <Clock className="h-3.5 w-3.5" />
                  Trading Hours
                </p>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  <div className="p-1.5 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">Start</p>
                    <p className="font-mono text-xs">{strategy.start_time}</p>
                  </div>
                  <div className="p-1.5 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">End</p>
                    <p className="font-mono text-xs">{strategy.end_time}</p>
                  </div>
                  <div className="p-1.5 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">Square Off</p>
                    <p className="font-mono text-xs">{strategy.squareoff_time}</p>
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Webhook Configuration */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Webhook className="h-4 w-4" />
            Webhook URL
          </CardTitle>
          <CardDescription className="text-xs">
            Use this URL to receive signals from your trading platform
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <code className="flex-1 p-2.5 bg-muted rounded text-sm font-mono break-all select-all">
              {webhookUrl || 'Loading...'}
            </code>
            <Button
              variant="outline"
              size="icon"
              className="flex-shrink-0"
              onClick={() => copyToClipboard(webhookUrl, 'url')}
            >
              {copiedField === 'url' ? (
                <Check className="h-4 w-4 text-green-500" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
          </div>

          {/* Credentials (non-TradingView) */}
          {platform !== 'tradingview' && (
            <Collapsible open={showCredentials} onOpenChange={setShowCredentials}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-between text-xs">
                  <span>Show Credentials</span>
                  <ExternalLink className="h-3.5 w-3.5" />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-2 mt-2">
                <div>
                  <p className="text-xs text-muted-foreground">Host URL</p>
                  <div className="flex gap-2 mt-1">
                    <code className="flex-1 p-1.5 bg-muted rounded text-xs font-mono">
                      {window.location.origin}
                    </code>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => copyToClipboard(window.location.origin, 'host')}
                    >
                      {copiedField === 'host' ? (
                        <Check className="h-3 w-3 text-green-500" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </Button>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Webhook ID</p>
                  <div className="flex gap-2 mt-1">
                    <code className="flex-1 p-1.5 bg-muted rounded text-xs font-mono">
                      {webhookId}
                    </code>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => copyToClipboard(webhookId, 'webhook_id')}
                    >
                      {copiedField === 'webhook_id' ? (
                        <Check className="h-3 w-3 text-green-500" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </Button>
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>
          )}

          {/* TradingView alert format */}
          {platform === 'tradingview' && (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Code className="h-3.5 w-3.5" />
                TradingView Alert Format
              </p>
              <pre className="p-2 bg-muted rounded text-xs font-mono overflow-x-auto">
                {`{
  "symbol": "{{ticker}}",
  "action": "BUY"
}`}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
