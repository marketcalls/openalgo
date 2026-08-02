/**
 * SIP Backtester — set up a systematic investment plan and see what it would
 * actually have returned.
 *
 * The whole result comes from one response, as with the portfolio backtester:
 * every tab is a view of the same simulation, so fetching per tab would risk
 * two tabs disagreeing about the same SIP.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { listBenchmarks } from '@/api/portfolio'
import { type PriceSource, runSipBacktest, type SipFrequency } from '@/api/sip'
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
import { type ChargeState, DEFAULT_CHARGES } from '@/lib/portfolioRequest'
import { useAuthStore } from '@/stores/authStore'
import { useSipBacktestStore } from '@/stores/sipBacktestStore'

const FREQUENCIES: { value: SipFrequency; label: string; note: string }[] = [
  { value: 'weekly', label: 'Weekly', note: '52x per year' },
  { value: 'fortnightly', label: 'Fortnightly', note: '26x per year' },
  { value: 'monthly', label: 'Monthly', note: '12x per year' },
  { value: 'quarterly', label: 'Quarterly', note: '4x per year' },
]

function todayISO(offsetYears = 0): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - offsetYears)
  return d.toISOString().slice(0, 10)
}

const inr = (n: number) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n)

export default function SipBacktester() {
  const navigate = useNavigate()
  const { apiKey } = useAuthStore()
  const setResult = useSipBacktestStore((s) => s.setResult)

  const [symbol, setSymbol] = useState('ICICIBANK')
  const [exchange, setExchange] = useState<'NSE' | 'BSE'>('NSE')
  const [amount, setAmount] = useState(10000)
  const [frequency, setFrequency] = useState<SipFrequency>('monthly')
  const [dayOfMonth, setDayOfMonth] = useState(1)
  const [stepUp, setStepUp] = useState(0)
  const [benchmark, setBenchmark] = useState('NIFTY')
  const [source, setSource] = useState<PriceSource>('api')
  const [startDate, setStartDate] = useState(todayISO(5))
  const [endDate, setEndDate] = useState(todayISO(0))
  const [charges, setCharges] = useState<ChargeState>(DEFAULT_CHARGES)
  const [costExchange, setCostExchange] = useState<'NSE' | 'BSE'>('NSE')

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // From the instrument master rather than hardcoded: which indices exist
  // depends on which broker's master contract was downloaded.
  const { data: benchmarks = [] } = useQuery({
    queryKey: ['portfolio', 'benchmarks'],
    queryFn: () => listBenchmarks(apiKey ?? ''),
    enabled: !!apiKey,
    staleTime: 5 * 60_000,
  })

  // Only monthly and quarterly SIPs have a meaningful day of month; a weekly
  // SIP is defined by its interval, not a calendar date.
  const usesDayOfMonth = frequency === 'monthly' || frequency === 'quarterly'

  const perYear = { weekly: 52, fortnightly: 26, monthly: 12, quarterly: 4 }[frequency]
  const yearlyOutlay = amount * perYear

  const run = async () => {
    if (!apiKey) {
      setError('No API key found. Generate one on the API Key page.')
      return
    }
    if (!symbol.trim()) {
      setError('Pick a symbol to invest in.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const req = {
        apikey: apiKey,
        symbol: symbol.trim().toUpperCase(),
        exchange,
        start_date: startDate,
        end_date: endDate,
        amount: Number(amount),
        frequency,
        day_of_month: usesDayOfMonth ? Number(dayOfMonth) : 1,
        step_up_percent: Number(stepUp),
        // The full statutory schedule, identical to the portfolio
        // backtester's mapping so the same trade costs the same in both.
        cost_model: 'indian_equity' as const,
        cost_exchange: costExchange,
        charges: {
          brokerage:
            charges.brokerageMode === 'flat'
              ? { flat: charges.brokerageFlat, rate: 0 }
              : {
                  flat: 0,
                  rate: charges.brokeragePct / 100,
                  cap: charges.brokerageCap,
                },
          stt: { rate: charges.stt / 100 },
          exchange_txn: { rate: charges.exchangeTxn / 100 },
          stamp_duty: { rate: charges.stampDuty / 100 },
          sebi: { rate: charges.sebiPerCrore / 1_00_00_000 },
        },
        gst_rate: charges.gst / 100,
        slippage: charges.slippage / 100,
        benchmark: benchmark === 'none' ? null : benchmark,
        benchmark_exchange: 'NSE_INDEX',
        source,
        include_grids: true,
      }
      const res = await runSipBacktest(req)
      if (res.status !== 'success') throw new Error('backtest failed')
      setResult(res, req)
      navigate('/sip-backtester/results')
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
        <h1 className="text-2xl font-bold tracking-tight">SIP Backtester</h1>
        <p className="text-sm text-muted-foreground">
          What a systematic investment plan would actually have returned. Measured with XIRR,
          because money paid in month 60 has not compounded for five years — a single CAGR would
          overstate it.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {/* ── What to invest in ─────────────────────────────────────── */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Invest in</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <SymbolSearchInput
              value={symbol}
              exchange={exchange}
              onSelect={(next: string) => setSymbol(next)}
            />
            <Select value={exchange} onValueChange={(v) => setExchange(v as 'NSE' | 'BSE')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NSE">NSE</SelectItem>
                <SelectItem value="BSE">BSE</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Cash equity and ETFs. A SIP into a derivative is not a thing.
            </p>
          </CardContent>
        </Card>

        {/* ── How much, how often ───────────────────────────────────── */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Installment</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="space-y-1">
              <Label className="text-xs">Amount per installment</Label>
              <Input
                type="number"
                min={1}
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
              />
            </div>
            <Select value={frequency} onValueChange={(v) => setFrequency(v as SipFrequency)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FREQUENCIES.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label} <span className="text-muted-foreground">{f.note}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              About <span className="font-medium">₹{inr(yearlyOutlay)}</span> a year.
            </p>
          </CardContent>
        </Card>

        {/* ── Benchmark ─────────────────────────────────────────────── */}
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
              The same schedule is run into the index, so the comparison is SIP against SIP — not
              SIP against an index CAGR.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── Period and options ──────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Period and options</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
          <div className="space-y-1">
            <Label className="text-xs">SIP start date</Label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">End date</Label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">SIP date</Label>
            <Input
              type="number"
              min={1}
              max={28}
              disabled={!usesDayOfMonth}
              value={dayOfMonth}
              onChange={(e) => setDayOfMonth(Number(e.target.value))}
            />
            <p className="text-[11px] text-muted-foreground">
              {usesDayOfMonth ? '1–28' : 'n/a for this frequency'}
            </p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Annual step-up %</Label>
            <Input
              type="number"
              min={0}
              max={100}
              value={stepUp}
              onChange={(e) => setStepUp(Number(e.target.value))}
            />
            <p className="text-[11px] text-muted-foreground">Raises on each anniversary</p>
          </div>
        </CardContent>
      </Card>

      {/* ── Charges ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Brokerage and charges</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <ChargeControls
            value={charges}
            onChange={setCharges}
            exchange={costExchange}
            onExchange={setCostExchange}
          />
          <p className="text-xs text-muted-foreground">
            Levied on <span className="font-medium">every installment</span>, not once for the SIP.
            Over 60 monthly buys that difference is not small, and it shows up as fewer units rather
            than a separate line.
          </p>
        </CardContent>
      </Card>

      {/* ── Data source ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Price data</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Select value={source} onValueChange={(v) => setSource(v as PriceSource)}>
            <SelectTrigger className="md:w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="api">Broker API</SelectItem>
              <SelectItem value="db">Historify (DB)</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {source === 'api'
              ? 'Fetched live from your broker and adjusted for corporate actions. Needs an active broker session.'
              : 'Read from your local Historify store. Works without a broker login, so backtesting at the weekend is fine.'}
          </p>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex justify-end">
        <Button onClick={run} disabled={busy} size="lg">
          {busy ? 'Running…' : 'Run SIP Backtest'}
        </Button>
      </div>
    </div>
  )
}
