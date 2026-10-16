/**
 * The pointer gestures that make no drawing of their own. Shift+click on
 * empty chart space lays down a ruler for a moment: a preview of the measure
 * tool from the click to the pointer, gone on the next click or on Escape.
 * Ctrl+drag on empty space draws a box that selects every drawing it touches.
 * The eraser, a mode rather than a modifier, deletes what a click or a drag
 * touches, as one undo step when the pointer lets go.
 *
 * Nothing here enters the model. A ruler is a preview, painted in the slot a
 * shape being placed uses, so it is never saved, never an undo step, never
 * announced as a drawing and never carried to another chart by a link. A box
 * only selects.
 *
 * A drag on empty space pans the chart, and the chart decides that on the
 * press, before any gesture sees the pointer. So the box is made ready ahead
 * of the press: while Ctrl is held over empty space with no tool armed, the
 * gestures ask for placement mode, in which a press is reported as pointer
 * moves and clicks instead of a pan. The pointer reports carry the keys held,
 * and the hover report says whether anything is under the pointer; the chart
 * gets its pan back on the first report that no longer holds.
 */
import type { PlotRect } from 'openalgo-charts';
import type { Drawing, DrawingPoint, DrawingStyle } from './types';
import { getDrawingTool, hasDrawingTool } from './registry';
import type { DrawingGestureOptions } from './controller-types';
import type { GestureLayer } from './gesture-layer';
import { boxSamples, normalizeBox, touchesBox, touchesPath } from './hit-geometry';
import { readOnly } from './layer';
import { clamp } from '../helpers/math';

/** The modifier keys a pointer report carried. `mod` is Ctrl or Cmd. */
export interface GestureKeys {
  shift: boolean;
  mod: boolean;
  alt: boolean;
}

/** A chart click as the gestures read it. */
interface GestureClick {
  id: string | null;
  time: number;
  price: number | null;
  paneIndex: number;
  viaDrag?: boolean;
  /** Container x and pane-local y. */
  point?: { x: number; y: number };
  keys: GestureKeys;
}

/** A pointer report as the gestures read it: container px, and whether a button is held. */
interface GesturePointer {
  paneIndex: number | null;
  point: { x: number; y: number } | null;
  pressed: boolean;
  keys: GestureKeys;
  /** A fingertip: the eraser reaches as far as a touch grabs. */
  touch: boolean;
}

/** Where the pointer is, in data space, on which pane. */
interface GestureCursor {
  time: number;
  price: number;
  paneIndex: number;
}

/** What the gestures need of the controller that owns them. */
interface GestureHost {
  /** The armed drawing tool, or null. */
  tool(): string | null;
  /** The gestures the host has left on. */
  options(): Required<DrawingGestureOptions>;
  /** Where a click at `point` lands on `paneIndex`, the magnet included. */
  aim(point: DrawingPoint, paneIndex: number): DrawingPoint;
  /** The style a preview is painted in. */
  style(): DrawingStyle;
  /** Paint the preview slot again: what `ruler` returns has changed. */
  preview(): void;
  emit(event: string, payload: unknown): void;
  /** The drawings, in paint order. */
  drawings(): readonly Drawing[];
  /** The selection, and a replacement of it. */
  selection(): readonly string[];
  select(ids: readonly string[]): void;
  /** A pane's top layer, made on first use when `make` is set. */
  layer(paneIndex: number, make?: boolean): GestureLayer | undefined;
  /** Leave these drawings unpainted until told otherwise: what an eraser drag has touched. */
  hide(ids: ReadonlySet<string>): void;
  /** Delete these drawings, as one undo step. */
  erase(ids: readonly string[]): void;
  /** A pane's plot in container px, or null for one with no plot on screen. */
  plotRect(paneIndex: number): PlotRect | null;
  /** What `wantsPlacement` answers may have changed: read it again. */
  placement(): void;
}

/**
 * How near, in media px, a drawing's geometry must come to count as touched:
 * the grab radius of a click, so a box takes what a click there would take.
 */
const REACH = 6;

/**
 * Past this many `distance` calls a frame, the box stops selecting as it
 * grows and selects once, on release: a box across a busy chart would
 * otherwise cost the drag its frame rate.
 */
const LIVE_BUDGET = 40000;

/** How far, in media px, a press travels before it is a drag: the chart's own click slop. */
const SLOP = 3;

/** A box being dragged: on one pane, in plot px, with the selection it adds to. */
interface Box {
  pane: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  base: readonly string[];
  moved: boolean;
}

/**
 * What the eraser may take: what the user could select and delete. A hidden
 * drawing is not under the pointer, a locked or unselectable one cannot be
 * picked, and a read-only one cannot be deleted by the user at all.
 */
const erasable = (d: Drawing): boolean =>
  d.visible !== false && d.locked !== true && d.policy?.selectable !== false && !readOnly(d);

/** The id of the ruler's preview. It is never a drawing, so it never collides with one. */
const RULER_ID = '__measure';

export class DrawingGestures {
  private readonly _host: GestureHost;
  private _measure: { pane: number; start: DrawingPoint; end: DrawingPoint } | null = null;
  private _box: Box | null = null;
  /** The keys held as of the last pointer report. */
  private _keys: GestureKeys = { shift: false, mod: false, alt: false };
  /** Any hit under the pointer, a drawing's or anything else's: a box starts only over nothing. */
  private _hit: string | null = null;
  /** The last position the pointer hovered at, where a press it makes lands. */
  private _over: { pane: number; x: number; y: number } | null = null;
  /** A pick is waiting for its click: it owns the press. */
  private _picking = false;
  /** Whether a press now is a box: what placement mode was last asked for by. */
  private _ready = false;
  /** Swallow the release half of the gesture just finished. */
  private _swallow = false;
  private _eraser = false;
  /** An eraser drag: where it last was on its pane, in plot px, and what it has touched. */
  private _sweep: { pane: number; last: { x: number; y: number }; ids: Set<string> } | null = null;
  /** The pane the eraser's ring is on. */
  private _ringPane: number | null = null;

  public constructor(host: GestureHost) {
    this._host = host;
  }

  /** Whether a temporary measure is on the chart. */
  public measuring(): boolean {
    return this._measure !== null;
  }

  /**
   * A click the gestures take, true when it was theirs and nothing else is
   * to act on it. Any click ends a ruler: it is there to be read and let go
   * of, and a click that also selected or placed something would be two acts
   * for one press. A Shift+click on empty space, with no tool armed, starts
   * one; with a tool armed Shift is the angle lock, and on a drawing it adds
   * to the selection.
   */
  public click(p: GestureClick): boolean {
    if (this._box !== null) return this._boxClick(p);
    if (this._swallow && p.viaDrag === true) { this._swallow = false; return true; }
    this._swallow = false;
    if (this._eraser) return this._eraserClick(p);
    if (this.endMeasure()) return true;
    const { shift, mod, alt } = p.keys;
    if (!this._host.options().measure || this._host.tool() !== null || p.id !== null || p.viaDrag === true
      || !shift || mod || alt || p.price === null || !Number.isFinite(p.price) || !Number.isFinite(p.time)
      || !hasDrawingTool('measure')) return false;
    const start = this._host.aim({ time: p.time, price: p.price }, p.paneIndex);
    this._measure = { pane: p.paneIndex, start, end: start };
    this._host.preview();
    this._host.emit('draw:measure', { active: true });
    return true;
  }

  /**
   * Follow the pointer with the ruler's far end, on the pane it started on.
   * True when the ruler moved. A pointer off that pane leaves the end where
   * it last was, so the reading stays up while the hand passes elsewhere.
   */
  public follow(cursor: GestureCursor | null): boolean {
    const m = this._measure;
    if (m === null || cursor === null || cursor.paneIndex !== m.pane) return false;
    m.end = this._host.aim({ time: cursor.time, price: cursor.price }, m.pane);
    return true;
  }

  /** The ruler as the preview slot paints it, or null when there is none. */
  public ruler(): Drawing | null {
    const m = this._measure;
    if (m === null) return null;
    return {
      id: RULER_ID, tool: 'measure', points: [{ ...m.start }, { ...m.end }], paneIndex: m.pane, zIndex: 0,
      style: { ...this._host.style(), ...getDrawingTool('measure').defaultStyle },
    };
  }

  /** Take the ruler away. True when there was one. */
  public endMeasure(): boolean {
    if (this._measure === null) return false;
    this._measure = null;
    this._host.preview();
    this._host.emit('draw:measure', { active: false });
    return true;
  }

  /** End every gesture in hand: the chart under it changed, or the controller is going. */
  public reset(): void {
    this.endMeasure();
    this._dropBox();
    this._dropSweep();
  }

  // ── eraser ──────────────────────────────────────────────────────────────

  public erasing(): boolean {
    return this._eraser;
  }

  /** Turn eraser mode on or off. True when that changed anything. */
  public setEraser(active: boolean): boolean {
    if (active === this._eraser) return false;
    this._dropSweep();
    this._eraser = active;
    if (!active) this._ring(null);
    this._host.placement();
    this._host.emit('draw:eraser', { active });
    return true;
  }

  /**
   * A click in eraser mode is the eraser's, whatever it lands on. The press
   * half of a drag ends the sweep, and its release half is swallowed; a click
   * with no drag deletes the drawing it hit, and one on empty space nothing.
   */
  private _eraserClick(p: GestureClick): boolean {
    if (this._sweep !== null) {
      this._commitSweep();
      this._swallow = p.viaDrag !== true;
      return true;
    }
    if (p.viaDrag !== true && p.id !== null && p.id.startsWith('draw:')) {
      const id = p.id.slice('draw:'.length).split('#')[0]!; // a split has a first part
      const d = this._host.drawings().find((x) => x.id === id);
      if (d !== undefined && erasable(d)) this._host.erase([id]);
    }
    return true;
  }

  /** A pointer report in eraser mode: the ring follows it, and a pressed one sweeps. */
  private _eraserPointer(p: GesturePointer): void {
    const rect = p.paneIndex === null || p.point === null ? null : this._host.plotRect(p.paneIndex);
    if (rect === null || p.paneIndex === null || p.point === null) { this._ring(null); return; }
    const at = { x: p.point.x - rect.left, y: p.point.y - rect.top };
    const reach = p.touch ? REACH * 2 : REACH;
    this._ring(p.paneIndex, at, reach);
    if (!p.pressed) {
      this._commitSweep();   // the release went unreported
      this._over = { pane: p.paneIndex, x: p.point.x, y: p.point.y };
      return;
    }
    let sweep = this._sweep;
    if (sweep === null || sweep.pane !== p.paneIndex) {
      // A press lands where the pointer last hovered: the chart reports no press.
      const from = sweep === null && this._over?.pane === p.paneIndex ? { x: this._over.x - rect.left, y: this._over.y - rect.top } : at;
      sweep = this._sweep = { pane: p.paneIndex, last: from, ids: sweep?.ids ?? new Set() };
    }
    const rc = this._host.layer(sweep.pane)?.context() ?? null;
    if (rc !== null) {
      const before = sweep.ids.size;
      for (const d of this._host.drawings()) {
        if (d.paneIndex === sweep.pane && !sweep.ids.has(d.id) && erasable(d) && touchesPath(d, rc, sweep.last, at, reach)) sweep.ids.add(d.id);
      }
      if (sweep.ids.size !== before) this._host.hide(sweep.ids);
    }
    sweep.last = at;
  }

  /** Delete what the sweep touched, as one step. */
  private _commitSweep(): void {
    const sweep = this._sweep;
    if (sweep === null) return;
    this._sweep = null;
    if (sweep.ids.size > 0) this._host.erase([...sweep.ids]);
    this._host.hide(new Set());
  }

  /** Give back what an interrupted sweep hid, deleting nothing. */
  private _dropSweep(): void {
    if (this._sweep === null) return;
    this._sweep = null;
    this._host.hide(new Set());
  }

  /** Put the eraser's ring on `pane` at `at`, or take it off. */
  private _ring(pane: number | null, at?: { x: number; y: number }, radius?: number): void {
    if (this._ringPane !== null && this._ringPane !== pane) this._host.layer(this._ringPane)?.setRing(null);
    this._ringPane = pane;
    if (pane !== null && at !== undefined) this._host.layer(pane, true)?.setRing(at, radius);
  }

  // ── box select ──────────────────────────────────────────────────────────

  /** The hit id under the pointer, as the chart's hover reports it. */
  public hover(id: string | null): void {
    this._hit = id;
    this._host.placement();
  }

  /** A pick started or ended: while one waits, a press is its. */
  public picking(active: boolean): void {
    this._picking = active;
    this._host.placement();
  }

  /** Whether a gesture needs the chart's press: a box in hand, or one ready to start. */
  public wantsPlacement(): boolean {
    this._ready = this._box === null && this._host.options().boxSelect && this._host.tool() === null && !this._eraser
      && this._measure === null && !this._picking && this._keys.mod && this._hit === null && this._over !== null;
    return this._eraser || this._box !== null || this._ready;
  }

  /** A crosshair report: follow the keys and the hover position, and grow a box in hand. */
  public pointer(p: GesturePointer): void {
    this._swallow = false;
    this._keys = p.keys;
    if (this._eraser) { this._eraserPointer(p); return; }
    if (this._box !== null) {
      // Past the plot the chart reports no point; the box waits for the pointer's return.
      if (p.point === null) return;
      if (p.pressed) this._growBox(p.point);
      else this._finishBox();   // the release went unreported
      return;
    }
    if (p.pressed) {
      if (this._ready && this._host.tool() === null && p.point !== null && p.paneIndex !== null) this._startBox(p.paneIndex, p.point);
      return;
    }
    this._over = p.point === null || p.paneIndex === null ? null : { pane: p.paneIndex, x: p.point.x, y: p.point.y };
    this._host.placement();
  }

  /**
   * Start a box on `pane` where the press landed: the last hover position
   * when it was on this pane, since the chart reports no press, else here.
   */
  private _startBox(pane: number, at: { x: number; y: number }): void {
    const rect = this._host.plotRect(pane);
    if (rect === null) return;
    const from = this._over?.pane === pane ? this._over : at;
    const x0 = clamp(from.x - rect.left, 0, rect.width);
    const y0 = clamp(from.y - rect.top, 0, rect.height);
    this._box = { pane, x0, y0, x1: x0, y1: y0, base: this._keys.shift ? [...this._host.selection()] : [], moved: false };
    this._growBox(at);
  }

  private _growBox(at: { x: number; y: number }): void {
    const box = this._box as Box;
    const rect = this._host.plotRect(box.pane);
    if (rect === null) return;
    box.x1 = clamp(at.x - rect.left, 0, rect.width);
    box.y1 = clamp(at.y - rect.top, 0, rect.height);
    box.moved ||= Math.abs(box.x1 - box.x0) > SLOP || Math.abs(box.y1 - box.y0) > SLOP;
    if (!box.moved) return;
    this._host.layer(box.pane)?.setBox(box);
    this._selectBox(box, false);
  }

  /**
   * The clicks a box's release makes. The press half comes first and ends
   * the box, at the exact press point, and the release half after it is
   * swallowed. A click with no drag behind it is not a box: it goes on as
   * the click it is, Ctrl+click on empty space.
   */
  private _boxClick(p: GestureClick): boolean {
    const box = this._box as Box;
    if (!box.moved) { this._dropBox(); return false; }
    if (p.viaDrag !== true && p.point !== undefined) {
      const rect = this._host.plotRect(box.pane);
      // The click's y is pane-local already, which is plot-local.
      if (rect !== null) { box.x0 = clamp(p.point.x - rect.left, 0, rect.width); box.y0 = clamp(p.point.y, 0, rect.height); }
    }
    this._finishBox();
    this._swallow = p.viaDrag !== true;
    return true;
  }

  private _finishBox(): void {
    const box = this._box;
    if (box === null) return;
    if (box.moved) this._selectBox(box, true);
    this._dropBox();
  }

  private _dropBox(): void {
    const box = this._box;
    if (box === null) return;
    this._box = null;
    this._host.layer(box.pane)?.setBox(null);
    this._host.placement();
  }

  /**
   * Select what `box` touches, added to what it started with under Shift.
   * While the box grows this is skipped once it would cost too much a frame;
   * the release always selects.
   */
  private _selectBox(box: Box, final: boolean): void {
    const rc = this._host.layer(box.pane)?.context() ?? null;
    if (rc === null) return;
    const b = normalizeBox(box);
    const candidates = this._host.drawings().filter((d) => d.paneIndex === box.pane && d.locked !== true && d.policy?.selectable !== false);
    if (!final && candidates.length * boxSamples(b, REACH) > LIVE_BUDGET) return;
    const hits = candidates.filter((d) => touchesBox(d, rc, b, REACH)).map((d) => d.id);
    this._host.select([...box.base, ...hits.filter((id) => !box.base.includes(id))]);
  }
}
