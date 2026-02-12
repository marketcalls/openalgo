import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock,
  Copy,
  Info,
  Power,
  Settings,
  Trash2,
  Webhook,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { chartinkApi } from '@/api/chartink'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import type { ChartinkStrategy, ChartinkSymbolMapping } from '@/types/chartink'

export default function ViewChartinkStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [strategy, setStrategy] = useState<ChartinkStrategy | null>(null)
  const [mappings, setMappings] = useState<ChartinkSymbolMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [hostConfig, setHostConfig] = useState<{ host_server: string; is_localhost: boolean } | null>(null)

  const fetchStrategy = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const data = await chartinkApi.getStrategy(Number(strategyId))
      setStrategy(data.strategy)
      setMappings(data.mappings || [])
    } catch (error) {
      showToast.error('Failed to load strategy', 'chartink')
      navigate('/chartink')
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
      const response = await chartinkApi.toggleStrategy(strategy.id)
      if (response.status === 'success') {
        setStrategy({ ...strategy, is_active: response.data?.is_active ?? !strategy.is_active })
        showToast.success(response.data?.is_active ? 'Strategy activated' : 'Strategy deactivated', 'chartink')
      } else {
        showToast.error(response.message || 'Failed to toggle strategy', 'chartink')
      }
    } catch (error) {
      showToast.error('Failed to toggle strategy', 'chartink')
    } finally {
      setToggling(false)
    }
  }

  const handleDelete = async () => {
    if (!strategy) return
    try {
      setDeleting(true)
      const response = await chartinkApi.deleteStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success('Strategy deleted successfully', 'chartink')
        navigate('/chartink')
      } else {
        showToast.error(response.message || 'Failed to delete strategy', 'chartink')
      }
    } catch (error) {
      showToast.error('Failed to delete strategy', 'chartink')
    } finally {
      setDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  const handleDeleteMapping = async (mappingId: number) => {
    if (!strategy) return
    try {
      const response = await chartinkApi.deleteSymbolMapping(strategy.id, mappingId)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingId))
        showToast.success('Symbol mapping deleted', 'chartink')
      } else {
        showToast.error(response.message || 'Failed to delete mapping', 'chartink')
      }
    } catch (error) {
      showToast.error('Failed to delete mapping', 'chartink')
    }
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
  const webhookUrl = `${baseUrl}/chartink/webhook/${strategy.webhook_id}`

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/chartink">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Chartink Strategies
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
            Chartink • Created {new Date(strategy.created_at).toLocaleDateString()}
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
                <p className="text-sm text-muted-foreground">Exchanges</p>
                <p className="mt-1">NSE, BSE only</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Products</p>
                <p className="mt-1">MIS, CNC only</p>
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
            <CardDescription>Use this URL in your Chartink screener</CardDescription>
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

            {/* Setup Instructions */}
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>
                <p className="font-medium mb-2">Chartink Setup:</p>
                <ol className="list-decimal list-inside space-y-1 text-sm">
                  <li>Go to your Chartink screener settings</li>
                  <li>Add this webhook URL</li>
                  <li>Include BUY/SELL/SHORT/COVER in alert name</li>
                  <li>Save and enable alerts</li>
                </ol>
              </AlertDescription>
            </Alert>
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
            <li>Chartink symbol must be configured in the mappings below</li>
            <li>Only NSE and BSE exchanges are supported</li>
            <li>Only MIS and CNC product types are supported</li>
          </ul>
        </AlertDescription>
      </Alert>

      {/* Symbol Mappings */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Symbol Mappings</CardTitle>
            <CardDescription>
              Chartink symbols configured for this strategy ({mappings.length} total)
            </CardDescription>
          </div>
          <Button asChild>
            <Link to={`/chartink/${strategy.id}/configure`}>
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
                <Link to={`/chartink/${strategy.id}/configure`}>Add your first symbol</Link>
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Chartink Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="w-16"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mappings.map((mapping) => (
                  <TableRow key={mapping.id}>
                    <TableCell className="font-medium">{mapping.chartink_symbol}</TableCell>
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
