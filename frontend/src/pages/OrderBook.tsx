import {
  CheckCircle2,
  Clock,
  Download,
  Loader2,
  Pencil,
  RefreshCw,
  Settings2,
  X,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { showToast } from '@/utils/toast'
import { type QuotesData, tradingApi } from '@/api/trading'
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
import { Input } from '@/components/ui/input'
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
// Note: AlertDialog still used for Cancel All Orders
import { useAuthStore } from '@/stores/authStore'
import { onModeChange } from '@/stores/themeStore'
import type { Order, OrderStats } from '@/types/trading'

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

const statusConfig: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
  complete: { icon: CheckCircle2, color: 'text-green-500', label: 'complete' },
  rejected: { icon: XCircle, color: 'text-red-500', label: 'rejected' },
  cancelled: { icon: XCircle, color: 'text-gray-500', label: 'cancelled' },
  open: { icon: Clock, color: 'text-blue-500', label: 'open' },
}

export default function OrderBook() {
  const { apiKey } = useAuthStore()
  const [orders, setOrders] = useState<Order[]>([])
  const [stats, setStats] = useState<OrderStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [statusFilter, setStatusFilter] = useState<string[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Modify order state
  const [modifyDialogOpen, setModifyDialogOpen] = useState(false)
  const [modifyingOrder, setModifyingOrder] = useState<Order | null>(null)
  const [quotes, setQuotes] = useState<QuotesData | null>(null)
  const [isLoadingQuotes, setIsLoadingQuotes] = useState(false)
  const [modifyForm, setModifyForm] = useState({
    quantity: 0,
    price: 0,
    trigger_price: 0,
    pricetype: 'MARKET' as string,
    product: 'MIS' as string,
  })

  // Filter orders based on status
  const filteredOrders = useMemo(() => {
    if (statusFilter.length === 0) return orders
    return orders.filter((order) => statusFilter.includes(order.order_status))
  }, [orders, statusFilter])

  const hasActiveFilters = statusFilter.length > 0

  const toggleStatusFilter = (status: string) => {
    setStatusFilter((prev) => {
      if (prev.includes(status)) {
        return prev.filter((s) => s !== status)
      }
      return [...prev, status]
    })
  }

  const clearFilters = () => {
    setStatusFilter([])
  }

  const fetchOrders = useCallback(
    async (showRefresh = false) => {
      if (!apiKey) {
        setIsLoading(false)
        return
      }

      if (showRefresh) setIsRefreshing(true)

      try {
        const response = await tradingApi.getOrders(apiKey)
        if (response.status === 'success' && response.data) {
          setOrders(response.data.orders || [])
          setStats(response.data.statistics)
          setError(null)
        } else {
          setError(response.message || 'Failed to fetch orders')
        }
      } catch {
        setError('Failed to fetch orders')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [apiKey]
  )

  useEffect(() => {
    fetchOrders()
    const interval = setInterval(() => fetchOrders(), 10000)
    return () => clearInterval(interval)
  }, [fetchOrders])

  // Listen for mode changes (live/analyze) and refresh data
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      fetchOrders()
    })
    return () => unsubscribe()
  }, [fetchOrders])

  const handleCancelOrder = async (orderid: string) => {
    try {
      const response = await tradingApi.cancelOrder(orderid)
      if (response.status === 'success') {
        showToast.success(`Order cancelled: ${orderid}`, 'orders')
        setTimeout(() => fetchOrders(true), 1000)
      } else {
        showToast.error(response.message || 'Failed to cancel order', 'orders')
      }
    } catch (error) {
      const axiosError = error as { response?: { data?: { message?: string } } }
      const message = axiosError.response?.data?.message || 'Failed to cancel order'
      showToast.error(message, 'orders')
    }
  }

  const handleCancelAllOrders = async () => {
    try {
      const response = await tradingApi.cancelAllOrders()
      if (response.status === 'success') {
        showToast.success(response.message || 'All orders cancelled', 'orders')
        // Delay refresh to allow broker to process cancellations
        setTimeout(() => fetchOrders(true), 2000)
      } else if (response.status === 'info') {
        showToast.info(response.message || 'No open orders to cancel', 'orders')
      } else {
        showToast.error(response.message || 'Failed to cancel all orders', 'orders')
      }
    } catch (error) {
      const axiosError = error as { response?: { data?: { message?: string } } }
      const message = axiosError.response?.data?.message || 'Failed to cancel all orders'
      showToast.error(message, 'orders')
    }
  }

  const openModifyDialog = async (order: Order) => {
    setModifyingOrder(order)
    setModifyForm({
      quantity: order.quantity,
      price: order.price,
      trigger_price: order.trigger_price,
      pricetype: order.pricetype,
      product: order.product,
    })
    setQuotes(null)
    setModifyDialogOpen(true)

    // Fetch quotes for the symbol
    if (apiKey) {
      setIsLoadingQuotes(true)
      try {
        const response = await tradingApi.getQuotes(apiKey, order.symbol, order.exchange)
        if (response.status === 'success' && response.data) {
          setQuotes(response.data)
        }
      } catch {
        // Silently fail - quotes are optional for order modification
      } finally {
        setIsLoadingQuotes(false)
      }
    }
  }

  const handleModifyOrder = async () => {
    if (!modifyingOrder) return

    try {
      const response = await tradingApi.modifyOrder(modifyingOrder.orderid, {
        symbol: modifyingOrder.symbol,
        exchange: modifyingOrder.exchange,
        action: modifyingOrder.action,
        product: modifyingOrder.product,
        pricetype: modifyForm.pricetype,
        price: modifyForm.price,
        quantity: modifyForm.quantity,
        trigger_price: modifyForm.trigger_price,
      })
      if (response.status === 'success') {
        showToast.success(`Order modified: ${modifyingOrder.orderid}`, 'orders')
        setModifyDialogOpen(false)
        setTimeout(() => fetchOrders(true), 1000)
      } else {
        showToast.error(response.message || 'Failed to modify order', 'orders')
      }
    } catch (error) {
      const axiosError = error as { response?: { data?: { message?: string } } }
      const message = axiosError.response?.data?.message || 'Failed to modify order'
      showToast.error(message, 'orders')
    }
  }

  const exportToCSV = () => {
    const headers = [
      'Symbol',
      'Exchange',
      'Action',
      'Qty',
      'Price',
      'Trigger',
      'Type',
      'Product',
      'Order ID',
      'Status',
      'Time',
    ]
    const rows = orders.map((o) => [
      sanitizeCSV(o.symbol),
      sanitizeCSV(o.exchange),
      sanitizeCSV(o.action),
      sanitizeCSV(o.quantity),
      sanitizeCSV(o.price),
      sanitizeCSV(o.trigger_price),
      sanitizeCSV(o.pricetype),
      sanitizeCSV(o.product),
      sanitizeCSV(o.orderid),
      sanitizeCSV(o.order_status),
      sanitizeCSV(o.timestamp),
    ])

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `orderbook_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  const openOrders = orders.filter((o) => o.order_status === 'open')

  const FilterChip = ({ status, label }: { status: string; label: string }) => (
    <Button
      variant={statusFilter.includes(status) ? 'default' : 'outline'}
      size="sm"
      className={cn(
        'rounded-full',
        statusFilter.includes(status) && 'bg-pink-500 hover:bg-pink-600'
      )}
      onClick={() => toggleStatusFilter(status)}
    >
      {label}
    </Button>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Order Book</h1>
          <p className="text-muted-foreground">View and manage your orders</p>
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
                <DialogTitle>Order Filters</DialogTitle>
                <DialogDescription>Filter orders by status</DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* Order Status */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Order Status
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip status="complete" label="Complete" />
                    <FilterChip status="open" label="Open" />
                    <FilterChip status="rejected" label="Rejected" />
                    <FilterChip status="cancelled" label="Cancelled" />
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
            onClick={() => fetchOrders(true)}
            disabled={isRefreshing}
          >
            <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={exportToCSV}>
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm" disabled={openOrders.length === 0}>
                <X className="h-4 w-4 mr-2" />
                Cancel All
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Cancel All Orders?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will cancel all {openOrders.length} open orders. This action cannot be
                  undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep Orders</AlertDialogCancel>
                <AlertDialogAction onClick={handleCancelAllOrders}>Cancel All</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Active Filters Bar */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">Active Filters:</span>
          {statusFilter.map((status) => (
            <Badge
              key={status}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {status}
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
      <div className="grid gap-4 md:grid-cols-5">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Buy Orders</CardDescription>
            <CardTitle className="text-2xl text-green-600">
              {stats?.total_buy_orders ?? 0}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Sell Orders</CardDescription>
            <CardTitle className="text-2xl text-red-600">{stats?.total_sell_orders ?? 0}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Completed</CardDescription>
            <CardTitle className="text-2xl">{stats?.total_completed_orders ?? 0}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Open</CardDescription>
            <CardTitle className="text-2xl text-blue-600">
              {stats?.total_open_orders ?? 0}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Rejected</CardDescription>
            <CardTitle className="text-2xl text-red-600">
              {stats?.total_rejected_orders ?? 0}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Orders Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-muted-foreground">{error}</div>
          ) : filteredOrders.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {hasActiveFilters ? (
                <div>
                  <p className="mb-4">No orders match your filters</p>
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    Clear Filters
                  </Button>
                </div>
              ) : (
                'No orders today'
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[120px]">Symbol</TableHead>
                    <TableHead className="w-[80px]">Exchange</TableHead>
                    <TableHead className="w-[70px]">Action</TableHead>
                    <TableHead className="w-[70px] text-right">Qty</TableHead>
                    <TableHead className="w-[100px] text-right">Price</TableHead>
                    <TableHead className="w-[100px] text-right">Trigger</TableHead>
                    <TableHead className="w-[80px]">Type</TableHead>
                    <TableHead className="w-[70px]">Product</TableHead>
                    <TableHead className="w-[140px]">Order ID</TableHead>
                    <TableHead className="w-[100px]">Status</TableHead>
                    <TableHead className="w-[100px]">Time</TableHead>
                    <TableHead className="w-[60px]">Cancel</TableHead>
                    <TableHead className="w-[60px]">Modify</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredOrders.map((order, index) => {
                    const status = statusConfig[order.order_status] || statusConfig.open
                    const StatusIcon = status.icon
                    const canCancel = order.order_status === 'open'

                    return (
                      <TableRow key={`${order.orderid}-${index}`}>
                        <TableCell className="font-medium">{order.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{order.exchange}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={order.action === 'BUY' ? 'default' : 'destructive'}
                            className={order.action === 'BUY' ? 'bg-green-500' : ''}
                          >
                            {order.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">{order.quantity}</TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(order.price)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(order.trigger_price)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{order.pricetype}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{order.product}</Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{order.orderid}</TableCell>
                        <TableCell>
                          <div className={cn('flex items-center gap-1', status.color)}>
                            <StatusIcon className="h-4 w-4" />
                            <span className="text-sm">{status.label}</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatTime(order.timestamp)}
                        </TableCell>
                        <TableCell>
                          {canCancel && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                              onClick={() => handleCancelOrder(order.orderid)}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          )}
                        </TableCell>
                        <TableCell>
                          {canCancel && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-blue-500 hover:text-blue-600"
                              onClick={() => openModifyDialog(order)}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Modify Order Dialog */}
      <Dialog open={modifyDialogOpen} onOpenChange={setModifyDialogOpen}>
        <DialogContent className="sm:max-w-[550px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span>Modify Order</span>
              <Badge
                variant={modifyingOrder?.action === 'BUY' ? 'default' : 'destructive'}
                className={modifyingOrder?.action === 'BUY' ? 'bg-green-500' : ''}
              >
                {modifyingOrder?.action}
              </Badge>
            </DialogTitle>
            <DialogDescription className="sr-only">Modify order details</DialogDescription>
          </DialogHeader>

          {/* Symbol and Order Info */}
          <div className="rounded-lg border p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-lg font-semibold">{modifyingOrder?.symbol}</div>
                <div className="text-sm text-muted-foreground">{modifyingOrder?.exchange}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-muted-foreground">Order ID</div>
                <div className="font-mono text-sm">{modifyingOrder?.orderid}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 pt-2 border-t">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Type:</span>
                <Badge variant="secondary" className="text-xs">
                  {modifyForm.pricetype}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Product:</span>
                <Badge variant="outline" className="text-xs">
                  {modifyForm.product}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Qty:</span>
                <span className="font-mono text-sm font-medium">{modifyForm.quantity}</span>
              </div>
            </div>
          </div>

          {/* Market Quotes Section */}
          <div className="rounded-lg border bg-muted/50 p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium">Market Data</span>
              {isLoadingQuotes && <Loader2 className="h-4 w-4 animate-spin" />}
            </div>
            {quotes ? (
              <div className="grid grid-cols-4 gap-4 text-sm">
                <div>
                  <div className="text-muted-foreground text-xs">LTP</div>
                  <div className="font-mono font-semibold">{formatCurrency(quotes.ltp)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Bid</div>
                  <div className="font-mono text-green-600">{formatCurrency(quotes.bid)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Ask</div>
                  <div className="font-mono text-red-600">{formatCurrency(quotes.ask)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Prev Close</div>
                  <div className="font-mono">{formatCurrency(quotes.prev_close)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Open</div>
                  <div className="font-mono">{formatCurrency(quotes.open)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">High</div>
                  <div className="font-mono text-green-600">{formatCurrency(quotes.high)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Low</div>
                  <div className="font-mono text-red-600">{formatCurrency(quotes.low)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs">Volume</div>
                  <div className="font-mono">{quotes.volume.toLocaleString('en-IN')}</div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                {isLoadingQuotes ? 'Loading quotes...' : 'Quotes not available'}
              </div>
            )}
          </div>

          {/* Editable Fields - Based on Order Type */}
          <div className="grid gap-4 py-2">
            {/* Price field - shown for LIMIT and SL orders */}
            {(modifyForm.pricetype === 'LIMIT' || modifyForm.pricetype === 'SL') && (
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="price" className="text-right">
                  Price
                </Label>
                <Input
                  id="price"
                  type="number"
                  step="0.05"
                  value={modifyForm.price}
                  onChange={(e) =>
                    setModifyForm({ ...modifyForm, price: parseFloat(e.target.value) || 0 })
                  }
                  className="col-span-3"
                />
              </div>
            )}
            {/* Trigger Price field - shown for SL and SL-M orders */}
            {(modifyForm.pricetype === 'SL' || modifyForm.pricetype === 'SL-M') && (
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="trigger_price" className="text-right">
                  Trigger Price
                </Label>
                <Input
                  id="trigger_price"
                  type="number"
                  step="0.05"
                  value={modifyForm.trigger_price}
                  onChange={(e) =>
                    setModifyForm({ ...modifyForm, trigger_price: parseFloat(e.target.value) || 0 })
                  }
                  className="col-span-3"
                />
              </div>
            )}
            {/* Info for MARKET orders */}
            {modifyForm.pricetype === 'MARKET' && (
              <div className="text-sm text-muted-foreground text-center py-2">
                Market orders cannot be modified. Cancel and place a new order.
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setModifyDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleModifyOrder}>Modify Order</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
