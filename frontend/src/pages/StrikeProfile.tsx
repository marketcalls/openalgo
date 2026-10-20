import { Check, ChevronsUpDown, Copy } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type StrikeProfileResponse, strikeProfileApi } from '@/api/strike-profile'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import Plot from '@/lib/Plot2D'
import { serverSentence } from '@/lib/serverSentence'
import {
  cellValue,
  columnTotal,
  expiryHeading,
  expiryPeaks,
  formatExposure,
  type Metric,
  maxMagnitude,
  nearestStrikeIndex,
  type PeakMode,
  RANGES,
  rangeCovered,
  type StrikeRange,
  shadeStrength,
  shortExpiryLabel,
  toApiExpiry,
  visibleStrikeIndexes,
} from '@/lib/strikeProfile'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

const AUTO_REFRESH_INTERVAL = 60000
const DEFAULT_EXPIRY_COUNT = 6
const MAX_EXPIRIES = 20
const FETCH_FALLBACK = 'Failed to fetch strike profile'

type View = 'table' | 'chart'
type Scale = 'global' | 'expiry'

const METRIC_LABEL: Record<Metric, string> = { gex: 'GEX', dex: 'DEX' }

/** Positive and negative colours per metric, validated for colour-blind separation. */
function metricColors(metric: Metric, isDark: boolean): { pos: string; neg: string } {
  if (metric === 'gex') return { pos: isDark ? '#3b82f6' : '#2563eb', neg: '#ea580c' }
  return { pos: '#0d9488', neg: '#e11d48' }
}

function withAlpha(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha.toFixed(3)})`
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'n/a'
  return value.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function formatTime(epochSeconds: number | undefined): string {
  if (!epochSeconds) return ''
  return new Date(epochSeconds * 1000).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

interface SegmentedProps<T extends string | number | null> {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}

function Segmented<T extends string | number | null>({
  label,
  value,
  options,
  onChange,
}: SegmentedProps<T>) {
  return (
    <fieldset className="flex items-center gap-1.5">
      <legend className="sr-only">{label}</legend>
      <span className="text-xs text-muted-foreground" aria-hidden="true">
        {label}
      </span>
      <div className="inline-flex rounded-md border border-border p-0.5">
        {options.map((option) => (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
            className={`px-2 py-0.5 text-xs rounded-sm transition-colors ${
              option.value === value
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  )
}

interface PaneProps {
  data: StrikeProfileResponse
  initialMetric: Metric
  loadedRange: StrikeRange
  onRequestRange: (range: StrikeRange) => void
  isDark: boolean
  isLoading: boolean
}

function ProfilePane({
  data,
  initialMetric,
  loadedRange,
  onRequestRange,
  isDark,
  isLoading,
}: PaneProps) {
  const [metric, setMetric] = useState<Metric>(initialMetric)
  const [view, setView] = useState<View>('table')
  const [peaks, setPeaks] = useState<PeakMode>('all')
  const [range, setRange] = useState<StrikeRange>(2)
  const [scale, setScale] = useState<Scale>('global')

  const strikes = data.strikes ?? []
  const expiries = data.expiries ?? []
  const spot = data.spot_price ?? 0
  const colors = metricColors(metric, isDark)
  const label = METRIC_LABEL[metric]

  // A range wider than the loaded window shows every loaded strike until the
  // wider window arrives.
  const shownRange = rangeCovered(range, loadedRange) ? range : loadedRange

  const rows = useMemo(
    () => visibleStrikeIndexes(strikes, spot, shownRange),
    [strikes, spot, shownRange]
  )
  const atmIndex = useMemo(() => nearestStrikeIndex(strikes, spot), [strikes, spot])

  const columns = useMemo(
    () =>
      expiries.map((expiry) => {
        const values = expiry.cells.map((cell) => cellValue(cell, metric))
        const shown = rows.map((i) => values[i])
        return {
          expiry,
          heading: expiryHeading(expiry),
          values,
          peaks: expiryPeaks(values, rows, peaks),
          total: columnTotal(values, rows),
          max: maxMagnitude(shown),
        }
      }),
    [expiries, metric, rows, peaks]
  )

  const globalMax = useMemo(
    () => maxMagnitude(columns.flatMap((c) => rows.map((i) => c.values[i]))),
    [columns, rows]
  )

  const nearest = columns.find((c) => c.expiry.available && c.total !== null)

  const copyTable = useCallback(async () => {
    const header = ['Strike', ...columns.map((c) => `${c.heading.dte} ${c.heading.date}`)]
    const lines = [header.join('\t')]
    for (const i of rows) {
      lines.push(
        [
          String(strikes[i]),
          ...columns.map((c) => (c.values[i] === null ? '' : c.values[i]?.toFixed(2))),
        ].join('\t')
      )
    }
    lines.push(
      [`Net ${label}`, ...columns.map((c) => (c.total === null ? '' : c.total.toFixed(2)))].join(
        '\t'
      )
    )
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      showToast.success('Table copied')
    } catch {
      showToast.error('Could not copy the table. Your browser blocked clipboard access.')
    }
  }, [columns, rows, strikes, label])

  const chart = useMemo(() => {
    const ys: number[] = []
    const xs: number[] = []
    const breakdown: string[] = []
    for (const i of rows) {
      let total = 0
      const parts: string[] = []
      for (const c of columns) {
        const v = c.values[i]
        if (v === null || v === undefined) continue
        total += v
        if (Math.abs(v) >= 0.05) parts.push(`${c.heading.dte}: ${formatExposure(v, true)}`)
      }
      ys.push(strikes[i])
      xs.push(total)
      breakdown.push(parts.slice(0, 10).join('<br>') || 'No exposure')
    }
    const text = isDark ? '#e0e0e0' : '#333333'
    const grid = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)'
    const line = isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)'
    const plotData: PlotlyTypes.Data[] = [
      {
        type: 'bar',
        orientation: 'h',
        x: xs,
        y: ys,
        marker: { color: xs.map((v) => (v >= 0 ? colors.pos : colors.neg)) },
        customdata: breakdown,
        hovertemplate: `Strike %{y}<br>Net ${label} %{x:,.1f} Cr<br><br>%{customdata}<extra></extra>`,
      },
    ]
    const shapes: Partial<PlotlyTypes.Shape>[] = [
      {
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: spot,
        y1: spot,
        line: { color: line, width: 1, dash: 'dash' },
      },
    ]
    const annotations: Partial<PlotlyTypes.Annotations>[] = [
      {
        xref: 'paper',
        x: 1,
        y: spot,
        xanchor: 'right',
        yanchor: 'bottom',
        text: `Spot ${formatPrice(spot)}`,
        showarrow: false,
        font: { color: text, size: 11 },
      },
    ]
    if (data.flip !== null && data.flip !== undefined) {
      shapes.push({
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: data.flip,
        y1: data.flip,
        line: { color: line, width: 1, dash: 'dot' },
      })
      annotations.push({
        xref: 'paper',
        x: 0,
        y: data.flip,
        xanchor: 'left',
        yanchor: 'bottom',
        text: `Flip ${formatPrice(data.flip)}`,
        showarrow: false,
        font: { color: text, size: 11 },
      })
    }
    const layout: Partial<PlotlyTypes.Layout> = {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: text, family: 'system-ui, sans-serif', size: 11 },
      margin: { l: 64, r: 16, t: 16, b: 48 },
      bargap: 0.25,
      showlegend: false,
      hoverlabel: { bgcolor: isDark ? '#1e293b' : '#ffffff', font: { color: text } },
      xaxis: {
        title: { text: `Net ${label}, Rs crore, sum of ${columns.length} expiries` },
        gridcolor: grid,
        zerolinecolor: line,
      },
      yaxis: { gridcolor: grid, tickformat: 'd' },
      shapes,
      annotations,
    }
    return { plotData, layout, height: Math.max(380, rows.length * 18 + 80) }
  }, [rows, columns, strikes, colors, label, spot, data.flip, isDark])

  return (
    <Card className="min-w-0">
      <CardContent className="p-3 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented<Metric>
            label="Exposure"
            value={metric}
            onChange={setMetric}
            options={[
              { value: 'gex', label: 'GEX' },
              { value: 'dex', label: 'DEX' },
            ]}
          />
          <Segmented<View>
            label="View"
            value={view}
            onChange={setView}
            options={[
              { value: 'table', label: 'Table' },
              { value: 'chart', label: 'Chart' },
            ]}
          />
          {view === 'table' && (
            <>
              <Segmented<PeakMode>
                label="Peaks"
                value={peaks}
                onChange={setPeaks}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'max', label: 'Max' },
                  { value: 'off', label: 'Off' },
                ]}
              />
              <Segmented<Scale>
                label="Shade"
                value={scale}
                onChange={setScale}
                options={[
                  { value: 'global', label: 'Global' },
                  { value: 'expiry', label: 'Per expiry' },
                ]}
              />
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <span>
              Net {label}{' '}
              <span
                className="text-sm normal-case"
                style={{
                  color: nearest && (nearest.total ?? 0) < 0 ? colors.neg : colors.pos,
                }}
              >
                {nearest?.total !== null && nearest?.total !== undefined
                  ? `${formatExposure(nearest.total, true)} Cr`
                  : 'n/a'}
              </span>
              {nearest && (
                <span className="normal-case"> {shortExpiryLabel(nearest.expiry.expiry)}</span>
              )}
            </span>
            <span>
              Flip <span className="text-sm text-foreground">{formatPrice(data.flip)}</span>
            </span>
            <span>
              C wall <span className="text-sm text-foreground">{formatPrice(data.call_wall)}</span>
            </span>
            <span>
              P wall <span className="text-sm text-foreground">{formatPrice(data.put_wall)}</span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Segmented<StrikeRange>
              label="Range"
              value={range}
              onChange={(next) => {
                setRange(next)
                onRequestRange(next)
              }}
              options={RANGES.map((r) => ({ value: r, label: r === null ? 'All' : `±${r}%` }))}
            />
            {view === 'table' && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={copyTable}
                aria-label="Copy table"
                title="Copy table"
              >
                <Copy className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
            No strikes in this range
          </div>
        ) : view === 'chart' ? (
          <Plot
            data={chart.plotData}
            layout={chart.layout}
            config={{ displaylogo: false, responsive: true, displayModeBar: false }}
            useResizeHandler
            style={{ width: '100%', height: `${chart.height}px` }}
          />
        ) : (
          <div
            className={`max-h-[70vh] overflow-auto rounded-md border border-border ${isLoading ? 'opacity-70' : ''}`}
          >
            <table className="w-full border-separate border-spacing-0 text-xs tabular-nums">
              <caption className="sr-only">
                Net {label} in rupees crore by strike and expiry
              </caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="sticky left-0 top-0 z-30 bg-card px-3 py-2 text-left font-medium text-muted-foreground border-b border-border"
                  >
                    Strike
                  </th>
                  {columns.map((c) => (
                    <th
                      key={c.expiry.expiry}
                      scope="col"
                      className="sticky top-0 z-20 bg-card px-2 py-1.5 text-center font-semibold border-b border-border whitespace-nowrap"
                    >
                      <div>{c.heading.dte}</div>
                      <div className="font-normal text-muted-foreground">{c.heading.date}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => {
                  const isAtm = i === atmIndex
                  const rowBorder = isAtm ? 'border-y border-dashed border-muted-foreground/60' : ''
                  return (
                    <tr key={strikes[i]}>
                      <th
                        scope="row"
                        className={`sticky left-0 z-10 bg-card px-3 py-1.5 text-left whitespace-nowrap ${rowBorder} ${
                          isAtm ? 'font-bold text-foreground' : 'font-normal text-muted-foreground'
                        }`}
                      >
                        {formatPrice(strikes[i])}
                      </th>
                      {columns.map((c) => {
                        const cell = c.expiry.cells[i]
                        const v = c.values[i]
                        if (!c.expiry.available || v === null || v === undefined) {
                          return (
                            <td
                              key={c.expiry.expiry}
                              className={`px-2 py-1.5 text-center text-muted-foreground/60 ${rowBorder}`}
                            />
                          )
                        }
                        const color = v >= 0 ? colors.pos : colors.neg
                        const isPeak = c.peaks.has(i)
                        const strength = shadeStrength(v, scale === 'expiry' ? c.max : globalMax)
                        const tip = [
                          `${formatPrice(strikes[i])} ${c.heading.dte} (${c.heading.date})`,
                          `Net ${label}: ${formatExposure(v, true)} Cr`,
                          `Call ${label}: ${formatExposure(metric === 'gex' ? (cell?.ce_gex ?? 0) : (cell?.ce_dex ?? 0), true)} Cr, OI ${(cell?.ce_oi ?? 0).toLocaleString('en-IN')}`,
                          `Put ${label}: ${formatExposure(metric === 'gex' ? (cell?.pe_gex ?? 0) : (cell?.pe_dex ?? 0), true)} Cr, OI ${(cell?.pe_oi ?? 0).toLocaleString('en-IN')}`,
                          cell?.unpriced ? 'Some open interest could not be priced' : '',
                        ]
                          .filter(Boolean)
                          .join('\n')
                        const style = isPeak
                          ? {
                              backgroundColor: color,
                              color: '#ffffff',
                              boxShadow: `inset 0 0 0 1px ${withAlpha('#ffffff', 0.35)}, 0 0 10px ${withAlpha(color, 0.7)}`,
                            }
                          : { backgroundColor: withAlpha(color, 0.04 + 0.6 * strength) }
                        return (
                          <td
                            key={c.expiry.expiry}
                            title={tip}
                            style={style}
                            className={`px-2 py-1.5 text-center whitespace-nowrap ${rowBorder} ${
                              isPeak
                                ? 'font-semibold relative z-[1]'
                                : strength > 0.4
                                  ? 'text-foreground'
                                  : 'text-muted-foreground'
                            }`}
                          >
                            {cell?.unpriced && v === 0 ? 'n/a' : formatExposure(v)}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th
                    scope="row"
                    className="sticky bottom-0 left-0 z-30 bg-card px-3 py-2 text-left font-medium text-muted-foreground border-t border-border whitespace-nowrap"
                    title="Sum of the strikes shown"
                  >
                    Net {label}
                  </th>
                  {columns.map((c) => (
                    <td
                      key={c.expiry.expiry}
                      className="sticky bottom-0 z-20 bg-card px-2 py-2 text-center font-semibold border-t border-border"
                      style={{
                        color:
                          c.total === null ? undefined : c.total >= 0 ? colors.pos : colors.neg,
                      }}
                    >
                      {c.expiry.available
                        ? c.total === null
                          ? '0'
                          : formatExposure(c.total)
                        : 'n/a'}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function StrikeProfile() {
  const { mode, appMode } = useThemeStore()
  const { toolsFnoExchanges, defaultToolsFnoExchange, defaultUnderlyings } = useSupportedExchanges()
  const isDark = mode === 'dark' || appMode === 'analyzer'

  const [selectedExchange, setSelectedExchange] = useState(defaultToolsFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultToolsFnoExchange] || []
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultToolsFnoExchange]?.[0] || ''
  )
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>([])
  const [expiryOpen, setExpiryOpen] = useState(false)
  const [draftExpiries, setDraftExpiries] = useState<string[]>([])
  const [loadedRange, setLoadedRange] = useState<StrikeRange>(5)
  const [paneCount, setPaneCount] = useState<1 | 2>(2)
  const [data, setData] = useState<StrikeProfileResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const requestIdRef = useRef(0)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && toolsFnoExchanges.some((ex) => ex.value === prev) ? prev : defaultToolsFnoExchange
    )
  }, [defaultToolsFnoExchange, toolsFnoExchanges])

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiries([])
    setData(null)

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await strikeProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          if (!response.underlyings.includes(defaults[0])) {
            setSelectedUnderlying(response.underlyings[0])
          }
        }
      } catch {
        // Keep defaults
      }
    }
    fetchUnderlyings()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings])

  // Fetch expiries when underlying changes; the nearest few are selected
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiries([])
    setData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await strikeProfileApi.getExpiries(selectedExchange, selectedUnderlying)
        if (cancelled) return
        if (response.status === 'success' && response.expiries.length > 0) {
          setExpiries(response.expiries)
          setSelectedExpiries(response.expiries.slice(0, DEFAULT_EXPIRY_COUNT))
        }
      } catch {
        if (cancelled) return
        setExpiries([])
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

  const fetchProfile = useCallback(async () => {
    if (selectedExpiries.length === 0) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const response = await strikeProfileApi.getProfileData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_dates: selectedExpiries.map(toApiExpiry),
        range_pct: loadedRange,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setData(response)
      } else {
        showToast.error(response.message || FETCH_FALLBACK)
      }
    } catch (error) {
      if (requestIdRef.current !== requestId) return
      showToast.error(serverSentence(error, FETCH_FALLBACK))
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExchange, selectedExpiries, loadedRange])

  const selectionKey = selectedExpiries.join(',')

  // biome-ignore lint/correctness/useExhaustiveDependencies: must fire only when the expiry selection or the loaded range changes; keying on fetchProfile would fire a stale request with mixed exchange/underlying params during an exchange switch
  useEffect(() => {
    if (selectionKey) fetchProfile()
  }, [selectionKey, loadedRange])

  useEffect(() => {
    if (!autoRefresh || selectedExpiries.length === 0) return
    const id = setInterval(fetchProfile, AUTO_REFRESH_INTERVAL)
    return () => clearInterval(id)
  }, [autoRefresh, fetchProfile, selectedExpiries.length])

  const requestRange = useCallback((range: StrikeRange) => {
    setLoadedRange((loaded) => (rangeCovered(range, loaded) ? loaded : range))
  }, [])

  const applyExpiries = () => {
    const ordered = expiries.filter((e) => draftExpiries.includes(e))
    setExpiryOpen(false)
    if (ordered.length === 0) return
    if (ordered.join(',') !== selectionKey) setSelectedExpiries(ordered)
  }

  const expiryButtonLabel =
    selectedExpiries.length === 0
      ? 'Expiries'
      : selectedExpiries.length === expiries.length
        ? `All ${expiries.length} expiries`
        : `${selectedExpiries.length} of ${expiries.length} expiries`

  return (
    <div className="py-6 space-y-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Strike Profile</h1>
          <p className="text-sm text-muted-foreground">
            Gamma and delta exposure by strike and expiry, in rupees crore. GEX is per 1% move in
            the underlying; DEX is delta-weighted open interest.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Select value={selectedExchange} onValueChange={setSelectedExchange}>
            <SelectTrigger className="w-[100px]" aria-label="Exchange">
              <SelectValue placeholder="Exchange" />
            </SelectTrigger>
            <SelectContent>
              {toolsFnoExchanges.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={underlyingOpen}
                className="w-[160px] justify-between"
              >
                {selectedUnderlying || 'Underlying'}
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 p-0" align="start">
              <Command>
                <CommandInput placeholder="Search underlying..." />
                <CommandList>
                  <CommandEmpty>No underlying found</CommandEmpty>
                  <CommandGroup>
                    {underlyings.map((u) => (
                      <CommandItem
                        key={u}
                        value={u}
                        onSelect={() => {
                          setSelectedUnderlying(u)
                          setUnderlyingOpen(false)
                        }}
                      >
                        <Check
                          className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`}
                        />
                        {u}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>

          <Popover
            open={expiryOpen}
            onOpenChange={(open) => {
              if (open) setDraftExpiries(selectedExpiries)
              setExpiryOpen(open)
            }}
          >
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className="w-[170px] justify-between"
                disabled={expiries.length === 0}
              >
                {expiryButtonLabel}
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-0" align="start">
              <div className="flex items-center justify-between gap-2 border-b border-border p-2 text-xs">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setDraftExpiries(expiries.slice(0, MAX_EXPIRIES))}
                >
                  {expiries.length > MAX_EXPIRIES ? `Nearest ${MAX_EXPIRIES}` : 'All'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setDraftExpiries(expiries.slice(0, DEFAULT_EXPIRY_COUNT))}
                >
                  Nearest {DEFAULT_EXPIRY_COUNT}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setDraftExpiries(expiries.slice(0, 1))}
                >
                  Nearest
                </Button>
              </div>
              <div className="max-h-72 overflow-y-auto p-2 space-y-1">
                {expiries.map((e) => {
                  const checked = draftExpiries.includes(e)
                  const full = !checked && draftExpiries.length >= MAX_EXPIRIES
                  const id = `strike-profile-expiry-${e}`
                  return (
                    <label
                      key={e}
                      htmlFor={id}
                      className={`flex items-center gap-2 rounded px-1 py-1 text-sm ${full ? 'opacity-50' : 'hover:bg-muted cursor-pointer'}`}
                    >
                      <Checkbox
                        id={id}
                        checked={checked}
                        disabled={full}
                        onCheckedChange={(value) =>
                          setDraftExpiries((prev) =>
                            value ? [...prev, e] : prev.filter((x) => x !== e)
                          )
                        }
                      />
                      {e}
                    </label>
                  )
                })}
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-border p-2">
                <span className="text-xs text-muted-foreground">
                  {draftExpiries.length} selected
                </span>
                <Button size="sm" onClick={applyExpiries} disabled={draftExpiries.length === 0}>
                  Apply
                </Button>
              </div>
            </PopoverContent>
          </Popover>

          <Segmented<1 | 2>
            label="Panes"
            value={paneCount}
            onChange={setPaneCount}
            options={[
              { value: 1, label: '1' },
              { value: 2, label: '2' },
            ]}
          />

          <Button
            variant={autoRefresh ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            {autoRefresh ? 'Auto: ON' : 'Auto: OFF'}
          </Button>

          <Button variant="outline" size="sm" onClick={fetchProfile} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {data?.status === 'success' && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
          <span>
            {data.underlying} spot{' '}
            <span className="font-medium text-foreground">
              {data.spot_price?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            </span>
          </span>
          <span>As of {formatTime(data.as_of)} IST</span>
          <span>
            {(data.expiries ?? []).filter((e) => e.available).length} of{' '}
            {(data.expiries ?? []).length} expiries loaded
          </span>
        </div>
      )}

      {!data ? (
        <Card>
          <CardContent className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">
            {isLoading
              ? `Loading ${selectedExpiries.length} expiries. Each expiry is one option chain, so this can take a few seconds.`
              : selectedExpiries.length > 0
                ? 'No strike profile loaded'
                : 'Select an underlying and expiries to view the strike profile'}
          </CardContent>
        </Card>
      ) : (
        <div className={`grid gap-4 ${paneCount === 2 ? 'grid-cols-1 2xl:grid-cols-2' : ''}`}>
          <ProfilePane
            data={data}
            initialMetric="gex"
            loadedRange={loadedRange}
            onRequestRange={requestRange}
            isDark={isDark}
            isLoading={isLoading}
          />
          {paneCount === 2 && (
            <ProfilePane
              data={data}
              initialMetric="dex"
              loadedRange={loadedRange}
              onRequestRange={requestRange}
              isDark={isDark}
              isLoading={isLoading}
            />
          )}
        </div>
      )}
    </div>
  )
}
