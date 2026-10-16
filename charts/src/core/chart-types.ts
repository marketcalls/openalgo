/**
 * The public option, event and payload types of the Chart class, with the two
 * small values published beside them (`compactVolume`, `PRICE_SCALE_MODES`).
 *
 * They sit in their own module so chart.ts can be split into internal pieces
 * without each piece importing the orchestrator for a type. chart.ts re-exports
 * every name declared here, so an import of './chart' or '../core/chart' keeps
 * the same names at the same path. `ChartClickEvent` and `PriceAxisState` are
 * declared in chart.ts instead: they carry deprecated members, and the
 * deprecation inventory (COMPATIBILITY.md and its test) names chart.ts as
 * their home.
 */
import type { RafScheduler, RafCanceller } from './render-loop';
import type { ChartTheme } from '../theme';
import type { TimeScaleOptions } from '../scale/time-scale';
import type { PriceScaleOptions } from '../scale/price-scale';
import type { TickMarkType } from '../render/axis';
import type { CanvasOptions, GridOptions } from '../render/grid';
import type {
  RenderBackendFactory, RenderBackendKind, RendererChoice, RendererFallbackReason,
} from '../render/backend';
import type { PriceScaleId, PriceFormat } from '../model/series';
import type { SeriesType } from '../model/chart-type-registry';
import type { SeriesTransformSpec } from '../model/series-transform';
import type { IndicatorBarsProvider, IndicatorBarsProviderAccess } from '../model/indicator-registry';
import type { SeriesStyle } from '../render/series-style';
import type { Bar } from '../model/bar';
import type { CrosshairMode } from '../input/crosshair';
import type { ShortcutManager, ShortcutManagerOptions } from '../input/shortcuts';
import type { EventMarkerDetails } from '../primitives/event-markers';
import type { LegendStatusLineOptions } from '../primitives/pane-legend';
import type { TimeNavigatorOptions } from '../primitives/time-navigator';
import type { LogoWatermarkOptions } from '../primitives/watermark';
import type { TextWatermarkOptions } from '../primitives/text-watermark';
import type { IndicatorPolicy } from '../model/indicator-policy';
import type { IndicatorBarSource } from '../model/indicator-bar-source';

/** What a wheel zoom holds still. */
export type ZoomAnchor = 'cursor' | 'right';
/** What a double-click on a pane does. See {@link ChartOptions.doubleClick}. */
export type DoubleClickAction = 'reset' | 'maximize' | 'none';
/**
 * The `dblclick` event. `paneIndex` is the pane under the pointer. A listener
 * that acts on the double-click itself (opening a text editor for the selected
 * drawing, say) sets `handled` to true, and the chart's own action is skipped
 * for that press.
 */
export interface DoubleClickEvent {
  paneIndex: number;
  x: number;
  y: number;
  handled: boolean;
}

/** Optional background text. Blank text follows the chart's symbol and interval. */
export interface ChartWatermarkOptions extends Partial<TextWatermarkOptions> {
  visible?: boolean;
}

/** A pane's plot area in container media px, from `Chart.plotRect`. */
export interface PlotRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Defensive branding snapshot emitted synchronously after setBranding as `branding:changed`. */
export type BrandingChangedEvent = false | LogoWatermarkOptions;

/**
 * Which corporate-action / news markers the chart draws. Every type defaults to
 * on; an unlisted type is always drawn. Only filters the strip the chart owns
 * (`setEvents`), not an `EventMarkers` a host drives itself.
 */
export interface ChartEventOptions {
  earnings?: boolean;
  dividend?: boolean;
  split?: boolean;
  news?: boolean;
}

/**
 * Chrome that lives on the axis strips rather than in the plot: a live clock in
 * the corner where the two axes meet, and a countdown to the current bar's close
 * inside the last-price tag.
 *
 * Both default to off. Neither is a thing a chart should start showing because
 * it upgraded, and a chart that sets none of this draws the axes it always drew.
 */
export interface AxisChromeOptions {
  /**
   * Live clock in the corner between the price and time axes. `true` takes the
   * defaults; the object form is there for the one thing worth choosing, the
   * second row carrying the zone's offset from UTC.
   */
  sessionClock?: boolean | { showOffset?: boolean };
  /** Second row in the last-price tag counting down to the bar's close. */
  barCountdown?: boolean;
  /**
   * Wall-clock UTC seconds. Both readings are times of day, so neither can use
   * `now`, which is a monotonic animation clock and not a calendar. Defaults to
   * the system clock; pass the feed's clock to keep a delayed or replayed chart
   * honest about what time its data thinks it is.
   */
  clock?: () => number;
}

/** Options for `Chart.exportSVG`. */
export interface ExportSvgOptions {
  /**
   * Document width in media px. Absent means the live chart width. A different
   * size lays the chart out afresh for the export (the same bar spacing over a
   * wider or narrower plot, every scale re-measured for its new height) and
   * puts the live layout back before returning.
   */
  width?: number;
  /** Document height in media px. Absent means the live chart height. */
  height?: number;
  /**
   * Paint the theme background under the chart. Default true. Off, the
   * document has no ground of its own and takes the colour of whatever page
   * it is placed on, which is what an embedded figure usually wants.
   */
  background?: boolean;
  /**
   * The pixel ratio the paint runs at. Only 1 is accepted: SVG has no device
   * pixels, and a renderer asked for 2 would snap its hairlines to half-media-
   * pixel edges that scale as a blur. Named so the option reads the same as
   * the PNG path and a future scaled export has a place to land.
   */
  dpr?: 1;
}

/** Preferences for pointer panning and the view restored by reset. */
export interface ChartNavigationOptions {
  /** Allow user plot translation, including touch, wheel and keys. Default: true. */
  panEnabled?: boolean;
  /** Allow user zoom and reset/fit actions. Programmatic setters remain available. Default: true. */
  zoomEnabled?: boolean;
  /** Mouse and pen plot drags. Touch gestures retain two-axis panning. Default: both. */
  mousePan: 'horizontal' | 'both';
  /** Latest bars to show initially and on reset. 0 fits all loaded bars (default). */
  defaultVisibleBars: number;
  /** Initial/reset spacing in CSS pixels. Positive values override the bar count; 0 disables it. */
  defaultBarSpacing?: number;
}

export interface ChartOptions {
  document?: Document;
  pixelRatio?: () => number;
  /**
   * The frame scheduler, for deterministic tests. Supplied, it runs every
   * frame the chart paints, the one after a resize or a new pixel ratio
   * included; with the default one the chart paints those inside the
   * callback that reports them, so a resize never shows a cleared canvas.
   */
  raf?: { schedule: RafScheduler; cancel?: RafCanceller };
  /** Full palette; pass `lightTheme` (the default), `darkTheme`, or a custom ChartTheme. */
  theme?: ChartTheme;
  priceAxisWidth?: number;
  timeAxisHeight?: number;
  /** Initial horizontal scale configuration, including spacing limits for wide profiles. */
  timeScale?: Partial<TimeScaleOptions>;
  /** Saved navigation preferences, also exposed in the Axes settings tab. */
  navigation?: Partial<ChartNavigationOptions>;
  /**
   * Where indicator legend rows start inside **one** pane, in media px. A host
   * that draws its own overlay in a pane's top-left corner (an OHLC readout, a
   * symbol line, a trade panel) needs to push these clear of it, or the rows
   * land underneath and their settings / close buttons become invisible and
   * unclickable.
   *
   * It follows the primary price pane, which is at the top until something
   * moves it below its studies: a readout of the price belongs to the price
   * pane, wherever it sits. Maximizing a study pane hides the price pane, so
   * the maximized pane, now in the same corner, inherits the offset. Every
   * other pane keeps the default corner, because a short study pane would
   * have its legend pushed off it entirely.
   *
   * Defaults to `{ top: 6, left: 8 }`.
   */
  legendOffset?: { top?: number; left?: number };
  /**
   * Crosshair behaviour. 'normal' (default): the cross follows the pointer
   * exactly. 'magnet': the horizontal line snaps to the nearest O/H/L/C of the
   * bar under the cursor (price pane only).
   */
  crosshairMode?: CrosshairMode;
  /** Snap the vertical crosshair to the nearest primary bar's center. Default false; independent of the price magnet. */
  crosshairSnapToBar?: boolean;
  /** Fit the primary series' scale to that series only. Does not enable auto-fit. Default false. */
  priceOnlyAutoScale?: boolean;
  /** Collapse study legend rows into a count without hiding their plots or stopping calculations. Default false. */
  indicatorLegendCollapsed?: boolean;
  /**
   * Optional chrome on the axis strips: the corner clock and the bar-close
   * countdown. Both are off unless asked for, so a chart that omits this block
   * draws the axes it always drew.
   */
  axisChrome?: AxisChromeOptions;
  /**
   * Time source for kinetic animation (defaults to performance.now).
   * `WidgetOptions.now` is a different clock (the widget's wall clock, epoch
   * milliseconds) and is not passed to a widget's chart.
   */
  now?: () => number;
  /**
   * Ease a wheel zoom over a few frames instead of landing the whole step on
   * one. Default true, matching the inertial pan a flick already gets: a chart
   * that glides when panned and jumps when zoomed reads as two different
   * instruments. Off restores the single-frame step.
   */
  animZoom?: boolean;
  /** Ease automatic price ranges during navigation. Defaults to animZoom (true). */
  animAutoscale?: boolean;
  /**
   * What a wheel zoom holds still: the bar under the cursor, or the right edge
   * (the latest bar). Default `'cursor'`, which is what the chart has always
   * done. `'right'` keeps the most recent bar pinned while history stretches
   * away from it, which is what a live chart usually wants.
   */
  zoomAnchor?: ZoomAnchor;
  /**
   * What a double-click on a pane does. `'reset'` (the default, and what the
   * chart has always done) fits every loaded bar on screen and autoscales,
   * which also lands the viewport on the oldest bar and so wakes a history
   * loader. `'maximize'` gives the pane the whole stack, and a second
   * double-click puts the stack back, which is what a multi-pane terminal
   * usually wants from the gesture. `'none'` only emits the event. While a
   * tool is being placed a double-click finishes the shape whatever this says.
   */
  doubleClick?: DoubleClickAction;
  /**
   * Level of detail for a zoomed-out chart (§4.4). Default true: once bars are
   * narrower than the stick a candle is drawn with (about one CSS px; exactly
   * one at a whole pixel ratio), the bars sharing a device-pixel column are
   * drawn as one OHLC-preserving stick (open of the first, close of the last,
   * the column's high and low), and line and histogram series keep each
   * column's first, lowest, highest and last values. A frame then costs the
   * plot's width, not the number of bars in view. Above that spacing nothing
   * changes. Data, autoscale, indicators and the crosshair still see every
   * bar. `false` draws every bar at every zoom.
   *
   * The default time scale never zooms out past one bar per CSS px
   * (`timeScale.minBarSpacing: 1`), so it matters once a host lowers that floor.
   */
  conflate?: boolean;
  /**
   * Column width in sticks (default 1). Higher merges into wider columns, and
   * from spacings that many times wider, for a coarser, cheaper picture.
   */
  conflationFactor?: number;
  /**
   * Which backend paints the series. `'canvas2d'` (the default) is the 2D
   * path every chart has always drawn with. `'webgl2'` asks for the GPU
   * backend: it throws when the tier that registers it has not been imported
   * (a missing import is a mistake in the code), and on a device where that
   * tier finds no WebGL2 it falls back to `canvas2d` with one console warning
   * (a property of the machine the host should still hear about). `'auto'`
   * takes `webgl2` when it is registered and available on this device and
   * `canvas2d` otherwise, silently. Decided once, at construction; read what
   * was actually chosen from `rendererKind`. A GPU backend that loses its
   * context later moves the chart to `canvas2d` for the rest of the session
   * and emits 'renderer:fallback'.
   */
  renderer?: RendererChoice;
  /**
   * Build the backend directly, one call per pane, bypassing `renderer` and
   * the registry. For a host bringing its own backend, and for tests that
   * want to see what the pane asks a backend to paint. A factory that returns
   * null gets the 2D backend for that pane.
   */
  renderBackend?: RenderBackendFactory;
  /**
   * Grid lines: visibility (both default to true) plus per-axis colour, dash,
   * width and spacing. Unset colours/dashes fall through to the theme.
   */
  grid?: Partial<GridOptions>;
  /**
   * The settings dialog's Canvas block: grid, crosshair, scale text/lines and
   * plot margins. Every field is an override of the theme, so a later
   * `setTheme` still restyles anything the dialog did not touch.
   */
  canvas?: CanvasOptions;
  /** Per-field status-line switches applied to every pane legend on the chart. */
  statusLine?: LegendStatusLineOptions;
  /**
   * Square side of a legend action button in media px. Default 16, held to
   * 12..28. Applied to every pane legend, because the rows stack against it.
   */
  legendIconSize?: number;
  /** Accessible label for the chart container (screen readers). */
  ariaLabel?: string;
  /**
   * Keyboard shortcuts. Pass a configured `ShortcutManager`, options to build
   * one, or `false` to disable keyboard control. Defaults to the built-in keymap.
   */
  shortcuts?: ShortcutManager | Partial<ShortcutManagerOptions> | false;
  /**
   * Custom price formatter for every pane's axis tick labels, the last-price
   * tag, and price-line labels. e.g. `(p) => '$' + p.toFixed(2)`. When omitted,
   * a tick-size-aware `toFixed` is used. Change it later via `setPriceFormatter`.
   */
  priceFormatter?: (price: number) => string;
  /**
   * Default price-scale options applied to every pane (tick size `minMove`,
   * `mode: 'linear' | 'logarithmic' | 'percentage' | 'indexed-to-100'`,
   * `inverted`, and top/bottom margins). `minMove` is the instrument's, so it
   * lands only on panes that quote it, see `setPriceScaleOptions`.
   * Tune a single pane later via `chart.panes()[n].priceScale.setOptions(...)`.
   */
  priceScale?: Partial<PriceScaleOptions>;
  /**
   * Where an indicator gets another instrument's bars. The engine is handed
   * one symbol's history and owns no transport, so a study that compares
   * against a benchmark asks through this and the host answers from wherever
   * it keeps candles. Change it later with `setBarsProvider`. Without one an
   * indicator's `requestBars` rejects, and the study reports itself
   * unsupported rather than drawing something invented.
   */
  barsProvider?: IndicatorBarsProvider | IndicatorBarsProviderAccess;
  /**
   * Custom time-axis and crosshair label formatter (receives UTC seconds). When
   * omitted, labels follow `timezone`, which is IST unless set. e.g. for UTC:
   * `(s) => new Date(s * 1000).toISOString().slice(11, 16)`.
   */
  timeFormatter?: (utcSeconds: number, tickMark?: TickMarkType) => string;
  /**
   * IANA zone the time axis and crosshair label in, e.g. 'America/New_York' or
   * 'Europe/London'. Defaults to 'Asia/Kolkata': a caller who passes nothing
   * gets exactly the labels the chart produced before this option existed.
   *
   * An IANA name and not a fixed offset, because a zone that observes DST is a
   * different offset in July than in January and a fixed one is silently wrong
   * for half the year. Change it at runtime with `setTimezone` when the terminal
   * moves between an NSE symbol and a US one. An explicit `timeFormatter`
   * outranks this: a host that formats its own labels has settled the question.
   *
   * Throws if the runtime does not recognise the name.
   */
  timezone?: string;
  /**
   * Hover-revealed zoom / step controls above the time axis, as terminals show.
   * `true` by default: they stay invisible until the pointer nears the bottom
   * of the chart. Pass `false` to drop them, or an options object to restyle.
   */
  timeNavigator?: boolean | Partial<TimeNavigatorOptions>;
  /** OpenAlgo corner mark by default. Pass false to hide it or options for custom branding. */
  branding?: boolean | LogoWatermarkOptions;
  /** Background text, off by default. Blank text follows setDataContext. */
  watermark?: boolean | ChartWatermarkOptions;
  /**
   * Let the primary price pane leave the top of the stack: below its studies
   * through `movePane`, `setPrimaryPaneIndex`, a study pane's own up and down
   * controls, or a restored layout that saved it lower down. Default false,
   * which keeps the price pane pinned at slot 0 exactly as every earlier
   * release did: `movePane` refuses to move or displace it,
   * `setPrimaryPaneIndex` returns false, and `restoreState` refuses a layout
   * that puts it anywhere else, so an explicit pane 0 always means the price.
   *
   * Opt-in because a host that passes 0 to mean the price pane (a price or
   * order line, `coordinateToPrice(y, 0)` pricing a right-click order, a price
   * alert check, `panes()[0]`) would read a study's units the moment a user
   * moved a study above the candles. Before turning it on, drop those explicit
   * zeros or ask `primaryPaneIndex()`, and follow `paneMoved`. Decided once,
   * at construction; read it back with `movablePrimaryPane()`. `createWidget`
   * and `createChartGrid` hand it to their charts as given, off by default too.
   */
  movablePrimaryPane?: boolean;
}

/** Where `chart.addIndicator` puts a study, and how the host holds it. */
export interface AddIndicatorOptions {
  /** The pane: an existing one, or `panes().length` for a new one. Default: the price pane for an overlay, a new pane otherwise. */
  paneIndex?: number;
  /** The scale the study's plots map to on that pane. */
  priceScaleId?: PriceScaleId;
  /** A scale per plot key, for a study whose plots belong on different scales. */
  plotPriceScaleIds?: Readonly<Record<string, PriceScaleId>>;
  /** What the user may do with the study; see `IndicatorPolicy`. */
  policy?: IndicatorPolicy;
  /** The id to give the study, to bring a removed one back under its own identity. */
  instanceId?: string;
  /** On a transformed chart, `'underlying'` computes on the host's bars instead of the elements drawn. */
  barSource?: IndicatorBarSource;
}

/** The chart options `chart.applyOptions` changes at runtime, without recreating the chart. */
export interface ChartApplyOptions {
  theme?: ChartTheme;
  grid?: Partial<GridOptions>;
  canvas?: CanvasOptions;
  statusLine?: LegendStatusLineOptions;
  legendIconSize?: number;
  priceScale?: Partial<PriceScaleOptions>;
  priceFormatter?: ((price: number) => string) | null;
  timeFormatter?: ((utcSeconds: number, tickMark?: TickMarkType) => string) | undefined;
  timezone?: string;
  crosshairMode?: CrosshairMode;
  crosshairSnapToBar?: boolean;
}

export interface AddSeriesOptions {
  /**
   * Target pane index. Omitted means the primary price pane wherever it sits
   * (slot 0 until something moves it, see `Chart.primaryPaneIndex`). Higher
   * panes are created on demand. An index that is not a whole number of 0 or
   * more throws a `RangeError` and adds nothing.
   */
  paneIndex?: number;
  /** Style overrides merged onto the chart type's defaults. */
  style?: SeriesStyle | undefined;
  /**
   * Which price axis this series maps to. 'right' (default) and 'left' each draw
   * an axis and autoscale independently; '' is a hidden overlay scale (no axis)
   * for a volume histogram inside the price pane.
   */
  priceScaleId?: PriceScaleId | undefined;
  /**
   * Value formatting applied to this series' price scale (axis + crosshair tag):
   * `price` (tick-size precision), `volume` (compact 1.2K / 3.4M / 5.6B),
   * `percent` (a `%` suffix at a fixed precision), or a `custom` formatter.
   *
   * `percent` suffixes the value as it stands and does **not** scale it: a study
   * that already returns 0..100 reads `62.24%`, and one that returns a 0..1
   * fraction reads `0.62%`. Multiplying here would put the axis and the plotted
   * value into disagreement, which is the one thing a formatter must never do.
   */
  priceFormat?: PriceFormat | undefined;
  /**
   * Have the chart apply a price-driven transform to the bars this series is
   * given, as `Chart.setSeriesTransform` does. The series draws with `type`,
   * so a host passes the transform's own renderer (`getSeriesTransform(type).renderer`)
   * unless it wants another. An unknown type or invalid option throws.
   */
  transform?: SeriesTransformSpec;
}

/** Compact volume/number formatter (1.2K / 3.4M / 5.6B). */
export function compactVolume(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(2) + 'K';
  return String(Math.round(v));
}

/**
 * Emitted on every crosshair move (and `null` fields on pointer-leave) so a host
 * can render an OHLC legend / tooltip. `bar` is the hovered bar of the primary
 * price series; `point` is container-relative media px for positioning a
 * floating tooltip. See `subscribeCrosshairMove`.
 */
export interface CrosshairMoveEvent {
  /** Linked readouts have no physical pointer position and are not pointer gestures. */
  source?: 'linked';
  /** UTC seconds of the hovered bar, or null when off the data / pointer left. */
  time: number | null;
  /** Logical index under the cursor, or null. */
  index: number | null;
  /** Price under the cursor on the hovered pane, or null. */
  price: number | null;
  /** Hovered bar of the primary (first) price series, or null. */
  bar: Bar | null;
  /** Cursor position in container media px, or null on leave. */
  point: { x: number; y: number } | null;
  /** Pane under the cursor, or null on leave. */
  paneIndex?: number | null;
  /**
   * True while a pointer is held. Placement mode swallows the pan path, so
   * this is the only way to tell a hover from a drag while it is still
   * happening. Absent on the all-null leave payload.
   */
  pressed?: boolean;
  /** Modifier keys held during the move. Absent on the leave payload. */
  modifiers?: PointerModifiers;
  /** Device behind the move. Absent on the leave payload. */
  pointerType?: PointerKind;
  /** Pressure as reported for the move (see `PointerSample`). Absent on the leave payload. */
  pressure?: number;
  /**
   * Every position the pointer passed through since the last move, in the
   * drag payload's space (container x, pane-local y), present only while
   * `pressed`. Placement mode never arms a drag, so a freehand stroke reads
   * its coalesced samples here.
   */
  samples?: PointerSample[];
}

/** Modifier keys held during a pointer gesture. */
export interface PointerModifiers {
  shift: boolean;
  alt: boolean;
  ctrl: boolean;
  meta: boolean;
}

/** Device behind a pointer gesture. Anything the browser does not name reports as a mouse. */
export type PointerKind = 'mouse' | 'touch' | 'pen';

/**
 * One position a pointer passed through during a drag, in the same media px
 * space as the payload's `point` (container x, pane-local y). `pressure` is
 * the pointer events convention: 0..1 from hardware that measures it, 0.5
 * while a button that cannot is held, 0 when nothing is known.
 */
export interface PointerSample {
  x: number;
  y: number;
  pressure: number;
}

/**
 * What the engine reports about the physical pointer behind a gesture.
 * `crosshair:move`, `click`, `drag:start`, `drag` and `drag:end` all carry these keys.
 */
export interface PointerInfo {
  modifiers: PointerModifiers;
  pointerType: PointerKind;
  pressure: number;
}

/** An event-strip click, including every member of a clustered marker. */
export interface ChartEventClick extends EventMarkerDetails {
  /** Chart-container CSS pixels, including the vertical offset of an event pane. */
  point: { x: number; y: number };
  paneIndex: number;
}

/** Payload of the `drag` event: a draggable primitive being moved. */
export interface ChartDragEvent extends PointerInfo {
  id: string;
  price: number;
  time: number;
  paneIndex: number;
  /** Where the gesture was grabbed, so a delta starts at the press rather than the first move. */
  fromPrice: number;
  fromTime: number;
  /** Current pointer position: container media x, pane-local media y. */
  point: { x: number; y: number };
  /**
   * Every position the pointer passed through since the previous `drag`,
   * oldest first, the last one at `point`. Browsers deliver moves at frame
   * rate and fold the positions between frames into the event; a freehand
   * stroke drawn from `point` alone is a polyline of frame-rate corners.
   */
  samples: PointerSample[];
}

/** Payload of `drag:start` (press) and `drag:end` (release) for a primitive drag. */
export interface ChartDragEndEvent extends PointerInfo {
  id: string;
  price: number;
  time: number;
  paneIndex: number;
  /** Release position: container media x, pane-local media y. */
  point: { x: number; y: number };
}

/**
 * What the pointer was over when the context menu was raised. The chart cannot
 * know which menu items an app wants, but it does know what was hit, which is
 * the part an app cannot work out for itself: a canvas gives it a pixel, not an
 * object. `primitive` is anything hit-testable that is not one of the named
 * kinds (a price line, an order pill, a marker).
 */
export type ContextMenuTargetKind =
  | 'drawing' | 'indicator' | 'legend' | 'primitive' | 'series' | 'price-scale' | 'time-scale' | 'empty';

export interface ContextMenuTarget {
  kind: ContextMenuTargetKind;
  /** Hit-test id of the thing under the pointer, when there was one. */
  id: string | null;
  /** Indicator instance id, when `kind` is 'indicator'. */
  instanceId?: string;
  /** Exact plot key when a study's plotted series was hit rather than its legend. */
  plotKey?: string;
  /** Series type, when `kind` is 'series'. */
  seriesType?: SeriesType;
  /** Which axis strip was hit, when `kind` is 'price-scale'. */
  side?: 'right' | 'left';
  /**
   * Which of the pane's scales that strip acts on, when `kind` is
   * 'price-scale': the side's own scale, or the hidden overlay scale ('') when
   * the side carries no series of its own and the pane's values are all on the
   * overlay. It is the argument the `priceAxis*` calls take.
   */
  scaleId?: PriceScaleId;
}

// Declared beside PriceScaleMode; published from here, where it always was.
export { PRICE_SCALE_MODES } from '../scale/price-scale';

/**
 * The setters that change what `getState` saves without an event of their
 * own, and so announce it with `layout:change`.
 */
export type LayoutSetter =
  | 'setPaneWeight' | 'setPriceAxisOptions' | 'setPriceAxisAutoFit' | 'setPriceAxisLockRatio'
  | 'setPriceScaleOptions' | 'setAutoScale' | 'setGridOptions' | 'setCanvasOptions' | 'setStatusLineOptions'
  | 'setWatermarkOptions' | 'setTradingSettings' | 'setAxisChromeOptions' | 'setEventOptions' | 'applyOptions'
  | 'setNavigationOptions';

/**
 * Payload of the `layout:change` event (`chart.on('layout:change', ...)`):
 * a setter in {@link LayoutSetter} has run and the saved layout may differ.
 * It fires once per outermost call, after the change is applied: the canvas
 * block setting the grid on its way is one event, named `setCanvasOptions`.
 * A call that names no pane or scale the chart has changes nothing and fires
 * nothing, and neither does a restore, which announces itself with
 * `state:restore:start` and `state:restore:end`. Compare what you read back
 * if a no-op matters: setting a value to what it already was still fires.
 */
export interface LayoutChangeEvent {
  setter: LayoutSetter;
}

/** Payload of the `contextmenu` event (`chart.on('contextmenu', ...)`). */
export interface ContextMenuEvent {
  paneIndex: number;
  /** Cursor position in container media px, for placing the menu. */
  point: { x: number; y: number };
  /** Price under the pointer on that pane, or null off the plot. */
  price: number | null;
  /** UTC seconds under the pointer, or null when there is no data. */
  time: number | null;
  /** Logical bar index under the pointer, or null off the plot. */
  index: number | null;
  target: ContextMenuTarget;
  /** Suppress the browser's own menu. Call it to show your own. */
  preventDefault(): void;
}

/**
 * Payload of the 'renderer:fallback' event: the chart has moved every pane
 * from a GPU backend to `canvas2d` for the rest of the session, because the
 * device's context was lost or turned out unusable. The frame that noticed
 * was already painted through 2D by the backend itself, so nothing went
 * blank; this is the host's cue to update anything that shows the renderer.
 */
export interface RendererFallbackEvent {
  from: RenderBackendKind;
  to: 'canvas2d';
  reason: RendererFallbackReason;
}
