/**
 * Portfolio Backtester — build a weighted portfolio, backtest it, read the result.
 *
 * Every tab renders from one response: they are all views of a single
 * simulation, so re-fetching per tab would risk two tabs disagreeing about
 * the same portfolio.
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import {
  type PortfolioHolding,
  type PriceSource,
  type RebalanceRule,
  downloadTearsheet,
  listBenchmarks,
  runPortfolioBacktest,
} from '@/api/portfolio'
import { ChargeControls } from '@/components/portfolio/ChargeControls'
import { SymbolSearchInput } from '@/components/portfolio/SymbolSearchInput'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuthStore } from '@/stores/authStore'
import { usePortfolioBacktestStore } from '@/stores/portfolioBacktestStore'
import { cn } from '@/lib/utils'
import { DEFAULT_CHARGES, buildPortfolioRequest, type ChargeState } from '@/lib/portfolioRequest'

const REBALANCE: { value: RebalanceRule; label: string; note: string }[] = [
  { value: 'never', label: 'Never', note: 'Buy & Hold' },
  { value: 'monthly', label: 'Monthly', note: '12x per year' },
  { value: 'quarterly', label: 'Quarterly', note: '4x per year' },
  { value: 'yearly', label: 'Yearly', note: '1x per year' },
]

function todayISO(offsetYears = 0): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - offsetYears)
  return d.toISOString().slice(0, 10)
}

export default function PortfolioBacktester() {
  const navigate = useNavigate()
  const { apiKey } = useAuthStore()
  const setBacktestResult = usePortfolioBacktestStore((s) => s.setResult)

  const [holdings, setHoldings] = useState<PortfolioHolding[]>([
    { symbol: 'NIFTYBEES', exchange: 'NSE', weight: 60 },
    { symbol: 'GOLDBEES', exchange: 'NSE', weight: 40 },
  ])
  const [benchmark, setBenchmark] = useState('NIFTY')
  const [rebalance, setRebalance] = useState<RebalanceRule>('never')
  const [source, setSource] = useState<PriceSource>('api')
  const [startDate, setStartDate] = useState(todayISO(5))
  const [endDate, setEndDate] = useState(todayISO(0))
  const [charges, setCharges] = useState<ChargeState>(DEFAULT_CHARGES)
  const [costExchange, setCostExchange] = useState<'NSE' | 'BSE'>('NSE')
  const [riskFree, setRiskFree] = useState(0)

  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Read from the instrument master rather than hardcoded: which indices
  // exist depends on which broker's master contract was downloaded.
  const { data: benchmarks = [] } = useQuery({
    queryKey: ['portfolio', 'benchmarks'],
    queryFn: () => listBenchmarks(apiKey ?? ''),
    enabled: !!apiKey,
    staleTime: 5 * 60_000,
  })

  const totalWeight = useMemo(
    () => holdings.reduce((s, h) => s + (Number(h.weight) || 0), 0),
    [holdings]
  )

  const setHolding = (i: number, patch: Partial<PortfolioHolding>) =>
    setHoldings((prev) => prev.map((h, n) => (n === i ? { ...h, ...patch } : h)))

  // Editing one weight by hand rescales every other row proportionally, so
  // the total stays at 100 instead of drifting past it one field at a time.
  const setWeight = (i: number, raw: number) =>
    setHoldings((prev) => {
      const newWeight = Math.max(0, Math.min(100, Number.isFinite(raw) ? raw : 0))
      const remaining = 100 - newWeight
      const othersSum = prev.reduce(
        (s, h, n) => (n === i ? s : s + (Number(h.weight) || 0)),
        0
      )
      const otherCount = prev.length - 1
      return prev.map((h, n) => {
        if (n === i) return { ...h, weight: newWeight }
        const w = Number(h.weight) || 0
        const scaled =
          othersSum > 0
            ? (w * remaining) / othersSum
            : otherCount > 0
              ? remaining / otherCount
              : 0
        return { ...h, weight: Number(scaled.toFixed(2)) }
      })
    })

  // New stock takes an equal share; the existing holdings shrink
  // proportionally to make room, so the total stays at 100 instead of
  // just growing by whatever the new row is given.
  const addHolding = () =>
    setHoldings((prev) => {
      const newWeight = Number((100 / (prev.length + 1)).toFixed(2))
      const remaining = 100 - newWeight
      const existingSum = prev.reduce((s, h) => s + (Number(h.weight) || 0), 0)
      const scaled = prev.map((h) => ({
        ...h,
        weight:
          existingSum > 0
            ? Number(((Number(h.weight) || 0) * (remaining / existingSum)).toFixed(2))
            : Number((remaining / prev.length).toFixed(2)),
      }))
      return [...scaled, { symbol: '', exchange: 'NSE', weight: newWeight }]
    })

  const distributeEqually = () =>
    setHoldings((prev) =>
      prev.map((h) => ({ ...h, weight: Number((100 / prev.length).toFixed(2)) }))
    )

  const buildRequest = () =>
    buildPortfolioRequest({
      apiKey: apiKey ?? '',
      holdings,
      startDate,
      endDate,
      benchmark: benchmark === 'none' ? null : benchmark,
      benchmarkExchange:
        benchmarks.find((item) => item.symbol === benchmark)?.exchange ?? 'NSE_INDEX',
      rebalance,
      source,
      charges,
      costExchange,
      riskFree,
    })

  const exportTearsheet = async () => {
    if (!apiKey) {
      setError('No API key found. Generate one on the API Key page.')
      return
    }
    setExporting(true)
    setError(null)
    try {
      await downloadTearsheet(buildRequest())
    } catch (err: unknown) {
      const e = err as { message?: string }
      setError(e.message ?? 'tearsheet export failed')
    } finally {
      setExporting(false)
    }
  }

  const analyse = async () => {
    if (!apiKey) {
      setError('No API key found. Generate one on the API Key page.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const req = buildRequest()
      const res = await runPortfolioBacktest(req)
      if (res.status !== 'success') throw new Error(res.message || 'backtest failed')
      setBacktestResult(res, req)
      navigate('/portfolio-backtester/results')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: unknown } }; message?: string }
      const msg = e.response?.data?.message ?? e.message ?? 'backtest failed'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Portfolio Backtester</h1>
        <p className="text-sm text-muted-foreground">
          Build a portfolio, set weights, pick a benchmark, and see how it would have
          performed. Costs and rebalancing are modelled, not assumed away.
        </p>
      </div>

      {/* ── Builder ─────────────────────────────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Benchmark</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select value={benchmark} onValueChange={setBenchmark}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {benchmarks.map((b) => (
                  <SelectItem key={`${b.exchange}-${b.symbol}`} value={b.symbol}>
                    {b.symbol}{' '}
                    <span className="text-muted-foreground">
                      {b.exchange.replace('_INDEX', '')}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Indices only, from your broker's instrument master -- alpha and
              beta against a single stock would not mean anything.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Rebalancing</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select
              value={rebalance}
              onValueChange={(v) => setRebalance(v as RebalanceRule)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REBALANCE.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label} <span className="text-muted-foreground">{r.note}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              More often is not better, it costs turnover.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Analysis Period</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Start</Label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <Label className="text-xs">End</Label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        {/* Left: holdings and run controls */}
        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <div>
              <CardTitle className="text-base">Portfolio Holdings</CardTitle>
              <p className="text-sm text-muted-foreground">
                NSE and BSE cash equity and ETFs.
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={addHolding}>
                Add Stock
              </Button>
              <Button variant="outline" size="sm" onClick={distributeEqually}>
                Distribute Equally
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {holdings.map((h, i) => (
              <div key={`row-${i}-${h.symbol}`} className="flex items-center gap-2">
                <SymbolSearchInput
                  className="w-56"
                  value={h.symbol}
                  exchange={h.exchange as 'NSE' | 'BSE'}
                  onSelect={(sym) => setHolding(i, { symbol: sym })}
                />
                <Select
                  value={h.exchange}
                  onValueChange={(v) => setHolding(i, { exchange: v })}
                >
                  <SelectTrigger className="w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="NSE">NSE</SelectItem>
                    <SelectItem value="BSE">BSE</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  className="w-20"
                  type="number"
                  value={h.weight}
                  onChange={(e) => setWeight(i, Number(e.target.value))}
                />
                <span className="text-xs text-muted-foreground">%</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={holdings.length <= 1}
                  onClick={() => setHoldings((p) => p.filter((_, n) => n !== i))}
                >
                  Remove
                </Button>
              </div>
            ))}

            <div className="flex flex-wrap items-end gap-4 border-t pt-3">
              <div>
                <Label className="text-xs">Data source</Label>
                <Select value={source} onValueChange={(v) => setSource(v as PriceSource)}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="db">Historify (local)</SelectItem>
                    <SelectItem value="api">Broker API</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs">Risk-free rate (%)</Label>
                <Input
                  className="w-28"
                  type="number"
                  step="0.1"
                  value={riskFree}
                  onChange={(e) => setRiskFree(Number(e.target.value))}
                />
              </div>
              <div className="ml-auto flex items-center gap-3">
                <span
                  className={cn(
                    'text-sm tabular-nums',
                    Math.abs(totalWeight - 100) < 0.01
                      ? 'text-emerald-500'
                      : 'text-muted-foreground'
                  )}
                >
                  Total {totalWeight.toFixed(1)}%
                </span>
                <Button
                  variant="outline"
                  onClick={exportTearsheet}
                  disabled={exporting || busy}
                  title="Full openstatz tearsheet as a self-contained HTML file"
                >
                  {exporting ? 'Building…' : 'Tearsheet'}
                </Button>
                <Button onClick={analyse} disabled={busy}>
                  {busy ? 'Analysing…' : 'Analyze Portfolio'}
                </Button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Weights are normalised, so they need not total 100.
            </p>
          </CardContent>
        </Card>

        {/* Right: every charge, editable */}
        <ChargeControls
          value={charges}
          onChange={setCharges}
          exchange={costExchange}
          onExchange={setCostExchange}
        />
      </div>

      {error && (
        <Card className="border-rose-500/40">
          <CardContent className="p-4 text-sm text-rose-500">{error}</CardContent>
        </Card>
      )}
    </div>
  )
}
