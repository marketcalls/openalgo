import { ArrowLeft, BarChart3 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { backtestApi } from '@/api/backtest'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { BacktestResult } from '@/types/backtest'
import { showToast } from '@/utils/toast'

const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea']

function ComparisonChart({ results }: { results: BacktestResult[] }) {
  const chartRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!chartRef.current || results.length === 0) return

    let chart: ReturnType<typeof import('lightweight-charts').createChart> | null = null

    const initChart = async () => {
      const { createChart, LineSeries } = await import('lightweight-charts')

      chart = createChart(chartRef.current!, {
        width: chartRef.current!.clientWidth,
        height: 400,
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

      results.forEach((r, i) => {
        if (!r.equity_curve?.length) return

        const series = chart!.addSeries(LineSeries, {
          color: COLORS[i % COLORS.length],
          lineWidth: 2,
          title: r.name,
        })

        // Normalize to percentage return for fair comparison
        const initial = r.equity_curve[0]?.equity || 1
        const chartData = r.equity_curve.map((d) => ({
          time: d.timestamp as import('lightweight-charts').UTCTimestamp,
          value: ((d.equity - initial) / initial) * 100,
        }))

        series.setData(chartData)
      })

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
  }, [results])

  return <div ref={chartRef} className="w-full" />
}

export default function CompareBacktests() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [results, setResults] = useState<BacktestResult[]>([])
  const [loading, setLoading] = useState(true)

  const fetchComparison = useCallback(async () => {
    const idsParam = searchParams.get('ids')
    if (!idsParam) {
      showToast.error('No backtest IDs provided')
      navigate('/backtest')
      return
    }

    const ids = idsParam.split(',').filter(Boolean)
    if (ids.length < 2) {
      showToast.error('Need at least 2 backtests to compare')
      navigate('/backtest')
      return
    }

    try {
      setLoading(true)
      const data = await backtestApi.compare(ids)
      setResults(data)
    } catch {
      showToast.error('Failed to load comparison data')
    } finally {
      setLoading(false)
    }
  }, [searchParams, navigate])

  useEffect(() => {
    fetchComparison()
  }, [fetchComparison])

  if (loading) {
    return (
      <div className="container mx-auto p-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (results.length < 2) {
    return (
      <div className="container mx-auto p-6">
        <p className="text-muted-foreground">Not enough completed backtests to compare.</p>
        <Button className="mt-4" onClick={() => navigate('/backtest')}>
          Back to Backtests
        </Button>
      </div>
    )
  }

  const metrics = [
    { key: 'total_return_pct', label: 'Total Return %', suffix: '%', better: 'higher' as const },
    { key: 'cagr', label: 'CAGR %', suffix: '%', better: 'higher' as const },
    { key: 'sharpe_ratio', label: 'Sharpe Ratio', better: 'higher' as const },
    { key: 'sortino_ratio', label: 'Sortino Ratio', better: 'higher' as const },
    { key: 'max_drawdown_pct', label: 'Max Drawdown %', suffix: '%', better: 'lower' as const },
    { key: 'calmar_ratio', label: 'Calmar Ratio', better: 'higher' as const },
    { key: 'win_rate', label: 'Win Rate %', suffix: '%', better: 'higher' as const },
    { key: 'profit_factor', label: 'Profit Factor', better: 'higher' as const },
    { key: 'total_trades', label: 'Total Trades' },
    { key: 'expectancy', label: 'Expectancy', better: 'higher' as const },
    { key: 'total_commission', label: 'Total Commission', better: 'lower' as const },
    { key: 'total_slippage', label: 'Total Slippage', better: 'lower' as const },
  ]

  // Find the best value for each metric
  const bestValues: Record<string, number> = {}
  for (const metric of metrics) {
    if (!metric.better) continue
    const values = results.map((r) => (r.metrics as unknown as Record<string, number>)[metric.key])
    bestValues[metric.key] = metric.better === 'higher' ? Math.max(...values) : Math.min(...values)
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate('/backtest')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            Compare Backtests
          </h1>
          <p className="text-muted-foreground text-sm">
            Comparing {results.length} backtests
          </p>
        </div>
      </div>

      {/* Equity Curve Comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Equity Curves (% Return)</CardTitle>
          <CardDescription>
            Normalized to percentage return for fair comparison
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 mb-4">
            {results.map((r, i) => (
              <div key={r.backtest_id} className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: COLORS[i % COLORS.length] }}
                />
                <span className="text-sm">{r.name}</span>
              </div>
            ))}
          </div>
          <ComparisonChart results={results} />
        </CardContent>
      </Card>

      {/* Metrics Comparison Table */}
      <Card>
        <CardHeader>
          <CardTitle>Metrics Comparison</CardTitle>
          <CardDescription>
            Bold values indicate the best performer for each metric
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                {results.map((r, i) => (
                  <TableHead key={r.backtest_id} className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: COLORS[i % COLORS.length] }}
                      />
                      {r.name}
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {/* Config row */}
              <TableRow>
                <TableCell className="font-medium text-muted-foreground">Symbols</TableCell>
                {results.map((r) => (
                  <TableCell key={r.backtest_id} className="text-right text-xs">
                    {r.config.symbols.join(', ')}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="font-medium text-muted-foreground">Period</TableCell>
                {results.map((r) => (
                  <TableCell key={r.backtest_id} className="text-right text-xs">
                    {r.config.start_date} to {r.config.end_date}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="font-medium text-muted-foreground">Capital</TableCell>
                {results.map((r) => (
                  <TableCell key={r.backtest_id} className="text-right font-mono">
                    {r.config.initial_capital.toLocaleString()}
                  </TableCell>
                ))}
              </TableRow>

              {/* Metric rows */}
              {metrics.map((metric) => (
                <TableRow key={metric.key}>
                  <TableCell className="font-medium">{metric.label}</TableCell>
                  {results.map((r) => {
                    const val = (r.metrics as unknown as Record<string, number>)[metric.key]
                    const isBest = metric.better && val === bestValues[metric.key]
                    return (
                      <TableCell
                        key={r.backtest_id}
                        className={`text-right font-mono ${isBest ? 'font-bold text-blue-600 dark:text-blue-400' : ''}`}
                      >
                        {typeof val === 'number' ? val.toFixed(2) : val}
                        {metric.suffix || ''}
                      </TableCell>
                    )
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
