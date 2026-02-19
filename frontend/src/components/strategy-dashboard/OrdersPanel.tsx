import { useEffect, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { dashboardApi } from '@/api/strategy-dashboard'
import type { DashboardOrder } from '@/types/strategy-dashboard'
import { StatusBadge } from './StatusBadge'
import { EmptyState } from './EmptyState'

interface OrdersPanelProps {
  strategyId: number
  strategyType: string
}

export function OrdersPanel({ strategyId, strategyType }: OrdersPanelProps) {
  const [orders, setOrders] = useState<DashboardOrder[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    dashboardApi
      .getOrders(strategyId, strategyType, { limit: 50 })
      .then((data) => {
        if (!cancelled) setOrders(data)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [strategyId, strategyType])

  if (loading) {
    return <div className="py-8 text-center text-sm text-muted-foreground">Loading orders...</div>
  }

  if (orders.length === 0) {
    return <EmptyState title="No orders" description="No orders recorded for this strategy." />
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Order ID</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Price</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Time</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((order) => (
            <TableRow key={order.id}>
              <TableCell className="text-xs font-mono">{order.orderid}</TableCell>
              <TableCell className="text-xs">{order.symbol}</TableCell>
              <TableCell>
                <span
                  className={`text-xs font-medium ${order.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}
                >
                  {order.action}
                </span>
              </TableCell>
              <TableCell className="text-xs">
                {order.is_entry ? 'Entry' : 'Exit'}
                {order.exit_reason && ` (${order.exit_reason})`}
              </TableCell>
              <TableCell className="text-right text-xs">{order.quantity}</TableCell>
              <TableCell className="text-right text-xs">
                {order.average_price ? order.average_price.toFixed(2) : order.price.toFixed(2)}
              </TableCell>
              <TableCell>
                <StatusBadge value={order.order_status} />
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {order.created_at
                  ? new Date(order.created_at).toLocaleTimeString('en-IN', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : '-'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
