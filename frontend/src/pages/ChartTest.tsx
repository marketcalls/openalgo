/**
 * ChartTest (DEV / TESTING ONLY) - route: /chart/test
 *
 * A throwaway test page (not linked from any menu) that:
 *   - searches symbols (same /search/api/search backend as the WebSocket test page),
 *   - lets you add multiple candlestick charts,
 *   - loads 1-minute history for the most recent trading day
 *     (/chart/test/api/history), and
 *   - streams the forming 1-minute candle live via the shared useMarketData hook.
 *
 * Only the 1-minute interval is supported. lightweight-charts is the bundled
 * v5 library (no CDN), and no CSP changes are required.
 */

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMarketData } from '@/hooks/useMarketData'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

// Matches the IST shift baked into the backend candle times so live bars line
// up with history bars on the time axis. 5h30m = 19800s.
const IST_OFFSET = 19800

const EXCHANGES = ['NSE', 'NFO', 'BFO', 'BSE', 'MCX', 'CDS', 'NSE_INDEX', 'BSE_INDEX']

// Common timeframe switcher (OpenAlgo interval format). Bucket size in seconds
// is a whole multiple of the 5h30m IST offset for each, so live ticks bucket in
// exact alignment with the broker's bars (no phase correction needed).
const TIMEFRAMES = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
]
const INTERVAL_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

interface SearchResult {
  symbol: string
  exchange: string
  name?: string
}

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface ChartItem {
  id: string // `${exchange}:${symbol}`
  symbol: string
  exchange: string
}

export default function ChartTest() {
  const [exchange, setExchange] = useState('NSE')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [showResults, setShowResults] = useState(false)
  const [charts, setCharts] = useState<ChartItem[]>([])
  const [timeframe, setTimeframe] = useState('1m')
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runSearch = useCallback(
    (q: string) => {
      if (!q.trim()) {
        setResults([])
        return
      }
      fetch(
        `/search/api/search?q=${encodeURIComponent(q)}&exchange=${encodeURIComponent(exchange)}`,
        { credentials: 'include', headers: { Accept: 'application/json' } }
      )
        .then((r) => r.json())
        .then((d) => {
          setResults((d.results || []).slice(0, 12))
          setShowResults(true)
        })
        .catch(() => setResults([]))
    },
    [exchange]
  )

  const onQueryChange = (v: string) => {
    setQuery(v)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => runSearch(v), 220)
  }

  const addChart = useCallback((symbol: string, ex: string) => {
    const id = `${ex}:${symbol}`
    setCharts((prev) => {
      if (prev.some((c) => c.id === id)) {
        showToast.info(`${symbol} (${ex}) is already added`)
        return prev
      }
      return [...prev, { id, symbol, exchange: ex }]
    })
    setShowResults(false)
    setQuery('')
  }, [])

  const removeChart = useCallback((id: string) => {
    setCharts((prev) => prev.filter((c) => c.id !== id))
  }, [])

  return (
    <div className="py-6 space-y-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">Chart Test</h1>
        <p className="text-sm text-muted-foreground">
          History (1m=1d, 5m=3d, 15m=9d) + live forming candle. The timeframe switches all charts
          at once. Add multiple charts. Testing only.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Select value={exchange} onValueChange={setExchange}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Exchange" />
          </SelectTrigger>
          <SelectContent>
            {EXCHANGES.map((ex) => (
              <SelectItem key={ex} value={ex}>
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="relative">
          <Input
            value={query}
            placeholder="Search symbol (e.g. RELIANCE, NIFTY)"
            className="w-[280px]"
            autoComplete="off"
            onChange={(e) => onQueryChange(e.target.value)}
            onFocus={() => results.length && setShowResults(true)}
            onBlur={() => {
              if (blurTimer.current) clearTimeout(blurTimer.current)
              blurTimer.current = setTimeout(() => setShowResults(false), 150)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && results[0]) addChart(results[0].symbol, results[0].exchange)
            }}
          />
          {showResults && results.length > 0 && (
            <div className="absolute z-30 mt-1 max-h-80 w-[340px] overflow-y-auto rounded-md border bg-popover shadow-lg">
              {results.map((r) => (
                <button
                  type="button"
                  key={`${r.exchange}:${r.symbol}`}
                  className="block w-full px-3 py-2 text-left hover:bg-accent"
                  onMouseDown={(e) => {
                    e.preventDefault()
                    addChart(r.symbol, r.exchange)
                  }}
                >
                  <div className="font-medium">{r.symbol}</div>
                  <div className="text-xs text-muted-foreground">
                    {r.name ? `${r.name} · ` : ''}
                    {r.exchange}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="inline-flex items-center rounded-md border p-0.5">
          {TIMEFRAMES.map((tf) => (
            <button
              type="button"
              key={tf.value}
              onClick={() => setTimeframe(tf.value)}
              className={`rounded px-3 py-1 text-sm font-medium transition-colors ${
                timeframe === tf.value
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tf.label}
            </button>
          ))}
        </div>

        {charts.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => setCharts([])}>
            Remove all
          </Button>
        )}
      </div>

      {charts.length === 0 ? (
        <div className="rounded-md border border-dashed py-16 text-center text-sm text-muted-foreground">
          Search a symbol and select it to add a chart. You can add multiple charts.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {charts.map((c) => (
            <LiveChart
              key={c.id}
              symbol={c.symbol}
              exchange={c.exchange}
              interval={timeframe}
              onRemove={() => removeChart(c.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function LiveChart({
  symbol,
  exchange,
  interval,
  onRemove,
}: {
  symbol: string
  exchange: string
  interval: string
  onRemove: () => void
}) {
  const { mode } = useThemeStore()
  const isDark = mode === 'dark'
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  // Authoritative model: bucket time -> candle. Completed bars are reconciled
  // from broker history; the current bucket is built live from ticks.
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef<number>(INTERVAL_SEC[interval] ?? 60)
  const readyRef = useRef(false)

  const [note, setNote] = useState('loading...')
  const [last, setLast] = useState<number | null>(null)
  const [refPrice, setRefPrice] = useState<number | null>(null)

  const { data, isAuthenticated } = useMarketData({
    symbols: [{ symbol, exchange }],
    mode: 'Quote',
    enabled: true,
    autoReconnect: true,
  })

  // Create the chart once per symbol/exchange. Data (and timeframe changes) are
  // handled by the separate effect below, so switching timeframe reloads data
  // without destroying/recreating the chart.
  // biome-ignore lint/correctness/useExhaustiveDependencies: isDark used only for initial colors; theme updates handled by the applyOptions effect
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 340,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#a6adbb' : '#333',
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.06)' },
        horzLines: { color: isDark ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.06)' },
      },
      rightPriceScale: { borderColor: isDark ? 'rgba(166,173,187,0.2)' : 'rgba(0,0,0,0.1)' },
      timeScale: {
        borderColor: isDark ? 'rgba(166,173,187,0.2)' : 'rgba(0,0,0,0.1)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    chartRef.current = chart
    seriesRef.current = series

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [symbol, exchange])

  // Load history for the selected interval and run the reconcile loop. Re-runs
  // when the timeframe changes -> instant flip across all charts; the chart
  // instance is reused (only the data is swapped).
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series) return
    let disposed = false
    let inflight = false
    let timer: ReturnType<typeof setTimeout> | null = null

    // Reset the model for the new timeframe.
    candlesRef.current = new Map()
    currentBucketRef.current = null
    intervalSecRef.current = INTERVAL_SEC[interval] ?? 60
    readyRef.current = false
    setNote('loading...')

    // Push the in-memory model to the chart. On reconcile we preserve the
    // user's current zoom/scroll; on first load we fit the range.
    const applyModel = (preserveRange: boolean) => {
      const ts = chart.timeScale()
      const range = preserveRange ? ts.getVisibleLogicalRange() : null
      series.setData(
        Array.from(candlesRef.current.values())
          .sort((a, b) => a.time - b.time)
          .map((k) => ({
            time: k.time as UTCTimestamp,
            open: k.open,
            high: k.high,
            low: k.low,
            close: k.close,
          }))
      )
      if (range) {
        try {
          ts.setVisibleLogicalRange(range)
        } catch {
          /* range no longer valid after data change */
        }
      } else {
        ts.fitContent()
      }
    }

    // Reconcile the recent COMPLETED bars against the broker's official 1m
    // OHLC. The live forming bar (currentBucket) is left untouched. Only the
    // trailing 10 completed bars are patched so each refresh stays cheap and
    // self-heals broker history lag.
    const reconcile = async () => {
      if (disposed || inflight) return
      inflight = true
      try {
        const date = tradingDateRef.current
        const url =
          `/chart/test/api/history?symbol=${encodeURIComponent(symbol)}` +
          `&exchange=${encodeURIComponent(exchange)}&interval=${encodeURIComponent(interval)}` +
          `${date ? `&date=${encodeURIComponent(date)}` : ''}`
        const res = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } })
        const d = await res.json()
        if (disposed || d.status !== 'success') return
        const fetched: Candle[] = d.candles || []
        if (!fetched.length) return
        if (d.date) tradingDateRef.current = d.date
        const cur = currentBucketRef.current
        const completed = cur == null ? fetched : fetched.filter((k) => k.time < cur)
        let changed = false
        for (const k of completed.slice(-10)) {
          const prev = candlesRef.current.get(k.time)
          if (
            !prev ||
            prev.open !== k.open ||
            prev.high !== k.high ||
            prev.low !== k.low ||
            prev.close !== k.close
          ) {
            candlesRef.current.set(k.time, { ...k })
            changed = true
          }
        }
        if (changed) applyModel(true)
      } catch {
        /* transient reconcile error; the next cycle retries */
      } finally {
        inflight = false
      }
    }

    // Random 20-30s loop, re-randomized every cycle so multiple charts drift
    // apart and never hit the history API at the same instant.
    const schedule = () => {
      const delay = 20000 + Math.random() * 10000
      timer = setTimeout(async () => {
        await reconcile()
        if (!disposed) schedule()
      }, delay)
    }

    fetch(
      `/chart/test/api/history?symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}&interval=${encodeURIComponent(interval)}`,
      { credentials: 'include', headers: { Accept: 'application/json' } }
    )
      .then((r) => r.json())
      .then((d) => {
        if (disposed) return
        if (d.status !== 'success') {
          setNote(`history error: ${d.message || 'failed'}`)
          schedule()
          return
        }
        const candles: Candle[] = d.candles || []
        tradingDateRef.current = d.date || null
        if (!candles.length) {
          setNote('no history')
          schedule()
          return
        }
        candlesRef.current = new Map(candles.map((k) => [k.time, { ...k }]))
        applyModel(false)
        const lastK = candles[candles.length - 1]
        currentBucketRef.current = lastK.time
        setRefPrice(candles.length > 1 ? candles[candles.length - 2].close : lastK.open)
        setLast(lastK.close)
        setNote(`${interval} · ${candles.length} bars`)
        readyRef.current = true
        schedule()
      })
      .catch(() => {
        if (!disposed) {
          setNote('history fetch failed')
          schedule()
        }
      })

    return () => {
      disposed = true
      readyRef.current = false
      if (timer) clearTimeout(timer)
    }
  }, [symbol, exchange, interval])

  // Re-apply theme colors without re-creating the chart.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#a6adbb' : '#333',
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.06)' },
        horzLines: { color: isDark ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.06)' },
      },
    })
  }, [isDark])

  // Update the forming candle from each live tick, bucketed at the active
  // interval. The 5h30m IST offset is a whole multiple of 60/300/900s, so a
  // plain floor aligns 1m/5m/15m buckets with the broker's bars.
  const tick = data.get(`${exchange}:${symbol}`)?.data
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  useEffect(() => {
    const series = seriesRef.current
    if (!series || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return

    const parsed = ts ? Date.parse(ts) : Number.NaN
    const epochUtc = Number.isNaN(parsed) ? Math.floor(Date.now() / 1000) : Math.floor(parsed / 1000)
    const sec = intervalSecRef.current
    const bucket = Math.floor((epochUtc + IST_OFFSET) / sec) * sec
    const cur = currentBucketRef.current

    let bar: Candle
    if (cur == null || bucket > cur) {
      // New bar: open at the current price.
      bar = { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp }
      currentBucketRef.current = bucket
    } else if (bucket === cur) {
      // Same bar: refine high/low/close, keep the open.
      const prev = candlesRef.current.get(bucket)
      bar = prev
        ? {
            time: bucket,
            open: prev.open,
            high: Math.max(prev.high, ltp),
            low: Math.min(prev.low, ltp),
            close: ltp,
          }
        : { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp }
    } else {
      return // stale tick older than the current bar
    }
    candlesRef.current.set(bucket, bar)
    series.update({
      time: bar.time as UTCTimestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })
    setLast(ltp)
  }, [ltp, ts])

  const up = last != null && refPrice != null ? last >= refPrice : true

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <span
          className={`h-2 w-2 rounded-full ${isAuthenticated ? 'bg-green-500' : 'bg-zinc-400'}`}
          title={isAuthenticated ? 'streaming' : 'connecting'}
        />
        <span className="font-semibold">{symbol}</span>
        <span className="text-xs text-muted-foreground">{exchange}</span>
        <span className="ml-2 text-xs text-muted-foreground">{note}</span>
        <span
          className={`ml-auto font-semibold tabular-nums ${up ? 'text-green-500' : 'text-red-500'}`}
        >
          {last != null ? last.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-'}
        </span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onRemove} title="Remove">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div ref={containerRef} className="w-full" style={{ height: 340 }} />
    </div>
  )
}
