/**
 * Indicator registry (ARCHITECTURE.md §6A, §8). The sibling of the chart-type
 * registry: that one answers *"how do I paint an array of bars"*, this one
 * answers *"what do I compute, what does it plot, and what can a user tune"*.
 *
 * A descriptor is data, not code-in-the-core: the chart never switches on an
 * indicator id. Each `plot` names a registered **chart type**, so indicators
 * ride the existing Family-A renderers and add no drawing code at all.
 *
 * The built-in descriptors live in the lazy `openalgo-charts/indicators` tier;
 * only the registry and the runtime ship in the base bundle, so an app that
 * plots its own maths pays nothing for the catalog.
 */
import type { Bar } from './bar';
import type { AlertEventPayload } from '../alerts/types';
import type { SeriesType } from './chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import type { PriceScaleId, PriceFormat, SeriesDataState } from './series';
import type { SeriesMarker } from '../primitives/markers';
import type { TableCell, ChartTableOptions } from '../primitives/table';
import type { FillGradient } from '../primitives/indicator-fill';
import type { IPrimitive } from '../primitives/primitive';
import type { DataVariant } from '../feed/data-variant';
import { validateIndicatorInputs } from './indicator-inputs';
import { IndicatorInputError } from './indicator-input-error';
import { isPlainObject } from '../helpers/validate';
export { IndicatorInputError } from './indicator-input-error';

/** Which price a calculation reads from each bar. */
export type IndicatorSource = 'open' | 'high' | 'low' | 'close' | 'hl2' | 'hlc3' | 'ohlc4' | 'volume';

/** A scalar study output, aligned with the primary source bars. */
export interface IndicatorStudySource {
  readonly kind: 'indicator';
  readonly instanceId: string;
  readonly plotKey: string;
}

/** Committed scalar output supplied by a host that schedules study dependencies. */
export interface IndicatorStudyOutput {
  generation: number;
  revision: number;
  /** Changes whenever an earlier output prefix may have changed. */
  historyRevision: number;
  source?: Readonly<SeriesDataState>;
  available: boolean;
  values: readonly (number | null)[];
}

/** A setting value an input condition compares with. */
export type IndicatorInputConditionValue = string | number | boolean;

/**
 * A test over a study's current settings, read by a settings form for
 * `activeWhen` and `visibleWhen`.
 *
 * `is` holds when the setting under `key` equals the value, or one of the
 * values when it is a list; `isNot` is its negation. `all` holds when every
 * nested condition does and `any` when at least one does, so `all` of nothing
 * holds and `any` of nothing does not. Values compare strictly: the number 5
 * is not the text '5'. It is data rather than a callback so a descriptor that
 * a compiler emits, or one saved as JSON, can carry it.
 */
export type IndicatorInputCondition =
  | { key: string; is: IndicatorInputConditionValue | readonly IndicatorInputConditionValue[] }
  | { key: string; isNot: IndicatorInputConditionValue | readonly IndicatorInputConditionValue[] }
  | { all: readonly IndicatorInputCondition[] }
  | { any: readonly IndicatorInputCondition[] };

/**
 * How a settings form presents an input. The calculation never reads these:
 * a hidden or inactive input keeps its value, and `calc` still receives it.
 */
export interface IndicatorInputPresentation {
  /**
   * The input can be edited only while this holds; otherwise the form shows it
   * disabled, with its value readable and a reason naming what it depends on.
   * Also inactive while an input the condition reads is hidden or inactive,
   * because a setting nobody can change cannot be what enables another.
   */
  activeWhen?: IndicatorInputCondition;
  /**
   * The input is shown only while this holds; otherwise it leaves the form and
   * the tab order, and any draft in it is kept for when it returns. Also
   * hidden while an input the condition reads is hidden.
   */
  visibleWhen?: IndicatorInputCondition;
  /**
   * Consecutive inputs sharing this id sit on one row, the first one's label
   * leading it: a length beside its source, a switch beside the value and
   * colour it turns on. A multi-line text input always takes a row of its own.
   */
  inline?: string;
}

/**
 * One tunable input. New typed values are validated before study mutations;
 * established input kinds retain their descriptor's calculation contract.
 *
 * `tooltip` is help text for the row. A label has to stay short enough to fit a
 * dense panel, which leaves nowhere to say what a parameter actually does, and a
 * ported study whose every input carried an explanation arrives here with that
 * explanation dropped. A settings UI renders it as a hover affordance beside the
 * label; the core ignores it.
 *
 * Every variant also takes the presentation fields of
 * {@link IndicatorInputPresentation}: `activeWhen`, `visibleWhen` and `inline`.
 */
export type IndicatorInput = IndicatorInputPresentation & (
  | { key: string; type: 'number'; label: string; default: number; min?: number; max?: number; step?: number; group?: string; tooltip?: string }
  | { key: string; type: 'boolean'; label: string; default: boolean; group?: string; tooltip?: string }
  | { key: string; type: 'color'; label: string; default: string; group?: string; tooltip?: string }
  | { key: string; type: 'text'; label: string; default: string; group?: string; tooltip?: string }
  | { key: string; type: 'symbol'; label: string; default: string; exchangeKey?: string; group?: string; tooltip?: string }
  | { key: string; type: 'session'; label: string; default: string; group?: string; tooltip?: string }
  | { key: string; type: 'multiline'; label: string; default: string; group?: string; tooltip?: string }
  | { key: string; type: 'price'; label: string; default: number; min?: number; max?: number; step?: number;
      pick?: boolean | { paneIndex?: number; priceScaleId?: PriceScaleId }; group?: string; tooltip?: string;
      /**
       * Key of a declared `timestamp` input this price pairs with: together
       * they name one point, a bar time and a price. A host picks both from
       * one click (`Chart.beginPick('point')`) and writes them in one settings
       * patch, so the study never computes on the time of one pick and the
       * price of another. A timestamp pairs with one price at most.
       */
      timeKey?: string;
      /**
       * With `timeKey`: a handle on the chart at the point, on the same pane
       * and scale a pick of this price uses, that drags the time and the price
       * together as one settings change and one undo step. The drawing tier's
       * controller draws it; a study the user may not configure keeps it still.
       */
      anchor?: boolean }
  /** Absolute UTC seconds. Independent of the chart timezone and legacy wall-clock `time` inputs. */
  | { key: string; type: 'timestamp'; label: string; default: number; min?: number; max?: number; step?: number;
      pick?: boolean; group?: string; tooltip?: string }
  | { key: string; type: 'select'; label: string; default: string; options: readonly { label: string; value: string }[]; group?: string; tooltip?: string }
  | { key: string; type: 'source'; label: string; default: IndicatorSource; allowStudyOutputs?: boolean; group?: string; tooltip?: string }
  /**
   * A timeframe code (`'5m'`, `'1d'`), for a study that folds the chart's bars
   * up to a coarser interval. A settings UI renders it as a select over the
   * registered intervals, so the value is always one the engine can bucket by;
   * a free text box would accept `'5min'` and leave the study computing on a
   * code it cannot resolve. An empty default means "the chart's own interval".
   */
  | { key: string; type: 'interval'; label: string; default: string; group?: string; tooltip?: string }
  /**
   * A wall-clock instant in the chart's zone, written `YYYY-MM-DD HH:MM` (the
   * time part optional), for an anchor a user picks by date: the start of an
   * anchored VWAP, an event to measure from. It is carried as that string, not
   * as UTC seconds, so a layout saved in one zone restores to the same wall
   * clock in another, and `zonedStringToUtcSeconds` turns it into a bar time.
   */
  | { key: string; type: 'time'; label: string; default: string; group?: string; tooltip?: string });

/** Dash pattern for a level, a drawing, or a plot. */
export type IndicatorLineStyle = 'solid' | 'dashed' | 'dotted';

/** Line-style options, for a settings UI's Style tab. */
export const INDICATOR_LINE_STYLES: readonly { label: string; value: string }[] = [
  { label: 'Solid', value: 'solid' },
  { label: 'Dashed', value: 'dashed' },
  { label: 'Dotted', value: 'dotted' },
];

/** Settings keys the runtime derives for a plot's appearance. */
export function plotStyleKeys(plot: IndicatorPlot): {
  color: string; width: string; lineStyle: string; opacity: string; type: string;
} {
  return {
    // A descriptor that already declares a colour input owns that key: a
    // generated one would shadow it, and setting the declared key would
    // silently stop working.
    color: plot.colorKey ?? `${plot.key}:color`,
    width: `${plot.key}:width`,
    lineStyle: `${plot.key}:lineStyle`,
    opacity: `${plot.key}:opacity`,
    type: `${plot.key}:type`,
  };
}

/**
 * Per-plot appearance inputs, generated from the descriptor rather than
 * hand-written on each one: every indicator gets colour, opacity, thickness,
 * and line style for free, and a settings UI can render them as a "Style" tab
 * beside the descriptor's own `inputs`.
 *
 * Defaults come from the plot's declared style (and its legacy `colorKey`), so
 * an indicator that already ships colours keeps them.
 */
export function indicatorStyleInputs(descriptor: IndicatorDescriptor): IndicatorInput[] {
  const out: IndicatorInput[] = [];
  for (const plot of descriptor.plots) {
    const k = plotStyleKeys(plot);
    const declared = descriptor.inputs.find((i) => i.key === plot.colorKey);
    const color = typeof declared?.default === 'string'
      ? declared.default
      : (plot.style?.color ?? '#4f8cff');
    out.push({ key: k.color, type: 'color', label: plot.title, default: color, group: plot.title });
    out.push({
      key: k.opacity, type: 'number', label: 'Opacity', default: 100,
      min: 0, max: 100, step: 1, group: plot.title,
    });
    out.push({
      key: k.width, type: 'number', label: 'Thickness', default: plot.style?.lineWidth ?? 1.5,
      min: 0.5, max: 8, step: 0.5, group: plot.title,
    });
    out.push({
      key: k.lineStyle, type: 'select', label: 'Line style',
      default: plot.style?.lineStyle ?? 'solid',
      options: INDICATOR_LINE_STYLES, group: plot.title,
    });
    out.push({
      key: k.type, type: 'select', label: 'Plot style',
      default: plot.type,
      options: INDICATOR_PLOT_STYLES, group: plot.title,
    });
  }
  return out;
}

/**
 * Chart types a plot can be re-rendered as. A moving average is a line by
 * default, but the same column of numbers reads better as a histogram or an
 * area depending on what you are looking for, and a descriptor cannot know
 * which. Restricted to the types that make sense for a single value column.
 */
export const INDICATOR_PLOT_STYLES: readonly { label: string; value: string }[] = [
  { label: 'Line', value: 'line' },
  { label: 'Line with markers', value: 'line-markers' },
  { label: 'Step line', value: 'step' },
  { label: 'Area', value: 'area' },
  { label: 'Histogram', value: 'histogram' },
  { label: 'Columns', value: 'column' },
];

/** Canonical option list for a `type: 'source'` input, for settings UIs. */
export const INDICATOR_SOURCES: readonly { label: string; value: IndicatorSource }[] = [
  { label: 'Close', value: 'close' },
  { label: 'Open', value: 'open' },
  { label: 'High', value: 'high' },
  { label: 'Low', value: 'low' },
  { label: 'HL2', value: 'hl2' },
  { label: 'HLC3', value: 'hlc3' },
  { label: 'OHLC4', value: 'ohlc4' },
];

export type IndicatorSettings = Record<string, unknown>;

/** A shaded band between two of an indicator's output columns. */
export interface IndicatorFillSpec {
  /** Plot keys or unplotted calculated columns; unplotted columns use the band's local scale. */
  between: readonly [string, string];
  /** Colour where the first plot is above the second. */
  colorUp?: string;
  /** Colour where the second is above the first. */
  colorDown?: string;
  /** Settings keys holding those colours, so the band is restyleable. */
  colorUpKey?: string;
  colorDownKey?: string;
  /** 0..1. Defaults to 0.12. */
  opacity?: number;
  /** A price-anchored gradient for the whole band, resolved after each calculation. */
  gradient?: FillGradient | ((ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }) => FillGradient | undefined);
  /** Per-bar gradient takes precedence over the whole-band gradient. Undefined uses the band default. */
  gradientBy?(ctx: {
    index: number;
    a: number | null;
    b: number | null;
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): FillGradient | undefined;
  /** Per-bar color takes precedence over both gradients and the up/down colors. */
  colorBy?(ctx: {
    index: number;
    a: number | null;
    b: number | null;
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): string | undefined;
  /**
   * Draw the band on the price pane even though the indicator owns a pane of
   * its own. The pair with `IndicatorPlot.overlay`: a study can already send
   * one plot to the candles, and a band between two such plots belongs beside
   * them rather than in the study pane the fill would otherwise land in.
   * Ignored for an `'onchart'` descriptor, which is on the price pane already.
   */
  overlay?: boolean;
}

/** A named summary grid owned by one indicator instance. */
export interface IndicatorTableSpec {
  /** Stable, nonempty identity, unique within this instance's table list. */
  id: string;
  rows: readonly (readonly TableCell[])[];
  options?: Partial<ChartTableOptions>;
  /** Keep this grid on the price pane when the indicator uses another pane. */
  overlay?: boolean;
}

/**
 * What `colorParts` answers: a candle plot's colour split three ways, which is
 * how a study paints a wick in full colour over a translucent body. `body` is
 * the bar's colour (and the only part a line, histogram or column reads); a
 * part left undefined falls back to `colorBy`, then to the plot's own colour.
 */
export type PlotBarColor = { body?: string; wick?: string; border?: string };

/** One plotted line/band/histogram. `type` is any registered chart type. */
export interface IndicatorPlot {
  /** Key into the `calc` result. */
  key: string;
  /** Registered chart type used to draw it ('line', 'histogram', 'area', ...). */
  type: SeriesType;
  /** Legend title. */
  title: string;
  /** Style overrides merged onto the chart type's defaults. */
  style?: SeriesStyle;
  /** Price axis for this plot. Defaults to 'right'. */
  priceScaleId?: PriceScaleId;
  /**
   * Value formatting for the axis and crosshair tag of the scale this plot maps
   * to: `percent` for a ratio study, `volume` for a cumulative one, `custom` for
   * anything else.
   *
   * Like `style.precision`, this is a property of the **price scale**, not of the
   * series, so it belongs to a plot that owns its pane. Setting it on an
   * `'onchart'` plot reformats the instrument's own axis, which is almost never
   * what a study wants.
   *
   * `percent` suffixes the value as it stands and does not scale it, so a study
   * returning a 0..1 fraction should keep returning it and read `0.62%`. Scaling
   * inside `calc` to make the axis read better changes the plotted value, and the
   * legend, the crosshair and every downstream calculation with it.
   */
  priceFormat?: PriceFormat;
  /**
   * Draw this one plot on the price pane even though the indicator owns a pane
   * of its own. An oscillator that also wants a signal
   * band or a stop line sitting on the candles is the case: the study belongs in
   * its own pane, one of its columns belongs on price, and splitting it into two
   * indicators would make the user configure the same inputs twice.
   *
   * Ignored for an `'onchart'` descriptor, which is already on the price pane.
   */
  overlay?: boolean;
  /**
   * Draw the column shifted this many bars to the right (negative: left). The
   * column itself stays one value per bar and `calc` returns exactly what it
   * always did; only where each value is painted moves. Positive is what a
   * displaced cloud or a projected channel wants: the last `offset` values land
   * in the right margin, past the newest candle, where no bar exists to hold
   * them. It shifts the drawn series only. A fill between two plots with the
   * same offset follows; the legend reads the value drawn under the cursor.
   */
  offset?: number;
  /**
   * Settings key holding this plot's color, so a settings change restyles the
   * series without a full rebuild.
   */
  colorKey?: string;
  /**
   * Four `calc` keys to draw this plot as bar-shaped elements instead of one
   * value per bar: candles, hollow candles, OHLC bars, high-low.
   *
   * A single column cannot express those at all, and the alternative (a second
   * result shape for `calc`) would fork the contract every descriptor and every
   * helper is written against. Naming four columns inside the *same*
   * `IndicatorValues` keeps one shape: a smoothed Heikin-Ashi overlay, a
   * higher-timeframe candle, a synthetic spread instrument each return four
   * ordinary columns and point at them from here.
   *
   * The named columns must all exist and be bar-aligned, or `addIndicator`
   * throws. `key` stays the series identity and the legend reading falls back to
   * the `close` column.
   */
  ohlc?: { open: string; high: string; low: string; close: string };
  /**
   * Per-bar colour, for plots whose meaning changes bar to bar: a MACD
   * histogram is four colours by sign and direction, a conditional study two.
   * Return `undefined` to fall back to the plot's own colour.
   *
   * Reaches the renderer as `Bar.color`, so every Family-A plot type honours
   * it: histogram, column, candles, OHLC bars, line, step and area.
   */
  colorBy?(ctx: {
    value: number;
    index: number;
    values: IndicatorValues;
    settings: IndicatorSettings;
  }): string | undefined;
  /**
   * Per-bar colour split three ways, for a candle plot whose wick or border
   * should not follow its body: a solid wick over a translucent body, a
   * border in the trend colour. Takes precedence over `colorBy` for the parts
   * it names; a part it leaves undefined falls back to `colorBy`, then to the
   * plot's own colour. A value plot (line, histogram, column) reads `body` only.
   */
  colorParts?(ctx: {
    value: number;
    index: number;
    values: IndicatorValues;
    settings: IndicatorSettings;
  }): PlotBarColor | undefined;
}

/** A horizontal reference level (RSI 70/30, Stochastic 80/20, a zero line). */
export interface IndicatorLevel {
  price: number;
  color?: string;
  title?: string;
  /**
   * Two-state shorthand for `lineStyle`. `lineStyle` wins when both are given,
   * and with neither a level draws dashed. A retained form rather than a
   * deprecated one (COMPATIBILITY.md lists why).
   */
  dashed?: boolean;
  lineWidth?: number;
  lineStyle?: IndicatorLineStyle;
}

/** One end of an indicator drawing: a time on the shared axis, a price on the pane's scale. */
export interface DrawAnchor {
  time: number;
  price: number;
}

/**
 * Where one returned drawing, marker or shading column goes, when the study's
 * own layer is the wrong place for it. A study in its own pane still has
 * things to say about the candles (a supply zone, a buy signal, a regime), and
 * a study whose plots sit on two axes has shapes and marks measured on each.
 * Naming no target keeps the output in the study's own layer, exactly as
 * before.
 *
 * Each distinct target gets a layer of its own, owned by the instance: it
 * hides with the study, is released with it, and is released as soon as a
 * calculation returns nothing for that target. Marks sent to the series the
 * study's own marks already anchor to join that layer instead, so marks at
 * one bar stack rather than overlap, unless that series is an `overlay` plot
 * of a study in its own pane (see `plot`). A study's layers stack in a fixed
 * order: its own marks, its marker targets, its own shapes, its drawing
 * targets, its own shading, then its shading targets, each kind's targets
 * taking the price pane first and then the plots in declaration order.
 * Shading paints behind every series on its pane, so on any one pane it sits
 * under the candles, the plots, the marks and the shapes whatever its slot;
 * the order decides which study's shading covers another's. A targeted layer
 * created after the study was added is put back in that order among the
 * targeted layers on its pane, below those of the studies added after it. No
 * other layer moves for it, so an output that names no target stacks exactly
 * as before.
 */
export interface IndicatorOutputTarget {
  /**
   * A declared plot key. A shape is drawn on that plot's pane and measured on
   * its effective price scale; a marker is anchored to that plot's series, so
   * `aboveBar` and `belowBar` read its values, and where it has none, the
   * candle's whenever that plot is on the price pane and on the candles' scale,
   * first plot or not. A shading column fills that plot's pane and is bound to
   * its effective scale, which has no price to measure but keeps the layer on
   * the axis the plot uses, so a reassignment never leaves a column held for
   * nothing. Each follows the plot through a scale reassignment or a study
   * move. An `overlay` plot takes it to the price pane.
   */
  plot?: string;
  /**
   * The price pane, in the instrument's own units, staying there when the
   * study moves. A shape is measured on the scale that pane quotes prices on
   * (its crosshair readout, which is the candles' own scale on whichever axis
   * they sit) and holds no axis itself, so the price axis stays free to move.
   * A marker is anchored to the instrument's candles, so `belowBar` sits
   * under the low; it is drawn once the chart has a primary series. A shading
   * column fills the price pane's full height and binds no axis. Naming a
   * plot as well is rejected: a plot already decides its pane.
   */
  overlay?: boolean;
}

/**
 * One column of per-bar shading a study's `background` returns in its list
 * form, optionally sent to another pane or plot. `colors` is what the plain
 * form returns: one entry per bar, `null` where nothing is shaded.
 */
export interface IndicatorBackgroundSpec extends IndicatorOutputTarget {
  colors: readonly (string | null)[];
}

/** A signal marker a study returns, optionally sent to another pane or plot. */
export type IndicatorMarker = SeriesMarker & IndicatorOutputTarget;

/**
 * A free-standing shape an indicator paints in its own pane, anchored to time
 * and price rather than to a bar index.
 *
 * Plots, levels and markers each answer a different question and none of them
 * answers this one: a pivot-to-pivot trendline, a supply zone, an order block,
 * a measured-move projection are all geometry between two arbitrary points, and
 * a column of one value per bar cannot express any of them. Anchors are times,
 * so a shape stays put when history is paged in and every logical index shifts.
 * Any shape can name an {@link IndicatorOutputTarget} to be drawn elsewhere.
 */
export type IndicatorDrawing = IndicatorOutputTarget & (
  | {
      kind: 'line';
      from: DrawAnchor;
      to: DrawAnchor;
      color?: string;
      lineWidth?: number;
      lineStyle?: IndicatorLineStyle;
      /** Continue the line past its anchor to the pane edge. */
      extendLeft?: boolean;
      extendRight?: boolean;
    }
  | {
      kind: 'box';
      from: DrawAnchor;
      to: DrawAnchor;
      /** Border colour. Omit `fillColor` to draw an outline only. */
      color?: string;
      fillColor?: string;
      /** Fill alpha, 0..1. Defaults to 0.12. */
      opacity?: number;
      lineWidth?: number;
      /** Caption drawn on a plate at the centre of the box; `\n` splits lines. */
      text?: string;
      textColor?: string;
      /** Positive finite CSS pixels. Defaults to 11. */
      fontSize?: number;
      /** CSS font-family list. Defaults to ui-sans-serif, system-ui, sans-serif. */
      fontFamily?: string;
      bold?: boolean;
      italic?: boolean;
      /** Multiline row alignment inside the plate. Defaults to left. */
      textAlign?: 'left' | 'center' | 'right';
      /** Plate placement inside the box. Defaults to center and middle. */
      align?: 'left' | 'center' | 'right';
      verticalAlign?: 'top' | 'middle' | 'bottom';
      /**
       * Detail shown on a plate while the pointer rests on the box, and gone
       * when it leaves; `\n` splits lines. A zone that carries its size, its
       * age and what formed it cannot print all of that on the box without
       * hiding the candles under it, so the caption names it and this explains
       * it. The box becomes hit-testable, and `id` (or the tooltip text) is
       * what `subscribeClick` reports for it.
       */
      tooltip?: string;
      /** Hit id, for `subscribeClick`. Defaults to the tooltip text. */
      id?: string;
    }
  | {
      kind: 'label';
      at: DrawAnchor;
      /** `\n` splits lines. */
      text: string;
      /** Plate fill. */
      color?: string;
      textColor?: string;
      /** Positive finite CSS pixels. Defaults to 11. */
      fontSize?: number;
      /** CSS font-family list. Defaults to ui-sans-serif, system-ui, sans-serif. */
      fontFamily?: string;
      bold?: boolean;
      italic?: boolean;
      /** Multiline row alignment inside the plate. Defaults to left. */
      textAlign?: 'left' | 'center' | 'right';
      /** Which edge of the plate sits on the anchor. Defaults to 'center'. */
      align?: 'left' | 'center' | 'right';
      /** Which vertical plate edge sits on the anchor. Defaults to middle. */
      verticalAlign?: 'top' | 'middle' | 'bottom';
      /** Hover detail, as on a box. */
      tooltip?: string;
      /** Hit id, for `subscribeClick`. Defaults to the tooltip text. */
      id?: string;
    }
  | {
      kind: 'polyline';
      points: readonly DrawAnchor[];
      /**
       * Straight segments by default. Smooth interpolates anchors in screen
       * space with half-chord tangents and can overshoot their price range.
       */
      curve?: 'linear' | 'smooth';
      color?: string;
      lineWidth?: number;
      /** Close the path back to the first point (a triangle, a wedge). */
      closed?: boolean;
      fillColor?: string;
      /** Fill alpha, 0..1. Defaults to 0.12. */
      opacity?: number;
    });

/** `calc` output: one array per plot key, aligned 1:1 with the input bars. */
export type IndicatorValues = Record<string, readonly (number | null)[]>;

/** Per-instance scratch owned by the descriptor (Tier-2 data lands here). */
export type IndicatorStore = Record<string, unknown>;

/** Why this calculation ran. Revisions count source mutations, not provider ticks executed. */
export interface IndicatorExecutionContext {
  /** Stable source-series identity within this host. */
  sourceId: number;
  provenance: 'history' | 'live' | 'replay';
  change: 'initial' | 'reset' | 'prepend' | 'append' | 'replace' | 'correction' | 'refresh';
  revision: number;
  historyRevision: number;
  confirmationSource: 'provider' | 'replay' | 'clock' | 'unknown' | 'empty';
}

/**
 * The fourth, optional argument to `calc` (and the sixth to `calcTail`): what
 * the calculation cannot read off the bars themselves.
 *
 * It is optional so that every descriptor written against `calc(bars, settings,
 * store)` keeps its exact signature and its exact behaviour, which is the whole
 * point: a calculation that ignores the context computes what it always did.
 */
export interface IndicatorCalcContext {
  /** Resolves declared, opted-in study inputs without recursively flushing the chart. */
  resolveSource?(source: IndicatorStudySource): readonly (number | null)[];
  /** Native mutation provenance. Older custom hosts may omit it. */
  execution?: IndicatorExecutionContext;
  /**
   * Where the last bar stands, so a study can act once per bar rather than once
   * per tick, or refuse to signal off a bar that is still moving.
   */
  barState: {
    /** A live execution sees a newer tail than the previous calculation, including coalesced appends. */
    isNew: boolean;
    /**
     * The last bar's declared duration or calendar period has elapsed on the
     * chart clock. Count-driven and unknown intervals cannot be confirmed by
     * the clock. Without an interval, retains the legacy last-gap estimate
     * (a single bar is confirmed). Explicit provider or replay state takes
     * precedence over that estimate. Empty history is confirmed.
     */
    isConfirmed: boolean;
    /** A live feed is driving updates, rather than a one-off history load. */
    isRealtime: boolean;
    /** Index of the last bar, `bars.length - 1` (-1 when there are none). */
    lastIndex: number;
  };
  /** The instrument, when the host knows one. See `IndicatorAttachContext`. */
  symbol?: string;
  /** The timeframe (`'5m'`, `'1d'`), on the same terms as `symbol`. */
  interval?: string;
  /** The chart's IANA zone, the calendar its axis is labelled in. */
  timezone: string;
  /**
   * True when the bars `calc` receives are a transform's elements (Renko
   * bricks, Heikin Ashi candles) rather than the bars the host feeds, so their
   * times do not mark out the clock. Absent otherwise.
   */
  transformed?: boolean;
  /** Chart wall clock in UTC seconds, the clock the countdown row reads. */
  now(): number;
  /**
   * The instrument's tick size, from the **price pane's** `minMove`.
   *
   * The price pane and not the indicator's own, because `calc` runs on the
   * instrument's bars whichever pane the plot lands in, and a study pane is not
   * quoted in the instrument's tick: an RSI is a dimensionless 0..100 band, so
   * its scale carries no tick at all to read.
   *
   * `undefined` when the host has not told the chart what it is, which is the
   * honest answer rather than a guessed 0.01: an indicator sizing a range in
   * ticks has to tell "one paisa" apart from "nobody said".
   */
  tickSize?: number;
}

/** What an alert's `when` predicate is handed, for the bar it is judging. */
export interface IndicatorAlertContext {
  bars: readonly Bar[];
  values: IndicatorValues;
  settings: Readonly<IndicatorSettings>;
  /** The bar being evaluated. */
  index: number;
}

/** Delivery frequency for eligible live calculations after chart batching. */
export type IndicatorAlertFrequency = 'everyUpdate' | 'oncePerBar' | 'onBarClose' | 'once';

/**
 * A condition the runtime watches, declared by the descriptor rather than wired
 * up by the host: the indicator is the only thing that knows what a crossover of
 * its own columns means.
 *
 * Evaluated once per bar, for bars that are new since the last evaluation, so
 * adding the indicator to a loaded chart fires nothing for history.
 */
export interface IndicatorAlertSpec {
  /** Stable within the descriptor, e.g. `'cross-up'`. */
  id: string;
  /** Short human label, e.g. `'MACD crossed up'`. */
  title: string;
  /**
   * Omitted retains evaluation only when a new bar is appended. Explicit
   * policies also observe qualifying updates within a bar. once is spent only
   * by a delivered live event and lasts for this instance's lifetime.
   * Historical loads, replay and settings-only recalculation never deliver.
   */
  frequency?: IndicatorAlertFrequency;
  /**
   * Longer text for a notification; defaults to `title`. A function is handed
   * the same context `when` judged, so the message can carry the bar's own
   * numbers: the price it crossed at, the histogram reading, a JSON body for a
   * webhook. It runs only for a bar `when` accepted.
   */
  message?: string | ((ctx: IndicatorAlertContext) => string);
  when(ctx: IndicatorAlertContext): boolean;
}

/**
 * Bars of another instrument or interval, supplied by the host on request.
 *
 * The engine is handed one symbol's bars and owns no transport, so a study
 * that compares against a benchmark, or a Tier-2 provider that needs a second
 * series, asks the host through this and the host answers from wherever it
 * keeps history. `from` and `to` are UTC seconds. Caller cancellation and the
 * instance lifetime both bound each request. Managed studies cancel their
 * data-setting generations while preserving requests across style changes.
 */
export interface IndicatorBarsRequest {
  symbol: string;
  exchange?: string;
  interval: string;
  from: number;
  to: number;
  /** The provider series to answer from; absent is its default. See `inheritedDataVariant`. */
  variant?: DataVariant;
  signal?: AbortSignal;
}

export type IndicatorBarsProvider = (request: IndicatorBarsRequest) => Promise<readonly Bar[]>;

/** Requested observations and their known availability, aligned one-to-one. */
export interface RequestedBarsSnapshot {
  /** Finite, strictly increasing opening times. Observations are never compacted. */
  bars: readonly Bar[];
  /** UTC seconds at or after opening; null means availability is unknown. */
  availableAt: readonly (number | null)[];
  /** Explicit confirmation, independent of a clock or the next observed opening. */
  confirmed: readonly boolean[];
}

/** An optional historical knowledge cutoff, separate from opening-time bounds. */
export interface IndicatorSnapshotRequest extends IndicatorBarsRequest {
  /** The provider must supply values as known then, or reject if unsupported. */
  asOf?: number;
}

/** Native provider access with optional explicit requested-data metadata. */
export interface IndicatorBarsProviderAccess {
  requestBars: IndicatorBarsProvider;
  requestSnapshot?(request: IndicatorSnapshotRequest): Promise<RequestedBarsSnapshot>;
}

/** Current native request identity and availability boundary. */
export interface IndicatorRequestState {
  source?: Readonly<SeriesDataState>;
  providerRevision: number;
  /** Host announcements of changed external data, independently of price ticks. */
  dataRevision: number;
  supportsSnapshots: boolean;
  /** Legacy replay has no known availability cutoff. */
  replay?: { time: number; asOf?: number; forming: boolean };
}

/** Payload of the `'indicator:alert'` event on the chart's own bus. */
export interface IndicatorAlertPayload extends AlertEventPayload {
  /** Descriptor id, e.g. `'macd'`. */
  indicatorId: string;
  /** Instance id, so a host can tell three EMAs apart. */
  instanceId: string;
  message: string;
}

/** Optional instrument identity and capability supplied by the host. */
export interface ChartDataContext {
  symbol?: string;
  exchange?: string;
  interval?: string;
  /** Instrument capability, independent of readings: false unsupported, absent unknown. */
  hasOpenInterest?: boolean;
  /** Which of the provider's series the chart shows; absent is its default. Set it with `publishDataContext`. */
  variant?: Readonly<DataVariant>;
}

/** Source identity changed, or the available source-bar range changed. */
export type IndicatorDataChange = 'context' | 'range';

/** Observable state of an indicator's external data lifecycle. */
export type IndicatorDataStatus =
  | { state: 'loading' | 'ready' | 'empty' | 'unsupported' }
  | { state: 'error'; error: unknown };

/** What an indicator's `attach` lifecycle can reach. */
export interface IndicatorAttachContext {
  /** Optional host identity, independent of the indicator's own settings. */
  dataContext?(): Readonly<ChartDataContext> | undefined;
  /** Read bars and identity again when the host publishes a change. */
  subscribeDataChanges?(listener: (change: IndicatorDataChange) => void): () => void;
  /** Publish status and an explicit retry action for this instance. */
  setDataStatus?(status: IndicatorDataStatus): void;
  setDataRetry?(retry: (() => void) | null): void;
  /** Instance lifetime. Aborted on removal, preserved across style changes. */
  signal?: AbortSignal;
  /** Current settings (live: read at call time, not captured). */
  settings(): Readonly<IndicatorSettings>;
  /** The bars the study computes on now: the chart's, or the underlying bars for a study set to them (`IndicatorApi.setBarSource`). */
  bars(): readonly Bar[];
  /** Re-run `calc` and repaint: call when external data arrives. */
  requestRecompute(): void;
  /** Scratch this instance owns; the same object `calc` receives. */
  store: IndicatorStore;
  /**
   * The instrument the chart is showing, when the host knows it.
   *
   * Hosts can supply this through `IndicatorHost` or Chart's explicit data
   * context. Without a configured identity it stays undefined. External
   * studies read `dataContext` to include the exchange as well.
   */
  symbol?(): string | undefined;
  /** The chart's timeframe (`'5m'`, `'1d'`), on the same terms as `symbol`. */
  interval?(): string | undefined;
  // The rest are always supplied by `IndicatorInstance`, which falls back to the
  // shipped default when its host declares no opinion. They are optional so a
  // caller can hand-build a minimal context (a unit test exercising one
  // descriptor's lifecycle) without stubbing the whole surface.
  /** The chart's IANA zone, the one its axis is labelled in. */
  timezone?(): string;
  /** Chart wall clock in UTC seconds, the same clock the countdown row uses. */
  now?(): number;
  /**
   * Ask the host for another instrument's (or interval's) bars. Always present
   * under `chart.addIndicator`; it rejects when the host has registered no
   * provider (`chart.setBarsProvider`), so a study can treat the rejection as
   * "unsupported here" and say so through `setDataStatus`.
   */
  requestBars?(request: IndicatorBarsRequest): Promise<readonly Bar[]>;
  /** Request explicit confirmation and availability without inferring either from raw bars. */
  requestSnapshot?(request: IndicatorSnapshotRequest): Promise<RequestedBarsSnapshot>;
  /** Native source, provider and replay identity, read at request time. */
  requestState?(): Readonly<IndicatorRequestState>;
  /** Includes source revisions, provider changes and within-bar replay clock movement. */
  subscribeRequestChanges?(listener: () => void): () => void;
  /** The pane this instance drew into. Moves when panes are reordered. */
  paneIndex?(): number;
  /** Attach a primitive to this indicator's pane, and detach it again. */
  addPrimitive?(p: IPrimitive): void;
  removePrimitive?(p: IPrimitive): void;
  /**
   * Emit on the chart's own event bus, the one `chart.on(name, cb)` listens to.
   *
   * The declarative `alerts` slot covers a condition read off the bars; this is
   * the imperative half, for an indicator whose signal arrives from outside the
   * calculation entirely (a subscription its `attach` opened).
   */
  emit?(event: string, payload: unknown): void;
}

/**
 * What `levels` is handed. It carries `bars` and `values` **and** spreads the
 * settings keys onto itself, so the built-ins written against the original
 * `levels(settings)` signature keep working unchanged: they read
 * `ctx.overbought` (or pass `ctx` to a `num(s, key, default)` helper) and find
 * exactly what they found before. A widened parameter is the only way a level
 * can be data-derived (yesterday's high, the session VWAP band), and that is a
 * whole class of level that could not be expressed at all before.
 *
 * The three data members are optional for the same backward-compatibility
 * reason, not because the runtime ever omits them: it always passes all three,
 * but a caller holding only a settings bag must still be able to invoke
 * `levels` directly. A descriptor that needs the data should default them
 * (`ctx.bars ?? []`).
 *
 * `settings`, `bars` and `values` are therefore reserved keys, the way
 * `timezone` already is in the settings a `calc` receives: an input declared
 * under one of those names is shadowed here.
 */
export type IndicatorLevelContext = IndicatorSettings & {
  settings?: Readonly<IndicatorSettings>;
  bars?: readonly Bar[];
  values?: IndicatorValues;
};

export interface IndicatorDescriptor {
  /** Registry key, e.g. `'macd'`. */
  id: string;
  /** Display name, e.g. `'MACD'`. */
  name: string;
  /** Grouping for a picker UI ('Trend', 'Momentum', 'Volume', 'Volatility'). */
  category?: string | undefined;
  /** `'onchart'` overlays the price pane; `'pane'` gets its own pane. */
  placement: 'onchart' | 'pane';
  /**
   * This indicator was written from code the host can show the user.
   *
   * Its legend row then carries a source button beside the gear, and pressing
   * it emits `indicatorSource` with the same payload `indicatorSettings`
   * carries. The engine does not hold the code and does not want to: a
   * descriptor may be compiled from a script, generated, or written by hand in
   * the host's own bundle, and only the host knows which of those it can put in
   * front of somebody. So this says a button is worth offering, and the host
   * decides what the button opens.
   *
   * Absent or false draws no button, which is every built-in study.
   */
  hasSource?: boolean;
  inputs: readonly IndicatorInput[];
  plots: readonly IndicatorPlot[];
  /**
   * Shaded bands between pairs of plots: the Ichimoku cloud, a Bollinger
   * channel. A pair of lines is not the same picture as a filled region: the
   * fill is what makes "price is above the cloud" readable at a glance, and
   * which side leads is itself the signal, hence the two colours.
   */
  fills?: readonly IndicatorFillSpec[];
  /**
   * Full recompute over every bar. Must return arrays the same length as
   * `bars` (use `null` for warmup gaps: the line renderer breaks across them
   * and autoscale skips them).
   *
   * Tier-1 indicators are pure functions of `(bars, settings)` and ignore
   * `store`. Tier-2 indicators (the ones with their own data) read the
   * external series their `attach` lifecycle put in `store`.
   */
  calc(
    bars: readonly Bar[],
    settings: Readonly<IndicatorSettings>,
    store: IndicatorStore,
    ctx?: IndicatorCalcContext,
  ): IndicatorValues;
  /**
   * Optional per-instance lifecycle, for indicators whose data is not derived
   * from the chart's bars (CVD, PCR, an external feed). Called once
   * when the instance is created; return a teardown function.
   *
   * Fetch into `ctx.store`, then call `ctx.requestRecompute()`: `calc` runs
   * again and reads what you stored.
   */
  attach?(ctx: IndicatorAttachContext): (() => void) | void;
  /**
   * Optional incremental path, called instead of `calc` when only the tail
   * changed (a live tick). Return values for indices `[fromIndex, bars.length)`
   * (the runtime splices them onto the previous result) or `null` to fall
   * back to a full `calc`.
   *
   * Without it every tick costs a full recompute. That is a few hundred
   * microseconds for one indicator over 50k bars, but it is O(n) per tick per
   * indicator, so implement this for anything meant to run in a busy live pane.
   */
  calcTail?(
    bars: readonly Bar[],
    settings: Readonly<IndicatorSettings>,
    fromIndex: number,
    previous: IndicatorValues,
    store: IndicatorStore,
    ctx?: IndicatorCalcContext,
  ): IndicatorValues | null;
  /**
   * Optional bar-anchored signal markers: a named "Buy"/"Sell" plate, an arrow
   * at a crossover. Runs after every `calc`, so it reads the values it just
   * produced rather than recomputing anything.
   *
   * A plot cannot express this: a plot is a column of prices drawn as a line or
   * histogram, whereas a signal is a discrete event with a label. Returning `[]`
   * (when a `showLabels`-style input is off, say) clears every layer. A mark
   * can name the price pane or a plot to anchor to instead of the default
   * (see {@link IndicatorOutputTarget}).
   */
  markers?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly IndicatorMarker[];
  /**
   * What `aboveBar` and `belowBar` are measured against.
   *
   * `'plot'`, the default, is this study's own first plot, which is right for a
   * mark that belongs to the line: an arrow on a moving average sits against
   * the average.
   *
   * `'price'` is the instrument's candles, so above is above the high and below
   * is below the low. That is what a buy or sell signal on an overlay study
   * means, and anchoring one to the study's own column instead puts it wherever
   * that column happens to sit: a study that anchors its marks to a mid-body
   * line draws every "below" mark through the middle of the candle.
   *
   * Ignored by a study in its own pane, which has no candles to measure
   * against, and ignored when the chart has no primary series yet. Both fall
   * back to the first plot rather than dropping the marker. It applies to the
   * marks that name no target; a study in its own pane sends a mark to the
   * candles with `overlay: true` on that mark.
   */
  markerAnchor?: 'plot' | 'price';
  /**
   * Optional summary grid pinned to a corner of the pane.
   *
   * Some studies are not a value per bar at all: a seasonality heatmap is a
   * matrix of monthly returns, a scoreboard is a handful of statistics. Those
   * have no place in `calc`, whose contract is one column per plot aligned to
   * the bars, so they come back through here instead. Runs after every `calc`.
   *
   * Return `null` (or a zero-row grid) to draw nothing, which is how a
   * `showTable`-style input should switch it off.
   */
  table?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): { rows: readonly (readonly TableCell[])[]; options?: Partial<ChartTableOptions> } | null;
  /**
   * Multiple named grids, refreshed after each calculation. Stable IDs reuse
   * their grid; omitted IDs are removed. Return [] to remove all grids.
   * When provided, this hook takes precedence over the single `table` hook.
   */
  tables?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly IndicatorTableSpec[];
  /**
   * Optional free-standing shapes: trendlines between pivots, supply and
   * demand boxes, projection labels. Drawn in the indicator's pane unless a
   * shape names another pane or plot (see {@link IndicatorOutputTarget}). Runs
   * after every `calc`, like `markers` and `table`, and the returned list
   * replaces the previous one wholesale, so returning `[]` clears every layer.
   */
  draws?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly IndicatorDrawing[];
  /**
   * Optional per-bar shading behind everything else in the indicator's pane: a
   * full-height column per bar, `null` where nothing should be shaded.
   *
   * A regime study answers "which state is the market in right now", and that is
   * a property of the whole bar, not a price. Drawn as a plot it would need a
   * value to sit at and would fight the pane's autoscale; as a column behind the
   * candles it reads at a glance and costs the scale nothing.
   *
   * Return a list of {@link IndicatorBackgroundSpec} instead to shade somewhere
   * else as well: each column can name the price pane or a plot (see
   * {@link IndicatorOutputTarget}), one column per target, and a column naming
   * none shades the indicator's pane exactly as the plain form does.
   *
   * Runs after every `calc`. Return `[]` to clear the study's own shading and
   * release every targeted column.
   */
  background?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly (string | null)[] | readonly IndicatorBackgroundSpec[];
  /**
   * Optional recolouring of the **main price candles**, one entry per bar,
   * `null` to leave that bar with its own colour.
   *
   * Distinct from a plot's `colorBy`, which paints the indicator's own series: a
   * trend filter, a volatility regime or a higher-timeframe bias is a statement
   * about the price bars themselves, and drawing it as a second series beside
   * them says something weaker.
   *
   * Only one indicator's colours can be on the candles at a time; the most
   * recent publisher wins, and publishers run in `addIndicator` order, so the
   * winner is the same one from frame to frame. Removing it, or hiding it,
   * restores the bars' own colours.
   */
  barColors?(ctx: {
    bars: readonly Bar[];
    values: IndicatorValues;
    settings: Readonly<IndicatorSettings>;
  }): readonly (string | null)[];
  /**
   * Optional conditions the runtime watches on the descriptor's behalf, emitted
   * as `'indicator:alert'` on the chart's event bus with an
   * {@link IndicatorAlertPayload}. See {@link IndicatorAlertSpec}.
   */
  alerts?: readonly IndicatorAlertSpec[];
  /**
   * Optional horizontal reference levels drawn in the indicator's pane.
   * Recomputed after every `calc`, so a level derived from the data (the
   * previous day's high) tracks it. See `IndicatorLevelContext` for why the
   * argument still reads as a settings bag.
   */
  levels?(ctx: IndicatorLevelContext): readonly IndicatorLevel[];
  /**
   * Optional fixed price range for the indicator's own pane (RSI 0..100).
   * Applied only when the indicator creates its pane: two indicators sharing a
   * pane would otherwise fight over it.
   */
  range?(settings: Readonly<IndicatorSettings>): { min: number; max: number } | null;
}

const registry = new Map<string, IndicatorDescriptor>();

/** Register an indicator descriptor. Later registrations of the same id win. */
export function registerIndicator(descriptor: IndicatorDescriptor): void {
  validateIndicatorInputs(descriptor.inputs, {});
  registry.set(descriptor.id, descriptor);
}

export function getIndicator(id: string): IndicatorDescriptor {
  const d = registry.get(id);
  if (d === undefined) {
    throw new Error(
      `openalgo-charts: unknown indicator "${id}", did you import 'openalgo-charts/indicators'?`,
    );
  }
  return d;
}

export function hasIndicator(id: string): boolean {
  return registry.has(id);
}

export function registeredIndicators(): IndicatorDescriptor[] {
  return Array.from(registry.values());
}

/** The descriptor's declared defaults as a settings object. */
export function indicatorDefaults(descriptor: IndicatorDescriptor): IndicatorSettings {
  validateIndicatorInputs(descriptor.inputs, {});
  const out: IndicatorSettings = Object.fromEntries(descriptor.inputs.map(input => [input.key, input.default]));
  for (const input of descriptor.inputs) {
    if (input.type === 'symbol' && input.exchangeKey !== undefined && !Object.prototype.hasOwnProperty.call(out, input.exchangeKey)) {
      Object.defineProperty(out, input.exchangeKey, { value: '', enumerable: true, writable: true, configurable: true });
    }
  }
  return out;
}

/** Read one bar's value for a price source. */
export function sourceValue(bar: Bar, source: IndicatorSource): number {
  switch (source) {
    case 'open': return bar.open;
    case 'high': return bar.high;
    case 'low': return bar.low;
    case 'hl2': return (bar.high + bar.low) / 2;
    case 'hlc3': return (bar.high + bar.low + bar.close) / 3;
    case 'ohlc4': return (bar.open + bar.high + bar.low + bar.close) / 4;
    case 'volume': return bar.volume ?? 0;
    default: return bar.close;
  }
}

/** Read a price source or an explicitly resolved scalar study output. */
export function sourceValues(bars: readonly Bar[], source: IndicatorSource): number[];
export function sourceValues(bars: readonly Bar[], source: IndicatorSource | IndicatorStudySource,
  context?: Pick<IndicatorCalcContext, 'resolveSource'>): (number | null)[];
export function sourceValues(bars: readonly Bar[], source: IndicatorSource | IndicatorStudySource,
  context?: Pick<IndicatorCalcContext, 'resolveSource'>): (number | null)[] {
  if (typeof source !== 'string') {
    if (!isPlainObject(source)) {
      throw new IndicatorInputError('Invalid study source reference');
    }
    const fields = Object.getOwnPropertyDescriptors(source);
    if (Reflect.ownKeys(fields).length !== 3 || fields.kind?.value !== 'indicator' ||
      typeof fields.instanceId?.value !== 'string' || !fields.instanceId.value.trim() ||
      typeof fields.plotKey?.value !== 'string' || !fields.plotKey.value.trim()) {
      throw new IndicatorInputError('Invalid study source reference');
    }
    if (!context?.resolveSource) throw new IndicatorInputError('Study source requires a calculation resolver');
    const values = context.resolveSource(source);
    if (!Array.isArray(values) || values.length !== bars.length) throw new IndicatorInputError('Study source length must align with source bars');
    return values.slice();
  }
  const out = new Array<number>(bars.length);
  for (let i = 0; i < bars.length; i++) out[i] = sourceValue(bars[i]!, source);
  return out;
}
