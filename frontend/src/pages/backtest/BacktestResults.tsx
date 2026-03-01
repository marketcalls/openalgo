import {
  ArrowLeft,
  BarChart3,
  Clock,
  Download,
  Loader2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { backtestApi } from '@/api/backtest'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { BacktestProgress, BacktestResult } from '@/types/backtest'

// Equity chart component using lightweight-charts
function EquityChart({ data }: { data: { timestamp: number; equity: number }[] }) {
  const chartRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chartRef.current || !data.length) return

    let chart: ReturnType<typeof import('lightweight-charts').createChart> | null = null

    const initChart = async () => {
      const { createChart, LineSeries } = await import('lightweight-charts')

      chart = createChart(chartRef.current!, {
        width: chartRef.current!.clientWidth,
        height: 350,
        layout: {
          background: { color: 'transparent' },
          textColor: '#888',
        },
        grid: {
          vertLines: { color: 'rgba(128,128,128,0.1)' },
          horzLines: { color: 'rgba(128,128,128,0.1)' },
        },
        rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
        timeScale: {
          borderColor: 'rgba(128,128,128,0.2)',
          timeVisible: true,
        },
      })

      const series = chart.addSeries(LineSeries, {
        color: '#2563eb',
        lineWidth: 2,
      })

      const chartData = data.map((d) => ({
        time: d.timestamp as import('lightweight-charts').UTCTimestamp,
        value: d.equity,
      }))

      series.setData(chartData)
      chart.timeScale().fitContent()

      // Handle resize
      const observer = new ResizeObserver(() => {
        if (chartRef.current && chart) {
          chart.applyOptions({ width: chartRef.current.clientWidth })
        }
      })
      if (chartRef.current) observer.observe(chartRef.current)
    }

    initChart()

    return () => {
      if (chart) chart.remove()
    }
  }, [data])

  return <div ref={chartRef} className="w-full" />
}

// Drawdown chart
function DrawdownChart({ data }: { data: { timestamp: number; drawdown: number }[] }) {
  const chartRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chartRef.current || !data.length) return

    let chart: ReturnType<typeof import('lightweight-charts').createChart> | null = null

    const initChart = async () => {
      const { createChart, AreaSeries } = await import('lightweight-charts')

      chart = createChart(chartRef.current!, {
        width: chartRef.current!.clientWidth,
        height: 200,
        layout: {
          background: { color: 'transparent' },
          textColor: '#888',
        },
        grid: {
          vertLines: { color: 'rgba(128,128,128,0.1)' },
          horzLines: { color: 'rgba(128,128,128,0.1)' },
        },
        rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
        timeScale: {
          borderColor: 'rgba(128,128,128,0.2)',
          timeVisible: true,
        },
      })

      const series = chart.addSeries(AreaSeries, {
        topColor: 'rgba(239, 68, 68, 0.3)',
        bottomColor: 'rgba(239, 68, 68, 0.05)',
        lineColor: '#ef4444',
        lineWidth: 1,
      })

      const chartData = data.map((d) => ({
        time: d.timestamp as import('lightweight-charts').UTCTimestamp,
        value: -(d.drawdown * 100),
      }))

      series.setData(chartData)
      chart.timeScale().fitContent()

      const observer = new ResizeObserver(() => {
        if (chartRef.current && chart) {
          chart.applyOptions({ width: chartRef.current.clientWidth })
        }
      })
      if (chartRef.current) observer.observe(chartRef.current)
    }

    initChart()

    return () => {
      if (chart) chart.remove()
    }
  }, [data])

  return <div ref={chartRef} className="w-full" />
}

function MetricCard({
  label,
  value,
  suffix,
  isPositive,
}: {
  label: string
  value: string | number
  suffix?: string
  isPositive?: boolean | null
}) {
  let colorClass = ''
  if (isPositive === true) colorClass = 'text-green-600 dark:text-green-400'
  else if (isPositive === false) colorClass = 'text-red-600 dark:text-red-400'

  return (
    <div className="text-center p-3 rounded-lg bg-muted/50">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-lg font-bold mt-1 ${colorClass}`}>
        {value}
        {suffix && <span className="text-sm font-normal">{suffix}</span>}
      </p>
    </div>
  )
}

export default function BacktestResults() {
  const { backtestId } = useParams<{ backtestId: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // For running backtests — show progress
  const [isRunning, setIsRunning] = useState(false)
  const [progress, setProgress] = useState<BacktestProgress | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const fetchResults = useCallback(async () => {
    if (!backtestId) return

    try {
      setLoading(true)

      // First check status
      const status = await backtestApi.getStatus(backtestId)

      if (status?.status === 'running' || status?.status === 'pending') {
        // Connect to SSE
        setIsRunning(true)
        setLoading(false)

        const es = backtestApi.createProgressStream(backtestId)
        eventSourceRef.current = es

        es.onmessage = (event) => {
          try {
            const data: BacktestProgress = JSON.parse(event.data)
            if (data.heartbeat) return
            setProgress(data)

            if (data.status === 'completed') {
              es.close()
              setIsRunning(false)
              // Fetch results
              backtestApi.getResults(backtestId).then((r) => {
                setResult(r)
              })
            } else if (data.status === 'failed' || data.status === 'cancelled') {
              es.close()
              setIsRunning(false)
              setError(data.message || `Backtest ${data.status}`)
            }
          } catch {
            // Ignore parse errors
          }
        }

        es.onerror = () => {
          es.close()
          setIsRunning(false)
          setError('Lost connection to backtest')
        }

        return
      }

      if (status?.status === 'completed') {
        const data = await backtestApi.getResults(backtestId)
        setResult(data)
      } else if (status?.status === 'failed') {
        setError(status.error_message || 'Backtest failed')
      } else if (status?.status === 'cancelled') {
        setError('Backtest was cancelled')
      } else {
        setError('Backtest not found')
      }
    } catch {
      setError('Failed to load backtest results')
    } finally {
      setLoading(false)
    }
  }, [backtestId])

  useEffect(() => {
    fetchResults()
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close()
    }
  }, [fetchResults])

  if (loading) {
    return (
      <div className="container mx-auto p-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  // Running state
  if (isRunning) {
    return (
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/backtest')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-2xl font-bold">Backtest Running...</h1>
        </div>
        <Card>
          <CardContent className="py-8">
            <div className="flex flex-col items-center space-y-4">
              <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
              <p className="text-lg">{progress?.message || 'Starting...'}</p>
              <div className="w-full max-w-md">
                <Progress value={progress?.progress || 0} className="h-3" />
              </div>
              <p className="text-sm text-muted-foreground font-mono">
                {progress?.progress || 0}%
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/backtest')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-2xl font-bold">Backtest Error</h1>
        </div>
        <Card>
          <CardContent className="py-8 text-center">
            <TrendingDown className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-lg text-red-600 dark:text-red-400">{error}</p>
            <Button className="mt-4" onClick={() => navigate('/backtest')}>
              Back to Backtests
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!result) return null

  const m = result.metrics

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/backtest')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold">{result.name}</h1>
            <p className="text-muted-foreground text-sm">
              {result.config.symbols.join(', ')} | {result.config.interval} |{' '}
              {result.config.start_date} to {result.config.end_date}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <a href={backtestApi.getExportUrl(result.backtest_id)}>
            <Button variant="outline">
              <Download className="h-4 w-4 mr-2" />
              Export CSV
            </Button>
          </a>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
        <MetricCard
          label="Total Return"
          value={`${m.total_return_pct >= 0 ? '+' : ''}${m.total_return_pct.toFixed(2)}`}
          suffix="%"
          isPositive={m.total_return_pct >= 0}
        />
        <MetricCard
          label="Final Capital"
          value={m.final_capital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          suffix=""
        />
        <MetricCard
          label="CAGR"
          value={m.cagr.toFixed(2)}
          suffix="%"
          isPositive={m.cagr >= 0}
        />
        <MetricCard
          label="Sharpe Ratio"
          value={m.sharpe_ratio.toFixed(2)}
          isPositive={m.sharpe_ratio > 0 ? true : m.sharpe_ratio < 0 ? false : null}
        />
        <MetricCard
          label="Sortino Ratio"
          value={m.sortino_ratio.toFixed(2)}
          isPositive={m.sortino_ratio > 0 ? true : m.sortino_ratio < 0 ? false : null}
        />
        <MetricCard
          label="Max Drawdown"
          value={`-${m.max_drawdown_pct.toFixed(2)}`}
          suffix="%"
          isPositive={false}
        />
        <MetricCard
          label="Calmar Ratio"
          value={m.calmar_ratio.toFixed(2)}
        />
        <MetricCard
          label="Win Rate"
          value={m.win_rate.toFixed(1)}
          suffix="%"
          isPositive={m.win_rate >= 50}
        />
        <MetricCard
          label="Profit Factor"
          value={m.profit_factor.toFixed(2)}
          isPositive={m.profit_factor > 1}
        />
        <MetricCard
          label="Expectancy"
          value={m.expectancy.toFixed(2)}
          isPositive={m.expectancy > 0}
        />
      </div>

      {/* Trade Summary Row */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <MetricCard label="Total Trades" value={m.total_trades} />
        <MetricCard label="Winners" value={m.winning_trades} isPositive={true} />
        <MetricCard label="Losers" value={m.losing_trades} isPositive={false} />
        <MetricCard label="Avg Win" value={m.avg_win.toFixed(2)} isPositive={true} />
        <MetricCard label="Avg Loss" value={m.avg_loss.toFixed(2)} isPositive={false} />
        <MetricCard label="Avg Bars Held" value={m.avg_holding_bars} />
      </div>

      {/* Charts & Trades Tabs */}
      <Tabs defaultValue="charts" className="w-full">
        <TabsList>
          <TabsTrigger value="charts">
            <BarChart3 className="h-4 w-4 mr-2" />
            Charts
          </TabsTrigger>
          <TabsTrigger value="trades">
            <TrendingUp className="h-4 w-4 mr-2" />
            Trades ({m.total_trades})
          </TabsTrigger>
          <TabsTrigger value="monthly">
            <Clock className="h-4 w-4 mr-2" />
            Monthly Returns
          </TabsTrigger>
        </TabsList>

        <TabsContent value="charts" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Equity Curve</CardTitle>
            </CardHeader>
            <CardContent>
              <EquityChart data={result.equity_curve} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Drawdown</CardTitle>
            </CardHeader>
            <CardContent>
              <DrawdownChart data={result.equity_curve} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trades">
          <Card>
            <CardHeader>
              <CardTitle>Trade Log</CardTitle>
              <CardDescription>
                {m.total_trades} trades | Max Win: {m.max_win.toFixed(2)} | Max Loss: {m.max_loss.toFixed(2)}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="max-h-[500px] overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>#</TableHead>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Direction</TableHead>
                      <TableHead>Qty</TableHead>
                      <TableHead className="text-right">Entry</TableHead>
                      <TableHead className="text-right">Exit</TableHead>
                      <TableHead className="text-right">P&L</TableHead>
                      <TableHead className="text-right">P&L%</TableHead>
                      <TableHead className="text-right">Net P&L</TableHead>
                      <TableHead className="text-right">Bars</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.trades.map((t) => (
                      <TableRow key={t.trade_num}>
                        <TableCell className="font-mono text-xs">{t.trade_num}</TableCell>
                        <TableCell>{t.symbol}</TableCell>
                        <TableCell>
                          <Badge
                            variant="secondary"
                            className={
                              t.action === 'LONG'
                                ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                                : 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                            }
                          >
                            {t.action}
                          </Badge>
                        </TableCell>
                        <TableCell>{t.quantity}</TableCell>
                        <TableCell className="text-right font-mono">{t.entry_price.toFixed(2)}</TableCell>
                        <TableCell className="text-right font-mono">{t.exit_price.toFixed(2)}</TableCell>
                        <TableCell
                          className={`text-right font-mono ${
                            t.pnl >= 0
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}
                        >
                          {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono ${
                            t.pnl_pct >= 0
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}
                        >
                          {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                        </TableCell>
                        <TableCell
                          className={`text-right font-mono font-bold ${
                            t.net_pnl >= 0
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}
                        >
                          {t.net_pnl >= 0 ? '+' : ''}{t.net_pnl.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right">{t.bars_held}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="monthly">
          <Card>
            <CardHeader>
              <CardTitle>Monthly Returns</CardTitle>
              <CardDescription>Monthly performance breakdown</CardDescription>
            </CardHeader>
            <CardContent>
              {Object.keys(result.monthly_returns).length === 0 ? (
                <p className="text-muted-foreground text-center py-8">
                  Not enough data for monthly returns
                </p>
              ) : (
                <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
                  {Object.entries(result.monthly_returns)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([date, ret]) => (
                      <div
                        key={date}
                        className={`p-3 rounded-lg text-center text-sm ${
                          ret >= 0
                            ? 'bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300'
                            : 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300'
                        }`}
                      >
                        <p className="text-xs text-muted-foreground">{date}</p>
                        <p className="font-bold mt-1">
                          {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                        </p>
                      </div>
                    ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Costs Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Cost Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard
              label="Total Commission"
              value={m.total_commission.toFixed(2)}
              isPositive={false}
            />
            <MetricCard
              label="Total Slippage"
              value={m.total_slippage.toFixed(2)}
              isPositive={false}
            />
            <MetricCard
              label="Max Win"
              value={m.max_win.toFixed(2)}
              isPositive={true}
            />
            <MetricCard
              label="Max Loss"
              value={m.max_loss.toFixed(2)}
              isPositive={false}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
