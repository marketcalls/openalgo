import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronUp,
  Info,
  PlayCircle,
  RefreshCw,
  Settings,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { io, type Socket } from 'socket.io-client'
import { webClient } from '@/api/client'
import { useAlertStore } from '@/stores/alertStore'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface PendingOrder {
  id: number
  strategy: string
  api_type: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  price_type: string
  product_type: string
  status: 'pending' | 'approved' | 'rejected'
  created_at_ist: string
  raw_order_data: Record<string, unknown>
}

interface OrderStats {
  total_pending: number
  total_approved: number
  total_rejected: number
  total_buy_orders: number
  total_sell_orders: number
}

interface ActionCenterResponse {
  status: string
  data: {
    orders: PendingOrder[]
    statistics: OrderStats
  }
}

export default function ActionCenterPage() {
  const [orders, setOrders] = useState<PendingOrder[]>([])
  const [stats, setStats] = useState<OrderStats>({
    total_pending: 0,
    total_approved: 0,
    total_rejected: 0,
    total_buy_orders: 0,
    total_sell_orders: 0,
  })
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [activeFilter, setActiveFilter] = useState<'pending' | 'approved' | 'rejected' | 'all'>(
    'pending'
  )
  const [expandedOrders, setExpandedOrders] = useState<Set<number>>(new Set())

  // Confirmation dialogs
  const [orderToDelete, setOrderToDelete] = useState<PendingOrder | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isApproving, setIsApproving] = useState<number | null>(null)
  const [isRejecting, setIsRejecting] = useState<number | null>(null)
  const [isApprovingAll, setIsApprovingAll] = useState(false)

  // Socket ref for realtime updates
  const socketRef = useRef<Socket | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const statusParam = activeFilter === 'all' ? '' : activeFilter
      const response = await webClient.get<ActionCenterResponse>(
        `/action-center/api/data${statusParam ? `?status=${statusParam}` : ''}`
      )

      if (response.data.status === 'success') {
        setOrders(Array.isArray(response.data.data.orders) ? response.data.data.orders : [])
        setStats(
          response.data.data.statistics || {
            total_pending: 0,
            total_approved: 0,
            total_rejected: 0,
            total_buy_orders: 0,
            total_sell_orders: 0,
          }
        )
      }
    } catch (error) {
      showToast.error('Failed to load action center data', 'actionCenter')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [activeFilter])

  useEffect(() => {
    fetchData()
    // Auto-refresh every 30 seconds for pending orders
    if (activeFilter === 'pending') {
      const interval = setInterval(fetchData, 30000)
      return () => clearInterval(interval)
    }
  }, [fetchData, activeFilter])

  // Socket connection for realtime order updates
  useEffect(() => {
    // Create audio element for alert sounds
    audioRef.current = new Audio('/sounds/alert.mp3')
    audioRef.current.preload = 'auto'

    // Connect to socket server
    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
    })

    const socket = socketRef.current

    // Listen for new pending orders (semi-auto mode)
    socket.on('pending_order_created', (data: { api_type: string; message: string }) => {
      const { shouldShowToast, shouldPlaySound } = useAlertStore.getState()

      // Play alert sound if enabled
      if (shouldPlaySound() && shouldShowToast('actionCenter') && audioRef.current) {
        audioRef.current.play().catch(() => {})
      }

      // Show toast notification (showToast handles category filtering)
      showToast.warning(`New Order Queued: ${data.message}`, 'actionCenter', {
        duration: 5000,
      })

      // Refresh data to show new order (always do this regardless of toast settings)
      fetchData()
    })

    // Listen for order updates (approved, rejected, deleted)
    socket.on('pending_order_updated', () => {
      // Refresh data
      fetchData()
    })

    return () => {
      socket.disconnect()
    }
  }, [fetchData])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchData()
    showToast.success('Data refreshed', 'actionCenter')
  }

  const handleApprove = async (orderId: number) => {
    setIsApproving(orderId)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        `/action-center/approve/${orderId}`,
        {}
      )

      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Order approved and executed', 'actionCenter')
        fetchData()
      } else if (response.data.status === 'warning') {
        showToast.warning(response.data.message, 'actionCenter')
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to approve order', 'actionCenter')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to approve order', 'actionCenter')
    } finally {
      setIsApproving(null)
    }
  }

  const handleReject = async (orderId: number) => {
    setIsRejecting(orderId)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        `/action-center/reject/${orderId}`,
        { reason: 'Rejected by user' }
      )

      if (response.data.status === 'success') {
        showToast.success('Order rejected', 'actionCenter')
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to reject order', 'actionCenter')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to reject order', 'actionCenter')
    } finally {
      setIsRejecting(null)
    }
  }

  const handleDelete = async () => {
    if (!orderToDelete) return

    setIsDeleting(true)
    try {
      const response = await webClient.delete<{ status: string; message: string }>(
        `/action-center/delete/${orderToDelete.id}`
      )

      if (response.data.status === 'success') {
        showToast.success('Order deleted', 'actionCenter')
        setOrderToDelete(null)
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to delete order', 'actionCenter')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to delete order', 'actionCenter')
    } finally {
      setIsDeleting(false)
    }
  }

  const handleApproveAll = async () => {
    setIsApprovingAll(true)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        '/action-center/approve-all',
        {}
      )

      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'All orders approved', 'actionCenter')
        fetchData()
      } else if (response.data.status === 'warning') {
        showToast.warning(response.data.message, 'actionCenter')
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to approve all orders', 'actionCenter')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to approve all orders', 'actionCenter')
    } finally {
      setIsApprovingAll(false)
    }
  }

  const toggleExpanded = (orderId: number) => {
    setExpandedOrders((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(orderId)) {
        newSet.delete(orderId)
      } else {
        newSet.add(orderId)
      }
      return newSet
    })
  }

  const getExchangeBadgeVariant = (exchange: string): 'default' | 'secondary' | 'outline' => {
    switch (exchange) {
      case 'NSE':
        return 'default'
      case 'NFO':
        return 'secondary'
      default:
        return 'outline'
    }
  }

  const getPriceTypeBadgeVariant = (
    priceType: string
  ): 'default' | 'secondary' | 'destructive' | 'outline' => {
    switch (priceType) {
      case 'MARKET':
        return 'default'
      case 'LIMIT':
        return 'secondary'
      case 'SL':
      case 'SL-M':
        return 'destructive'
      default:
        return 'outline'
    }
  }

  const getRelativeTime = (istTimestamp: string): string => {
    if (!istTimestamp) return ''
    try {
      const orderTime = new Date(istTimestamp.replace(' IST', ''))
      const now = new Date()
      const diffMs = now.getTime() - orderTime.getTime()
      const diffMins = Math.floor(diffMs / 60000)

      if (diffMins < 1) return 'Just now'
      if (diffMins === 1) return '1 minute ago'
      if (diffMins < 60) return `${diffMins} minutes ago`

      const diffHours = Math.floor(diffMins / 60)
      if (diffHours === 1) return '1 hour ago'
      if (diffHours < 24) return `${diffHours} hours ago`

      const diffDays = Math.floor(diffHours / 24)
      if (diffDays === 1) return 'Yesterday'
      return `${diffDays} days ago`
    } catch {
      return ''
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
      {/* Info Alert */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>OpenAlgo Action Center</AlertTitle>
        <AlertDescription>
          Centralized hub for managing semi-automated trading orders. When Semi-Auto mode is enabled
          in API Key settings, all incoming orders are queued here for manual approval before broker
          execution.
        </AlertDescription>
      </Alert>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <PlayCircle className="h-6 w-6" />
              Action Center
            </h1>
          </div>
          <p className="text-muted-foreground">Review and manage pending orders</p>
        </div>
        <div className="flex gap-2">
          {activeFilter === 'pending' && stats.total_pending > 0 && (
            <Button
              variant="default"
              className="bg-green-500 hover:bg-green-600"
              onClick={handleApproveAll}
              disabled={isApprovingAll}
            >
              {isApprovingAll ? (
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Check className="h-4 w-4 mr-2" />
              )}
              Approve All ({stats.total_pending})
            </Button>
          )}
          <Button variant="outline" onClick={handleRefresh} disabled={isRefreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Link to="/apikey">
            <Button variant="outline">
              <Settings className="h-4 w-4 mr-2" />
              Toggle Order Mode
            </Button>
          </Link>
        </div>
      </div>

      {/* Filter Tabs */}
      <Tabs value={activeFilter} onValueChange={(v) => setActiveFilter(v as typeof activeFilter)}>
        <TabsList>
          <TabsTrigger value="pending" className="relative">
            Pending
            {stats.total_pending > 0 && (
              <Badge variant="destructive" className="ml-2 animate-pulse">
                {stats.total_pending}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="approved">
            Approved
            {stats.total_approved > 0 && (
              <Badge variant="secondary" className="ml-2 bg-green-500">
                {stats.total_approved}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="rejected">
            Rejected
            {stats.total_rejected > 0 && (
              <Badge variant="destructive" className="ml-2">
                {stats.total_rejected}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="all">All Orders</TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-yellow-500">{stats.total_pending}</p>
            <p className="text-sm text-muted-foreground">Pending Approval</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-green-500">{stats.total_buy_orders}</p>
            <p className="text-sm text-muted-foreground">Buy Orders</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-red-500">{stats.total_sell_orders}</p>
            <p className="text-sm text-muted-foreground">Sell Orders</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-green-500">{stats.total_approved}</p>
            <p className="text-sm text-muted-foreground">Approved</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-red-500">{stats.total_rejected}</p>
            <p className="text-sm text-muted-foreground">Rejected</p>
          </CardContent>
        </Card>
      </div>

      {/* Orders Table */}
      <Card>
        <CardHeader>
          <CardTitle>Orders</CardTitle>
          <CardDescription>{orders.length} orders</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Order Type</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                      <div className="space-y-2">
                        <p>No orders found</p>
                        <p className="text-sm">
                          Enable Semi-Auto mode in{' '}
                          <Link to="/apikey" className="text-primary hover:underline">
                            API Key settings
                          </Link>{' '}
                          to queue orders here
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  orders.map((order) => (
                    <>
                      <TableRow key={order.id}>
                        <TableCell>
                          <Badge variant="outline">{order.strategy}</Badge>
                          <div className="text-xs text-muted-foreground mt-1">{order.api_type}</div>
                        </TableCell>
                        <TableCell className="font-medium">{order.symbol}</TableCell>
                        <TableCell>
                          <Badge variant={getExchangeBadgeVariant(order.exchange)}>
                            {order.exchange}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            className={`gap-1 ${
                              order.action === 'BUY'
                                ? 'bg-green-500 hover:bg-green-600'
                                : 'bg-red-500 hover:bg-red-600'
                            }`}
                          >
                            {order.action === 'BUY' ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : (
                              <ArrowDown className="h-3 w-3" />
                            )}
                            {order.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">{order.quantity}</TableCell>
                        <TableCell className="text-right font-mono">{order.price || 0}</TableCell>
                        <TableCell>
                          <Badge variant={getPriceTypeBadgeVariant(order.price_type)}>
                            {order.price_type}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{order.product_type}</Badge>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm font-mono">{order.created_at_ist}</div>
                          <div className="text-xs text-muted-foreground">
                            {getRelativeTime(order.created_at_ist)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap">
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8"
                              onClick={() => toggleExpanded(order.id)}
                            >
                              {expandedOrders.has(order.id) ? (
                                <ChevronUp className="h-4 w-4" />
                              ) : (
                                <ChevronDown className="h-4 w-4" />
                              )}
                            </Button>

                            {order.status === 'pending' ? (
                              <>
                                <Button
                                  size="sm"
                                  className="bg-green-500 hover:bg-green-600 h-8"
                                  onClick={() => handleApprove(order.id)}
                                  disabled={isApproving === order.id}
                                >
                                  {isApproving === order.id ? (
                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <Check className="h-4 w-4" />
                                  )}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  className="h-8"
                                  onClick={() => handleReject(order.id)}
                                  disabled={isRejecting === order.id}
                                >
                                  {isRejecting === order.id ? (
                                    <RefreshCw className="h-4 w-4 animate-spin" />
                                  ) : (
                                    <X className="h-4 w-4" />
                                  )}
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-8 text-destructive hover:text-destructive"
                                onClick={() => setOrderToDelete(order)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>

                      {/* Expanded Details Row */}
                      {expandedOrders.has(order.id) && (
                        <TableRow>
                          <TableCell colSpan={10} className="bg-muted/50 p-4">
                            <Collapsible open={true}>
                              <CollapsibleContent>
                                <div className="space-y-4">
                                  <h4 className="font-semibold">Order Details</h4>

                                  {/* Order Type Specific Details */}
                                  {order.api_type === 'basketorder' &&
                                  order.raw_order_data.orders ? (
                                    <div className="space-y-3">
                                      <p className="text-sm text-muted-foreground">
                                        Basket Order with{' '}
                                        {Array.isArray(order.raw_order_data.orders)
                                          ? order.raw_order_data.orders.length
                                          : 0}{' '}
                                        orders
                                      </p>
                                      {Array.isArray(order.raw_order_data.orders) &&
                                        order.raw_order_data.orders.map(
                                          (basketOrder: Record<string, unknown>, idx: number) => (
                                            <Card key={idx}>
                                              <CardContent className="p-3">
                                                <div className="flex items-center gap-2 mb-2">
                                                  <Badge variant="outline">Order {idx + 1}</Badge>
                                                  <span className="font-medium">
                                                    {String(basketOrder.symbol || '')}
                                                  </span>
                                                  <Badge
                                                    className={
                                                      basketOrder.action === 'BUY'
                                                        ? 'bg-green-500'
                                                        : 'bg-red-500'
                                                    }
                                                  >
                                                    {String(basketOrder.action || '')}
                                                  </Badge>
                                                </div>
                                                <div className="grid grid-cols-4 gap-2 text-sm">
                                                  {Object.entries(basketOrder).map(
                                                    ([key, value]) => (
                                                      <div key={key}>
                                                        <span className="text-muted-foreground">
                                                          {key}:
                                                        </span>{' '}
                                                        <span className="font-medium">
                                                          {String(value)}
                                                        </span>
                                                      </div>
                                                    )
                                                  )}
                                                </div>
                                              </CardContent>
                                            </Card>
                                          )
                                        )}
                                    </div>
                                  ) : (
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                      {Object.entries(order.raw_order_data).map(([key, value]) => (
                                        <div key={key} className="bg-background rounded-lg p-3">
                                          <p className="text-xs text-muted-foreground uppercase">
                                            {key}
                                          </p>
                                          <p className="font-medium break-all">
                                            {typeof value === 'object'
                                              ? JSON.stringify(value, null, 2)
                                              : String(value)}
                                          </p>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              </CollapsibleContent>
                            </Collapsible>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!orderToDelete} onOpenChange={() => setOrderToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Order?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this order? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={isDeleting}>
              {isDeleting ? 'Deleting...' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
