import { Download, Loader2, Radio, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { tradingApi } from '@/api/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLivePrice, calculateLiveStats } from '@/hooks/useLivePrice'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { cn, sanitizeCSV } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { onModeChange } from '@/stores/themeStore'
import type { Holding, HoldingsStats } from '@/types/trading'

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(value)
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export default function Holdings() {
  const { apiKey } = useAuthStore()
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [stats, setStats] = useState<HoldingsStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Centralized real-time price hook with WebSocket + MultiQuotes fallback
  const { data: enhancedHoldings, isLive } = useLivePrice(holdings, {
    enabled: holdings.length > 0,
    useMultiQuotesFallback: true,
    staleThreshold: 5000,
    multiQuotesRefreshInterval: 30000,
  })

  // Calculate enhanced stats based on real-time data
  const enhancedStats = useMemo(() => {
    if (!stats) return stats

    // Check if any holding has live data
    const hasAnyLiveData = enhancedHoldings.some(
      (h) => (h as Holding & { _dataSource?: string })._dataSource !== 'rest'
    )

    // If no live data, return original REST stats
    if (!hasAnyLiveData) return stats

    // Recalculate stats with real-time data
    return calculateLiveStats(enhancedHoldings, stats)
  }, [stats, enhancedHoldings])

  const fetchHoldings = useCallback(
    async (showRefresh = false) => {
      if (!apiKey) {
        setIsLoading(false)
        return
      }

      if (showRefresh) setIsRefreshing(true)

      try {
        const response = await tradingApi.getHoldings(apiKey)
        if (response.status === 'success' && response.data) {
          setHoldings(response.data.holdings || [])
          setStats(response.data.statistics)
          setError(null)
        } else {
          setError(response.message || 'Failed to fetch holdings')
        }
      } catch {
        setError('Failed to fetch holdings')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [apiKey]
  )

  // Initial fetch and polling
  useEffect(() => {
    fetchHoldings()
    // Reduce polling interval when live (WebSocket connected AND market open)
    const intervalMs = isLive ? 30000 : 10000
    const interval = setInterval(() => fetchHoldings(), intervalMs)
    return () => clearInterval(interval)
  }, [fetchHoldings, isLive])

  // Listen for mode changes (live/analyze) and refresh data
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      fetchHoldings()
    })
    return () => unsubscribe()
  }, [fetchHoldings])

  // Centralized Socket.IO event listener for order events
  useOrderEventRefresh(fetchHoldings, {
    events: ['order_event', 'analyzer_update'],
    delay: 500,
  })

  const exportToCSV = () => {
    const headers = [
      'Symbol',
      'Exchange',
      'Quantity',
      'Avg Price',
      'LTP',
      'Product',
      'P&L',
      'P&L %',
    ]
    const rows = enhancedHoldings.map((h) => [
      sanitizeCSV(h.symbol),
      sanitizeCSV(h.exchange),
      sanitizeCSV(h.quantity),
      sanitizeCSV(h.average_price),
      sanitizeCSV(h.ltp),
      sanitizeCSV(h.product),
      sanitizeCSV(h.pnl),
      sanitizeCSV(h.pnlpercent),
    ])

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `holdings_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  const isProfit = (value: number) => value >= 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">Investor Summary</h1>
            {isLive && (
              <Badge
                variant="outline"
                className="bg-emerald-500/10 text-emerald-600 border-emerald-500/30 gap-1"
              >
                <Radio className="h-3 w-3 animate-pulse" />
                Live
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground">View your holdings portfolio</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchHoldings(true)}
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

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Holding Value</CardDescription>
            <CardTitle className="text-2xl text-primary">
              {enhancedStats ? formatCurrency(enhancedStats.totalholdingvalue) : '---'}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Investment Value</CardDescription>
            <CardTitle className="text-2xl">
              {enhancedStats ? formatCurrency(enhancedStats.totalinvvalue) : '---'}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Profit and Loss</CardDescription>
            <CardTitle
              className={cn(
                'text-2xl',
                enhancedStats && isProfit(enhancedStats.totalprofitandloss)
                  ? 'text-green-600'
                  : 'text-red-600'
              )}
            >
              {enhancedStats ? (
                <div className="flex items-center gap-1">
                  {isProfit(enhancedStats.totalprofitandloss) ? (
                    <TrendingUp className="h-5 w-5" />
                  ) : (
                    <TrendingDown className="h-5 w-5" />
                  )}
                  {formatCurrency(enhancedStats.totalprofitandloss)}
                </div>
              ) : (
                '---'
              )}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total PnL Percentage</CardDescription>
            <CardTitle
              className={cn(
                'text-2xl',
                enhancedStats && isProfit(enhancedStats.totalpnlpercentage)
                  ? 'text-green-600'
                  : 'text-red-600'
              )}
            >
              {enhancedStats ? formatPercent(enhancedStats.totalpnlpercentage) : '---'}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Holdings Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-muted-foreground">{error}</div>
          ) : holdings.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No holdings found</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Trading Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Avg Price</TableHead>
                    <TableHead className="text-right">LTP</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="text-right">Profit and Loss</TableHead>
                    <TableHead className="text-right">PnL %</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {enhancedHoldings.map((holding, index) => (
                    <TableRow key={`${holding.symbol}-${holding.exchange}-${index}`}>
                      <TableCell className="font-medium">{holding.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{holding.exchange}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">{holding.quantity}</TableCell>
                      <TableCell className="text-right font-mono">
                        {holding.average_price !== undefined
                          ? formatCurrency(holding.average_price)
                          : '-'}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {holding.ltp !== undefined ? formatCurrency(holding.ltp) : '-'}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{holding.product}</Badge>
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right font-medium',
                          isProfit(holding.pnl) ? 'text-green-600' : 'text-red-600'
                        )}
                      >
                        <div className="flex items-center justify-end gap-1">
                          {isProfit(holding.pnl) ? (
                            <TrendingUp className="h-4 w-4" />
                          ) : (
                            <TrendingDown className="h-4 w-4" />
                          )}
                          {formatCurrency(holding.pnl)}
                        </div>
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right',
                          isProfit(holding.pnlpercent) ? 'text-green-600' : 'text-red-600'
                        )}
                      >
                        {formatPercent(holding.pnlpercent)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
                <TableFooter>
                  <TableRow className="bg-muted/50">
                    <TableCell colSpan={6} className="text-right text-muted-foreground">
                      Total P&L:
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right font-bold',
                        enhancedStats && isProfit(enhancedStats.totalprofitandloss)
                          ? 'text-green-600'
                          : 'text-red-600'
                      )}
                    >
                      {enhancedStats
                        ? `${enhancedStats.totalprofitandloss >= 0 ? '+' : ''}${formatCurrency(enhancedStats.totalprofitandloss)}`
                        : '-'}
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right font-bold',
                        enhancedStats && isProfit(enhancedStats.totalpnlpercentage)
                          ? 'text-green-600'
                          : 'text-red-600'
                      )}
                    >
                      {enhancedStats ? formatPercent(enhancedStats.totalpnlpercentage) : '-'}
                    </TableCell>
                  </TableRow>
                </TableFooter>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
