/**
 * ScalpChart - a self-contained live candlestick + volume chart for the
 * scalping terminal.
 *
 * Given a symbol/exchange/interval it:
 *   - loads history from /scalping/api/history (1m=1d, 5m=3d, 15m=9d lookback),
 *   - draws candles + a volume histogram with an OHLC legend,
 *   - streams the forming candle live via the shared useMarketData feed, and
 *   - reconciles completed bars to the broker's official OHLC on a staggered
 *     20-30s timer (so multiple charts never hit the API at the same instant).
 *
 * Works for any exchange (options/futures/equity/indices). Index symbols carry
 * volume 0.
 *
 * Drawn by openalgo-charts, the engine /trading uses, driven the way the other
 * read-only charts drive it (`CandleViz`): `createChart` on a host div, the
 * app's theme tokens through `buildChartTheme`, and volume on the price pane's
 * hidden overlay scale, coloured by direction as /trading colours it. The
 * engine also supplies the countdown to the candle close. The legend stays this
 * component's own DOM overlay, as /trading keeps its own: the engine's status
 * line belongs to its widget tier, which this chart does not use.
 *
 * Two things differ from /trading because this chart sits inside an order
 * entry screen:
 *   - The engine's keyboard shortcuts are off. The scalper places orders on
 *     the arrow keys from a window listener, and a chart that claimed a chord
 *     would pan or swallow a keystroke the trader meant as an order.
 *   - No trade layer, drawings or indicators. Orders are placed from the
 *     scalper's own controls, so the chart only reads.
 */

import { type Chart, compactVolume, createChart, type SeriesApi } from 'openalgo-charts'
import { useEffect, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { useMarketData } from '@/hooks/useMarketData'
import { priceDecimals } from '@/lib/scalpingPrice'
import { buildChartTheme, quietVolumeStyle } from '@/lib/trading/chartTheme'
import { buildChartLegend, legendHtml } from '@/lib/trading/legend'
import { volumePoint } from '@/lib/trading/volumeSettings'
import { useThemeStore } from '@/stores/themeStore'

// Matches the IST shift the backend bakes into bar times so live bars line up
// with history bars. 5h30m = 19800s, a whole multiple of 60/300/900s.
//
// The bucket model below keeps that shifted base. The engine wants real UTC
// seconds and shows them in IST itself (its default zone), so the shift comes
// off at the one place a bar is handed to the chart. Handing it shifted times
// would label every candle 5h30m late and push the countdown out by as much.
const IST_OFFSET = 19800
const INTERVAL_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 }

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// Indices trade no volume of their own (the backend sends 0), so their charts
// draw no volume bars and no volume readout, as /trading treats its quote-only
// exchanges. Every one of those ends in `_INDEX`.
const hasVolume = (exchange: string) => !exchange.endsWith('_INDEX')

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
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)

  const containerRef = useRef<HTMLDivElement | null>(null)
  const legendRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<Chart | null>(null)
  const candleRef = useRef<SeriesApi | null>(null)
  const volRef = useRef<SeriesApi | null>(null)
  const renderLegendRef = useRef<(time?: number) => void>(() => {})
  // The bar under the pointer, in the model's time base, or null when the
  // pointer is off the chart. Kept so a live tick redraws the legend for the
  // bar being read rather than snapping it to the latest one.
  const hoveredTimeRef = useRef<number | null>(null)
  const intervalRef = useRef<string>(interval)

  // Authoritative model: bucket time -> candle. Completed bars are reconciled
  // from broker history; the current bucket is built live from ticks.
  const candlesRef = useRef<Map<number, Candle>>(new Map())
  const sortedRef = useRef<Candle[]>([])
  const idxByTimeRef = useRef<Map<number, number>>(new Map())
  const currentBucketRef = useRef<number | null>(null)
  const tradingDateRef = useRef<string | null>(null)
  const intervalSecRef = useRef<number>(INTERVAL_SEC[interval] ?? 60)
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

  // Volume as /trading draws it by default: the candle pair, half way to the
  // background. Read from the chart's live theme, so a theme switch recolours it.
  const volumeBar = (k: Candle, prevClose: number | undefined) => {
    const theme = chartRef.current?.theme()
    const style = theme
      ? quietVolumeStyle({ upColor: theme.upColor, downColor: theme.downColor }, theme.background)
      : {}
    return volumePoint(toBar(k), prevClose, k.volume, style, true)
  }

  // Create the chart once per symbol/exchange (candles + volume). The theme is
  // read for the initial colours only; theme changes are applied by the
  // separate re-theme effect below, so it is intentionally not a dependency.
  // biome-ignore lint/correctness/useExhaustiveDependencies: theme excluded; handled by the re-theme effect
  useEffect(() => {
    const container = containerRef.current
    if (!container || !enabled) return

    // Currency derivatives (CDS/BCD) price to 4 decimals; everything else to 2.
    const decimals = priceDecimals(exchange)

    const chart = createChart(container, {
      theme: buildChartTheme(mode, appMode),
      // See the module docstring: the arrow keys belong to order entry.
      shortcuts: false,
      // The hover zoom rail is chrome a 340px chart has no room for.
      timeNavigator: false,
      // The countdown to the forming candle's close, under the last price, as
      // /trading shows it. Off in the engine by default; a live chart is the
      // case it is for.
      axisChrome: { barCountdown: true },
      ariaLabel: `${symbol} ${exchange} price chart`,
    })
    chart.setDataContext({ symbol, exchange, interval })
    const candle = chart.addSeries('candlestick', {
      priceFormat: { type: 'price', precision: decimals, minMove: 10 ** -decimals },
    })
    // '' is the hidden overlay scale: the histogram sits under the candles and
    // draws no axis of its own, pinned to the bottom fifth.
    const vol = chart.addSeries('histogram', {
      paneIndex: 0,
      priceScaleId: '',
      priceFormat: { type: 'volume' },
    })
    vol.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 })
    if (!hasVolume(exchange)) vol.applyOptions({ visible: false })

    chartRef.current = chart
    candleRef.current = candle
    volRef.current = vol

    // OHLC legend overlay: hovered bar, or the last bar when not hovering.
    // `time` is in the model's IST-shifted base. Built and rendered by the same
    // two functions as the /trading legend, so the two read alike.
    const renderLegend = (time = hoveredTimeRef.current ?? undefined) => {
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
      const runs = buildChartLegend({
        symbol,
        interval: intervalRef.current,
        exchange,
        lotsize: null,
        bar: hasVolume(exchange) ? bar : { ...bar, volume: undefined },
        prevClose: idx > 0 ? arr[idx - 1].close : null,
        fmt: (n) => n.toFixed(decimals),
        fmtVolume: compactVolume,
      })
      // The volume readout is a show/hide switch on /trading. The scalper has
      // no such switch, so it renders as plain text rather than as a control
      // that does nothing.
      el.innerHTML = legendHtml(runs.map((run) => ({ ...run, action: undefined })))
    }
    renderLegendRef.current = renderLegend
    // The engine reports the hovered bar in real UTC seconds; the model is keyed
    // in the shifted base, so the shift goes back on for the lookup.
    const offCrosshair = chart.subscribeCrosshairMove((e) => {
      hoveredTimeRef.current = e.time == null ? null : e.time + IST_OFFSET
      renderLegend()
    })

    return () => {
      offCrosshair()
      hoveredTimeRef.current = null
      chart.destroy()
      // `destroy` releases the engine's listeners; clearing the host is what
      // guarantees the next symbol starts on an empty div rather than stacking
      // a second canvas on the first.
      container.innerHTML = ''
      chartRef.current = null
      candleRef.current = null
      volRef.current = null
    }
  }, [symbol, exchange, enabled])

  // Load history for the selected interval and run the reconcile loop. Re-runs
  // on timeframe change (instant flip; chart instance reused).
  // biome-ignore lint/correctness/useExhaustiveDependencies: volumeBar reads refs only
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
    chart.setDataContext({ symbol, exchange, interval })
    candle.setData([])
    vol.setData([])
    setStatus('loading...')

    const applyModel = (preserveRange: boolean) => {
      const arr = Array.from(candlesRef.current.values()).sort((a, b) => a.time - b.time)
      sortedRef.current = arr
      const idxMap = new Map<number, number>()
      arr.forEach((k, i) => idxMap.set(k.time, i))
      idxByTimeRef.current = idxMap

      const range = preserveRange ? chart.getVisibleLogicalRange() : null
      candle.setData(arr.map(toBar))
      vol.setData(arr.map((k, i) => volumeBar(k, arr[i - 1]?.close)))
      if (range) {
        try {
          chart.setVisibleLogicalRange(range)
        } catch {
          /* range no longer valid */
        }
      } else {
        chart.fitContent()
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

  // Re-theme the chart without recreating it, and recolour the volume, whose
  // colours are baked into each bar. The legend inherits the page's text colour,
  // so it follows the theme on its own.
  // biome-ignore lint/correctness/useExhaustiveDependencies: volumeBar reads refs only
  useEffect(() => {
    const chart = chartRef.current
    const vol = volRef.current
    if (!chart || !vol) return
    chart.setTheme(buildChartTheme(mode, appMode))
    const arr = sortedRef.current
    vol.setData(arr.map((k, i) => volumeBar(k, arr[i - 1]?.close)))
  }, [mode, appMode])

  // Update the forming candle (and its volume) from each live tick.
  const tick = data.get(`${exchange}:${symbol}`)?.data
  const ltp = tick?.ltp
  const ts = tick?.timestamp
  const tickVol = typeof tick?.volume === 'number' ? tick.volume : null
  // biome-ignore lint/correctness/useExhaustiveDependencies: volumeBar reads refs only
  useEffect(() => {
    const candle = candleRef.current
    const vol = volRef.current
    if (!candle || !vol || !readyRef.current || ltp == null || !Number.isFinite(ltp)) return

    const parsed = ts ? Date.parse(ts) : Number.NaN
    const epochUtc = Number.isNaN(parsed)
      ? Math.floor(Date.now() / 1000)
      : Math.floor(parsed / 1000)
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

    candle.update(toBar(bar))
    vol.update(volumeBar(bar, arr[arr.length - 2]?.close))
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

  // The engine tracks its own container size, so there is no ResizeObserver
  // here; the absolute fill gives it a box with a real height to measure.
  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border bg-card">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-3 top-1.5 z-10">
        <div ref={legendRef} className="text-xs font-medium text-foreground" />
      </div>
      {status && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          {status}
        </div>
      )}
    </div>
  )
}

/** A model candle as the engine takes it: real UTC seconds, volume included. */
function toBar(k: Candle) {
  return {
    time: k.time - IST_OFFSET,
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close,
    volume: k.volume,
  }
}
