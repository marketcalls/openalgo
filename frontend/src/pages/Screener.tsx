/**
 * The indicator screener.
 *
 * Pick a set of symbols, pick one chart indicator, filter on what it outputs,
 * scan. It is the same shape as TradingView's Pine Screener, with one
 * substitution: the scanning language is an `openalgo-charts` indicator
 * descriptor rather than a Pine script. Plots take the place of Pine's `plot()`
 * as filter operands and table columns, and a descriptor's declared alerts take
 * the place of `alertcondition()`.
 *
 * That substitution is the whole point. A descriptor's `calc` is a pure
 * function of `(bars, settings)`, so the study drawn on `/trading` -- built-in
 * or one of the user's own files in `strategies/indicators/` -- runs here
 * unchanged. A number in this table is the number on the chart because it came
 * out of the same function, not because two implementations were kept in step.
 *
 * Everything expensive happens in a worker (`lib/screener/scanWorker.ts`),
 * including fetching, so the page stays responsive and progress is real rather
 * than animated.
 */
import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { fetchCSRFToken } from '@/api/client'
import { type MarketPulseData, tradefinderApi } from '@/api/tradefinder'
import { watchlistApi } from '@/api/watchlist'
import { FilterBuilder, type FilterColumn } from '@/components/screener/FilterBuilder'
import {
  type CatalogEntry,
  IndicatorPickerDialog,
  noteRecentIndicator,
} from '@/components/trading/IndicatorPickerDialog'
import { SettingsField } from '@/components/trading/IndicatorSettingsDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Filter, ScanEvent, ScanRow, ScanSymbol } from '@/lib/screener/model'
import type { IndicatorField } from '@/lib/trading/terminal'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

const INTERVALS = ['1m', '5m', '15m', '30m', '1h', 'D'] as const
const BAR_CHOICES = [200, 300, 500] as const
const MAX_SYMBOLS = 500

/** TradeFinder is an NSE cash product; its list items carry no exchange. */
const TF_EXCHANGE = 'NSE'
const TF_LISTS = [
  { key: 'intraday_boost', label: 'TradeFinder: Intraday Boost' },
  { key: 'breakout_beacon', label: 'TradeFinder: Breakout Beacon' },
  { key: 'high_powered_stocks', label: 'TradeFinder: High Powered' },
] as const

interface Descriptor {
  id: string
  name: string
  inputs?: IndicatorField[]
  plots?: { key: string; title?: string }[]
  alerts?: { id: string; title?: string }[]
  attach?: unknown
}

type SortState = { key: string; dir: 'asc' | 'desc' } | null

function fmt(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '-'
    : value.toFixed(digits)
}

function barTime(seconds: number | null): string {
  if (!seconds) return '-'
  return new Date(seconds * 1000).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function Screener() {
  // --- source -------------------------------------------------------------
  const [sourceId, setSourceId] = useState<string>('')
  const { data: watchlists } = useQuery({
    queryKey: ['watchlists'],
    queryFn: () => watchlistApi.list(),
  })
  const { apiKey } = useAuthStore()
  const { data: pulse } = useQuery({
    queryKey: ['screener-market-pulse', apiKey],
    queryFn: () => tradefinderApi.getMarketPulse(apiKey as string),
    enabled: Boolean(apiKey),
    staleTime: 30_000,
  })
  const pulseData: MarketPulseData | undefined = pulse?.data

  const symbols: ScanSymbol[] = useMemo(() => {
    if (sourceId.startsWith('tf:')) {
      const key = sourceId.slice(3) as (typeof TF_LISTS)[number]['key']
      const items = pulseData?.[key] ?? []
      return items.map((item) => ({ symbol: item.symbol, exchange: TF_EXCHANGE }))
    }
    if (sourceId.startsWith('wl:')) {
      const list = watchlists?.find((w) => String(w.id) === sourceId.slice(3))
      return (list?.items ?? []).map((item) => ({
        symbol: item.symbol,
        exchange: item.exchange,
      }))
    }
    return []
  }, [sourceId, pulseData, watchlists])

  // --- indicator ----------------------------------------------------------
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [descriptor, setDescriptor] = useState<Descriptor | null>(null)
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const registry = useRef<{
    getIndicator(id: string): Descriptor | undefined
    indicatorDefaults(d: unknown): Record<string, unknown>
  } | null>(null)

  useEffect(() => {
    let alive = true
    void (async () => {
      // Same order as terminal.ts: the built-in tier registers first so the
      // custom loader can tell a user file shadowing a built-in.
      const core = await import('openalgo-charts')
      await import('openalgo-charts/indicators')
      const { loadCustomIndicators } = await import('@/lib/trading/customIndicators')
      const result = await loadCustomIndicators({
        onProblem: (message) => showToast.error(message),
      })
      for (const failure of result.errors) {
        showToast.error(`${failure.file}: ${failure.message}`)
      }
      if (!alive) return
      const api = core as unknown as {
        registeredIndicators(): CatalogEntry[]
        getIndicator(id: string): Descriptor | undefined
        indicatorDefaults(d: unknown): Record<string, unknown>
      }
      registry.current = api
      setCatalog(
        api.registeredIndicators().map((d) => ({
          id: d.id,
          name: d.name,
          category: d.category || 'Custom',
        }))
      )
    })()
    return () => {
      alive = false
    }
  }, [])

  const selectIndicator = useCallback((id: string) => {
    const found = registry.current?.getIndicator(id)
    if (!found) return
    noteRecentIndicator(id)
    setDescriptor(found)
    setSettings(registry.current?.indicatorDefaults(found) ?? {})
    setFilters([])
    setPickerOpen(false)
  }, [])

  // --- scan inputs --------------------------------------------------------
  const [interval, setInterval] = useState<string>('D')
  const [bars, setBars] = useState<number>(300)
  const [live, setLive] = useState(false)
  const [filters, setFilters] = useState<Filter[]>([])

  // --- scan state ---------------------------------------------------------
  const worker = useRef<Worker | null>(null)
  const runId = useRef(0)
  const [scanning, setScanning] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [rows, setRows] = useState<ScanRow[]>([])
  const [missing, setMissing] = useState<ScanSymbol[]>([])
  const [extraColumns, setExtraColumns] = useState<string[]>([])
  const [showExtra, setShowExtra] = useState(false)
  const [summary, setSummary] = useState<string>('')
  const [resultKey, setResultKey] = useState<string>('')
  const [sort, setSort] = useState<SortState>(null)

  // One worker for the life of the page. Spawning one per scan would leak a
  // thread and a second copy of the indicator library on every click.
  useEffect(() => {
    const instance = new Worker(new URL('@/lib/screener/scanWorker.ts', import.meta.url), {
      type: 'module',
    })
    instance.onmessage = (event: MessageEvent<ScanEvent>) => {
      const message = event.data
      // A stale run's results must never land in a newer run's table.
      if (message.runId !== runId.current) return
      switch (message.type) {
        case 'progress':
          setProgress({ done: message.done, total: message.total })
          break
        case 'columns':
          setExtraColumns(message.extra)
          break
        case 'rows':
          setRows((prev) => [...prev, ...message.rows])
          break
        case 'missing':
          setMissing((prev) => [...prev, ...message.missing])
          break
        case 'problem':
          showToast.error(message.message)
          break
        case 'done':
          setScanning(false)
          setSummary(
            `${message.matched} of ${message.scanned} matched` +
              (message.failed ? `, ${message.failed} errored` : '')
          )
          break
        case 'error':
          setScanning(false)
          showToast.error(message.message)
          break
      }
    }
    worker.current = instance
    return () => {
      instance.terminate()
      worker.current = null
    }
  }, [])

  const plotColumns: FilterColumn[] = useMemo(
    () => (descriptor?.plots ?? []).map((p) => ({ key: p.key, label: p.title || p.key })),
    [descriptor]
  )
  const filterColumns: FilterColumn[] = useMemo(
    () => [
      ...plotColumns,
      ...extraColumns
        .filter((key) => !plotColumns.some((p) => p.key === key))
        .map((key) => ({ key, label: key })),
    ],
    [plotColumns, extraColumns]
  )
  const alertOptions = useMemo(
    () => (descriptor?.alerts ?? []).map((a) => ({ id: a.id, title: a.title || a.id })),
    [descriptor]
  )

  /**
   * Everything a result depends on, in one string. When it stops matching the
   * key the table was produced under, the table is stale -- shown as a banner
   * rather than auto-rescanned, because a scan is expensive and should be asked
   * for.
   */
  const scanKey = useMemo(
    () =>
      JSON.stringify({
        sourceId,
        symbols,
        indicatorId: descriptor?.id,
        settings,
        filters,
        interval,
        bars,
        live,
      }),
    [sourceId, symbols, descriptor, settings, filters, interval, bars, live]
  )
  const stale = resultKey !== '' && resultKey !== scanKey

  const scan = useCallback(async () => {
    if (!descriptor || symbols.length === 0 || !worker.current) return
    if (symbols.length > MAX_SYMBOLS) {
      showToast.error(`${symbols.length} symbols; the limit is ${MAX_SYMBOLS}`)
      return
    }
    if (descriptor.attach) {
      showToast.warning(
        `${descriptor.name} loads external data on the chart, which a scan cannot provide. Its columns may be empty.`
      )
    }
    let csrf = ''
    try {
      csrf = await fetchCSRFToken()
    } catch {
      showToast.error('Could not start scan: session expired')
      return
    }
    // Tell the running scan to stop before claiming the new id, or it keeps
    // fetching chunks nobody will read.
    worker.current.postMessage({ type: 'cancel', runId: runId.current })
    runId.current += 1
    setRows([])
    setMissing([])
    setSummary('')
    setSort(null)
    setProgress({ done: 0, total: symbols.length })
    setScanning(true)
    setResultKey(scanKey)
    worker.current.postMessage({
      type: 'scan',
      runId: runId.current,
      csrf,
      symbols,
      interval,
      bars,
      live,
      indicatorId: descriptor.id,
      settings,
      filters,
    })
  }, [descriptor, symbols, interval, bars, live, settings, filters, scanKey])

  const valueColumns = useMemo(
    () => [...plotColumns, ...(showExtra ? filterColumns.slice(plotColumns.length) : [])],
    [plotColumns, filterColumns, showExtra]
  )

  const sorted = useMemo(() => {
    const good = rows.filter((r) => !r.error)
    const bad = rows.filter((r) => r.error)
    if (!sort) return [...good, ...bad]
    const read = (row: ScanRow): number | null =>
      sort.key === 'close'
        ? row.close
        : sort.key === 'changePct'
          ? row.changePct
          : (row.values[sort.key] ?? null)
    const factor = sort.dir === 'asc' ? 1 : -1
    // Nulls sort last in both directions: no reading is not a small number, and
    // burying the symbols an indicator could not judge under the ones it could
    // is the only ordering that reads correctly either way round.
    good.sort((a, b) => {
      const x = read(a)
      const y = read(b)
      if (x === null && y === null) return 0
      if (x === null) return 1
      if (y === null) return -1
      return (x - y) * factor
    })
    return [...good, ...bad]
  }, [rows, sort])

  const toggleSort = (key: string) =>
    setSort((prev) =>
      prev?.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }
    )

  // Every row failing the same way means the indicator cannot be screened at
  // all, which deserves saying once rather than repeating N times in a table.
  const uniformError = useMemo(() => {
    const errors = rows.filter((r) => r.error)
    if (errors.length === 0 || errors.length !== rows.length) return null
    const first = errors[0].error
    return errors.every((r) => r.error === first) ? first : null
  }, [rows])

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div>
        <h1 className="text-2xl font-semibold">Screener</h1>
        <p className="text-sm text-muted-foreground">
          Scan a watchlist with any chart indicator. The same calculation that draws the study on
          the chart produces these values.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Scan</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Source
              </Label>
              <Select value={sourceId} onValueChange={setSourceId}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Choose a watchlist or list" />
                </SelectTrigger>
                <SelectContent>
                  {(watchlists ?? []).map((list) => (
                    <SelectItem key={list.id} value={`wl:${list.id}`}>
                      {list.name} ({list.items?.length ?? 0})
                    </SelectItem>
                  ))}
                  {TF_LISTS.map((list) => (
                    <SelectItem key={list.key} value={`tf:${list.key}`}>
                      {list.label} ({pulseData?.[list.key]?.length ?? 0})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Timeframe
                </Label>
                <Select value={interval} onValueChange={setInterval}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INTERVALS.map((i) => (
                      <SelectItem key={i} value={i}>
                        {i}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Bars
                </Label>
                <Select value={String(bars)} onValueChange={(v) => setBars(Number(v))}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BAR_CHOICES.map((b) => (
                      <SelectItem key={b} value={String(b)}>
                        {b}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="screener-live" className="text-[13px] text-muted-foreground">
                Stitch the live candle
              </Label>
              <Switch id="screener-live" checked={live} onCheckedChange={setLive} />
            </div>

            <div className="space-y-1">
              <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                Indicator
              </Label>
              <Button
                variant="outline"
                className="h-9 w-full justify-start"
                onClick={() => setPickerOpen(true)}
                disabled={catalog.length === 0}
              >
                {descriptor?.name ?? (catalog.length === 0 ? 'Loading...' : 'Choose an indicator')}
              </Button>
            </div>

            {descriptor && (descriptor.inputs?.length ?? 0) > 0 && (
              <div className="space-y-2">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Settings
                </Label>
                <div className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-2">
                  {(descriptor.inputs ?? []).map((field) => (
                    <SettingsField
                      key={field.key}
                      field={field}
                      id={`screener-input-${field.key}`}
                      value={settings[field.key]}
                      onChange={(v) => setSettings((prev) => ({ ...prev, [field.key]: v }))}
                    />
                  ))}
                </div>
              </div>
            )}

            {descriptor && (
              <FilterBuilder
                columns={filterColumns}
                alerts={alertOptions}
                filters={filters}
                onChange={setFilters}
              />
            )}

            <Button
              className="w-full"
              onClick={() => void scan()}
              disabled={scanning || !descriptor || symbols.length === 0}
            >
              {scanning
                ? `Scanning ${progress.done}/${progress.total}`
                : `Scan ${symbols.length} symbol${symbols.length === 1 ? '' : 's'}`}
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-3">
          {stale && !scanning && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-sm">
              Inputs changed since this scan. Rescan to refresh the results.
            </div>
          )}

          {uniformError && (
            <div className="rounded border border-destructive/40 bg-destructive/10 p-2 text-sm">
              Every symbol failed the same way: {uniformError}. This indicator needs chart context
              and cannot be screened.
            </div>
          )}

          {scanning && (
            <div className="h-1 w-full overflow-hidden rounded bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{
                  width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%`,
                }}
              />
            </div>
          )}

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
              <CardTitle className="text-base">Results{summary ? ` - ${summary}` : ''}</CardTitle>
              {filterColumns.length > plotColumns.length && (
                <Button size="sm" variant="ghost" onClick={() => setShowExtra((v) => !v)}>
                  {showExtra ? 'Hide' : 'Show'} all columns
                </Button>
              )}
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead
                      className="cursor-pointer text-right"
                      onClick={() => toggleSort('close')}
                    >
                      Close
                    </TableHead>
                    <TableHead
                      className="cursor-pointer text-right"
                      onClick={() => toggleSort('changePct')}
                    >
                      Chg %
                    </TableHead>
                    {valueColumns.map((column) => (
                      <TableHead
                        key={column.key}
                        className="cursor-pointer text-right"
                        onClick={() => toggleSort(column.key)}
                      >
                        {column.label}
                      </TableHead>
                    ))}
                    <TableHead>Last bar</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5 + valueColumns.length}
                        className="text-center text-sm text-muted-foreground"
                      >
                        {scanning ? 'Scanning...' : 'No results yet.'}
                      </TableCell>
                    </TableRow>
                  )}
                  {sorted.map((row) => (
                    <TableRow key={`${row.exchange}:${row.symbol}`}>
                      <TableCell className="font-medium">{row.symbol}</TableCell>
                      <TableCell className="text-muted-foreground">{row.exchange}</TableCell>
                      {row.error ? (
                        <TableCell
                          colSpan={2 + valueColumns.length + 1}
                          className="text-sm text-destructive"
                        >
                          {row.error}
                        </TableCell>
                      ) : (
                        <>
                          <TableCell className="text-right">{fmt(row.close)}</TableCell>
                          <TableCell
                            className={
                              row.changePct === null
                                ? 'text-right'
                                : row.changePct >= 0
                                  ? 'text-right text-emerald-500'
                                  : 'text-right text-red-500'
                            }
                          >
                            {fmt(row.changePct)}
                          </TableCell>
                          {valueColumns.map((column) => (
                            <TableCell key={column.key} className="text-right">
                              {fmt(row.values[column.key], 4)}
                            </TableCell>
                          ))}
                          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                            {barTime(row.lastBarTime)}
                          </TableCell>
                        </>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {missing.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">No data ({missing.length})</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  These were not scanned because Historify holds no {interval} bars for them.
                  Download them in{' '}
                  <Link className="underline" to="/historify">
                    Historify
                  </Link>{' '}
                  and scan again.
                </p>
                <p className="text-sm">
                  {missing.map((m) => `${m.exchange}:${m.symbol}`).join(', ')}
                </p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Limits</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-muted-foreground">
              <p>Up to {MAX_SYMBOLS} symbols per scan.</p>
              <p>Only symbols already downloaded into Historify are scanned.</p>
              <p>
                Timeframes are limited to what Historify stores or aggregates: 1m, 5m, 15m, 30m, 1h
                and D.
              </p>
              <p>
                Indicators that read chart context, or that load external data on the chart, cannot
                be screened.
              </p>
              <p>
                With the live candle stitched on, its close is the current price and its high and
                low approximate the forming candle. The last-bar column shows how fresh each symbol
                actually is.
              </p>
              <p>Only the most recent bar is judged, and the one before it for crossovers.</p>
            </CardContent>
          </Card>
        </div>
      </div>

      <IndicatorPickerDialog
        open={pickerOpen}
        catalog={catalog}
        active={descriptor ? [{ id: descriptor.id, name: descriptor.name }] : []}
        onAdd={selectIndicator}
        onRemove={() => setDescriptor(null)}
        onSettings={() => {}}
        onClose={() => setPickerOpen(false)}
      />
    </div>
  )
}
