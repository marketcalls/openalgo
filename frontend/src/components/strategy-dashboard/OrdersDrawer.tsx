import { CheckCircle2, Clock, ClipboardList, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { StrategyOrder } from '@/types/strategy-dashboard'

interface OrdersDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  strategyId: number
  strategyName: string
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'complete':
      return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
    case 'rejected':
      return <XCircle className="h-3.5 w-3.5 text-red-500" />
    case 'cancelled':
      return <XCircle className="h-3.5 w-3.5 text-gray-400" />
    case 'open':
    case 'pending':
      return <Clock className="h-3.5 w-3.5 text-blue-500" />
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground" />
  }
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    day: '2-digit',
    month: 'short',
  })
}

export function OrdersDrawer({
  open,
  onOpenChange,
  strategyId,
  strategyName,
}: OrdersDrawerProps) {
  const [orders, setOrders] = useState<StrategyOrder[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    const fetchOrders = async () => {
      setLoading(true)
      try {
        const data = await strategyDashboardApi.getOrders(strategyId)
        setOrders(data)
      } catch {
        setOrders([])
      } finally {
        setLoading(false)
      }
    }
    fetchOrders()
  }, [open, strategyId])

  const buyCount = orders.filter((o) => o.action === 'BUY').length
  const sellCount = orders.filter((o) => o.action === 'SELL').length
  const completeCount = orders.filter((o) => o.order_status === 'complete').length
  const rejectedCount = orders.filter((o) => o.order_status === 'rejected').length

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-[600px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5" />
            Orders — {strategyName}
          </SheetTitle>
          <SheetDescription>
            {orders.length} orders total
          </SheetDescription>
        </SheetHeader>

        {/* Stats row */}
        {!loading && orders.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            <Badge variant="outline" className="text-green-600">Buy: {buyCount}</Badge>
            <Badge variant="outline" className="text-red-600">Sell: {sellCount}</Badge>
            <Badge variant="outline" className="text-green-600">
              <CheckCircle2 className="h-3 w-3 mr-1" /> {completeCount}
            </Badge>
            {rejectedCount > 0 && (
              <Badge variant="outline" className="text-red-600">
                <XCircle className="h-3 w-3 mr-1" /> {rejectedCount}
              </Badge>
            )}
          </div>
        )}

        <div className="mt-4">
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : orders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <ClipboardList className="h-10 w-10 mb-3 opacity-40" />
              <p className="text-sm">No orders yet</p>
            </div>
          ) : (
            <div className="relative w-full overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Avg Price</TableHead>
                    <TableHead>Entry/Exit</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orders.map((order) => (
                    <TableRow key={order.id}>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatTime(order.created_at)}
                      </TableCell>
                      <TableCell className="font-medium">{order.symbol}</TableCell>
                      <TableCell>
                        <Badge
                          className={
                            order.action === 'BUY'
                              ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                              : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                          }
                        >
                          {order.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {order.quantity}
                      </TableCell>
                      <TableCell className="text-xs">{order.price_type}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          {getStatusIcon(order.order_status)}
                          <span className="text-xs capitalize">{order.order_status}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {order.average_price ? order.average_price.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {order.exit_reason ? 'Exit' : 'Entry'}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
