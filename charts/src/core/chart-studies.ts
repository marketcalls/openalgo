/**
 * The study host: adding, moving, reordering and removing studies, the
 * `IndicatorHost` every study instance talks to, the deferred recompute with
 * its dependency queue, the price-scale ranges studies claim, and the colour
 * overlay a study can put on the price bars.
 *
 * Its own module because this is the one seam between the chart and the
 * indicator runtime, and the recompute state (the pass in flight, what it has
 * processed, the overlay's owner and the bars' own colours) belongs to these
 * methods alone. The chart reaches it through `Chart._studies`, and it reaches
 * the chart through `StudiesHost`. The chart instance itself comes in beside
 * the host, because the replay window is looked up by the chart's identity
 * and would not be found under any other object. `addIndicator`,
 * `indicators`, `moveIndicator`, `reorderIndicator` and `removeIndicator`
 * stay public on Chart as delegates and carry the documented contract, and
 * `Chart._indicatorHost` stays as a delegate because the restore and tests
 * build a host through it by name. Members the chart calls are public on this
 * internal class; no entry point exports the class and the chart holds it in
 * a private field, so none of it reaches the published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Chart } from './chart';
import type { AddIndicatorOptions } from './chart-types';
import type { PreservedScaleFormats } from './chart-state';
import type { Pane } from './pane';
import type { PriceScale } from '../scale/price-scale';
import type { SeriesApi, PriceScaleId } from '../model/series';
import { isPriceScaleId } from '../model/price-axis-layout';
import { replayWindow, observeReplayWindow } from '../model/replay-window';
import { runAbortable } from '../model/abortable-request';
import { cloneIndicatorSettings, planIndicatorDependencies } from '../model/indicator-dependencies';
import type { SeriesType } from '../model/chart-type-registry';
import { getIndicator, plotStyleKeys, type IndicatorDescriptor, type IndicatorRequestState, type IndicatorSettings } from '../model/indicator-registry';
import {
  IndicatorInstance, parseIndicatorPlotPriceScales, validateIndicatorScaleAssignment, type IndicatorApi, type IndicatorHost,
} from '../model/indicator-instance';
import { parseIndicatorPolicy, type IndicatorEditOptions } from '../model/indicator-policy';
import { validateIndicatorInputs } from '../model/indicator-inputs';
import { parseIndicatorBarSource } from '../model/indicator-bar-source';
import type { SeriesStyle } from '../render/series-style';
import type { Bar } from '../model/bar';
import type { IPrimitive } from '../primitives/primitive';
import type { PriceLine, PriceLineOptions } from '../primitives/price-line';
import { PaneLegend, type PaneLegendAction } from '../primitives/pane-legend';
import { ChartTable } from '../primitives/table';
import type { LooseOptional } from '../helpers/types';

/**
 * Colours the 2nd and later instances of the same indicator rotate through.
 * Chosen to stay apart on both dark and light panes and to read as distinct at
 * a 1px stroke, which rules out near-neighbour hues.
 */
const INSTANCE_PALETTE: readonly string[] = [
  '#f5a623', '#26a69a', '#ab47bc', '#ef5350',
  '#26c6da', '#8bc34a', '#ff7043', '#5c6bc0',
];

/**
 * The slice of the chart the study host reads, writes and drives. The chart
 * itself is the host: each member carries the name and the type of the chart's
 * own, so the moved code reads as it did in chart.ts, and a member the chart
 * renames or retypes fails to compile here. The two writable fields are the
 * chart's own, assigned here.
 */
export interface StudiesHost {
  readonly _panes: Chart['_panes'];
  readonly _primaryPane: Chart['_primaryPane'];
  readonly _indicators: Chart['_indicators'];
  readonly _indicatorRanges: Chart['_indicatorRanges'];
  readonly _ownedScaleRanges: Chart['_ownedScaleRanges'];
  readonly _indicatorRefreshes: Chart['_indicatorRefreshes'];
  readonly _indicatorReservedIds: Chart['_indicatorReservedIds'];
  readonly _seriesRecords: Chart['_seriesRecords'];
  readonly _seriesOwners: Chart['_seriesOwners'];
  readonly _seriesProvenance: Chart['_seriesProvenance'];
  readonly _firstDataId: Chart['_firstDataId'];
  readonly _dataLayer: Chart['_dataLayer'];
  readonly _loop: Chart['_loop'];
  readonly _legends: Chart['_legends'];
  readonly _legendActions: Chart['_legendActions'];
  readonly _studyLegends: Chart['_studyLegends'];
  readonly _timezone: Chart['_timezone'];
  readonly _dataContext: Chart['_dataContext'];
  readonly _barsProvider: Chart['_barsProvider'];
  readonly _barsRequests: Chart['_barsRequests'];
  readonly _barsProviderRevision: Chart['_barsProviderRevision'];
  readonly _requestedDataRevision: Chart['_requestedDataRevision'];
  readonly _destroyed: Chart['_destroyed'];
  readonly isDestroyed: Chart['isDestroyed'];
  _indicatorsDirty: Chart['_indicatorsDirty'];
  _scaleMutationDepth: Chart['_scaleMutationDepth'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _series: Chart['_series'];
  readonly _primitives: Chart['_primitives'];
  readonly _layout: Chart['_layout'];
  readonly _legendStack: Chart['_legendStack'];
  _wallClock: Chart['_wallClock'];
  _primaryIndex: Chart['_primaryIndex'];
  _readoutIndex: Chart['_readoutIndex'];
  _policyAllows: Chart['_policyAllows'];
  seriesType: Chart['seriesType'];
  primarySeries: Chart['primarySeries'];
  hasSnapshotProvider: Chart['hasSnapshotProvider'];
  addPriceLine: Chart['addPriceLine'];
  removePrimitive: Chart['removePrimitive'];
  removePane: Chart['removePane'];
  invalidate: Chart['invalidate'];
  on: Chart['on'];
  _emit: Chart['_emit'];
  _bus: Chart['_bus'];
}

export class ChartStudies {
  private readonly _host: StudiesHost;
  /** The chart itself, the key the replay window is registered under. */
  private readonly _chart: object;
  /** Guards indicator recompute against re-entry via its own `series.setData`. */
  private _recomputing = false;
  private _indicatorWork: Map<string, boolean> | null = null;
  private _indicatorProcessed: Set<string> | null = null;
  /** Instance id of the indicator whose colours are on the price bars, if any. */
  private _barColorOwner: string | null = null;
  private _barColors: readonly (string | null)[] | null = null;
  /**
   * Each price bar's own colour, indexed like the series. The overlay overwrites
   * `Bar.color`, so a bar's own value is only readable the first time we touch
   * it, and removing the indicator has to put something back.
   */
  private readonly _barColorBase: (string | undefined)[] = [];
  /** Time of bar 0 when the snapshot was taken, to catch a replaced history. */
  private _barColorAnchor = 0;

  public constructor(chart: object, host: StudiesHost) {
    this._chart = chart;
    this._host = host;
  }

  /** The work of `Chart.addIndicator`, which carries the documented contract. */
  public addIndicator(
    indicatorId: string,
    settings: Readonly<IndicatorSettings>,
    options: AddIndicatorOptions,
  ): IndicatorApi {
    const instanceId = options.instanceId;
    if (instanceId !== undefined && (typeof instanceId !== 'string' || !instanceId.trim())) throw new TypeError('Invalid indicator instance id');
    if (instanceId !== undefined && this._host._indicators.some(item => item.id === instanceId)) throw new Error(`Indicator instance id already in use: ${instanceId}`);
    if (options.priceScaleId !== undefined && !isPriceScaleId(options.priceScaleId)) throw new TypeError('Invalid indicator price scale');
    const policy = options.policy === undefined ? undefined : parseIndicatorPolicy(options.policy);
    const barSource = options.barSource === undefined ? undefined : parseIndicatorBarSource(options.barSource);
    const descriptor = getIndicator(indicatorId);
    const validatedSettings = cloneIndicatorSettings(settings);
    validateIndicatorInputs(descriptor.inputs, validatedSettings);
    const plotPriceScaleIds = options.plotPriceScaleIds === undefined ? undefined : parseIndicatorPlotPriceScales(descriptor, options.plotPriceScaleIds);
    validateIndicatorScaleAssignment(descriptor, options.priceScaleId, plotPriceScaleIds,
      options.paneIndex ?? (descriptor.placement === 'onchart' ? this._host._primaryIndex() : this._host._panes.length), this._host._primaryIndex());
    this._flushIndicators();
    const before = this._host._series._sharedAxis();
    const reserved = new Set([...this._host._indicatorReservedIds, ...this._host._indicators.map(item => item.id)]);
    for (const edges of planIndicatorDependencies(this._host._indicators.map(item => item.dependencyNode())).dependencies.values()) {
      for (const edge of edges) reserved.add(edge.source.instanceId);
    }
    const instance = new IndicatorInstance(
      this._indicatorHost(),
      descriptor,
      this._distinctColors(descriptor, validatedSettings),
      options.paneIndex,
      instanceId,
      reserved,
      options.priceScaleId,
      plotPriceScaleIds,
      policy,
      barSource,
    );
    this._host._indicators.push(instance);
    // Its first pass ran in the constructor, outside a flush.
    this._invalidateStudies([instance.id], before);
    this._host._legendStack._restackLegends();
    this._host._indicatorReservedIds.add(instance.id);
    this._queueIndicatorDependents(instance.id, true);
    this._host._emit('objects:change', {});
    return instance;
  }

  /**
   * Give a repeated indicator its own colours. Three EMAs all in the
   * descriptor's default blue are indistinguishable on the chart *and* in the
   * legend, so the second and later instances rotate through a palette.
   *
   * Only fills colour keys the caller left unset, so an explicit colour always
   * wins, and the first instance is never touched: it keeps the colours the
   * descriptor chose.
   */
  private _distinctColors(
    descriptor: IndicatorDescriptor,
    settings: Readonly<IndicatorSettings>,
  ): Readonly<IndicatorSettings> {
    const nth = this._host._indicators.filter((i) => i.indicatorId === descriptor.id).length;
    if (nth === 0) return settings;
    const out: IndicatorSettings = { ...settings };
    const plots = descriptor.plots;
    for (let i = 0; i < plots.length; i++) {
      const key = plotStyleKeys(plots[i]!).color;
      if (out[key] !== undefined) continue; // an explicit colour always wins
      // Stride by the plot count so a multi-plot indicator (MACD) shifts as a
      // block rather than landing on the previous instance's colours.
      out[key] = INSTANCE_PALETTE[(nth * plots.length + i) % INSTANCE_PALETTE.length];
    }
    return out;
  }

  /** The work of `Chart.indicators`, which carries the documented contract. */
  public indicators(): readonly IndicatorApi[] {
    this._flushIndicators();
    return this._host._indicators;
  }

  /** The work of `Chart.moveIndicator`, which carries the documented contract. */
  public moveIndicator(instanceId: string, paneIndex: number, options: IndicatorEditOptions): boolean {
    const instance = this._host._indicators.find(item => item.id === instanceId);
    if (this._host.isDestroyed || !instance || !this._host._policyAllows(instance, 'movable', options) || !Number.isInteger(paneIndex) || paneIndex < 0 || paneIndex > this._host._panes.length || instance.paneIndex === paneIndex || !instance.canRelocate(paneIndex)) return false;
    const previous = instance.paneIndex;
    const freshTarget = paneIndex === this._host._panes.length;
    this._host._layout._ensurePane(paneIndex);
    const target = this._host._panes[paneIndex]!; // a whole index up to one past the end, made above
    const resources = instance.renderResources();
    for (const { api, overlay } of resources.series) {
      if (overlay) continue;
      const owner = this._host._seriesOwners.get(api);
      const record = this._host._seriesRecords.get(api);
      if (!owner || !record || owner.pane === target) continue;
      const scale = owner.pane.scaleOf(record);
      const options = scale.options;
      owner.pane.removeSeries(record);
      target.addSeries(record);
      owner.pane = target;
      if (freshTarget && target.series().filter(item => item.scaleId === record.scaleId).length === 1) target.scaleOf(record).setOptions(options);
      this._host._series._applySeriesPriceFormat(target.scaleOf(record), owner.priceFormat);
      if (record.style.precision !== undefined) this._host._series._applyPrecision(target.scaleOf(record), record.style.precision);
    }
    for (const { primitive, overlay } of resources.primitives) {
      if (overlay) continue;
      this._host._panes.find(pane => pane.hasPrimitive(primitive))?.transferPrimitive(primitive, target);
    }
    instance.relocate(paneIndex);
    // The source keeps its place when the study it sat on leaves its pane.
    this._host._primitives._reanchorSource();
    this._host._legendStack._syncLegendPanes();
    // Alert visuals resolve the instance's new pane before we decide whether its old pane is empty.
    this._host._emit('objects:change', {});
    // Retain a pane holding drawings or host visuals even after its last plot moves.
    const source = this._host._panes[previous]!; // the pane the study was on still stands
    if (this._host._layout._holdsOnlyFurniture(source)) this._host.removePane(previous);
    this._reorderIndicatorResources();
    this._host._layout._recomputeAxisColumns();
    this._host._layout._relayout();
    this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emit('objects:change', {});
    return true;
  }

  /** The work of `Chart.reorderIndicator`, which carries the documented contract. */
  public reorderIndicator(instanceId: string, direction: -1 | 1, options: IndicatorEditOptions): boolean {
    if (direction !== -1 && direction !== 1) return false;
    const index = this._host._indicators.findIndex(item => item.id === instanceId);
    // `index` was found in the list and `target` is kept inside it.
    if (this._host.isDestroyed || index < 0 || !this._host._policyAllows(this._host._indicators[index]!, 'movable', options)) return false;
    const paneIndex = this._host._indicators[index]!.paneIndex;
    let target = index + direction;
    while (target >= 0 && target < this._host._indicators.length && this._host._indicators[target]!.paneIndex !== paneIndex) target += direction;
    if (target < 0 || target >= this._host._indicators.length) return false;
    [this._host._indicators[index], this._host._indicators[target]] = [this._host._indicators[target]!, this._host._indicators[index]!];
    this._reorderIndicatorResources();
    this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emit('objects:change', {});
    return true;
  }

  public _reorderIndicatorResources(): void {
    for (const instance of this._host._indicators) instance.refreshBarColors();
    const resources = this._host._indicators.map(instance => instance.renderResources());
    const records = resources.flatMap(resource => resource.series.flatMap(({ api }) => {
      const record = this._host._seriesRecords.get(api);
      return record ? [record] : [];
    }));
    const primitives = resources.flatMap(resource => resource.primitives.map(item => item.primitive));
    for (const pane of this._host._panes) { pane.reorderSeries(records); pane.reorderPrimitives(primitives); }
    const legends = this._host._indicators.flatMap(instance => instance.legend() ? [instance.legend()!] : []);
    const owned = new Set(legends);
    // One study row per owned entry, taken in study order.
    let index = 0;
    for (const entry of this._host._legends) if (owned.has(entry.legend)) entry.legend = legends[index++]!;
    this._host._primitives._placeSource();
    this._host._legendStack._syncLegendPanes();
  }

  /** The work of `Chart.removeIndicator`, which carries the documented contract. */
  public removeIndicator(instanceId: string, options: IndicatorEditOptions): boolean {
    const instance = this._host._indicators.find(x => x.id === instanceId);
    return instance !== undefined && instance.remove(options);
  }

  private _forgetIndicator(instanceId: string, failedOwnedPane?: number): void {
    const i = this._host._indicators.findIndex((x) => x.id === instanceId);
    if (i < 0) {
      const pane = failedOwnedPane === undefined ? undefined : this._host._panes[failedOwnedPane];
      if (failedOwnedPane !== undefined && pane !== undefined && this._host._layout._holdsOnlyFurniture(pane)) this._host.removePane(failedOwnedPane);
      return;
    }
    const { indicatorId, paneIndex } = this._host._indicators[i]!;
    this._host._indicators.splice(i, 1);
    this._host._primitives._reanchorSource();
    this._host._legendStack._restackLegends();
    this._host._indicatorReservedIds.add(instanceId);
    this._host._indicatorRefreshes.delete(instanceId);
    this._queueIndicatorDependents(instanceId, true);
    this._host._emit('indicatorRemoved', { instanceId, indicatorId, paneIndex });
    // An indicator pane that just emptied has nothing left to show. This lived
    // in the legend's close handler, so only the on-chart × pruned the pane: a
    // host removing the same indicator from its own UI left it behind, and
    // `getState` then persisted the orphan, so every reload restored a blank
    // region. Doing it here means every caller behaves the same. The price
    // pane stays whatever emptied it, and it can sit in any slot.
    // Unlike a move, this does not ask `_holdsOnlyFurniture`: what was placed
    // on the pane was placed against the study's units, and it goes with it.
    const pane = this._host._panes[paneIndex];
    if (pane !== undefined && pane !== this._host._primaryPane && pane.series().length === 0) this._host.removePane(paneIndex);
  }

  public _indicatorHost(preservedFormats?: PreservedScaleFormats): IndicatorHost {
    return {
      assignIndicatorScale: (id, series, primitives, commit) => this._assignIndicatorScale(id, series, primitives, commit),
      bindIndicatorPrimitiveScale: (primitive, scaleId) => {
        const pane = this._host._panes.find(item => item.hasPrimitive(primitive));
        pane?.bindPrimitiveScale(primitive, scaleId);
        // A data-derived level is bound again each time it moves, so this runs
        // inside a recompute. Only the pane whose scale now counts the
        // primitive has changed; a new axis column repaints every pane itself.
        this._host._layout._recomputeAxisColumns();
        const index = pane === undefined ? -1 : this._host._panes.indexOf(pane);
        this._host.invalidate(mask => index < 0 ? mask.invalidateGlobal(InvalidationLevel.Full)
          : mask.invalidatePane(index, { level: InvalidationLevel.Full, autoScale: true }));
      },
      setIndicatorRange: (id, paneIndex, scaleId, range, series) => {
        const previous = this._host._indicatorRanges.get(id);
        const pane = this._host._panes[paneIndex];
        if (range && pane) this._host._indicatorRanges.set(id, { pane, scaleId, range, series, token: previous?.token ?? {} });
        else this._host._indicatorRanges.delete(id);
        this._reconcileIndicatorRanges();
      },
      legendIndex: () => this._host._readoutIndex(),
      indicatorRemoved: (id, failedOwnedPane): void => this._forgetIndicator(id, failedOwnedPane),
      flushIndicators: (): void => this._flushIndicators(),
      validateIndicatorSettings: (id, descriptor, settings) => {
        const nodes = this._host._indicators.filter(item => item.id !== id).map(item => item.dependencyNode());
        nodes.push({ id, descriptor, settings });
        planIndicatorDependencies(nodes);
      },
      studyOutput: reference => this._host._indicators.find(item => item.id === reference.instanceId)?.studyOutput(reference.plotKey),
      indicatorOutputChanged: (id, refresh) => this._queueIndicatorDependents(id, refresh),
      indicatorRecompute: (id, refresh, fallback) => {
        if (!this._host._indicators.some(item => item.id === id)) { fallback(); return; }
        if (this._recomputing) {
          fallback();
          this._indicatorWork?.delete(id);
          this._indicatorProcessed?.add(id);
          return;
        }
        this._host._indicatorRefreshes.set(id, refresh || this._host._indicatorRefreshes.get(id) === true);
        this._queueIndicatorDependents(id, refresh);
        const sourcePending = this._host._indicatorsDirty;
        this._flushIndicators();
        // An explicit refresh cannot consume the source pass already queued by
        // a data write. That pass can recover a failed external calculation.
        if (sourcePending) { this._host._indicatorsDirty = true; this._host._loop.requestFrame(); }
      },
      resourcesChanged: (): void => this._reorderIndicatorResources(),
      // The scale that draws the ladder is the one that decides how a number on
      // that pane is written, floor, tick, custom formatter and all.
      formatPrice: (paneIndex: number, value: number, series?: SeriesApi): string | undefined =>
        (series?.priceScale() ?? this._host._panes[paneIndex]?.priceScale)?.format(value),
      policyChanged: (): void => {
        this._host._legendStack._restackLegends();
        this._host._emit('objects:change', {});
      },
      addIndicatorLegend: (o): PaneLegend => {
        // A row starts with its own show / settings / delete. Stacking it gives
        // it the pane-level controls when it is the first study row of a lower
        // pane, so they follow whichever row leads rather than the row count
        // at creation, which a host row above it would throw off.
        const paneActions: PaneLegendAction[] = ['hide', 'settings', 'close'];
        // The source button sits next to the gear, because the two are the
        // same errand at different depths: what this study is set to, and what
        // it is. Only a descriptor that says it has source gets one.
        if (o.hasSource === true) paneActions.splice(paneActions.indexOf('settings') + 1, 0, 'source');
        // _syncLegendOffsets decides which pane wears the offset, and runs on
        // every relayout; this is just the initial placement.
        const legend = new PaneLegend({ ...o, actions: paneActions });
        this._host._legendActions.set(legend, [paneActions, legend.options().actions]);
        this._host._studyLegends.add(legend);
        this._host._primitives._addPrimitive(o.paneIndex, legend);
        return legend;
      },
      removeIndicatorLegend: (legend): void => {
        this._host._studyLegends.delete(legend);
        this._host.removePrimitive(legend);
        this._host._legendStack._restackLegends();
      },
      legendRowsOn: (paneIndex): number => this._host._legends.filter((l) => l.paneIndex === paneIndex).length,
      primarySeries: (): SeriesApi | null => this._host.primarySeries(),
      setIndicatorSeriesType: (series, type) => this._host._series._setSeriesType(series, type as SeriesType, false),
      addIndicatorSeries: (type, paneIndex, style, priceScaleId, priceFormat): SeriesApi =>
        this._host._series._createSeries(
          type as SeriesType,
          {
            paneIndex,
            style: style as SeriesStyle | undefined,
            priceScaleId: priceScaleId as PriceScaleId | undefined,
            priceFormat,
          },
          false,
          preservedFormats,
        ),
      addIndicatorLevel: (l, paneIndex): PriceLine => {
        // The instance resolves `lineStyle` before calling the host, a
        // descriptor's `dashed` boolean included, so the line needs nothing
        // else to pick its dash.
        const opts: PriceLineOptions = {
          price: l.price, color: l.color, lineWidth: l.lineWidth,
          lineStyle: l.lineStyle, leftLabel: l.label, id: l.id,
        };
        return this._host.addPriceLine(opts, paneIndex);
      },
      removeIndicatorLevel: (line): void => this._host.removePrimitive(line),
      addIndicatorFill: (fill, paneIndex): void => this._host._primitives._addPrimitive(paneIndex, fill),
      removeIndicatorFill: (fill): void => this._host.removePrimitive(fill),
      removeIndicatorMarkers: (markers): void => this._host.removePrimitive(markers),
      addIndicatorPrimitive: (p, paneIndex): void => this._host._primitives._addPrimitive(paneIndex, p),
      removeIndicatorPrimitive: (p): void => this._host.removePrimitive(p),
      addIndicatorTable: (paneIndex): ChartTable => {
        const t = new ChartTable();
        this._host._primitives._addPrimitive(paneIndex, t);
        return t;
      },
      removeIndicatorTable: (table): void => this._host.removePrimitive(table),
      sourceBars: (): readonly Bar[] =>
        this._host._firstDataId.value === null ? [] : this._host._dataLayer.seriesBars(this._host._firstDataId.value),
      underlyingBars: () => this._host._series._underlying(this._host._firstDataId.value),
      sourceState: () => {
        const state = this._host._seriesProvenance.get(this._host._firstDataId.value ?? -1)?.snapshot();
        const replay = replayWindow(this._chart);
        return state && replay ? {
          ...state, provenance: 'replay', confirmation: replay.forming ? 'forming' : 'confirmed', confirmationSource: 'replay',
        } : state;
      },
      nextPaneIndex: (): number => this._host._panes.length,
      // Read at every call, never kept: a study resolves its price-pane plots,
      // bands, tables and marks against wherever the price pane sits now.
      primaryPaneIndex: (): number => this._host._primaryIndex(),
      // The calendar a session anchor resets on and the calendar the axis is
      // labelled in have to be the same one, or a VWAP restarts in the middle
      // of the afternoon the axis is showing.
      timezone: (): string => this._host._timezone,
      // The same clock the countdown row reads, so an indicator that decides
      // whether the last bar is still forming agrees with the axis about it.
      // Instrument identity exists only when a host explicitly supplies it.
      now: (): number => this._host._wallClock(),
      symbol: (): string | undefined => this._host._dataContext?.symbol,
      interval: (): string | undefined => this._host._dataContext?.interval,
      dataContext: () => this._host._dataContext,
      // Answered at call time rather than at host build time, so a provider
      // registered after the indicator was added still serves it.
      requestBars: (request) => {
        const provider = this._host._barsProvider;
        if (provider === null) {
          return Promise.reject(new Error('openalgo-charts: this chart has no bars provider; call chart.setBarsProvider(...) to serve other instruments'));
        }
        return runAbortable(signal => typeof provider === 'function'
          ? provider({ ...request, signal }) : provider.requestBars({ ...request, signal }),
        [request.signal, this._host._barsRequests.signal]);
      },
      requestSnapshot: request => {
        const provider = this._host._barsProvider;
        return runAbortable(signal => {
          if (typeof provider !== 'object' || provider?.requestSnapshot === undefined) throw new Error('Requested snapshots are unsupported by this provider');
          const replay = replayWindow(this._chart);
          if (replay && replay.asOf === undefined) throw new Error('Requested snapshots require an availability clock during replay');
          if (request.asOf !== undefined && !Number.isFinite(request.asOf)) throw new RangeError('Requested availability time must be finite');
          const asOf = replay?.asOf === undefined ? request.asOf : Math.min(request.asOf ?? Infinity, replay.asOf);
          return provider.requestSnapshot({ ...request, ...(asOf === undefined ? {} : { asOf }), signal });
        }, [request.signal, this._host._barsRequests.signal]);
      },
      requestState: () => ({
        source: this._host._seriesProvenance.get(this._host._firstDataId.value ?? -1)?.snapshot(),
        providerRevision: this._host._barsProviderRevision, dataRevision: this._host._requestedDataRevision,
        supportsSnapshots: this._host.hasSnapshotProvider(),
        replay: replayWindow(this._chart),
      }) satisfies LooseOptional<IndicatorRequestState> as IndicatorRequestState, // an absent source or replay window is written as undefined
      subscribeRequestChanges: listener => {
        const subscriptions = (['data:context', 'data:range', 'data:requests'] as const).map(event => this._host.on(event, listener));
        subscriptions.push(observeReplayWindow(this._chart, listener));
        return () => { for (const unsubscribe of subscriptions) unsubscribe(); };
      },
      subscribeDataChanges: listener => {
        const context = this._host.on('data:context', () => listener('context'));
        const range = this._host.on('data:range', () => listener('range'));
        return () => { context(); range(); };
      },
      // The tick size the price scale is already formatting and snapping to.
      // Unlike symbol and interval, the chart genuinely knows this one, so an
      // indicator sizing a range in ticks does not have to be told twice.
      //
      // Answered per pane, so a pane that does not quote the instrument says
      // undefined (see `_scalePatchFor`). That is what the legend beside that
      // axis wants; an indicator's `calc` wants the instrument's own tick, and
      // asks the price pane for it.
      tickSize: (paneIndex: number): number | undefined => {
        const pane = this._host._panes[paneIndex] ?? this._host._primaryPane;
        const min = pane?.priceScale.options.minMove ?? 0;
        // 0 is the scale's "infer from the visible range" sentinel, not a tick.
        return min > 0 ? min : undefined;
      },
      setBarColors: (colors, owner): void => this._setBarColors(colors, owner),
      // Indicator alerts land on the same bus as every other chart event, so a
      // host wires one listener rather than a second subscription mechanism.
      // A descriptor may name any event (`ctx.emit`), so this skips the map's check.
      emit: (event, payload): void => this._host._bus.emit(event, payload),
      setPaneRange: (paneIndex, range): void => {
        const pane = this._host._panes[paneIndex];
        if (pane === undefined) return;
        // Declared, not measured: the scale remembers the band so a later
        // auto-fit request comes back to it instead of re-measuring an
        // oscillator against its own values (see `PriceScale.setFixedRange`).
        const shared = pane === this._host._primaryPane || this._host._indicators.filter(item => item.paneIndex === paneIndex).length > 1;
        pane.priceScale.setFixedRange(shared ? null : range);
        if (range === null) pane.priceScale.setAutoScale(true);
      },
    };
  }

  private _assignIndicatorScale(id: string,
    series: readonly { api: SeriesApi; scaleId: PriceScaleId }[],
    primitives: readonly { primitive: IPrimitive; scaleId: PriceScaleId }[], commit: () => void): boolean {
    if (this._host._destroyed || !this._host._indicators.some(instance => instance.id === id)) return false;
    for (const item of series) if (!isPriceScaleId(item.scaleId) || this._host.seriesType(item.api) === null) return false;
    for (const item of primitives) if (!isPriceScaleId(item.scaleId) || !this._host._panes.some(pane => pane.hasPrimitive(item.primitive))) return false;
    this._host._scaleMutationDepth++;
    try {
      for (const { api, scaleId } of series) {
        const record = this._host._seriesRecords.get(api)!, owner = this._host._seriesOwners.get(api)!;
        const target = owner.pane.scaleFor(scaleId);
        record.scaleId = scaleId;
        this._host._series._applySeriesPriceFormat(target, owner.priceFormat);
        if (record.style.precision !== undefined) this._host._series._applyPrecision(target, record.style.precision);
      }
      for (const { primitive, scaleId } of primitives) this._host._panes.find(pane => pane.hasPrimitive(primitive))!.bindPrimitiveScale(primitive, scaleId);
      commit();
      this._host._layout._recomputeAxisColumns();
    } finally {
      this._host._scaleMutationDepth--;
      this._host.invalidate(mask => mask.invalidateGlobal(InvalidationLevel.Full));
    }
    this._host._emit('objects:change', {});
    return true;
  }

  public _reconcileIndicatorRanges(): void {
    const selected = new Map<PriceScale, { token: object; range: { min: number; max: number } }>();
    for (const claim of this._host._indicatorRanges.values()) {
      if (!this._host._panes.includes(claim.pane)) continue;
      const scale = claim.pane.scaleFor(claim.scaleId);
      if (selected.has(scale)) continue;
      const peers = [...this._host._indicatorRanges.values()].filter(peer => peer.pane === claim.pane && peer.scaleId === claim.scaleId
        && peer.range.min === claim.range.min && peer.range.max === claim.range.max);
      const records = new Set(peers.flatMap(peer => peer.series.flatMap(api => {
        const record = this._host._seriesRecords.get(api); return record ? [record] : [];
      })));
      if (claim.pane.series().some(record => record.scaleId === claim.scaleId && !records.has(record))) continue;
      selected.set(scale, claim);
    }
    for (const [scale, token] of this._host._ownedScaleRanges) {
      if (!selected.has(scale)) {
        scale.clearOwnedFixedRange(token);
        this._host._ownedScaleRanges.delete(scale);
      }
    }
    for (const [scale, claim] of selected) {
      const token = this._host._ownedScaleRanges.get(scale) ?? claim.token;
      if (scale.setOwnedFixedRange(token, claim.range)) this._host._ownedScaleRanges.set(scale, token);
      else if (!scale.ownsFixedRange(token)) this._host._ownedScaleRanges.delete(scale);
    }
  }

  /**
   * Take (or withdraw) the price bars' colour overlay on behalf of one
   * indicator instance.
   *
   * Only one overlay can be on the candles, so this is last writer wins. That is
   * deterministic rather than arbitrary: publishers run inside
   * `_flushIndicators`, in `addIndicator` order, so the same instance wins
   * every frame. Withdrawal is gated on ownership, or the first publisher's
   * teardown would wipe the second one's colours. If the *winner* is removed
   * while another publisher is still live, the bars go back to their own colours
   * until that publisher's next recompute.
   */
  private _setBarColors(colors: readonly (string | null)[] | null, owner: string): void {
    if (colors === null) {
      if (this._barColorOwner !== owner) return;
      this._barColorOwner = null;
    } else {
      this._barColorOwner = owner;
    }
    this._barColors = colors;
    this._applyBarColors();
  }

  /**
   * Republish the primary series with the overlay applied.
   *
   * The bars in the data layer are the **caller's own objects** (`setData` keeps
   * the references), so painting a colour onto them in place would reach back
   * into the host's array and outlive the indicator. Cloning the ones that
   * change is what keeps that from happening; unchanged bars are passed through,
   * and a pass where nothing changed writes nothing at all, which is the common
   * case on a live tick.
   */
  private _applyBarColors(): void {
    const dataId = this._host._firstDataId.value;
    if (dataId === null) return;
    const bars = this._host._dataLayer.seriesBars(dataId);
    const n = bars.length;
    const base = this._barColorBase;
    // Anything that replaces history (a symbol change, a page of older bars)
    // invalidates the snapshot, since index i is no longer the same bar. A
    // snapshot is read against the bars only where there are at least as many.
    if (n < base.length || (base.length > 0 && bars[0]!.time !== this._barColorAnchor)) base.length = 0;
    if (base.length === 0) this._barColorAnchor = n > 0 ? bars[0]!.time : 0;
    for (let i = base.length; i < n; i++) base[i] = bars[i]!.color;
    const colors = this._barColors;
    const out = new Array<Bar>(n);
    let changed = false;
    for (let i = 0; i < n; i++) {
      const bar = bars[i]!;
      const color = colors?.[i] ?? base[i];
      if (color === bar.color) { out[i] = bar; continue; }
      out[i] = { ...bar, color } satisfies LooseOptional<Bar> as Bar; // undefined restores a host bar that had no colour
      changed = true;
    }
    if (!changed) return;
    // Straight to the data layer, not through `_setData`: the time points are
    // untouched, so nothing about the axis or the base index moves, and routing
    // it through the data path would recompute every indicator mid-recompute.
    this._host._dataLayer.setSeriesData(dataId, out);
    // The colours are on the price bars alone, so only their pane repaints.
    const pane = this._host._panes.findIndex(item => item.series().some(record => record.dataId === dataId));
    this._host.invalidate((m) => {
      if (pane < 0) m.invalidateGlobal(InvalidationLevel.Light);
      else m.invalidatePane(pane, { level: InvalidationLevel.Light, autoScale: false });
    });
  }

  /**
   * Mark every indicator stale after a source-data change, to be recomputed
   * once before the next paint.
   *
   * Recomputing straight from the data update instead costs a full pass over
   * every bar, for every indicator, for every tick. A busy symbol delivers ticks
   * in bursts far faster than the display refreshes, so most of those passes are
   * thrown away unseen: 50 ticks between two frames cost 50 recomputes per
   * indicator and blocked the main thread for over half a second on a ten
   * indicator chart. Deferring to the frame makes that one recompute, because
   * only the last one could ever have been shown.
   *
   * `flushIndicators` therefore has to run before anything that can observe a
   * value, which is the frame and the public `indicators()` accessor.
   */
  public _invalidateIndicators(): void {
    this._host._emit('data:range', {});
    if (this._host._indicators.length === 0) return;
    this._host._indicatorsDirty = true;
    this._host._loop.requestFrame();
  }

  /**
   * Recompute every stale indicator. Reentrant-guarded: an indicator writes its
   * plots with `series.setData`, or on a live tick with `series.update`, and
   * either re-enters the same data-mutation path that marked us dirty.
   */
  public _flushIndicators(): void {
    if (!this._host._indicatorsDirty && this._host._indicatorRefreshes.size === 0) return;
    if (this._recomputing) return;
    if (this._host._indicators.length === 0) {
      this._host._indicatorsDirty = false;
      this._host._indicatorRefreshes.clear();
      return;
    }
    const all = this._host._indicatorsDirty;
    const before = this._host._series._sharedAxis();
    const order = planIndicatorDependencies(this._host._indicators.map(item => item.dependencyNode())).order;
    const work = new Map(this._host._indicatorRefreshes);
    this._host._indicatorRefreshes.clear();
    if (all) for (const id of order) if (!work.has(id)) work.set(id, false);
    this._host._indicatorsDirty = false;
    this._recomputing = true;
    this._indicatorWork = work;
    const processed = new Set<string>();
    this._indicatorProcessed = processed;
    try {
      for (const id of order) {
        if (!work.has(id) || processed.has(id)) continue;
        const indicator = this._host._indicators.find(item => item.id === id);
        if (!indicator) continue;
        processed.add(id);
        indicator.recompute(work.get(id));
      }
      for (const indicator of this._host._indicators) indicator.republishBarColors();
    } finally {
      this._indicatorWork = null;
      this._indicatorProcessed = null;
      this._recomputing = false;
      this._invalidateStudies(processed, before);
    }
  }

  /**
   * Repaint what recomputing these studies changed: every pane holding one of
   * their plots or primitives, which is each study's own pane and any pane
   * its output targets, at `Full` so each re-measures its scale. Nothing else
   * has changed, unless the pass moved the shared index or the time scale,
   * which every pane follows. `before` is `ChartSeries._sharedAxis` from
   * before the pass.
   *
   * Asked for here as well as by each plot's write, because not everything a
   * pass changes is a series: a level line or an attached primitive on a
   * pane with no plot of the study still widens that pane's range.
   */
  private _invalidateStudies(ids: Iterable<string>, before: readonly number[]): void {
    const panes = new Set<Pane>();
    for (const id of ids) {
      const resources = this._host._indicators.find(item => item.id === id)?.renderResources();
      for (const { api } of resources?.series ?? []) {
        const pane = this._host._seriesOwners.get(api)?.pane;
        if (pane !== undefined) panes.add(pane);
      }
      for (const { primitive } of resources?.primitives ?? []) {
        const pane = this._host._panes.find(item => item.hasPrimitive(primitive));
        if (pane !== undefined) panes.add(pane);
      }
    }
    this._host._series._invalidateWrite(panes, before);
  }

  private _queueIndicatorDependents(id: string, refresh: boolean): void {
    const plan = planIndicatorDependencies(this._host._indicators.map(item => item.dependencyNode()));
    const pending = [id];
    const visited = new Set(pending);
    for (let i = 0; i < pending.length; i++) {
      for (const [consumer, edges] of plan.dependencies) {
        if (visited.has(consumer) || !edges.some(edge => edge.source.instanceId === pending[i])) continue;
        visited.add(consumer);
        pending.push(consumer);
        this._host._indicators.find(item => item.id === consumer)?.invalidateStudyOutput();
        const target = this._indicatorWork && !this._indicatorProcessed?.has(consumer)
          ? this._indicatorWork : this._host._indicatorRefreshes;
        target.set(consumer, refresh || target.get(consumer) === true);
      }
    }
    if (this._host._indicatorRefreshes.size > 0) this._host._loop.requestFrame();
  }
}
