import { useEffect, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Loader2,
  Download,
  X,
  RefreshCw,
  Filter,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useAuthStore } from '@/stores/authStore';
import { tradingApi } from '@/api/trading';
import type { Position } from '@/types/trading';
import { cn, sanitizeCSV } from '@/lib/utils';
import { toast } from 'sonner';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export default function Positions() {
  const { apiKey } = useAuthStore();
  const [positions, setPositions] = useState<Position[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [productFilter, setProductFilter] = useState<string>('all');
  const [directionFilter, setDirectionFilter] = useState<string>('all');

  const fetchPositions = async (showRefresh = false) => {
    if (!apiKey) {
      setIsLoading(false);
      return;
    }

    if (showRefresh) setIsRefreshing(true);

    try {
      const response = await tradingApi.getPositions(apiKey);
      if (response.status === 'success' && response.data) {
        setPositions(response.data);
        setError(null);
      } else {
        setError(response.message || 'Failed to fetch positions');
      }
    } catch {
      setError('Failed to fetch positions');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(() => fetchPositions(), 10000);
    return () => clearInterval(interval);
  }, [apiKey]);

  const handleClosePosition = async (position: Position) => {
    try {
      const response = await tradingApi.closePosition(
        position.symbol,
        position.exchange,
        position.product
      );
      if (response.status === 'success') {
        toast.success(`Position closed: ${position.symbol}`);
        fetchPositions(true);
      } else {
        toast.error(response.message || 'Failed to close position');
      }
    } catch (err) {
      console.error('Close position error:', err);
      toast.error('Failed to close position');
    }
  };

  const handleCloseAllPositions = async () => {
    try {
      const response = await tradingApi.closeAllPositions();
      if (response.status === 'success') {
        toast.success('All positions closed');
        fetchPositions(true);
      } else {
        toast.error(response.message || 'Failed to close all positions');
      }
    } catch (err) {
      console.error('Close all positions error:', err);
      toast.error('Failed to close all positions');
    }
  };

  const exportToCSV = () => {
    const headers = ['Symbol', 'Exchange', 'Product', 'Quantity', 'Avg Price', 'LTP', 'P&L', 'P&L %'];
    const rows = filteredPositions.map((p) => [
      sanitizeCSV(p.symbol),
      sanitizeCSV(p.exchange),
      sanitizeCSV(p.product),
      sanitizeCSV(p.quantity),
      sanitizeCSV(p.average_price),
      sanitizeCSV(p.ltp),
      sanitizeCSV(p.pnl),
      sanitizeCSV(p.pnlpercent),
    ]);

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `positions_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const filteredPositions = positions.filter((p) => {
    if (productFilter !== 'all' && p.product !== productFilter) return false;
    if (directionFilter === 'long' && p.quantity <= 0) return false;
    if (directionFilter === 'short' && p.quantity >= 0) return false;
    return true;
  });

  const stats = {
    total: positions.length,
    long: positions.filter((p) => p.quantity > 0).length,
    short: positions.filter((p) => p.quantity < 0).length,
    totalPnl: positions.reduce((sum, p) => sum + p.pnl, 0),
  };

  const isProfit = (value: number) => value >= 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Positions</h1>
          <p className="text-muted-foreground">Manage your open positions</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchPositions(true)}
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
              <Button variant="destructive" size="sm" disabled={positions.length === 0}>
                <X className="h-4 w-4 mr-2" />
                Close All
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Close All Positions?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will close all {positions.length} open positions at market price.
                  This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleCloseAllPositions}>
                  Close All
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Open Positions</CardDescription>
            <CardTitle className="text-2xl">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Long</CardDescription>
            <CardTitle className="text-2xl text-green-600">{stats.long}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Short</CardDescription>
            <CardTitle className="text-2xl text-red-600">{stats.short}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total P&L</CardDescription>
            <CardTitle
              className={cn(
                'text-2xl',
                isProfit(stats.totalPnl) ? 'text-green-600' : 'text-red-600'
              )}
            >
              {formatCurrency(stats.totalPnl)}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={productFilter} onValueChange={setProductFilter}>
            <SelectTrigger className="w-32">
              <SelectValue placeholder="Product" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Products</SelectItem>
              <SelectItem value="MIS">MIS</SelectItem>
              <SelectItem value="NRML">NRML</SelectItem>
              <SelectItem value="CNC">CNC</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Select value={directionFilter} onValueChange={setDirectionFilter}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Direction" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="long">Long</SelectItem>
            <SelectItem value="short">Short</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Positions Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-muted-foreground">{error}</div>
          ) : filteredPositions.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              No open positions
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Avg Price</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                  <TableHead className="text-right">P&L %</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredPositions.map((position, index) => (
                  <TableRow key={`${position.symbol}-${position.exchange}-${index}`}>
                    <TableCell className="font-medium">{position.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{position.exchange}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{position.product}</Badge>
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right font-medium',
                        position.quantity > 0 ? 'text-green-600' : 'text-red-600'
                      )}
                    >
                      {position.quantity}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatCurrency(position.average_price)}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatCurrency(position.ltp)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right font-medium',
                        isProfit(position.pnl) ? 'text-green-600' : 'text-red-600'
                      )}
                    >
                      <div className="flex items-center justify-end gap-1">
                        {isProfit(position.pnl) ? (
                          <TrendingUp className="h-4 w-4" />
                        ) : (
                          <TrendingDown className="h-4 w-4" />
                        )}
                        {formatCurrency(position.pnl)}
                      </div>
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right',
                        isProfit(position.pnlpercent) ? 'text-green-600' : 'text-red-600'
                      )}
                    >
                      {formatPercent(position.pnlpercent)}
                    </TableCell>
                    <TableCell className="text-right">
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="sm">
                            <X className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Close Position?</AlertDialogTitle>
                            <AlertDialogDescription>
                              Close {Math.abs(position.quantity)} units of {position.symbol} at market price?
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleClosePosition(position)}>
                              Close
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
