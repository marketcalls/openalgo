/**
 * Indicator runtime (ARCHITECTURE.md §8). Turns an `IndicatorDescriptor` into
 * live chart objects: one series per plot, optional reference levels, an
 * optional fixed pane range, and recomputes them when the source data or the
 * settings change.
 *
 * It adds **no rendering code**. Every plot names a registered chart type, so
 * indicators draw through the same Family-A renderers as any other series.
 */
import type { Bar } from './bar';
import { runAbortable } from './abortable-request';
import { IndicatorAlertPolicy, alertContext, studyBarTime } from './indicator-alert-policy';
import { cloneIndicatorSettings, planIndicatorDependencies, type IndicatorDependencyNode } from './indicator-dependencies';
import { validateIndicatorInputs } from './indicator-inputs';
import { parseIndicatorPolicy, type IndicatorEditOptions, type IndicatorPolicy } from './indicator-policy';
import type { PriceFormat, PriceScaleId, SeriesApi, SeriesDataState } from './series';
import { isPriceScaleId } from './price-axis-layout';
import type { PriceLine } from '../primitives/price-line';
import type { PaneLegend, LegendValue, PaneLegendOptions } from '../primitives/pane-legend';
import { SeriesMarkers } from '../primitives/markers';
import type { ChartTable } from '../primitives/table';
import type { IPrimitive } from '../primitives/primitive';
import type { IndicatorFillSpec, IndicatorPlot } from './indicator-registry';
import { IndicatorFill as IndicatorFillPrimitive } from '../primitives/indicator-fill';
import { IndicatorDrawings } from '../primitives/indicator-draws';
import { IndicatorBackground } from '../primitives/indicator-background';
import { PlotWrites } from './indicator-plot-writes';
import { spliceTail } from './indicator-tail-splice';
import { drawnTime, parseIndicatorBarSource, sampleIndicatorValues, type IndicatorBarSource } from './indicator-bar-source';
import { isPlainObject } from '../helpers/validate';

import { isInvisible, withAlpha } from '../render/pill';
import { DEFAULT_TIMEZONE } from '../feed/time';
import { nextBucketStart, tryResolveInterval } from '../feed/intervals';
import { precisionForStep } from '../scale/ticks';
import {
  indicatorDefaults,
  indicatorStyleInputs,
  plotStyleKeys,
  IndicatorInputError,
  type IndicatorStudySource,
  type IndicatorStudyOutput,
  type IndicatorBarsRequest,
  type IndicatorSnapshotRequest,
  type RequestedBarsSnapshot,
  type IndicatorRequestState,
  type ChartDataContext,
  type IndicatorDataChange,
  type IndicatorDataStatus,
  type IndicatorCalcContext, type IndicatorAttachContext,
  type IndicatorDescriptor,
  type IndicatorLevelContext,
  type IndicatorLineStyle,
  type IndicatorOutputTarget,
  type IndicatorBackgroundSpec,
  type IndicatorSettings,
  type IndicatorStore,
  type IndicatorValues,
} from './indicator-registry';
import type { LooseOptional } from '../helpers/types';

const num = (v: unknown, fallback: number): number =>
  (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

function plotScaleEntries(descriptor: IndicatorDescriptor, input: unknown, clear: boolean): [string, PriceScaleId | null][] {
  if (!isPlainObject(input)) throw new TypeError('Invalid indicator plot price scale map');
  const keys = new Set(descriptor.plots.map(plot => plot.key));
  return Reflect.ownKeys(input).map(key => {
    const property = Object.getOwnPropertyDescriptor(input, key)!;
    if (typeof key !== 'string' || !keys.has(key) || !property.enumerable || !('value' in property)
      || !(isPriceScaleId(property.value) || (clear && property.value === null))) {
      throw new TypeError('Invalid indicator plot price scale assignment');
    }
    return [key, property.value as PriceScaleId | null];
  });
}

/** Internal construction and restore validation, without evaluating caller accessors. */
export function parseIndicatorPlotPriceScales(descriptor: IndicatorDescriptor, input: unknown): Record<string, PriceScaleId> {
  return input === undefined ? {} : Object.fromEntries(plotScaleEntries(descriptor, input, false)) as Record<string, PriceScaleId>;
}

function plotPriceScale(plot: IndicatorPlot, whole: PriceScaleId | null, assignments: Readonly<Record<string, PriceScaleId>>): PriceScaleId {
  return (Object.prototype.hasOwnProperty.call(assignments, plot.key) ? assignments[plot.key] : undefined)
    ?? (plot.overlay === true ? null : whole) ?? plot.priceScaleId ?? 'right';
}

function localPriceScale(descriptor: IndicatorDescriptor, whole: PriceScaleId | null, assignments: Readonly<Record<string, PriceScaleId>>): PriceScaleId {
  const first = descriptor.plots.find(plot => plot.overlay !== true);
  return first ? plotPriceScale(first, whole, assignments) : whole ?? 'right';
}

/**
 * `pricePane` is the slot of the chart's price pane, where an `overlay` plot or
 * band draws. It is a slot, not zero: an on-chart study on a price pane moved
 * below its studies has its own plots and its overlay plots on the same pane,
 * and comparing its slot with zero would call that a band across two panes.
 */
function fillPriceScale(descriptor: IndicatorDescriptor, fill: IndicatorFillSpec, whole: PriceScaleId | null,
  assignments: Readonly<Record<string, PriceScaleId>>, paneIndex: number, pricePane = 0): PriceScaleId | null {
  const a = descriptor.plots.find(plot => plot.key === fill.between[0]);
  const b = descriptor.plots.find(plot => plot.key === fill.between[1]);
  const pane = fill.overlay === true ? pricePane : paneIndex;
  if ((a && (a.overlay === true ? pricePane : paneIndex) !== pane) || (b && (b.overlay === true ? pricePane : paneIndex) !== pane)) return null;
  // Calculated fill columns without plot series follow the first local plot.
  const fallback = fill.overlay === true ? 'right' : localPriceScale(descriptor, whole, assignments);
  const scale = a ? plotPriceScale(a, whole, assignments) : fallback;
  return scale === (b ? plotPriceScale(b, whole, assignments) : fallback) ? scale : null;
}

/** Internal preflight shared by construction and Chart restore before resources change. */
export function validateIndicatorScaleAssignment(descriptor: IndicatorDescriptor, priceScaleId: PriceScaleId | undefined,
  plotPriceScaleIds: Readonly<Record<string, PriceScaleId>> | undefined, paneIndex: number, pricePane = 0): void {
  if (priceScaleId !== undefined && !isPriceScaleId(priceScaleId)) throw new TypeError('Invalid indicator price scale');
  const assignments = parseIndicatorPlotPriceScales(descriptor, plotPriceScaleIds);
  // Omitted assignments retain the legacy descriptor-only fill behavior.
  if (priceScaleId === undefined && Object.keys(assignments).length === 0) return;
  if ((descriptor.fills ?? []).some(fill => fillPriceScale(descriptor, fill, priceScaleId ?? null, assignments, paneIndex, pricePane) === null)) {
    throw new RangeError('Indicator fill endpoints must share their pane and price scale');
  }
}

/** Defaults for the generated per-plot appearance settings. */
function styleDefaults(descriptor: IndicatorDescriptor): IndicatorSettings {
  const out: IndicatorSettings = {};
  for (const input of indicatorStyleInputs(descriptor)) out[input.key] = input.default;
  return out;
}

/**
 * Legend numbers: enough precision to be useful, never a 17-digit float.
 *
 * `tick` is the pane's price step when the pane quotes prices. Given one, the
 * value is formatted to exactly the precision that tick implies, which is the
 * same precision the axis beside it prints.
 *
 * Without it the magnitude ladder below applies, and that ladder is wrong for a
 * price: it rounds anything at or above 1000 to whole numbers, so a Supertrend
 * sitting at 1339.70 on a stock read "1340" in the legend while the axis two
 * inches away read 1339.70. The ladder is still right for the columns it was
 * written for, volume and open interest, where 12345678 has to compact to
 * 12.35M and the trailing paise are noise.
 */
function formatValue(v: number, tick?: number): string {
  if (tick !== undefined && tick > 0) return v.toFixed(precisionForStep(tick));
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}

/** The slice of the chart the runtime needs. Keeps this module testable alone. */
export interface IndicatorHost {
  validateIndicatorSettings?(id: string, descriptor: IndicatorDescriptor, settings: Readonly<IndicatorSettings>): void;
  studyOutput?(source: IndicatorStudySource): Readonly<IndicatorStudyOutput> | undefined;
  indicatorOutputChanged?(id: string, refresh: boolean): void;
  indicatorRecompute?(id: string, refresh: boolean, fallback: () => void): void;
  assignIndicatorScale?(id: string,
    series: readonly { api: SeriesApi; scaleId: PriceScaleId }[],
    primitives: readonly { primitive: IPrimitive; scaleId: PriceScaleId }[],
    commit: () => void): boolean;
  bindIndicatorPrimitiveScale?(primitive: IPrimitive, scaleId: PriceScaleId): void;
  setIndicatorRange?(id: string, paneIndex: number, scaleId: PriceScaleId,
    range: { min: number; max: number } | null, series: readonly SeriesApi[]): void;
  /** Forget a disposed instance, including disposal through its public handle. */
  indicatorRemoved?(instanceId: string, failedOwnedPane?: number): void;
  /** Optional instrument identity and source-range notifications. */
  dataContext?(): Readonly<ChartDataContext> | undefined;
  subscribeDataChanges?(listener: (change: IndicatorDataChange) => void): () => void;
  /** Add the pane-legend row (name + inline up/down/hide/maximize/close). */
  addIndicatorLegend(opts: {
    id: string; title: string; params: string; color?: string; row: number; paneIndex: number;
    /** The descriptor's `hasSource`, so the row can offer a source button. */
    hasSource?: boolean;
  }): PaneLegend;
  removeIndicatorLegend(legend: PaneLegend): void;
  /** How many legends already sit on this pane, so rows stack. */
  legendRowsOn(paneIndex: number): number;
  /** The instrument's own series, for a descriptor anchoring marks to price. */
  primarySeries?(): SeriesApi | null;
  /**
   * A series for one plot. The study writes it with `setData` for a whole pass
   * and, from 2.5.8, with `update` for the points a live tick moved (older
   * points included), so a host's own series must implement both as documented.
   */
  addIndicatorSeries(
    type: string,
    paneIndex: number,
    style: Record<string, unknown> | undefined,
    priceScaleId: string | undefined,
    /** Axis/crosshair formatting for the scale this plot maps to. */
    priceFormat?: PriceFormat,
  ): SeriesApi;
  setIndicatorSeriesType?(series: SeriesApi, type: string): boolean;
  /**
   * Add a reference level. One options object rather than seven positional
   * arguments: the list grew a width and a dash style in 1.7.1, and a call site
   * of seven bare values is where the next one gets passed in the wrong slot.
   */
  addIndicatorLevel(
    level: {
      price: number;
      color: string;
      /**
       * Kept for hosts predating `lineStyle`; always `lineStyle === 'dashed'`.
       *
       * @deprecated Removed in 3.0.0. Read `lineStyle` (since 1.7.1), which
       * also carries `'dotted'`. The instance resolves it before calling the
       * host, so it is never absent.
       */
      dashed: boolean;
      lineWidth: number;
      lineStyle: IndicatorLineStyle;
      label: string;
      id: string;
    },
    paneIndex: number,
  ): PriceLine;
  removeIndicatorLevel(line: PriceLine): void;
  /** Attach a band drawn behind the plots (an Ichimoku cloud). */
  addIndicatorFill(fill: IndicatorFillPrimitive, paneIndex: number): void;
  removeIndicatorFill(fill: IndicatorFillPrimitive): void;
  /**
   * Detach a signal-marker layer. There is no matching `add`: the layer comes
   * from `series.createMarkers()` on a plot's own series, or on the instrument's
   * for marks sent to the candles, so it already lands in the right pane.
   * Removing a series does not remove its primitives, hence this.
   */
  removeIndicatorMarkers(markers: SeriesMarkers): void;
  /** Attach a corner-pinned summary grid to a pane, and detach it again. */
  addIndicatorTable(paneIndex: number): ChartTable;
  removeIndicatorTable(table: ChartTable): void;
  /**
   * Attach an arbitrary primitive to a pane, and detach it again. Carries both
   * the descriptor's drawing layer and whatever a Tier-2 `attach` lifecycle
   * wants to paint, so those two do not need a host method each.
   *
   * Optional, like `timezone`, so a host predating it still satisfies this
   * interface: an indicator that draws simply draws nothing there.
   */
  addIndicatorPrimitive?(primitive: IPrimitive, paneIndex: number): void;
  removeIndicatorPrimitive?(primitive: IPrimitive): void;
  /**
   * Recompute whatever the host has marked stale, before a caller reads a value.
   *
   * Optional, like `timezone`, so a host predating it still satisfies this
   * interface: one that recomputes eagerly has nothing to flush.
   */
  flushIndicators?(): void;
  /**
   * Restore the host's study stack after settings replace series or attached
   * visuals. Also called from inside a calculation pass when that pass first
   * creates a layer for an output target (see `IndicatorOutputTarget`), so the
   * layer takes its study's place among the targeted layers instead of landing
   * above every later study's. During that call the instances report their
   * targeted layers alone, so nothing else moves. It must only restack:
   * recomputing studies from it would run them in the middle of another
   * study's pass.
   */
  resourcesChanged?(): void;
  /** A study's policy changed: the chart redraws its legend buttons and the inventory. */
  policyChanged?(): void;
  /** Bars of the primary price series: the calculation input. */
  sourceBars(): readonly Bar[];
  /**
   * The host's bars under a transformed primary series and the source bar each
   * of `sourceBars` was completed on (null when they are one to one), or null
   * when the chart draws its bars as given. Optional; without it a study on the
   * underlying bars computes on `sourceBars`, and one on the chart's bars is
   * never told they are transformed (`IndicatorCalcContext.transformed`).
   */
  underlyingBars?(): { bars: readonly Bar[]; sourceIndex: readonly number[] | null } | null;
  /** Optional mutation metadata; absent hosts retain the legacy timestamp heuristic. */
  sourceState?(): SeriesDataState | undefined;
  /** Selected candle after native or linked hover; absent means latest. */
  legendIndex?(): number | undefined;
  /** Index of a fresh pane for an indicator that wants its own. */
  nextPaneIndex(): number;
  /**
   * Current slot of the chart's price pane, where an on-chart study and every
   * `overlay` plot, band, table and price-anchored mark draws. Read at each
   * use, since the price pane can be moved below the studies. Optional so a
   * host predating it still satisfies this interface; absent means slot 0.
   */
  primaryPaneIndex?(): number;
  /**
   * The chart's configured IANA zone. Optional so a host predating the option
   * still satisfies this interface; absent means the shipped default.
   *
   * A descriptor is handed bars and settings and never the chart, so this is
   * how the calendar an anchor resets on (a VWAP session, a seasonality month)
   * reaches the calculation. See `IndicatorInstance._descriptorSettings`.
   */
  timezone?(): string;
  /**
   * The instrument and timeframe on screen, when the host knows them. The
   * host can supply an explicit `dataContext` instead. Without either hook,
   * a descriptor sees `undefined` rather than a guessed identity.
   */
  symbol?(): string | undefined;
  interval?(): string | undefined;
  /** Chart wall clock in UTC seconds. Absent means the system clock. */
  now?(): number;
  /**
   * Publish an indicator's per-bar colours onto the **primary price series**,
   * or withdraw them with `null`. `owner` is the instance id: a host holds one
   * overlay at a time and only lets its current owner withdraw it, so a second
   * publisher taking over does not get cleared by the first one's teardown.
   *
   * Optional, like `timezone`: a host that does not implement it simply gives a
   * `barColors` descriptor nowhere to publish, and the indicator's own plots are
   * unaffected.
   */
  setBarColors?(colors: readonly (string | null)[] | null, owner: string): void;
  /** Emit on the chart's event bus (indicator alerts, and `attach`'s own events). */
  emit?(event: string, payload: unknown): void;
  /**
   * Bars of another instrument or interval, from wherever the host keeps its
   * history. Optional: without it the attach context's `requestBars` rejects,
   * which a study reads as "not available on this chart".
   */
  requestBars?(request: IndicatorBarsRequest): Promise<readonly Bar[]>;
  requestSnapshot?(request: IndicatorSnapshotRequest): Promise<RequestedBarsSnapshot>;
  requestState?(): Readonly<IndicatorRequestState>;
  subscribeRequestChanges?(listener: () => void): () => void;
  /**
   * Tick size of the named pane's price scale, or undefined when none is set.
   * Optional so a host predating it still satisfies this interface.
   *
   * Per pane, and the panes genuinely differ: a pane that does not quote the
   * instrument has no tick to report. The price pane (`primaryPaneIndex`) is
   * the one to ask for the instrument's own step.
   */
  tickSize?(paneIndex: number): number | undefined;
  /**
   * Write a number the way the price axis of that pane writes it.
   *
   * The legend sits inches from the axis and names the same quantity, so the
   * two disagreeing is the reading a user has to reconcile themselves. Deriving
   * the format here from a tick got that wrong twice over: a study pane carries
   * no tick at all, so a percentage read `0.618` beside an axis saying `0.62`,
   * and a price pane's tick alone misses the precision floor and the host's own
   * formatter, so a volume study read seven digits where its axis said `1.20M`.
   *
   * Asking the scale removes the second opinion. Optional so a host driving
   * this module alone still works, falling back to the magnitude ladder.
   */
  formatPrice?(paneIndex: number, value: number, series?: SeriesApi): string | undefined;
  /** Pin a pane's price scale to a fixed range, or release it with `null`. */
  setPaneRange(paneIndex: number, range: { min: number; max: number } | null): void;
}

/** Public handle returned by `chart.addIndicator(...)`. */
export interface IndicatorApi {
  /** Whole-study scale override, or null for descriptor assignments. */
  priceScaleId(): PriceScaleId | null;
  /**
   * Move local price resources together; null restores descriptor assignments.
   * False, and nothing changes, for a study whose policy is not `configurable`
   * unless `options.force` is set.
   */
  setPriceScale(scaleId: PriceScaleId | null, options?: IndicatorEditOptions): boolean;
  /** Effective scale for a declared plot, or null for an unknown key. */
  plotPriceScaleId(plotKey: string): PriceScaleId | null;
  /** Detached explicit per-plot assignments, before descriptor and study defaults. */
  plotPriceScaleIds(): Readonly<Record<string, PriceScaleId>>;
  /**
   * Atomically patch plot assignments; null clears an override. Invalid patches
   * return false, and so does a study that is not `configurable` unless forced.
   */
  setPlotPriceScales(assignments: Readonly<Record<string, PriceScaleId | null>>, options?: IndicatorEditOptions): boolean;
  /** The restrictions the host set, only the flags that are false. */
  policy(): Readonly<IndicatorPolicy>;
  /**
   * Replace the policy; null lifts every restriction. The host's act, never
   * restricted itself. Throws on a flag that is not a boolean.
   */
  setPolicy(policy: IndicatorPolicy | null): void;
  /** External data state, or null for a study without a managed lifecycle. */
  dataStatus(): Readonly<IndicatorDataStatus> | null;
  /** Observe changes; immediately receives the current managed status, if any. */
  subscribeDataStatus(listener: (status: Readonly<IndicatorDataStatus>) => void): () => void;
  /** Retry external history when the descriptor supplies a retry action. */
  retryData(): void;
  /** Unique instance id (several instances of one indicator can coexist). */
  readonly id: string;
  /** The descriptor id, e.g. `'macd'`. */
  readonly indicatorId: string;
  /** Display name. */
  readonly name: string;
  /** Pane the indicator drew into. */
  readonly paneIndex: number;
  /** Current settings (a copy). */
  settings(): IndicatorSettings;
  /**
   * Merge a settings patch, recompute, and restyle. False, and nothing changes,
   * when the study is removed, or is not `configurable` and `options.force` is not set.
   */
  setSettings(patch: Readonly<IndicatorSettings>, options?: IndicatorEditOptions): boolean;
  /** The series backing one plot key, for direct styling. */
  series(plotKey: string): SeriesApi | undefined;
  /** Latest computed values (a reference: do not mutate). */
  values(): IndicatorValues;
  /** Whether the plots are drawn (the legend's eye toggle). */
  visible(): boolean;
  /** Show or hide every plot without removing the instance. */
  setVisible(on: boolean): void;
  /** This indicator's legend row, or null if it has none. */
  legend(): PaneLegend | null;
  /** Refresh the legend readings for a bar index; omit for the latest bar. */
  updateLegendValues(index?: number): void;
  /** The bars it computes on: the chart's, or on a transformed chart the host's underlying bars. */
  barSource(): IndicatorBarSource;
  /**
   * Compute on the bars the chart draws (`'chart'`, the default) or the bars
   * the host feeds (`'underlying'`), whose values are then read at the bar
   * each drawn element was completed on. The two are the same bars on a chart
   * with no transform. False when unchanged, or for a study that is not
   * `configurable` unless `options.force` is set; any other value throws.
   */
  setBarSource(source: IndicatorBarSource, options?: IndicatorEditOptions): boolean;
  /**
   * Remove every series, level, and legend row this indicator created. False
   * when it is already gone, or is not `removable` and `options.force` is not set.
   */
  remove(options?: IndicatorEditOptions): boolean;
}

let nextInstance = 1;
let nextGeneration = 1;
/**
 * Set while a pass restacks the host for a routed layer it created. Study order
 * has not changed, so no bar colours need republishing, and doing it there would
 * publish this pass's colours before the pass has succeeded and run every other
 * study's hook against bars its values do not describe yet. It also narrows
 * `renderResources` to routed layers, so that restack moves nothing else.
 */
let restacking = false;

class StudyInputUnavailable extends IndicatorInputError {}

interface StudyBindings {
  snapshots: Map<string, Readonly<IndicatorStudyOutput>>;
  canTail: boolean;
  current(): boolean;
  resolve(source: IndicatorStudySource): readonly (number | null)[];
}

export class IndicatorInstance implements IndicatorApi {
  public readonly id: string;
  public readonly indicatorId: string;
  public readonly name: string;
  /** Mutable: the chart re-indexes this when panes are moved or removed. */
  public paneIndex: number;

  private readonly _host: IndicatorHost;
  private readonly _d: IndicatorDescriptor;
  private readonly _ownPane: boolean;
  private _settings: IndicatorSettings;
  private _scaleOverride: PriceScaleId | null;
  private _plotScaleOverrides: Record<string, PriceScaleId>;
  private _policy: Readonly<IndicatorPolicy>;
  /** Memo for `_descriptorSettings`, keyed on the zone and the settings identity. */
  private _zoned: { zone: string; base: IndicatorSettings; merged: IndicatorSettings } | null = null;
  private readonly _series = new Map<string, SeriesApi>();
  /** The chart type each plot is currently drawn as (settings can override). */
  private readonly _plotTypes = new Map<string, string>();
  /** One band per declared fill, in descriptor order. */
  private readonly _fills: IndicatorFillPrimitive[] = [];
  private _levels: PriceLine[] = [];
  /** Signature of the level list the price lines were built from. */
  private _levelSig = '';
  private _values: IndicatorValues = {};
  /** What each plot series holds, so a tick writes the points that moved. */
  private readonly _writes = new PlotWrites();
  private _barCount = 0;
  /**
   * First and last bar times behind `_values`. `_barCount` alone cannot tell a
   * live tick from a symbol change or a page of history, and both of those can
   * land on a matching count. See `recompute`.
   */
  private _firstTime = 0;
  private _lastTime = 0;
  private _removed = false;
  private readonly _store: IndicatorStore = {};
  private readonly _attachedPrimitives = new Set<IPrimitive>();
  private _detach: (() => void) | null = null;
  private readonly _lifetime = new AbortController();
  private _dataStatus: Readonly<IndicatorDataStatus> | null = null;
  private _dataRetry: (() => void) | null = null;
  private readonly _dataListeners = new Set<(status: Readonly<IndicatorDataStatus>) => void>();
  private _legend: PaneLegend | null = null;
  private _markers: SeriesMarkers | null = null;
  private _markerSeries: SeriesApi | undefined;
  /** Marker layers for explicit targets, each with the series it was created on. */
  private readonly _markerLayers = new Map<string | null, [SeriesMarkers, SeriesApi]>();
  private _table: ChartTable | null = null;
  private _tables = new Map<string, { table: ChartTable; overlay: boolean }>();
  private _draws: IndicatorDrawings | null = null;
  /** Drawing layers for explicit targets: `null` is the price pane, a string names a plot. */
  private readonly _drawLayers = new Map<string | null, IndicatorDrawings>();
  private _background: IndicatorBackground | null = null;
  /** Shading layers for explicit targets, keyed as the drawing layers are. */
  private readonly _bgLayers = new Map<string | null, IndicatorBackground>();
  /**
   * Time of the newest bar the alerts have already judged. Bars at or before it
   * are history as far as this instance is concerned, so a full recompute (a
   * settings change, a page of older bars) re-fires nothing.
   */
  private _alertTime = 0;
  private _alertRead = -Infinity; // the bar the study read at the last element judged or seeded (`studyBarTime`)
  private readonly _alertPolicy: IndicatorAlertPolicy;
  private _calculationEpoch = 0;
  /** Set once a tail-only change lands, which is what a live feed looks like. */
  private _live = false;
  private _sourceId: number | undefined;
  private _sourceRevision: number | null = null;
  private _sourceHistoryRevision: number | null = null;
  private _sourceLastTime: number | undefined;
  private _visible = true;
  /** Set once the constructor's own recompute has passed; see `recompute`. */
  private _constructed = false;
  /** Whether the status currently published is a recompute failure of ours. */
  private _calcFailed = false;
  /** A successful cached calculation cannot settle an unfinished provider lifecycle. */
  private _lifecycleStatus: Readonly<IndicatorDataStatus> | null = null;
  private readonly _generation = nextGeneration++;
  private _outputRevision = 0;
  private _outputHistoryRevision = 0;
  private _outputSource: Readonly<SeriesDataState> | undefined;
  private _studySnapshots = new Map<string, Readonly<IndicatorStudyOutput>>();
  private _dependencyUnavailable = false;
  private _alertNeedsSeed = false;
  private _outputPending = false;
  private _publishedBarColors: readonly (string | null)[] | null = null;
  private _barSource: IndicatorBarSource;
  /** Rebuilt by a restore, which brings back a study its inputs refuse on this chart as it was saved. */
  private readonly _restored: boolean;
  /** The bars a pass on the underlying bars computed on, while its values are read across onto the drawn ones. */
  private _sampled: { bars: readonly Bar[]; sourceIndex: readonly number[] } | null = null;

  public constructor(
    host: IndicatorHost,
    descriptor: IndicatorDescriptor,
    settings: Readonly<IndicatorSettings> = {},
    paneIndex?: number,
    instanceId?: string,
    reservedIds?: ReadonlySet<string>,
    priceScaleId?: PriceScaleId,
    plotPriceScaleIds?: Readonly<Record<string, PriceScaleId>>,
    policy?: IndicatorPolicy,
    barSource?: IndicatorBarSource,
    restored = false,
  ) {
    this._restored = restored;
    this._host = host;
    this._d = descriptor;
    this._barSource = barSource === undefined ? 'chart' : parseIndicatorBarSource(barSource);
    // Before anything is built: the legend row's buttons are chosen by it.
    this._policy = policy === undefined ? Object.freeze({}) : parseIndicatorPolicy(policy);
    this._scaleOverride = priceScaleId ?? null;
    this._plotScaleOverrides = parseIndicatorPlotPriceScales(descriptor, plotPriceScaleIds);
    this.indicatorId = descriptor.id;
    this.name = descriptor.name;
    this._alertPolicy = new IndicatorAlertPolicy(descriptor.alerts ?? []);
    let id = instanceId;
    if (id === undefined) do { id = `${descriptor.id}-${nextInstance++}`; } while (reservedIds?.has(id));
    this.id = id;
    // Declared inputs plus the generated per-plot appearance settings, so every
    // indicator supports colour / opacity / thickness / line style with no
    // per-descriptor boilerplate.
    this._settings = this._validatedSettings({
      ...indicatorDefaults(descriptor),
      ...styleDefaults(descriptor),
      ...cloneIndicatorSettings(settings),
    });

    if (paneIndex !== undefined) {
      this.paneIndex = paneIndex;
      this._ownPane = false;
    } else if (descriptor.placement === 'onchart') {
      this.paneIndex = this._pricePane();
      this._ownPane = false;
    } else {
      this.paneIndex = host.nextPaneIndex();
      this._ownPane = true;
    }

    validateIndicatorScaleAssignment(descriptor, priceScaleId,
      plotPriceScaleIds === undefined ? undefined : this._plotScaleOverrides, this.paneIndex, this._pricePane());

    for (const plot of descriptor.plots) {
      const type = this._plotType(plot);
      this._plotTypes.set(plot.key, type);
      this._series.set(
        plot.key,
        host.addIndicatorSeries(type, this._plotPane(plot), this._plotStyle(plot), this._plotScale(plot), plot.priceFormat),
      );
    }

    for (const fill of descriptor.fills ?? []) {
      const band = new IndicatorFillPrimitive({
        colorUp: this._fillColor(fill, true),
        colorDown: this._fillColor(fill, false),
        opacity: fill.opacity ?? 0.12,
      });
      this._fills.push(band);
      // A band may follow its plots onto the price pane; see `IndicatorFillSpec.overlay`.
      host.addIndicatorFill(band, fill.overlay === true ? this._pricePane() : this.paneIndex);
      const scale = this._fillScale(fill, this._scaleOverride);
      if (scale !== null) host.bindIndicatorPrimitiveScale?.(band, scale);
    }

    this._legend = host.addIndicatorLegend({
      id: `indicator:${this.id}`,
      title: descriptor.name,
      params: this._paramSummary(),
      color: this._legendColor(),
      row: host.legendRowsOn(this.paneIndex),
      paneIndex: this.paneIndex,
      hasSource: descriptor.hasSource === true,
    } satisfies LooseOptional<Parameters<IndicatorHost['addIndicatorLegend']>[0]> as Parameters<IndicatorHost['addIndicatorLegend']>[0]); // `color` may be written undefined, read as absent

    this._applyRange();
    // Levels are applied inside `recompute`, so a data-derived one is built
    // from values that exist rather than from the empty set. This first pass
    // refuses a descriptor that cannot compute at all. Release its resources
    // before propagating the error so a failed add leaves no orphaned legend.
    try { this.recompute(); }
    catch (error) { this.remove({ force: true }); throw error; }
    this._constructed = true;
    this._attach();
  }

  /**
   * Which pane a plot's series belongs on. Normally the indicator's own, but a
   * plot may force itself onto the price pane (`overlay`), so one descriptor can
   * put its study in a pane and its band on the candles.
   */
  private _plotPane(plot: IndicatorPlot): number {
    return plot.overlay === true ? this._pricePane() : this.paneIndex;
  }

  /**
   * The slot the chart's price pane holds right now. Asked each time, never
   * kept: the price pane can be moved below the studies, and a resource made
   * after the move has to land where it went.
   */
  private _pricePane(): number {
    return this._host.primaryPaneIndex?.() ?? 0;
  }

  private _plotScale(plot: IndicatorPlot, override = this._scaleOverride, assignments = this._plotScaleOverrides): PriceScaleId {
    return plotPriceScale(plot, override, assignments);
  }

  private _localScale(override = this._scaleOverride, assignments = this._plotScaleOverrides): PriceScaleId {
    return localPriceScale(this._d, override, assignments);
  }

  private _fillScale(fill: IndicatorFillSpec, override: PriceScaleId | null, paneIndex = this.paneIndex,
    assignments = this._plotScaleOverrides): PriceScaleId | null {
    return fillPriceScale(this._d, fill, override, assignments, paneIndex, this._pricePane());
  }

  /**
   * The targeted layer an output belongs to: `undefined` for the study's own
   * layer, `null` for the price pane, or a declared plot key. It throws while
   * the outputs are being split, before any layer of that kind changes.
   */
  private _targetKey({ plot, overlay }: IndicatorOutputTarget): string | null | undefined {
    if (plot === undefined) return overlay === true ? null : undefined;
    if (overlay === true || !this._d.plots.some(item => item.key === plot)) {
      throw new Error('Indicator output target must name one declared plot or the price pane');
    }
    return plot;
  }

  /** Every target, in the order its layers stack: the price pane, then each plot. */
  private _targets(): (string | null)[] {
    return [null, ...this._d.plots.map(plot => plot.key)];
  }

  /**
   * Split outputs by target. A target that `join` accepts stays with the
   * untargeted outputs, in the order returned, and that list keeps its
   * identity when nothing is routed. Groups come out in target order rather
   * than the order a pass returned them in, so a pass creates layers in the
   * order the host stacks them and a later restack leaves the stack as that
   * pass left it.
   */
  private _route<T extends IndicatorOutputTarget>(items: readonly T[], join?: (key: string | null) => boolean): [readonly T[], Map<string | null, T[]>] {
    const local: T[] = [];
    const groups = new Map<string | null, T[]>(this._targets().map(key => [key, []]));
    for (const item of items) {
      const key = this._targetKey(item);
      (key === undefined || join?.(key) ? local : groups.get(key)!).push(item);
    }
    for (const [key, list] of groups) if (list.length === 0) groups.delete(key);
    return [groups.size > 0 ? local : items, groups];
  }

  /** A price-pane target, or one following a plot that draws on the candles, stays on the price pane. */
  private _overlayTarget(key: string | null): boolean {
    return key === null || this._d.plots.some(plot => plot.key === key && plot.overlay === true);
  }

  /**
   * Pane and scale of a targeted drawing layer. A price-pane shape is in the
   * instrument's units, so it binds no scale and measures on the one scale the
   * price pane quotes prices on, the candles' own (see `_syncDraws`): a fixed
   * id would strand it when the instrument sits on another axis, and would pin
   * that axis in place. It is read from the pane being drawn, never from the
   * candles' series, because the candles can live on another pane.
   */
  private _drawTarget(key: string | null, override = this._scaleOverride, assignments = this._plotScaleOverrides): [number, PriceScaleId | null] {
    const plot = this._d.plots.find(item => item.key === key);
    return plot ? [this._plotPane(plot), this._plotScale(plot, override, assignments)] : [this._pricePane(), null];
  }

  public priceScaleId(): PriceScaleId | null { return this._scaleOverride; }

  public plotPriceScaleId(plotKey: string): PriceScaleId | null {
    const plot = this._d.plots.find(item => item.key === plotKey);
    return plot ? this._plotScale(plot) : null;
  }

  public plotPriceScaleIds(): Readonly<Record<string, PriceScaleId>> { return { ...this._plotScaleOverrides }; }

  public canRelocate(paneIndex: number): boolean {
    return (this._d.fills ?? []).every(fill => this._fillScale(fill, this._scaleOverride, paneIndex) !== null);
  }

  /** Keep a uniform study assignment synchronized with a whole-axis move. */
  public adoptPriceScale(scaleId: PriceScaleId): void {
    this._scaleOverride = scaleId;
    this._plotScaleOverrides = this._overlayScaleOverrides();
  }

  private _overlayScaleOverrides(): Record<string, PriceScaleId> {
    return Object.fromEntries(this._d.plots.filter(plot => plot.overlay === true
      && Object.prototype.hasOwnProperty.call(this._plotScaleOverrides, plot.key)).map(plot => [plot.key, this._plotScaleOverrides[plot.key]!]));
  }

  public policy(): Readonly<IndicatorPolicy> { return this._policy; }

  public barSource(): IndicatorBarSource { return this._barSource; }

  public setBarSource(source: IndicatorBarSource, options?: IndicatorEditOptions): boolean {
    const next = parseIndicatorBarSource(source);
    if (this._removed || next === this._barSource || !this._allows('configurable', options)) return false;
    this._barSource = next;
    this._barCount = 0; // other bars invalidate any calcTail state
    this._requestRecompute(true);
    this._host.emit?.('objects:change', {});
    return true;
  }

  public setPolicy(policy: IndicatorPolicy | null): void {
    const next = policy === null ? Object.freeze({}) : parseIndicatorPolicy(policy);
    if (this._removed) return;
    this._policy = next;
    this._host.policyChanged?.();
  }

  /** Whether a call may make a change the policy reserves for the host. */
  private _allows(flag: keyof IndicatorPolicy, options: IndicatorEditOptions | undefined): boolean {
    return options?.force === true || this._policy[flag] !== false;
  }

  public setPriceScale(scaleId: PriceScaleId | null, options?: IndicatorEditOptions): boolean {
    if (this._removed || !this._allows('configurable', options) || (scaleId !== null && !isPriceScaleId(scaleId))) return false;
    const assignments = this._overlayScaleOverrides();
    if (scaleId === this._scaleOverride && Object.keys(assignments).length === Object.keys(this._plotScaleOverrides).length) return false;
    return this._assignPriceScales(scaleId, assignments, false);
  }

  public setPlotPriceScales(assignments: Readonly<Record<string, PriceScaleId | null>>, options?: IndicatorEditOptions): boolean {
    if (this._removed || !this._allows('configurable', options)) return false;
    let patch: [string, PriceScaleId | null][];
    try { patch = plotScaleEntries(this._d, assignments, true); } catch { return false; }
    const next = new Map(Object.entries(this._plotScaleOverrides));
    let changed = false;
    for (const [key, value] of patch) {
      if (value === null) changed = next.delete(key) || changed;
      else if (next.get(key) !== value) { next.set(key, value); changed = true; }
    }
    return changed && this._assignPriceScales(this._scaleOverride, Object.fromEntries(next), true);
  }

  private _assignPriceScales(scaleId: PriceScaleId | null, assignments: Record<string, PriceScaleId>, overlays: boolean): boolean {
    const plots = this._d.plots.filter(plot => overlays || plot.overlay !== true);
    const destinations = new Map<number, Set<PriceScaleId>>();
    for (const plot of plots) {
      const target = this._plotScale(plot, scaleId, assignments);
      if (target === this._plotScale(plot)) continue;
      const pane = this._plotPane(plot), scales = destinations.get(pane) ?? new Set<PriceScaleId>();
      scales.add(target); destinations.set(pane, scales);
    }
    // Reapply target peers in descriptor order, without touching unrelated or
    // metadata-only assignments and their host-configured formatters.
    const series = plots.flatMap(plot => {
      const target = this._plotScale(plot, scaleId, assignments);
      if (!destinations.get(this._plotPane(plot))?.has(target)) return [];
      const api = this._series.get(plot.key);
      return api ? [{ api, scaleId: target }] : [];
    });
    const primitives: { primitive: IPrimitive; scaleId: PriceScaleId }[] = [];
    for (let i = 0; i < this._fills.length; i++) { // one band per descriptor fill, in order
      const scale = this._fillScale(this._d.fills![i]!, scaleId, this.paneIndex, assignments);
      if (scale === null) return false;
      if ((overlays || this._d.fills![i]!.overlay !== true)
        && scale !== this._fillScale(this._d.fills![i]!, this._scaleOverride)) primitives.push({ primitive: this._fills[i]!, scaleId: scale });
    }
    const local = this._localScale(scaleId, assignments);
    if (local !== this._localScale()) for (const primitive of [...this._levels, this._draws, ...this._attachedPrimitives]) {
      if (primitive !== null) primitives.push({ primitive, scaleId: local });
    }
    for (const [key, primitive] of [...this._drawLayers, ...this._bgLayers]) {
      const scale = this._drawTarget(key, scaleId, assignments)[1];
      if (scale !== null && scale !== this._drawTarget(key)[1]) primitives.push({ primitive, scaleId: scale });
    }
    // Descriptor code can fail or reenter. Resolve it before moving resources,
    // then let a newer settings, pane or assignment owner keep its result.
    const settings = this._settings, previous = this._plotScaleOverrides, whole = this._scaleOverride, paneIndex = this.paneIndex;
    const range = this._host.setIndicatorRange || this._ownPane ? this._d.range?.(this._descriptorSettings()) ?? null : null;
    if (this._removed || settings !== this._settings || previous !== this._plotScaleOverrides
      || whole !== this._scaleOverride || paneIndex !== this.paneIndex) return false;
    const applied = this._host.assignIndicatorScale?.(this.id, series, primitives, () => {
      this._scaleOverride = scaleId;
      this._plotScaleOverrides = assignments;
      this._applyRange(range);
    }) ?? false;
    // A host formatter may throw; geometry and ownership notifications must
    // already describe the completed assignment when that happens.
    if (applied) this.updateLegendValues(this._host.legendIndex?.());
    return applied;
  }

  /**
   * The numeric/select inputs as a compact string (`14 close`), the way a
   * charting legend abbreviates an indicator's configuration. Colors are
   * excluded: the swatch already carries that. Booleans are excluded for the
   * same reason in reverse: a bare `true true true` names nothing, and what a
   * visibility toggle did is already visible on the chart.
   */
  private _paramSummary(): string {
    const out: string[] = [];
    for (const input of this._d.inputs) {
      if (input.type === 'color' || input.type === 'boolean') continue;
      const v = this._settings[input.key];
      if (v === undefined || v === null || v === '') continue;
      if (input.type === 'source' && input.allowStudyOutputs && typeof v === 'object') {
        const source = v as IndicatorStudySource;
        out.push(`${source.instanceId}/${source.plotKey}`);
      } else out.push(String(v));
    }
    return out.join(' ');
  }

  /** First settings-driven plot color, for the legend swatch. */
  private _legendColor(): string | undefined {
    for (const plot of this._d.plots) {
      const key = plot.colorKey;
      if (key !== undefined && typeof this._settings[key] === 'string') return this._settings[key] as string;
      if (typeof plot.style?.color === 'string') return plot.style.color;
    }
    return undefined;
  }

  /** Whether the indicator's plots are drawn. */
  public visible(): boolean {
    return this._visible;
  }

  /** Show or hide every plot without removing the instance (the eye button). */
  public setVisible(on: boolean): void {
    if (this._removed || on === this._visible) return;
    this._visible = on;
    for (const plot of this._d.plots) this._series.get(plot.key)?.applyOptions({ visible: on && plot.style?.visible !== false });
    for (const band of this._fills) band.setVisible(on);
    // Markers are a separate primitive, so hiding the plots does not hide them;
    // re-running the sync clears the layer (or repopulates it) explicitly.
    const bars = this._host.sourceBars();
    this._applyLevels(bars, this._descriptorSettings());
    this._syncMarkers(bars);
    try { this._syncTable(bars); }
    catch (error) {
      // A rejected grid must not interrupt the eye toggle for other resources.
      this._calcFailed = true;
      this._publishStatus({ state: 'error', error });
    }
    this._syncBarColors(bars);
    this._draws?.setVisible(on);
    for (const layer of [...this._drawLayers.values(), ...this._bgLayers.values()]) layer.setVisible(on);
    this._background?.setVisible(on);
    this._legend?.setOptions({ hidden: !on });
    this._host.emit?.('objects:change', {});
  }

  /** The chart calls this when panes are reordered or one is removed. */
  public shiftPane(delta: number): void {
    this.paneIndex += delta;
  }

  /** Owned render resources, with explicit price overlays left on the price pane. */
  public renderResources(): { series: { api: SeriesApi; overlay: boolean }[]; primitives: { primitive: IPrimitive; overlay: boolean }[] } {
    const series = this._d.plots.flatMap(plot => {
      const api = this._series.get(plot.key);
      return api ? [{ api, overlay: plot.overlay === true }] : [];
    });
    const primitives = this._fills.map((primitive, index) => ({ primitive: primitive as IPrimitive, overlay: this._d.fills?.[index]!.overlay === true }));
    for (const { table, overlay } of this._tables.values()) primitives.push({ primitive: table, overlay });
    // A pass's restack hands the host routed layers alone (see `restacking`),
    // so series and every other layer, all of a study that names no target
    // included, stay exactly where they landed.
    if (restacking) {
      series.length = 0;
      primitives.length = 0;
    }
    const own = (...list: (IPrimitive | null)[]): void => {
      for (const primitive of list) if (primitive !== null && !restacking) primitives.push({ primitive, overlay: primitive === this._markers && (this._markerSeries === this._host.primarySeries?.() || series.some(item => item.api === this._markerSeries && item.overlay)) });
    };
    // Each kind's targeted layers follow its own layer in target order, which
    // is where a pass creates them, so restacking keeps a study's first stack
    // and a released target that is used again comes back to the same place.
    const routed = (layer: (key: string | null) => IPrimitive | undefined): void => {
      for (const key of this._targets()) {
        const primitive = layer(key);
        if (primitive) primitives.push({ primitive, overlay: this._overlayTarget(key) });
      }
    };
    own(this._legend, ...this._levels, this._markers);
    routed(key => this._markerLayers.get(key)?.[0]);
    own(this._table, this._draws);
    routed(key => this._drawLayers.get(key));
    own(this._background);
    routed(key => this._bgLayers.get(key));
    own(...this._attachedPrimitives);
    return { series, primitives };
  }

  /** Move the existing instance without rerunning its external attach lifecycle. */
  public relocate(paneIndex: number): void {
    if (this._ownPane && !this._host.setIndicatorRange) this._host.setPaneRange(this.paneIndex, null);
    this.paneIndex = paneIndex;
    this._applyRange();
    this._syncMarkers(this._host.sourceBars());
  }

  /**
   * Republish candle colors after a change in instance stacking order. After a
   * failed pass the hook is not run again: the values are that pass's, or none
   * at all when `calc` threw, and its colours wait for a pass that succeeds.
   */
  public refreshBarColors(): void {
    if (restacking) return;
    if (this._calcFailed) this.republishBarColors();
    else this._syncBarColors(this._host.sourceBars());
  }

  /** Calculation order must not choose the visual color-overlay winner. */
  public republishBarColors(): void {
    if (this._d.barColors) this._host.setBarColors?.(this._publishedBarColors, this.id);
  }

  /** The legend row, for the host to add pane-level actions to the first one. */
  public legend(): PaneLegend | null {
    return this._legend;
  }

  /**
   * Show one reading per plot on the legend row, each in its plot's own color:
   * a multi-plot source (an MA ribbon, MACD) is unreadable as a single number.
   * `index` is the crosshair's bar; omit it for the latest bar.
   */
  public updateLegendValues(index?: number): void {
    if (this._legend === null) return;
    const n = this._barCount;
    const i = index === undefined || index < 0 || index >= n ? n - 1 : index;
    if (i < 0) { this._legend.setValues([]); return; }
    const out: LegendValue[] = [];
    for (const plot of this._d.plots) {
      // A bar-shaped plot's `key` names no column of its own, so the legend
      // reads the close, which is the number a candle legend shows anyway.
      // A shifted plot paints value `i - offset` under bar `i`, and the legend
      // reads what is drawn under the cursor, not what was computed for it.
      const v = this._values[plot.ohlc?.close ?? plot.key]?.[i - (plot.offset ?? 0)];
      if (v === null || v === undefined || !Number.isFinite(v)) continue;
      // The pane this plot draws in, so a plot on its own pane is written the
      // way that pane's axis writes it and not the price pane's.
      const pane = this._plotPane(plot);
      // A plot drawn in a fully transparent colour is on the chart only to be
      // measured against: the invisible mid-body line a marker anchors to, a
      // column a band is filled from. It draws nothing, so it has no number to
      // read, and reading one anyway left a blank the width of a price sitting
      // between the parameters and the first real value. That reads as a
      // broken legend, because from the outside it is one.
      const color = this._plotColor(plot);
      if (color !== undefined && isInvisible(color)) continue;
      const text = this._host.formatPrice?.(pane, v, this._series.get(plot.key))
        ?? formatValue(v, this._host.tickSize?.(pane));
      out.push({ text, color } satisfies LooseOptional<LegendValue> as LegendValue);
    }
    this._legend.setValues(out);
  }

  /** A band's colour: its settings key if it has one, else the declared value. */
  private _fillColor(fill: IndicatorFillSpec, up: boolean): string {
    const key = up ? fill.colorUpKey : fill.colorDownKey;
    const fromSettings = key !== undefined ? this._settings[key] : undefined;
    if (typeof fromSettings === 'string') return fromSettings;
    const declared = up ? fill.colorUp : fill.colorDown;
    return declared ?? (up ? '#26a69a' : '#ef5350');
  }

  /** Feed each band the two plots it spans, on the shared logical index. */
  private _syncFills(bars: readonly Bar[]): void {
    const fills = this._d.fills ?? [];
    const settings = this._descriptorSettings();
    for (let i = 0; i < fills.length; i++) {
      const band = this._fills[i];
      if (band === undefined) continue;
      const spec = fills[i]!;
      const a = this._values[spec.between[0]];
      const b = this._values[spec.between[1]];
      band.setOptions({
        colorUp: this._fillColor(spec, true),
        colorDown: this._fillColor(spec, false),
        opacity: spec.opacity ?? 0.12,
        gradient: typeof spec.gradient === 'function'
          ? spec.gradient({ bars, values: this._values, settings }) : spec.gradient,
      });
      if (a === undefined || b === undefined) { band.setPoints([]); continue; }
      // The band follows its first plot's shift, so a displaced cloud is
      // shaded where its edges are painted rather than where they were computed.
      const shift = this._d.plots.find((p) => p.key === spec.between[0])?.offset ?? 0;
      const pts = [];
      for (let j = 0; j < this._barCount; j++) {
        const first = a[j] ?? null;
        const second = b[j] ?? null;
        const context = { index: j, a: first, b: second, values: this._values, settings };
        const color = spec.colorBy?.(context);
        const gradient = spec.gradientBy?.(context);
        pts.push({ index: j + shift, a: first, b: second, color, gradient });
      }
      band.setPoints(pts);
    }
  }

  /**
   * Refresh the descriptor's signal markers. The layer is created lazily on the
   * first plot's series, so it shares the indicator's pane and price scale,
   * and is only created once the descriptor actually returns a marker, which
   * keeps the common no-marker indicator free of an extra primitive.
   */
  private _syncMarkers(bars: readonly Bar[]): void {
    if (this._dependencyUnavailable) return;
    if (this._d.markers === undefined) return;
    const sampled = this._sampled;
    const all = !this._visible ? [] : this._d.markers({ bars, values: this._values, settings: this._descriptorSettings() })
      .flatMap(mark => {
        const time = sampled === null ? mark.time : drawnTime(mark.time, bars, sampled.bars, sampled.sourceIndex);
        return time === null ? [] : [time === mark.time ? mark : { ...mark, time }];
      });
    const primary = this._host.primarySeries?.() ?? undefined;
    const onPrice = this.paneIndex === this._pricePane();
    const first = (this._d.markerAnchor === 'price' && onPrice ? primary : undefined)
      ?? this._series.get(this._d.plots[0]?.key ?? '');
    const anchor = (key: string | null): SeriesApi | undefined => (key === null ? primary : this._series.get(key));
    // Marks sent to the series the study's own marks already anchor to join
    // that layer, so marks at one bar stack there instead of drawing over each
    // other from two layers, but only where both fill a gap alike: the study's
    // own layer takes the candle while the study is on the price pane, a mark
    // naming a plot while that plot is, so an overlay plot of a study in its
    // own pane keeps a layer of its own.
    const [markers, groups] = this._route(all, key => anchor(key) === first && !(!onPrice && this._overlayTarget(key)));
    // Check every mark before any layer changes, as the drawings do.
    if (groups.size > 0) new SeriesMarkers(0).setMarkers(all);
    let created = false;
    if (this._markers !== null && first !== this._markerSeries) {
      this._host.removeIndicatorMarkers(this._markers);
      this._markers = null;
    }
    if (this._markers === null && markers.length > 0 && first !== undefined) {
      this._markerSeries = first;
      // Only substitute instrument bars when both series share price units.
      // Resolve scales lazily so moving an axis keeps the same guarantee.
      this._markers = first.createMarkers(() => {
        const current = this._host.primarySeries?.();
        return this.paneIndex === this._pricePane() && current != null && first.priceScale() === current.priceScale()
          ? this._host.sourceBars() : [];
      });
    }
    this._markers?.setMarkers(markers);
    // A group is anchored to the candles or to the plot it names. A hidden pass
    // keeps its layer and clears it, so showing the study again refills the
    // same layer; a visible pass releases a vacated group, and a replaced
    // series gets a layer of its own, which the host then restacks.
    for (const [key, [layer, series]] of this._markerLayers) {
      if (series !== anchor(key) || (this._visible && !groups.has(key))) {
        this._host.removeIndicatorMarkers(layer);
        this._markerLayers.delete(key);
      } else if (!this._visible) layer.setMarkers([]);
    }
    for (const [key, list] of groups) {
      let entry = this._markerLayers.get(key);
      const series = anchor(key);
      if (entry === undefined && series !== undefined) {
        // The candles are their own bars and need no fallback; a plot takes
        // them on the same terms as the default layer, judged by its own pane.
        const plot = this._d.plots.find(item => item.key === key);
        created = true;
        this._markerLayers.set(key, entry = [series.createMarkers(plot && (() => {
          const current = this._host.primarySeries?.();
          return this._plotPane(plot) === this._pricePane() && current != null && series.priceScale() === current.priceScale()
            ? this._host.sourceBars() : [];
        })), series]);
      }
      entry?.[0].setMarkers(list);
    }
    this._restack(created);
  }

  /**
   * Refresh the descriptor's summary grid, created lazily on first use so an
   * indicator without the hook never costs an extra primitive.
   */
  private _syncTable(bars: readonly Bar[]): void {
    if (this._dependencyUnavailable) return;
    if (this._d.tables !== undefined) { this._syncTables(bars); return; }
    if (this._d.table === undefined) return;
    const spec = this._visible
      ? this._d.table({ bars, values: this._values, settings: this._descriptorSettings() })
      : null;
    const rows = spec?.rows ?? [];
    if (this._table === null) {
      if (rows.length === 0) return;
      this._table = this._host.addIndicatorTable(this.paneIndex);
    }
    if (spec?.options !== undefined) this._table.setOptions(spec.options);
    this._table.setRows(rows);
  }

  private _syncTables(bars: readonly Bar[]): void {
    if (!this._visible) {
      for (const { table } of this._tables.values()) table.setRows([]);
      return;
    }
    const specs = this._d.tables!({ bars, values: this._values, settings: this._descriptorSettings() });
    const ids = new Set<string>();
    // Reject ambiguous identities before removing or updating a working grid.
    for (const spec of specs) {
      if (typeof spec.id !== 'string' || spec.id.trim() === '' || ids.has(spec.id)) {
        throw new Error('Indicator table IDs must be nonempty and unique');
      }
      ids.add(spec.id);
    }
    for (const [id, { table }] of this._tables) {
      if (ids.has(id)) continue;
      this._host.removeIndicatorTable(table);
      this._tables.delete(id);
    }
    for (const spec of specs) {
      const overlay = spec.overlay === true;
      let entry = this._tables.get(spec.id);
      if (entry !== undefined && entry.overlay !== overlay) {
        this._host.removeIndicatorTable(entry.table);
        this._tables.delete(spec.id);
        entry = undefined;
      }
      if (entry === undefined) {
        entry = { table: this._host.addIndicatorTable(overlay ? this._pricePane() : this.paneIndex), overlay };
        this._tables.set(spec.id, entry);
      }
      if (spec.options !== undefined) entry.table.setOptions(spec.options);
      entry.table.setRows(spec.rows);
    }
  }

  /**
   * Refresh the descriptor's drawings. Rebuilt wholesale on every recompute,
   * the way markers are: a shape is derived geometry, so diffing it against the
   * previous frame would cost more than recreating the list.
   */
  private _syncDraws(bars: readonly Bar[]): void {
    if (this._d.draws === undefined) return;
    const all = this._d.draws({ bars, values: this._values, settings: this._descriptorSettings() });
    const [items, groups] = this._route(all);
    // Check every shape before any layer changes, so a rejected pass leaves
    // each target as the last good one drew it.
    if (groups.size > 0) new IndicatorDrawings().setItems(all);
    if (this._draws === null && items.length > 0 && this._host.addIndicatorPrimitive !== undefined) {
      this._draws = new IndicatorDrawings();
      this._draws.setVisible(this._visible);
      this._host.addIndicatorPrimitive(this._draws, this.paneIndex);
      this._host.bindIndicatorPrimitiveScale?.(this._draws, this._localScale());
    }
    this._draws?.setItems(items);
    this._syncRouted(this._drawLayers, groups,
      (_, scale) => new IndicatorDrawings(scale === null ? rc => rc.readoutPriceScale : undefined), (layer, list) => layer.setItems(list));
  }

  /**
   * Keep one owned layer per target a pass returned, for shapes and shading
   * alike. A vacated target is released rather than kept empty, so a study
   * that stops routing somewhere leaves nothing behind there. Using the target
   * again creates a layer that the host restacks into study order. `make`
   * declines, with null, a target not worth a layer yet.
   */
  private _syncRouted<L extends IndicatorDrawings | IndicatorBackground, G>(layers: Map<string | null, L>, groups: Map<string | null, G>,
    make: (group: G, scale: PriceScaleId | null) => L | null, fill: (layer: L, group: G) => void): void {
    let created = false;
    for (const [key, layer] of layers) {
      if (groups.has(key)) continue;
      this._host.removeIndicatorPrimitive?.(layer);
      layers.delete(key);
    }
    for (const [key, group] of groups) {
      let layer = layers.get(key);
      if (layer === undefined) {
        const [pane, scale] = this._drawTarget(key);
        const made = this._host.addIndicatorPrimitive && make(group, scale);
        if (!made) continue;
        created = true;
        layers.set(key, layer = made);
        layer.setVisible(this._visible);
        this._host.addIndicatorPrimitive!(layer, pane);
        if (scale !== null) this._host.bindIndicatorPrimitiveScale?.(layer, scale);
      }
      fill(layer, group);
    }
    this._restack(created);
  }

  /**
   * A targeted layer created after the first pass is appended above every later
   * study on its pane. The host puts the targeted layers back in study order,
   * which it would otherwise only do on the next settings change or move. Only
   * those move (see `restacking`): series and every study's own layers are left
   * where they land, exactly as before targets existed.
   */
  private _restack(created: boolean): void {
    if (!created || !this._constructed) return;
    restacking = true;
    try { this._host.resourcesChanged?.(); } finally { restacking = false; }
  }

  /**
   * Refresh the pane's per-bar shading, created lazily on first use the way the
   * drawing layer is. Hidden rather than detached when the indicator is hidden,
   * because a regime background is the cheapest layer here to keep around.
   *
   * The list form is told apart by its entries, since the plain form holds
   * colours and gaps only. A targeted layer is created lazily too, on the first
   * column with entries, and kept while its target is returned at all.
   */
  private _syncBackground(bars: readonly Bar[]): void {
    if (this._d.background === undefined) return;
    const out: readonly (string | null | IndicatorBackgroundSpec)[] =
      this._d.background({ bars, values: this._values, settings: this._descriptorSettings() });
    const listed = out.some(item => typeof item === 'object' && item !== null);
    // Every column and target is checked before any shading layer changes; the
    // outputs this pass synced earlier stay applied. `for...of` visits holes,
    // which `every` would skip.
    if (listed) for (const item of out) if (!Array.isArray((item as IndicatorBackgroundSpec | null)?.colors)) {
      throw new Error('Indicator background must return colours or a list of columns');
    }
    const [local, groups] = listed ? this._route(out as readonly IndicatorBackgroundSpec[])
      : [[{ colors: out as readonly (string | null)[] }], new Map<string | null, IndicatorBackgroundSpec[]>()];
    for (const list of [local, ...groups.values()]) if (list.length > 1) throw new Error('Indicator background allows one column per target');
    const colors = local[0]?.colors ?? [];
    if (this._background === null && colors.length > 0 && this._host.addIndicatorPrimitive !== undefined) {
      this._background = new IndicatorBackground();
      this._background.setVisible(this._visible);
      this._host.addIndicatorPrimitive(this._background, this.paneIndex);
    }
    this._background?.setColors(colors, bars);
    this._syncRouted(this._bgLayers, groups, ([spec]) => (spec!.colors.length > 0 ? new IndicatorBackground() : null),
      (layer, [spec]) => layer.setColors(spec!.colors, bars)); // `_route` keeps no empty group, and one spec each passed above
  }

  /**
   * Publish the descriptor's price-bar colours, or withdraw them while hidden.
   * The host owns the arbitration between two publishers (see `setBarColors`);
   * all this side does is state what this instance currently wants.
   */
  private _syncBarColors(bars: readonly Bar[]): void {
    if (this._d.barColors === undefined) return;
    const colors = this._visible && !this._dependencyUnavailable
      ? this._d.barColors({ bars, values: this._values, settings: this._descriptorSettings() })
      : null;
    this._publishedBarColors = colors;
    this._host.setBarColors?.(colors, this.id);
  }

  /**
   * Fire the descriptor's alerts for bars that have appeared since the last
   * pass. The watermark is a bar **time**, not a count: a page of history
   * arriving at the left edge changes every index and would otherwise re-fire
   * the whole chart.
   *
   * Only a tail-only change fires, and each bar it appended is judged in turn,
   * as the newest, once per bar the study read: every element one bar under a
   * transform completed reads it. Any other change replaced history, and an
   * indicator dropped onto a loaded chart (or moved to another symbol) must not
   * announce every crossover of the last two years at once; it reseeds silently.
   */
  private _syncAlerts(bars: readonly Bar[], settings: Readonly<IndicatorSettings>, tailOnly: boolean,
    calculation: IndicatorCalcContext, refresh: boolean, current: () => boolean): void {
    const specs = this._d.alerts;
    const n = bars.length;
    if (specs === undefined || !current()) return;
    const seen = this._alertTime, read = studyBarTime(bars, this._sampled);
    if (n > 0) this._alertTime = bars[n - 1]!.time;
    let from = n;
    if (tailOnly && !refresh) while (from > 0 && bars[from - 1]!.time > seen) from--;
    else this._alertRead = n > 0 ? read(n - 1) : -Infinity;
    let failed = false, failure: unknown;
    for (let i = from; i < n; i++) {
      if (read(i) <= this._alertRead) continue; // judged at an element before this one, in this pass or an earlier one
      this._alertRead = read(i);
      const ctx = alertContext(bars, this._values, settings, i);
      for (const spec of specs) {
        if (spec.frequency !== undefined) continue;
        if (!current()) return;
        try {
          const matches = spec.when(ctx);
          if (!current()) return;
          if (!matches) continue;
          const message = typeof spec.message === 'function' ? spec.message(ctx) : (spec.message ?? spec.title);
          if (!current()) return;
          this._host.emit?.('indicator:alert', {
            indicatorId: this.indicatorId, instanceId: this.id, alertId: spec.id,
            title: spec.title, message, time: bars[i]!.time, index: i,
          });
        } catch (error) {
          if (!current()) return;
          if (!failed) { failed = true; failure = error; }
        }
      }
    }
    if (!current()) return;
    try {
      this._alertPolicy.evaluate({ bars, values: this._values, settings, calculation, tailOnly, refresh, current, from, sampled: this._sampled }, payload => {
        this._host.emit?.('indicator:alert', { ...payload, indicatorId: this.indicatorId, instanceId: this.id });
      });
    } catch (error) {
      if (!failed) { failed = true; failure = error; }
    }
    if (failed && current()) throw failure;
  }

  /**
   * The optional fourth argument to `calc`, rebuilt per recompute because
   * `barState` is the whole reason it exists and it moves every tick.
   *
   * A known interval supplies the bar's duration or calendar boundary. Only
   * legacy hosts without an interval use the observed gap: a session break is
   * not the duration of the first candle after it. Count-driven bars cannot be
   * confirmed from a clock reading.
   */
  private _calcContext(bars: readonly Bar[], appended: boolean, source?: SeriesDataState): IndicatorCalcContext {
    const n = bars.length;
    const now = (): number => this._host.now?.() ?? Date.now() / 1000;
    const interval = this._host.interval?.();
    const timezone = this._host.timezone?.() ?? DEFAULT_TIMEZONE;
    const step = n > 1 ? bars[n - 1]!.time - bars[n - 2]!.time : 0;
    let isConfirmed = n === 0;
    let confirmationSource: NonNullable<IndicatorCalcContext['execution']>['confirmationSource'] = n === 0 ? 'empty' : 'unknown';
    if (n > 0) {
      const open = bars[n - 1]!.time;
      if (interval === undefined) {
        isConfirmed = step <= 0 || now() >= open + step;
        confirmationSource = 'clock';
      } else {
        const bucketing = tryResolveInterval(interval)?.bucketing;
        // Fixed bars can be session-aligned rather than epoch-aligned. Their
        // recorded opening is authoritative; calendar bars use local boundaries.
        const close = bucketing?.mode === 'interval'
          ? (bucketing.seconds > 0 ? open + bucketing.seconds : null)
          : bucketing === undefined ? null : nextBucketStart(bucketing, open, timezone);
        isConfirmed = close !== null && now() >= close;
        if (close !== null) confirmationSource = 'clock';
      }
    }
    if (n > 0 && source?.confirmation !== undefined) {
      isConfirmed = source.confirmation === 'confirmed';
      confirmationSource = source.confirmationSource ?? 'provider';
    }
    const initial = this._sourceRevision === null || source?.sourceId !== this._sourceId;
    const changed = source !== undefined && source.revision !== this._sourceRevision;
    const realtime = source === undefined ? this._live : !initial && changed && source.provenance === 'live';
    return {
      ...(source === undefined ? {} : { execution: {
        sourceId: source.sourceId,
        provenance: source.provenance === 'replay' ? 'replay' as const : realtime ? 'live' as const : 'history' as const,
        change: initial ? 'initial' as const : changed ? source.change : 'refresh' as const,
        revision: source.revision, historyRevision: source.historyRevision, confirmationSource,
      } }),
      barState: {
        isNew: source === undefined ? appended : realtime && n > 0 &&
          (this._sourceLastTime === undefined || bars[n - 1]!.time > this._sourceLastTime),
        isConfirmed,
        isRealtime: realtime,
        lastIndex: n - 1,
      },
      symbol: this._host.symbol?.(),
      interval,
      timezone,
      now,
      // The price pane's, not this indicator's own pane: `calc` runs on the
      // instrument's bars, so the step it sizes a range in is the instrument's,
      // whatever units the pane it draws in happens to read. An oscillator's
      // pane carries no tick at all (see `Chart._scalePatchFor`), so asking it
      // would answer "nobody said" for every study off the price pane, and so
      // would asking slot 0 once a study pane sits above the price pane.
      // 0 is the scale's "infer from the visible range" sentinel, not a tick.
      tickSize: this._host.tickSize?.(this._pricePane()) || undefined,
    } satisfies LooseOptional<IndicatorCalcContext> as IndicatorCalcContext; // unknown members go as undefined, which `calc` reads as absent
  }

  /** The chart type to draw a plot as: the settings override, else declared. */
  private _plotType(plot: IndicatorPlot): string {
    const v = this._settings[plotStyleKeys(plot).type];
    return typeof v === 'string' && v !== '' ? v : plot.type;
  }

  private _plotColor(plot: IndicatorPlot): string | undefined {
    const v = this._settings[plotStyleKeys(plot).color];
    if (typeof v === 'string') return v;
    return typeof plot.style?.color === 'string' ? plot.style.color : undefined;
  }

  /**
   * The series style for a plot: its declared defaults, then the legacy
   * `colorKey`, then the generated appearance settings. Opacity folds into the
   * colour as an alpha, since a canvas stroke has no separate opacity channel.
   */
  private _plotStyle(plot: IndicatorPlot): Record<string, unknown> {
    const k = plotStyleKeys(plot);
    const style: Record<string, unknown> = {
      ...(plot.style ?? {}), title: plot.title, visible: this._visible && plot.style?.visible !== false,
    };
    const color = this._plotColor(plot);
    const opacity = num(this._settings[k.opacity], 100);
    if (color !== undefined) style.color = opacity >= 100 ? color : withAlpha(color, opacity / 100);
    const width = this._settings[k.width];
    if (typeof width === 'number' && width > 0) style.lineWidth = width;
    const lineStyle = this._settings[k.lineStyle];
    if (typeof lineStyle === 'string') style.lineStyle = lineStyle;
    if (plot.offset !== undefined && plot.offset !== 0) style.barOffset = plot.offset;
    return style;
  }

  /**
   * Run the descriptor's optional lifecycle (Tier-2 fetch / subscribe). Re-run
   * on every settings change so an indicator whose data depends on a setting
   * can reload; `_store` persists across the cycle, so a descriptor that caches
   * there can no-op when nothing data-affecting actually changed.
   */
  private _attach(): void {
    this._dataRetry = null;
    const detach = this._d.attach?.({
      dataContext: () => this._host.dataContext?.(),
      subscribeDataChanges: (listener) => this._host.subscribeDataChanges?.(listener) ?? (() => {}),
      signal: this._lifetime.signal,
      setDataStatus: (status) => {
        this._lifecycleStatus = Object.freeze({ ...status });
        this._publishStatus(this._lifecycleStatus);
      },
      setDataRetry: (retry) => { if (!this._removed) this._dataRetry = retry; },
      requestBars: (request) => {
        const provider = this._host.requestBars;
        if (provider === undefined) {
          return Promise.reject(new Error(
            'openalgo-charts: this chart has no bars provider; call chart.setBarsProvider(...) to serve other instruments',
          ));
        }
        return runAbortable(signal => provider.call(this._host, { ...request, signal }), [request.signal, this._lifetime.signal]);
      },
      requestSnapshot: request => runAbortable(signal => {
        const provider = this._host.requestSnapshot;
        if (!provider) throw new Error('Requested snapshots are unsupported by this host');
        return provider.call(this._host, { ...request, signal });
      }, [request.signal, this._lifetime.signal]),
      requestState: this._host.requestState ? () => this._host.requestState!() : undefined,
      subscribeRequestChanges: this._host.subscribeRequestChanges ? listener => this._host.subscribeRequestChanges!(listener) : undefined,
      settings: () => this._descriptorSettings(),
      bars: () => (this._barSource === 'underlying' ? this._host.underlyingBars?.()?.bars : undefined) ?? this._host.sourceBars(),
      requestRecompute: () => {
        if (this._removed) return;
        this._barCount = 0; // external data invalidates any calcTail state
        this._requestRecompute(true);
      },
      store: this._store,
      symbol: () => this._host.symbol?.(),
      interval: () => this._host.interval?.(),
      timezone: () => this._host.timezone?.() ?? DEFAULT_TIMEZONE,
      now: () => this._host.now?.() ?? Date.now() / 1000,
      paneIndex: () => this.paneIndex,
      addPrimitive: (p: IPrimitive) => {
        this._attachedPrimitives.add(p); this._host.addIndicatorPrimitive?.(p, this.paneIndex);
        this._host.bindIndicatorPrimitiveScale?.(p, this._localScale());
      },
      removePrimitive: (p: IPrimitive) => { this._attachedPrimitives.delete(p); this._host.removeIndicatorPrimitive?.(p); },
      emit: (event: string, payload: unknown) => { this._host.emit?.(event, payload); },
    } satisfies LooseOptional<IndicatorAttachContext> as IndicatorAttachContext); // as the calc context: hooks the host lacks go as undefined
    this._detach = typeof detach === 'function' ? detach : null;
  }

  /**
   * Publish the instance's data status once per change. Shared by the attach
   * context's `setDataStatus` and by the recompute guard, so a study's own
   * lifecycle and a failed calculation report through one channel.
   */
  private _publishStatus(status: IndicatorDataStatus): void {
    if (this._removed) return;
    const previous = this._dataStatus;
    if (previous?.state === status.state &&
      (status.state !== 'error' || (previous.state === 'error' && previous.error === status.error))) return;
    this._dataStatus = Object.freeze({ ...status });
    this._outputRevision++;
    this._outputHistoryRevision++;
    this._host.indicatorOutputChanged?.(this.id, true);
    for (const listener of this._dataListeners) listener(this._dataStatus);
    this._host.emit?.('indicator:data-status', {
      id: this.id, indicatorId: this.indicatorId, status: this._dataStatus,
    });
  }

  public dataStatus(): Readonly<IndicatorDataStatus> | null { return this._dataStatus; }

  public subscribeDataStatus(listener: (status: Readonly<IndicatorDataStatus>) => void): () => void {
    if (this._removed) return () => {};
    this._dataListeners.add(listener);
    if (this._dataStatus !== null) listener(this._dataStatus);
    return () => { this._dataListeners.delete(listener); };
  }

  public retryData(): void { if (!this._removed) this._dataRetry?.(); }

  public dependencyNode(): IndicatorDependencyNode {
    return { id: this.id, descriptor: this._d, settings: this._settings };
  }

  public invalidateStudyOutput(): void { this._outputPending = true; }

  private _validatedSettings(settings: Readonly<IndicatorSettings>): IndicatorSettings {
    const copy = cloneIndicatorSettings(settings);
    validateIndicatorInputs(this._d.inputs, copy);
    planIndicatorDependencies([{ id: this.id, descriptor: this._d, settings: copy }]);
    this._host.validateIndicatorSettings?.(this.id, this._d, copy);
    for (const input of this._d.inputs) {
      if (input.type === 'source' && typeof copy[input.key] === 'object' && copy[input.key] !== null) Object.freeze(copy[input.key]);
    }
    return copy;
  }

  public studyOutput(plotKey: string): Readonly<IndicatorStudyOutput> | undefined {
    const plot = this._d.plots.find(item => item.key === plotKey);
    if (!plot || plot.ohlc) return undefined;
    return {
      generation: this._generation, revision: this._outputRevision, historyRevision: this._outputHistoryRevision,
      source: this._outputSource, values: this._values[plotKey] ?? [],
      available: !this._removed && this._outputRevision > 0 && !this._outputPending && !this._calcFailed && !this._dependencyUnavailable
        && (this._lifecycleStatus === null || this._lifecycleStatus.state === 'ready'),
    } satisfies LooseOptional<IndicatorStudyOutput> as IndicatorStudyOutput; // `source` is undefined before the first source write
  }

  private _studyBindings(bars: readonly Bar[], source: SeriesDataState | undefined): StudyBindings {
    const edges = planIndicatorDependencies([this.dependencyNode()]).dependencies.get(this.id) ?? [];
    const snapshots = new Map<string, Readonly<IndicatorStudyOutput>>();
    const columns = new Map<string, readonly (number | null)[]>();
    let canTail = this._studySnapshots.size === edges.length;
    for (const { inputKey, source: reference } of edges) {
      const output = this._host.studyOutput?.(reference);
      if (!output?.available || output.values.length !== bars.length ||
        (source !== undefined && (output.source?.sourceId !== source.sourceId ||
          output.source.revision !== source.revision || output.source.historyRevision !== source.historyRevision))) {
        throw new StudyInputUnavailable(`Study input ${inputKey} is unavailable: ${reference.instanceId}/${reference.plotKey}`);
      }
      snapshots.set(inputKey, output);
      columns.set(inputKey, Object.freeze(output.values.slice()));
      const previous = this._studySnapshots.get(inputKey);
      if (!previous || previous.generation !== output.generation || previous.historyRevision !== output.historyRevision
        || previous.revision > output.revision) canTail = false;
    }
    return {
      snapshots, canTail,
      current: () => edges.every(({ inputKey, source: reference }) => {
        const previous = snapshots.get(inputKey)!;
        const current = this._host.studyOutput?.(reference);
        return current?.available === true && previous.generation === current.generation
          && previous.revision === current.revision && previous.historyRevision === current.historyRevision;
      }),
      resolve: reference => {
        const edge = edges.find(item => item.source.instanceId === reference.instanceId && item.source.plotKey === reference.plotKey);
        if (!edge) throw new IndicatorInputError('Study source must be declared by an opted-in input');
        return columns.get(edge.inputKey)!;
      },
    };
  }

  private _requestRecompute(refresh: boolean): void {
    if (this._host.indicatorRecompute) this._host.indicatorRecompute(this.id, refresh, () => this.recompute(refresh));
    else this.recompute(refresh);
  }

  private _clearUnavailableOutput(bars: readonly Bar[]): void {
    this._dependencyUnavailable = true;
    this._alertNeedsSeed = true;
    this._studySnapshots.clear();
    const keys = new Set([...Object.keys(this._values), ...this._d.plots.map(plot => plot.key)]);
    this._values = Object.fromEntries([...keys].map(key => [key, new Array<null>(bars.length).fill(null)]));
    this._barCount = 0;
    this._outputHistoryRevision++;
    for (const series of this._series.values()) this._writes.clear(series);
    for (const fill of this._fills) fill.setPoints([]);
    this._markers?.setMarkers([]);
    for (const [layer] of this._markerLayers.values()) layer.setMarkers([]);
    this._table?.setRows([]);
    for (const { table } of this._tables.values()) table.setRows([]);
    this._draws?.setItems([]);
    for (const layer of this._drawLayers.values()) layer.setItems([]);
    for (const layer of [this._background, ...this._bgLayers.values()]) layer?.setColors([], bars);
    for (const level of this._levels) this._host.removeIndicatorLevel(level);
    this._levels = [];
    this._publishedBarColors = null;
    this._host.setBarColors?.(null, this.id);
    this.updateLegendValues();
  }

  public settings(): IndicatorSettings {
    return cloneIndicatorSettings(this._settings);
  }

  /**
   * Settings as a *descriptor* sees them: the chart's zone rides along under
   * the reserved `timezone` key, because a `calc` is handed settings and never
   * the chart.
   *
   * It is deliberately not folded into `_settings`. That object is the user's
   * own values, it is what `settings()` returns and what `getState()` persists,
   * and baking the zone into it would mean a layout saved on a New York chart
   * kept computing on New York after being restored onto an IST one, silently
   * out of step with the axis beside it.
   *
   * The default zone returns `_settings` untouched, so every existing caller
   * allocates nothing and computes exactly what it computed before.
   */
  private _descriptorSettings(): Readonly<IndicatorSettings> {
    const zone = this._host.timezone?.() ?? DEFAULT_TIMEZONE;
    if (zone === DEFAULT_TIMEZONE) return this._settings;
    const cached = this._zoned;
    // `_settings` is replaced wholesale by `setSettings`, so identity is a
    // sufficient staleness check and costs one compare per recompute.
    if (cached !== null && cached.zone === zone && cached.base === this._settings) return cached.merged;
    const merged = { ...this._settings, timezone: zone };
    this._zoned = { zone, base: this._settings, merged };
    return merged;
  }

  public series(plotKey: string): SeriesApi | undefined {
    return this._series.get(plotKey);
  }

  public values(): IndicatorValues {
    // The host defers recompute to the frame, so a caller that updates a bar and
    // reads the value back in the same turn would otherwise get the previous
    // tick's numbers. Flushing here keeps the read synchronous without putting
    // the maths back on the data-update path.
    this._host.flushIndicators?.();
    return this._values;
  }

  public setSettings(patch: Readonly<IndicatorSettings>, options?: IndicatorEditOptions): boolean {
    if (this._removed || !this._allows('configurable', options)) return false;
    this._settings = this._validatedSettings({ ...this._settings, ...cloneIndicatorSettings(patch) });
    this._outputPending = true;
    this._host.indicatorOutputChanged?.(this.id, true);
    // Restyle before recomputing: appearance is independent of the maths, so a
    // colour or thickness change must not wait on a full recalculation.
    for (const plot of this._d.plots) {
      // Native hosts can retain the handle while changing its renderer.
      // Older hosts keep their existing series-recreation path.
      const wanted = this._plotType(plot);
      if (wanted !== this._plotTypes.get(plot.key)) {
        const current = this._series.get(plot.key);
        if (current && this._host.setIndicatorSeriesType?.(current, wanted)) {
          current.applyOptions(this._plotStyle(plot) as never);
          this._plotTypes.set(plot.key, wanted);
          continue;
        }
        this._series.get(plot.key)?.remove();
        this._series.set(
          plot.key,
          this._host.addIndicatorSeries(wanted, this._plotPane(plot), this._plotStyle(plot), this._plotScale(plot), plot.priceFormat),
        );
        this._plotTypes.set(plot.key, wanted);
        continue;
      }
      this._series.get(plot.key)?.applyOptions(this._plotStyle(plot) as never);
    }
    this._legend?.setOptions({ params: this._paramSummary(), color: this._legendColor() } satisfies LooseOptional<Partial<PaneLegendOptions>> as Partial<PaneLegendOptions>);
    this._applyRange();
    this._values = {};
    this._barCount = 0; // force a full recompute; settings invalidate any tail state
    this._requestRecompute(true);
    this._detach?.();
    this._attach();
    this._host.resourcesChanged?.();
    this._host.emit?.('objects:change', {});
    return true;
  }

  /**
   * Recompute from the host's source bars. Uses the descriptor's `calcTail`
   * when only the tail moved (a live tick) and it declares one; otherwise a
   * full `calc`.
   */
  public recompute(refresh = false): void {
    if (this._removed) return;
    const epoch = ++this._calculationEpoch;
    const settingsIdentity = this._settings;
    const source = this._host.sourceState?.();
    const shown = this._host.sourceBars();
    const under = this._barSource === 'underlying' ? this._host.underlyingBars?.() ?? null : null;
    const bars = under?.bars ?? shown;
    const sourceIndex = under?.sourceIndex ?? null;
    let bindings: StudyBindings | undefined;
    const current = (): boolean => {
      if (this._removed || epoch !== this._calculationEpoch || settingsIdentity !== this._settings) return false;
      if (bindings && !bindings.current()) return false;
      const latest = this._host.sourceState?.();
      return source === undefined ? latest === undefined : latest !== undefined
        && source.sourceId === latest.sourceId && source.revision === latest.revision
        && source.historyRevision === latest.historyRevision && source.provenance === latest.provenance;
    };
    try {
      bindings = this._studyBindings(bars, source);
      this._recompute(refresh, bars, sourceIndex === null ? bars : shown, sourceIndex, source, bindings, current);
    } catch (error) {
      if (!current()) return;
      if (!this._constructed && !(error instanceof StudyInputUnavailable)
        && !(this._restored && error instanceof IndicatorInputError)) throw error;
      if (error instanceof StudyInputUnavailable) this._clearUnavailableOutput(sourceIndex === null ? bars : shown);
      // One study's bad input must not stall the frame for every other one, and
      // a study that silently stops drawing tells the user nothing. So the
      // failure goes where a Tier-2 fetch failure already goes, the previous
      // plots stay up, and the next recompute that succeeds clears it.
      this._calcFailed = true;
      this._publishStatus({ state: 'error', error });
      this._host.indicatorOutputChanged?.(this.id, true);
      return;
    }
    // A callback can complete a newer pass. Its status owns recovery too.
    if (!current()) return;
    if (this._calcFailed) {
      this._calcFailed = false;
      this._publishStatus(this._lifecycleStatus ?? { state: 'ready' });
    }
    if (current()) this._host.indicatorOutputChanged?.(this.id, refresh);
  }

  /**
   * `calc` is what the study computes on and `bars` what it draws on: the same
   * bars unless it computes on the bars under a transform, when `sourceIndex`
   * reads its values across and the tail path, which splices by calculation
   * index, is not taken.
   */
  private _recompute(refresh: boolean, calc: readonly Bar[], bars: readonly Bar[], sourceIndex: readonly number[] | null,
    source: SeriesDataState | undefined, bindings: StudyBindings, current: () => boolean): void {
    const n = bars.length;
    // Resolved once: the zone is fixed for the frame, and calc, calcTail and
    // every colorBy below must be told the same calendar.
    const settings = this._descriptorSettings();

    let values: IndicatorValues | null = null;
    // The tail path is only valid when the previous result still describes every
    // bar before the tail. A bar count of `n` or `n + 1` does not say that: a
    // page of history arriving at the left edge, or a symbol change, can land on
    // a matching count and would then splice new values onto a history that no
    // longer exists, leaving the plot silently wrong until the next full calc.
    // Native revisions retain historical invalidation across coalesced writes,
    // and let the last bar sit at its index with a later time: a transformed
    // chart's forming element, dated at a newer source bar. Hosts without them
    // retain the timestamp heuristic: the first bar is unchanged and the last
    // is replaced or followed by new bars.
    const last = this._barCount > 0 && n >= this._barCount ? bars[this._barCount - 1]!.time : NaN;
    const kept = (last === this._lastTime || (source !== undefined && last > this._lastTime))
      && (this._barCount === 1 || bars[0]!.time === this._firstTime);
    const appended = kept && n > this._barCount;
    const tailOnly = kept && (source === undefined || (source.sourceId === this._sourceId && source.revision !== this._sourceRevision &&
      source.historyRevision === this._sourceHistoryRevision && source.provenance === 'live'));
    // Older hosts have no mutation provenance and retain the live heuristic.
    if (source === undefined && tailOnly) this._live = true;
    if (tailOnly && last > this._lastTime) this._redate(last, calc === bars);
    const ctx = this._calcContext(calc, appended, source);
    ctx.resolveSource = bindings.resolve;
    // The chart's own bars on a transformed series are its elements, not time bars.
    if (this._barSource === 'chart' && (this._host.underlyingBars?.() ?? null) !== null) ctx.transformed = true;
    let usedTail = false;
    // One appended bar at most: more (a frame's burst of ticks, or the bricks one source bar completes) take a full `calc`.
    if (tailOnly && n <= this._barCount + 1 && sourceIndex === null && bindings.canTail && this._d.calcTail !== undefined) {
      const from = this._barCount - 1; // the previously-last bar may have been replaced
      const tail = this._d.calcTail(calc, settings, from, this._values, this._store, ctx);
      if (tail !== null) { values = spliceTail(this._values, tail, from, n); usedTail = true; }
    }
    if (values === null) values = this._d.calc(calc, settings, this._store, ctx);
    if (!current()) return;
    if (sourceIndex !== null) values = sampleIndicatorValues(values, sourceIndex);
    this._sampled = sourceIndex === null ? null : { bars: calc, sourceIndex };

    this._values = values;
    this._outputPending = false;
    this._dependencyUnavailable = false;
    this._studySnapshots = bindings.snapshots;
    this._outputRevision++;
    if (!usedTail) this._outputHistoryRevision++;
    this._outputSource = source ? { ...source } : undefined;
    this._barCount = n;
    this._firstTime = n > 0 ? bars[0]!.time : 0;
    this._lastTime = n > 0 ? bars[n - 1]!.time : 0;
    if (source !== undefined) {
      this._sourceId = source.sourceId;
      this._sourceRevision = source.revision;
      this._sourceHistoryRevision = source.historyRevision;
      this._sourceLastTime = calc[calc.length - 1]?.time;
    }

    this._writes.begin(bars);
    for (const plot of this._d.plots) {
      const series = this._series.get(plot.key);
      if (series === undefined) continue;
      if (plot.ohlc !== undefined) this._writes.writeCandles(series, plot, plot.ohlc, bars, values, settings, this.indicatorId);
      else this._writes.writeValues(series, plot, values[plot.key], bars, values, settings);
    }
    this._syncFills(bars);
    this._syncMarkers(bars);
    this._syncTable(bars);
    this._syncDraws(bars);
    this._syncBackground(bars);
    this._syncBarColors(bars);
    this._applyLevels(bars, settings);
    if (this._alertNeedsSeed) {
      this._alertNeedsSeed = false;
      const seed = { ...ctx, execution: ctx.execution ? { ...ctx.execution, provenance: 'history' as const } : undefined } satisfies LooseOptional<IndicatorCalcContext> as IndicatorCalcContext;
      this._syncAlerts(bars, settings, false, seed, false, current);
    } else this._syncAlerts(bars, settings, tailOnly, ctx, refresh, current);
    if (!current()) return;
    this.updateLegendValues(this._host.legendIndex?.());
  }

  /**
   * The bar the last pass ended on, dated again at `time`: a transformed
   * chart's forming element moved forward by a newer source bar. It is the
   * same bar, so what the alerts and `barState.isNew` said of it holds there;
   * `own` when the calculation runs on these bars, not the ones under them,
   * which are never dated again and keep a study's checkpoints where they were.
   */
  private _redate(time: number, own: boolean): void {
    if (this._alertTime === this._lastTime) this._alertTime = time;
    if (own) { this._sourceLastTime = time; this._alertPolicy.redate(this._lastTime, time); }
  }

  /**
   * Rebuild the reference levels. Runs after every `calc` so a data-derived
   * level (the previous day's high, a session VWAP band) follows the data, but
   * the great majority of levels are constants, so a signature compare keeps a
   * live tick from detaching and reattaching a price line per level per bar.
   */
  private _applyLevels(bars: readonly Bar[], settings: Readonly<IndicatorSettings>): void {
    if (this._d.levels === undefined) return;
    // The context spreads the settings keys onto itself so descriptors written
    // against the original `levels(settings)` signature read what they always
    // did. See `IndicatorLevelContext`.
    const ctx: IndicatorLevelContext = { ...settings, settings, bars, values: this._values };
    const levels = this._visible ? this._d.levels(ctx) : [];
    let sig = '';
    for (const l of levels) {
      sig += `${l.price}|${l.color ?? ''}|${l.title ?? ''}|${l.dashed ?? ''}|${l.lineWidth ?? ''}|${l.lineStyle ?? ''};`;
    }
    if (sig === this._levelSig) return;
    this._levelSig = sig;
    for (const line of this._levels) this._host.removeIndicatorLevel(line);
    this._levels = [];
    let i = 0;
    for (const l of levels) {
      // `dashed` predates `lineStyle` and stays the fallback, defaulting to a
      // dashed line the way every built-in level already draws.
      const lineStyle: IndicatorLineStyle = l.lineStyle ?? (l.dashed === false ? 'solid' : 'dashed');
      this._levels.push(
        this._host.addIndicatorLevel(
          {
            price: l.price,
            color: l.color ?? '#8892a6',
            dashed: lineStyle === 'dashed',
            lineWidth: l.lineWidth ?? 1,
            lineStyle,
            label: l.title ?? '',
            id: `${this.id}:level:${i++}`,
          },
          this.paneIndex,
        ),
      );
      this._host.bindIndicatorPrimitiveScale?.(this._levels[this._levels.length - 1]!, this._localScale()); // the one just pushed
    }
  }

  private _applyRange(range?: { min: number; max: number } | null): void {
    if (this._host.setIndicatorRange) {
      const local = this._d.plots.filter(plot => plot.overlay !== true).flatMap(plot => {
        const series = this._series.get(plot.key);
        return series ? [series] : [];
      });
      this._host.setIndicatorRange(this.id, this.paneIndex, this._localScale(),
        range === undefined ? this._d.range?.(this._descriptorSettings()) ?? null : range, local);
      return;
    }
    if (!this._ownPane) return; // a shared pane belongs to whoever created it
    this._host.setPaneRange(this.paneIndex, range === undefined ? this._d.range?.(this._descriptorSettings()) ?? null : range);
  }

  public remove(options?: IndicatorEditOptions): boolean {
    if (this._removed || !this._allows('removable', options)) return false;
    this._removed = true;
    this._lifetime.abort();
    this._dataRetry = null;
    this._dataListeners.clear();
    try { this._detach?.(); } catch { /* External cleanup cannot retain the indicator's chart resources. */ }
    this._detach = null;
    for (const primitive of this._attachedPrimitives) this._host.removeIndicatorPrimitive?.(primitive);
    this._attachedPrimitives.clear();
    if (this._legend !== null) { this._host.removeIndicatorLegend(this._legend); this._legend = null; }
    for (const line of this._levels) this._host.removeIndicatorLevel(line);
    this._levels = [];
    for (const series of this._series.values()) series.remove();
    this._series.clear();
    for (const band of this._fills) this._host.removeIndicatorFill(band);
    this._fills.length = 0;
    if (this._markers !== null) { this._host.removeIndicatorMarkers(this._markers); this._markers = null; }
    for (const [layer] of this._markerLayers.values()) this._host.removeIndicatorMarkers(layer);
    this._markerLayers.clear();
    if (this._table !== null) { this._host.removeIndicatorTable(this._table); this._table = null; }
    for (const { table } of this._tables.values()) this._host.removeIndicatorTable(table);
    this._tables.clear();
    if (this._draws !== null) { this._host.removeIndicatorPrimitive?.(this._draws); this._draws = null; }
    for (const layer of [...this._drawLayers.values(), ...this._bgLayers.values()]) this._host.removeIndicatorPrimitive?.(layer);
    this._drawLayers.clear();
    this._bgLayers.clear();
    if (this._background !== null) { this._host.removeIndicatorPrimitive?.(this._background); this._background = null; }
    this._host.setIndicatorRange?.(this.id, this.paneIndex, this._localScale(), null, []);
    // Withdraw the candle colours before anything else forgets who owned them.
    if (this._d.barColors !== undefined) this._host.setBarColors?.(null, this.id);
    if (this._ownPane && !this._host.setIndicatorRange) this._host.setPaneRange(this.paneIndex, null);
    this._host.indicatorRemoved?.(this.id, !this._constructed && this._ownPane ? this.paneIndex : undefined);
    return true;
  }
}
