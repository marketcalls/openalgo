import {
  AlertTriangle,
  ArrowLeftRight,
  Check,
  Clock,
  Code,
  Copy,
  ExternalLink,
  Loader2,
  Plus,
  Power,
  Search,
  ShieldCheck,
  Trash2,
  TrendingDown,
  TrendingUp,
  Upload,
  Webhook,
} from 'lucide-react'
import type React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import {
  CircuitBreakerBanner,
  hasCircuitBreakerConfig,
} from '@/components/strategy/CircuitBreakerBanner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
import { Textarea } from '@/components/ui/textarea'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { useCircuitBreaker } from '@/hooks/useCircuitBreaker'
import type { Strategy, StrategySymbolMapping, SymbolSearchResult } from '@/types/strategy'
import { EXCHANGES, getProductTypes } from '@/types/strategy'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface OverviewTabProps {
  strategy: DashboardStrategy
  onRefresh: () => void
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

export function OverviewTab({ strategy: dashStrategy, onRefresh }: OverviewTabProps) {
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [mappings, setMappings] = useState<StrategySymbolMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [showCredentials, setShowCredentials] = useState(false)
  const [hostConfig, setHostConfig] = useState<{ host_server: string; is_localhost: boolean } | null>(null)

  // Symbol add form
  const [showAddForm, setShowAddForm] = useState(false)
  const [symbolSearch, setSymbolSearch] = useState('')
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolSearchResult | null>(null)
  const [exchange, setExchange] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [productType, setProductType] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Bulk import dialog
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [csvData, setCsvData] = useState('')

  const { getStatus } = useCircuitBreaker()

  const fetchStrategy = useCallback(async () => {
    try {
      setLoading(true)
      const data = await strategyApi.getStrategy(dashStrategy.id)
      setStrategy(data.strategy)
      setMappings(data.mappings || [])
    } catch {
      showToast.error('Failed to load strategy details', 'strategy')
    } finally {
      setLoading(false)
    }
  }, [dashStrategy.id])

  useEffect(() => {
    fetchStrategy()
  }, [fetchStrategy])

  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch {
        setHostConfig({
          host_server: window.location.origin,
          is_localhost: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1',
        })
      }
    }
    fetchHostConfig()
  }, [])

  // Debounced symbol search
  const searchSymbols = useCallback(
    async (query: string) => {
      if (query.length < 2) {
        setSearchResults([])
        return
      }
      try {
        setSearchLoading(true)
        const results = await strategyApi.searchSymbols(query, exchange || undefined)
        setSearchResults(results)
      } catch {
        // ignore
      } finally {
        setSearchLoading(false)
      }
    },
    [exchange]
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      searchSymbols(symbolSearch)
    }, 300)
    return () => clearTimeout(timer)
  }, [symbolSearch, searchSymbols])

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

  const handleSymbolSelect = (result: SymbolSearchResult) => {
    setSelectedSymbol(result)
    setSymbolSearch(result.symbol)
    setExchange(result.exchange)
    setSearchOpen(false)
    const products = getProductTypes(result.exchange)
    setProductType(products[0])
  }

  const handleAddSymbol = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedSymbol || !exchange || !quantity || Number(quantity) < 1 || !productType) {
      showToast.error('Please fill all fields', 'strategy')
      return
    }
    try {
      setSubmitting(true)
      const response = await strategyApi.addSymbolMapping(dashStrategy.id, {
        symbol: selectedSymbol.symbol,
        exchange,
        quantity: Number(quantity),
        product_type: productType,
      })
      if (response.status === 'success') {
        showToast.success('Symbol added', 'strategy')
        setSelectedSymbol(null)
        setSymbolSearch('')
        setExchange('')
        setQuantity('1')
        setProductType('')
        setShowAddForm(false)
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to add symbol', 'strategy')
      }
    } catch {
      showToast.error('Failed to add symbol', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBulkImport = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!csvData.trim()) {
      showToast.error('Please enter CSV data', 'strategy')
      return
    }
    try {
      setSubmitting(true)
      const response = await strategyApi.addBulkSymbols(dashStrategy.id, csvData)
      if (response.status === 'success') {
        const { added = 0, failed = 0 } = response.data || {}
        showToast.success(`Added ${added} symbols${failed > 0 ? `, ${failed} failed` : ''}`, 'strategy')
        setCsvData('')
        setBulkDialogOpen(false)
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to import', 'strategy')
      }
    } catch {
      showToast.error('Failed to import symbols', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteMapping = async (mappingId: number) => {
    try {
      const response = await strategyApi.deleteSymbolMapping(dashStrategy.id, mappingId)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingId))
        showToast.success('Symbol removed', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to remove', 'strategy')
      }
    } catch {
      showToast.error('Failed to remove symbol', 'strategy')
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
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to toggle', 'strategy')
      }
    } catch {
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
        showToast.success('Strategy deleted', 'strategy')
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to delete', 'strategy')
      }
    } catch {
      showToast.error('Failed to delete strategy', 'strategy')
    } finally {
      setDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  const productTypes = exchange ? getProductTypes(exchange) : []

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!strategy) return null

  const baseUrl = hostConfig?.host_server || window.location.origin
  const webhookId = dashStrategy.webhook_id || strategy?.webhook_id || ''
  const webhookUrl = webhookId ? `${baseUrl}/strategy/webhook/${webhookId}` : ''

  return (
    <div className="space-y-4">
      {/* Two-column: Details + Webhook */}
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
                <Badge variant={strategy.is_active ? 'default' : 'secondary'} className="mt-1">
                  {strategy.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Type</p>
                <Badge variant="outline" className="mt-1">
                  {strategy.is_intraday ? 'Intraday' : 'Positional'}
                </Badge>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Trading Mode</p>
                <div className="flex items-center gap-1.5 mt-1">
                  {getTradingModeIcon(strategy.trading_mode)}
                  <span>{strategy.trading_mode}</span>
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Platform</p>
                <p className="mt-1">{PLATFORM_LABELS[strategy.platform] || strategy.platform}</p>
              </div>
            </div>

            {strategy.is_intraday && strategy.start_time && (
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
            {strategy.platform !== 'tradingview' && (
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
                        {copiedField === 'host' ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                      </Button>
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Webhook ID</p>
                    <div className="flex gap-2 mt-1">
                      <code className="flex-1 p-1.5 bg-muted rounded text-xs font-mono">
                        {strategy.webhook_id}
                      </code>
                      <Button
                        variant="outline"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => copyToClipboard(strategy.webhook_id, 'webhook_id')}
                      >
                        {copiedField === 'webhook_id' ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                      </Button>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* TradingView alert format */}
            {strategy.platform === 'tradingview' && (
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

      {/* Circuit Breaker */}
      {strategy && hasCircuitBreakerConfig(strategy) && (() => {
        const cbStatus = getStatus(strategy.id)
        const formatType = (type?: string) => type === 'points' ? 'pts' : type || ''
        return (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4" />
                Daily Risk Limits
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                {strategy.daily_stoploss_value != null && strategy.daily_stoploss_value > 0 && (
                  <div className="p-2 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">Daily Stoploss</p>
                    <p className="font-mono font-medium text-sm">
                      ₹{strategy.daily_stoploss_value.toLocaleString('en-IN')}{' '}
                      <span className="text-xs text-muted-foreground">{formatType(strategy.daily_stoploss_type)}</span>
                    </p>
                  </div>
                )}
                {strategy.daily_target_value != null && strategy.daily_target_value > 0 && (
                  <div className="p-2 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">Daily Target</p>
                    <p className="font-mono font-medium text-sm">
                      ₹{strategy.daily_target_value.toLocaleString('en-IN')}{' '}
                      <span className="text-xs text-muted-foreground">{formatType(strategy.daily_target_type)}</span>
                    </p>
                  </div>
                )}
                {strategy.daily_trailstop_value != null && strategy.daily_trailstop_value > 0 && (
                  <div className="p-2 bg-muted rounded">
                    <p className="text-xs text-muted-foreground">Daily Trail Stop</p>
                    <p className="font-mono font-medium text-sm">
                      ₹{strategy.daily_trailstop_value.toLocaleString('en-IN')}{' '}
                      <span className="text-xs text-muted-foreground">{formatType(strategy.daily_trailstop_type)}</span>
                    </p>
                  </div>
                )}
              </div>
              <CircuitBreakerBanner status={cbStatus} strategy={strategy} />
            </CardContent>
          </Card>
        )
      })()}

      {/* Symbol Mappings */}
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm">Symbol Mappings ({mappings.length})</CardTitle>
            <CardDescription className="text-xs">Symbols configured for webhook signals</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setBulkDialogOpen(true)}>
              <Upload className="h-3.5 w-3.5 mr-1" />
              Bulk Import
            </Button>
            <Button size="sm" onClick={() => setShowAddForm(!showAddForm)}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add Symbol
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Inline add symbol form */}
          {showAddForm && (
            <form onSubmit={handleAddSymbol} className="p-3 border rounded-lg bg-muted/30 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Symbol</Label>
                  <Popover open={searchOpen} onOpenChange={setSearchOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        variant="outline"
                        role="combobox"
                        aria-expanded={searchOpen}
                        className="w-full justify-between font-normal h-8 text-xs"
                      >
                        {selectedSymbol ? selectedSymbol.symbol : 'Search...'}
                        <Search className="ml-1 h-3 w-3 shrink-0 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-[280px] p-0" align="start">
                      <Command>
                        <CommandInput
                          placeholder="Search symbols..."
                          value={symbolSearch}
                          onValueChange={setSymbolSearch}
                        />
                        <CommandList>
                          <CommandEmpty>
                            {searchLoading ? 'Searching...' : 'No symbols found.'}
                          </CommandEmpty>
                          <CommandGroup>
                            {searchResults.map((result) => (
                              <CommandItem
                                key={`${result.symbol}-${result.exchange}`}
                                value={result.symbol}
                                onSelect={() => handleSymbolSelect(result)}
                              >
                                <div className="flex flex-col">
                                  <span className="font-medium text-sm">{result.symbol}</span>
                                  <span className="text-xs text-muted-foreground">
                                    {result.name} • {result.exchange}
                                  </span>
                                </div>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Exchange</Label>
                  <Select value={exchange} onValueChange={(v) => { setExchange(v); setProductType('') }}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="Exchange" />
                    </SelectTrigger>
                    <SelectContent>
                      {EXCHANGES.map((ex) => (
                        <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Quantity</Label>
                  <Input
                    type="number"
                    min="1"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Product</Label>
                  <Select value={productType} onValueChange={setProductType} disabled={!exchange}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="Product" />
                    </SelectTrigger>
                    <SelectContent>
                      {productTypes.map((pt) => (
                        <SelectItem key={pt} value={pt}>{pt}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={submitting}>
                  {submitting ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Plus className="h-3.5 w-3.5 mr-1" />}
                  Add
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowAddForm(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}

          {/* Mappings table */}
          {mappings.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p className="text-sm">No symbols configured yet.</p>
              <p className="text-xs mt-1">Click "Add Symbol" to get started.</p>
            </div>
          ) : (
            <div className="relative w-full overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="w-12"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mappings.map((mapping) => (
                    <TableRow key={mapping.id}>
                      <TableCell className="font-medium">{mapping.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">{mapping.exchange}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs capitalize">
                          {(mapping.order_mode || 'equity').replace('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{mapping.quantity}</TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">{mapping.product_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                          onClick={() => handleDeleteMapping(mapping.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Important Notes */}
      <Alert>
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle className="text-sm">Important</AlertTitle>
        <AlertDescription>
          <ul className="list-disc list-inside space-y-0.5 text-xs">
            <li>Orders are processed only when the strategy is <strong>active</strong></li>
            {strategy.is_intraday && (
              <li>Orders processed during trading hours ({strategy.start_time} - {strategy.end_time})</li>
            )}
            <li>Symbol must be configured in mappings above to receive orders</li>
          </ul>
        </AlertDescription>
      </Alert>

      {/* Manage Actions */}
      <div className="flex items-center gap-2 pt-2 border-t">
        <Button
          variant={strategy.is_active ? 'outline' : 'default'}
          size="sm"
          onClick={handleToggle}
          disabled={toggling}
        >
          {toggling ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Power className="h-4 w-4 mr-1" />
          )}
          {strategy.is_active ? 'Deactivate Strategy' : 'Activate Strategy'}
        </Button>
        <div className="flex-1" />
        <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm">
              <Trash2 className="h-4 w-4 mr-1" />
              Delete Strategy
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete Strategy</AlertDialogTitle>
              <AlertDialogDescription>
                Are you sure you want to delete "{strategy.name}"? This action cannot be undone. All symbol mappings will also be deleted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleDelete}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700"
              >
                {deleting ? 'Deleting...' : 'Delete Strategy'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      {/* Bulk Import Dialog */}
      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Bulk Import Symbols</DialogTitle>
            <DialogDescription>
              Paste CSV data: Symbol,Exchange,Quantity,Product (one per line, no header).
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleBulkImport}>
            <Textarea
              placeholder="RELIANCE,NSE,100,CNC&#10;TATAMOTORS,NSE,50,MIS"
              value={csvData}
              onChange={(e) => setCsvData(e.target.value)}
              rows={6}
              maxLength={102400}
              className="font-mono text-sm"
            />
            <DialogFooter className="mt-4">
              <Button type="button" variant="outline" onClick={() => setBulkDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Importing...' : 'Import'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
