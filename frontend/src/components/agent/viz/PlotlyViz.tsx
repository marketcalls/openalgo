/**
 * Option analytics in the conversation, rendered with Plotly.
 *
 * This is the `kind: "plotly"` branch of the `viz` frame: open interest by
 * strike, net gamma exposure, and the implied volatility surface. The producer
 * is a tool that called a service, so every number here came from the platform
 * and none of it was typed by the model. The renderer's job is presentation
 * only, and it must never invent a series, a label or an axis title.
 *
 * Why this file and not the chart library
 * ---------------------------------------
 *
 * Plotly is already the engine behind `/strategybuilder` and twelve option
 * analytics pages, so an OI chart in the chat reads as the same product rather
 * than as a second charting stack. `PayoffChart.tsx` is the house pattern this
 * follows: assemble data, layout and config in a `useMemo`, stay
 * presentational, and take the computed result as a prop.
 *
 * The two bundles are separate
 * ----------------------------
 *
 * `lib/Plot2D` carries scatter, bar and candlestick; `lib/Plot3D` carries
 * surfaces, and it is much larger. Both are lazy so a conversation with no
 * chart in it pays for neither, and a bar chart never pulls in the 3D build.
 * `engine` on the spec picks one, but a spec whose traces are 3D is rendered
 * with the 3D build whatever it declared: the 2D build has no `surface` type
 * and would draw an empty box.
 *
 * Colour is split by who owns the meaning
 * ---------------------------------------
 *
 * The producer sets only meaning-bearing colour, calls against puts, positive
 * gamma against negative, and deliberately sends no paper, plot, font or grid
 * colour at all. Those are the reader's, so the theme is merged underneath the
 * spec: every key the producer sent wins, and everything it left out comes
 * from the app's light and dark palettes. A future producer that does set a
 * colour therefore keeps it without this file changing.
 *
 * Nothing here may throw
 * ----------------------
 *
 * A malformed or empty spec renders as one line of plain text, and an error
 * raised inside Plotly is caught by a boundary that renders the same line. A
 * chart that fails is a missing chart, never a broken conversation.
 */

import {
  Component,
  type ComponentType,
  type CSSProperties,
  lazy,
  type ReactNode,
  Suspense,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'

/** A Plotly object literal: traces, layout and config are all this shape. */
type PlotlyRecord = Record<string, unknown>

/**
 * The props of a `react-plotly.js` component.
 *
 * `lib/Plot2D` and `lib/Plot3D` are built by an untyped CommonJS factory, so
 * their default export carries no signature. Declaring the three props this
 * file passes is what keeps the call site type-checked instead of implicitly
 * unchecked.
 */
interface PlotComponentProps {
  data: PlotlyRecord[]
  layout: PlotlyRecord
  config: PlotlyRecord
  style?: CSSProperties
}

type PlotModule = { default: ComponentType<PlotComponentProps> }

// Both builds are loaded on demand. A static import of either would put the
// whole of Plotly into the chat chunk for every conversation, charted or not.
const Plot2D = lazy(() => import('@/lib/Plot2D') as unknown as Promise<PlotModule>)
const Plot3D = lazy(() => import('@/lib/Plot3D') as unknown as Promise<PlotModule>)

// ---------------------------------------------------------------------------
// The wire shape
// ---------------------------------------------------------------------------

/** Which Plotly build a spec needs. The frame states it; the traces confirm it. */
export type PlotlyVizEngine = '2d' | '3d'

/**
 * The `spec` object of a `viz` frame whose `kind` is `plotly`.
 *
 * Every field is optional and typed loosely on purpose. The spec arrives over
 * SSE and is validated at runtime rather than trusted, so this interface
 * documents the shape without asserting it.
 */
export interface PlotlyVizSpec {
  /** `2d` for bar and scatter traces, `3d` for surfaces. */
  engine?: PlotlyVizEngine
  /** Plotly traces, passed through verbatim. */
  data?: unknown
  /** Plotly layout, carrying no colours. The theme is merged underneath it. */
  layout?: unknown
  /** Plotly config. The mode bar is the renderer's, see `buildConfig`. */
  config?: unknown
  /** Volatility surface only: expiry labels parallel to the trace's `y`. */
  expiry_labels?: unknown
}

export interface PlotlyVizProps {
  /**
   * The frame's `spec`, exactly as it arrived.
   *
   * Typed `unknown` rather than `PlotlyVizSpec` deliberately: this component
   * validates before it renders, so the caller passes the frame through
   * without asserting anything about a payload neither of them parsed.
   */
  spec: unknown
  /** The frame's `title`. May be empty. */
  title?: string
  /** The frame's `source`, the service the numbers came from. May be empty. */
  source?: string
  /** Plot height in pixels. Defaults by engine: 340 for 2D, 420 for 3D. */
  height?: number
  /**
   * Render the visible title and provenance row. Pass `false` when the caller
   * draws its own chrome around the frame; the heading is still emitted for
   * screen readers.
   */
  showHeader?: boolean
  /** Extra classes on the outer shell. */
  className?: string
}

// ---------------------------------------------------------------------------
// Plain-object helpers, shared by every branch below
// ---------------------------------------------------------------------------

/** Keys that must never be written through assignment. See `mergeDeep`. */
const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype'])

function isRecord(value: unknown): value is PlotlyRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function recordAt(source: PlotlyRecord, key: string): PlotlyRecord {
  const value = source[key]
  return isRecord(value) ? value : {}
}

function numericArray(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  return value.every((item) => typeof item === 'number' && Number.isFinite(item))
    ? (value as number[])
    : null
}

function stringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  return value.every((item) => typeof item === 'string') ? (value as string[]) : null
}

/**
 * Merge `override` onto `base`, recursing into plain objects only.
 *
 * Arrays are replaced whole, which is what `shapes`, `annotations`, `tickvals`
 * and every data array want. This one function is why no axis, legend or
 * hover-label needs a special case: the themed base supplies colour, the spec
 * supplies everything else, and the spec always wins on a conflict.
 *
 * Args:
 *   base: The themed defaults.
 *   override: The producer's own values.
 */
function mergeDeep(base: PlotlyRecord, override: PlotlyRecord): PlotlyRecord {
  const merged: PlotlyRecord = { ...base }
  for (const key of Object.keys(override)) {
    // A JSON payload can carry a literal "__proto__" key, and assigning it
    // walks the prototype chain into Object.prototype's setter.
    if (UNSAFE_KEYS.has(key)) continue
    const current = merged[key]
    const next = override[key]
    merged[key] = isRecord(current) && isRecord(next) ? mergeDeep(current, next) : next
  }
  return merged
}

/** A Plotly axis title, which may be a bare string or `{ text }`. */
function axisTitle(axis: PlotlyRecord, fallback: string): string {
  const title = axis.title
  if (typeof title === 'string') return title
  if (isRecord(title) && typeof title.text === 'string') return title.text
  return fallback
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Trace types the 2D build does not carry. */
const THREE_D_TRACE_TYPES = new Set([
  'surface',
  'scatter3d',
  'mesh3d',
  'isosurface',
  'volume',
  'cone',
  'streamtube',
])

interface ParsedSpec {
  engine: PlotlyVizEngine
  traces: PlotlyRecord[]
  layout: PlotlyRecord
  config: PlotlyRecord
  expiryLabels: string[] | null
}

type ParseResult = { ok: true; spec: ParsedSpec } | { ok: false; reason: string }

function parseSpec(raw: unknown): ParseResult {
  if (!isRecord(raw)) return { ok: false, reason: 'This chart arrived without a specification.' }

  const data = raw.data
  if (!Array.isArray(data)) return { ok: false, reason: 'This chart arrived with no data.' }

  const traces = data.filter(isRecord)
  if (traces.length === 0) return { ok: false, reason: 'This chart arrived with no data.' }

  const declared = raw.engine === '3d' || raw.engine === '2d' ? raw.engine : null
  const looks3d = traces.some(
    (trace) => typeof trace.type === 'string' && THREE_D_TRACE_TYPES.has(trace.type)
  )

  return {
    ok: true,
    spec: {
      // A declared 2D engine carrying a surface is honoured as 3D: the 2D
      // build has no such trace type and would draw an empty box.
      engine: declared === '3d' || looks3d ? '3d' : '2d',
      traces,
      layout: isRecord(raw.layout) ? raw.layout : {},
      config: isRecord(raw.config) ? raw.config : {},
      expiryLabels: stringArray(raw.expiry_labels),
    },
  }
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

interface VizTheme {
  text: string
  muted: string
  grid: string
  plotBg: string
  hoverBg: string
  hoverBorder: string
  shapeLine: string
  colorscale: string
}

function useVizTheme(): VizTheme {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  // Analyzer mode is the dark purple theme, so it reads as dark regardless of
  // the light and dark setting. PayoffChart and CodeArtifact do the same.
  const isDark = mode === 'dark' || isAnalyzer

  return useMemo(
    () => ({
      text: isDark ? '#e2e8f0' : '#1e293b',
      muted: isDark ? '#94a3b8' : '#64748b',
      grid: isDark ? 'rgba(148,163,184,0.18)' : 'rgba(15,23,42,0.08)',
      // The paper stays transparent so the plot sits on the card colour
      // whatever the active theme token resolves to. Only the plotting area
      // is tinted, which is what separates it from the surrounding text.
      plotBg: isDark ? 'rgba(148,163,184,0.06)' : 'rgba(15,23,42,0.03)',
      hoverBg: isDark ? (isAnalyzer ? '#2d2545' : '#0f172a') : '#ffffff',
      hoverBorder: isDark ? (isAnalyzer ? '#7c3aed' : '#475569') : '#e2e8f0',
      shapeLine: isDark ? 'rgba(226,232,240,0.55)' : 'rgba(15,23,42,0.45)',
      // Matches /volsurface, which is the page this surface came from.
      colorscale: isAnalyzer ? 'Plasma' : isDark ? 'Viridis' : 'YlOrRd',
    }),
    [isDark, isAnalyzer]
  )
}

// ---------------------------------------------------------------------------
// Figure assembly
// ---------------------------------------------------------------------------

/**
 * Fill in colour the producer left out, on traces only.
 *
 * A surface arrives without a colorscale because the palette belongs to the
 * theme. Bar and scatter traces arrive with their colours already set, because
 * a call is red and a put is green wherever they are drawn, so they are
 * returned untouched.
 */
function themeTraces(traces: PlotlyRecord[], theme: VizTheme): PlotlyRecord[] {
  return traces.map((trace) => {
    if (trace.type !== 'surface') return trace
    const themed: PlotlyRecord = { ...trace }
    if (themed.colorscale === undefined) themed.colorscale = theme.colorscale
    themed.colorbar = mergeDeep(
      {
        tickfont: { color: theme.text, size: 10 },
        title: { font: { color: theme.text, size: 11 } },
        outlinewidth: 0,
        len: 0.6,
      },
      recordAt(themed, 'colorbar')
    )
    return themed
  })
}

/**
 * Give the surface's expiry axis its labels and its hover readout.
 *
 * `y` is days to expiry, which is what makes the surface's spacing honest, and
 * `expiry_labels` is the human reading of the same values. Both are used: the
 * axis ticks show the label, the spacing stays proportional to the number.
 * Hover text is built from whatever axis titles the producer supplied, so this
 * never asserts that an axis means strike or implied volatility.
 */
function labelSurfaceExpiries(
  traces: PlotlyRecord[],
  layout: PlotlyRecord,
  labels: string[]
): { traces: PlotlyRecord[]; sceneOverride: PlotlyRecord } {
  const surfaceIndex = traces.findIndex((trace) => trace.type === 'surface')
  if (surfaceIndex === -1) return { traces, sceneOverride: {} }

  const surface = traces[surfaceIndex]
  const y = numericArray(surface.y)
  if (!y || y.length !== labels.length) return { traces, sceneOverride: {} }

  const sceneOverride: PlotlyRecord = {
    yaxis: { tickmode: 'array', tickvals: y, ticktext: labels },
  }

  // Only when the producer left the hover alone. A supplied hovertemplate is
  // its own decision and is not second-guessed.
  const z = surface.z
  if (
    surface.customdata !== undefined ||
    surface.hovertemplate !== undefined ||
    !Array.isArray(z) ||
    z.length !== labels.length
  ) {
    return { traces, sceneOverride }
  }

  const columns = numericArray(surface.x)?.length ?? 0
  if (columns === 0) return { traces, sceneOverride }

  const scene = recordAt(layout, 'scene')
  const xLabel = axisTitle(recordAt(scene, 'xaxis'), 'x')
  const yLabel = axisTitle(recordAt(scene, 'yaxis'), 'y')
  const zLabel = axisTitle(recordAt(scene, 'zaxis'), 'z')

  const next = [...traces]
  next[surfaceIndex] = {
    ...surface,
    customdata: labels.map((label) => new Array(columns).fill(label)),
    hovertemplate: `${xLabel}: %{x}<br>${yLabel}: %{customdata}<br>${zLabel}: %{z:.4g}<extra></extra>`,
  }
  return { traces: next, sceneOverride }
}

/** Themed defaults for a 2D figure. Everything here is overridable by the spec. */
function base2dLayout(theme: VizTheme, uirevision: string): PlotlyRecord {
  const axis: PlotlyRecord = {
    gridcolor: theme.grid,
    zerolinecolor: theme.grid,
    linecolor: theme.grid,
    tickfont: { color: theme.text, size: 10 },
    title: { font: { color: theme.text, size: 11 } },
    // A chat column is narrow and a strike axis is long. Let Plotly claim the
    // room its own tick labels need rather than clipping them.
    automargin: true,
  }
  return {
    autosize: true,
    uirevision,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: theme.plotBg,
    font: { color: theme.text, family: 'system-ui, sans-serif', size: 11 },
    hovermode: 'x unified',
    hoverlabel: {
      bgcolor: theme.hoverBg,
      bordercolor: theme.hoverBorder,
      font: { color: theme.text, size: 12 },
    },
    legend: {
      orientation: 'h',
      x: 0.5,
      xanchor: 'center',
      y: -0.22,
      font: { color: theme.text, size: 11 },
    },
    margin: { l: 56, r: 24, t: 24, b: 48 },
    xaxis: axis,
    yaxis: { ...axis },
  }
}

/** Themed defaults for a 3D figure. Everything here is overridable by the spec. */
function base3dLayout(theme: VizTheme, uirevision: string): PlotlyRecord {
  const axis: PlotlyRecord = {
    gridcolor: theme.grid,
    zerolinecolor: theme.grid,
    backgroundcolor: 'rgba(0,0,0,0)',
    showbackground: false,
    tickfont: { color: theme.text, size: 10 },
    title: { font: { color: theme.text, size: 11 } },
  }
  return {
    autosize: true,
    uirevision,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: theme.text, family: 'system-ui, sans-serif', size: 11 },
    hoverlabel: {
      bgcolor: theme.hoverBg,
      bordercolor: theme.hoverBorder,
      font: { color: theme.text, size: 12 },
    },
    showlegend: false,
    margin: { l: 0, r: 0, t: 8, b: 0 },
    scene: {
      bgcolor: 'rgba(0,0,0,0)',
      aspectmode: 'manual',
      aspectratio: { x: 1.8, y: 1.1, z: 0.8 },
      camera: { eye: { x: 1.6, y: -1.6, z: 0.7 } },
      xaxis: axis,
      yaxis: { ...axis },
      zaxis: { ...axis },
    },
  }
}

/**
 * Give the spec's marker lines and labels a colour.
 *
 * The ATM and spot markers arrive as dotted shapes with matching annotations
 * and no colour at all, which Plotly draws in a near-black that vanishes on a
 * dark background. Anything the producer did colour is left alone.
 */
function themeOverlays(layout: PlotlyRecord, theme: VizTheme): PlotlyRecord {
  const themed: PlotlyRecord = { ...layout }

  if (Array.isArray(themed.shapes)) {
    themed.shapes = themed.shapes.map((shape) =>
      isRecord(shape)
        ? {
            ...shape,
            line: mergeDeep({ color: theme.shapeLine, width: 1 }, recordAt(shape, 'line')),
          }
        : shape
    )
  }

  if (Array.isArray(themed.annotations)) {
    themed.annotations = themed.annotations.map((annotation) =>
      isRecord(annotation)
        ? {
            ...annotation,
            font: mergeDeep({ color: theme.muted, size: 10 }, recordAt(annotation, 'font')),
          }
        : annotation
    )
  }

  return themed
}

/**
 * The mode bar is the renderer's, not the producer's.
 *
 * A chart inside a transcript needs a visible way back from an accidental
 * zoom, and a way to lift a 3D surface out of the conversation as an image, so
 * the bar is kept whatever the spec asked for. Everything else the spec sets
 * is honoured.
 */
function buildConfig(specConfig: PlotlyRecord): PlotlyRecord {
  return {
    ...specConfig,
    displayModeBar: true,
    displaylogo: false,
    responsive: true,
    // Selection tools have no meaning on a read-only analytics chart, and
    // spike lines fight with the unified hover label.
    modeBarButtonsToRemove: ['select2d', 'lasso2d', 'toggleSpikelines'],
  }
}

// ---------------------------------------------------------------------------
// Sizing
// ---------------------------------------------------------------------------

/**
 * The rendered width of an element, tracked as it changes.
 *
 * Plotly's own `responsive` config only listens for a window resize, and the
 * chat column changes width without one: the conversation sidebar collapses,
 * a panel is dragged, a scrollbar appears. The width is therefore measured and
 * given to Plotly explicitly.
 *
 * `measured` is the gate rather than the width itself. Drawing before the
 * first measurement would mean an immediate second draw at the real size, and
 * a measurement of zero is a real answer, not a missing one: a container that
 * is not laid out yet, or an environment with no layout at all. That case
 * falls back to Plotly's own autosize rather than showing a skeleton forever.
 */
function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ width: 0, measured: false })

  useEffect(() => {
    const node = ref.current
    if (!node) return

    let frame = 0
    const measure = () => {
      frame = 0
      const next = Math.round(node.getBoundingClientRect().width)
      setSize((current) =>
        current.measured && Math.abs(current.width - next) < 1
          ? current
          : { width: next, measured: true }
      )
    }

    measure()

    // Absent in some test environments, where one measurement is enough.
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }

    const observer = new ResizeObserver(() => {
      // One measurement per frame. A drag fires the observer continuously and
      // a Plotly relayout is not cheap.
      if (frame !== 0) return
      frame = window.requestAnimationFrame(measure)
    })
    observer.observe(node)
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  return { ref, width: size.width, measured: size.measured }
}

// ---------------------------------------------------------------------------
// Failure containment
// ---------------------------------------------------------------------------

interface PlotBoundaryProps {
  children: ReactNode
  fallback: ReactNode
}

interface PlotBoundaryState {
  failed: boolean
}

/**
 * Catch anything Plotly throws while drawing.
 *
 * A trace the bundled build does not implement, or an attribute combination it
 * rejects, throws during the draw. Without this the whole conversation
 * unmounts and the operator loses the answer along with the chart. Mounted
 * with a key derived from the spec, so a new frame gets a fresh attempt.
 */
class PlotBoundary extends Component<PlotBoundaryProps, PlotBoundaryState> {
  constructor(props: PlotBoundaryProps) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError(): PlotBoundaryState {
    return { failed: true }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

const DEFAULT_HEIGHT: Readonly<Record<PlotlyVizEngine, number>> = { '2d': 340, '3d': 420 }

/** `option_chain_service` reads as `option chain`. */
function humaniseSource(source: string): string {
  return source
    .trim()
    .replace(/_service$/, '')
    .replace(/_/g, ' ')
    .trim()
}

/**
 * Render one `plotly` visualization frame.
 *
 * Args:
 *   spec: The frame's `spec`, validated here rather than by the caller.
 *   title: The frame's title, used as the accessible name.
 *   source: The service the numbers came from, shown as provenance.
 *   height: Plot height in pixels.
 *   showHeader: Whether to draw the visible title row.
 *   className: Extra classes on the outer shell.
 */
export function PlotlyViz({
  spec,
  title,
  source,
  height,
  showHeader = true,
  className,
}: PlotlyVizProps) {
  const headingId = useId()
  const theme = useVizTheme()
  const { ref, width, measured } = useMeasuredWidth()

  const parsed = useMemo(() => parseSpec(spec), [spec])
  const heading = title?.trim() ?? ''
  const sourceLabel = humaniseSource(source ?? '')
  const accessibleName = heading || 'Option analytics chart'
  const engine = parsed.ok ? parsed.spec.engine : '2d'
  const plotHeight = height ?? DEFAULT_HEIGHT[engine]

  const figure = useMemo(() => {
    if (!parsed.ok) return null
    const { engine: specEngine, layout: specLayout, config, expiryLabels } = parsed.spec

    // uirevision keeps a reader's zoom and camera across a theme change or a
    // resize. It is derived from the chart's identity, not from its numbers,
    // so a redraw of the same chart does not throw the view away.
    const uirevision = `${specEngine}:${heading}:${sourceLabel}`

    let traces = themeTraces(parsed.spec.traces, theme)
    let sceneOverride: PlotlyRecord = {}
    if (specEngine === '3d' && expiryLabels) {
      const labelled = labelSurfaceExpiries(traces, specLayout, expiryLabels)
      traces = labelled.traces
      sceneOverride = labelled.sceneOverride
    }

    const base =
      specEngine === '3d' ? base3dLayout(theme, uirevision) : base2dLayout(theme, uirevision)
    let layout = mergeDeep(base, specLayout)
    if (Object.keys(sceneOverride).length > 0) {
      layout = mergeDeep(layout, { scene: sceneOverride })
    }

    return { data: traces, layout: themeOverlays(layout, theme), config: buildConfig(config) }
  }, [parsed, theme, heading, sourceLabel])

  // Size is applied outside the figure memo so a drag does not rebuild the
  // themed layout on every frame. A width of zero means the container could
  // not be measured, and Plotly's own autosize is the better answer than a
  // plot pinned to nothing.
  const sizedLayout = useMemo(() => {
    if (!figure) return null
    if (width <= 0) return { ...figure.layout, height: plotHeight, autosize: true }
    return { ...figure.layout, width, height: plotHeight, autosize: false }
  }, [figure, width, plotHeight])

  const placeholder = (message: string) => (
    <p className="px-3 py-2 text-xs text-muted-foreground">{message}</p>
  )

  let body: ReactNode
  if (!parsed.ok) {
    body = placeholder(parsed.reason)
  } else {
    const Plot = engine === '3d' ? Plot3D : Plot2D
    const skeleton = (
      <Skeleton className="w-full" style={{ height: plotHeight }} aria-hidden="true" />
    )
    body = (
      <div ref={ref} className="w-full px-1 pb-1">
        {measured && figure && sizedLayout ? (
          <PlotBoundary
            key={`${engine}:${parsed.spec.traces.length}:${heading}`}
            fallback={placeholder('This chart could not be drawn.')}
          >
            <Suspense fallback={skeleton}>
              <Plot
                data={figure.data}
                layout={sizedLayout}
                config={figure.config}
                style={{ width: width > 0 ? width : '100%', height: plotHeight }}
              />
            </Suspense>
          </PlotBoundary>
        ) : (
          skeleton
        )}
      </div>
    )
  }

  const headerVisible = showHeader && (heading !== '' || sourceLabel !== '')

  return (
    <section
      aria-labelledby={headingId}
      className={cn('my-3 overflow-hidden rounded-lg border border-border bg-card', className)}
    >
      {headerVisible ? (
        <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-3 py-1.5">
          <h3 id={headingId} className="text-[11px] font-medium text-foreground">
            {accessibleName}
          </h3>
          {sourceLabel !== '' && (
            <span className="ml-auto text-[11px] text-muted-foreground">from {sourceLabel}</span>
          )}
        </div>
      ) : (
        <h3 id={headingId} className="sr-only">
          {accessibleName}
        </h3>
      )}
      {body}
    </section>
  )
}
