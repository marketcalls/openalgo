import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, PieChart as PieChartIcon, TrendingUp, AlertTriangle, Cpu } from 'lucide-react'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import { usePortfolioCVaR } from '@/hooks/useStrategyAnalysis'

const COLORS = [
  '#6366f1', '#22c55e', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16',
]

const DEFAULT_SYMBOLS = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'SBIN']

interface Props {
  exchange: string
}

function WeightPie({ weights, title }: { weights: Record<string, number>; title: string }) {
  const data = Object.entries(weights).map(([name, value]) => ({
    name,
    value: +(value * 100).toFixed(1),
  }))
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              outerRadius={70}
              dataKey="value"
              label={({ name, value }) => `${name} ${value}%`}
              labelLine={false}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => `${Number(v).toFixed(1)}%`} />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

export function PortfolioCVaRTab({ exchange }: Props) {
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS)
  const [inputVal, setInputVal] = useState(DEFAULT_SYMBOLS.join(', '))
  const [run, setRun] = useState(false)
  const { data, isLoading, refetch } = usePortfolioCVaR(symbols, exchange, run)

  const handleAnalyse = () => {
    const syms = inputVal
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    setSymbols(syms)
    setRun(true)
    setTimeout(() => refetch(), 50)
  }

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <PieChartIcon className="h-5 w-5 text-indigo-500" />
        <h3 className="font-semibold text-lg">CVaR Portfolio Optimiser</h3>
        <Badge variant="outline" className="text-xs">SciPy / GPU-optional</Badge>
        {data?.gpu_used && (
          <Badge className="text-xs bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
            <Cpu className="h-3 w-3 mr-1" /> GPU
          </Badge>
        )}
      </div>

      {/* Symbol Input */}
      <Card>
        <CardContent className="pt-4 flex gap-2 flex-wrap items-end">
          <div className="flex-1 min-w-48">
            <label className="text-xs text-muted-foreground mb-1 block">
              Symbols (comma-separated, min 2, max 20)
            </label>
            <input
              className="w-full border rounded px-3 py-2 text-sm bg-background"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder="RELIANCE, TCS, INFY, HDFCBANK"
            />
          </div>
          <Button onClick={handleAnalyse} disabled={isLoading}>
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
                Optimising…
              </>
            ) : (
              'Optimise'
            )}
          </Button>
        </CardContent>
      </Card>

      {!run && (
        <p className="text-sm text-muted-foreground text-center py-8">
          Enter symbols and click <strong>Optimise</strong> to run CVaR portfolio analysis.
        </p>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-12 gap-2 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" /> Running portfolio optimisation…
        </div>
      )}

      {data?.status === 'error' && (
        <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-700 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{data.message}</span>
        </div>
      )}

      {data?.status === 'success' && (
        <>
          {/* Risk Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              {
                label: 'CVaR 95%',
                value: `${(data.cvar_95 * 100).toFixed(2)}%`,
                note: 'Daily tail loss',
                color: 'text-red-600',
              },
              {
                label: 'CVaR 99%',
                value: `${(data.cvar_99 * 100).toFixed(2)}%`,
                note: 'Extreme tail loss',
                color: 'text-red-700',
              },
              {
                label: 'Sharpe',
                value: data.sharpe.toFixed(2),
                note: 'Max Sharpe portfolio',
                color: 'text-green-600',
              },
              {
                label: 'Ann. Return',
                value: `${(data.annual_return * 100).toFixed(1)}%`,
                note: 'Max Sharpe portfolio',
                color: 'text-blue-600',
              },
            ].map((m) => (
              <Card key={m.label}>
                <CardContent className="pt-3 pb-3">
                  <p className="text-xs text-muted-foreground">{m.label}</p>
                  <p className={`text-2xl font-bold font-mono ${m.color}`}>{m.value}</p>
                  <p className="text-xs text-muted-foreground">{m.note}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Weight Pies */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <WeightPie weights={data.min_cvar_weights} title="Min CVaR Weights" />
            <WeightPie weights={data.max_sharpe_weights} title="Max Sharpe Weights" />
          </div>

          {/* Efficient Frontier */}
          {data.efficient_frontier.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1">
                  <TrendingUp className="h-4 w-4" /> Efficient Frontier
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={220}>
                  <ScatterChart>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="volatility"
                      name="Volatility"
                      tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                      label={{ value: 'Ann. Vol', position: 'insideBottom', offset: -5 }}
                    />
                    <YAxis
                      dataKey="return"
                      name="Return"
                      tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                      label={{ value: 'Ann. Return', angle: -90, position: 'insideLeft' }}
                    />
                    <Tooltip formatter={(v) => `${(Number(v) * 100).toFixed(2)}%`} />
                    <Scatter data={data.efficient_frontier} fill="#6366f1" />
                  </ScatterChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          <p className="text-xs text-muted-foreground">
            Data: {data.n_days} trading days · {data.symbols.length} assets
            {data.gpu_used ? ' · GPU-accelerated' : ' · CPU compute'}
          </p>
        </>
      )}
    </div>
  )
}
