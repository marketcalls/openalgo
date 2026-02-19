import { Activity, Briefcase, Calendar, Download, Package, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

interface DailyPnL {
  date: string
  realized_pnl: number
  positions_unrealized: number
  holdings_unrealized: number
  total_unrealized: number
  total_mtm: number
  portfolio_value: number
}

interface Position {
  symbol: string
  exchange: string
  product: string
  quantity: number
  average_price: number
  ltp: number
  today_realized_pnl: number
  all_time_realized_pnl: number
  status: string
  updated_at: string
}

interface Holding {
  symbol: string
  exchange: string
  quantity: number
  average_price: number
  ltp: number
  unrealized_pnl: number
  pnl_percent: number
  settlement_date: string
}

interface Trade {
  tradeid: string
  symbol: string
  exchange: string
  action: string
  quantity: number
  price: number
  product: string
  timestamp: string
}

interface Summary {
  today_realized_pnl: number
  positions_unrealized_pnl: number
  holdings_unrealized_pnl: number
  today_total_mtm: number
  all_time_realized_pnl: number
}

interface SandboxData {
  summary: Summary
  daily_pnl: DailyPnL[]
  positions: Position[]
  holdings: Holding[]
  trades: Trade[]
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function getPnLColor(value: number): string {
  if (value > 0) return 'text-green-500'
  if (value < 0) return 'text-red-500'
  return ''
}

export default function SandboxPnL() {
  const [data, setData] = useState<SandboxData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('daily')

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = async () => {
    try {
      const response = await fetch('/sandbox/mypnl/api/data', {
        credentials: 'include',
      })
      if (response.ok) {
        const result = await response.json()
        if (result.status === 'success') {
          setData(result.data)
        }
      }
    } catch (error) {
    } finally {
      setIsLoading(false)
    }
  }

  const handleExport = (type: 'daily' | 'positions' | 'holdings' | 'trades') => {
    // Trigger download by navigating to the export endpoint
    window.location.href = `/sandbox/mypnl/export/${type}`
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-8 px-4 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  const summary = data?.summary || {
    today_realized_pnl: 0,
    positions_unrealized_pnl: 0,
    holdings_unrealized_pnl: 0,
    today_total_mtm: 0,
    all_time_realized_pnl: 0,
  }

  return (
    <div className="container mx-auto py-6 px-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold">My P&L History</h1>
          <p className="text-muted-foreground mt-1">
            Track your daily and historical profit & loss
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/sandbox">
            <Settings className="h-4 w-4 mr-2" />
            Sandbox Config
          </Link>
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        {/* Today's Realized P&L */}
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground">Realized P&L</div>
            <div className={cn('text-2xl font-bold', getPnLColor(summary.today_realized_pnl))}>
              {formatCurrency(summary.today_realized_pnl)}
            </div>
            <Badge
              variant={summary.today_realized_pnl >= 0 ? 'default' : 'destructive'}
              className="mt-1"
            >
              Today
            </Badge>
          </CardContent>
        </Card>

        {/* Positions Unrealized P&L */}
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground">Positions MTM</div>
            <div
              className={cn('text-2xl font-bold', getPnLColor(summary.positions_unrealized_pnl))}
            >
              {formatCurrency(summary.positions_unrealized_pnl)}
            </div>
            <Badge variant="secondary" className="mt-1">
              Unrealized
            </Badge>
          </CardContent>
        </Card>

        {/* Holdings Unrealized P&L */}
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground">Holdings MTM</div>
            <div className={cn('text-2xl font-bold', getPnLColor(summary.holdings_unrealized_pnl))}>
              {formatCurrency(summary.holdings_unrealized_pnl)}
            </div>
            <Badge variant="outline" className="mt-1">
              Unrealized
            </Badge>
          </CardContent>
        </Card>

        {/* Today's Total MTM */}
        <Card className="border-2 border-primary">
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground">Total MTM</div>
            <div className={cn('text-2xl font-bold', getPnLColor(summary.today_total_mtm))}>
              {formatCurrency(summary.today_total_mtm)}
            </div>
            <Badge className="mt-1">Today</Badge>
          </CardContent>
        </Card>

        {/* All-Time Realized P&L */}
        <Card>
          <CardContent className="p-4">
            <div className="text-sm text-muted-foreground">All-Time P&L</div>
            <div className={cn('text-2xl font-bold', getPnLColor(summary.all_time_realized_pnl))}>
              {formatCurrency(summary.all_time_realized_pnl)}
            </div>
            <Badge
              variant={summary.all_time_realized_pnl >= 0 ? 'default' : 'destructive'}
              className="mt-1"
            >
              Lifetime
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="daily" className="gap-2">
            <Calendar className="h-4 w-4" />
            Date-wise P&L
          </TabsTrigger>
          <TabsTrigger value="positions" className="gap-2">
            <Briefcase className="h-4 w-4" />
            Positions
          </TabsTrigger>
          <TabsTrigger value="holdings" className="gap-2">
            <Package className="h-4 w-4" />
            Holdings
          </TabsTrigger>
          <TabsTrigger value="trades" className="gap-2">
            <Activity className="h-4 w-4" />
            Recent Trades
          </TabsTrigger>
        </TabsList>

        {/* Date-wise P&L Tab */}
        <TabsContent value="daily">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Date-wise P&L Report</CardTitle>
              {data?.daily_pnl && data.daily_pnl.length > 0 && (
                <Button variant="outline" size="sm" onClick={() => handleExport('daily')}>
                  <Download className="h-4 w-4 mr-2" />
                  Export CSV
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {data?.daily_pnl && data.daily_pnl.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead className="text-right">Realized P&L</TableHead>
                        <TableHead className="text-right">Positions MTM</TableHead>
                        <TableHead className="text-right">Holdings MTM</TableHead>
                        <TableHead className="text-right">Total Unrealized</TableHead>
                        <TableHead className="text-right">Total MTM</TableHead>
                        <TableHead className="text-right">Portfolio Value</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.daily_pnl.map((day, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-semibold">{day.date}</TableCell>
                          <TableCell className={cn('text-right', getPnLColor(day.realized_pnl))}>
                            {formatCurrency(day.realized_pnl)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(day.positions_unrealized))}
                          >
                            {formatCurrency(day.positions_unrealized)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(day.holdings_unrealized))}
                          >
                            {formatCurrency(day.holdings_unrealized)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(day.total_unrealized))}
                          >
                            {formatCurrency(day.total_unrealized)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right font-bold', getPnLColor(day.total_mtm))}
                          >
                            {formatCurrency(day.total_mtm)}
                          </TableCell>
                          <TableCell className="text-right text-primary">
                            {formatCurrency(day.portfolio_value)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Calendar className="h-16 w-16 mx-auto mb-4 opacity-50" />
                  <p>No daily P&L data yet. Snapshots are captured at 23:59 IST daily.</p>
                  <p className="text-sm mt-2">Start trading to see your date-wise P&L history.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Positions Tab */}
        <TabsContent value="positions">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Position-wise P&L</CardTitle>
              {data?.positions && data.positions.length > 0 && (
                <Button variant="outline" size="sm" onClick={() => handleExport('positions')}>
                  <Download className="h-4 w-4 mr-2" />
                  Export CSV
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {data?.positions && data.positions.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Exchange</TableHead>
                        <TableHead>Product</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">Avg Price</TableHead>
                        <TableHead className="text-right">LTP</TableHead>
                        <TableHead className="text-right">Today's P&L</TableHead>
                        <TableHead className="text-right">All-Time P&L</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Last Updated</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.positions.map((pos, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-semibold">{pos.symbol}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{pos.exchange}</Badge>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                pos.product === 'MIS'
                                  ? 'secondary'
                                  : pos.product === 'CNC'
                                    ? 'default'
                                    : 'outline'
                              }
                            >
                              {pos.product}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">{pos.quantity}</TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(pos.average_price)}
                          </TableCell>
                          <TableCell className="text-right">{formatCurrency(pos.ltp)}</TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(pos.today_realized_pnl))}
                          >
                            {formatCurrency(pos.today_realized_pnl)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(pos.all_time_realized_pnl))}
                          >
                            {formatCurrency(pos.all_time_realized_pnl)}
                          </TableCell>
                          <TableCell>
                            <Badge variant={pos.status === 'Open' ? 'default' : 'secondary'}>
                              {pos.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {pos.updated_at}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Briefcase className="h-16 w-16 mx-auto mb-4 opacity-50" />
                  <p>No positions found. Start trading to see your P&L history.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Holdings Tab */}
        <TabsContent value="holdings">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Holdings P&L (T+1 Settled)</CardTitle>
              {data?.holdings && data.holdings.length > 0 && (
                <Button variant="outline" size="sm" onClick={() => handleExport('holdings')}>
                  <Download className="h-4 w-4 mr-2" />
                  Export CSV
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {data?.holdings && data.holdings.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Exchange</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">Avg Price</TableHead>
                        <TableHead className="text-right">LTP</TableHead>
                        <TableHead className="text-right">Unrealized P&L</TableHead>
                        <TableHead className="text-right">P&L %</TableHead>
                        <TableHead>Settlement Date</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.holdings.map((holding, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-semibold">{holding.symbol}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{holding.exchange}</Badge>
                          </TableCell>
                          <TableCell className="text-right">{holding.quantity}</TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(holding.average_price)}
                          </TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(holding.ltp)}
                          </TableCell>
                          <TableCell
                            className={cn('text-right', getPnLColor(holding.unrealized_pnl))}
                          >
                            {formatCurrency(holding.unrealized_pnl)}
                          </TableCell>
                          <TableCell className={cn('text-right', getPnLColor(holding.pnl_percent))}>
                            {formatCurrency(holding.pnl_percent)}%
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {holding.settlement_date}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Package className="h-16 w-16 mx-auto mb-4 opacity-50" />
                  <p>No holdings found. CNC positions settle to holdings after T+1.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Recent Trades Tab */}
        <TabsContent value="trades">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Recent Trades (Last 50)</CardTitle>
              {data?.trades && data.trades.length > 0 && (
                <Button variant="outline" size="sm" onClick={() => handleExport('trades')}>
                  <Download className="h-4 w-4 mr-2" />
                  Export All CSV
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {data?.trades && data.trades.length > 0 ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Trade ID</TableHead>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Exchange</TableHead>
                        <TableHead>Action</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">Price</TableHead>
                        <TableHead>Product</TableHead>
                        <TableHead>Timestamp</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.trades.map((trade, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-mono text-xs">
                            {trade.tradeid.slice(0, 12)}...
                          </TableCell>
                          <TableCell className="font-semibold">{trade.symbol}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{trade.exchange}</Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={trade.action === 'BUY' ? 'default' : 'destructive'}>
                              {trade.action}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">{trade.quantity}</TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(trade.price)}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                trade.product === 'MIS'
                                  ? 'secondary'
                                  : trade.product === 'CNC'
                                    ? 'default'
                                    : 'outline'
                              }
                            >
                              {trade.product}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {trade.timestamp}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Activity className="h-16 w-16 mx-auto mb-4 opacity-50" />
                  <p>No trades found. Start trading to see your trade history.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
