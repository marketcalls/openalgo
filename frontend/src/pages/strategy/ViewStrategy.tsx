import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  Check,
  Clock,
  Code,
  Copy,
  ExternalLink,
  Power,
  Settings,
  Trash2,
  TrendingDown,
  TrendingUp,
  Webhook,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Strategy, StrategySymbolMapping } from '@/types/strategy'

export default function ViewStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [mappings, setMappings] = useState<StrategySymbolMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [showCredentials, setShowCredentials] = useState(false)
  const [hostConfig, setHostConfig] = useState<{ host_server: string; is_localhost: boolean } | null>(null)

  const fetchStrategy = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const data = await strategyApi.getStrategy(Number(strategyId))
      setStrategy(data.strategy)
      setMappings(data.mappings || [])
    } catch (error) {
      showToast.error('Failed to load strategy', 'strategy')
      navigate('/strategy')
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
    fetchStrategy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const handleToggle = async () => {
    if (!strategy) return
    try {
      setToggling(true)
      const response = await strategyApi.toggleStrategy(strategy.id)
      if (response.status === 'success') {
        setStrategy({ ...strategy, is_active: response.data?.is_active ?? !strategy.is_active })
        showToast.success(response.data?.is_active ? 'Strategy activated' : 'Strategy deactivated', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to toggle strategy', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to toggle strategy', 'strategy')
    } finally {
      setToggling(false)
    }
  }

  const handleDelete = async () => {
    if (!strategy) return
    try {
      setDeleting(true)
      const response = await strategyApi.deleteStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success('Strategy deleted successfully', 'strategy')
        navigate('/strategy')
      } else {
        showToast.error(response.message || 'Failed to delete strategy', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to delete strategy', 'strategy')
    } finally {
      setDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  const handleDeleteMapping = async (mappingId: number) => {
    if (!strategy) return
    try {
      const response = await strategyApi.deleteSymbolMapping(strategy.id, mappingId)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingId))
        showToast.success('Symbol mapping deleted', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to delete mapping', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to delete mapping', 'strategy')
    }
  }

  const getTradingModeIcon = (mode: string) => {
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

  const getPlatformLabel = (platform: string) => {
    const labels: Record<string, string> = {
      tradingview: 'TradingView',
      amibroker: 'Amibroker',
      python: 'Python',
      metatrader: 'Metatrader',
      excel: 'Excel',
      others: 'Others',
    }
    return labels[platform] || platform
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!strategy) {
    return null
  }

  // Get webhook URL using host config
  const baseUrl = hostConfig?.host_server || window.location.origin
  const webhookUrl = `${baseUrl}/strategy/webhook/${strategy.webhook_id}`

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/strategy">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            {strategy.name}
            <Badge variant={strategy.is_active ? 'default' : 'secondary'}>
              {strategy.is_active ? 'Active' : 'Inactive'}
            </Badge>
          </h1>
          <p className="text-muted-foreground">
            {getPlatformLabel(strategy.platform)} • Created{' '}
            {new Date(strategy.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={strategy.is_active ? 'outline' : 'default'}
            onClick={handleToggle}
            disabled={toggling}
          >
            <Power className="h-4 w-4 mr-2" />
            {toggling ? 'Updating...' : strategy.is_active ? 'Deactivate' : 'Activate'}
          </Button>
          <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
            <Trash2 className="h-4 w-4 mr-2" />
            Delete
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Strategy Details */}
        <Card>
          <CardHeader>
            <CardTitle>Strategy Details</CardTitle>
            <CardDescription>Configuration and settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Status</p>
                <Badge variant={strategy.is_active ? 'default' : 'secondary'} className="mt-1">
                  {strategy.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Type</p>
                <Badge variant="outline" className="mt-1">
                  {strategy.is_intraday ? 'Intraday' : 'Positional'}
                </Badge>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Trading Mode</p>
                <div className="flex items-center gap-2 mt-1">
                  {getTradingModeIcon(strategy.trading_mode)}
                  <span>{strategy.trading_mode}</span>
                </div>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Platform</p>
                <p className="mt-1">{getPlatformLabel(strategy.platform)}</p>
              </div>
            </div>

            {strategy.is_intraday && strategy.start_time && (
              <>
                <Separator />
                <div>
                  <p className="text-sm text-muted-foreground flex items-center gap-2 mb-2">
                    <Clock className="h-4 w-4" />
                    Trading Hours
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">Start</p>
                      <p className="font-mono">{strategy.start_time}</p>
                    </div>
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">End</p>
                      <p className="font-mono">{strategy.end_time}</p>
                    </div>
                    <div className="p-2 bg-muted rounded">
                      <p className="text-xs text-muted-foreground">Square Off</p>
                      <p className="font-mono">{strategy.squareoff_time}</p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Webhook Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Webhook className="h-5 w-5" />
              Webhook Configuration
            </CardTitle>
            <CardDescription>Use this URL to receive trading alerts</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Webhook URL */}
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Webhook URL</p>
              <div className="flex gap-2">
                <code className="flex-1 p-2 bg-muted rounded text-sm font-mono break-all">
                  {webhookUrl}
                </code>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => copyToClipboard(webhookUrl, 'url')}
                >
                  {copiedField === 'url' ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>

            {/* Credentials (collapsible) */}
            {strategy.platform !== 'tradingview' && (
              <Collapsible open={showCredentials} onOpenChange={setShowCredentials}>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" className="w-full justify-between">
                    <span>Show Credentials</span>
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-3 mt-3">
                  <div className="space-y-2">
                    <p className="text-sm text-muted-foreground">Host URL</p>
                    <div className="flex gap-2">
                      <code className="flex-1 p-2 bg-muted rounded text-sm font-mono">
                        {window.location.origin}
                      </code>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => copyToClipboard(window.location.origin, 'host')}
                      >
                        {copiedField === 'host' ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <p className="text-sm text-muted-foreground">Webhook ID</p>
                    <div className="flex gap-2">
                      <code className="flex-1 p-2 bg-muted rounded text-sm font-mono">
                        {strategy.webhook_id}
                      </code>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => copyToClipboard(strategy.webhook_id, 'webhook_id')}
                      >
                        {copiedField === 'webhook_id' ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* TradingView specific message format */}
            {strategy.platform === 'tradingview' && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground flex items-center gap-2">
                  <Code className="h-4 w-4" />
                  TradingView Alert Message Format
                </p>
                <pre className="p-3 bg-muted rounded text-xs font-mono overflow-x-auto">
                  {`{
  "symbol": "{{ticker}}",
  "action": "BUY"
}`}
                </pre>
                <p className="text-xs text-muted-foreground">
                  Use BUY, SELL, SHORT, or COVER for the action field.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Important Notes */}
      <Alert>
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Important Notes</AlertTitle>
        <AlertDescription>
          <ul className="list-disc list-inside mt-2 space-y-1 text-sm">
            <li>
              Orders are processed only when the strategy is <strong>active</strong>
            </li>
            {strategy.is_intraday && (
              <li>
                Orders are processed only during trading hours ({strategy.start_time} -{' '}
                {strategy.end_time})
              </li>
            )}
            <li>Symbol must be configured in the mappings below to receive orders</li>
            <li>Use the correct action keywords: BUY, SELL, SHORT, COVER</li>
            {strategy.trading_mode === 'BOTH' && (
              <li>
                In BOTH mode, include <code className="bg-muted px-1 rounded">position_size</code>{' '}
                in your JSON payload
              </li>
            )}
          </ul>
        </AlertDescription>
      </Alert>

      {/* Symbol Mappings */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Symbol Mappings</CardTitle>
            <CardDescription>
              Symbols configured for this strategy ({mappings.length} total)
            </CardDescription>
          </div>
          <Button asChild>
            <Link to={`/strategy/${strategy.id}/configure`}>
              <Settings className="h-4 w-4 mr-2" />
              Configure Symbols
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {mappings.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No symbols configured yet.</p>
              <Button variant="link" asChild>
                <Link to={`/strategy/${strategy.id}/configure`}>Add your first symbol</Link>
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="w-16"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mappings.map((mapping) => (
                  <TableRow key={mapping.id}>
                    <TableCell className="font-medium">{mapping.symbol}</TableCell>
                    <TableCell>{mapping.exchange}</TableCell>
                    <TableCell className="text-right">{mapping.quantity}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{mapping.product_type}</Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-red-500 hover:text-red-600 hover:bg-red-50"
                        onClick={() => handleDeleteMapping(mapping.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Delete Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Strategy</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{strategy.name}"? This action cannot be undone. All
              symbol mappings will also be deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete Strategy'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
