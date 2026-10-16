/**
 * Multi-symbol comparison: put a second instrument on the primary one's pane
 * and read them together (NIFTY against BANKNIFTY, a stock against its index).
 *
 * Headless, in the spirit of `DrawingController` (src/draw/controller.ts) and
 * `ReplayController`: it owns the series, the alignment and the scales, and
 * ships no DOM, so the host draws its own symbol chips and legend rows from
 * `list()`.
 *
 * Three decisions carry the design:
 *
 * 1. **Each comparison owns a scale.** A free legacy overlay or left scale
 *    preserves the first source's placement; additional sources use named
 *    hidden scales so their different price units cannot affect one another.
 *
 * 2. **Comparability comes from the scale, not from the data.** The bars handed
 *    over are stored as the instrument's own prices, so the legend, the
 *    crosshair and any live update still speak in real prices. What makes the
 *    lines readable together is the pane mode: `percentage` and
 *    `indexed-to-100` give every scale its own baseline (its first visible
 *    close, or an explicit common timestamp), and `_mirror` gives it the same
 *    band of percent the primary's axis is showing. Without that mirror each
 *    scale would autoscale to its own data and a 1% mover would look exactly
 *    like a 10% mover, both filling the pane.
 *
 * 3. **Alignment is by timestamp** and lives in `./align`, which documents what
 *    happens in each direction of mismatch.
 *
 * Each comparison owns a scale and baseline. Further instruments use keyed
 * hidden scales so their absolute prices cannot change another source's units.
 */
import { scaleAutoscaleRange, type PriceScale, type PriceScaleMode } from '../scale/price-scale';
import type { PriceScaleId, SeriesApi } from '../model/series';
import { getChartType, type SeriesType } from '../model/chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import type { Bar, SeriesDataItem } from '../model/bar';
import { toBar } from '../model/bar';
import { observeReplayWindow, replayWindow } from '../model/replay-window';
import type { IPrimitive } from '../primitives/primitive';
import type { AddSeriesOptions } from '../core/chart';
import { alignToPrimary, EMPTY_ALIGNMENT, type ComparisonAlignment } from './align';

/**
 * How the pane quotes prices while a comparison is on it. The two rebasing
 * modes are the reason the lines are comparable at all; `none` leaves the
 * pane's own mode alone, for a host that wants the raw overlay.
 */
export type ComparisonMode = 'percentage' | 'indexed-to-100' | 'none';
/** Independent first-visible closes, or the first visible timestamp shared by all visible sources. */
export type ComparisonBaseline = 'first-visible' | 'common';

export interface ComparisonOptions {
  /** Instrument label, e.g. 'BANKNIFTY'. Carried on the handle for the host's UI. */
  symbol: string;
  /** The instrument's own bars. Aligned to the primary series, see `./align`. */
  bars: readonly SeriesDataItem[];
  /** Line colour shorthand; `style.color` wins if both are given. */
  color?: string;
  /** Style overrides merged onto the chart type's defaults. */
  style?: SeriesStyle;
  /** Renderer for the comparison. Default 'line'. */
  type?: SeriesType;
  /** Pane to draw on. Default: the price pane, wherever it sits (`Chart.primaryPaneIndex`). */
  paneIndex?: number;
}

export interface ComparisonControllerOptions {
  /** Pane mode applied while any comparison is on it. Default 'percentage'. */
  mode?: ComparisonMode;
  /** Baseline policy. Default 'first-visible' preserves existing integrations. */
  baseline?: ComparisonBaseline;
}

/** What `addComparison` hands back: one instrument on the chart. */
export interface ComparisonHandle {
  readonly symbol: string;
  /**
   * The series this comparison draws through, for style patches and markers.
   * Data set on it directly skips alignment (use `setBars`), and removing it
   * directly leaves the pane rebased with nothing on it (use `remove`).
   */
  readonly series: SeriesApi;
  /** The slot of the pane it draws on, read live: it follows that pane through a move. */
  readonly paneIndex: number;
  /** The hidden scale it maps to. Never the pane's own price axis. */
  priceScale(): PriceScale;
  /** How the last alignment against the primary's bars went. */
  alignment(): ComparisonAlignment;
  /** Eligible aligned bar in its own price units; null for gaps, suppressed baselines or forming replay candles. */
  barAt(time: number): Readonly<Bar> | null;
  /** Replace the instrument's bars (a longer history, a refreshed fetch). */
  setBars(bars: readonly SeriesDataItem[]): void;
  /** Take this instrument off the chart. Safe to call twice. */
  remove(): void;
  /** Every comparison on this chart, in the order they were added. */
  list(): readonly ComparisonHandle[];
}

/**
 * The slice of a pane the controller reads. Declared structurally, like
 * `ReplayViewport`, so nothing here depends on `Pane` beyond the two members
 * that decide where a comparison can go.
 */
export interface ComparisonPane {
  readonly priceScale: PriceScale;
  series(): readonly { readonly scaleId: string; readonly style?: SeriesStyle }[];
}

/**
 * The slice of the chart this controller needs. `Chart` satisfies it; declaring
 * it structurally keeps the controller testable against a stub.
 */
export interface ComparisonChartHost {
  addSeries(type: SeriesType, options: AddSeriesOptions): SeriesApi;
  panes(): readonly ComparisonPane[];
  addPrimitive(primitive: IPrimitive, paneIndex?: number): void;
  removePrimitive(primitive: IPrimitive): void;
  primarySeries(): SeriesApi | null;
  /** Avoids allocating a primary history copy when the host provides it. */
  primaryBars?(): readonly Bar[];
  getVisibleLogicalRange?(): { from: number; to: number };
  on?(event: string, callback: (payload: unknown) => void): () => void;
  /** The shared logical axis locates visible primary bars even when another series adds times. */
  readonly dataLayer: { readonly length: number; indexToTime?(index: number): number | undefined };
  /** Slot of the price pane, the default target. Absent means slot 0. */
  primaryPaneIndex?(): number;
}

/**
 * The primary mode is shared by a pane and restored after its last comparison.
 * Keyed by the pane itself rather than its slot: panes move, the price pane
 * included, and a slot number kept here would name a different pane after one.
 */
interface PaneEntry {
  readonly pane: ComparisonPane;
  /** The pane's own price axis; its mode is temporarily rebased. */
  readonly primary: PriceScale;
  readonly savedPrimaryMode: PriceScaleMode;
  /** The mode we put in force, or null if we left the pane alone. */
  applied: PriceScaleMode | null;
  readonly sync: IPrimitive;
  count: number;
}

interface ItemState {
  readonly series: SeriesApi;
  readonly entry: PaneEntry;
  readonly scale: PriceScale;
  readonly savedScaleMode: PriceScaleMode;
  readonly savedInverted: boolean;
  appliedInverted: boolean | null;
  readonly scaleId: PriceScaleId;
  readonly type: SeriesType;
  readonly style: SeriesStyle;
  bars: readonly SeriesDataItem[];
  items: SeriesDataItem[];
  values: Map<number, Bar>;
  suppressed: boolean;
  alignment: ComparisonAlignment;
  removed: boolean;
}

export class ComparisonController {
  private readonly _chart: ComparisonChartHost;
  private _mode: ComparisonMode;
  private _baseline: ComparisonBaseline;
  private readonly _panes = new Map<ComparisonPane, PaneEntry>();
  /** Insertion-ordered, and the handle is the key so `remove` is a lookup. */
  private readonly _items = new Map<ComparisonHandle, ItemState>();
  /** Axis length plus primary identity and boundaries avoid scanning history each frame. */
  private _alignedAt = -1;
  /** Guards `realign` against re-entry through its own `setData` repaint. */
  private _realigning = false;
  private _nextScale = 0;
  private _syncing = false;
  private _alignedPrimary: readonly Bar[] | null = null;
  private _primaryLength = -1;
  private _primaryFirst: number | undefined;
  private _primaryLast: number | undefined;
  private readonly _off: (() => void)[] = [];
  private _destroyed = false;

  public constructor(chart: ComparisonChartHost, options: ComparisonControllerOptions = {}) {
    this._chart = chart;
    this._mode = options.mode ?? 'percentage';
    this._baseline = options.baseline ?? 'first-visible';
    this._off.push(observeReplayWindow(chart, () => this.realign()));
    if (chart.on) {
      this._off.push(chart.on('data:update', () => { if (this._needsAlignment()) this.realign(); }));
      this._off.push(chart.on('destroy', () => this._dispose()));
    }
  }

  // ── public API ──────────────────────────────────────────────────────────

  /** Put an instrument on the chart alongside the primary series. */
  public add(options: ComparisonOptions): ComparisonHandle {
    if (this._destroyed) throw new Error('openalgo-charts: comparison controller is destroyed');
    if (this._chart.primarySeries() === null) {
      throw new Error('openalgo-charts: a comparison needs a primary series to align against');
    }
    const paneIndex = options.paneIndex ?? this._chart.primaryPaneIndex?.() ?? 0;
    const style: SeriesStyle = { ...options.style };
    if (style.color === undefined && options.color !== undefined) style.color = options.color;
    const before = this._chart.panes()[paneIndex];
    const existing = before === undefined ? undefined : this._panes.get(before);
    const scaleId = this._scaleIdFor(paneIndex);
    const series = this._chart.addSeries(options.type ?? 'line', { paneIndex, style, priceScaleId: scaleId });
    // `addSeries` makes a pane that did not exist yet, and throws for an index
    // it cannot make one at, so the pane is read after it.
    const entry = existing ?? this._openPane(this._chart.panes()[paneIndex]!, paneIndex);
    entry.count++;
    const chart = this._chart;
    let slot = paneIndex;

    const state: ItemState = {
      series, entry, scale: series.priceScale(), savedScaleMode: series.priceScale().options.mode,
      savedInverted: series.priceScale().options.inverted, appliedInverted: null,
      scaleId, type: options.type ?? 'line', style, items: [], values: new Map(), suppressed: false,
      bars: options.bars, alignment: EMPTY_ALIGNMENT, removed: false,
    };
    if (this._mode !== 'none') state.scale.setOptions({ mode: this._mode });
    const handle: ComparisonHandle = {
      symbol: options.symbol,
      series,
      // Live, so a comparison on the price pane still names it after the pane
      // moves; the last slot it held once the pane is gone.
      get paneIndex(): number {
        const at = chart.panes().indexOf(entry.pane);
        if (at >= 0) slot = at;
        return slot;
      },
      priceScale: () => state.scale,
      alignment: () => state.alignment,
      barAt: (time): Readonly<Bar> | null => {
        const bar = state.values.get(time);
        return !state.removed && !state.suppressed && bar && Number.isFinite(bar.close) ? bar : null;
      },
      setBars: (bars: readonly SeriesDataItem[]): void => {
        if (state.removed) return;
        state.bars = bars;
        this._align(state, this._primaryBars());
      },
      remove: (): void => { this.remove(handle); },
      list: () => this.list(),
    };
    this._items.set(handle, state);
    this._align(state, this._primaryBars());
    this._rememberAlignment();
    return handle;
  }

  /** Take one instrument off. Returns false if it was already gone. */
  public remove(handle: ComparisonHandle): boolean {
    const state = this._items.get(handle);
    if (state === undefined || state.removed) return false;
    this._restoreScale(state);
    state.removed = true;
    this._items.delete(handle);
    // The pane is put back first, then the series goes: dropping the series
    // raises a full repaint, and a host running frames synchronously would
    // otherwise paint one more time in a mode we were about to restore.
    const entry = state.entry;
    if (--entry.count <= 0) this._closePane(entry);
    state.series.remove();
    return true;
  }

  /** Every comparison on the chart, in the order they were added. */
  public list(): readonly ComparisonHandle[] {
    return Array.from(this._items.keys());
  }

  /** Take them all off, putting every pane back the way it was found. */
  public clear(): void {
    for (const handle of this.list()) this.remove(handle);
  }

  /**
   * Change the mode the panes are held in while comparisons are on them.
   * Panes that already have one switch immediately.
   */
  public setMode(mode: ComparisonMode): void {
    if (mode === this._mode) return;
    this._mode = mode;
    this._syncing = true;
    try {
      for (const entry of this._panes.values()) {
        this._restoreMode(entry);
        this._applyMode(entry);
      }
      for (const state of this._items.values()) this._setSuppressed(state, false);
    } finally { this._syncing = false; }
    this._repaint();
  }

  public get mode(): ComparisonMode {
    return this._mode;
  }

  /** Select a shared timestamp without changing the instruments' stored price units. */
  public setBaseline(baseline: ComparisonBaseline): void {
    if (baseline === this._baseline) return;
    this._baseline = baseline;
    this._syncing = true;
    try {
      for (const state of this._items.values()) this._setSuppressed(state, false);
    } finally { this._syncing = false; }
    this._repaint();
  }

  public get baseline(): ComparisonBaseline { return this._baseline; }

  /**
   * Shared baseline timestamp, or null for no overlap, no visible sources, or
   * independent baselines. Asks about the price pane unless a slot is named.
   */
  public baselineTime(paneIndex?: number): number | null {
    const pane = this._chart.panes()[paneIndex ?? this._chart.primaryPaneIndex?.() ?? 0];
    const entry = pane === undefined ? undefined : this._panes.get(pane);
    return this._baseline === 'common' && this._mode !== 'none' && entry && entry.primary.options.mode === entry.applied
      ? this._commonAnchor(entry, this._visiblePrimary())?.time ?? null : null;
  }

  /**
   * Re-project onto the primary's current bars. Chart handles data replacement
   * and replay automatically. A structural host without data events or primary
   * history identity can call this after replacing its timestamps.
   */
  public realign(): void {
    if (this._realigning || this._destroyed || !this._items.size) return;
    this._realigning = true;
    const syncing = this._syncing;
    this._syncing = true;
    try {
      const bars = this._primaryBars();
      for (const state of this._items.values()) this._align(state, bars);
      this._rememberAlignment();
    } finally { this._realigning = false; this._syncing = syncing; }
    if (!syncing) this._repaint();
  }

  /**
   * Bring the overlay scales in line with the primary axis, re-aligning first
   * if the shared time axis has moved under us (a live bar, history paged in,
   * a replay step). Runs once per base paint through the per-pane hook.
   *
   * Re-aligning here writes series data mid-frame, which is safe because the
   * hook is a `bottom` primitive: it runs after the pane has autoscaled and
   * before any series is drawn, so the frame that notices the change is also
   * the frame that draws it. The repaint that write asks for lands on the next
   * frame, or re-enters this one on a host that runs frames synchronously,
   * which is what `realign`'s guard is for.
   */
  public sync(): void {
    if (this._syncing) return;
    this._syncing = true;
    try {
      if (this._needsAlignment()) this.realign();
      for (const entry of this._panes.values()) this._mirror(entry);
    } finally { this._syncing = false; }
  }

  /** Remove every comparison and forget the chart. */
  public destroy(): void {
    if (this._destroyed) return;
    this.clear();
    this._dispose();
  }

  private _dispose(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    for (const off of this._off.splice(0)) off();
    for (const state of this._items.values()) {
      state.removed = true; state.bars = []; state.items = []; state.values.clear();
    }
    this._items.clear(); this._panes.clear(); this._alignedPrimary = null;
    controllers.delete(this._chart);
  }

  private _needsAlignment(): boolean {
    if (this._destroyed || !this._items.size) return false;
    const primary = this._chart.primaryBars?.();
    return this._chart.dataLayer.length !== this._alignedAt || Boolean(primary && (
      primary !== this._alignedPrimary || primary.length !== this._primaryLength
      || primary[0]?.time !== this._primaryFirst || primary[primary.length - 1]?.time !== this._primaryLast
    ));
  }

  private _rememberAlignment(): void {
    this._alignedAt = this._chart.dataLayer.length;
    this._alignedPrimary = this._chart.primaryBars?.() ?? null;
    this._primaryLength = this._alignedPrimary?.length ?? -1;
    this._primaryFirst = this._alignedPrimary?.[0]?.time;
    this._primaryLast = this._alignedPrimary?.[this._primaryLength - 1]?.time;
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  /**
   * Preserve the first comparison's legacy placement when the scale is free.
   * Additional comparisons need their own baselines, and an occupied volume
   * or left scale must keep its source and units.
   */
  private _scaleIdFor(paneIndex: number): PriceScaleId {
    const pane = this._chart.panes()[paneIndex];
    const used = (id: string): boolean => pane?.series().some(s => s.scaleId === id) ?? false;
    if (pane === undefined || !this._panes.has(pane)) {
      if (!used('')) return '';
      if (!used('left')) return 'left';
    }
    let id: PriceScaleId;
    do { id = `overlay:comparison-${++this._nextScale}`; } while (used(id));
    return id;
  }

  private _openPane(pane: ComparisonPane, paneIndex: number): PaneEntry {
    const primary = pane.priceScale;
    const entry: PaneEntry = {
      pane,
      primary,
      savedPrimaryMode: primary.options.mode,
      applied: null,
      // A primitive that paints nothing, used purely as a frame hook.
      // `afterAutoscale` runs once every scale on the pane has been measured and
      // before anything is painted, which is the only window in which the
      // overlay's range can be corrected and still reach its own axis: the price
      // axes are drawn near the top of `paintBase`, well before primitives, so a
      // correction made in `draw` labelled the left ladder from the range of the
      // previous frame, and on a chart that had stopped repainting, never.
      sync: { zOrder: () => 'bottom', draw: (): void => {}, afterAutoscale: (): void => { this.sync(); } },
      count: 0,
    };
    this._panes.set(pane, entry);
    this._applyMode(entry);
    this._chart.addPrimitive(entry.sync, paneIndex);
    return entry;
  }

  private _closePane(entry: PaneEntry): void {
    this._restoreMode(entry);
    this._chart.removePrimitive(entry.sync);
    this._panes.delete(entry.pane);
  }

  private _applyMode(entry: PaneEntry): void {
    if (this._mode === 'none') return;
    entry.applied = this._mode;
    entry.primary.setOptions({ mode: this._mode });
    // The overlay is rebased too, or it would keep quoting absolute prices
    // under an axis that no longer does. `chart.setPriceScaleOptions` leaves
    // overlays out of a mode change for the opposite (and correct) reason: it
    // cannot tell a comparison from a volume histogram.
    for (const state of this._items.values()) {
      if (state.entry === entry) state.scale.setOptions({ mode: this._mode });
    }
  }

  private _restoreScale(state: ItemState): void {
    if (state.entry.applied !== null && state.scale.options.mode === state.entry.applied) {
      state.scale.setOptions({ mode: state.savedScaleMode });
    }
    if (state.appliedInverted !== null && state.scale.options.inverted === state.appliedInverted) {
      state.scale.setOptions({ inverted: state.savedInverted });
    }
    state.appliedInverted = null;
  }

  private _restoreMode(entry: PaneEntry): void {
    const applied = entry.applied;
    if (applied === null) return;
    for (const state of this._items.values()) {
      if (state.entry === entry) this._restoreScale(state);
    }
    entry.applied = null;
    // Only put back what is still ours: a user who switched the pane to log
    // while comparing keeps their choice instead of having it silently undone.
    if (entry.primary.options.mode === applied) entry.primary.setOptions({ mode: entry.savedPrimaryMode });
  }

  /**
   * Give the overlay the same band of percent the primary axis is showing, so
   * equal moves land on equal pixels and the divergence between two
   * instruments is the thing you see.
   *
   * Each scale has its own price baseline, and rebasing maps price to the
   * ratio `price / baseline`. So the
   * two scales agree exactly when their ranges hold the same ratios, which is
   * one multiplication: the primary's range times `baseline_overlay /
   * baseline_primary`. It holds for `indexed-to-100` and `percentage` alike,
   * since they are one ladder a hundred points apart.
   *
   * A null baseline means this scale is not rebasing (linear, logarithmic, or
   * a pane with nothing visible on it yet). Then there is no shared ladder to
   * join and the overlay keeps its own autoscale, which is what mode 'none'
   * asks for: two instruments each filling the pane, comparable in shape only.
   *
   * The overlay stays under autoscale throughout, even though the range it
   * measures is overwritten here every frame. That measurement is one pass over
   * bars the renderer is about to walk anyway, and paying for it buys the
   * failure mode we want: a chart that stops calling `sync` falls back to an
   * independently scaled overlay instead of freezing on a stale range.
   */
  private _mirror(entry: PaneEntry): void {
    // Gate on the mode, not merely on a baseline being present. The two used
    // to be the same thing only by accident, and a baseline that outlived its
    // mode kept this mirroring a percentage ladder the user had switched off.
    if (entry.applied === null) return;
    const states = Array.from(this._items.values()).filter(state => state.entry === entry);
    if (entry.primary.options.mode !== entry.applied) {
      for (const state of states) this._setSuppressed(state, false);
      return;
    }
    if (this._baseline === 'common' && entry.primary.options.mode === entry.applied) {
      const bars = this._visiblePrimary();
      const anchor = this._commonAnchor(entry, bars);
      for (const state of states) {
        const value = anchor && state.values.get(anchor.time)?.close;
        this._setSuppressed(state, !value || !Number.isFinite(value) || value <= 0);
      }
      if (anchor === null) return;
      entry.primary.setBaseline(anchor.close);
      const range = entry.primary.priceRange();
      for (const state of states) {
        const value = state.values.get(anchor.time)?.close;
        state.scale.setBaseline(value && value > 0 ? value : null);
        if (!entry.primary.autoScale || !value || value <= 0 || !this._visible(state)) continue;
        // Fit relative moves, not absolute prices. Manual primary ranges stay owned by the user.
        const renderer = getChartType(state.type);
        const style = this._record(state)?.style ?? state.style;
        let low = Infinity, high = -Infinity;
        for (const bar of bars) {
          const own = state.values.get(bar.time);
          if (!own) continue;
          const extents = renderer.extents(own, style);
          if (!Number.isFinite(extents.min) || !Number.isFinite(extents.max)) continue;
          low = Math.min(low, extents.min); high = Math.max(high, extents.max);
        }
        if (!(low <= high)) continue;
        const fitted = scaleAutoscaleRange(entry.primary.options.mode, low, high, entry.primary.options.marginTop, entry.primary.options.marginBottom);
        const factor = anchor.close / value;
        range.min = Math.min(range.min, fitted.min * factor);
        range.max = Math.max(range.max, fitted.max * factor);
      }
      if (entry.primary.autoScale) entry.primary.setComputedRange(range);
    }
    const bp = entry.primary.baseline;
    if (bp === null || !Number.isFinite(bp) || bp <= 0 || !entry.primary.scaled) return;
    const range = entry.primary.priceRange();
    for (const state of this._items.values()) {
      if (state.entry !== entry) continue;
      const bc = state.scale.baseline;
      if (bc === null || !Number.isFinite(bc) || bc <= 0) continue;
      const k = bc / bp;
      state.appliedInverted = entry.primary.options.inverted;
      state.scale.setOptions({ inverted: state.appliedInverted });
      state.scale.setComputedRange({ min: range.min * k, max: range.max * k });
    }
  }

  private _primaryBars(): readonly Bar[] {
    return this._chart.primaryBars?.() ?? this._chart.primarySeries()?.getData() ?? [];
  }

  private _record(state: ItemState): ReturnType<ComparisonPane['series']>[number] | undefined {
    return state.entry.pane.series().find(record => record.scaleId === state.scaleId);
  }

  private _visible(state: ItemState): boolean { return this._record(state)?.style?.visible !== false; }

  private _visiblePrimary(): readonly Bar[] {
    const bars = this._primaryBars();
    const range = this._chart.getVisibleLogicalRange?.();
    if (!range) return bars;
    const lo = Math.max(0, Math.floor(range.from));
    const hi = Math.min(this._chart.dataLayer.length - 1, Math.ceil(range.to));
    if (lo > hi) return [];
    const from = this._chart.dataLayer.indexToTime?.(lo) ?? bars[lo]?.time;
    const to = this._chart.dataLayer.indexToTime?.(hi) ?? bars[hi]?.time;
    if (from === undefined || to === undefined) return [];
    // Both searches read only below `bars.length`.
    let left = 0, right = bars.length;
    while (left < right) {
      const mid = (left + right) >>> 1;
      if (bars[mid]!.time < from) left = mid + 1;
      else right = mid;
    }
    let end = left;
    while (end < bars.length && bars[end]!.time <= to) end++;
    return bars.slice(left, end);
  }

  private _commonAnchor(entry: PaneEntry, bars: readonly Bar[]): Bar | null {
    const active = Array.from(this._items.values()).filter(state => state.entry === entry && this._visible(state));
    if (!active.length) return null;
    return bars.find(bar => Number.isFinite(bar.close) && bar.close > 0 && active.every(state => {
      const value = state.values.get(bar.time)?.close;
      return value !== undefined && Number.isFinite(value) && value > 0;
    })) ?? null;
  }

  private _setSuppressed(state: ItemState, suppressed: boolean): void {
    if (suppressed === state.suppressed) return;
    state.suppressed = suppressed;
    this._write(state);
  }

  private _write(state: ItemState): void {
    state.series.setData(state.suppressed ? state.items.map(item => ({ time: item.time })) : state.items);
  }

  private _align(state: ItemState, primary: readonly Bar[]): void {
    const window = replayWindow(this._chart);
    const shown = window ? primary.filter(bar => bar.time <= window.time) : primary;
    const source = window?.forming ? state.bars.filter(bar => bar.time !== window.time) : state.bars;
    const result = alignToPrimary(shown, source);
    state.alignment = result.alignment;
    state.items = result.items;
    state.values = new Map(result.items.map(item => { const bar = toBar(item); return [bar.time, bar]; }));
    this._write(state);
  }

  /**
   * Ask for a full repaint after a mode change. The pane hands a rebasing scale
   * its baseline during the autoscale pass, so a `Light` repaint (all a
   * primitive's `requestUpdate` raises) would paint the new mode before it has
   * anything to quote against. `applyOptions` is the series handle's own route
   * to a Full invalidation, and an empty patch changes no style. Several of
   * them coalesce into one frame, so asking every comparison costs nothing.
   */
  private _repaint(): void {
    for (const state of this._items.values()) state.series.applyOptions({});
  }
}

/** One controller per chart, so `addComparison` can be called as a free function. */
const controllers = new WeakMap<ComparisonChartHost, ComparisonController>();

/** Exporting data must not create a controller or subscribe to chart events. */
export function existingComparisonHandles(chart: ComparisonChartHost): readonly ComparisonHandle[] {
  return controllers.get(chart)?.list() ?? [];
}

/**
 * The controller for a chart, created on first use. Use it to change the mode
 * for the whole chart, to list what is on it, or to clear it.
 *
 * A chart has one, so a later call returns the same controller, with the `mode`
 * and `baseline` it passes applied through `setMode` and `setBaseline`. An
 * attach helper merges a repeated request this way; a controller that owns
 * state a second owner would fight over (alerts, a replay group) refuses one.
 */
export function comparisonController(
  chart: ComparisonChartHost,
  options?: ComparisonControllerOptions,
): ComparisonController {
  let controller = controllers.get(chart);
  if (controller === undefined) {
    controller = new ComparisonController(chart, options);
    controllers.set(chart, controller);
  } else {
    if (options?.mode !== undefined) controller.setMode(options.mode);
    if (options?.baseline !== undefined) controller.setBaseline(options.baseline);
  }
  return controller;
}

/**
 * Put an instrument on the chart next to the primary one:
 *
 * ```ts
 * const bn = addComparison(chart, { symbol: 'BANKNIFTY', bars, color: '#f0b90b' });
 * ```
 *
 * The pane switches to percentage while any comparison is on it and goes back
 * to the mode it had when the last one leaves.
 */
export function addComparison(chart: ComparisonChartHost, options: ComparisonOptions): ComparisonHandle {
  return comparisonController(chart).add(options);
}
