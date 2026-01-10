import { useEffect, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Loader2,
  Download,
  RefreshCw,
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
import { useAuthStore } from '@/stores/authStore';
import { tradingApi } from '@/api/trading';
import type { Trade } from '@/types/trading';
import { cn, sanitizeCSV } from '@/lib/utils';

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

export default function TradeBook() {
  const { apiKey } = useAuthStore();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = async (showRefresh = false) => {
    if (!apiKey) {
      setIsLoading(false);
      return;
    }

    if (showRefresh) setIsRefreshing(true);

    try {
      const response = await tradingApi.getTrades(apiKey);
      if (response.status === 'success' && response.data) {
        setTrades(response.data);
        setError(null);
      } else {
        setError(response.message || 'Failed to fetch trades');
      }
    } catch {
      setError('Failed to fetch trades');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(() => fetchTrades(), 10000);
    return () => clearInterval(interval);
  }, [apiKey]);

  const exportToCSV = () => {
    const headers = ['Symbol', 'Exchange', 'Product', 'Action', 'Qty', 'Price', 'Trade Value', 'Order ID', 'Time'];
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
    ]);

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tradebook_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const stats = {
    total: trades.length,
    buyTrades: trades.filter((t) => t.action === 'BUY').length,
    sellTrades: trades.filter((t) => t.action === 'SELL').length,
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trade Book</h1>
          <p className="text-muted-foreground">View your executed trades</p>
        </div>
        <div className="flex items-center gap-2">
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
          ) : trades.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No trades today</div>
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
                  {trades.map((trade, index) => (
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
                          className={cn(
                            'gap-1',
                            trade.action === 'BUY' ? 'bg-green-500' : ''
                          )}
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
  );
}
