/**
 * The chart's input routing: the pointer, wheel, double-click, pinch and
 * keyboard handlers, the context-menu payload and snapshot, hit testing, the
 * hover state and cursor hint, and the crosshair, click and drag events they
 * emit.
 *
 * Its own module because the gesture state (where the press landed, the
 * pointers held, the drag, pinch, axis drag or divider drag in flight, what is
 * hovered) belongs to these handlers alone. The chart reaches it through
 * `Chart._input`, and it reaches the chart through `InputHost`. The listener
 * functions stay on the chart as arrow fields that delegate here, so the
 * function added is the function removed, and the handlers reach each other
 * through those same fields, as they did in chart.ts. Members the chart still
 * calls or reads are public on this internal class; no entry point exports the
 * class and the chart holds it in a private field, so none of it reaches the
 * published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type {
  DoubleClickEvent, CrosshairMoveEvent, PointerSample, PointerInfo, ChartDragEvent, ChartDragEndEvent,
  ContextMenuTarget, ContextMenuEvent, ChartNavigationOptions,
} from './chart-types';
import type { Chart, ChartClickEvent } from './chart';
import type { PriceScale } from '../scale/price-scale';
import type { SeriesRecord } from '../model/series';
import { getChartType } from '../model/chart-type-registry';
import { getIndicator } from '../model/indicator-registry';
import type { PriceAxisSlot } from '../model/price-axis-layout';
import type { Bar } from '../model/bar';
import { barAtIndex } from '../model/data-layer';
import { KineticAnimation } from '../input/kinetic';
import { wheelPixels, wheelLogFactor } from '../input/wheel';
import { magnetSnapPrice } from '../input/crosshair';
import { ShortcutManager } from '../input/shortcuts';
import { pinchState, pinchDelta, type PinchState } from '../input/touch';
import type { PrimitiveHit } from '../primitives/primitive';
import { INDICATOR_LEGEND_TOGGLE } from '../primitives/indicator-legend-toggle';
import { dispatch } from '../helpers/dispatch';
import type { LogoWatermark } from '../primitives/watermark';
import type { TimeNavigatorOptions } from '../primitives/time-navigator';

/**
 * How fast a drag's remembered velocity fades while the pointer is still down,
 * in ms. Short enough that a deliberate pause before releasing kills the fling,
 * long enough that the ordinary jitter between two move events does not.
 */
const KINETIC_VELOCITY_HALFLIFE_MS = 50;

/**
 * How far a press may travel, in media px along either axis, and still end as
 * a click. Past it the gesture is a drag, which is what decides whether a
 * button under the press (an order's cancel box, a legend's hide) fires.
 */
const CLICK_SLOP_PX = 3;

/**
 * The slice of a pointer event the payload builders read. Structural so the
 * same builders serve a coalesced sample, and so a field a browser omits
 * degrades to the spec fallback instead of an `undefined` in a host's hands.
 */
type PointerLike = Partial<Pick<PointerEvent,
  'shiftKey' | 'altKey' | 'ctrlKey' | 'metaKey' | 'pointerType' | 'pressure' | 'buttons'>>;

/**
 * One call to a `subscribeDrag` subscription: a move, or the release. One
 * entry per subscription, rather than one per callback, so unsubscribing is
 * one removal.
 */
interface SubscribedDrag { end: boolean; id: string; price: number; time: number }

/** A pointer position projected onto the pane under it, as the handlers read it. */
type LocalPoint = { x: number; y: number; pane: number; localY: number; paneHeight: number };

/** The three pointer facts every gesture payload carries. */
function pointerInfo(e: PointerLike): PointerInfo {
  const kind = e.pointerType;
  return {
    modifiers: { shift: e.shiftKey === true, alt: e.altKey === true, ctrl: e.ctrlKey === true, meta: e.metaKey === true },
    pointerType: kind === 'touch' || kind === 'pen' ? kind : 'mouse',
    pressure: pointerPressure(e),
  };
}

/**
 * Pressure as the pointer events spec defines it: what the hardware measured,
 * else 0.5 while a button is held and 0 otherwise. Browsers already report
 * that stand-in for a mouse; the fallback covers an event that omits the
 * field, so a host never reads `undefined` or a value outside 0..1.
 */
function pointerPressure(e: PointerLike): number {
  const p = e.pressure;
  if (typeof p === 'number' && Number.isFinite(p)) return Math.min(1, Math.max(0, p));
  return (e.buttons ?? 0) !== 0 ? 0.5 : 0;
}

/**
 * The slice of the chart the input routing reads and drives. The chart itself
 * is the host: each member carries the name and the type of the chart's own,
 * so the moved code reads as it did in chart.ts, and a member the chart
 * renames or retypes fails to compile here. The writable fields are the
 * chart's own, assigned here.
 */
export interface InputHost {
  readonly _destroyed: Chart['_destroyed'];
  readonly _panes: Chart['_panes'];
  readonly _primaryPane: Chart['_primaryPane'];
  readonly _container: Chart['_container'];
  readonly _doc: Chart['_doc'];
  readonly _width: Chart['_width'];
  readonly _height: Chart['_height'];
  readonly _leftAxisWidth: Chart['_leftAxisWidth'];
  readonly _rightAxisWidth: Chart['_rightAxisWidth'];
  readonly _timeAxisHeight: Chart['_timeAxisHeight'];
  readonly _timeScale: Chart['_timeScale'];
  readonly _dataLayer: Chart['_dataLayer'];
  readonly _navigation: Chart['_navigation'];
  readonly _timeNav: Chart['_timeNav'];
  readonly _motion: Chart['_motion'];
  readonly _branding: Chart['_branding'];
  readonly _indicators: Chart['_indicators'];
  readonly _seriesRecords: Chart['_seriesRecords'];
  readonly _bus: Chart['_bus'];
  readonly _shortcuts: Chart['_shortcuts'];
  readonly _firstDataId: Chart['_firstDataId'];
  readonly _timeNavPane: Chart['_timeNavPane'];
  readonly _theme: Chart['_theme'];
  readonly _gridVert: Chart['_gridVert'];
  readonly _gridHorz: Chart['_gridHorz'];
  readonly _zoomAnchor: Chart['_zoomAnchor'];
  readonly _animZoom: Chart['_animZoom'];
  readonly _doubleClick: Chart['_doubleClick'];
  _crosshairMode: Chart['_crosshairMode'];
  /** The fling velocity and its last sample: the chart's own fields, which a test sets there by name. */
  _dragVelocity: Chart['_dragVelocity'];
  _lastDragX: Chart['_lastDragX'];
  _lastDragT: Chart['_lastDragT'];
  /** The chart's own listener functions, added here and removed by the chart, by identity. */
  readonly _onPointerEnter: Chart['_onPointerEnter'];
  readonly _onContextMenu: Chart['_onContextMenu'];
  readonly _onPointerDown: Chart['_onPointerDown'];
  readonly _onPointerMove: Chart['_onPointerMove'];
  readonly _onPointerUp: Chart['_onPointerUp'];
  readonly _onPointerUpNative: Chart['_onPointerUpNative'];
  readonly _onPointerCancel: Chart['_onPointerCancel'];
  readonly _onLostPointerCapture: Chart['_onLostPointerCapture'];
  readonly _onPointerLeave: Chart['_onPointerLeave'];
  readonly _onWheel: Chart['_onWheel'];
  readonly _onDblClick: Chart['_onDblClick'];
  readonly _onKeyDown: Chart['_onKeyDown'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _layout: Chart['_layout'];
  readonly _legendStack: Chart['_legendStack'];
  _now: Chart['_now'];
  _pixelRatio: Chart['_pixelRatio'];
  _renderContext: Chart['_renderContext'];
  _paneLayout: Chart['_paneLayout'];
  _bottomPaneIndex: Chart['_bottomPaneIndex'];
  _ensureScaled: Chart['_ensureScaled'];
  _xToTime: Chart['_xToTime'];
  _mutateTimeScale: Chart['_mutateTimeScale'];
  _emitViewport: Chart['_emitViewport'];
  _emitViewportIfMoved: Chart['_emitViewportIfMoved'];
  _maybeLoadHistory: Chart['_maybeLoadHistory'];
  _startKinetic: Chart['_startKinetic'];
  _handleLegendAction: Chart['_handleLegendAction'];
  _feedTimeNav: Chart['_feedTimeNav'];
  _updateAccessibleSummary: Chart['_updateAccessibleSummary'];
  priceAxisLayout: Chart['priceAxisLayout'];
  resetScale: Chart['resetScale'];
  fitContent: Chart['fitContent'];
  downloadScreenshot: Chart['downloadScreenshot'];
  setGridOptions: Chart['setGridOptions'];
  applyOptions: Chart['applyOptions'];
  maximizePane: Chart['maximizePane'];
  invalidate: Chart['invalidate'];
  _emit: Chart['_emit'];
}

export class ChartInput {
  private readonly _host: InputHost;
  private _pointerInside = false;
  public _keyTarget: HTMLElement | Document | null = null;
  public _cursorPane: number | null = null;
  public _cursor: { x: number; y: number } | null = null;
  public _dragging = false;
  /** A cancelled navigation sequence stays consumed until every held pointer ends. */
  public _navigationCancelled = false;
  private _dragStartX = 0;
  private _dragStartY = 0;
  private _lastDragY = 0;
  // multi-touch: active pointers + current pinch gesture
  /** Pointers whose gesture the missed-release recovery already ended. */
  private readonly _endedPointers = new Set<number>();
  public readonly _pointers = new Map<number, { x: number; y: number; pane: number }>();
  public _pinch: PinchState | null = null;
  private _pinchPane = 0;
  private _dragStartOffset = 0;
  private _indicatorTogglePress: { pointerId: number; moved: boolean } | null = null;
  /** Native double clicks can join a consumed count press to a newly empty plot row. */
  private _lastPressOnIndicatorToggle = false;
  private _previousPressOnIndicatorToggle = false;
  /** `subscribeClick` and `subscribeCrosshairMove` subscribers: the host's and the trade layer's alike. */
  public readonly _clickCbs = new Set<(externalId: string) => void>();
  public readonly _crosshairCbs = new Set<(e: CrosshairMoveEvent) => void>();
  public _readoutTime: number | null = null;
  public _pointerMoved = false;
  /** While true, pointer gestures place anchors instead of panning. */
  public _placementMode = false;
  private _downPane = 0;
  private _downX = 0;
  private _downLocalY = 0;
  /** Pressure at the press; a click reports this, since its release always reads 0. */
  private _downPressure = 0;
  public _dragId: string | null = null; // externalId of the primitive being dragged
  private _dragPriceScale: PriceScale | null = null;
  private _dragCancelOnEscape = false;
  public _hoverId: string | null = null; // externalId of the primitive under the pointer
  public _hoverKey: string | null = null;
  /** Whether that primitive draws below the overlay, so leaving it must repaint the base. */
  private _hoverOnBase = false;
  public _overlayFrozen = false; // native context menu open: keep the save-image snapshot
  /** The navigator's buttons as configured, before the navigation policy withholds any. */
  public _timeNavButtons: TimeNavigatorOptions['buttons'] = [];
  /** `subscribeDrag` subscribers. While there is one, an `ns-resize` price line drags. */
  public readonly _dragCbs = new Set<(drag: SubscribedDrag) => void>();
  // axis-drag rescale (price axis = vertical, time axis = horizontal)
  public _axisDrag: 'price' | 'time' | 'empty' | null = null;
  /** The scale a price-axis drag is rescaling: either side's, whichever strip was grabbed. */
  public _axisDragScale: PriceScale | null = null;
  /** True once a primitive drag has actually moved (see the pointerup note). */
  private _dragMoved = false;
  /** Where the drag was grabbed, in data space, so deltas start at the press. */
  private _dragFrom: { time: number; price: number } = { time: 0, price: 0 };
  /** Active pane-divider drag: which boundary, and the weights/heights at grab time. */
  private _paneResize: {
    a: number; b: number; startY: number;
    aWeight: number; bWeight: number; aHeight: number; bHeight: number;
  } | null = null;
  private _axisStartCoord = 0;
  private _axisStartMin = 0;
  private _axisStartMax = 0;
  private _axisStartSpacing = 0;
  private _brandingPress: { pointerId: number; mark: LogoWatermark; moved: boolean } | null = null;

  public constructor(host: InputHost) {
    this._host = host;
  }

  public _attachInput(): void {
    if (typeof window === 'undefined') return;
    const el = this._host._container;
    el.addEventListener('pointerdown', this._host._onPointerDown);
    el.addEventListener('pointermove', this._host._onPointerMove);
    el.addEventListener('pointerup', this._host._onPointerUpNative);
    el.addEventListener('pointercancel', this._host._onPointerCancel);
    el.addEventListener('lostpointercapture', this._host._onLostPointerCapture);
    el.addEventListener('pointerleave', this._host._onPointerLeave);
    el.addEventListener('wheel', this._host._onWheel, { passive: false });
    el.addEventListener('dblclick', this._host._onDblClick);
    el.addEventListener('pointerenter', this._host._onPointerEnter);
    el.addEventListener('contextmenu', this._host._onContextMenu);
    // Keyboard: listen on the document when available (so shortcuts fire on hover
    // without focusing the chart), else on the focusable container. The handler
    // gates by scope / hover / focus.
    const keyTarget: HTMLElement | Document =
      typeof this._host._doc.addEventListener === 'function' ? this._host._doc : el;
    keyTarget.addEventListener('keydown', this._host._onKeyDown as EventListener);
    this._keyTarget = keyTarget;
  }

  /** Take off what `_attachInput` put on, by the same function identities. */
  public _detachInput(): void {
    if (typeof window === 'undefined') return;
    const el = this._host._container;
    el.removeEventListener('pointerdown', this._host._onPointerDown);
    el.removeEventListener('pointermove', this._host._onPointerMove);
    el.removeEventListener('pointerup', this._host._onPointerUpNative);
    el.removeEventListener('pointercancel', this._host._onPointerCancel);
    el.removeEventListener('lostpointercapture', this._host._onLostPointerCapture);
    el.removeEventListener('pointerleave', this._host._onPointerLeave);
    el.removeEventListener('wheel', this._host._onWheel);
    el.removeEventListener('dblclick', this._host._onDblClick);
    el.removeEventListener('pointerenter', this._host._onPointerEnter);
    el.removeEventListener('contextmenu', this._host._onContextMenu);
    this._keyTarget?.removeEventListener('keydown', this._host._onKeyDown as EventListener);
    this._keyTarget = null;
  }

  public _onPointerEnter(): void { this._pointerInside = true; }

  /**
   * The chart renders as stacked canvases, so the browser's right-click
   * "Save image as…" would capture only the topmost (transparent overlay)
   * layer: a blank image. Just before the native menu opens, composite the
   * clicked pane's base layer *beneath* its overlay bitmap so the saved image
   * is the visible chart, and freeze overlay repaints (live ticks repaint every
   * few hundred ms and would wipe the snapshot while the menu is open). The
   * freeze lifts on the next pointer/wheel/key input after the menu closes.
   * Apps that present their own menu (preventDefault on contextmenu) are
   * unaffected. Multi-pane note: the native save captures the clicked pane
   * only. Use `downloadScreenshot()` for the full multi-pane composite.
   *
   * A listener on the `contextmenu` **chart** event takes over entirely: it is
   * told what was hit, and the snapshot is skipped, since the app is raising a
   * menu of its own instead of the browser's.
   */
  public _onContextMenu(e: MouseEvent): void {
    if (e.defaultPrevented) return; // app shows its own menu (e.g. order entry)
    const p = this._localPoint(e);
    const pane = this._host._panes[p.pane];
    if (pane === undefined) return;
    // A live listener, not a name someone once subscribed to: treating that as
    // "an app is handling it" would silently retire the snapshot fallback for
    // the rest of the chart's life.
    if (this._host._bus.has('contextmenu')) {
      this._host._emit('contextmenu', this._contextMenuEvent(e, p));
      return;
    }
    // Null the crosshair without invalidating: a pointerleave fired while the
    // native menu is open must not schedule a repaint that wipes the snapshot.
    this._cursor = null;
    this._cursorPane = null;
    try {
      const g = pane.top.ctx;
      g.save();
      g.globalCompositeOperation = 'destination-over';
      g.drawImage(pane.base.element, 0, 0);
      g.restore();
      this._overlayFrozen = true;
    } catch { /* zero-sized or detached canvas: nothing to snapshot */ }
  }

  /** Build the `contextmenu` payload: where the pointer is, and what it is over. */
  private _contextMenuEvent(
    e: MouseEvent,
    p: { x: number; y: number; pane: number; localY: number; paneHeight: number },
  ): ContextMenuEvent {
    const plotX = p.x - this._host._leftAxisWidth;
    const onPlot = plotX >= 0 && p.x < this._host._width - this._host._rightAxisWidth;
    const index = onPlot ? Math.round(this._host._timeScale.xToIndex(plotX)) : null;
    if (onPlot) this._host._ensureScaled(p.pane); // a menu can be raised before the first paint
    return {
      paneIndex: p.pane,
      point: { x: p.x, y: p.y },
      price: onPlot ? this._priceAt(p.pane, p.localY) : null,
      time: index === null ? null : (this._host._dataLayer.indexToTime(index) ?? null),
      index,
      target: this._contextTarget(p, onPlot, index),
      preventDefault: (): void => e.preventDefault(),
    };
  }

  /**
   * Classify what the pointer is over. A canvas hands an app a pixel, not an
   * object, so this is the part it cannot work out for itself, and the part
   * that decides which menu items make sense.
   */
  private _contextTarget(
    p: { x: number; pane: number; localY: number; paneHeight: number },
    onPlot: boolean,
    index: number | null,
  ): ContextMenuTarget {
    const isBottom = p.pane === this._host._bottomPaneIndex();
    const onRightAxis = p.x >= this._host._width - this._host._rightAxisWidth;
    const onTimeAxis = isBottom && p.localY >= p.paneHeight - this._host._timeAxisHeight;
    // The time axis spans the full width, including the left column: a click in
    // the bottom-left corner is on the dates, not on a price ladder that stops
    // above them. The bottom-*right* corner stays the price axis', which is
    // where its own labels run out.
    if (onTimeAxis && !onRightAxis) return { kind: 'time-scale', id: null };
    if (!onPlot) {
      const slot = this._axisAt(p.pane, p.x);
      return slot ? { kind: 'price-scale', id: null, side: slot.side, scaleId: slot.scaleId } : { kind: 'empty', id: null };
    }

    const pane = this._host._panes[p.pane]!; // `_project` only names a pane that exists
    const context = this._host._renderContext(p.pane);
    const hit = this._hitAt(p.pane, p.x, p.localY);
    // A strip plots nothing, so nothing on it can be under the pointer.
    const record = index === null || this._host._layout._collapsedShown(p.pane) ? null : this._seriesAt(p.pane, index, p.localY);
    // What is painted on top takes the menu: a drawing placed under a source
    // or a study loses the pointer to that series where the two overlap.
    if (hit != null && !(record !== null && hit.paintedBy !== undefined && pane.paintsBelowSeries(hit.paintedBy, record, context))) {
      const id = hit.externalId;
      if (id.startsWith('draw:')) return { kind: 'drawing', id };
      if (id.startsWith('indicator:')) {
        const sep = id.lastIndexOf('::');
        const instanceId = id.slice('indicator:'.length, sep < 0 ? undefined : sep);
        return { kind: 'indicator', id, instanceId };
      }
      // A host-owned legend (the symbol/OHLC row) hit-tests as `${id}::row`.
      if (id.endsWith('::row')) return { kind: 'legend', id };
      return { kind: 'primitive', id };
    }
    if (record === null) return { kind: 'empty', id: null };
    for (const instance of this._host._indicators) {
      for (const plot of getIndicator(instance.indicatorId).plots) {
        const series = instance.series(plot.key);
        if (series && this._host._seriesRecords.get(series) === record) {
          return { kind: 'indicator', id: `indicator:${instance.id}`, instanceId: instance.id, plotKey: plot.key };
        }
      }
    }
    return { kind: 'series', id: null, seriesType: record.type };
  }

  /** Vacant aligned cells have no scale target, even if a hidden scale exists. */
  private _axisAt(paneIndex: number, x: number): PriceAxisSlot | undefined {
    return this._host.priceAxisLayout(paneIndex).find(slot => x >= slot.x && x < slot.x + slot.width);
  }

  /**
   * Which series the pointer sits on, if any. A pane is one bitmap, so "on the
   * candle" has to be recomputed rather than looked up: take each series'
   * autoscale extents for the bar under the cursor and test the band they span,
   * with a few px of slack so a 1px line is still a target.
   */
  private _seriesAt(paneIndex: number, index: number, localY: number): SeriesRecord | null {
    const pane = this._host._panes[paneIndex];
    if (pane === undefined) return null;
    const tol = 3;
    // Later series paint above earlier series, so their context actions win overlaps.
    const records = pane.series();
    for (let position = records.length - 1; position >= 0; position--) {
      const record = records[position]!; // walks the list from its end
      if (record.style.visible === false) continue;
      const bar = barAtIndex(this._host._dataLayer, record.dataId, index);
      if (bar === undefined) continue;
      const ext = getChartType(record.type).extents(bar, record.style);
      if (!isFinite(ext.min) || !isFinite(ext.max)) continue;
      const scale = pane.scaleOf(record);
      const a = scale.priceToY(ext.max);
      const b = scale.priceToY(ext.min);
      if (localY >= Math.min(a, b) - tol && localY <= Math.max(a, b) + tol) return record;
    }
    return null;
  }

  /**
   * The price under a pane-local y, for an event payload. Null on a strip: it
   * plots nothing, so a price read off it would place a drawing, an alert or a
   * pick somewhere nobody can see.
   */
  private _priceAt(paneIndex: number, y: number): number | null {
    return this._host._layout._collapsedShown(paneIndex) ? null : this._host._panes[paneIndex]?.yToPrice(y) ?? null;
  }

  /** Resume overlay repaints after the native context menu closes. */
  private _unfreezeOverlay(): void {
    if (!this._overlayFrozen) return;
    this._overlayFrozen = false;
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Cursor));
  }

  private _localPoint(e: { clientX: number; clientY: number }): { x: number; y: number; pane: number; localY: number; paneHeight: number } {
    const rect = this._host._container.getBoundingClientRect();
    return this._project(e.clientX - rect.left, e.clientY - rect.top, this._host._paneLayout());
  }

  /** Container media px to the pane under it and that pane's local y. */
  private _project(x: number, y: number, layout: { top: number; height: number }[]): { x: number; y: number; pane: number; localY: number; paneHeight: number } {
    // Map Y to a pane by cumulative weighted heights, matching the DOM/canvas layout.
    let pane = 0;
    for (let i = 0; i < layout.length; i++) if (y >= layout[i]!.top) pane = i;
    const pl = layout[pane] ?? { top: 0, height: this._host._height };
    return { x, y, pane, localY: y - pl.top, paneHeight: pl.height };
  }

  /**
   * Every position a drag passed through since the previous move event, in
   * the same space as the payload's `point`. The rect and layout are read once
   * for the batch: a fast stroke coalesces several positions per frame, and
   * each one going back to the DOM is layout work on the pointer path.
   */
  private _dragSamples(e: PointerEvent): PointerSample[] {
    const coalesced = typeof e.getCoalescedEvents === 'function' ? e.getCoalescedEvents() : [];
    const events: readonly PointerEvent[] = coalesced.length > 0 ? coalesced : [e];
    const rect = this._host._container.getBoundingClientRect();
    const layout = this._host._paneLayout();
    const out: PointerSample[] = [];
    for (const s of events) {
      const p = this._project(s.clientX - rect.left, s.clientY - rect.top, layout);
      out.push({ x: p.x, y: this._dragId === null ? p.localY : p.y - (layout[this._downPane]?.top ?? 0), pressure: pointerPressure(s) });
    }
    return out;
  }

  /**
   * Pointer facts for a click. Modifiers and device come from the release,
   * pressure from the press: a release always reads 0, which would leave the
   * field carrying nothing on any device.
   */
  private _clickInfo(e: PointerLike): PointerInfo & { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean } {
    const info = pointerInfo(e);
    info.pressure = this._downPressure;
    // The flat flags predate `modifiers` and are deprecated, removed in 3.0.0;
    // they stay until then so a host typed against either keeps working.
    return { ...info, shiftKey: info.modifiers.shift, ctrlKey: info.modifiers.ctrl, metaKey: info.modifiers.meta };
  }

  public _onPointerDown(e: PointerEvent): void {
    this._unfreezeOverlay();
    // Only the primary button starts a pan / line-drag. A right-click (context
    // menu) also fires pointerdown, and its pointerup is often swallowed by the
    // menu: arming the drag state then makes the chart pan with no button held.
    if ((e.pointerType === 'mouse' || e.pointerType === 'pen') && e.button !== 0) return;
    this._previousPressOnIndicatorToggle = this._lastPressOnIndicatorToggle;
    this._lastPressOnIndicatorToggle = false;
    this._endedPointers.delete(e.pointerId);
    if (this._pointers.size === 0) this._navigationCancelled = false;
    this._host._motion._stopKinetic();
    // Taking hold of the chart ends a zoom glide too: the viewport is the
    // user's again the moment they touch it.
    this._host._motion._stopZoomGlide();
    const p = this._localPoint(e);
    this._pointers.set(e.pointerId, { x: p.x, y: p.y, pane: p.pane });
    // `setPointerCapture` throws NotFoundError when the pointer id is not
    // currently active (a synthetic event, or one already released). The
    // optional call only guarded against the method being absent, so the throw
    // aborted the rest of pointerdown, losing the divider grab, the axis-drag
    // arm, and the line-drag arm. Capture is an optimisation; never fatal.
    try { this._host._container.setPointerCapture?.(e.pointerId); } catch { /* not capturable */ }
    if (this._navigationCancelled) return;
    if (this._pointers.size >= 2) { this._beginPinch(); return; } // second finger: pinch, skip single-drag
    this._downPane = p.pane;
    this._downX = p.x;
    this._downLocalY = p.localY;
    this._downPressure = pointerPressure(e);

    // Pane divider: pressing within a few px of the boundary between two panes
    // starts a resize, redistributing weight between them.
    const divider = this._host._layout._dividerAt(p.y);
    if (divider !== null) { this._beginDividerResize(divider, p); return; }

    // Axis-drag rescale: dragging the price axis (right strip) rescales Y;
    // dragging the time axis (bottom strip of the last pane) rescales X.
    const plotWidth = Math.max(0, this._host._width - this._host._rightAxisWidth);
    // Either strip rescales the axis drawn in it: a pane whose scale was moved
    // to the left has no right ladder to grab, and before the move the left one
    // was drawn but not draggable.
    const onLeftAxis = this._host._leftAxisWidth > 0 && p.x < this._host._leftAxisWidth;
    const onPriceAxis = p.x >= plotWidth || onLeftAxis;
    const onTimeAxis = p.pane === this._host._bottomPaneIndex() && p.localY >= p.paneHeight - this._host._timeAxisHeight;
    if (onPriceAxis) { this._beginPriceAxisDrag(p); return; }
    if (onTimeAxis) {
      if (this._host._navigation.zoomEnabled === false) { this._axisDrag = 'empty'; return; }
      this._axisDrag = 'time';
      this._axisStartCoord = p.x;
      this._axisStartSpacing = this._host._timeScale.barSpacing;
      this._dragging = false;
      return;
    }

    if (this._host._legendStack._indicatorLegendHit(p.pane, p.x, p.localY)) {
      this._lastPressOnIndicatorToggle = true;
      this._indicatorTogglePress = { pointerId: e.pointerId, moved: false };
      this._dragging = false;
      this._pointerMoved = false;
      return;
    }

    // The mark takes the press only where nothing else answers it: see `_hitAt`.
    const hit = this._host._panes[p.pane]?.hitTestPrimitives(p.x - this._host._leftAxisWidth, p.localY, this._host._renderContext(p.pane), this._host._branding);
    if (this._host._branding !== null && !hit && this._brandingHit(p.pane, p.x, p.localY)) {
      this._brandingPress = { pointerId: e.pointerId, mark: this._host._branding, moved: false };
      this._dragging = false;
      this._pointerMoved = false;
      return;
    }

    // While a host is placing something (a drawing tool is armed), a press is the
    // start of a shape, not a pan. Bail before the drag/hit paths so the gesture
    // can only produce anchors: `_onPointerUp` turns it into clicks.
    if (this._placementMode) {
      this._dragging = false;
      this._pointerMoved = false;
      return;
    }

    // If the press lands on a draggable line (order/SL/TP), drag it, don't pan.
    // `draggable` primitives (drawing anchors/shapes) arm regardless of a host
    // callback: they publish through the `drag` event bus. The `ns-resize`
    // form is the original price-line path and still needs `subscribeDrag`.
    if (hit && (hit.draggable === true || (hit.cursor === 'ns-resize' && this._dragCbs.size > 0))) {
      this._beginPrimitiveDrag(e, p, hit);
      return;
    }

    this._dragging = this._host._navigation.panEnabled !== false;
    // Hover-only controls must survive a repaint between press and release.
    this._setHover(hit ?? null);
    this._pointerMoved = false;
    this._dragStartX = p.x;
    this._dragStartY = p.y;
    this._lastDragY = p.y;
    this._dragStartOffset = this._host._timeScale.rightOffset;
    this._host._lastDragX = p.x;
    this._host._lastDragT = this._host._now();
    this._host._dragVelocity = 0;
  }

  public _onPointerMove(e: PointerEvent): void {
    this._unfreezeOverlay();
    // A move here is the pointer over the chart. Not every engine sends a
    // pointerenter to a container put back under a pointer that entered it
    // before it was parked, and the hover was forgotten while it was away.
    this._pointerInside = true;
    // Hover from a second device must not move or release the pointer that owns the gesture.
    if (this._pointers.size > 0 && !this._pointers.has(e.pointerId)) return;
    // Safety: if the primary button is no longer held (missed pointerup, e.g.
    // released over a context menu or outside the window), end any drag now.
    if ((e.pointerType === 'mouse' || e.pointerType === 'pen') && (e.buttons & 1) === 0
      && (this._pointers.has(e.pointerId) || this._dragging || this._dragId !== null || this._axisDrag !== null || this._brandingPress !== null || this._indicatorTogglePress !== null)) {
      if (this._brandingPress !== null) this._brandingPress.moved = true;
      if (this._indicatorTogglePress !== null) this._indicatorTogglePress.moved = true;
      this._host._onPointerUp(e);
      // Marked after the fact, not before: the recovery IS this pointer's one
      // real end, so it has to run. What must be swallowed is the release that
      // follows it.
      this._endedPointers.add(e.pointerId);
      return;
    }
    const p = this._localPoint(e);
    if (this._pointers.has(e.pointerId)) this._pointers.set(e.pointerId, { x: p.x, y: p.y, pane: p.pane });
    if (this._navigationCancelled) return;
    if (this._pinch !== null) { this._updatePinch(); return; }
    if (this._axisDrag === 'empty') return;
    if (this._indicatorTogglePress !== null) {
      if (this._movedFromPress(p.x, p.localY) || p.pane !== this._downPane) {
        this._indicatorTogglePress.moved = true;
      }
      return;
    }
    if (this._brandingPress !== null) {
      if (this._movedFromPress(p.x, p.localY)
        || p.pane !== this._downPane || (e.pointerType === 'mouse' && (e.buttons & 1) === 0)) {
        this._brandingPress.moved = true;
      }
      return;
    }
    if (this._axisDrag === 'price') {
      // drag up (dy<0) expands (zoom in); drag down compresses (zoom out)
      const dy = p.localY - this._axisStartCoord;
      const factor = Math.exp(dy * 0.005);
      const centre = (this._axisStartMin + this._axisStartMax) / 2;
      const half = ((this._axisStartMax - this._axisStartMin) / 2) * factor;
      const ps = this._axisDragScale ?? this._host._panes[this._downPane]!.priceScale; // the pane the press landed on
      ps.setPriceRange({ min: centre - half, max: centre + half });
      ps.setAutoScale(false);
      this._host.invalidate((m) => m.invalidatePane(this._downPane, { level: InvalidationLevel.Light, autoScale: false }));
      return;
    }
    if (this._paneResize !== null) {
      const r = this._paneResize;
      // Move `dy` px of height from one pane to the other, keeping their summed
      // weight constant so the other panes are untouched. Clamped so neither
      // side collapses below a usable height.
      const total = r.aHeight + r.bHeight;
      const sum = r.aWeight + r.bWeight;
      const min = Math.min(24, total / 4);
      const aH = Math.max(min, Math.min(total - min, r.aHeight + (p.y - r.startY)));
      this._host._panes[r.a]!.weight = (aH / total) * sum; // the two panes the press found at the divider
      this._host._panes[r.b]!.weight = sum - this._host._panes[r.a]!.weight;
      this._host._layout._relayout();
      this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
      return;
    }
    if (this._axisDrag === 'time') {
      this._host._motion._beginAutoscaleMotion();
      // Drag left to widen bars; drag right to show more bars in the same space.
      const dx = p.x - this._axisStartCoord;
      this._host._mutateTimeScale(() => this._host._timeScale.setBarSpacing(this._axisStartSpacing * Math.exp(-dx * 0.005)));
      this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
      this._host._emitViewport('zoom');
      return;
    }
    // Placement mode suppresses the pan path, which is where `_pointerMoved`
    // is normally set. Track the gesture here so pointerup can still tell a
    // click from a drag-to-draw.
    if ((this._placementMode || !this._dragging) && this._pointers.size > 0
      && this._movedFromPress(p.x, p.localY)) {
      this._pointerMoved = true;
    }
    if (this._dragId !== null) { this._movePrimitiveDrag(e, p); return; }
    if (this._dragging) { this._movePan(e, p); return; }
    this._updateCursor(p.pane, p.x, p.localY, p.y, e);
  }

  public _onPointerUp(e: PointerEvent): void {
    if (this._pointers.size > 0 && !this._pointers.has(e.pointerId)) return;
    const togglePress = this._indicatorTogglePress?.pointerId === e.pointerId ? this._indicatorTogglePress : null;
    if (togglePress) this._indicatorTogglePress = null;
    // Finish ownership before release: a host can report lost capture synchronously.
    this._pointers.delete(e.pointerId);
    try { this._host._container.releasePointerCapture?.(e.pointerId); } catch { /* already released */ }
    // A gesture ends once. `_onPointerMove` calls this directly when it finds the
    // button already released, because a release over a context menu or outside
    // the window never reaches us -- and the real `pointerup` still arrives after
    // it. Without this guard that second call finds the drag already torn down,
    // falls through to the plain click branch, and fires the same click again at
    // the stale press coordinates. Every host control addressed by
    // `subscribeClick` doubles: a legend's hide toggles twice and looks dead.
    if (this._endedPointers.has(e.pointerId)) { this._endedPointers.delete(e.pointerId); return; }
    if (this._navigationCancelled) {
      if (this._pointers.size === 0) this._navigationCancelled = false;
      this._endedPointers.add(e.pointerId);
      return;
    }
    if (togglePress) {
      const p = this._localPoint(e);
      this._endedPointers.add(e.pointerId);
      if (!togglePress.moved && p.pane === this._downPane && Math.abs(p.x - this._downX) <= CLICK_SLOP_PX
        && Math.abs(p.localY - this._downLocalY) <= CLICK_SLOP_PX && this._host._legendStack._indicatorLegendHit(p.pane, p.x, p.localY)) {
        this._host._handleLegendAction(INDICATOR_LEGEND_TOGGLE);
      }
      return;
    }
    if (this._brandingPress?.pointerId === e.pointerId) {
      const press = this._brandingPress;
      this._brandingPress = null;
      const p = this._localPoint(e);
      if (!press.moved && press.mark === this._host._branding && p.pane === this._downPane
        && Math.abs(p.x - this._downX) <= CLICK_SLOP_PX && Math.abs(p.localY - this._downLocalY) <= CLICK_SLOP_PX
        && this._brandingHit(p.pane, p.x, p.localY)) {
        const href = press.mark.href();
        if (href && /^https?:\/\//i.test(href)) this._host._doc.defaultView?.open(href, '_blank', 'noopener,noreferrer');
      }
      this._endedPointers.add(e.pointerId);
      return;
    }
    if (this._pinch !== null) {
      // Keep the remaining finger in the same gesture so its release cannot place a drawing.
      if (this._pointers.size === 0) { this._pinch = null; this._dragging = false; }
      return;
    }
    if (this._paneResize !== null) {
      this._paneResize = null;
      this._host._emit('paneResized', { paneIndex: this._downPane });
      return;
    }
    if (this._axisDrag !== null) {
      this._axisDrag = null;
      this._axisDragScale = null;
      return;
    }
    if (this._dragId !== null) { this._endPrimitiveDrag(e); return; }
    const wasPanning = this._dragging;
    this._dragging = false;
    // Placement mode: a press-drag-release is how every charting UI draws a
    // two-point shape, but the click branch below is gated on the pointer having
    // stayed still, so the gesture used to place nothing at all. Replay it as the
    // two clicks it means: press point, then release point. `viaDrag` lets the
    // host ignore the second one for single-anchor tools it already completed.
    if (this._placementMode && this._pointerMoved) { this._endPlacement(e, wasPanning); return; }
    // Always hit-test a clean click: the chart's own chrome (pane-legend
    // buttons) must work whether or not the host subscribed to clicks.
    if (!this._pointerMoved) { this._endClick(e, wasPanning); return; }
    if (wasPanning) this._setHover(null);
    // A mouse or pen release places the viewport precisely; only a touch flick coasts.
    if (wasPanning && this._host._navigation.panEnabled !== false && e.pointerType === 'touch' && e.type !== 'pointercancel'
      && KineticAnimation.shouldAnimate(this._host._dragVelocity)) this._host._startKinetic(this._host._dragVelocity);
  }

  /** Whether the pointer at (x, pane y) has left the press by more than the click slop. */
  private _movedFromPress(x: number, localY: number): boolean {
    return Math.abs(x - this._downX) > CLICK_SLOP_PX || Math.abs(localY - this._downLocalY) > CLICK_SLOP_PX;
  }

  /** A press on a pane divider: start moving weight between the two panes. */
  private _beginDividerResize(divider: readonly [number, number], p: LocalPoint): void {
    const layout = this._host._paneLayout();
    const [a, b] = divider;
    this._paneResize = {
      a, b,
      startY: p.y,
      // `_dividerAt` names two panes that exist, and the layout has a box for each.
      aWeight: this._host._panes[a]!.weight,
      bWeight: this._host._panes[b]!.weight,
      aHeight: layout[a]!.height,
      bHeight: layout[b]!.height,
    };
    this._dragging = false;
  }

  /** A press on a price axis strip: arm a rescale of the scale drawn in it. */
  private _beginPriceAxisDrag(p: LocalPoint): void {
    const slot = this._axisAt(p.pane, p.x);
    this._dragging = false;
    if (!slot || this._host._navigation.zoomEnabled === false) { this._axisDrag = 'empty'; return; }
    this._axisDrag = 'price';
    this._axisDragScale = this._host._panes[p.pane]!.scaleFor(slot.scaleId); // a projected point is on a pane
    this._axisStartCoord = p.localY;
    const r = this._axisDragScale.priceRange();
    this._axisStartMin = r.min;
    this._axisStartMax = r.max;
    this._dragging = false;
  }

  /** A press on a draggable primitive: arm its drag instead of a pan. */
  private _beginPrimitiveDrag(e: PointerEvent, p: LocalPoint, hit: PrimitiveHit): void {
    this._dragId = hit.externalId;
    this._dragPriceScale = hit.priceScale ?? null;
    this._dragCancelOnEscape = hit.cancelOnEscape === true;
    this._dragMoved = false;
    this._host._ensureScaled(p.pane);
    this._dragFrom = {
      time: this._host._xToTime(p.x),
      price: this._dragPriceScale?.yToPrice(p.localY) ?? this._host._panes[p.pane]!.yToPrice(p.localY),
    };
    this._setHover(hit); // active state + cursor even when no hover preceded (touch)
    // Hide the crosshair while dragging a line: a frozen crosshair at the
    // grab point reads as a phantom second line (the axis tag tracks price).
    this._cursor = null;
    this._cursorPane = null;
    this._readoutTime = null;
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Cursor));
    this._dragging = false;
    this._pointerMoved = false;
    const start: ChartDragEndEvent = {
      id: hit.externalId, ...this._dragFrom, paneIndex: this._downPane,
      point: { x: p.x, y: p.localY }, ...pointerInfo(e),
    };
    this._host._emit('drag:start', start);
  }

  /** A move while a primitive is held (the caller checks `_dragId`): report the price and time under the pointer. */
  private _movePrimitiveDrag(e: PointerEvent, p: LocalPoint): void {
    const localY = p.y - (this._host._paneLayout()[this._downPane]?.top ?? 0);
    if (this._movedFromPress(p.x, localY)) this._dragMoved = true;
    const price = this._dragPriceScale?.yToPrice(localY) ?? this._host._panes[this._downPane]!.yToPrice(localY); // the press's pane
    const time = this._host._xToTime(p.x);
    dispatch(this._dragCbs, { end: false, id: this._dragId!, price, time });
    const drag: ChartDragEvent = {
      id: this._dragId!, price, time, paneIndex: this._downPane,
      // The grab origin, so a consumer's delta starts at the press instead of
      // the first move. Otherwise the shape lags the cursor by one event.
      fromPrice: this._dragFrom.price, fromTime: this._dragFrom.time,
      point: { x: p.x, y: localY },
      samples: this._dragSamples(e),
      ...pointerInfo(e),
    };
    this._host._emit('drag', drag);
  }

  /** A move while the plot is held: pan time, and price where the pointer and the scale allow. */
  private _movePan(e: PointerEvent, p: LocalPoint): void {
    this._host._motion._beginAutoscaleMotion();
    const dx = p.x - this._dragStartX;
    if (Math.abs(dx) > CLICK_SLOP_PX || Math.abs(p.y - this._dragStartY) > CLICK_SLOP_PX) this._pointerMoved = true;
    if (this._pointerMoved && this._hoverId !== null) this._setHover(null);
    // horizontal: scroll time
    this._host._mutateTimeScale(() => this._host._timeScale.setRightOffset(this._dragStartOffset - dx / this._host._timeScale.barSpacing));
    // Horizontal-only mode preserves autoscale when the pointer moves vertically.
    if (e.pointerType === 'touch' || this._host._navigation.mousePan === 'both') {
      // A strip's scale is not on screen, so a drag across it pans time only.
      const scale = this._host._layout._collapsedShown(this._downPane) ? undefined : this._host._panes[this._downPane]?.priceScale;
      const fromStart = p.y - this._dragStartY;
      // Minor mouse/pen drift must not turn an automatic axis into a frozen
      // manual range. Once vertical movement is intentional, include its full
      // distance from the press; already-manual axes retain fine adjustments.
      if (scale && (e.pointerType === 'touch' || !scale.autoScale || Math.abs(fromStart) > 3)) {
        scale.panByPixels(e.pointerType !== 'touch' && scale.autoScale ? fromStart : p.y - this._lastDragY);
      }
    }
    this._lastDragY = p.y;
    const t = this._host._now();
    const dt = t - this._host._lastDragT;
    if (dt > 0) {
      // Blend rather than replace, and let an idle gap wash the old value out.
      // Sampling only on pointermove means a drag that stops and holds keeps
      // whatever velocity its last moving frame had, so releasing after a
      // deliberate pause flings the chart as if it were still moving. Decay is
      // measured in elapsed time, so it works the same on a throttled feed.
      const instant = (p.x - this._host._lastDragX) / dt;
      const keep = Math.exp(-dt / KINETIC_VELOCITY_HALFLIFE_MS);
      this._host._dragVelocity = this._host._dragVelocity * keep + instant * (1 - keep);
    }
    this._host._lastDragX = p.x;
    this._host._lastDragT = t;
    this._host._maybeLoadHistory();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emitViewport('pan');
  }

  /** The release of a primitive drag (the caller checks `_dragId`), a click on it when it never moved. */
  private _endPrimitiveDrag(e: PointerEvent): void {
    const p = this._localPoint(e);
    const localY = p.y - (this._host._paneLayout()[this._downPane]?.top ?? 0);
    const price = this._dragPriceScale?.yToPrice(localY) ?? this._host._panes[this._downPane]!.yToPrice(localY); // the press's pane
    const time = this._host._xToTime(p.x);
    dispatch(this._dragCbs, { end: true, id: this._dragId!, price, time });
    const end: ChartDragEndEvent = {
      id: this._dragId!, price, time, paneIndex: this._downPane,
      point: { x: p.x, y: localY },
      ...pointerInfo(e),
    };
    this._host._emit('drag:end', end);
    // A press on a draggable primitive arms a drag, so this branch used to
    // swallow the release, and a plain click on a drawing never reached the
    // click path, leaving it unselectable. A gesture that never moved is a
    // click by any reasonable reading.
    if (!this._dragMoved) {
      const id = this._dragId!;
      dispatch(this._clickCbs, id);
      const click: ChartClickEvent = {
        id, price, time,
        paneIndex: this._downPane,
        point: { x: this._downX, y: this._downLocalY },
        ...this._clickInfo(e),
      };
      this._host._emit('click', click);
    }
    this._dragId = null;
    this._dragPriceScale = null;
    // Re-evaluate hover at the release point (mouse keeps hovering the line;
    // touch has no pointer any more) and drop the dragging visual state.
    const hit = e.pointerType === 'touch' ? null : this._hitAt(p.pane, p.x, p.localY);
    this._setHover(hit);
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Light));
  }

  /** A press-drag-release while placing: the two clicks it means. */
  private _endPlacement(e: PointerEvent, wasPanning: boolean): void {
    if (wasPanning) this._setHover(null);
    const p = this._localPoint(e);
    this._host._ensureScaled(this._downPane);
    const info = this._clickInfo(e);
    const press: ChartClickEvent = {
      id: null,
      price: this._priceAt(this._downPane, this._downLocalY),
      time: this._host._xToTime(this._downX),
      paneIndex: this._downPane,
      point: { x: this._downX, y: this._downLocalY },
      ...info,
    };
    this._host._emit('click', press);
    const release: ChartClickEvent = {
      id: null,
      price: this._priceAt(this._downPane, p.localY),
      time: this._host._xToTime(p.x),
      paneIndex: this._downPane,
      point: { x: p.x, y: p.localY },
      viaDrag: true,
      ...info,
    };
    this._host._emit('click', release);
  }

  /** A release that did not move: a click at the press point, on a hit or on the plot. */
  private _endClick(e: PointerEvent, wasPanning: boolean): void {
    const hit = this._hitAt(this._downPane, this._downX, this._downLocalY);
    if (wasPanning) this._setHover(e.pointerType === 'touch' ? null : hit ?? null);
    // Pane-legend buttons are the chart's own chrome: handle them here so
    // the host doesn't have to re-implement remove/hide/move/maximize.
    if (hit && this._host._handleLegendAction(hit.externalId)) return;
    if (hit) dispatch(this._clickCbs, hit.externalId);
    // The event carries position and fires on empty plot too, which is what a
    // tool that *places* something (a drawing, an alert) needs; `id` is null
    // there. `subscribeClick` stays hit-only for back-compat.
    this._host._ensureScaled(this._downPane);
    const click: ChartClickEvent = {
      id: hit?.externalId ?? null,
      price: this._priceAt(this._downPane, this._downLocalY),
      time: this._host._xToTime(this._downX),
      paneIndex: this._downPane,
      point: { x: this._downX, y: this._downLocalY },
      // Modifier flags ride along so the draw tier can make a shift or
      // ctrl click additive to the selection; the payload carries no event.
      ...this._clickInfo(e),
    };
    this._host._emit('click', click);
  }

  /**
   * DOM pointerup entry point. Mirrors the primary-button guard in
   * `_onPointerDown`: a right-click (or any non-primary mouse button) fires
   * pointerdown *and* pointerup, but `_onPointerDown` ignores it, so the
   * down state (`_downX`/`_downLocalY`/`_downPane`/`_pointerMoved`) is never
   * refreshed and still holds the *previous* left-click. Letting a non-primary
   * pointerup through would re-run the click branch against that stale position
   * and replay the last click (e.g. re-firing a Buy/Sell button, a phantom
   * order). Touch and pen tip contact use button 0. The internal
   * recovery call from `_onPointerMove` invokes `_onPointerUp` directly, so it
   * bypasses this filter and still ends a drag when a button release is missed.
   */
  public _onPointerUpNative(e: PointerEvent): void {
    if ((e.pointerType === 'mouse' || e.pointerType === 'pen') && e.button !== 0) return;
    this._host._onPointerUp(e);
  }

  public _onPointerCancel(e: PointerEvent): void {
    // Existing hosts still receive their end notification; transactional consumers
    // discard the draft first so cancellation can never become a saved edit.
    this._cancelPrimitiveDrag('pointercancel');
    if (this._pointers.has(e.pointerId)) this._pointerMoved = true;
    if (this._brandingPress?.pointerId === e.pointerId) this._brandingPress.moved = true;
    if (this._indicatorTogglePress?.pointerId === e.pointerId) this._indicatorTogglePress.moved = true;
    this._host._onPointerUp(e);
  }

  public _onLostPointerCapture(e: PointerEvent): void {
    if (this._indicatorTogglePress?.pointerId === e.pointerId) {
      this._indicatorTogglePress.moved = true;
      this._host._onPointerUp(e);
      return;
    }
    // Another element can take capture before release. Abandon the pan without a click or fling.
    if (!this._pointers.has(e.pointerId) || this._dragId !== null || this._paneResize !== null || this._brandingPress !== null) return;
    if (this._pinch !== null || this._navigationCancelled) {
      this._navigationCancelled = true;
      this._pinch = null;
    }
    this._dragging = false;
    this._axisDrag = null;
    this._axisDragScale = null;
    this._host._dragVelocity = 0;
    this._pointerMoved = true;
    this._pointers.delete(e.pointerId);
    if (this._pointers.size === 0) this._navigationCancelled = false;
    this._endedPointers.add(e.pointerId);
    this._setHover(null);
  }

  /** The corner mark's hit at a container x and pane y, whatever else is there. */
  private _brandingHit(paneIndex: number, x: number, y: number): PrimitiveHit | null {
    const pane = this._host._panes[paneIndex];
    if (this._host._branding === null || !pane?.hasPrimitive(this._host._branding)) return null;
    const isBottom = paneIndex === this._host._bottomPaneIndex();
    return this._host._branding.hitTest(x - this._host._leftAxisWidth, y, {
      timeScale: this._host._timeScale, priceScale: pane.priceScale, dataLayer: this._host._dataLayer,
      plotWidth: this._host._width - this._host._leftAxisWidth - this._host._rightAxisWidth,
      plotHeight: (this._host._paneLayout()[paneIndex]?.height ?? 0) - (isBottom ? this._host._timeAxisHeight : 0),
      priceAxisWidth: this._host._rightAxisWidth, dpr: this._host._pixelRatio(), theme: this._host._theme,
    });
  }

  /**
   * What the pointer is over on a pane, at a container x and pane y. The
   * corner mark comes last: a note pinned over it, or anything else there,
   * is what the user can see and means to grab, and the mark is only a link.
   */
  private _hitAt(paneIndex: number, x: number, y: number): PrimitiveHit | null {
    return this._host._panes[paneIndex]?.hitTestPrimitives(x - this._host._leftAxisWidth, y, this._host._renderContext(paneIndex), this._host._branding)
      ?? this._brandingHit(paneIndex, x, y);
  }

  public _onPointerLeave(): void {
    this._pointerInside = false;
    this._host._feedTimeNav(null);
    if (this._dragId === null) this._setHover(null); // keep the active state while dragging
    if (this._cursor !== null) {
      this._cursor = null;
      this._cursorPane = null;
      // clear the crosshair from every pane (global vertical line)
      this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Cursor));
      // Pointer left the plot: legends fall back to the latest bar.
      for (const indicator of this._host._indicators) indicator.updateLegendValues();
      const cleared = { time: null, index: null, price: null, bar: null, point: null, paneIndex: null };
      dispatch(this._crosshairCbs, cleared);
      this._host._emit('crosshair:readout', cleared);
      this._host._emit('crosshair:move', cleared);
    }
  }

  public _onWheel(e: WheelEvent): void {
    const delta = wheelPixels(e, this._host._width, this._host._height);
    if (delta.x === 0 && delta.y === 0) return;
    const p = this._localPoint(e);
    const onLeft = this._host._leftAxisWidth > 0 && p.x < this._host._leftAxisWidth;
    const onRight = this._host._rightAxisWidth > 0 && p.x >= this._host._width - this._host._rightAxisWidth;
    const horizontal = !onLeft && !onRight && !e.ctrlKey && !e.metaKey
      && (e.shiftKey || Math.abs(delta.x) > Math.abs(delta.y));
    if (horizontal ? this._host._navigation.panEnabled === false : this._host._navigation.zoomEnabled === false) return;
    if (!horizontal && delta.y === 0) return;
    this._unfreezeOverlay();
    e.preventDefault();
    this._host._motion._stopKinetic();
    if (onLeft || onRight) {
      if (delta.y === 0) return;
      const slot = this._axisAt(p.pane, p.x);
      if (!slot) return;
      this._host._motion._stopZoomGlide();
      const pane = this._host._panes[p.pane]!; // a projected point is on a pane
      const scale = pane.scaleFor(slot.scaleId);
      scale.scaleAtY(p.localY, Math.exp(-wheelLogFactor(delta.y)));
      this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
      return;
    }
    if (horizontal) {
      this._host._motion._stopZoomGlide();
      this._host._motion._beginAutoscaleMotion();
      this._host._mutateTimeScale(() => this._host._timeScale.scrollByPixels(-(e.shiftKey && delta.x === 0 ? delta.y : delta.x)));
      this._host._maybeLoadHistory();
      this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
      this._host._emitViewport('pan');
      return;
    }
    if (delta.y === 0) return;
    const focusX = this._host._zoomAnchor === 'right' && !e.ctrlKey && !e.metaKey
      ? this._host._timeScale.width : Math.max(0, Math.min(this._host._timeScale.width, p.x - this._host._leftAxisWidth));
    if (this._host._animZoom) {
      // Every step eases, a trackpad's smallest included: applied at once, a
      // stream of tiny steps tracked the raw event jitter.
      this._host._motion._retargetZoom(focusX, wheelLogFactor(delta.y));
      return;
    }
    // Carry the unpainted distance across a switch to instant zoom, and bound
    // the step now so input at a limit cannot accumulate invisible debt.
    const remaining = this._host._motion._remainingZoom();
    const spacing = this._host._timeScale.barSpacing;
    const target = this._host._timeScale.constrainBarSpacing(spacing * Math.exp(remaining + wheelLogFactor(delta.y)));
    this._host._motion._stopZoomGlide();
    const logFactor = Math.log(target / spacing);
    if (logFactor !== 0) this._host._motion._applyZoom(focusX, logFactor);
  }

  public _onDblClick(e: { clientX: number; clientY: number }): void {
    // A count-control press cannot participate in a chart double click. The
    // browser counts clicks on the canvas even when the first collapsed a row;
    // two later plot or axis presses retain the normal double-click action.
    if (this._lastPressOnIndicatorToggle || this._previousPressOnIndicatorToggle) return;
    const p = this._localPoint(e);
    if (this._host._legendStack._indicatorLegendHit(p.pane, p.x, p.localY)) return;
    // The mark's own double click does nothing; one on a drawing over it is the drawing's.
    if (this._brandingHit(p.pane, p.x, p.localY)
      && !this._host._panes[p.pane]?.hitTestPrimitives(p.x - this._host._leftAxisWidth, p.localY, this._host._renderContext(p.pane), this._host._branding)) return;
    const ev: DoubleClickEvent = { paneIndex: p.pane, x: p.x, y: p.y, handled: false };
    this._host._emit('dblclick', ev);
    // While a tool is armed a double-click means "finish this shape" (a
    // variable-anchor tool has no other way to end), so it must not also throw
    // the view back to its default mid-placement. A listener that took the
    // press for itself has said so on the event.
    if (this._placementMode || ev.handled) return;
    if (this._host._doubleClick === 'reset' && this._host._navigation.zoomEnabled !== false) this._host.resetScale();
    else if (this._host._doubleClick === 'maximize') this._host.maximizePane(p.pane);
  }

  // ── multi-touch pinch (zoom + two-finger pan) ─────────────────────────────
  private _beginPinch(): void {
    this._cancelPrimitiveDrag('pinch');
    this._brandingPress = null;
    this._indicatorTogglePress = null;
    const pts = [...this._pointers.values()]; // a second pointer down is what begins a pinch
    this._pinch = pinchState(pts[0]!, pts[1]!);
    this._pinchPane = pts[0]!.pane;
    // abort any single-pointer interaction so it doesn't fight the pinch
    this._dragging = false; this._axisDrag = null; this._axisDragScale = null; this._dragId = null; this._pointerMoved = true;
    this._dragPriceScale = null;
    this._setHover(null);
  }

  private _updatePinch(): void {
    const pts = [...this._pointers.values()];
    if (pts.length < 2 || this._pinch === null) return;
    const cur = pinchState(pts[0]!, pts[1]!);
    const d = pinchDelta(this._pinch, cur);
    this._pinch = cur;
    const zoom = this._host._navigation.zoomEnabled !== false && d.factor !== 1;
    const pan = this._host._navigation.panEnabled !== false && (d.dx !== 0 || d.dy !== 0);
    if (!zoom && !pan) return;
    this._host._motion._beginAutoscaleMotion();
    this._host._mutateTimeScale(() => {
      if (zoom) this._host._timeScale.zoomAtX(cur.cx, d.factor);
      if (pan) this._host._timeScale.setRightOffset(this._host._timeScale.rightOffset - d.dx / this._host._timeScale.barSpacing);
    });
    if (pan && d.dy !== 0 && !this._host._layout._collapsedShown(this._pinchPane)) this._host._panes[this._pinchPane]?.priceScale.panByPixels(d.dy);
    this._host._maybeLoadHistory();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emitViewport(zoom ? 'zoom' : 'pan');
  }

  // ── keyboard navigation (focus the chart, then arrows / +- / Home) ────────
  private _cancelPrimitiveDrag(reason: 'pointercancel' | 'pinch' | 'escape'): void {
    if (this._dragId === null) return;
    this._dragMoved = true;
    this._host._emit('drag:cancel', { id: this._dragId, paneIndex: this._downPane, reason });
  }

  public _onKeyDown(e: KeyboardEvent): void {
    this._unfreezeOverlay();
    // Opt-in drafts own Escape without stranding legacy consumers that require a release.
    if (e.key === 'Escape' && this._dragCancelOnEscape && this._dragId !== null && !ShortcutManager.shouldIgnore(e.target)) {
      this._cancelPrimitiveDrag('escape');
      this._dragId = null;
      this._dragPriceScale = null;
      this._dragging = false;
      this._pointerMoved = true;
      for (const id of this._pointers.keys()) this._endedPointers.add(id);
      this._pointers.clear();
      this._setHover(null);
      this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Light));
      e.preventDefault();
      return;
    }
    const sc = this._host._shortcuts;
    if (sc === null || ShortcutManager.shouldIgnore(e.target) || !this._shortcutsActive()) return;
    const cmd = sc.resolve(e);
    if (cmd === null) return;
    if (!this._navigationAllowed(cmd)) return;
    let handled = this._runShortcut(cmd);
    if (!handled) handled = sc.runCustom(cmd);
    if (!handled) return;
    e.preventDefault();
    sc.emitTrigger(cmd);
    this._host._maybeLoadHistory();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._updateAccessibleSummary();
  }

  /**
   * Whether the pointer is over the chart, as far as its keys are concerned.
   * A container taken out of the document under a still pointer, as a
   * framework does when it parks a view it keeps alive, is sent no
   * pointerleave, so the chart would go on answering hover-scoped keys
   * typed at whatever replaced it. Once seen out of the document the hover
   * is forgotten, and the chart back in place waits for the pointer to come
   * in again rather than trusting where it last was.
   */
  private _hovered(): boolean {
    if (!this._pointerInside) return false;
    if (this._host._container.isConnected !== false) return true;
    this._pointerInside = false;
    return false;
  }

  /** Scope gating: hover keeps keys chart-local; global always acts. */
  private _shortcutsActive(): boolean {
    if (this._host._shortcuts === null) return false;
    if (this._host._shortcuts.scope === 'global' || this._hovered()) return true;
    const active = this._host._doc.activeElement as Node | null;
    return active !== null && (active === this._host._container || this._host._container.contains?.(active) === true);
  }

  /** Execute a built-in command; returns false for unknown (custom) commands. */
  public _runShortcut(command: string): boolean {
    if (!this._navigationAllowed(command)) return false;
    const ts = this._host._timeScale;
    // Keyboard navigation moves the same viewport a drag or a wheel does, so it
    // announces itself the same way: a chart linked into a grid must follow an
    // arrow key, not only a gesture. `panUp` / `panDown` move a price scale, not
    // the time window, and deliberately emit nothing (the payload is a time
    // range, and `_emitViewportIfMoved` sees no movement in it anyway).
    const pan = (bars: number): boolean => {
      this._host._motion._stopZoomGlide();
      this._host._motion._beginAutoscaleMotion();
      const before = ts.visibleRange();
      this._host._mutateTimeScale(() => ts.setRightOffset(ts.rightOffset + bars));
      this._host._emitViewportIfMoved(before);
      return true;
    };
    const zoom = (factor: number): boolean => {
      this._host._motion._stopZoomGlide();
      this._host._motion._beginAutoscaleMotion();
      const before = ts.visibleRange();
      this._host._mutateTimeScale(() => ts.zoomAtX(this._host._width / 2, factor));
      this._host._emitViewportIfMoved(before);
      return true;
    };
    switch (command) {
      case 'panLeftBar': return pan(-1);
      case 'panRightBar': return pan(1);
      case 'panLeft': return pan(-2);
      case 'panRight': return pan(2);
      case 'panLeftFast': return pan(-10);
      case 'panRightFast': return pan(10);
      case 'panUp': this._host._primaryPane.priceScale.panByPixels(20); return true;
      case 'panDown': this._host._primaryPane.priceScale.panByPixels(-20); return true;
      case 'zoomIn': return zoom(1.1);
      case 'zoomOut': return zoom(1 / 1.1);
      case 'resetScale': this._host.resetScale(); return true;
      case 'fitContent': this._host.fitContent(); return true;
      case 'screenshot': this._host.downloadScreenshot(); return true;
      case 'toggleGridVert': this._host.setGridOptions({ vertLines: !this._host._gridVert }); return true;
      case 'toggleGridHorz': this._host.setGridOptions({ horzLines: !this._host._gridHorz }); return true;
      // Through applyOptions, as the grid toggles go through setGridOptions: the
      // mode is saved state, so the change is announced like any other.
      case 'toggleCrosshairMagnet': this._host.applyOptions({ crosshairMode: this._host._crosshairMode === 'magnet' ? 'normal' : 'magnet' }); return true;
      default: return false;
    }
  }

  /**
   * Track the primitive under the pointer: apply its cursor hint to the
   * container and repaint on hover enter/leave so lines/pills can render
   * hover states (they read `hoverId` off the render context).
   */
  public _setHover(hit: PrimitiveHit | null): void {
    const id = hit?.externalId ?? null;
    const key = hit?.hoverKey ?? id;
    this._host._container.style.cursor = this._dragging && hit?.cursor !== 'pointer' ? 'grabbing' : hit?.cursor ?? '';
    if (id === this._hoverId && key === this._hoverKey) return;
    const changedId = id !== this._hoverId;
    // Hover-styled primitives on the base canvas need a light repaint, no
    // rescale. A change that touches only 'top' primitives (leaving a drawing
    // for another, or for empty space) is the overlay's alone: the pointer
    // moves sixty times a second, and repainting the series for a line it
    // merely passes over is a stutter.
    const onBase = hit !== null && hit.zOrder !== 'top';
    const level = onBase || this._hoverOnBase ? InvalidationLevel.Light : InvalidationLevel.Cursor;
    this._hoverId = id;
    this._hoverKey = key;
    this._hoverOnBase = onBase;
    this._host.invalidate((m) => m.invalidateGlobal(level));
    if (changedId) this._host._emit('hover', { id });
  }

  private _updateCursor(paneIndex: number, x: number, localY: number, containerY: number, source: PointerEvent): void {
    // Plot spans [leftAxisWidth, width - priceAxisWidth]; work in plot-relative x.
    const rightEdge = this._host._width - this._host._rightAxisWidth;
    const plotX = x - this._host._leftAxisWidth;
    const plotWidth = Math.max(0, rightEdge - this._host._leftAxisWidth);
    if (plotX < 0 || plotX > plotWidth) {
      this._host._onPointerLeave();
      return;
    }
    const pane = this._host._panes[paneIndex]!; // the pane the pointer was projected onto
    const hit = this._hitAt(paneIndex, x, localY);
    // A pane boundary beats a primitive hit: the divider is a thin target and
    // the legend rows sit right below one.
    if (hit === null && this._host._layout._dividerAt(containerY) !== null) {
      this._setHover(null);
      this._host._container.style.cursor = 'row-resize';
      return;
    }
    this._setHover(hit);
    // The navigator reveals on pointer position, not on hover id. See the note
    // in time-navigator.ts. Only the lowest open pane carries it.
    // The hover label occupies the same bottom strip as the navigation row.
    this._host._feedTimeNav(paneIndex === this._host._timeNavPane && !this._brandingHit(paneIndex, x, localY)
      ? { x: plotX, y: localY } : null);
    let y = localY;
    const index = Math.round(this._host._timeScale.xToIndex(plotX));
    let hoveredBar: Bar | null = null;
    if (this._host._firstDataId.value !== null) {
      const bar = barAtIndex(this._host._dataLayer, this._host._firstDataId.value, index);
      if (bar !== undefined) {
        hoveredBar = bar;
        // Magnet only snaps within the pane that holds the price series, never
        // in the volume/indicator panes (their scale isn't a price scale).
        if (this._host._crosshairMode === 'magnet' && paneIndex === this._host._layout._firstPaneSlot()) {
          const snapped = magnetSnapPrice(pane.yToPrice(localY), hoveredBar);
          y = pane.priceToY(snapped);
        }
      }
    }
    this._cursorPane = paneIndex;
    this._cursor = { x: plotX, y }; // plot-relative; the crosshair line is drawn inside the plot shift
    this._readoutTime = hoveredBar?.time ?? null;
    // Legend rows read the bar under the crosshair, like every charting package.
    for (const indicator of this._host._indicators) indicator.updateLegendValues(index);
    // global crosshair: repaint every pane's overlay (cheap; base untouched)
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Cursor));
    if (this._crosshairCbs.size > 0 || this._host._bus.has('crosshair:move') || this._host._bus.has('crosshair:readout')) {
      const time = this._host._dataLayer.indexToTime(index);
      const move: CrosshairMoveEvent = {
        time: time ?? null,
        index,
        price: this._priceAt(paneIndex, localY),
        bar: hoveredBar,
        point: { x, y: containerY },
        paneIndex,
        // Whether a pointer is down for this move. Placement mode swallows the
        // pan path, so this is the only way a consumer can tell a hover from a
        // drag while it is still happening: what freehand drawing samples.
        pressed: this._pointers.size > 0,
        ...pointerInfo(source),
        // Only while pressed: a hover has no trail worth carrying, and the key
        // set of the hover payload is what hosts and tests pin.
        ...(this._pointers.size > 0 ? { samples: this._dragSamples(source) } : {}),
      };
      dispatch(this._crosshairCbs, move);
      this._host._emit('crosshair:readout', move);
      this._host._emit('crosshair:move', move);
    }
  }

  /**
   * Apply a navigation preference patch. Turning panning or zooming off also
   * stops the motion and ends the gesture it would have carried on, so a
   * setting a host applies mid-drag holds from that moment.
   */
  public _patchNavigation(patch: Partial<ChartNavigationOptions>): void {
    const wasPan = this._host._navigation.panEnabled, wasZoom = this._host._navigation.zoomEnabled;
    for (const key of ['panEnabled', 'zoomEnabled'] as const) {
      const field = Object.getOwnPropertyDescriptor(patch, key);
      if (field && 'value' in field && typeof field.value === 'boolean') this._host._navigation[key] = field.value;
    }
    const stopPan = wasPan !== false && this._host._navigation.panEnabled === false;
    const stopZoom = wasZoom !== false && this._host._navigation.zoomEnabled === false;
    if (stopPan || stopZoom) {
      this._host._motion._stopDisabled(stopPan, stopZoom);
      if (this._pinch !== null || (stopPan && this._dragging)
        || (stopZoom && (this._axisDrag === 'price' || this._axisDrag === 'time'))) {
        this._navigationCancelled = true;
        this._dragging = false;
        this._axisDrag = null;
        this._axisDragScale = null;
        this._pinch = null;
        this._pointerMoved = true;
        this._host._dragVelocity = 0;
        this._setHover(null);
      }
    }
    if (wasPan !== this._host._navigation.panEnabled || wasZoom !== this._host._navigation.zoomEnabled) this._syncNavigatorPolicy();
    if (patch.mousePan === 'horizontal' || patch.mousePan === 'both') this._host._navigation.mousePan = patch.mousePan;
    const count = patch.defaultVisibleBars;
    // Saved layouts are untrusted input. Invalid values must not poison spacing.
    if (typeof count === 'number' && Number.isFinite(count) && count >= 0) {
      this._host._navigation.defaultVisibleBars = Math.min(100000, Math.floor(count));
      // An explicit count edit selects count mode. A complete saved preference
      // can carry both fields, in which case its spacing still takes precedence.
      if (patch.defaultBarSpacing === undefined) delete this._host._navigation.defaultBarSpacing;
    }
    const spacing = patch.defaultBarSpacing;
    if (typeof spacing === 'number' && Number.isFinite(spacing) && spacing >= 0) {
      if (spacing === 0) delete this._host._navigation.defaultBarSpacing;
      else this._host._navigation.defaultBarSpacing = spacing;
    }
  }

  /** Whether the navigation policy lets a shortcut or navigator command run. */
  public _navigationAllowed(command: string): boolean {
    switch (command) {
      case 'panLeftBar': case 'panRightBar': case 'panLeft': case 'panRight':
      case 'panLeftFast': case 'panRightFast': case 'panUp': case 'panDown':
        return this._host._navigation.panEnabled !== false;
      case 'zoomIn': case 'zoomOut': case 'resetScale': case 'fitContent':
        return this._host._navigation.zoomEnabled !== false;
      default: return true;
    }
  }

  /** Show only the navigator buttons the policy allows, closing the gap a withheld group leaves. */
  public _syncNavigatorPolicy(): void {
    if (this._host._timeNav === null) return;
    if (this._timeNavButtons.every(action => action === null || this._navigationAllowed(action))) {
      this._host._timeNav.setOptions({ buttons: [...this._timeNavButtons] });
      return;
    }
    const buttons: (TimeNavigatorOptions['buttons'][number])[] = [];
    let gap = false;
    for (const action of this._timeNavButtons) {
      if (action === null) { gap = true; continue; }
      if (!this._navigationAllowed(action)) continue;
      if (gap && buttons.length > 0) buttons.push(null);
      buttons.push(action);
      gap = false;
    }
    this._host._timeNav.setOptions({ buttons });
  }
}
