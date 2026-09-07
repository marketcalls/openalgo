/**
 * A price chart inside one agent answer.
 *
 * The engine is `openalgo-charts` 1.9.2, the one the `/trading` terminal draws
 * with, and it is driven the way the terminal drives it: `createChart` on a
 * host div, one price series taken from the shared `CHART_TYPES` map, a volume
 * histogram on a hidden overlay scale, and the app's own theme tokens through
 * `buildChartTheme`. Nothing here is a second way to drive the library, and
 * nothing here is a copy of a helper the terminal already owns.
 *
 * A chat chart is not the terminal, and four things follow from that.
 *
 * **It is read-only and it is inline.** No trade layer, no drawings, no
 * history paging, no keyboard shortcuts. The composer owns the keyboard on this
 * page, so `shortcuts: false` is not a preference: a chart that claims a chord
 * eats a keystroke the operator meant for their message. The hover zoom rail is
 * off for the same reason a compact card carries no chrome it does not need.
 * Panning, zooming and the crosshair stay, because reading a chart is the point.
 *
 * **It disposes its instance.** A thread grows and never reloads, so every
 * chart in it holds a canvas, a `ResizeObserver` and a frame loop until it is
 * destroyed. The effect creates exactly one instance and its cleanup destroys
 * it, including on the path where the component unmounts while the engine is
 * still being imported.
 *
 * **The engine is imported on demand.** A conversation that never asks for a
 * chart must not pay for the charting bundle, so the core, the theme bridge,
 * the chart-type map and the indicator tier are all dynamic imports inside the
 * effect, exactly as `terminal.ts` loads its own tiers.
 *
 * **A malformed frame renders a sentence, never an exception.** The spec
 * arrives as JSON off the wire, so it is parsed rather than trusted: every
 * field is read defensively, a bar missing a time or a close is dropped, and a
 * spec with nothing drawable renders a plain message. An indicator id this
 * build does not know is skipped rather than thrown, so a newer backend cannot
 * break a chart mid-answer. The imperative work sits inside try/catch because
 * an exception thrown from an effect unmounts the tree above it, which in this
 * component would take the whole conversation down with one bad frame.
 */

import type { Bar, Chart, SeriesStyle, SeriesType } from 'openalgo-charts'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { asNumber, asRecord, asText, parseBars } from './spec'

/** Most overlays one chart draws. The backend caps at six; this is the guard. */
const MAX_OVERLAYS = 8

/** Most notices shown under a chart before the rest are dropped. */
const MAX_NOTICES = 4

/**
 * Widest one bar may draw, in media px.
 *
 * `fitContent` spreads whatever it was given across the full width, so a
 * single candle becomes a block the width of the card and three candles become
 * three of them. Capping the spacing keeps a short range looking like a chart.
 */
const MAX_BAR_SPACING = 24

// ---------------------------------------------------------------------------
// Reading the frame
// ---------------------------------------------------------------------------
//
// `asRecord`, `asText`, `asNumber` and `parseBars` live in `./spec`: the
// instrument card reads the same four things out of its own payload, and a
// second copy of them here is how the two would drift.

/** One entry of the spec's `indicators` list. */
interface CandleOverlay {
  /** An `openalgo-charts` indicator id, e.g. `ema`. */
  id: string
  /** That indicator's own input keys, e.g. `{ length: 20 }`. */
  inputs: Record<string, unknown>
}

/** The drawable part of a `kind: "candles"` spec, after parsing. */
interface CandleChartSpec {
  bars: Bar[]
  chartType: string
  overlays: CandleOverlay[]
  symbol: string | null
  exchange: string | null
  interval: string | null
  timezone: string | null
  startDate: string | null
  endDate: string | null
  changePercent: number | null
  notices: string[]
}

type CandleParse =
  | { ok: true; spec: CandleChartSpec }
  | { ok: false; reason: 'unreadable' | 'empty' }

function parseOverlays(value: unknown): CandleOverlay[] {
  if (!Array.isArray(value)) return []
  const overlays: CandleOverlay[] = []
  for (const entry of value) {
    if (overlays.length >= MAX_OVERLAYS) break
    const row = asRecord(entry)
    const id = row ? asText(row.id) : null
    if (!row || !id) continue
    overlays.push({ id: id.toLowerCase(), inputs: asRecord(row.inputs) ?? {} })
  }
  return overlays
}

function parseNotices(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const notices: string[] = []
  for (const entry of value) {
    if (notices.length >= MAX_NOTICES) break
    const text = asText(entry)
    if (text) notices.push(text)
  }
  return notices
}

/**
 * Read a `kind: "candles"` spec.
 *
 * Args:
 *   value: The frame's `spec`, exactly as it came off the wire.
 *
 * Returns:
 *   The drawable spec, or why there is nothing to draw: `empty` when the tool
 *   answered with no candles, `unreadable` when the shape is not one this
 *   renderer knows.
 */
function parseCandleSpec(value: unknown): CandleParse {
  const root = asRecord(value)
  if (!root) return { ok: false, reason: 'unreadable' }
  const bars = parseBars(root.bars)
  if (bars.length === 0) {
    // An empty list is the tool saying the range held nothing. A list that had
    // entries and yielded no bar is a shape this renderer does not know, and
    // saying "no candles came back" about it would be wrong.
    const empty = Array.isArray(root.bars) && root.bars.length === 0
    return { ok: false, reason: empty ? 'empty' : 'unreadable' }
  }
  const summary = asRecord(root.summary)
  return {
    ok: true,
    spec: {
      bars,
      chartType: (asText(root.chart_type) ?? 'candlestick').toLowerCase(),
      overlays: parseOverlays(root.indicators),
      symbol: asText(root.symbol),
      exchange: asText(root.exchange),
      interval: asText(root.interval),
      timezone: asText(root.timezone),
      startDate: asText(root.start_date),
      endDate: asText(root.end_date),
      changePercent: summary ? asNumber(summary.change_percent) : null,
      notices: parseNotices(root.notices),
    },
  }
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

function overlayLabel(overlay: CandleOverlay): string {
  const values = Object.values(overlay.inputs)
    .filter(
      (input): input is number | string => typeof input === 'number' || typeof input === 'string'
    )
    .map((input) => String(input))
  return values.length ? `${overlay.id}(${values.join(', ')})` : overlay.id
}

function changeLabel(percent: number): string {
  const sign = percent > 0 ? '+' : ''
  return `${sign}${percent.toFixed(2)}%`
}

/** The screen-reader description of the whole figure. */
function chartLabel(spec: CandleChartSpec | null, title?: string, source?: string): string {
  const fallback = asText(title) ?? 'Price chart'
  if (!spec) return fallback
  const named = [spec.symbol, spec.exchange, spec.interval].filter(
    (part): part is string => part !== null
  )
  const head = named.length ? named.join(' ') : fallback
  const range = spec.startDate && spec.endDate ? ` from ${spec.startDate} to ${spec.endDate}` : ''
  const provenance = asText(source) ? `, data from ${asText(source)}` : ''
  return `${head} ${spec.chartType} chart, ${spec.bars.length} bars${range}${provenance}`
}

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export interface CandleVizProps {
  /**
   * The `spec` object of a `kind: "candles"` viz frame, unvalidated. It is read
   * defensively here, so an incomplete or malformed one renders a message
   * rather than throwing.
   *
   * Pass the frame's own object. Its identity is what decides whether the chart
   * is rebuilt, so a fresh object literal on every render of the thread would
   * tear the chart down and build it again on every streamed token.
   */
  spec: unknown
  /**
   * The frame's `title`, e.g. `RELIANCE NSE D`. Used only when the spec names
   * no symbol; the header is otherwise built from the spec itself, so this
   * component needs no chrome wrapped around it.
   */
  title?: string
  /** The frame's `source`, e.g. `history_service`. Reported to screen readers. */
  source?: string
  /**
   * How much of the card this draws.
   *
   * `figure`, the default, is the standalone block a `candles` frame renders
   * as: its own border, a caption naming the instrument, and a footer counting
   * the bars. `inline` is the same chart with all of that removed and a
   * shorter height, for a host that has already said what the instrument is.
   * The instrument card is that host, and this prop is why it drives no second
   * copy of the engine: the chart, its disposal, its theme and its handling of
   * a malformed payload are this component's, once.
   */
  variant?: 'figure' | 'inline'
  /** Extra classes on the figure, for a host that needs to adjust its margins. */
  className?: string
}

/**
 * Draw one price chart from a viz frame.
 *
 * Args:
 *   spec: The frame's `spec`.
 *   title: The frame's `title`.
 *   source: The frame's `source`.
 *   variant: `figure` for the standalone block, `inline` for a chart inside a
 *     host that supplies its own header.
 *   className: Extra classes on the figure.
 */
export function CandleViz({ spec, title, source, variant = 'figure', className }: CandleVizProps) {
  const inline = variant === 'inline'
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [failed, setFailed] = useState(false)

  const parsed = useMemo(() => parseCandleSpec(spec), [spec])
  const chartSpec = parsed.ok ? parsed.spec : null
  const label = useMemo(() => chartLabel(chartSpec, title, source), [chartSpec, title, source])

  useEffect(() => {
    const host = hostRef.current
    if (!chartSpec || !host) return

    let instance: Chart | null = null
    let disposed = false

    const build = async () => {
      // Every one of these is dynamic so a chat with no chart never loads the
      // charting engine. `chartTheme` and `chartTypes` both import the library
      // themselves, so importing either statically would pull it in anyway.
      const [core, theme, types, transform] = await Promise.all([
        import('openalgo-charts'),
        import('@/lib/trading/chartTheme'),
        import('@/lib/trading/chartTypes'),
        import('openalgo-charts/transform'),
      ])
      if (disposed) return

      // The library throws on a zone it does not recognise, and the frame's is
      // whatever the backend put there.
      const zone = chartSpec.timezone
      const timezone = zone && core.isValidTimezone(zone) ? zone : undefined

      const created = core.createChart(host, {
        theme: theme.buildChartTheme(mode, appMode),
        priceAxisWidth: 64,
        ariaLabel: label,
        // See the module docstring: the composer owns the keyboard, and a
        // compact card carries no hover rail.
        shortcuts: false,
        timeNavigator: false,
        ...(timezone ? { timezone } : {}),
      })
      instance = created
      // The component can unmount inside the awaits above, in which case the
      // cleanup has already run and this instance is the one nobody would
      // destroy.
      if (disposed) {
        created.destroy()
        instance = null
        return
      }

      // The brand mark, the same primitive and the same asset /trading mounts,
      // so a chart in the conversation is recognisably the platform's chart
      // rather than an anonymous one. It is smaller here than on the terminal:
      // a chat card is a fraction of the height, and a mark sized for a full
      // screen would sit on the candles instead of under them.
      //
      // The library has no watermark option; the mark is a primitive the host
      // owns and adds, which is why a chart that never adds one simply has
      // none. Pane 0, because volume is an overlay there and pane 1 only
      // exists once an indicator asks for one.
      const watermark = new core.LogoWatermark({
        // The glyph, not the app icon: that asset is a full-bleed plate whose
        // mark fills under half of it, so scaling it up scales the padding too.
        src: '/images/openalgo-glyph.svg',
        position: 'bottom-left',
        // Proportional to the chart it sits in: a mark sized for the standalone
        // block would occupy a sixth of an inline one.
        height: inline ? 15 : 22,
        padding: 3,
        margin: 8,
        opacity: 0.8,
        // Mark alone at rest; the wording unrolls to its right on hover, so it
        // names itself when looked at without occupying the corner always.
        label: 'OpenAlgo Charts',
        labelColor: mode === 'dark' || appMode === 'analyzer' ? '#e4e8f4' : '#3c4354',
        href: 'https://openalgo.in',
      })
      created.addPrimitive(watermark, 0)

      const definition = types.CHART_TYPES[chartSpec.chartType] ?? types.CHART_TYPES.candlestick
      // Only Heikin Ashi is reachable from the backend's list and it ignores
      // the box size, but the movement-driven types share one signature, so
      // one is computed rather than the map being read a second way.
      const bars = definition.transform
        ? transform.runTransform(definition.transform(boxSize(chartSpec.bars)), chartSpec.bars)
        : chartSpec.bars

      const style: SeriesStyle = definition.baseline
        ? { baseValue: bars.reduce((sum, bar) => sum + bar.close, 0) / bars.length }
        : {}
      const price = created.addSeries(definition.series as SeriesType, { style })
      price.setData(bars)

      // Volume rides an overlay scale inside the price pane, as it does on
      // `/trading`: it autoscales on its own and draws no second axis, so the
      // card keeps one price ladder. A transform carries its own volume, so a
      // Heikin Ashi chart still gets it and a type that drops it draws none.
      if (bars.some((bar) => typeof bar.volume === 'number' && bar.volume > 0)) {
        const volume = created.addSeries('histogram', {
          paneIndex: 0,
          priceScaleId: '',
          style: { color: theme.volumeColor(mode, appMode) },
          priceFormat: { type: 'volume' },
        })
        volume.setData(
          bars.map((bar) => ({
            time: bar.time,
            open: 0,
            high: bar.volume ?? 0,
            low: 0,
            close: bar.volume ?? 0,
          }))
        )
        volume.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 })
      }

      // The frame is a finished range rather than a live feed, so the whole of
      // it is the view. A flat range (one bar, or a high that equals its low)
      // is the engine's problem and it widens it to something drawable.
      created.fitContent()
      if (created.timeScale.barSpacing > MAX_BAR_SPACING) {
        created.timeScale.setBarSpacing(MAX_BAR_SPACING)
      }

      if (chartSpec.overlays.length === 0) return
      await import('openalgo-charts/indicators')
      if (disposed || instance !== created) return
      for (const overlay of chartSpec.overlays) {
        try {
          created.addIndicator(overlay.id, overlay.inputs)
        } catch {
          // The backend validates an indicator's shape, not its id against
          // this build's registry. Skipping an id this client does not know is
          // what stops a newer backend breaking the chart it asked for.
        }
      }
    }

    build().catch((error) => {
      // An exception out of an effect unmounts the tree above it, so it is
      // caught here and shown as a sentence in the card instead.
      console.error('[agent viz] candles', error)
      try {
        instance?.destroy()
      } catch {
        /* already gone */
      }
      instance = null
      if (!disposed) setFailed(true)
    })

    return () => {
      disposed = true
      try {
        instance?.destroy()
      } catch {
        /* already gone */
      }
      instance = null
      // `destroy` releases the engine's own listeners; clearing the host is
      // what guarantees a rebuild (a theme switch) starts on an empty div
      // rather than stacking a second canvas on the first.
      host.innerHTML = ''
    }
  }, [chartSpec, label, mode, appMode, inline])

  const heading = chartSpec?.symbol ?? asText(title) ?? 'Price chart'
  const overlayText = chartSpec?.overlays.map(overlayLabel).join(', ') ?? ''

  let body: ReactNode
  if (!parsed.ok) {
    body = (
      <p
        className={cn(
          'text-center text-[12px] text-muted-foreground',
          inline ? 'px-3 py-6' : 'px-3 py-8'
        )}
      >
        {parsed.reason === 'empty'
          ? 'No candles came back for this range, so there is nothing to draw.'
          : 'This chart could not be drawn: the price data did not arrive in a shape this page can read.'}
      </p>
    )
  } else if (failed) {
    body = (
      <p
        className={cn(
          'text-center text-[12px] text-muted-foreground',
          inline ? 'px-3 py-6' : 'px-3 py-8'
        )}
      >
        This chart could not be drawn. The answer above still stands.
      </p>
    )
  } else {
    // A definite height, because the engine measures its host. Compact enough
    // that several charts read as one thread rather than one page each.
    body = (
      <div
        ref={hostRef}
        className={cn('w-full', inline ? 'h-[150px] sm:h-[180px]' : 'h-[280px] sm:h-[340px]')}
      />
    )
  }

  // The host has already named the instrument and framed the block, so an
  // inline chart is the drawing and nothing else.
  if (inline) {
    return <div className={cn('min-w-0', className)}>{body}</div>
  }

  return (
    <figure
      className={cn(
        'my-3 min-w-0 overflow-hidden rounded-lg border border-border bg-card',
        className
      )}
      aria-label={label}
    >
      <figcaption className="flex items-center gap-2 border-b border-border bg-muted/50 px-3 py-1.5">
        <span className="truncate font-mono text-[11px] font-medium text-foreground">
          {heading}
        </span>
        {chartSpec?.exchange && (
          <span className="text-[11px] text-muted-foreground">{chartSpec.exchange}</span>
        )}
        {chartSpec?.interval && (
          <span className="text-[11px] text-muted-foreground">{chartSpec.interval}</span>
        )}
        {chartSpec?.changePercent != null && (
          <span
            className={cn(
              'ml-auto shrink-0 font-mono text-[11px] font-medium',
              chartSpec.changePercent < 0
                ? 'text-red-600 dark:text-red-400'
                : 'text-emerald-600 dark:text-emerald-500'
            )}
          >
            {changeLabel(chartSpec.changePercent)}
          </span>
        )}
      </figcaption>

      {body}

      {chartSpec && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
          <span>
            {chartSpec.bars.length} {chartSpec.bars.length === 1 ? 'bar' : 'bars'}
          </span>
          {chartSpec.startDate && chartSpec.endDate && (
            <span>
              {chartSpec.startDate} to {chartSpec.endDate}
            </span>
          )}
          {overlayText && <span className="truncate">{overlayText}</span>}
        </div>
      )}

      {chartSpec?.notices.map((notice) => (
        <p
          key={notice}
          className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground"
        >
          {notice}
        </p>
      ))}
    </figure>
  )
}

/**
 * A box size for the movement-driven chart types.
 *
 * Only Heikin Ashi can reach this from the agent's own vocabulary and it
 * ignores the value, so this is the safety net for a type added later: 0.15
 * percent of the last close, which is what the terminal's own box size works
 * out to before it snaps the result to the instrument's tick.
 */
function boxSize(bars: readonly Bar[]): number {
  const last = bars.length ? bars[bars.length - 1].close : 0
  return Math.max(Math.abs(last) * 0.0015, 0.01)
}
