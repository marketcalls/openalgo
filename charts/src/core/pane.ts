/**
 * A pane is one vertically-stacked drawing region (price pane, volume pane,
 * indicator pane). It owns a base + top canvas (ARCHITECTURE.md §3.1) and a
 * price scale, and renders its series against the shared time scale + DataLayer.
 *
 * The canvas pile, bottom to top, and what lands on each:
 *
 *   base canvas (2D context, z 0): background, grid, the series pass, the
 *     normal-layer primitives, the axis strip (ladder, last-price tag, value
 *     tags, trading pills). Repainted on Light and Full.
 *   top canvas (2D context, z 1): the crosshair and its tags, and the
 *     top-layer primitives (drawings over the series or lifted for a drag,
 *     legends, tables, trading buttons, trade markers). Repainted on Cursor.
 *     Order and position lines are normal-layer price lines on the base canvas.
 *
 * Both canvases are the pane's height. Their backing store is `media x dpr`,
 * or the device-pixel box the browser reports where it reports one
 * (`CanvasLayer.setDeviceSize`), and the chart puts every pane boundary on a
 * device pixel, so neither canvas is ever stretched by a fraction of a pixel.
 * Under the rule between panes (`setSeparator`) they start one CSS pixel down
 * at a whole-number ratio and at the pane's top at a fractional one.
 *
 * A GPU backend adds no canvas to the pile. It rasterises the series pass on
 * one page-wide offscreen surface shared by every pane of every chart and
 * blits the result into the base canvas at `endFrame`, between the grid and
 * the normal-layer primitives, exactly where the 2D backend would have
 * painted them. That is why the grid, the primitives, the axes and the
 * overlay keep painting on 2D contexts whatever the backend is, why
 * `takeScreenshot` and the export still read `base.element`, and why a
 * browser's cap on live WebGL contexts never limits how many panes a page
 * can show.
 */
import { CanvasLayer, hairlineHeight, separatorIsBorder } from './canvas';
import { PriceScale } from '../scale/price-scale';
import { type TimeScale } from '../scale/time-scale';
import { barAtIndex, visibleSpan, type DataLayer, type VisibleSpan } from '../model/data-layer';
import type { SeriesRecord, PriceScaleId } from '../model/series';
import type { PriceScaleState } from '../model/chart-state';
import { PriceAxisLayout, isPriceScaleId, type PriceAxisPlacement, type PriceAxisSide, type PriceAxisSlot } from '../model/price-axis-layout';
import { computeGridLines, drawGrid, resolveGridStyle, resolveScaleStyle, type CanvasOptions } from '../render/grid';
import { getChartType, registeredChartTypes, type SeriesRenderContext } from '../model/chart-type-registry';
import type { SeriesStyle } from '../render/series-style';
import { lodActive, lodColumnWidth, lodKind } from '../model/conflation';
import { createSeriesDrawItems, type LodRequest, type SeriesDrawItems } from '../render/draw-items';
import { announcingHost, createHitBoxes, inHitBox } from '../render/hit-boxes';
import {
  drawPriceAxis, drawTimeAxis, drawLastPriceLine, drawLastPriceTag, drawSessionClock,
  drawTimeAxisPill, lastPriceTagHeight, AXIS_LABEL_PRIORITY, resolveAxisLabels, drawSeriesValueTag,
  axisTagY,
  type PlotLayout, type TickMarkType, type AxisLabelBand,
  type SessionClockOptions, type BarCountdownOptions, type AxisStyle,
} from '../render/axis';
import { crosshairTagWidth, drawCrosshair, drawCrosshairTag, resolveCrosshairStyle } from '../render/crosshair';
import { isInvisible } from '../render/pill';
import type { IPrimitive, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, ZOrder } from '../primitives/primitive';
import { PaneLegend } from '../primitives/pane-legend';
import { backendDegradation, type IRenderBackend, type RendererFallbackReason } from '../render/backend';
import { Canvas2dBackend } from '../render/canvas2d-backend';
import type { ChartTheme } from '../theme';
import { DEFAULT_TIMEZONE, formatZonedCrosshairLabel } from '../feed/time';
import type { LooseOptional } from '../helpers/types';

export interface PaneRenderContext {
  timeScale: TimeScale;
  dataLayer: DataLayer;
  /** Restrict the primary series' scale, wherever that series is placed. */
  priceOnlyAutoScale?: boolean;
  primaryDataId?: SeriesRecord['dataId'] | undefined;
  dpr: number;
  priceAxisWidth: number;
  /** Left inset (px) reserved chart-wide for a left price axis; 0/absent when none. */
  leftAxisWidth?: number;
  /** Width of one price column; omitted preserves the legacy single-column layout. */
  axisColumnWidth?: number;
  /** Empty panes show the default column only when the whole chart has no scale users. */
  emptyPriceAxis?: boolean;
  timeAxisHeight: number;
  /** Only the bottom pane draws the time axis. */
  showTimeAxis: boolean;
  /**
   * The pane is folded to its header strip: its legend rows draw and answer
   * the pointer, and the time axis when it is the bottom pane. Series, grid,
   * price axes and every other primitive keep their data and state but
   * neither paint nor hit-test until it opens again.
   */
  collapsed?: boolean;
  /**
   * Draw one OHLC-preserving stick per device-pixel column once bars are
   * narrower than a column (§4.4); false draws every bar at every zoom.
   */
  conflate: boolean;
  /** Columns this many sticks wide (1 = one stick, the default; higher = coarser). */
  conflationFactor: number;
  /** Active palette: drives chrome, series defaults, and trade colors. */
  theme: ChartTheme;
  /** Draw the vertical (time) grid lines. */
  showVertGrid: boolean;
  /** Draw the horizontal (price) grid lines. */
  showHorzGrid: boolean;
  /**
   * The settings dialog's Canvas block (grid, crosshair, scales, margins).
   * Named `canvasOptions` rather than `canvas` so it is never mistaken for the
   * canvas element. Every field is an override: unset falls back to the theme.
   */
  canvasOptions?: CanvasOptions;
  /** Optional custom time label formatter (UTC seconds -> string). Omitted, labels follow `timezone`. */
  timeFormatter?: ((utcSeconds: number, tickMark?: TickMarkType) => string) | undefined;
  /**
   * IANA zone the time axis and crosshair label in. Absent means the shipped
   * default ('Asia/Kolkata'); an explicit `timeFormatter` outranks it, because a
   * host that formats its own labels has already decided the question.
   */
  timezone?: string;
  /**
   * The corner clock between the two axis strips. Absent draws nothing, which
   * is the shipped chart: it is chrome a host asks for.
   */
  sessionClock?: SessionClockOptions | undefined;
  /**
   * The countdown row inside the last-price tag. Absent leaves the tag the one
   * line it has always been.
   */
  barCountdown?: BarCountdownOptions | undefined;
  /** externalId of the primitive under the pointer (hover visual state). */
  hoverId?: string | null;
  hoverKey?: string | null;
  /** externalId of the line currently being dragged (active visual state). */
  dragId?: string | null;
  /**
   * Fill the pane with the theme background before anything else. Absent means
   * yes, which is every on-screen frame; the vector export turns it off for a
   * document that is meant to sit on the host's own page.
   */
  paintBackground?: boolean;
  /**
   * The series a series-band entry ('source:primary', 'indicator:<id>') paints
   * last on this pane, or undefined when it has none here. A primitive placed
   * above that entry paints right after it.
   */
  stackSlot?(entry: string): SeriesRecord | undefined;
}

/**
 * The one colour that stands for a series, for a tag that is too small to carry
 * more than one. Line-family series say it outright; a candle or bar family says
 * it per direction, so the current bar picks the side.
 *
 * Undefined means the series has no colour of its own to borrow, and no tag is
 * worth inventing one for.
 */
function seriesTagColor(style: SeriesStyle, up: boolean): string | undefined {
  if (typeof style.color === 'string') return style.color;
  const directional = up ? style.upColor : style.downColor;
  if (typeof directional === 'string') return directional;
  if (typeof style.closeColor === 'string') return style.closeColor;
  return undefined;
}

/** Where a z-order band paints, back to front; the series band sits between 1 and 2. */
const HIT_RANK: Record<ZOrder, number> = { bottom: 0, normal: 2, top: 3 };

/**
 * Scratch for the pane's visible-bar walks and its level-of-detail request, so
 * a frame allocates nothing per bar or per series for them. Shared by every
 * pane: a frame paints one pane at a time and nothing here outlives a call.
 */
const SPAN: VisibleSpan = { start: 0, lastTime: 0 };
const LOD: LodRequest = { kind: 'ohlc', dpr: 1, factor: 1 };

/** The instrument's last bar, for the last-price line and its axis tag. */
interface LastPriceEntry { close: number; up: boolean; showLine: boolean; showTag: boolean }

/** Another series' last value, tagged on the strip its scale is drawn in. */
interface ValueTag { price: number; color: string; scaleId: PriceScaleId }

/**
 * The renderers the level of detail may hand merged bars to: the built-in ones,
 * as registered before any host code ran. A host may register its own
 * renderer under a built-in name, and it gets every bar, as any other custom
 * type does: it may read fields or neighbours a merge cannot know about.
 */
const LOD_RENDERERS = new Set(registeredChartTypes().map(getChartType));

export class Pane {
  public readonly element: HTMLElement;
  public readonly base: CanvasLayer;
  public readonly top: CanvasLayer;
  /** The rule over the pane's top edge, shown on every pane but the one against the chart's top. */
  private readonly _separator: HTMLElement;
  /**
   * What paints this pane's series onto `base`. Everything else on that canvas
   * (background, grid, axes, primitives) the pane draws itself on the 2D
   * context the backend hands back, so a GPU backend only has to own the one
   * pass that is worth moving. Replaced through `setBackend` when the chart
   * falls back to 2D for the session.
   */
  private _backend: IRenderBackend;
  private _rightScale = new PriceScale();
  /** Extra scales created on demand: left axis and a hidden overlay (volume). */
  private _leftScale: PriceScale | null = null;
  private readonly _overlayScales = new Map<PriceScaleId, PriceScale>();
  private readonly _axisLayout = new PriceAxisLayout();
  /**
   * Scales whose price-per-bar ratio is pinned, with the geometry the ratio was
   * last held against. A lock stores that geometry rather than a number,
   * because the ratio lives in the scale's *transformed* span (log prices are
   * not linear in price) and only the scale itself can measure that. Every
   * later change in bar spacing or pane height is answered by the opposite
   * change in the visible span, which needs no such measurement.
   */
  private readonly _ratioLocks = new Map<PriceScaleId, { barSpacing: number; height: number }>();
  /** Relative height weight within the chart (price=1, volume≈0.3). */
  public weight = 1;
  private readonly _series: SeriesRecord[] = [];
  private readonly _primitives: IPrimitive[] = [];
  private readonly _primitiveScales = new Map<IPrimitive, PriceScaleId>();
  /** Primitives painted inside the series band, each with the entry it sits directly above. */
  private readonly _stackAbove = new Map<IPrimitive, string>();
  /**
   * The chart's price source when it is on this pane. It is the instrument the
   * readout, the last-price line and the rebasing modes describe wherever it
   * paints: moved over a study it is no longer the first series here.
   */
  private _source: SeriesRecord | null = null;
  private _destroyed = false;
  private _width = 0;
  private _height = 0;
  /** Each series' draw items, reused from frame to frame (src/render/draw-items.ts). */
  private readonly _drawItems = new Map<SeriesRecord, SeriesDrawItems>();
  /** Hit boxes of the primitives that declare one, kept while nothing they follow changes (src/render/hit-boxes.ts). */
  private readonly _hitBoxes = createHitBoxes();
  /** Bumped by every change on this pane that can move a primitive's context: series, scales, axes, primitives. */
  private _hitEpoch = 0;

  /**
   * `backend` defaults to the 2D one so a pane built on its own (tests, a host
   * composing panes by hand) paints the way it always has; the chart passes
   * whatever its `renderer` option resolved to.
   */
  public constructor(doc: Document, backend: IRenderBackend = new Canvas2dBackend()) {
    this.element = doc.createElement('div');
    this.element.style.position = 'relative';
    this.element.style.width = '100%';
    this.element.style.flex = '1 1 auto';
    this.element.style.overflow = 'hidden';
    // The rule between stacked panes is DOM rather than a canvas line: it sits
    // on the box boundary, so it cannot drift from the pane it separates when
    // weights change, and costs nothing to repaint. At a whole-number ratio it
    // is this 1 px border, the canvases starting under it and their last row
    // clipped; see `setSeparator` for the fractional ones.
    this.element.style.borderTopStyle = 'solid';
    this.element.style.borderTopWidth = '0px';
    this.element.style.boxSizing = 'border-box';
    this.base = new CanvasLayer(doc, 0);
    this.top = new CanvasLayer(doc, 1);
    this.element.appendChild(this.base.element);
    this.element.appendChild(this.top.element);
    // The rule at a fractional ratio: a box laid over the canvases' first rows.
    const rule = doc.createElement('div');
    const s = rule.style;
    s.position = 'absolute';
    s.left = '0';
    s.top = '0';
    s.width = '100%';
    s.height = '0px';
    s.zIndex = '2';
    s.pointerEvents = 'none';
    s.display = 'none';
    this._separator = rule;
    this.element.appendChild(rule);
    this._backend = backend;
    // The base canvas already holds a 2D context (CanvasLayer asks for it on
    // construction), so the backend is handed that one rather than left to ask
    // for another: a frame is then one context's op stream, which is what the
    // recording-context tests and the parity gate both compare.
    backend.mount(this.base.element, this.base.ctx);
  }

  public get backend(): IRenderBackend {
    return this._backend;
  }

  /**
   * Swap the backend for the rest of the session: the old one releases its
   * resources, the new one takes the base canvas and its context and is told
   * the current size, so it is ready for the very next frame. The chart calls
   * this for every pane at once when a GPU backend degrades, so a chart never
   * paints half its panes one way and half the other.
   */
  public setBackend(next: IRenderBackend): void {
    if (next === this._backend) return;
    this._backend.destroy();
    this._backend = next;
    next.mount(this.base.element, this.base.ctx);
    if (this._width > 0 && this._height > 0) next.resize(this._width, this._height, this.base.pixelRatio);
  }

  /**
   * Why the backend is painting through its 2D fallback rather than the path
   * it was chosen for, or null. Read by the chart after each frame; the
   * answer is a property of the device, so it is the same for every pane
   * sharing it.
   */
  public get backendDegradation(): RendererFallbackReason | null {
    return backendDegradation(this._backend);
  }

  /**
   * The 'right' scale: the pane's primary axis, and the one a series maps to
   * unless it names another. A getter over a field rather than a plain readonly
   * property because `moveSeriesScale` swaps the two side scales, and the range,
   * mode, margins, tick size and formatter all belong to the axis being moved.
   */
  public get priceScale(): PriceScale {
    return this._rightScale;
  }

  public addSeries(record: SeriesRecord): void {
    this._scaleFor(record.scaleId); // create the target scale if needed
    this._series.push(record);
    this._hitEpoch++;
  }

  /** The PriceScale for a scale id, creating the left/overlay scale on first use. */
  private _scaleFor(id: PriceScaleId): PriceScale {
    this._axisLayout.register(id);
    if (id === 'left') return (this._leftScale ??= new PriceScale());
    if (id === '' || id.startsWith('overlay:')) {
      let scale = this._overlayScales.get(id);
      if (!scale) { scale = new PriceScale(); this._overlayScales.set(id, scale); }
      return scale;
    }
    return this._rightScale;
  }

  /**
   * The scale for an id, created if this pane has never used it. A host acting
   * on one axis (a price-axis menu) needs the scale a side *would* use, not
   * only the ones series happen to occupy. Unused scales retain their settings,
   * while axis labels and columns follow the series that use them.
   */
  public scaleFor(id: PriceScaleId): PriceScale {
    return this._scaleFor(id);
  }

  /** True when a series or explicitly bound primitive uses the named scale. */
  public usesScale(id: PriceScaleId): boolean {
    if (this._series.some((s) => s.scaleId === id)) return true;
    for (const bound of this._primitiveScales.values()) if (bound === id) return true;
    return false;
  }

  public axisPlacement(id: PriceScaleId): PriceAxisPlacement {
    return this._axisLayout.get(id);
  }

  public setAxisPlacement(id: PriceScaleId, side: PriceAxisSide, order?: number): boolean {
    if (!this._axisLayout.set(id, side, order)) return false;
    this._hitEpoch++;
    this._retainPlacedScales();
    return true;
  }

  public restoreAxisPlacements(saved: ReadonlyMap<PriceScaleId, PriceAxisPlacement>): void {
    this._axisLayout.restore(saved);
    this._hitEpoch++;
    this._retainPlacedScales();
  }

  private _retainPlacedScales(): void {
    // Reordering a live column can also change a previously vacated peer's rank.
    for (const { scaleId } of this._axisLayout.entries()) {
      if (this._axisLayout.configured(scaleId)) this._scaleFor(scaleId);
    }
  }

  /** Active columns, nearest the plot first on each side. Vacant scales keep their rank. */
  public visibleAxes(emptyPriceAxis = true): readonly { scaleId: PriceScaleId; side: 'left' | 'right'; order: number }[] {
    const empty = emptyPriceAxis && this._series.length === 0 && this._primitiveScales.size === 0;
    return this._axisLayout.entries().filter((entry): entry is typeof entry & { side: 'left' | 'right' } =>
      entry.side !== 'hidden' && (this.usesScale(entry.scaleId) || (empty && entry.scaleId === 'right')))
      .sort((a, b) => a.side.localeCompare(b.side) || a.order - b.order);
  }

  /**
   * Column x positions relative to the plot, shared by rendering and chart input.
   * A collapsed pane has none: it draws no ladder, so no axis gesture may land on it.
   */
  public axisSlots(ctx: PaneRenderContext): readonly PriceAxisSlot[] {
    if (ctx.collapsed === true) return [];
    const layout = this._layout(ctx), counts = { left: 0, right: 0 };
    return this.visibleAxes(ctx.emptyPriceAxis).map(entry => {
      const width = ctx.axisColumnWidth ?? (entry.side === 'left' ? layout.plotLeft : layout.priceAxisWidth);
      const index = counts[entry.side]++;
      return { ...entry, width, x: entry.side === 'left' ? -(index + 1) * width : layout.plotWidth + index * width };
    }).filter(slot => slot.width > 0);
  }

  /**
   * Move every series and bound primitive on one side to the other, axis and all.
   *
   * The two scale objects are swapped rather than their state copied across:
   * the range, mode, margins, tick size and any custom formatter are all
   * properties of the axis being moved, and copying would have to enumerate
   * every one of them (and gain a field each time one is added). What is left
   * behind carries nothing, so it is reset: keeping its range would label the
   * vacated strip with a ladder for prices that are no longer on that side.
   *
   * Refuses when the target side already carries series or bound primitives.
   * One side draws one axis, so a move onto an occupied side could only mean stacking two ladders
   * in one strip or silently sending the sitting tenant the other way, and
   * neither is what "move this axis to the left" asks for.
   */
  public moveSeriesScale(from: 'right' | 'left', to: 'right' | 'left'): boolean {
    if (from === to || !this.usesScale(from) || this.usesScale(to)) return false;
    this._hitEpoch++;
    const moving = this._scaleFor(from);
    const vacated = this._scaleFor(to);
    this._axisLayout.set(to, to);
    this._axisLayout.set(from, from);
    if (to === 'left') {
      this._leftScale = moving;
      this._rightScale = vacated;
    } else {
      this._rightScale = moving;
      this._leftScale = vacated;
    }
    for (const s of this._series) if (s.scaleId === from) s.scaleId = to;
    for (const [primitive, id] of this._primitiveScales) if (id === from) this._primitiveScales.set(primitive, to);
    // `reset` declines to throw away a range a user set by hand, which is right
    // everywhere else and wrong here: there is no series left to re-measure it.
    // A declared band goes first, or the strip would keep the range and the
    // auto-fit refusal that came with the series that just left it.
    vacated.setFixedRange(null);
    vacated.setAutoScale(true);
    vacated.reset();
    const lock = this._ratioLocks.get(from);
    if (lock !== undefined) {
      this._ratioLocks.delete(from);
      this._ratioLocks.set(to, lock);
    }
    return true;
  }

  /** Whether this scale's price-per-bar ratio is currently pinned. */
  public ratioLocked(id: PriceScaleId): boolean {
    return this._ratioLocks.has(id);
  }

  /**
   * Pin (or release) the price-per-bar ratio of one scale, against the geometry
   * in force right now. A locked scale is manual by definition: autoscaling it
   * would re-fit the data every frame and undo the ratio being held.
   *
   * Locking a scale nothing has measured does nothing: there is no ratio to
   * hold yet, and switching it to manual would strand it on the 0..1
   * placeholder with nothing left to measure it. Returns whether the scale
   * ended up in the state asked for; releasing always succeeds.
   */
  public setRatioLock(id: PriceScaleId, on: boolean, barSpacing: number, plotHeight: number): boolean {
    if (!on) {
      this._ratioLocks.delete(id);
      return true;
    }
    const scale = this._scaleFor(id);
    if (!scale.scaled || !(barSpacing > 0) || !(plotHeight > 0)) return false;
    scale.setAutoScale(false);
    this._ratioLocks.set(id, { barSpacing, height: plotHeight });
    return true;
  }

  /** Release every ratio lock on this pane (resetting the view drops them). */
  public clearRatioLocks(): void {
    this._ratioLocks.clear();
  }

  /** The price scale a series maps to (for the series handle's `priceScale()`). */
  public scaleOf(record: SeriesRecord): PriceScale {
    return this._scaleFor(record.scaleId);
  }

  /**
   * Every scale this pane has actually created. The left and overlay scales are
   * built on demand, so a caller applying a pane-wide setting (plot margins,
   * label precision) needs the live set rather than all three ids.
   */
  public scales(): PriceScale[] {
    const out: PriceScale[] = [this.priceScale];
    if (this._leftScale !== null) out.push(this._leftScale);
    out.push(...this._overlayScales.values());
    return out;
  }

  /** Detached scale configuration, excluding data baselines and runtime formatters. */
  public scaleStates(): Partial<Record<PriceScaleId, PriceScaleState>> {
    const entries: [PriceScaleId, PriceScale][] = [['right', this.priceScale]];
    if (this._leftScale !== null) entries.push(['left', this._leftScale]);
    entries.push(...this._overlayScales);
    return Object.fromEntries(entries.map(([id, scale]) => {
      const options = scale.options;
      const state: PriceScaleState = {
        marginTop: options.marginTop, marginBottom: options.marginBottom, minMove: options.minMove,
        minPrecision: options.minPrecision, mode: options.mode, inverted: options.inverted,
        autoScale: scale.autoScale, fixedRange: scale.fixedRange,
        placement: this._axisLayout.get(id),
      };
      if (!scale.autoScale) state.range = scale.priceRange();
      const lock = this._ratioLocks.get(id);
      if (lock && !scale.autoScale) state.ratioLock = { ...lock };
      return [id, state];
    }));
  }

  /**
   * Scales configured with a visible column, including temporarily vacant ones.
   * Hidden overlays are deliberately excluded from chart-wide axis settings.
   *
   * That scale is positioned by whoever created it and by nobody else. A volume
   * histogram sitting in the bottom fifth of the price pane is an overlay with
   * `marginTop: 0.82`, and a chart-wide plot-margin change that swept it up
   * with the visible axes replaced that 0.82 with the dialog's number: the bars
   * grew to fill most of the pane, and putting the dialog back where it started
   * wrote 0.1, not the 0.82 nobody had recorded. Destructive and unrecoverable,
   * from a control that only claims to move the plot inside its own axes.
   */
  public axisScales(): PriceScale[] {
    return this._axisLayout.entries().filter(entry => entry.side !== 'hidden').map(entry => this._scaleFor(entry.scaleId));
  }

  /** True when a series or explicitly bound primitive uses the left axis. */
  public hasLeftScale(): boolean {
    return this._leftScale !== null && this.usesScale('left');
  }

  /** Remove a series record if present; returns true if it was found. */
  public removeSeries(record: SeriesRecord): boolean {
    const i = this._series.indexOf(record);
    if (i < 0) return false;
    this._series.splice(i, 1);
    this._drawItems.delete(record);
    this._hitEpoch++;
    // A scale with nothing left on it keeps describing what just left, and a
    // pane is reused when one indicator replaces another. Forget the range so
    // the next occupant is measured on its own terms, or not labelled at all.
    if (!this.usesScale(record.scaleId)) {
      const scale = this._scaleFor(record.scaleId);
      scale.reset();
      if (record.scaleId !== '' && this._axisLayout.get(record.scaleId).side === 'hidden'
        && !this._axisLayout.configured(record.scaleId) && !scale.hasConfiguration()
        && !this._ratioLocks.has(record.scaleId)) this._overlayScales.delete(record.scaleId);
    }
    return true;
  }

  public series(): readonly SeriesRecord[] {
    return this._series;
  }

  /** Reorder a subset of series without disturbing unrelated sources. */
  public reorderSeries(ordered: readonly SeriesRecord[]): void {
    const members = new Set(ordered);
    const local = ordered.filter(record => this._series.includes(record));
    this._hitEpoch++;
    let index = 0; // one `local` entry for each member slot below
    for (let i = 0; i < this._series.length; i++) if (members.has(this._series[i]!)) this._series[i] = local[index++]!;
  }

  /** Name the chart's price source on this pane, or null when it is elsewhere or gone. */
  public setSourceSeries(record: SeriesRecord | null): void {
    this._source = record;
    this._hitEpoch++;
  }

  /** The price source when it shows a price here, else undefined. */
  private _shownSource(): SeriesRecord | undefined {
    const s = this._source;
    return s !== null && s.style.visible !== false && getChartType(s.type).isPriceSeries && this._series.includes(s) ? s : undefined;
  }

  /** Move one series to just before `before`, or to the end for null: the price source taking its place. */
  public moveSeries(record: SeriesRecord, before: SeriesRecord | null): void {
    const from = this._series.indexOf(record);
    if (from < 0 || record === before) return;
    this._hitEpoch++;
    this._series.splice(from, 1);
    const at = before === null ? -1 : this._series.indexOf(before);
    this._series.splice(at < 0 ? this._series.length : at, 0, record);
  }

  /** Reorder owned visuals within each renderer layer. */
  public reorderPrimitives(ordered: readonly IPrimitive[]): void {
    const members = new Set(ordered);
    const local = ordered.filter(primitive => this._primitives.includes(primitive));
    this._hitEpoch++;
    let index = 0; // one `local` entry for each member slot below
    for (let i = 0; i < this._primitives.length; i++) if (members.has(this._primitives[i]!)) this._primitives[i] = local[index++]!;
  }

  /** Transfer ownership without ending an attached primitive's lifetime. */
  public transferPrimitive(primitive: IPrimitive, target: Pane): boolean {
    const index = this._primitives.indexOf(primitive);
    if (index < 0 || target === this || target._destroyed || target.hasPrimitive(primitive)) return false;
    const scaleId = this._primitiveScales.get(primitive);
    if (scaleId !== undefined) target._scaleFor(scaleId);
    const entry = this._stackAbove.get(primitive);
    this._primitives.splice(index, 1);
    this._primitiveScales.delete(primitive);
    this._stackAbove.delete(primitive);
    this._hitEpoch++;
    target._hitEpoch++;
    target._primitives.push(primitive);
    if (scaleId !== undefined) target._primitiveScales.set(primitive, scaleId);
    if (entry !== undefined) target._stackAbove.set(primitive, entry);
    return true;
  }

  /**
   * Paint an attached primitive in the series band, directly above the entry
   * `above` names, instead of in its own z-order band; null puts it back. An
   * entry with no series on this pane leaves it in its own band.
   */
  public setPrimitiveStackAbove(primitive: IPrimitive, above: string | null): boolean {
    if (this._destroyed || !this.hasPrimitive(primitive)) return false;
    if (above === null) this._stackAbove.delete(primitive);
    else this._stackAbove.set(primitive, above);
    return true;
  }

  /** The entry a primitive is placed above, or null for one in its own band. */
  public primitiveStackAbove(primitive: IPrimitive): string | null {
    return this._stackAbove.get(primitive) ?? null;
  }

  /**
   * The placed primitives this frame can honour, keyed by the series each
   * paints right after, or null when there are none (the common case, which
   * then costs nothing).
   */
  private _slotted(live: readonly IPrimitive[], ctx: PaneRenderContext): Map<IPrimitive, SeriesRecord> | null {
    if (this._stackAbove.size === 0 || ctx.stackSlot === undefined) return null;
    let out: Map<IPrimitive, SeriesRecord> | null = null;
    for (const primitive of live) {
      const entry = this._stackAbove.get(primitive);
      const after = entry === undefined ? undefined : ctx.stackSlot(entry);
      if (after !== undefined && this._series.includes(after)) (out ??= new Map()).set(primitive, after);
    }
    return out;
  }

  /**
   * Whether `primitive` paints under `record`: in the band behind the series,
   * or in the series band after an earlier series. The chart asks when a
   * drawing and a series are both under the pointer, so the one painted on top
   * takes the context menu.
   */
  public paintsBelowSeries(primitive: IPrimitive, record: SeriesRecord, ctx: PaneRenderContext): boolean {
    const entry = this._stackAbove.get(primitive);
    const after = entry === undefined ? undefined : ctx.stackSlot?.(entry);
    const at = after === undefined ? -1 : this._series.indexOf(after);
    return at >= 0 ? at < this._series.indexOf(record) : primitive.zOrder() === 'bottom';
  }

  /**
   * Bind an attached primitive without detaching it. Null restores the right scale.
   * The owner schedules layout and repaint after finishing its resource transaction.
   */
  public bindPrimitiveScale(primitive: IPrimitive, scaleId: PriceScaleId | null): boolean {
    if (this._destroyed || !this.hasPrimitive(primitive)) return false;
    if (scaleId !== null && !isPriceScaleId(scaleId)) return false;
    if (this.primitiveScaleId(primitive) === scaleId) return false;
    this._hitEpoch++;
    if (scaleId === null) this._primitiveScales.delete(primitive);
    else {
      this._scaleFor(scaleId);
      this._primitiveScales.set(primitive, scaleId);
    }
    return true;
  }

  /** Explicit binding, or null for an unbound or unavailable primitive. */
  public primitiveScaleId(primitive: IPrimitive): PriceScaleId | null {
    return this._primitiveScales.get(primitive) ?? null;
  }

  /** Primitives attached to this pane, in draw order. */
  public primitives(): readonly IPrimitive[] {
    return this._primitives;
  }

  public addPrimitive(primitive: IPrimitive, host: PrimitiveHost): void {
    this._primitives.push(primitive);
    this._hitEpoch++;
    // A primitive with a hit box gets a host that also retires the box when it
    // announces a change; every other one keeps the chart's host as it was.
    primitive.attached?.(primitive.hitBounds === undefined ? host : announcingHost(host));
  }

  /** Whether this pane currently holds `primitive`. */
  public hasPrimitive(primitive: IPrimitive): boolean {
    return this._primitives.includes(primitive);
  }

  /** Remove a primitive if present; returns true if it was found. */
  public removePrimitive(primitive: IPrimitive): boolean {
    const i = this._primitives.indexOf(primitive);
    if (i < 0) return false;
    this._primitives.splice(i, 1);
    this._primitiveScales.delete(primitive);
    this._stackAbove.delete(primitive);
    this._hitEpoch++;
    primitive.detached?.();
    return true;
  }

  /** Detach every primitive (lifecycle cleanup) and remove the pane element. */
  public destroy(): void {
    this._destroyed = true;
    this._primitiveScales.clear();
    this._stackAbove.clear();
    this._drawItems.clear();
    this._hitBoxes.clear();
    for (const p of this._primitives) p.detached?.();
    this._primitives.length = 0;
    this._backend.destroy();
    this.element.remove();
  }

  private _primitiveContext(ctx: PaneRenderContext): PrimitiveRenderContext {
    const layout = this._layout(ctx);
    const slot = this.axisSlots(ctx).find(slot => slot.scaleId === 'right');
    return {
      timeScale: ctx.timeScale,
      priceScale: this.priceScale,
      readoutPriceScale: this._readoutScale(),
      dataLayer: ctx.dataLayer,
      plotWidth: layout.plotWidth,
      plotHeight: layout.plotHeight,
      priceAxisWidth: slot?.width ?? 0,
      priceAxisSide: slot?.side ?? 'hidden',
      priceAxisOffset: slot ? slot.x + (slot.side === 'left' ? slot.width : 0) : undefined,
      dpr: ctx.dpr,
      theme: ctx.theme,
      hoverId: ctx.hoverId ?? null,
      hoverKey: ctx.hoverKey ?? null,
      dragId: ctx.dragId ?? null,
      bars: () => {
        for (const s of this._source !== null && this._series.includes(this._source) ? [this._source, ...this._series] : this._series) {
          if (getChartType(s.type).isPriceSeries) return ctx.dataLayer.seriesBars(s.dataId);
        }
        return [];
      },
    } satisfies LooseOptional<PrimitiveRenderContext> as PrimitiveRenderContext; // an undefined `priceAxisOffset` reads as absent: no axis to sit beside
  }

  private _boundPrimitiveContext(primitive: IPrimitive, context: PrimitiveRenderContext, ctx: PaneRenderContext): PrimitiveRenderContext {
    const id = this._primitiveScales.get(primitive);
    if (id === undefined) return context;
    const slot = this.axisSlots(ctx).find(slot => slot.scaleId === id);
    return { ...context, priceScale: this._scaleFor(id), priceAxisSide: slot?.side ?? 'hidden',
      priceAxisWidth: slot?.width ?? 0,
      priceAxisOffset: slot ? slot.x + (slot.side === 'left' ? slot.width : 0) : undefined } satisfies LooseOptional<PrimitiveRenderContext> as PrimitiveRenderContext;
  }

  /** What a frame draws and the pointer can reach: only the legend rows of a collapsed pane. */
  private _live(ctx: PaneRenderContext): readonly IPrimitive[] {
    return ctx.collapsed === true ? this._primitives.filter(p => p instanceof PaneLegend) : this._primitives;
  }

  /**
   * Topmost primitive hit at media-px (x,y) relative to this pane's plot.
   * `except` is left out, for the chart's corner mark, which yields to
   * anything else at the point.
   *
   * What paints over the series (the overlay band and the front) beats what
   * paints with or behind it (a drawing or a primitive placed in the series
   * band, a drawing sent behind the series, a bottom primitive), whatever the
   * distance: a box under an order line gives the press to the line, as the
   * eye does. On either side the nearest wins, then the one painted later in
   * band order, as `bestHit` ranks them. A hit painted by a primitive placed
   * in the series band names it (`paintedBy`), so the chart can rank it
   * against a series painted over it too.
   *
   * Two things keep a pointer move from asking every primitive. One that
   * declares a hit box is skipped when the point is outside it; the boxes are
   * kept while nothing they depend on changes (`_checkHitBoxes`). And the
   * walk stops at an exact hit in the front band, which nothing after it can
   * outrank: a later primitive would need a smaller distance than zero or a
   * band above the front one, and the order the walk visits primitives in
   * only ever breaks exact ties, which the first hit wins.
   */
  public hitTestPrimitives(x: number, y: number, ctx: PaneRenderContext, except?: IPrimitive | null): PrimitiveHit | null {
    const prc = this._primitiveContext(ctx), live = this._live(ctx), slotted = this._slotted(live, ctx);
    this._checkHitBoxes(ctx);
    let best: PrimitiveHit | null = null, bestRank = 0;
    for (let i = 0; i < live.length; i++) {
      const p = live[i]!;
      if (!p.hitTest || p === except) continue;
      // The kept box first, so a primitive the point is nowhere near costs a
      // read and four comparisons: not even its render context is built.
      let context: PrimitiveRenderContext | undefined;
      let box = this._hitBoxes.kept(i);
      if (box === undefined) box = this._hitBoxes.measure(i, p, context = this._boundPrimitiveContext(p, prc, ctx));
      if (!inHitBox(box, x, y)) continue;
      context ??= this._boundPrimitiveContext(p, prc, ctx);
      let hit = p.hitTest(x, y, context);
      if (hit === null) continue;
      if (this._primitiveScales.has(p)) hit = { ...hit, priceScale: context.priceScale };
      const painter = hit.paintedBy ?? p, after = slotted?.get(painter);
      if (after !== undefined) hit = { ...hit, paintedBy: painter };
      const rank = after !== undefined ? 1 + (this._series.indexOf(after) + 1) / (this._series.length + 1)
        : HIT_RANK[painter === p ? hit.zOrder : painter.zOrder()];
      // Over the series (rank 2 and up) first, then the nearest, then the higher band.
      const side = +(rank >= 2) - +(bestRank >= 2);
      if (best === null || side > 0 || side === 0 && (hit.distance < best.distance || hit.distance === best.distance && rank > bestRank)) {
        best = hit; bestRank = rank;
        if (best.distance === 0 && bestRank >= HIT_RANK.top) break;
      }
    }
    return best;
  }

  /** After an on-screen paint: what the pane shows now is what the key describes (src/render/hit-boxes.ts). */
  private _paintedHitBoxes(ctx: PaneRenderContext): void {
    this._checkHitBoxes(ctx);
    this._hitBoxes.painted();
  }

  /**
   * Read the key the kept hit boxes are checked against: what a primitive's
   * render context can map with (the time scale and the bars' times, every
   * price scale here, the pane's size and axes, the pixel ratio, the readout
   * scale, hover and drag, the theme, the session calendar) and this pane's
   * own count of changes.
   */
  private _checkHitBoxes(ctx: PaneRenderContext): void {
    const key = this._hitBoxes, ts = ctx.timeScale, layer = ctx.dataLayer;
    key.begin();
    key.number(this._hitEpoch);
    key.number(ctx.dpr);
    key.number(this._width);
    key.number(this._height);
    key.number(ctx.priceAxisWidth);
    key.number(ctx.leftAxisWidth ?? 0);
    key.number(ctx.axisColumnWidth ?? -1);
    key.number(ctx.showTimeAxis ? ctx.timeAxisHeight : -1);
    key.number(ctx.collapsed === true ? 1 : 0);
    key.number(ctx.emptyPriceAxis === false ? 0 : 1);
    key.number(ts.barSpacing);
    key.number(ts.rightOffset);
    key.number(ts.width);
    key.number(layer.length);
    key.number(layer.indexToTime(0) ?? NaN);
    key.number(layer.indexToTime(layer.baseIndex) ?? NaN);
    key.scale(this._rightScale);
    if (this._leftScale !== null) key.scale(this._leftScale);
    for (const scale of this._overlayScales.values()) key.scale(scale);
    key.ref(ctx.hoverId ?? null);
    key.ref(ctx.hoverKey ?? null);
    key.ref(ctx.dragId ?? null);
    key.ref(ctx.theme);
    key.ref(layer.sessionCalendar);
    key.ref(this._readoutScale());
    key.ref(this._rightScale);
    key.end();
  }

  /**
   * Draw the rule over this pane's top edge in `color` at device pixel ratio
   * `dpr`, or none with a null colour.
   *
   * At a whole-number ratio it is the pane's 1 px top border, with the
   * canvases starting under it: 1 px is whole device pixels there, and it is
   * the layout, and the pane-local y, that every earlier release showed. At a
   * fractional ratio a 1 px border is 1.25 or 1.5 device pixels, which starts
   * the canvases part way into a pixel, and the browser then resamples the
   * whole pane and blends the rule into it. There the rule is a box
   * `hairlineHeight(dpr)` tall, one device pixel, laid over the canvases'
   * first rows, and the canvases start on the pane's own top.
   */
  public setSeparator(color: string | null, dpr: number): void {
    const border = separatorIsBorder(dpr) ? color : null;
    const over = border === null ? color : null;
    const box = this.element.style;
    box.borderTopWidth = border === null ? '0px' : '1px';
    box.borderTopColor = border ?? 'transparent';
    const s = this._separator.style;
    s.display = over === null ? 'none' : '';
    s.height = `${over === null ? 0 : hairlineHeight(dpr)}px`;
    s.background = over ?? 'transparent';
  }

  public resize(width: number, height: number, dpr: number): void {
    this._width = width;
    this._height = height;
    this.base.resize(width, height, dpr);
    this.top.resize(width, height, dpr);
    // After the layer, which owns the backing store: a backend that keeps its
    // own buffers (a GL viewport) sizes them to what the canvas now is.
    this._backend.resize(width, height, dpr);
  }

  /**
   * Lay the pane out at a size without touching its canvases. The vector
   * export paints at a size of the caller's choosing and then puts the live
   * size back; resizing a canvas clears it, so going through `resize` would
   * blank the screen until the next frame.
   */
  public setLayoutSize(width: number, height: number): void {
    this._width = width;
    this._height = height;
  }

  /**
   * Give every scale on this pane its plot height. Height is a *layout*
   * property, but it used to be set only inside the autoscale pass, so any
   * conversion between y and price before the first paint divided by zero and returned
   * ±Infinity. Layout is when the height is actually known.
   */
  public setScaleHeights(plotHeight: number): void {
    this.priceScale.setHeight(plotHeight);
    this._leftScale?.setHeight(plotHeight);
    for (const scale of this._overlayScales.values()) scale.setHeight(plotHeight);
  }

  private _layout(ctx: PaneRenderContext): PlotLayout {
    const plotLeft = ctx.leftAxisWidth ?? 0;
    return {
      plotWidth: Math.max(0, this._width - ctx.priceAxisWidth - plotLeft),
      plotHeight: Math.max(0, this._height - (ctx.showTimeAxis ? ctx.timeAxisHeight : 0)),
      priceAxisWidth: ctx.priceAxisWidth,
      timeAxisHeight: ctx.showTimeAxis ? ctx.timeAxisHeight : 0,
      plotLeft,
    };
  }

  /** Autoscale each active price scale from its own series (independent axes). */
  public autoscale(ctx: PaneRenderContext, progress = 1): boolean {
    let easing = false;
    const layout = this._layout(ctx);
    const range = ctx.timeScale.visibleRange();
    easing = this._autoscaleScale(this.priceScale, 'right', ctx, layout.plotHeight, range, progress) || easing;
    if (this._leftScale) easing = this._autoscaleScale(this._leftScale, 'left', ctx, layout.plotHeight, range, progress) || easing;
    for (const [id, scale] of this._overlayScales) {
      easing = this._autoscaleScale(scale, id, ctx, layout.plotHeight, range, progress) || easing;
    }
    // After the measuring pass and before anything reads a range: a locked
    // scale is manual, so nothing above touched it, and the correction has to
    // land before the axis is labelled from it.
    if (this._ratioLocks.size > 0) this._applyRatioLocks(ctx.timeScale.barSpacing, layout.plotHeight);
    // Every scale on the pane now holds a measured range, and nothing has been
    // painted yet. That is the only window in which a primitive can correct a
    // scale and still have the axis drawn from the corrected value.
    for (const p of this._primitives) p.afterAutoscale?.();
    return easing;
  }

  private _autoscaleScale(
    scale: PriceScale,
    scaleId: PriceScaleId,
    ctx: PaneRenderContext,
    plotHeight: number,
    range: { from: number; to: number },
    progress: number,
  ): boolean {
    const primaryOnly = ctx.priceOnlyAutoScale === true
      && this._series.some(s => s.dataId === ctx.primaryDataId && s.scaleId === scaleId);
    const match = (s: SeriesRecord): boolean => s.scaleId === scaleId && (!primaryOnly || s.dataId === ctx.primaryDataId);
    scale.setHeight(plotHeight);
    // Before the manual-range early-out on purpose: an axis-dragged scale still
    // has to label itself, and the gather loop below never runs for it. Guarded
    // on the mode: only the rebasing modes quote against the first visible bar.
    const mode = scale.options.mode;
    if (mode === 'percentage' || mode === 'indexed-to-100') {
      scale.setBaseline(this._firstVisibleValue(match, ctx, range, primaryOnly));
    }
    if (!scale.autoScale) return false; // manual (axis-dragged) range: leave it
    let low = Infinity;
    let high = -Infinity;
    for (const s of this._series) {
      if (s.style.visible === false || !match(s)) continue;
      const entry = getChartType(s.type);
      // The same shift the paint pass applies, so the range fits what is drawn.
      // Walked in place rather than through `visibleBars`, which builds a pair
      // per bar, every frame of a pan.
      const shift = s.style.barOffset ?? 0;
      const layer = ctx.dataLayer, bars = layer.seriesBars(s.dataId), span = SPAN;
      if (!visibleSpan(layer, bars, range.from - shift, range.to - shift, span)) continue;
      for (let i = span.start; i < bars.length; i++) {
        const bar = bars[i]!;
        if (bar.time > span.lastTime) break;
        if (layer.timeToIndex(bar.time) === undefined) continue;
        const ext = entry.extents(bar, s.style);
        if (ext.min < low) low = ext.min;
        if (ext.max > high) high = ext.max;
      }
    }
    for (const p of this._primitives) {
      if (primaryOnly) break;
      if ((this._primitiveScales.get(p) ?? 'right') !== scaleId) continue;
      const ext = p.autoscaleInfo?.();
      if (ext) {
        if (ext.min < low) low = ext.min;
        if (ext.max > high) high = ext.max;
      }
    }
    return low <= high ? scale.autoscale(low, high, progress) : false;
  }

  /**
   * Hold every locked scale's price-per-bar ratio against the geometry it is
   * being painted into. A bar is `barSpacing` px wide and the plot is
   * `plotHeight` px tall, so a fixed ratio means the visible price span moves
   * with height / barSpacing: zoom in on time and the same slope needs fewer
   * prices in view to keep drawing at the same angle.
   */
  private _applyRatioLocks(barSpacing: number, plotHeight: number): void {
    if (!(barSpacing > 0) || !(plotHeight > 0)) return;
    for (const [id, ref] of this._ratioLocks) {
      const factor = (plotHeight / barSpacing) / (ref.height / ref.barSpacing);
      // Advance the reference even when the correction is skipped, or a scale
      // that could not take one would keep answering for geometry two zooms old.
      ref.barSpacing = barSpacing;
      ref.height = plotHeight;
      if (!isFinite(factor) || factor <= 0 || Math.abs(factor - 1) < 1e-9) continue;
      const scale = this._scaleFor(id);
      if (scale.scaled) this._scaleSpan(scale, factor);
    }
  }

  /**
   * Multiply a scale's visible span by `factor` around the middle of the pane,
   * in the scale's own transformed space so a log axis scales by decades rather
   * than by price. Reading the endpoints back through `yToPrice` is what keeps
   * this transform-agnostic: y is linear in transformed space by construction,
   * whichever mode the scale is in.
   */
  private _scaleSpan(scale: PriceScale, factor: number): void {
    const h = scale.height;
    if (!(h > 0)) return;
    const half = (h / 2) * factor;
    const a = scale.yToPrice(h / 2 - half);
    const b = scale.yToPrice(h / 2 + half);
    if (!isFinite(a) || !isFinite(b) || a === b) return;
    scale.setPriceRange({ min: Math.min(a, b), max: Math.max(a, b) });
  }

  /** Close of the first visible bar on this scale: the rebasing modes quote against it. */
  private _firstVisibleValue(
    match: (s: SeriesRecord) => boolean,
    ctx: PaneRenderContext,
    range: { from: number; to: number },
    honorOffset = false,
  ): number | null {
    // The price source first: what a rebased axis quotes against must not
    // change when the source is moved over a study.
    const source = this._shownSource();
    for (const s of source ? [source, ...this._series] : this._series) {
      if (s.style.visible === false || !match(s)) continue;
      const shift = honorOffset ? s.style.barOffset ?? 0 : 0;
      const layer = ctx.dataLayer, bars = layer.seriesBars(s.dataId), span = SPAN;
      if (!visibleSpan(layer, bars, range.from - shift, range.to - shift, span)) continue;
      for (let i = span.start; i < bars.length; i++) {
        const bar = bars[i]!;
        if (bar.time > span.lastTime) break;
        if (layer.timeToIndex(bar.time) === undefined) continue;
        if (isFinite(bar.close)) return bar.close; // whitespace bars are NaN
      }
    }
    return null;
  }

  /**
   * Paint background + grid + series + axes on the base canvas, or into
   * `target` when given: the vector export runs this exact pass into a
   * serialising context, so what it produces is the frame and not a
   * re-description of it. Only the pane's own canvas is cleared first; a
   * target starts empty by construction.
   */
  public paintBase(ctx: PaneRenderContext, target?: CanvasRenderingContext2D): void {
    const layout = this._layout(ctx);
    const dpr = ctx.dpr;
    // On screen, the chrome goes on whatever 2D context the backend offers
    // (the base canvas's own, for the 2D backend). A serialising target takes
    // the whole frame, series included: the export is a document, and the
    // backend has no pixels to put in one.
    const g = target ?? this._backend.overlay2d() ?? this.base.ctx;
    if (target === undefined) this._backend.beginFrame(true);
    const open = ctx.collapsed !== true;
    const live = this._live(ctx);

    const axisStyle = resolveScaleStyle(ctx.theme, ctx.canvasOptions?.scales);

    // background (full pane), skipped when transparent so the page shows through
    if (ctx.paintBackground !== false && ctx.theme.background !== 'transparent') {
      g.fillStyle = ctx.theme.background;
      g.fillRect(0, 0, Math.round(this._width * dpr), Math.round(this._height * dpr));
    }

    // Shift the plot right by the reserved left-axis width (0 = a no-op).
    g.save();
    if (layout.plotLeft > 0) g.translate(Math.round(layout.plotLeft * dpr), 0);

    // Grid within the plot area. Visibility still comes from the render context
    // (setGridOptions is the long-standing switch); colour, dash, width and
    // spacing come from the canvas block, per axis.
    const gridOpts = ctx.canvasOptions?.grid;
    const lines = computeGridLines(layout.plotWidth, layout.plotHeight, {
      ...gridOpts,
      spacing: gridOpts?.spacing ?? 60,
      vertLines: ctx.showVertGrid && open,
      horzLines: ctx.showHorzGrid && open,
    });
    if (lines.verticals.length > 0 || lines.horizontals.length > 0) {
      drawGrid(g, lines, layout.plotWidth, layout.plotHeight, dpr, resolveGridStyle(ctx.theme, gridOpts, dpr));
    }

    // Everything that draws *in* the plot is clipped to it.
    //
    // A bar is positioned by its centre and drawn outward, so the newest bar
    // sitting against the right edge paints half a body and a wick past it, into
    // the price-axis strip, where it shows through behind the labels. Scrolling
    // the series under the axis makes it obvious. The axis ladder and the tags
    // are drawn after this block is restored, because they live in that strip on
    // purpose and clipping them would erase them.
    g.save();
    g.beginPath();
    g.rect(0, 0, Math.round(layout.plotWidth * dpr), Math.round(layout.plotHeight * dpr));
    g.clip();

    // bottom-layer primitives (background zones) draw behind series
    const prc = this._primitiveContext(ctx);
    const slotted = this._slotted(live, ctx);
    for (const p of live) if (p.zOrder() === 'bottom' && !slotted?.has(p)) p.draw(g, this._boundPrimitiveContext(p, prc, ctx));

    const { readout, lastEntry, valueTags } = this._paintSeriesPass(g, ctx, layout, open, prc, slotted, target);
    // Still inside the clip and before the normal-layer primitives: a backend
    // that batched the series has to land them under the price lines and
    // markers, not over them.
    if (target === undefined) this._backend.endFrame();

    // End of the plot clip. Everything below draws into the axis strip on
    // purpose: the ladder, the last-price tag, the trading pills. Restoring here
    // and not at the end of the frame is the whole point.
    g.restore();

    const slots = this.axisSlots(ctx);
    const colors = { up: ctx.theme.lastPriceUp, down: ctx.theme.lastPriceDown, text: ctx.theme.lastPriceText };
    const last = lastEntry;
    if (last !== null && last.showLine) drawLastPriceLine(g, readout, last.close, last.up, layout, dpr, colors);
    // The countdown counts to the close of the chart's own bar, so it rides
    // on the tag of the pane that shows the price source. A study pane's tag
    // is the study's value: a clock under it named a bar the pane does not
    // draw, and doubled the tag's height into the study's level tags.
    const countdown = this._source !== null && this._series.includes(this._source) ? ctx.barCountdown : undefined;
    const lastTagOn = (scale: PriceScale): boolean => last !== null && last.showTag && readout === scale;
    this._paintAxisLadders(g, layout, dpr, slots, valueTags, last, lastTagOn, countdown, axisStyle);

    // normal-layer primitives (price lines, markers, events) draw over series
    for (const p of live) if (p.zOrder() === 'normal' && !slotted?.has(p)) p.draw(g, this._boundPrimitiveContext(p, prc, ctx));

    // The readout tag goes on after them: where the market is now outranks a
    // level's tag (AXIS_LABEL_PRIORITY), so a price line crossing it, a
    // study's 70 or an order at the touch, does not cover the one number that
    // moves.
    // Only the strip that carries the tag is clipped again: a pane with a
    // strip on each side, or with its tag turned off, pays for no second pass.
    for (const slot of slots) {
      if (last === null || !lastTagOn(this._scaleFor(slot.scaleId))) continue;
      this._inAxisSlot(g, slot, layout, dpr, (scale, columnLayout) => drawLastPriceTag(g, scale, last.close, last.up, columnLayout, dpr,
        axisStyle, { colors, countdown, side: slot.side }));
    }

    if (ctx.showTimeAxis) {
      // The zone goes to the axis rather than being pre-baked into a formatter
      // here: the axis is what decides date-versus-clock and what computes the
      // `tickMark` hint, so a host formatter and the default one only agree on
      // where the day turns over if both are decided on the same calendar.
      drawTimeAxis(g, ctx.timeScale, ctx.dataLayer, layout, dpr, axisStyle, ctx.timeFormatter, ctx.timezone);
      // The corner the two strips meet in, which no tick, tag or series ever
      // occupies. Drawn last so it sits over the time axis's own row.
      if (ctx.sessionClock !== undefined) drawSessionClock(g,
        { ...layout, priceAxisWidth: Math.min(layout.priceAxisWidth, ctx.axisColumnWidth ?? layout.priceAxisWidth) },
        dpr, ctx.sessionClock, axisStyle);
    }
    g.restore(); // end plot shift
    if (target === undefined) this._paintedHitBoxes(ctx);
  }

  /**
   * The series pass of `paintBase`, inside the plot clip: every series at the
   * frame's level of detail, each followed by the primitives slotted above it.
   * It hands back what the axis strips draw afterwards.
   */
  private _paintSeriesPass(g: CanvasRenderingContext2D, ctx: PaneRenderContext, layout: PlotLayout, open: boolean,
    prc: PrimitiveRenderContext, slotted: Map<IPrimitive, SeriesRecord> | null, target: CanvasRenderingContext2D | undefined,
  ): { readout: PriceScale; lastEntry: LastPriceEntry | null; valueTags: ValueTag[] } {
    const dpr = ctx.dpr;
    // series (registry-driven: the core never switches on type)
    const range = ctx.timeScale.visibleRange();
    // Last-price line/tag follows the pane's readout series (the main one),
    // whichever side its scale is drawn on.
    const readout = this._readoutScale();
    // The instrument owns the last-price line: the price source when it shows
    // here, else the first price series on the readout scale, as it always was.
    const source = this._shownSource();
    const instrument = source !== undefined && this._scaleFor(source.scaleId) === readout ? source
      : this._series.find(s => s.style.visible !== false && getChartType(s.type).isPriceSeries && this._scaleFor(s.scaleId) === readout);
    let lastEntry: LastPriceEntry | null = null;
    // Every visible axis describes its own sources, even when the pane's main
    // readout belongs to the other side or a hidden scale.
    const valueTags: ValueTag[] = [];
    // The level of detail is decided once for the frame: every series shares
    // the time scale, so they all cross the threshold together.
    const spacing = ctx.timeScale.barSpacing;
    const columnWidth = lodColumnWidth(dpr, ctx.conflationFactor);
    const lodOn = ctx.conflate && lodActive(spacing, dpr, columnWidth);
    const lod = LOD;
    lod.dpr = dpr;
    lod.factor = ctx.conflationFactor;
    for (const s of this._series) {
      // What sits directly above this series paints right after it, hidden or
      // not: the slot belongs to the entry, not to whether it is showing.
      if (s.style.visible === false || !open) { this._paintSlot(slotted, s, g, prc, ctx, target); continue; }
      const scale = this._scaleFor(s.scaleId);
      const entry = getChartType(s.type);
      // A shifted series is painted `barOffset` bars from where its data sits,
      // so the bars in view are the ones whose shifted position lands in range.
      const shift = s.style.barOffset ?? 0;
      const kind = lodOn && LOD_RENDERERS.has(entry) ? lodKind(s.type) : null;
      if (kind !== null) lod.kind = kind;
      let buffer = this._drawItems.get(s);
      if (buffer === undefined) this._drawItems.set(s, buffer = createSeriesDrawItems());
      const priceToY = buffer.priceToY;
      const items = buffer.build(ctx.dataLayer, s.dataId, range.from - shift, range.to - shift, shift, ctx.timeScale,
        scale, kind === null ? null : lod, entry.connectsBars === true);
      // A merged stick stands for its whole column, so the renderer sizes it
      // for the column rather than for one of the bars inside it.
      const drawSpacing = kind === 'ohlc' ? Math.max(spacing, columnWidth / dpr) : spacing;
      // Previous-close colouring needs the bar left of the visible range to
      // colour the first drawn one; nothing else does, so only that mode pays
      // for the lookup, and only a series with no bar there falls back.
      if (s.style.colorByPreviousClose === true && items.length > 0) {
        const at = buffer.firstIndex() - 1;
        const before = barAtIndex(ctx.dataLayer, s.dataId, at);
        if (before !== undefined) items[0]!.prevClose = before.close; // items is not empty, checked above
      }
      let maxVolume = 0;
      for (let i = 0; i < items.length; i++) {
        const volume = items[i]!.bar.volume ?? 0;
        if (volume > maxVolume) maxVolume = volume;
      }
      const rc: SeriesRenderContext = { plotHeight: layout.plotHeight, maxVolume, theme: ctx.theme };
      if (target === undefined) this._backend.drawSeries(entry, items, priceToY, drawSpacing, dpr, s.style, rc);
      else entry.draw(g, items, priceToY, drawSpacing, dpr, s.style, rc);
      const last = ctx.dataLayer.lastIndexedBar(s.dataId);
      if (last !== null) {
        const color = seriesTagColor(s.style, last.bar.close >= last.bar.open);
        if (s === instrument && lastEntry === null) {
          // The first price series on the readout scale is the instrument, and
          // it owns the last-price line and the countdown tag.
          lastEntry = {
            close: last.bar.close,
            up: last.bar.close >= last.bar.open,
            showLine: s.style.priceLineVisible !== false,
            showTag: s.style.lastValueVisible !== false && (color === undefined || !isInvisible(color)),
          };
        } else if (s.style.lastValueVisible !== false) {
          // A plot that is currently `na` writes NaN rather than dropping the
          // point, and a tag for it would either be blank or, worse, the stale
          // value from whenever the line last had one. A flipped Supertrend's
          // dormant half shows no tag, which is the honest answer.
          if (color !== undefined && !isInvisible(color) && Number.isFinite(last.bar.close)) {
            valueTags.push({ price: last.bar.close, color, scaleId: s.scaleId });
          }
        }
      }
      this._paintSlot(slotted, s, g, prc, ctx, target);
    }
    return { readout, lastEntry, valueTags };
  }

  /** The tick ladder of each axis strip, with the value tags that fit beside the readout tag. */
  private _paintAxisLadders(g: CanvasRenderingContext2D, layout: PlotLayout, dpr: number, slots: readonly PriceAxisSlot[],
    valueTags: readonly ValueTag[], last: LastPriceEntry | null, lastTagOn: (scale: PriceScale) => boolean,
    countdown: BarCountdownOptions | undefined, axisStyle: AxisStyle): void {
    // Resolve each strip independently: equal prices on opposite scales do not
    // overlap. The readout tag outranks series tags, which outrank axis ticks.
    for (const slot of slots) this._inAxisSlot(g, slot, layout, dpr, (scale, columnLayout) => {
      const { side, width, scaleId } = slot;
      const tags = valueTags.filter(tag => tag.scaleId === scaleId);
      const bands: AxisLabelBand[] = [];
      if (last !== null && lastTagOn(scale)) {
        const height = lastPriceTagHeight(dpr, countdown?.visible === true);
        const y = axisTagY(Math.round(scale.priceToY(last.close) * dpr), layout.plotHeight * dpr, height, side);
        if (y !== null) bands.push({ y, height, priority: AXIS_LABEL_PRIORITY.lastPrice });
      }
      const tagBase = bands.length;
      for (const tag of tags) {
        const height = lastPriceTagHeight(dpr);
        const y = axisTagY(Math.round(scale.priceToY(tag.price) * dpr), layout.plotHeight * dpr, height, side);
        bands.push({ y: y ?? NaN, height, priority: AXIS_LABEL_PRIORITY.seriesValue });
      }
      const allowed = bands.length > 0 ? resolveAxisLabels(bands, 2 * dpr) : [];
      const reserved = bands.length > 0 ? bands.filter((_, index) => allowed[index]) : undefined;
      if (side === 'left') {
        // The left tick renderer uses absolute pane coordinates; tags use the
        // same plot-relative coordinates as their source series.
        g.save();
        g.translate(-Math.round(width * dpr), 0);
        drawPriceAxis(g, scale, columnLayout, dpr, axisStyle, reserved, 'left');
        g.restore();
      } else drawPriceAxis(g, scale, columnLayout, dpr, axisStyle, reserved);
      for (let i = 0; i < tags.length; i++) {
        if (allowed[tagBase + i]) drawSeriesValueTag(g, scale, tags[i]!.price, tags[i]!.color, columnLayout, dpr, axisStyle, side);
      }
    });
  }

  /** Paint into one axis strip, clipped to it, in the coordinates its tags use. */
  private _inAxisSlot(g: CanvasRenderingContext2D, slot: PriceAxisSlot, layout: PlotLayout, dpr: number,
    paint: (scale: PriceScale, columnLayout: PlotLayout) => void): void {
    const { side, width } = slot, scale = this._scaleFor(slot.scaleId);
    if (!scale.scaled) return;
    g.save();
    const outer = Math.round(slot.x * dpr), end = Math.round((slot.x + width) * dpr);
    g.beginPath(); g.rect(outer, 0, end - outer, Math.round(layout.plotHeight * dpr)); g.clip();
    g.translate(side === 'left' ? end : outer - Math.round(layout.plotWidth * dpr), 0);
    paint(scale, { ...layout, priceAxisWidth: width, plotLeft: width });
    g.restore();
  }

  /**
   * Paint the primitives placed directly above `record`. A backend that
   * batches series flushes first, so the batch so far lands under them and
   * the series after them on top, the way it keeps a 2D fallback type in order.
   */
  private _paintSlot(slotted: Map<IPrimitive, SeriesRecord> | null, record: SeriesRecord, g: CanvasRenderingContext2D,
    prc: PrimitiveRenderContext, ctx: PaneRenderContext, target: CanvasRenderingContext2D | undefined): void {
    if (slotted === null) return;
    let flushed = false;
    for (const [p, after] of slotted) {
      if (after !== record) continue;
      if (!flushed && target === undefined) this._backend.endFrame();
      flushed = true;
      p.draw(g, this._boundPrimitiveContext(p, prc, ctx));
    }
  }

  /**
   * Top (overlay) canvas: top-layer primitives + crosshair. Cheap repaint on
   * cursor moves. `cross.x` is the shared plot x (vertical line, drawn in every
   * pane for a global crosshair); `cross.yLocal` is the price-line y for the
   * hovered pane only (null elsewhere); `cross.showTimeTag` draws the date tag
   * on the bottom pane's axis strip.
   */
  public paintTop(
    cross: { x: number; yLocal: number | null; showTimeTag: boolean } | null,
    ctx: PaneRenderContext,
    target?: CanvasRenderingContext2D,
  ): void {
    if (target === undefined) this.top.clearBitmap();
    const layout = this._layout(ctx);
    const g = target ?? this.top.ctx;
    const dpr = ctx.dpr;
    // Shift top-layer primitives + crosshair by the reserved left-axis width.
    g.save();
    if (layout.plotLeft > 0) g.translate(Math.round(layout.plotLeft * dpr), 0);
    const prc = this._primitiveContext(ctx);
    const live = this._live(ctx);
    // Resolved only for a top primitive placed in the series band: this runs on
    // every pointer move, and a drawing's series layers are not top primitives.
    const slotted = this._stackAbove.size === 0 ? null : this._slotted(live.filter(p => p.zOrder() === 'top' && this._stackAbove.has(p)), ctx);
    for (const p of live) if (p.zOrder() === 'top' && !slotted?.has(p)) p.draw(g, this._boundPrimitiveContext(p, prc, ctx));
    if (cross !== null) {
      const style = resolveCrosshairStyle(ctx.theme, ctx.canvasOptions?.crosshair, dpr);
      // A strip has no plot to cross; its time tag below still follows the pointer.
      if (ctx.collapsed !== true) drawCrosshair(g, cross.x, cross.yLocal, layout.plotWidth, layout.plotHeight, dpr,
        style.color, style.width, style.dash);

      // An overridden crosshair colour tints its value tags too, the way the
      // reference dialog does; an explicit label background still wins.
      const tagBg = ctx.theme.crosshairLabelBackground ?? style.color;
      const showTags = ctx.theme.crosshairLabelVisible !== false;
      const axisStyle = resolveScaleStyle(ctx.theme, ctx.canvasOptions?.scales);
      // price tag on the strip this pane's prices are actually labelled in
      // (hovered pane only)
      if (showTags && cross.yLocal !== null) {
        const scale = this._readoutScale();
        const slot = this.axisSlots(ctx).find(slot => this._scaleFor(slot.scaleId) === scale);
        if (slot) {
          const text = scale.format(scale.yToPrice(cross.yLocal));
          const start = Math.round(slot.x * dpr), end = Math.round((slot.x + slot.width) * dpr);
          const x = slot.side === 'left' ? end - crosshairTagWidth(g, text, dpr, axisStyle) : start;
          g.save(); g.beginPath(); g.rect(start, 0, end - start, Math.round(layout.plotHeight * dpr)); g.clip();
          drawCrosshairTag(g, text, x, cross.yLocal * dpr, dpr, tagBg, ctx.theme.lastPriceText, 'right', axisStyle);
          g.restore();
        }
      }
      // date/time tag on the bottom pane's axis strip (cross.x is plot-relative)
      if (showTags && cross.showTimeTag && cross.x >= 0 && cross.x <= layout.plotWidth) {
        const idx = Math.round(ctx.timeScale.xToIndex(cross.x));
        const t = ctx.dataLayer.indexToTime(idx);
        if (t !== undefined) {
          const label = ctx.timeFormatter
            ? ctx.timeFormatter(t)
            : formatZonedCrosshairLabel(t, ctx.timezone ?? DEFAULT_TIMEZONE);
          // A pill rather than a plain tag: this one lands on the time strip,
          // over tick labels already on the base canvas, so it needs the
          // opaque backplate to cut them out and the rounded, slightly taller
          // box to read as a separate object instead of one more tick label in
          // a different colour. The price tag above has neither problem.
          drawTimeAxisPill(
            g, label, cross.x * dpr, layout.plotHeight * dpr, dpr,
            { background: tagBg, textColor: ctx.theme.lastPriceText, backplate: ctx.theme.background },
            axisStyle,
          );
        }
      }
    }
    g.restore();
    if (target === undefined) this._paintedHitBoxes(ctx);
  }

  /**
   * The scale this pane's price readout belongs to: the one the chart's price
   * source maps to while it shows here, else the one its first visible price
   * series maps to, falling back to the right scale. A pane whose series
   * sit on the left axis has nothing on the right one, and reading the
   * crosshair price off it would tag the cursor with the 0..1 placeholder.
   */
  private _readoutScale(): PriceScale {
    const source = this._shownSource();
    if (source !== undefined) return this._scaleFor(source.scaleId);
    for (const s of this._series) {
      if (s.style.visible === false) continue;
      if (getChartType(s.type).isPriceSeries) return this._scaleFor(s.scaleId);
    }
    return this._rightScale;
  }

  /**
   * The scale a price quoted for this pane belongs to: the crosshair readout,
   * the price on a click or a drag, and the chart's coordinate API all mean
   * this one. It is the right scale in every layout that has not moved an axis.
   */
  public readoutScale(): PriceScale {
    return this._readoutScale();
  }

  /** Media-px y of a price on this pane's readout scale. The inverse of `yToPrice`. */
  public priceToY(price: number): number {
    return this._readoutScale().priceToY(price);
  }

  /** Price at a media-px y on this pane (crosshair magnet, click/drag readout). */
  public yToPrice(y: number): number {
    return this._readoutScale().yToPrice(y);
  }
}
