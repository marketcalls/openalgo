/**
 * ScalpChart - a self-contained live candlestick + volume chart for the
 * scalping terminal.
 *
 * Given a symbol/exchange/interval it:
 *   - loads history from /scalping/api/history (1m=1d, 5m=3d, 15m=9d lookback),
 *   - draws candles + a volume histogram with a TradingView-style OHLC legend,
 *   - streams the forming candle live via the shared useMarketData feed, and
 *   - reconciles completed bars to the broker's official OHLC on a staggered
 *     20-30s timer (so multiple charts never hit the API at the same instant).
 *
 * Works for any exchange (options/futures/equity/indices). Index symbols carry
 * volume 0. Uses the bundled lightweight-charts v5 (no CDN).
 */

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { priceDecimals } from '@/lib/scalpingPrice'
import { useThemeStore } from '@/stores/themeStore'

// Matches the IST shift the backend bakes into bar times so live bars line up
// with history bars. 5h30m = 19800s, a whole multiple of 60/300/900s.
const IST_OFFSET = 19800
const INTERVAL_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

const UP = '#26a69a'
const DOWN = '#ef5350'
const VOL_UP = 'rgba(38,166,154,0.45)'
const VOL_DOWN = 'rgba(239,83,80,0.45)'

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

function fmtPrice(n: number, decimals = 2): string {
  return n.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}
function fmtVol(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(2)}K`
  return String(Math.round(n))
}

export function ScalpChart({
  symbol,
  exchange,
  interval,
  title,
}: {
  symbol: string
  exchange: string
  interval: string
  title?: string
}) {
  const { mode } = useThemeStore()
  const isDark = mode === 'dark'

  const containerRef = useRef<HTMLDivElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const renderLegendRef = useRef<(time?: number) => void>(() => {})
  const colorsRef = useRef({ title: '#d6dde6', muted: '#8a97a5' })

  // Authoritative model: bucket time -> candle. Completed bars are reconciled
  // from broker history; the current bucket is built live from ticks.
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const sortedRef = useRef<Candle[]>([])
  const idxByTimeRef = useRef<Map<number, number>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef<number>(INTERVAL_SEC[interval] ?? 60)
  const intervalRef = useRef<string>(interval)
  const barStartVolRef = useRef<number | null>(null)
  const readyRef = useRef(false)

  const [status, setStatus] = useState('')

  const enabled = !!(symbol && exchange)
  const { data } = useMarketData({
    symbols: enabled ? [{ symbol, exchange }] : [],
    mode: 'Quote',
    enabled,
    autoReconnect: true,
  })

  // Create the chart once per symbol/exchange (candles + volume + legend).
  // isDark is used only for the initial colors; theme changes are applied by the
  // separate re-theme effect below, so it is intentionally not a dependency.
  // biome-ignore lint/correctness/useExhaustiveDependencies: isDark excluded; theme handled by the re-theme effect
  useEffect(() => {
    const container = containerRef.current
    if (!container || !enabled) return

    // Currency derivatives (CDS/BCD) price to 4 decimals; everything else to 2.
    const decimals = priceDecimals(exchange)

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: colorsRef.current.muted,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
        horzLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
      },
      rightPriceScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
      timeScale: {
        borderColor: isDark ? '#1b2330' : '#e2e8f0',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: 'price', precision: decimals, minMove: 10 ** -decimals },
    })
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    chartRef.current = chart
    candleRef.current = candle
    volRef.current = vol

    // OHLC legend overlay: hovered bar, or the last bar when not hovering.
    const renderLegend = (time?: number) => {
      const el = legendRef.current
      const arr = sortedRef.current
      if (!el) return
      if (!arr.length) {
        el.innerHTML = ''
        return
      }
      let idx = arr.length - 1
      if (time != null) {
        const i = idxByTimeRef.current.get(time)
        if (i != null) idx = i
      }
      const bar = arr[idx]
      const ref = idx > 0 ? arr[idx - 1].close : bar.open
      const chg = bar.close - ref
      const pct = ref ? (chg / ref) * 100 : 0
      const col = chg >= 0 ? UP : DOWN
      const sign = chg >= 0 ? '+' : ''
      const { title: titleColor, muted } = colorsRef.current
      el.innerHTML =
        `<div style="color:${titleColor};font-weight:600">${symbol} ` +
        `<span style="color:${muted};font-weight:500">· ${intervalRef.current} · ${exchange}</span></div>` +
        `<div style="color:${col};margin-top:1px">O${fmtPrice(bar.open, decimals)} H${fmtPrice(bar.high, decimals)} ` +
        `L${fmtPrice(bar.low, decimals)} C${fmtPrice(bar.close, decimals)} ${sign}${fmtPrice(chg, decimals)} (${sign}${pct.toFixed(2)}%)</div>` +
        `<div style="color:${muted};margin-top:1px">Volume <span style="color:${col}">${fmtVol(bar.volume)}</span></div>`
    }
    renderLegendRef.current = renderLegend
    chart.subscribeCrosshairMove((param) => {
      renderLegend(typeof param.time === 'number' ? param.time : undefined)
    })

    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volRef.current = null
    }
  }, [symbol, exchange, enabled])

  // Load history for the selected interval and run the reconcile loop. Re-runs
  // on timeframe change (instant flip; chart instance reused).
  useEffect(() => {
    const chart = chartRef.current
    const candle = candleRef.current
    const vol = volRef.current
    if (!chart || !candle || !vol || !enabled) return
    let disposed = false
    let inflight = false
    let timer: ReturnType<typeof setTimeout> | null = null

    candlesRef.current = new Map()
    sortedRef.current = []
    idxByTimeRef.current = new Map()
    currentBucketRef.current = null
    barStartVolRef.current = null
    intervalSecRef.current = INTERVAL_SEC[interval] ?? 60
    intervalRef.current = interval
    readyRef.current = false
    setStatus('loading...')

    const applyModel = (preserveRange: boolean) => {
      const arr = Array.from(candlesRef.current.values()).sort((a, b) => a.time - b.time)
      sortedRef.current = arr
      const idxMap = new Map<number, number>()
      arr.forEach((k, i) => idxMap.set(k.time, i))
      idxByTimeRef.current = idxMap

      const ts = chart.timeScale()
      const range = preserveRange ? ts.getVisibleLogicalRange() : null
      candle.setData(
        arr.map((k) => ({ time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close }))
      )
      vol.setData(
        arr.map((k) => ({
          time: k.time as UTCTimestamp,
          value: k.volume,
          color: k.close >= k.open ? VOL_UP : VOL_DOWN,
        }))
      )
      if (range) {
        try {
          ts.setVisibleLogicalRange(range)
        } catch {
          /* range no longer valid */
        }
      } else {
        ts.fitContent()
      }
      renderLegendRef.current()
    }

    const reconcile = async () => {
      if (disposed || inflight) return
      inflight = true
      try {
        const d = await scalpingApi.getHistory(
          symbol,
          exchange,
          interval,
          tradingDateRef.current || undefined
        )
        if (disposed || d.status !== 'success') return
        const fetched = d.candles || []
        if (!fetched.length) return
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
            prev.close !== k.close ||
            prev.volume !== k.volume
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

    const schedule = () => {
      const delay = 20000 + Math.random() * 10000
      timer = setTimeout(async () => {
        await reconcile()
        if (!disposed) schedule()
      }, delay)
    }

    scalpingApi
      .getHistory(symbol, exchange, interval)
      .then((d) => {
        if (disposed) return
        if (d.status !== 'success') {
          setStatus(`error: ${d.message || 'history failed'}`)
          schedule()
          return
        }
        const candles = d.candles || []
        tradingDateRef.current = d.date || null
        if (!candles.length) {
          // No broker history (e.g. TradeSmart serves none for the CDS segment).
          // Build the chart live from the websocket feed instead of stalling on
          // a permanent "no history" — readyRef lets the tick effect form bars.
          readyRef.current = true
          currentBucketRef.current = null
          setStatus('waiting for live ticks…')
          schedule()
          return
        }
        candlesRef.current = new Map(candles.map((k) => [k.time, { ...k }]))
        applyModel(false)
        currentBucketRef.current = candles[candles.length - 1].time
        setStatus('')
        readyRef.current = true
        schedule()
      })
      .catch(() => {
        if (!disposed) {
          setStatus('history fetch failed')
          schedule()
        }
      })

    return () => {
      disposed = true
      readyRef.current = false
      if (timer) clearTimeout(timer)
    }
  }, [symbol, exchange, interval, enabled])

  // Re-theme the chart and legend without recreating it.
  useEffect(() => {
    colorsRef.current = isDark
      ? { title: '#d6dde6', muted: '#8a97a5' }
      : { title: '#0f172a', muted: '#64748b' }
    const chart = chartRef.current
    if (chart) {
      chart.applyOptions({
        layout: { textColor: colorsRef.current.muted },
        grid: {
          vertLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
          horzLines: { color: isDark ? 'rgba(120,130,145,0.06)' : 'rgba(0,0,0,0.05)' },
        },
        rightPriceScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
        timeScale: { borderColor: isDark ? '#1b2330' : '#e2e8f0' },
      })
    }
    renderLegendRef.current()
  }, [isDark])

  // Update the forming candle (and its volume) from each live tick.
  const tick = data.get(`${exchange}:${symbol}`)?.data
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  const tickVol = typeof tick?.volume === 'number' ? tick.volume : null
  useEffect(() => {
    const candle = candleRef.current
    const vol = volRef.current
    if (!candle || !vol || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return

    const parsed = ts ? Date.parse(ts) : Number.NaN
    const epochUtc = Number.isNaN(parsed) ? Math.floor(Date.now() / 1000) : Math.floor(parsed / 1000)
    const sec = intervalSecRef.current
    const bucket = Math.floor((epochUtc + IST_OFFSET) / sec) * sec
    const cur = currentBucketRef.current

    let bar: Candle
    let isNew = false
    if (cur == null || bucket > cur) {
      isNew = true
      barStartVolRef.current = tickVol
      bar = { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp, volume: 0 }
      currentBucketRef.current = bucket
    } else if (bucket === cur) {
      const prev = candlesRef.current.get(bucket)
      const v =
        tickVol != null && barStartVolRef.current != null
          ? Math.max(0, tickVol - barStartVolRef.current)
          : (prev?.volume ?? 0)
      bar = prev
        ? {
            time: bucket,
            open: prev.open,
            high: Math.max(prev.high, ltp),
            low: Math.min(prev.low, ltp),
            close: ltp,
            volume: v,
          }
        : { time: bucket, open: ltp, high: ltp, low: ltp, close: ltp, volume: v }
    } else {
      return // stale tick older than the current bar
    }

    candlesRef.current.set(bucket, bar)
    const arr = sortedRef.current
    if (isNew) {
      arr.push(bar)
      idxByTimeRef.current.set(bucket, arr.length - 1)
    } else if (arr.length) {
      arr[arr.length - 1] = bar
    }

    const color = bar.close >= bar.open ? VOL_UP : VOL_DOWN
    candle.update({ time: bar.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close })
    vol.update({ time: bar.time as UTCTimestamp, value: bar.volume, color })
    renderLegendRef.current()
    // Clear the live-only "waiting for ticks" placeholder once a bar exists.
    setStatus((s) => (s ? '' : s))
  }, [ltp, ts, tickVol])

  if (!enabled) {
    return (
      <div className="flex h-full w-full items-center justify-center rounded-lg border bg-card text-xs text-muted-foreground">
        {title ? `${title} — not selected` : 'No instrument'}
      </div>
    )
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border bg-card">
      <div ref={containerRef} className="absolute inset-0" />
      <div
        ref={legendRef}
        className="pointer-events-none absolute left-2.5 top-2 z-10 font-mono text-[11px] leading-tight"
      />
      {status && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          {status}
        </div>
      )}
    </div>
  )
}
