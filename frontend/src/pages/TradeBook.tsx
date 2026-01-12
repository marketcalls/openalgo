import { Download, Loader2, RefreshCw, Settings2, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { tradingApi } from '@/api/trading'
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
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn, sanitizeCSV } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { onModeChange } from '@/stores/themeStore'
import type { Trade } from '@/types/trading'

interface FilterState {
  action: string[]
  exchange: string[]
  product: string[]
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 2,
  }).format(value)
}

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return timestamp
  }
}

export default function TradeBook() {
  const { apiKey } = useAuthStore()
  const [trades, setTrades] = useState<Trade[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [filters, setFilters] = useState<FilterState>({
    action: [],
    exchange: [],
    product: [],
  })
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Filter trades
  const filteredTrades = useMemo(() => {
    return trades.filter((trade) => {
      if (filters.action.length > 0 && !filters.action.includes(trade.action)) return false
      if (filters.exchange.length > 0 && !filters.exchange.includes(trade.exchange)) return false
      if (filters.product.length > 0 && !filters.product.includes(trade.product)) return false
      return true
    })
  }, [trades, filters])

  const hasActiveFilters =
    filters.action.length > 0 || filters.exchange.length > 0 || filters.product.length > 0

  const toggleFilter = (type: keyof FilterState, value: string) => {
    setFilters((prev) => {
      const arr = prev[type]
      const index = arr.indexOf(value)
      if (index > -1) {
        return { ...prev, [type]: arr.filter((v) => v !== value) }
      }
      return { ...prev, [type]: [...arr, value] }
    })
  }

  const clearFilters = () => {
    setFilters({ action: [], exchange: [], product: [] })
  }

  const fetchTrades = useCallback(
    async (showRefresh = false) => {
      if (!apiKey) {
        setIsLoading(false)
        return
      }

      if (showRefresh) setIsRefreshing(true)

      try {
        const response = await tradingApi.getTrades(apiKey)
        if (response.status === 'success' && response.data) {
          setTrades(response.data)
          setError(null)
        } else {
          setError(response.message || 'Failed to fetch trades')
        }
      } catch {
        setError('Failed to fetch trades')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [apiKey]
  )

  useEffect(() => {
    fetchTrades()
    const interval = setInterval(() => fetchTrades(), 10000)
    return () => clearInterval(interval)
  }, [fetchTrades])

  // Listen for mode changes (live/analyze) and refresh data
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      fetchTrades()
    })
    return () => unsubscribe()
  }, [fetchTrades])

  const exportToCSV = () => {
    const headers = [
      'Symbol',
      'Exchange',
      'Product',
      'Action',
      'Qty',
      'Price',
      'Trade Value',
      'Order ID',
      'Time',
    ]
    const rows = trades.map((t) => [
      sanitizeCSV(t.symbol),
      sanitizeCSV(t.exchange),
      sanitizeCSV(t.product),
      sanitizeCSV(t.action),
      sanitizeCSV(t.quantity),
      sanitizeCSV(t.average_price),
      sanitizeCSV(t.trade_value),
      sanitizeCSV(t.orderid),
      sanitizeCSV(t.timestamp),
    ])

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tradebook_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  const stats = {
    total: filteredTrades.length,
    buyTrades: filteredTrades.filter((t) => t.action === 'BUY').length,
    sellTrades: filteredTrades.filter((t) => t.action === 'SELL').length,
  }

  const FilterChip = ({
    type,
    value,
    label,
  }: {
    type: keyof FilterState
    value: string
    label: string
  }) => (
    <Button
      variant={filters[type].includes(value) ? 'default' : 'outline'}
      size="sm"
      className={cn(
        'rounded-full',
        filters[type].includes(value) && 'bg-pink-500 hover:bg-pink-600'
      )}
      onClick={() => toggleFilter(type, value)}
    >
      {label}
    </Button>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trade Book</h1>
          <p className="text-muted-foreground">View your executed trades</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Settings Button */}
          <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
            <DialogTrigger asChild>
              <Button
                variant={hasActiveFilters ? 'default' : 'outline'}
                size="sm"
                className="relative"
              >
                <Settings2 className="h-4 w-4 mr-2" />
                Filters
                {hasActiveFilters && (
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-red-500 rounded-full" />
                )}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Trade Filters</DialogTitle>
                <DialogDescription>Filter trades by action, exchange, or product</DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* Action */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Action
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip type="action" value="BUY" label="Buy" />
                    <FilterChip type="action" value="SELL" label="Sell" />
                  </div>
                </div>

                {/* Exchange */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Exchange
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip type="exchange" value="NSE" label="NSE" />
                    <FilterChip type="exchange" value="BSE" label="BSE" />
                    <FilterChip type="exchange" value="NFO" label="NFO" />
                    <FilterChip type="exchange" value="BFO" label="BFO" />
                    <FilterChip type="exchange" value="MCX" label="MCX" />
                    <FilterChip type="exchange" value="CDS" label="CDS" />
                  </div>
                </div>

                {/* Product */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Product
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip type="product" value="CNC" label="CNC" />
                    <FilterChip type="product" value="MIS" label="MIS" />
                    <FilterChip type="product" value="NRML" label="NRML" />
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={clearFilters}>
                  Clear All
                </Button>
                <Button onClick={() => setSettingsOpen(false)}>Done</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchTrades(true)}
            disabled={isRefreshing}
          >
            <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={exportToCSV}>
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
        </div>
      </div>

      {/* Active Filters Bar */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">Active Filters:</span>
          {filters.action.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          {filters.exchange.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          {filters.product.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="text-red-500 border-red-500/50 hover:bg-red-500/10"
            onClick={clearFilters}
          >
            Clear All
          </Button>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Trades</CardDescription>
            <CardTitle className="text-2xl">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Buy Trades</CardDescription>
            <CardTitle className="text-2xl text-green-600 flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              {stats.buyTrades}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Sell Trades</CardDescription>
            <CardTitle className="text-2xl text-red-600 flex items-center gap-2">
              <TrendingDown className="h-5 w-5" />
              {stats.sellTrades}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Trades Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-muted-foreground">{error}</div>
          ) : filteredTrades.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {hasActiveFilters ? (
                <div>
                  <p className="mb-4">No trades match your filters</p>
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    Clear Filters
                  </Button>
                </div>
              ) : (
                'No trades today'
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Trade Value</TableHead>
                    <TableHead>Order ID</TableHead>
                    <TableHead>Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTrades.map((trade, index) => (
                    <TableRow key={`${trade.orderid}-${index}`}>
                      <TableCell className="font-medium">{trade.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{trade.exchange}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{trade.product}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={trade.action === 'BUY' ? 'default' : 'destructive'}
                          className={cn('gap-1', trade.action === 'BUY' ? 'bg-green-500' : '')}
                        >
                          {trade.action === 'BUY' ? (
                            <TrendingUp className="h-3 w-3" />
                          ) : (
                            <TrendingDown className="h-3 w-3" />
                          )}
                          {trade.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">{trade.quantity}</TableCell>
                      <TableCell className="text-right font-mono">
                        {formatCurrency(trade.average_price)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatCurrency(trade.trade_value)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{trade.orderid}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatTime(trade.timestamp)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
