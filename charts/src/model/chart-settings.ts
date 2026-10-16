/**
 * Declarative chart-settings schema: the tabs and controls a host renders to
 * build the terminal's settings dialog, without hardcoding a list.
 *
 * WHY it reuses `IndicatorInput` rather than inventing a widget vocabulary: a
 * host that can already render the indicator settings form (built from
 * `indicatorStyleInputs`) can render this one with no new widget code. It adds
 * exactly one widget of its own, `colorPair`, because a bullish/bearish pair is
 * one row of the dialog and expressing it as two `color` inputs forces a host
 * into a section header plus two stacked rows: three times the height, for the
 * property a trader changes most.
 *
 * WHY read/write live on the same object as the input: the schema and the
 * accessors are one structure, so a control cannot drift from the option it
 * drives, and there is no second table to keep in step. That is also the rule
 * for what ships here: **every control maps to an option that actually changes
 * what is drawn or stored.** Controls this engine has no backing for are absent
 * rather than inert; a checkbox that does nothing is worse than one that is not
 * there.
 *
 * The tabs are our own five, not a reference terminal's seven. Alerts are not
 * here because they have a dialog and a saved document of their own, and
 * corporate events are not here because nothing in the engine sources them:
 * an empty tab is worse than an absent one.
 *
 * Keys are dotted paths (`symbol.upColor`, `canvas.grid.vertColor`), so a patch
 * is a flat `Record<string, value>` that survives JSON. They are a wire format
 * a host may have written down, so they stay put when the grouping above them
 * changes: a key names the option it writes, not the tab it is shown on.
 */
import type { AxisChromeOptions, Chart, ChartEventOptions, ChartNavigationOptions, ChartWatermarkOptions } from '../core/chart';
import type { IndicatorInput, IndicatorInputCondition, IndicatorInputPresentation } from './indicator-registry';
import { getChartType } from './chart-type-registry';
import { getSeriesTransform } from './series-transform';
import type { SeriesStyle } from '../render/series-style';
import type { CanvasOptions, CanvasLineStyle, GridOptions, ScaleCanvasOptions } from '../render/grid';
import { SCALE_FONT_MIN, SCALE_FONT_MAX } from '../render/grid';
import { HLC_AREA_BAND_COLOR } from '../render/line';
import type { CrosshairOptions } from '../render/crosshair';
import type { LegendStatusLineOptions, LegendTitleMode } from '../primitives/pane-legend';
import type { TradingColors, TradingSettings } from '../core/trading-controller';
import { PRICE_SCALE_MODES, type PriceScaleMode } from '../scale/price-scale';
import { DEFAULT_TIMEZONE, isValidTimezone } from '../feed/time';
import { filterLinkAppearance } from '../link/appearance';
import type { LooseOptional } from '../helpers/types';

/**
 * Tabs of the settings dialog. Five groups, chosen so a trader finds a setting
 * without hunting: what the instrument is painted with, what the header reads
 * out, what the two axes do, what the surface around the data looks like, and
 * what the trade layer draws.
 */
export type ChartSettingsTabId = 'price' | 'readout' | 'axes' | 'appearance' | 'trading';

/**
 * Two colours on one labelled row, with an optional switch in front of them:
 *
 *     [x] Borders   [up] [down]
 *
 * `key` identifies the row and is not itself a value. The value keys are
 * `up.key`, `down.key` and `enabled.key`, each an ordinary flat key of
 * `ChartSettingsValues`, so a host patches this row exactly the way it patches
 * a plain colour and nothing about read/apply has to know the widget exists.
 *
 * `enabled` is absent when the pair has no visibility flag behind it (a candle
 * body is always drawn), which is the difference between a row whose checkbox
 * does something and one whose checkbox would be a lie.
 *
 * It takes `visibleWhen` and `activeWhen`, and a condition that reads any of
 * its three value keys reads the pair. It takes no `inline`: the row already
 * holds a switch and two swatches, so it always stands on its own.
 */
export interface ChartSettingsColorPairInput extends Omit<IndicatorInputPresentation, 'inline'> {
  key: string;
  type: 'colorPair';
  label: string;
  group?: string;
  /** Help text for the row, on the same terms as `IndicatorInput['tooltip']`. */
  tooltip?: string;
  enabled?: { key: string; default: boolean };
  up: { key: string; label: string; default: string };
  down: { key: string; label: string; default: string };
}

/** Everything a host may be handed in `ChartSettingsTab.inputs`. */
export type ChartSettingsInput = IndicatorInput | ChartSettingsColorPairInput;

export interface ChartSettingsTab {
  id: ChartSettingsTabId;
  label: string;
  /** Controls in display order; `input.group` names the sub-heading. */
  inputs: ChartSettingsInput[];
}

export type ChartSettingsValue = string | number | boolean;
/** Flat, JSON-safe snapshot of every control, keyed by the schema's dotted key. */
export type ChartSettingsValues = Record<string, ChartSettingsValue>;

/**
 * The settings slice of a saved chart state. It is declared here rather than on
 * `ChartState` so this module owns its own persistence: `chart.getState()`
 * returns a `ChartState & ChartSettingsState`, which is still a `ChartState` to
 * every existing consumer, and `restoreState` reads it back.
 *
 * `events` stays in the saved state although the dialog no longer offers the
 * switches: the chart still owns `setEventOptions`, a host that feeds its own
 * corporate actions still sets them, and dropping the field would throw that
 * host's saved layout away.
 */
export interface ChartSettingsState {
  navigation?: Partial<ChartNavigationOptions>;
  canvas?: CanvasOptions;
  statusLine?: LegendStatusLineOptions;
  watermark?: ChartWatermarkOptions;
  trading?: TradingSettings;
  events?: ChartEventOptions;
  /**
   * The axis-strip switches. Only the switches: `AxisChromeOptions.clock` is a
   * callback, which no JSON survives, and a host that supplied one supplies it
   * again when it builds the chart.
   */
  axisChrome?: Pick<AxisChromeOptions, 'sessionClock' | 'barCountdown'>;
}

/** One value in the flat patch: a key with the accessor pair that backs it. */
interface Field {
  key: string;
  read(chart: Chart): ChartSettingsValue;
  write(chart: Chart, value: ChartSettingsValue): void;
}

/**
 * One row of the dialog. Most rows carry one value; a `colorPair` carries two
 * or three, which is the whole reason a control is not just a field.
 */
interface Control {
  input: ChartSettingsInput;
  fields: readonly Field[];
}

interface Tab {
  id: ChartSettingsTabId;
  label: string;
  controls: Control[];
}

// ── control factories ─────────────────────────────────────────────────────
// The cast lives in one place per type, so every call site below stays a plain
// getter/setter pair against a real option.

function boolCtl(
  key: string, label: string, group: string, def: boolean,
  get: (c: Chart) => boolean, set: (c: Chart, v: boolean) => void,
): Control {
  return {
    input: { key, type: 'boolean', label, default: def, group },
    fields: [{ key, read: get, write: (c, v) => set(c, v === true) }],
  };
}

function colorCtl(
  key: string, label: string, group: string, def: string,
  get: (c: Chart) => string, set: (c: Chart, v: string) => void,
): Control {
  return {
    input: { key, type: 'color', label, default: def, group },
    fields: [{ key, read: get, write: (c, v) => set(c, String(v)) }],
  };
}

function numCtl(
  key: string, label: string, group: string, def: number,
  range: { min: number; max: number; step: number },
  get: (c: Chart) => number, set: (c: Chart, v: number) => void,
): Control {
  return {
    input: { key, type: 'number', label, default: def, min: range.min, max: range.max, step: range.step, group },
    fields: [{ key, read: get, write: (c, v) => set(c, Number(v)) }],
  };
}

function selectCtl(
  key: string, label: string, group: string, def: string,
  options: readonly { label: string; value: string }[],
  get: (c: Chart) => string, set: (c: Chart, v: string) => void,
  tooltip?: string,
): Control {
  return {
    input: { key, type: 'select', label, default: def, options, group, tooltip } satisfies LooseOptional<ChartSettingsInput> as ChartSettingsInput, // no tooltip reads as none
    fields: [{ key, read: get, write: (c, v) => set(c, String(v)) }],
  };
}

/** One colour of a pair: the key it patches and the accessors behind it. */
interface PairHalf {
  key: string;
  label: string;
  def: string;
  get: (c: Chart) => string;
  set: (c: Chart, v: string) => void;
}

/** The optional switch in front of a pair. Omitted when no flag backs it. */
interface PairToggle {
  key: string;
  def: boolean;
  get: (c: Chart) => boolean;
  set: (c: Chart, v: boolean) => void;
}

function colorPairCtl(
  key: string, label: string, group: string,
  up: PairHalf, down: PairHalf, toggle?: PairToggle,
): Control {
  const input: ChartSettingsColorPairInput = {
    key, type: 'colorPair', label, group,
    up: { key: up.key, label: up.label, default: up.def },
    down: { key: down.key, label: down.label, default: down.def },
  };
  const fields: Field[] = [
    { key: up.key, read: up.get, write: (c, v) => up.set(c, String(v)) },
    { key: down.key, read: down.get, write: (c, v) => down.set(c, String(v)) },
  ];
  if (toggle !== undefined) {
    input.enabled = { key: toggle.key, default: toggle.def };
    fields.unshift({ key: toggle.key, read: toggle.get, write: (c, v) => toggle.set(c, v === true) });
  }
  return { input, fields };
}

const LINE_STYLES: readonly { label: string; value: string }[] = [
  { label: 'Solid', value: 'solid' },
  { label: 'Dashed', value: 'dashed' },
  { label: 'Dotted', value: 'dotted' },
];

const PRECISIONS: readonly { label: string; value: string }[] = [
  { label: 'Default', value: 'default' },
  ...Array.from({ length: 9 }, (_, i) => ({ label: String(i), value: String(i) })),
];

// ── shared accessors ──────────────────────────────────────────────────────

/** Live style of the primary series, or an empty bag before one is added. */
const sty = (chart: Chart): Readonly<SeriesStyle> => chart.primarySeriesInfo()?.style ?? {};

/** Patch the primary series. A no-op with no series, so a control never throws. */
const setSty = (chart: Chart, patch: Partial<SeriesStyle>): void => {
  chart.primarySeries()?.applyOptions(patch);
};

/** Style fields a colour control writes, named so the accessors stay typed. */
type StyleColorKey =
  | 'upColor' | 'downColor'
  | 'borderUpColor' | 'borderDownColor'
  | 'wickUpColor' | 'wickDownColor'
  | 'areaTopColor' | 'areaBottomColor'
  | 'topColor' | 'bottomColor'
  | 'closeColor'
  | 'thickColor' | 'thinColor'
  | 'color';

/** Style fields a pair's switch writes. */
type StyleFlagKey = 'borderVisible' | 'wickVisible' | 'bodyVisible';

/** The one cast: a computed key is a string to TypeScript, not a style field. */
const setStyleField = (chart: Chart, key: StyleColorKey | StyleFlagKey, value: string | boolean): void =>
  setSty(chart, { [key]: value } as Partial<SeriesStyle>);

/** A bullish/bearish colour pair over two `SeriesStyle` fields. */
function seriesColorPair(
  rowKey: string, label: string, group: string,
  up: { key: StyleColorKey; label: string; def: string },
  down: { key: StyleColorKey; label: string; def: string },
  toggle?: { key: StyleFlagKey },
): Control {
  const half = (h: { key: StyleColorKey; label: string; def: string }): PairHalf => ({
    key: `symbol.${h.key}`,
    label: h.label,
    def: h.def,
    get: (c) => sty(c)[h.key] ?? h.def,
    set: (c, v) => setStyleField(c, h.key, v),
  });
  const flag = toggle === undefined ? undefined : {
    key: `symbol.${toggle.key}`,
    def: true,
    get: (c: Chart) => sty(c)[toggle.key] !== false,
    set: (c: Chart, v: boolean) => setStyleField(c, toggle.key, v),
  };
  return colorPairCtl(rowKey, label, group, half(up), half(down), flag);
}

/**
 * Fraction (what the price scale stores) to the dialog's percent, rounded to
 * one decimal. `0.1 * 100` is 10.000000000000002, which would make a read of an
 * untouched chart fail to equal the 10 a host had just written.
 */
const pct = (fraction: number): number => Math.round(fraction * 1000) / 10;

// ── Price ─────────────────────────────────────────────────────────────────

/**
 * Price controls that apply to every series type: the label precision, the
 * dashed line the last price draws across the plot, and its axis tag. The line
 * and the tag sit together deliberately: they are the same reading in two
 * places, and splitting them across tabs is how they end up contradicting.
 */
function priceShared(): Control[] {
  return [
    selectCtl(
      'symbol.precision', 'Precision', 'Values', 'default', PRECISIONS,
      (c) => { const p = sty(c).precision; return p === undefined ? 'default' : String(p); },
      (c, v) => setSty(c, { precision: v === 'default' ? undefined : Number(v) } satisfies LooseOptional<Partial<SeriesStyle>> as Partial<SeriesStyle>), // undefined clears it
    ),
    boolCtl(
      'symbol.priceLineVisible', 'Price line', 'Values', true,
      (c) => sty(c).priceLineVisible !== false,
      (c, v) => setSty(c, { priceLineVisible: v }),
    ),
    boolCtl(
      'symbol.lastValueVisible', 'Last value label', 'Values', true,
      (c) => sty(c).lastValueVisible !== false,
      (c, v) => setSty(c, { lastValueVisible: v }),
    ),
  ];
}

/**
 * Take the up/down verdict from the previous close instead of the bar's own
 * open, offered for the two families whose renderers honour it (candles and
 * OHLC bars). A line has no up/down pair for it to switch, so the control is
 * absent there rather than inert.
 */
const prevCloseCtl = (group: string): Control => boolCtl(
  'symbol.colorByPreviousClose', 'Color from previous close', group, false,
  (c) => sty(c).colorByPreviousClose === true,
  (c, v) => setSty(c, { colorByPreviousClose: v }),
);

/** A condition over a transform's option keys, read over the settings keys they are shown under. */
function underKey(condition: IndicatorInputCondition, prefix: string): IndicatorInputCondition {
  if ('all' in condition) return { all: condition.all.map(item => underKey(item, prefix)) };
  if ('any' in condition) return { any: condition.any.map(item => underKey(item, prefix)) };
  return { ...condition, key: prefix + condition.key };
}

/**
 * The options of the primary series' transform (`Chart.setSeriesTransform`),
 * one control each as the transform declares it, keyed `transform.<option>`
 * under the transform's name. None without a transform. A write that puts an
 * option back to its default drops it from the spec, so the saved state
 * carries only what was chosen and a size left at 0 keeps following the
 * history. An option the transform refuses is skipped, as a stale zone is.
 */
function transformControls(chart: Chart): Control[] {
  const series = chart.primarySeries();
  const spec = series === null ? null : chart.seriesTransform(series);
  if (spec === null) return [];
  const { name, inputs } = getSeriesTransform(spec.type);
  const prefix = 'transform.';
  return inputs.map((option): Control => {
    const key = prefix + option.key;
    const input = { ...option, key, group: name } as IndicatorInput;
    if (option.visibleWhen) input.visibleWhen = underKey(option.visibleWhen, prefix);
    if (option.activeWhen) input.activeWhen = underKey(option.activeWhen, prefix);
    const current = (c: Chart): ReturnType<Chart['seriesTransform']> => {
      const primary = c.primarySeries();
      const now = primary === null ? null : c.seriesTransform(primary);
      return now?.type === spec.type ? now : null;
    };
    return {
      input,
      fields: [{
        key,
        read: (c) => current(c)?.options?.[option.key] ?? (option.default as number | string),
        write: (c, v) => {
          const now = current(c);
          if (now === null) return;
          const options = { ...now.options };
          if (v === option.default) delete options[option.key];
          else options[option.key] = v as number | string;
          try { c.setSeriesTransform(c.primarySeries()!, { type: now.type, options }); } catch { /* refused, as validation says */ }
        },
      }],
    };
  });
}

/**
 * Type-dependent Price controls. Only what the primary series' renderer
 * actually reads: a candle has borders and wicks, a line has a dash, and a
 * baseline has neither, so it gets the shared block alone.
 */
function priceControls(chart: Chart): Control[] {
  const t = chart.theme();
  const type = chart.primarySeriesInfo()?.type;
  const out: Control[] = [];
  // No primary series is no instrument to paint, and every control below writes
  // through `chart.primarySeries()`: with none, the shared block would render
  // three switches that silently write nowhere. That is the case on a chart
  // before its data arrives, and on one whose only series is not a price series
  // (a bare volume histogram or column). An empty tab is the host's to hide; a
  // tab of controls that do nothing is a lie.
  if (type === undefined) return [];
  // What the chart derives its elements from comes before how they are painted.
  out.push(...transformControls(chart));
  if (type === 'candlestick' || type === 'hollow-candle' || type === 'volume-candle') {
    out.push(
      // Body carries a switch like its neighbours: `bodyVisible` skips the fill
      // and leaves the outline and the wick.
      seriesColorPair('symbol.body', 'Body', 'Candles',
        { key: 'upColor', label: 'Up', def: t.upColor },
        { key: 'downColor', label: 'Down', def: t.downColor },
        { key: 'bodyVisible' }),
      seriesColorPair('symbol.borders', 'Borders', 'Candles',
        { key: 'borderUpColor', label: 'Up', def: t.upColor },
        { key: 'borderDownColor', label: 'Down', def: t.downColor },
        { key: 'borderVisible' }),
      seriesColorPair('symbol.wick', 'Wick', 'Candles',
        { key: 'wickUpColor', label: 'Up', def: t.wickUpColor },
        { key: 'wickDownColor', label: 'Down', def: t.wickDownColor },
        { key: 'wickVisible' }),
      prevCloseCtl('Candles'),
    );
  } else if (type === 'bar' || type === 'high-low' || type === 'column') {
    const group = type === 'column' ? 'Columns' : 'Bars';
    out.push(seriesColorPair('symbol.body', type === 'column' ? 'Columns' : 'Bars', group,
      { key: 'upColor', label: 'Up', def: t.upColor },
      { key: 'downColor', label: 'Down', def: t.downColor }));
    // A column is drawn from a base value, not open to close, so it has no
    // previous-close verdict to take: only the two true bar renderers get it.
    if (type !== 'column') out.push(prevCloseCtl(group));
  } else if (type === 'point-figure') {
    // A column of Xs rises and one of Os falls: the renderer's up and down colours.
    out.push(seriesColorPair('symbol.body', 'Boxes', 'Columns',
      { key: 'upColor', label: 'X', def: '#26a69a' },
      { key: 'downColor', label: 'O', def: '#ef5350' }));
  } else if (type === 'kagi') {
    out.push(seriesColorPair('symbol.kagi', 'Line', 'Kagi',
      { key: 'thickColor', label: 'Thick', def: '#26a69a' },
      { key: 'thinColor', label: 'Thin', def: '#ef5350' }));
  } else {
    // Which colour a line-family renderer actually reads is not the same field
    // across the family, and offering the wrong one ships a swatch that moves
    // nothing. A baseline's line is a bullish/bearish *pair* split at the base
    // value (`topColor` / `bottomColor`) and it never reads `color`; an
    // HLC area draws its close line from `closeColor`. Only the plain line,
    // step and area renderers take `color`.
    if (type === 'baseline') {
      out.push(seriesColorPair('symbol.baseline', 'Line', 'Baseline',
        { key: 'topColor', label: 'Above', def: t.baselineTopLine },
        { key: 'bottomColor', label: 'Below', def: t.baselineBottomLine }));
    } else if (type === 'hlc-area') {
      out.push(colorCtl('symbol.closeColor', 'Close line', 'Line', t.lineColor,
        (c) => sty(c).closeColor ?? t.lineColor, (c, v) => setSty(c, { closeColor: v })));
    } else {
      out.push(colorCtl('symbol.color', 'Line', 'Line', t.lineColor, (c) => sty(c).color ?? t.lineColor, (c, v) => setSty(c, { color: v })));
    }
    if (type !== 'histogram') {
      out.push(numCtl(
        'symbol.lineWidth', 'Thickness', 'Line', 1.5, { min: 0.5, max: 8, step: 0.5 },
        (c) => sty(c).lineWidth ?? 1.5, (c, v) => setSty(c, { lineWidth: v }),
      ));
    }
    // The line renderers and the area outline honour a dash; baseline and HLC
    // area stroke with a fixed style, so the control would be inert there.
    if (type === 'line' || type === 'line-markers' || type === 'step' || type === 'area') {
      out.push(selectCtl(
        'symbol.lineStyle', 'Line style', 'Line', 'solid', LINE_STYLES,
        (c) => sty(c).lineStyle ?? 'solid',
        (c, v) => setSty(c, { lineStyle: v as NonNullable<SeriesStyle['lineStyle']> }),
      ));
    }
    if (type === 'area') {
      // Not bullish/bearish, but the same row shape: two colours that are only
      // ever read against each other belong side by side.
      out.push(seriesColorPair('symbol.fill', 'Fill', 'Line',
        { key: 'areaTopColor', label: 'Top', def: t.areaTopColor },
        { key: 'areaBottomColor', label: 'Bottom', def: t.areaBottomColor }));
    } else if (type === 'baseline') {
      // The baseline's two fills are a genuine pair, split at the same base
      // value its line is: one row, matching the line row above it.
      out.push(seriesColorPair('symbol.fill', 'Fill', 'Baseline',
        { key: 'areaTopColor', label: 'Above', def: t.baselineTopFill },
        { key: 'areaBottomColor', label: 'Below', def: t.baselineBottomFill }));
    } else if (type === 'hlc-area') {
      // One band between high and low, so one colour: a pair here would put a
      // second swatch on the row with nothing reading it.
      out.push(colorCtl('symbol.areaTopColor', 'Band', 'Line', HLC_AREA_BAND_COLOR,
        (c) => sty(c).areaTopColor ?? HLC_AREA_BAND_COLOR, (c, v) => setSty(c, { areaTopColor: v })));
    }
  }
  return [...out, ...priceShared()];
}

// ── Readout ───────────────────────────────────────────────────────────────

const TITLE_MODES: readonly { label: string; value: string }[] = [
  { label: 'Symbol', value: 'symbol' },
  { label: 'Description', value: 'description' },
  { label: 'Ticker', value: 'ticker' },
];

/** One status-line switch. Every one defaults to on, matching the primitive. */
function statusSwitch(key: keyof LegendStatusLineOptions, label: string, group: string): Control {
  return boolCtl(
    `statusLine.${key}`, label, group, true,
    (c) => c.statusLineOptions()[key] !== false,
    (c, v) => c.setStatusLineOptions({ [key]: v }),
  );
}

function readoutControls(chart: Chart): Control[] {
  const t = chart.theme();
  return [
    statusSwitch('logo', 'Logo', 'Show'),
    statusSwitch('title', 'Title', 'Show'),
    selectCtl(
      'statusLine.titleMode', 'Title shows', 'Show', 'symbol', TITLE_MODES,
      (c) => c.statusLineOptions().titleMode ?? 'symbol',
      (c, v) => c.setStatusLineOptions({ titleMode: v as LegendTitleMode }),
    ),
    statusSwitch('marketStatus', 'Session state', 'Show'),
    statusSwitch('chartValues', 'Open, high, low, close', 'Show'),
    statusSwitch('barChange', 'Bar change', 'Show'),
    statusSwitch('volume', 'Volume', 'Show'),
    boolCtl(
      'statusLine.openInterest', 'Open interest', 'Show', false,
      (c) => c.statusLineOptions().openInterest === true,
      (c, v) => c.setStatusLineOptions({ openInterest: v }),
    ),
    statusSwitch('lastDayChange', 'Change since previous close', 'Show'),
    statusSwitch('lastValueLabel', 'Indicator values', 'Show'),
    boolCtl(
      'statusLine.indicatorsCollapsed', 'Collapse indicator legends', 'Show', false,
      (c) => c.indicatorLegendCollapsed(),
      (c, v) => c.setIndicatorLegendCollapsed(v),
    ),
    // The plate is the one switch that is off by default: the row has never had
    // one, so turning it on has to be a deliberate choice.
    boolCtl(
      'statusLine.background', 'Background', 'Background', false,
      (c) => c.statusLineOptions().background === true,
      (c, v) => c.setStatusLineOptions({ background: v }),
    ),
    colorCtl(
      'statusLine.backgroundColor', 'Color', 'Background', t.background,
      (c) => c.statusLineOptions().backgroundColor ?? t.background,
      (c, v) => c.setStatusLineOptions({ backgroundColor: v }),
    ),
    numCtl(
      'statusLine.backgroundOpacity', 'Opacity', 'Background', 0.8, { min: 0, max: 1, step: 0.05 },
      (c) => c.statusLineOptions().backgroundOpacity ?? 0.8,
      (c, v) => c.setStatusLineOptions({ backgroundOpacity: v }),
    ),
  ];
}

// ── Axes ──────────────────────────────────────────────────────────────────

/** Keyed by the mode, so a fifth mode fails to compile here until it has a label. */
const SCALE_MODE_LABELS: Readonly<Record<PriceScaleMode, string>> = {
  linear: 'Linear',
  logarithmic: 'Logarithmic',
  percentage: 'Percent',
  'indexed-to-100': 'Indexed to 100',
};
const SCALE_MODES: readonly { label: string; value: string }[] =
  PRICE_SCALE_MODES.map(value => ({ label: SCALE_MODE_LABELS[value], value }));

/**
 * Zones offered by the timezone control, roughly east to west so the list reads
 * like a trading day. IANA names, never fixed offsets: an offset is silently
 * wrong for half the year anywhere that observes DST. A host wanting a longer
 * list can render its own control and call `chart.setTimezone` directly; this is
 * the set a settings dialog can show without a search field.
 */
export const CHART_TIMEZONES: readonly string[] = [
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Moscow',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Singapore',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'Australia/Sydney',
  'America/Sao_Paulo',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
];

/**
 * The zone list with the chart's current one folded in. A chart configured with
 * a zone outside the list (a host is free to pass any IANA name) must still see
 * its own setting selected rather than silently reading as the first entry.
 */
function timezoneOptions(chart: Chart): readonly { label: string; value: string }[] {
  const current = chart.timezone();
  const zones = CHART_TIMEZONES.includes(current) ? CHART_TIMEZONES : [...CHART_TIMEZONES, current];
  return zones.map((zone) => ({ label: zone, value: zone }));
}

/**
 * Whether this chart has a last-price tag for the countdown row to sit in. The
 * countdown is a second line *inside* that tag, so a chart whose only series is
 * a volume histogram or a column has nowhere to draw it: no series there is a
 * price series, so no tag is drawn at all. Absent rather than inert, the same
 * rule the Price tab follows for a colour no renderer reads.
 */
function hasLastPriceTag(chart: Chart): boolean {
  const type = chart.primarySeriesInfo()?.type;
  return type !== undefined && getChartType(type).isPriceSeries;
}

function axesControls(chart: Chart): Control[] {
  const controls: Control[] = [
    boolCtl('navigation.panEnabled', 'Enable panning', 'Navigation', true,
      c => c.navigationOptions().panEnabled !== false,
      (c, v) => c.setNavigationOptions({ panEnabled: v })),
    boolCtl('navigation.zoomEnabled', 'Enable zooming', 'Navigation', true,
      c => c.navigationOptions().zoomEnabled !== false,
      (c, v) => c.setNavigationOptions({ zoomEnabled: v })),
    selectCtl(
      'navigation.mousePan', 'Mouse drag', 'Navigation', 'both',
      [{ label: 'Horizontal only', value: 'horizontal' }, { label: 'Time and price', value: 'both' }],
      (c) => c.navigationOptions().mousePan,
      (c, v) => c.setNavigationOptions({ mousePan: v as ChartNavigationOptions['mousePan'] }),
    ),
    numCtl(
      'navigation.defaultVisibleBars', 'Default visible bars (0 = all)', 'Navigation', 0,
      { min: 0, max: 100000, step: 1 },
      (c) => c.navigationOptions().defaultVisibleBars,
      (c, v) => c.setNavigationOptions({ defaultVisibleBars: v }),
    ),
    numCtl(
      'navigation.defaultBarSpacing', 'Default bar spacing (0 = use bar count)', 'Navigation', 0,
      { min: 0, max: 10000, step: 0.5 },
      (c) => c.navigationOptions().defaultBarSpacing ?? 0,
      (c, v) => c.setNavigationOptions({ defaultBarSpacing: v }),
    ),
    selectCtl(
      'scales.mode', 'Scale', 'Price scale', 'linear', SCALE_MODES,
      (c) => c.priceScaleOptions().mode,
      (c, v) => c.setPriceScaleOptions({ mode: v as PriceScaleMode }),
      'Linear plots the price. Logarithmic gives equal space to equal percentage moves. '
        + 'Percent and Indexed to 100 both rebase to the left edge of the visible range, '
        + 'the first as a change from it, the second as a level starting at 100.',
    ),
    boolCtl(
      'scales.autoScale', 'Auto-fit to the data', 'Price scale', true,
      (c) => c.panes()[c.primaryPaneIndex()]!.priceScale.autoScale, // a chart always holds its price pane
      (c, v) => c.setAutoScale(v),
    ),
    boolCtl(
      'scales.priceOnly', 'Fit primary prices only', 'Price scale', false,
      (c) => c.priceOnlyAutoScale(),
      (c, v) => c.setPriceOnlyAutoScale(v),
    ),
    boolCtl(
      'scales.inverted', 'Invert scale', 'Price scale', false,
      (c) => c.priceScaleOptions().inverted,
      (c, v) => c.setPriceScaleOptions({ inverted: v }),
    ),
    // The zone the axis and the crosshair label in, and the calendar every
    // session-anchored indicator resets on: `setTimezone` recomputes them, so
    // this control moves numbers and not only labels.
    selectCtl(
      'time.timezone', 'Timezone', 'Time axis', DEFAULT_TIMEZONE, timezoneOptions(chart),
      (c) => c.timezone(),
      // A patch is data of unknown provenance (a saved workspace, an older
      // build's zone list), and `setTimezone` throws on a name the runtime does
      // not know. Skipping it keeps one stale zone from losing the whole apply.
      (c, v) => { if (isValidTimezone(v)) c.setTimezone(v); },
      'The calendar the axis and crosshair label in, and the one every session-anchored '
        + 'study resets on. Changing it moves VWAP and pivot values, not only the labels.',
    ),
    // Both default to off, and that is a deliberate library default rather than
    // an oversight. The countdown repaints once a second for as long as the
    // chart is on screen, and it counts against the last bar's close: on the
    // historical range most charts open on, that bar closed months ago, so the
    // cost is real and the reading is not. The corner clock is the wall clock,
    // which says nothing about a chart of last March and is actively wrong on a
    // replay. Both earn their place on a live chart, and that is the host's
    // call to make, so the switches are here for it to make it.
    boolCtl(
      'axisChrome.sessionClock', 'Corner clock', 'Axis chrome', false,
      (c) => c.axisChromeOptions().sessionClock !== undefined && c.axisChromeOptions().sessionClock !== false,
      // `true` means "on as this clock was configured", so a host that chose
      // `showOffset` keeps it across an off and on again (see `Chart`).
      (c, v) => c.setAxisChromeOptions({ sessionClock: v }),
    ),
  ];
  if (hasLastPriceTag(chart)) {
    controls.push(boolCtl(
      'axisChrome.barCountdown', 'Countdown to bar close', 'Axis chrome', false,
      (c) => c.axisChromeOptions().barCountdown === true,
      (c, v) => c.setAxisChromeOptions({ barCountdown: v }),
    ));
  }
  return controls;
}

// ── Appearance ────────────────────────────────────────────────────────────

const CROSSHAIR_MODES: readonly { label: string; value: string }[] = [
  { label: 'Cross', value: 'normal' },
  { label: 'Magnet', value: 'magnet' },
];

function appearanceControls(chart: Chart): Control[] {
  const t = chart.theme();
  const grid = (c: Chart): Partial<GridOptions> => c.gridOptions();
  const cross = (c: Chart): CrosshairOptions => c.canvasOptions().crosshair ?? {};
  const scales = (c: Chart): ScaleCanvasOptions => c.canvasOptions().scales ?? {};
  return [
    boolCtl('watermark.visible', 'Show watermark', 'Watermark', false,
      (c) => c.watermarkOptions().visible ?? false, (c, v) => c.setWatermarkOptions({ visible: v })),
    {
      input: { key: 'watermark.text', type: 'text', label: 'Text (blank uses symbol and interval)', group: 'Watermark', default: '' },
      fields: [{ key: 'watermark.text', read: (c) => c.watermarkOptions().text ?? '', write: (c, v) => c.setWatermarkOptions({ text: String(v) }) }],
    },
    colorCtl('watermark.color', 'Color', 'Watermark', '#9aa4b2',
      (c) => c.watermarkOptions().color ?? '#9aa4b2', (c, v) => c.setWatermarkOptions({ color: v })),
    numCtl('watermark.opacity', 'Opacity', 'Watermark', 0.08, { min: 0, max: 1, step: 0.01 },
      (c) => c.watermarkOptions().opacity ?? 0.08, (c, v) => c.setWatermarkOptions({ opacity: v })),
    numCtl('watermark.fontSize', 'Text size', 'Watermark', 64, { min: 10, max: 200, step: 1 },
      (c) => c.watermarkOptions().fontSize ?? 64, (c, v) => c.setWatermarkOptions({ fontSize: v })),

    boolCtl('canvas.grid.vertLines', 'Vert grid lines', 'Grid', true,
      (c) => c.gridOptions().vertLines, (c, v) => c.setGridOptions({ vertLines: v })),
    colorCtl('canvas.grid.vertColor', 'Vert color', 'Grid', t.grid,
      (c) => grid(c)?.vertColor ?? t.grid, (c, v) => c.setGridOptions({ vertColor: v })),
    selectCtl('canvas.grid.vertStyle', 'Vert style', 'Grid', t.gridStyle ?? 'solid', LINE_STYLES,
      (c) => grid(c)?.vertStyle ?? t.gridStyle ?? 'solid', (c, v) => c.setGridOptions({ vertStyle: v as CanvasLineStyle })),
    boolCtl('canvas.grid.horzLines', 'Horz grid lines', 'Grid', true,
      (c) => c.gridOptions().horzLines, (c, v) => c.setGridOptions({ horzLines: v })),
    colorCtl('canvas.grid.horzColor', 'Horz color', 'Grid', t.grid,
      (c) => grid(c)?.horzColor ?? t.grid, (c, v) => c.setGridOptions({ horzColor: v })),
    selectCtl('canvas.grid.horzStyle', 'Horz style', 'Grid', t.gridStyle ?? 'solid', LINE_STYLES,
      (c) => grid(c)?.horzStyle ?? t.gridStyle ?? 'solid', (c, v) => c.setGridOptions({ horzStyle: v as CanvasLineStyle })),
    numCtl('canvas.grid.lineWidth', 'Width', 'Grid', 1, { min: 1, max: 4, step: 1 },
      (c) => grid(c)?.lineWidth ?? 1, (c, v) => c.setGridOptions({ lineWidth: v })),
    numCtl('canvas.grid.spacing', 'Spacing', 'Grid', 60, { min: 20, max: 200, step: 10 },
      (c) => grid(c)?.spacing ?? 60, (c, v) => c.setGridOptions({ spacing: v })),

    selectCtl('canvas.crosshairMode', 'Mode', 'Crosshair', 'normal', CROSSHAIR_MODES,
      (c) => c.crosshairMode(), (c, v) => c.applyOptions({ crosshairMode: v === 'magnet' ? 'magnet' : 'normal' })),
    boolCtl('canvas.crosshairSnapToBar', 'Snap to candle center', 'Crosshair', false,
      (c) => c.crosshairSnapToBar(), (c, v) => c.applyOptions({ crosshairSnapToBar: v })),
    colorCtl('canvas.crosshair.color', 'Color', 'Crosshair', t.crosshair,
      (c) => cross(c).color ?? t.crosshair, (c, v) => c.setCanvasOptions({ crosshair: { color: v } })),
    selectCtl('canvas.crosshair.style', 'Style', 'Crosshair', t.crosshairStyle ?? 'dashed', LINE_STYLES,
      (c) => cross(c).style ?? t.crosshairStyle ?? 'dashed',
      (c, v) => c.setCanvasOptions({ crosshair: { style: v as CanvasLineStyle } })),
    numCtl('canvas.crosshair.width', 'Width', 'Crosshair', 1, { min: 1, max: 4, step: 1 },
      (c) => cross(c).width ?? t.crosshairWidth ?? 1, (c, v) => c.setCanvasOptions({ crosshair: { width: v } })),

    colorCtl('canvas.scales.textColor', 'Text color', 'Scale text', t.axisText,
      (c) => scales(c).textColor ?? t.axisText, (c, v) => c.setCanvasOptions({ scales: { textColor: v } })),
    numCtl('canvas.scales.fontSize', 'Text size', 'Scale text', t.axisFontSize ?? 11,
      { min: SCALE_FONT_MIN, max: SCALE_FONT_MAX, step: 1 },
      (c) => scales(c).fontSize ?? t.axisFontSize ?? 11, (c, v) => c.setCanvasOptions({ scales: { fontSize: v } })),
    colorCtl('canvas.scales.lineColor', 'Lines color', 'Scale text', t.axisLine,
      (c) => scales(c).lineColor ?? t.axisLine, (c, v) => c.setCanvasOptions({ scales: { lineColor: v } })),

    // Read back from the price scale, not from the option bag: the scale is
    // where the margin actually lives, so this reports what is drawn even when
    // a host set it through `priceScale` instead of the dialog.
    numCtl('canvas.margins.top', 'Top margin %', 'Plot margins', 10, { min: 0, max: 49, step: 1 },
      (c) => pct(c.priceScaleOptions().marginTop), (c, v) => c.setCanvasOptions({ margins: { top: v } })),
    numCtl('canvas.margins.bottom', 'Bottom margin %', 'Plot margins', 10, { min: 0, max: 49, step: 1 },
      (c) => pct(c.priceScaleOptions().marginBottom), (c, v) => c.setCanvasOptions({ margins: { bottom: v } })),
  ];
}

// ── Trading ───────────────────────────────────────────────────────────────

/**
 * The trade layer names a colour twice: `TradingSettings` is the patch shape
 * (`longColor`) and `TradingColors` is the resolved one (`long`), so a control
 * carries both halves rather than deriving one from the other.
 */
function tradingHalf(
  chart: Chart, key: keyof TradingSettings, color: keyof TradingColors, label: string,
): PairHalf {
  return {
    key: `trading.${key}`,
    label,
    def: chart.tradingSettings()[color],
    get: (c) => c.tradingSettings()[color],
    set: (c, v) => c.setTradingSettings({ [key]: v } as TradingSettings),
  };
}

/**
 * Every trade colour the layer draws with. All three rows are genuine
 * bullish/bearish pairs (long against short, take profit against stop loss, buy
 * against sell), which is one row each instead of six stacked swatches; the
 * resting order is the only colour with no opposite.
 */
function tradingControls(chart: Chart): Control[] {
  const half = (key: keyof TradingSettings, color: keyof TradingColors, label: string): PairHalf =>
    tradingHalf(chart, key, color, label);
  return [
    colorPairCtl('trading.positions', 'Position', 'Positions',
      half('longColor', 'long', 'Long'), half('shortColor', 'short', 'Short')),
    colorCtl('trading.orderColor', 'Order', 'Orders', chart.tradingSettings().order,
      (c) => c.tradingSettings().order,
      (c, v) => c.setTradingSettings({ orderColor: v })),
    colorPairCtl('trading.bracket', 'Bracket', 'Orders',
      half('tpColor', 'tp', 'Take profit'), half('slColor', 'sl', 'Stop loss')),
    colorPairCtl('trading.executions', 'Execution', 'Executions',
      half('buyColor', 'buy', 'Buy'), half('sellColor', 'sell', 'Sell')),
  ];
}

/** Every tab with its controls. The one structure schema + read + apply share. */
function buildTabs(chart: Chart): Tab[] {
  return [
    { id: 'price', label: 'Price', controls: priceControls(chart) },
    { id: 'readout', label: 'Readout', controls: readoutControls(chart) },
    { id: 'axes', label: 'Axes', controls: axesControls(chart) },
    { id: 'appearance', label: 'Appearance', controls: appearanceControls(chart) },
    { id: 'trading', label: 'Trading', controls: tradingControls(chart) },
  ];
}

/**
 * The settings dialog, described. Takes the chart because the Price tab depends
 * on the primary series type (a candle has borders, a line has a dash), because
 * the colour defaults come from the live theme, and because the timezone list
 * has to include whatever zone the chart is already in.
 */
export function chartSettingsSchema(chart: Chart): ChartSettingsTab[] {
  return buildTabs(chart).map((tab) => ({ id: tab.id, label: tab.label, inputs: tab.controls.map((c) => c.input) }));
}

/** Current value of every control in the schema, keyed the same way. */
export function readChartSettings(chart: Chart): ChartSettingsValues {
  const out: ChartSettingsValues = {};
  for (const tab of buildTabs(chart)) {
    for (const control of tab.controls) {
      for (const field of control.fields) out[field.key] = field.read(chart);
    }
  }
  return out;
}

/**
 * Apply a patch produced by the dialog. Only the keys present are written, so a
 * single changed control is a one-key object; unknown keys are ignored, which is
 * what lets a state saved by a newer build restore into an older one.
 */
export function applyChartSettings(chart: Chart, patch: Readonly<Partial<ChartSettingsValues>>): void {
  const byKey = new Map<string, Field>();
  const applied: ChartSettingsValues = {};
  for (const tab of buildTabs(chart)) {
    for (const control of tab.controls) {
      for (const field of control.fields) byKey.set(field.key, field);
    }
  }
  for (const key of Object.keys(patch)) {
    const value = patch[key];
    if (value === undefined) continue;
    const field = byKey.get(key);
    if (!field) continue;
    field.write(chart, value);
    applied[key] = field.read(chart);
  }
  const appearance = filterLinkAppearance(applied);
  if (Object.keys(appearance).length) chart.emit('style:change', appearance);
}
