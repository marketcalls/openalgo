import { useEffect, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Loader2,
  RefreshCw,
  Download,
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
import type { Holding, HoldingsStats } from '@/types/trading';
import { cn, sanitizeCSV } from '@/lib/utils';

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

export default function Holdings() {
  const { apiKey } = useAuthStore();
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [stats, setStats] = useState<HoldingsStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHoldings = async (showRefresh = false) => {
    if (!apiKey) {
      setIsLoading(false);
      return;
    }

    if (showRefresh) setIsRefreshing(true);

    try {
      const response = await tradingApi.getHoldings(apiKey);
      if (response.status === 'success' && response.data) {
        setHoldings(response.data.holdings || []);
        setStats(response.data.statistics);
        setError(null);
      } else {
        setError(response.message || 'Failed to fetch holdings');
      }
    } catch {
      setError('Failed to fetch holdings');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchHoldings();
    const interval = setInterval(() => fetchHoldings(), 30000);
    return () => clearInterval(interval);
  }, [apiKey]);

  const exportToCSV = () => {
    const headers = ['Symbol', 'Exchange', 'Quantity', 'Product', 'P&L', 'P&L %'];
    const rows = holdings.map((h) => [
      sanitizeCSV(h.symbol),
      sanitizeCSV(h.exchange),
      sanitizeCSV(h.quantity),
      sanitizeCSV(h.product),
      sanitizeCSV(h.pnl),
      sanitizeCSV(h.pnlpercent),
    ]);

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `holdings_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const isProfit = (value: number) => value >= 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Investor Summary</h1>
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
              {stats ? formatCurrency(stats.totalholdingvalue) : '---'}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Investment Value</CardDescription>
            <CardTitle className="text-2xl">
              {stats ? formatCurrency(stats.totalinvvalue) : '---'}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Profit and Loss</CardDescription>
            <CardTitle
              className={cn(
                'text-2xl',
                stats && isProfit(stats.totalprofitandloss)
                  ? 'text-green-600'
                  : 'text-red-600'
              )}
            >
              {stats ? (
                <div className="flex items-center gap-1">
                  {isProfit(stats.totalprofitandloss) ? (
                    <TrendingUp className="h-5 w-5" />
                  ) : (
                    <TrendingDown className="h-5 w-5" />
                  )}
                  {formatCurrency(stats.totalprofitandloss)}
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
                stats && isProfit(stats.totalpnlpercentage)
                  ? 'text-green-600'
                  : 'text-red-600'
              )}
            >
              {stats ? formatPercent(stats.totalpnlpercentage) : '---'}
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
            <div className="text-center py-12 text-muted-foreground">
              No holdings found
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Trading Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="text-right">Profit and Loss</TableHead>
                    <TableHead className="text-right">PnL Percentage</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {holdings.map((holding, index) => (
                    <TableRow key={`${holding.symbol}-${holding.exchange}-${index}`}>
                      <TableCell className="font-medium">{holding.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{holding.exchange}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {holding.quantity}
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
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
