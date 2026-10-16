/**
 * The drag of a drawing, a multi-selection or one handle: the gesture's
 * starting state, each frame applied from it, the magnet's pull on a grabbed
 * shape, a drag that moves copies, and the end or the cancel.
 *
 * Its own module for the reason chart.ts has collaborators: the gesture's
 * state belongs to these methods alone. The controller reaches it through
 * `DrawingController._drag`, and it reaches the controller through
 * `DragHost`; the public `cancelDrag` stays on the controller with its
 * documentation. Members the controller calls are public on this internal
 * class; the tier entry does not export it.
 */
import type { Drawing, DrawingPoint, ScreenPoint, ViewportPoint } from './types';
import type { DrawingController, DragPayload } from './controller';
import type { DrawingHistoryEntry } from './drawing-history';
import { placeViewportAnchors, readOnly } from './layer';
import { getDrawingTool, hasDrawingTool } from './registry';
import { cloneDrawing, freshCopy } from './clipboard';
import { clamp } from '../helpers/math';
import { barAt } from './snap';

/**
 * The slice of the controller the drag reads and drives, typed from the
 * controller's own members as `HistoryHost` is.
 */
export interface DragHost {
  _drawings: DrawingController['_drawings'];
  readonly _chart: DrawingController['_chart'];
  readonly _opts: DrawingController['_opts'];
  readonly _screen: DrawingController['_screen'];
  readonly _history: DrawingController['_history'];
  readonly _layerSet: DrawingController['_layerSet'];
  readonly _selection: DrawingController['_selection'];
  readonly _shift: DrawingController['_shift'];
  get: DrawingController['get'];
  select: DrawingController['select'];
  toJSON: DrawingController['toJSON'];
  _selectable: DrawingController['_selectable'];
  _targets: DrawingController['_targets'];
  _insert: DrawingController['_insert'];
  _setSelection: DrawingController['_setSelection'];
  _sync: DrawingController['_sync'];
  _shownFilter: DrawingController['_shownFilter'];
  _noteKeys: DrawingController['_noteKeys'];
  _notePointer: DrawingController['_notePointer'];
  _snapPoint: DrawingController['_snapPoint'];
  _emitChange: DrawingController['_emitChange'];
}

export class DrawingDrag {
  private readonly _host: DragHost;
  /**
   * Drawings that live under the series but are painted on the top layer for
   * the length of a drag. The top layer repaints on the cursor tier; the
   * bottom one costs the series every frame, which is the difference between
   * a drag that follows the hand and one that stutters through the candles.
   */
  public readonly _lifted = new Set<string>();
  /**
   * One gesture's starting state. `items` are ids rather than objects because
   * an undo mid-drag replaces every drawing object, and a stale reference
   * would move a shape that is no longer in the model.
   */
  public _dragStart: {
    id: string;
    handle: number | null;
    from: DrawingPoint;
    /** The press on its pane's plot, in media px: what a viewport drawing moves by the pointer from. */
    origin: ScreenPoint | null;
    /** For a shape grabbed by its body, the anchor of it the magnet lands. */
    anchor: number | null;
    /** The drawing that anchor is on: the one grabbed, or its copy. */
    lead: string;
    /** On a drag that copies, the copies it moves and the selection they replaced. */
    copy?: { ids: string[]; sources: string[] };
    items: { id: string; paneIndex: number; points: DrawingPoint[]; viewportPoints?: ViewportPoint[] }[];
    undo: DrawingHistoryEntry[];
    redo: DrawingHistoryEntry[];
  } | null = null;

  public constructor(host: DragHost) {
    this._host = host;
  }

  /**
   * The anchor of a grabbed shape the magnet lands: the one nearest the
   * press, since what the hand is closest to is what it means to put down.
   */
  private _grabbedAnchor(d: Drawing, p: DragPayload): number | null {
    if (d.space === 'viewport' || d.points.length === 0) return null;
    const press = this._host._screen.toPixel({ time: p.fromTime ?? p.time, price: p.fromPrice ?? p.price }, d.paneIndex);
    let best = 0;
    let bestD = Infinity;
    d.points.forEach((q, i) => {
      const at = press === null ? null : this._host._screen.toPixel(q, d.paneIndex);
      const dist = at === null || press === null ? i : Math.hypot(at.x - press.x, at.y - press.y);
      if (dist < bestD) { bestD = dist; best = i; }
    });
    return best;
  }

  /**
   * A shape's move with the magnet's pull on its grabbed anchor applied, or
   * null when nothing pulls: the whole shape shifts by what lands that one
   * anchor on the value, so it keeps its form.
   */
  private _pullShape(start: NonNullable<typeof this._dragStart>, dt: number, dp: number): { dt: number; dp: number } | null {
    const item = start.anchor === null ? undefined : start.items.find((i) => i.id === start.lead);
    const a = item === undefined || item.viewportPoints !== undefined ? undefined : item.points[start.anchor as number];
    if (a === undefined) return null;
    const moved = { time: a.time + dt, price: a.price + dp };
    const hit = this._host._snapPoint(moved, item!.paneIndex, barAt(this._host._chart, moved.time));
    return hit === null ? null : { dt: hit.time - a.time, dp: hit.price - a.price };
  }

  public _onDrag(p: DragPayload): void {
    if (!p.id.startsWith('draw:')) return;
    const [rawId, handleStr] = p.id.slice('draw:'.length).split('#') as [string, ...string[]]; // a split has a first part
    const d = this._host.get(rawId);
    if (d === undefined || d.locked === true || readOnly(d) || !this._host._selectable(rawId)) return;
    const handle = handleStr === undefined ? null : Number(handleStr);

    this._host._notePointer(p);
    this._host._noteKeys(p);
    if (this._dragStart === null || this._dragStart.id !== rawId || this._dragStart.handle !== handle) {
      // Grabbing the body of an unselected shape selects it first, on its own:
      // the selection is what moves, and a drag that moved something other than
      // what it grabbed would be a surprise.
      if (handle === null && !this._host._selection.includes(rawId)) this._host.select(rawId);
      let moving = handle === null
        ? this._host._targets(this._host._selection).filter((m) => m.locked !== true && !readOnly(m))
        : [d];
      // Alt on a body moves copies instead, and only once the pointer has
      // really travelled: a copy dropped by a jitter would sit unseen under
      // the drawing it copies.
      const copy = handle === null && this._host._opts.gestures.dragCopy && p.modifiers?.alt === true;
      if (copy && !this._travelled(p)) return;
      // Snapshot once per gesture so undo restores the pre-drag position, not
      // an intermediate frame.
      const undo = this._host._history._undo.slice();
      const redo = this._host._history._redo.slice();
      this._host._history._pushUndo();
      const sources = this._host._selection.slice();
      const lead = moving.indexOf(d);
      if (copy) moving = this._copies(moving);
      this._dragStart = {
        id: rawId, handle,
        undo, redo,
        from: { time: p.fromTime ?? p.time, price: p.fromPrice ?? p.price },
        origin: this._host._screen.dragOrigin(p),
        anchor: handle === null ? this._grabbedAnchor(d, p) : null,
        lead: moving[lead]?.id ?? rawId,
        ...(copy ? { copy: { ids: moving.map((m) => m.id), sources } } : {}),
        items: moving.map((m) => ({
          id: m.id, paneIndex: m.paneIndex, points: m.points.map((q) => ({ ...q })),
          ...(m.space === 'viewport' ? { viewportPoints: (m.viewportPoints ?? []).map((q) => ({ ...q })) } : {}),
        })),
      };
      // Anything under the series rides on the top layer for the gesture, so
      // the frames that follow repaint the overlay alone. Lifting re-lists the
      // bottom layer once, which is the one series repaint a lifted drag
      // costs; a drag with nothing to lift never touches it.
      let lifted = false;
      for (const m of moving) {
        if (!this._host._layerSet._onTop(m)) { this._lifted.add(m.id); lifted = true; }
      }
      this._moveDrag(p, d, handle);
      if (lifted) this._host._sync();
      else this._syncDrag();
      this._emitDragPreview();
      return;
    }
    this._moveDrag(p, d, handle);
    this._syncDrag();
    this._emitDragPreview();
  }

  /** Whether a drag has left its press by more than the chart's click slop, on screen. */
  private _travelled(p: DragPayload): boolean {
    const from = this._host._screen.toPixel({ time: p.fromTime ?? p.time, price: p.fromPrice ?? p.price }, p.paneIndex);
    const to = this._host._screen.toPixel({ time: p.time, price: p.price }, p.paneIndex);
    return from === null || to === null || Math.hypot(to.x - from.x, to.y - from.y) > 3;
  }

  /**
   * Copies of `sources` for a drag to move, in the model and selected. A
   * copy is the user's own drawing, as a duplicate is: no policy, a fresh
   * id, and `_insert` drops the link lineage.
   */
  private _copies(sources: readonly Drawing[]): Drawing[] {
    const copies = sources.map((m) => this._host._insert(freshCopy(m)));
    this._host._setSelection(copies.map((c) => c.id));
    return copies;
  }

  /** A cancelled copy leaves nothing: its copies go, and the selection is what they were copied from. */
  private _dropCopies(start: NonNullable<typeof this._dragStart>): void {
    if (start.copy === undefined) return;
    const gone = new Set(start.copy.ids);
    this._host._drawings = this._host._drawings.filter((d) => !gone.has(d.id));
    this._host._setSelection(start.copy.sources.filter((id) => this._host._selectable(id)));
  }

  private _emitDragPreview(): void {
    const drawings = this._dragStart?.items.map(item => this._host.get(item.id)).filter((d): d is Drawing => d !== undefined) ?? [];
    this._host._chart.emit('draw:preview', { drawings: drawings.map(cloneDrawing) });
  }

  /**
   * Roll back an interrupted drag and put back the undo and redo branches it
   * found. `sync` false leaves the layers and the chart state as they are,
   * for a caller that is about to renumber the panes they are listed by.
   */
  public cancelDrag(sync = true): boolean {
    const start = this._dragStart;
    if (start === null) return false;
    this._dragStart = null;
    for (const item of start.items) {
      const drawing = this._host.get(item.id);
      if (drawing !== undefined) this._restoreAnchors(drawing, item);
    }
    this._dropCopies(start);
    this._host._history._undo = start.undo;
    this._host._history._redo = start.redo;
    this._host._history._pendingHistory = null;
    this._lifted.clear();
    if (sync && this._host._chart.isDestroyed !== true) this._host._sync();
    this._host._chart.emit('draw:preview-clear', { ids: start.items.map(item => item.id) });
    return true;
  }

  /** Apply one drag frame to the model, from the gesture's snapshot. */
  private _moveDrag(p: DragPayload, d: Drawing, handle: number | null): void {
    const start = this._dragStart as NonNullable<typeof this._dragStart>;
    if (handle === null) {
      // Whole shape: translate every anchor of every selected shape by the
      // cursor delta. A shape on another pane cannot take the price delta (its
      // scale is a different quantity), so it takes the same screen distance.
      const pull = this._pullShape(start, p.time - start.from.time, p.price - start.from.price);
      const dt = pull?.dt ?? p.time - start.from.time;
      const dp = pull?.dp ?? p.price - start.from.price;
      const dy = this._host._screen.pixelDelta(start.from.price, pull === null ? p.price : start.from.price + dp, p.paneIndex);
      // A pinned shape takes the pointer's travel on screen, as a fraction of
      // its own pane, so it moves with the hand whatever the scales say.
      const at = this._host._screen.gesturePlot(p, p.paneIndex);
      const travel = at === null || start.origin === null ? null : { x: at.x - start.origin.x, y: at.y - start.origin.y };
      for (const item of start.items) {
        const m = this._host.get(item.id);
        if (m === undefined) continue;
        if (item.viewportPoints !== undefined) {
          const frame = this._host._screen.plotFrame(item.paneIndex);
          if (frame !== null && travel !== null) m.viewportPoints = this._host._screen.shiftPinned(m, item.viewportPoints, travel.x, travel.y, frame);
          continue;
        }
        const samePane = item.paneIndex === p.paneIndex;
        m.points = item.points.map((q) => ({
          ...q,
          time: q.time + dt,
          price: samePane ? q.price + dp : this._host._screen.offsetPrice(q.price, item.paneIndex, dy),
        }));
      }
    } else if (d.space === 'viewport') {
      // A handle lands under the pointer, held on the plot, and then the box
      // is kept inside it: a note's one handle is its corner, and the rest of
      // the note has to stay where it can be seen and grabbed again too.
      const anchors = start.items[0]!.viewportPoints ?? []; // a handle drag carries its one drawing
      const at = this._host._screen.gesturePlot(p, d.paneIndex);
      const frame = this._host._screen.plotFrame(d.paneIndex);
      if (handle >= 0 && handle < anchors.length && at !== null && frame !== null) {
        const { width, height } = frame;
        const placed = placeViewportAnchors(d, anchors, width, height);
        placed[handle] = { x: clamp(at.x, 0, width), y: clamp(at.y, 0, height) };
        // Where the box reaches an edge before the handle does (a label above
        // a box), the handle stops short instead of pushing the other corners
        // away from the edge it was dragged to.
        placed[handle] = placeViewportAnchors(d, placed.map((q) => ({ x: q.x / width, y: q.y / height })), width, height)[handle]!;
        d.viewportPoints = this._host._screen.pinPlot(d, placed, frame);
      }
    } else if (handle >= 0 && handle < d.points.length) {
      const item = start.items[0]!; // a handle drag carries its one drawing, and handle is one of its anchors
      const target: DrawingPoint = { time: p.time, price: p.price };
      // Shift on the handle of a two-anchor line locks it to the 45 degree
      // step about the other anchor, the same way placement does, and the
      // lock wins over the magnet there too.
      const locked = this._host._shift && item.points.length === 2 && hasDrawingTool(d.tool) && getDrawingTool(d.tool).angleLock === true
        ? this._host._screen.lockAngle(item.points[1 - handle]!, target, d.paneIndex) : null;
      const landed = locked ?? this._host._snapPoint(target, d.paneIndex, barAt(this._host._chart, target.time)) ?? target;
      const moved = item.points.map((q, i) => (i === handle ? { ...q, ...landed } : { ...q }));
      // A tool with a constraint reads the whole set after the one anchor
      // moved, from the gesture's snapshot every frame: constraining the
      // already-constrained previous frame would let a flip feed on itself.
      const tool = hasDrawingTool(d.tool) ? getDrawingTool(d.tool) : undefined;
      d.points = tool?.constrain === undefined ? moved : tool.constrain(moved, handle);
    }
  }

  /** Put a drawing's anchors back as a gesture found them. */
  private _restoreAnchors(d: Drawing, item: { points: readonly DrawingPoint[]; viewportPoints?: readonly ViewportPoint[] }): void {
    d.points = item.points.map((point) => ({ ...point }));
    if (item.viewportPoints !== undefined) d.viewportPoints = item.viewportPoints.map((point) => ({ ...point }));
  }

  public _onDragEnd(): void {
    if (this._dragStart === null) return;
    const moved = this._dragStart.items.map((i) => this._host.get(i.id)).filter((m): m is Drawing => m !== undefined);
    const copied = this._dragStart.copy !== undefined;
    this._dragStart = null;
    this._host._chart.emit('draw:preview-clear', { ids: moved.map(d => d.id) });
    // Whatever was lifted for the gesture goes back under the series.
    if (this._lifted.size > 0) {
      this._lifted.clear();
      this._host._sync();
    }
    // A copy is new at the drop: announced once, where it landed, so a link
    // or an autosave never sees it at the place it was copied from.
    for (const m of moved) this._host._chart.emit(copied ? 'draw:add' : 'draw:update', { drawing: m });
    if (moved.length > 0) this._host._emitChange(moved.map((m) => m.id), copied ? 'add' : 'update');
  }

  /**
   * The per-frame half of a drag: only the top layers of the panes the
   * gesture touches are re-listed, so the repaint stays on the cursor tier.
   * Everything moving is on a top layer by then (anything under the series
   * was lifted when the gesture began), and the bottom layers have not
   * changed since, so re-listing them would cost a series repaint for
   * nothing.
   */
  private _syncDrag(): void {
    const start = this._dragStart;
    if (start === null) return;
    const panes = new Set(start.items.map((i) => i.paneIndex));
    const shown = this._host._shownFilter();
    for (const pane of panes) {
      const l = this._host._layerSet._layers.get(pane);
      if (l === undefined) continue;
      l.top.setDrawings(this._host._drawings.filter((d) => d.paneIndex === pane && this._host._layerSet._onTop(d) && shown(d)));
    }
    this._host._chart.setDrawingState(this._host.toJSON());
  }
}
