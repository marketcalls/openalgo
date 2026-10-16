/**
 * The drawing controller's layers on each pane: under the series, over it,
 * and one in the series band per entry a drawing is placed above; listing
 * every drawing on the layer of the slot it paints in, and the placement
 * preview and the magnet's ring on the top layer.
 *
 * Its own module because the layers and the bookkeeping of what they last
 * listed belong to these methods alone. The controller reaches it through
 * `DrawingController._layerSet`, and it reaches the controller through
 * `LayerSetHost`. Members the controller calls are public on this internal
 * class; the tier entry does not export it.
 */
import type { Drawing, DrawingPoint } from './types';
import type { DrawingController } from './controller';
import { DrawingLayer } from './layer';
import { GestureLayer } from './gesture-layer';

/**
 * The layers of one pane: under the series, over it, and one inside the
 * series band for each entry a drawing is placed above.
 */
interface PaneLayers {
  bottom: DrawingLayer;
  top: GestureLayer;
  series: Map<string, DrawingLayer>;
}

/**
 * The slot a drawing paints in: `entry:<id>` while the entry it is placed
 * above is in its pane's series band, else its side of the series by `zIndex`.
 */
export function slotOf(d: Drawing, entries: readonly string[]): string {
  return d.stackAbove !== undefined && entries.includes(d.stackAbove) ? 'entry:' + d.stackAbove : d.zIndex < 0 ? 'below' : 'above';
}

/**
 * The slice of the controller the layers read, typed from the controller's
 * own members as `HistoryHost` is.
 */
export interface LayerSetHost {
  readonly _chart: DrawingController['_chart'];
  readonly _opts: DrawingController['_opts'];
  readonly _drawings: DrawingController['_drawings'];
  readonly _selection: DrawingController['_selection'];
  readonly _hovered: DrawingController['_hovered'];
  readonly _linkedPreviews: DrawingController['_linkedPreviews'];
  readonly _pointerKind: DrawingController['_pointerKind'];
  readonly _gestures: DrawingController['_gestures'];
  readonly _drag: DrawingController['_drag'];
  readonly _tool: DrawingController['_tool'];
  readonly _pending: DrawingController['_pending'];
  readonly _pendingPane: DrawingController['_pendingPane'];
  readonly _lastCursor: DrawingController['_lastCursor'];
  _entries: DrawingController['_entries'];
  _shownFilter: DrawingController['_shownFilter'];
  _aimPoint: DrawingController['_aimPoint'];
  _isFreehand: DrawingController['_isFreehand'];
  _lockedPoint: DrawingController['_lockedPoint'];
  _snapPoint: DrawingController['_snapPoint'];
}

export class PaneLayerSet {
  private readonly _host: LayerSetHost;
  public readonly _layers = new Map<number, PaneLayers>();
  /** Drawings an eraser drag has touched: still in the model, left unpainted until it lets go. */
  public _hidden: ReadonlySet<string> = new Set();
  /** The slots the series-band drawings were last listed in; see `_slotSignature`. */
  public _slotKey = '';
  /** The drawings the chart's interval hid when the layers were last listed; see `_followInterval`. */
  public _offInterval = '';

  public constructor(host: LayerSetHost) {
    this._host = host;
  }

  /** Every layer of every pane. */
  public _allLayers(): DrawingLayer[] {
    return [...this._layers.values()].flatMap(l => [l.bottom, l.top, ...l.series.values()]);
  }

  /**
   * The pair of layers for a pane, made on first use. The bottom one is added
   * first so a host that lists primitives sees them in paint order; the top one
   * adopts it so handles and hit-tests come from one place.
   */
  public _layerFor(paneIndex: number): PaneLayers {
    let pair = this._layers.get(paneIndex);
    if (pair === undefined) {
      pair = { bottom: new DrawingLayer('bottom'), top: new GestureLayer(), series: new Map() };
      this._host._chart.addPrimitive(pair.bottom, paneIndex);
      this._host._chart.addPrimitive(pair.top, paneIndex);
      pair.top.setBelow(pair.bottom);
      pair.bottom.setSelected(this._host._selection);
      pair.top.setSelected(this._host._selection);
      this._layers.set(paneIndex, pair);
    }
    return pair;
  }

  /**
   * Whether a drawing paints on the top layer: over the series and outside
   * the series band, or lifted for a drag.
   */
  public _onTop(d: Drawing, entries = this._host._entries(d.paneIndex)): boolean {
    return this._host._drag._lifted.has(d.id) || slotOf(d, entries) === 'above';
  }

  /** Each drawing placed in the series band, with the slot it resolves to now. */
  public _slotSignature(): string {
    const stacks = new Map<number, readonly string[]>();
    let key = '';
    for (const d of this._host._drawings) {
      if (d.stackAbove === undefined) continue;
      let entries = stacks.get(d.paneIndex);
      if (entries === undefined) stacks.set(d.paneIndex, entries = this._host._entries(d.paneIndex));
      key += d.id + '\u0000' + slotOf(d, entries) + '\u0000';
    }
    return key;
  }

  /** List every drawing on the layer of the slot it paints in. */
  public _syncLayers(): void {
    this._slotKey = this._slotSignature();
    const byPane = new Map<number, { below: Drawing[]; above: Drawing[]; series: Map<string, Drawing[]> }>();
    const stacks = new Map<number, readonly string[]>();
    const shown = this._host._shownFilter();
    const off: string[] = [];
    for (const committed of this._host._drawings) {
      if (!shown(committed)) { off.push(committed.id); continue; }
      if (this._hidden.has(committed.id)) continue;
      const d = this._host._linkedPreviews.get(committed.id) ?? committed;
      let lists = byPane.get(d.paneIndex);
      if (lists === undefined) {
        lists = { below: [], above: [], series: new Map() };
        byPane.set(d.paneIndex, lists);
      }
      let entries = stacks.get(d.paneIndex);
      if (entries === undefined) stacks.set(d.paneIndex, entries = this._host._entries(d.paneIndex));
      const slot = this._host._drag._lifted.has(d.id) ? 'above' : slotOf(d, entries);
      if (slot === 'above') lists.above.push(d);
      else if (slot === 'below') lists.below.push(d);
      else {
        const list = lists.series.get(slot.slice('entry:'.length));
        if (list) list.push(d); else lists.series.set(slot.slice('entry:'.length), [d]);
      }
    }
    for (const [pane, lists] of byPane) {
      const l = this._layerFor(pane);
      l.bottom.setDrawings(lists.below);
      l.top.setDrawings(lists.above);
      this._syncSeriesLayers(pane, l, lists.series, stacks.get(pane) ?? []);
    }
    // Panes that lost their last drawing must be cleared, not left stale.
    for (const [pane, l] of this._layers) {
      if (!byPane.has(pane)) {
        l.bottom.setDrawings([]);
        l.top.setDrawings([]);
        this._syncSeriesLayers(pane, l, new Map(), []);
      }
      for (const layer of [l.bottom, l.top, ...l.series.values()]) layer.setSelected(this._host._selection);
    }
    this._offInterval = off.join('\u0000');
  }

  /**
   * One series-band layer per entry a drawing on this pane is placed above,
   * made on first use and dropped when its last drawing leaves, each painted
   * by the chart right after its entry. The top layer answers for them,
   * front to back, then for the layer under the series.
   */
  private _syncSeriesLayers(pane: number, l: PaneLayers, groups: ReadonlyMap<string, Drawing[]>, entries: readonly string[]): void {
    for (const [entry, layer] of l.series) {
      if (groups.has(entry)) continue;
      l.series.delete(entry);
      this._host._chart.removePrimitive(layer);
    }
    for (const [entry, list] of groups) {
      let layer = l.series.get(entry);
      if (layer === undefined) {
        layer = new DrawingLayer('series');
        this._host._chart.addPrimitive(layer, pane);
        this._host._chart.setPrimitiveStackAbove?.(layer, entry);
        layer.setPointerType(this._host._pointerKind);
        layer.setHovered(this._host._hovered);
        l.series.set(entry, layer);
      }
      layer.setDrawings(list);
    }
    l.top.setBelow([...entries].reverse().flatMap(entry => l.series.get(entry) ?? []).concat(l.bottom));
  }

  /**
   * Mirror the in-progress anchors (plus the cursor) into the preview slot.
   * The cursor point goes through the same aim as a click would, so the
   * preview shows the locked angle or the snapped anchor before it lands.
   */
  public _syncPreview(): void {
    for (const l of this._layers.values()) l.top.setPreview(null);
    const ruler = this._host._gestures.ruler();
    if (ruler !== null) this._layerFor(ruler.paneIndex).top.setPreview(ruler);
    if (this._host._tool === null || this._host._pending.length === 0) return;
    const cursor = this._host._lastCursor;
    const points = cursor === null || cursor.paneIndex !== this._host._pendingPane
      ? this._host._pending
      : [...this._host._pending, this._host._aimPoint({ time: cursor.time, price: cursor.price }, cursor.paneIndex)];
    this._layerFor(this._host._pendingPane).top.setPreview({
      id: '__preview', tool: this._host._tool, points, style: this._host._opts.defaultStyle,
      paneIndex: this._host._pendingPane, zIndex: 0,
    });
  }

  /**
   * Show where the magnet will land the next click, or nothing. A ring only
   * while a click would place an anchor: a tool armed, not a brush (which
   * inks where the pointer is), and the pull actually applying at the cursor.
   * Angle lock bypasses the magnet, so it hides the ring too.
   */
  public _syncSnapRing(): void {
    const cursor = this._host._lastCursor;
    let ring: DrawingPoint | null = null;
    let pane = cursor?.paneIndex ?? this._host._pendingPane;
    if (cursor !== null && this._host._tool !== null && !this._host._isFreehand()
      && this._host._lockedPoint({ time: cursor.time, price: cursor.price }, cursor.paneIndex) === null) {
      ring = this._host._snapPoint({ time: cursor.time, price: cursor.price }, cursor.paneIndex);
      pane = cursor.paneIndex;
    }
    for (const [index, l] of this._layers) l.top.setSnapPoint(index === pane ? ring : null);
    // The ring's pane may not have layers yet (no drawing there so far); make
    // them only when there is a ring to paint, since a pair costs a pane repaint.
    if (ring !== null && !this._layers.has(pane)) this._layerFor(pane).top.setSnapPoint(ring);
  }
}
