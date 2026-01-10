import { useEffect, useState } from 'react';
import {
  Loader2,
  Download,
  X,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
} from 'lucide-react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
} from '@/components/ui/alert-dialog';
import { useAuthStore } from '@/stores/authStore';
import { tradingApi } from '@/api/trading';
import type { Order, OrderStats } from '@/types/trading';
import { cn, sanitizeCSV } from '@/lib/utils';
import { toast } from 'sonner';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 2,
  }).format(value);
}

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return timestamp;
  }
}

const statusConfig: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
  complete: { icon: CheckCircle2, color: 'text-green-500', label: 'Complete' },
  rejected: { icon: XCircle, color: 'text-red-500', label: 'Rejected' },
  cancelled: { icon: XCircle, color: 'text-gray-500', label: 'Cancelled' },
  open: { icon: Clock, color: 'text-blue-500', label: 'Open' },
  pending: { icon: Clock, color: 'text-yellow-500', label: 'Pending' },
  'trigger pending': { icon: AlertCircle, color: 'text-orange-500', label: 'Trigger Pending' },
};

export default function OrderBook() {
  const { apiKey } = useAuthStore();
  const [orders, setOrders] = useState<Order[]>([]);
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOrders = async (showRefresh = false) => {
    if (!apiKey) {
      setIsLoading(false);
      return;
    }

    if (showRefresh) setIsRefreshing(true);

    try {
      const response = await tradingApi.getOrders(apiKey);
      if (response.status === 'success' && response.data) {
        setOrders(response.data.orders || []);
        setStats(response.data.statistics);
        setError(null);
      } else {
        setError(response.message || 'Failed to fetch orders');
      }
    } catch {
      setError('Failed to fetch orders');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(() => fetchOrders(), 10000);
    return () => clearInterval(interval);
  }, [apiKey]);

  const handleCancelOrder = async (orderid: string) => {
    if (!apiKey) return;

    try {
      const response = await tradingApi.cancelOrder(apiKey, orderid, 'manual');
      if (response.status === 'success') {
        toast.success(`Order cancelled: ${orderid}`);
        fetchOrders(true);
      } else {
        toast.error(response.message || 'Failed to cancel order');
      }
    } catch {
      toast.error('Failed to cancel order');
    }
  };

  const handleCancelAllOrders = async () => {
    if (!apiKey) return;

    try {
      const response = await tradingApi.cancelAllOrders(apiKey, 'cancel_all');
      if (response.status === 'success') {
        toast.success('All orders cancelled');
        fetchOrders(true);
      } else {
        toast.error(response.message || 'Failed to cancel all orders');
      }
    } catch {
      toast.error('Failed to cancel all orders');
    }
  };

  const exportToCSV = () => {
    const headers = ['Symbol', 'Exchange', 'Action', 'Qty', 'Price', 'Trigger', 'Type', 'Product', 'Order ID', 'Status', 'Time'];
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
    ]);

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `orderbook_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const openOrders = orders.filter((o) => o.order_status === 'open' || o.order_status === 'pending' || o.order_status === 'trigger pending');

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Order Book</h1>
          <p className="text-muted-foreground">View and manage your orders</p>
        </div>
        <div className="flex items-center gap-2">
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
                  This will cancel all {openOrders.length} open orders. This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep Orders</AlertDialogCancel>
                <AlertDialogAction onClick={handleCancelAllOrders}>
                  Cancel All
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

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
            <CardTitle className="text-2xl text-red-600">
              {stats?.total_sell_orders ?? 0}
            </CardTitle>
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
          ) : orders.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No orders today</div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Trigger</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>Order ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Time</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orders.map((order, index) => {
                    const status = statusConfig[order.order_status] || statusConfig.pending;
                    const StatusIcon = status.icon;
                    const canCancel = ['open', 'pending', 'trigger pending'].includes(order.order_status);

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
                        <TableCell className="text-right">{order.quantity}</TableCell>
                        <TableCell className="text-right">{formatCurrency(order.price)}</TableCell>
                        <TableCell className="text-right">
                          {order.trigger_price > 0 ? formatCurrency(order.trigger_price) : '-'}
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
                        <TableCell className="text-right">
                          {canCancel && (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="ghost" size="sm">
                                  <X className="h-4 w-4" />
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>Cancel Order?</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    Cancel order {order.orderid} for {order.symbol}?
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>Keep Order</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => handleCancelOrder(order.orderid)}>
                                    Cancel Order
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
