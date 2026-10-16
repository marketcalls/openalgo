/**
 * Study input anchors: a handle on the chart for a price input paired with a
 * time (`timeKey`) and declared with `anchor: true`. It sits at the point the
 * two settings name, on the pane and scale a pick of that price reads, and a
 * drag moves both halves as one settings change that the drawing history
 * holds as one undo step, or hands to a host's own timeline. A point written
 * any other way, a settings dialog's Pick point, is a step of the drawing
 * history too: held nowhere, it would leave the drag before it describing a
 * point the study no longer holds, and an undo would pass over both to the
 * drawing before them.
 *
 * The drawing controller owns the anchors because the two share everything
 * that makes an edit on the chart safe: an active drawing tool takes the press
 * instead, Escape cancels a drag in hand, and Undo is the key a host already
 * routes to the drawing history.
 */
// Runtime and types both come from the package entry: the registry is one Map
// the chart reads, and a second copy inlined here would be empty.
import { getIndicator, plotStyleKeys } from 'openalgo-charts';
import type {
  IndicatorApi, IPrimitive, PriceScale, PriceScaleId, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, ZOrder,
} from 'openalgo-charts';
import type { DrawingChartHost } from './controller-types';

/** Where a study's price input is picked and anchored: a pane, and a scale on it. */
export interface StudyInputTarget {
  paneIndex: number;
  priceScaleId: PriceScaleId;
}

/** The pane methods a target is resolved through. `Pane` has them. */
interface TargetPane {
  scales(): readonly PriceScale[];
  scaleStates(): object;
  scaleFor(id: PriceScaleId): PriceScale;
}

/** The slice of the chart the anchors need. `Chart` satisfies it. */
type InputAnchorHost = Pick<DrawingChartHost, 'on' | 'addPrimitive' | 'removePrimitive' | 'dataLayer' | 'indicators' | 'panes'>;

/**
 * One anchor move as an undo step, walked by the drawing history or by the
 * host's timeline it was handed to (`DrawingController.delegateInputAnchorSteps`).
 * Each call writes the other side's point, and is false, writing nothing, once
 * the study no longer holds the point it starts from.
 */
export interface InputAnchorStep {
  undo(): boolean;
  redo(): boolean;
}

interface Point { time: number; price: number }

/** The two settings one anchor writes, on the study that holds them. */
interface Pair { readonly studyId: string; readonly priceKey: string; readonly timeKey: string }

const samePoint = (a: Point, b: Point): boolean => Object.is(a.time, b.time) && Object.is(a.price, b.price);
const finitePoint = (p: Point): boolean => Number.isFinite(p.time) && Number.isFinite(p.price);

const RADIUS = 5;
const HIT_RADIUS = 9;
const PREFIX = 'input-anchor:';

/**
 * The pane and scale a study's `price` input is picked on and anchored to,
 * or null when that cannot be told. An explicit `pick` target with both
 * halves is used as given. Otherwise the study's own plots decide: the price
 * belongs where they are drawn, which must be one scale on one pane (and
 * inside any half the descriptor did name), since a price read off the wrong
 * scale is a different number.
 */
export function studyInputTarget(chart: { panes?(): readonly unknown[] }, study: IndicatorApi, key: string): StudyInputTarget | null {
  let descriptor;
  try { descriptor = getIndicator(study.indicatorId); } catch { return null; }
  const input = descriptor.inputs.find(item => item.key === key);
  if (input?.type !== 'price') return null;
  const explicit = typeof input.pick === 'object' && input.pick !== null ? input.pick : {};
  if (explicit.paneIndex !== undefined && explicit.priceScaleId !== undefined) {
    return { paneIndex: explicit.paneIndex, priceScaleId: explicit.priceScaleId };
  }
  const panes = (chart.panes?.() ?? []) as readonly TargetPane[];
  const targets = new Map<string, StudyInputTarget>();
  for (const plot of descriptor.plots) {
    const series = study.series(plot.key), priceScaleId = study.plotPriceScaleId(plot.key);
    if (!series || priceScaleId === null) continue;
    const scale = series.priceScale(), paneIndex = panes.findIndex(pane => pane.scales().includes(scale));
    if (paneIndex < 0 || (explicit.paneIndex !== undefined && explicit.paneIndex !== paneIndex)
      || (explicit.priceScaleId !== undefined && explicit.priceScaleId !== priceScaleId)) continue;
    targets.set(`${paneIndex}:${priceScaleId}`, { paneIndex, priceScaleId });
  }
  return targets.size === 1 ? [...targets.values()][0]! : null;
}

/** The handle itself: a ring at the point, with guides while it is in hand. */
class AnchorHandle implements IPrimitive {
  public time = Number.NaN;
  public price = Number.NaN;
  public color: string | null = null;
  public editable = true;
  private _host: PrimitiveHost | null = null;

  public constructor(
    public readonly id: string,
    public readonly studyId: string,
    public readonly priceKey: string,
    public readonly timeKey: string,
    public target: StudyInputTarget,
    private readonly _scale: (target: StudyInputTarget) => PriceScale | null,
    private readonly _live: () => boolean,
  ) {}

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  public zOrder(): ZOrder { return 'top'; }
  public autoscaleInfo(): null { return null; }
  public update(): void { this._host?.requestUpdate(); }
  public scale(): PriceScale | null { return this._scale(this.target); }

  /** Plot-relative media px of the point, or null when it has no place there. */
  private _at(rc: PrimitiveRenderContext): { x: number; y: number } | null {
    const scale = this.scale();
    if (scale === null || !Number.isFinite(this.time) || !Number.isFinite(this.price)) return null;
    const x = rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(this.time));
    const y = scale.priceToY(this.price);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const at = this._at(rc);
    if (at === null) return;
    const { dpr } = rc;
    const active = this.editable && (rc.hoverId === this.id || rc.dragId === this.id);
    const color = this.color ?? rc.theme.crosshair;
    const x = at.x * dpr, y = at.y * dpr, w = rc.plotWidth * dpr, h = rc.plotHeight * dpr;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, Math.round(w), Math.round(h));
    ctx.clip();
    if (active) {
      // Both halves of the point named while it is in hand: the bar it is
      // on and the price it reads, which is what a drag changes together.
      const px = Math.round(x) + 0.5, py = Math.round(y) + 0.5;
      ctx.globalAlpha = 0.6;
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(1, Math.round(dpr));
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      ctx.beginPath();
      ctx.moveTo(px, 0); ctx.lineTo(px, h);
      ctx.moveTo(0, py); ctx.lineTo(w, py);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
    ctx.beginPath();
    ctx.arc(x, y, (active ? RADIUS + 1 : RADIUS) * dpr, 0, Math.PI * 2);
    ctx.fillStyle = rc.theme.background;
    ctx.fill();
    ctx.lineWidth = 2 * dpr;
    ctx.strokeStyle = color;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 1.5 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    // Not grabbable while a drawing tool or a pick owns the next press, nor
    // for a study the user may not configure: a handle that cannot move
    // must not look as if it could.
    if (!this.editable || !this._live()) return null;
    const at = this._at(rc);
    if (at === null || at.x < 0 || at.x > rc.plotWidth || at.y < 0 || at.y > rc.plotHeight) return null;
    const distance = Math.hypot(x - at.x, y - at.y);
    if (distance > HIT_RADIUS) return null;
    const scale = this.scale();
    return { externalId: this.id, zOrder: 'top', distance, cursor: 'move', draggable: true, cancelOnEscape: true,
      ...(scale === null ? {} : { priceScale: scale }) };
  }
}

type Settings = Readonly<Record<string, unknown>>;

/**
 * Keeps one handle per anchored input of every study on the chart, moves it
 * while it is dragged, and commits the release as one settings patch.
 * @internal Built and owned by `DrawingController`.
 */
export class InputAnchors {
  private readonly _handles = new Map<string, AnchorHandle>();
  /**
   * The point each anchored input of every study holds, hidden or not, and
   * the study object it was read from: a point that differs at the next sync
   * was written by someone else. The anchors' own writes note theirs first.
   */
  private readonly _points = new Map<string, { study: IndicatorApi; point: Point }>();
  private readonly _off: (() => void)[] = [];
  private _drag: { handle: AnchorHandle; from: Point } | null = null;
  private _picking = false;
  private _destroyed = false;

  public constructor(
    private readonly _chart: InputAnchorHost,
    private readonly _hooks: { record(step: InputAnchorStep, outside: boolean): void; placing(): boolean },
  ) {
    const on = (event: string, handler: (payload: unknown) => void): void => { this._off.push(_chart.on(event, handler)); };
    for (const event of ['objects:change', 'indicatorRemoved', 'paneMoved', 'paneRemoved']) on(event, () => this._sync());
    on('drag:start', p => this._onDragStart(p as { id?: unknown }));
    on('drag', p => this._onDrag(p as { id?: unknown; time?: unknown; price?: unknown }));
    on('drag:end', p => this._onDragEnd(p as { id?: unknown; time?: unknown; price?: unknown }));
    on('drag:cancel', p => { if (this._drag?.handle.id === (p as { id?: unknown }).id) this._cancelDrag(); });
    // A tool chosen or a pick started takes the next press, and a new context
    // is a different chart: none of them may inherit a drag in hand.
    on('draw:tool', () => { this._cancelDrag(); this._refresh(); });
    on('pick:start', () => { this._picking = true; this._cancelDrag(); this._refresh(); });
    on('pick:end', () => { this._picking = false; this._refresh(); });
    on('data:context', () => this._cancelDrag());
    on('destroy', () => this.destroy());
    this._sync();
  }

  public destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    for (const off of this._off.splice(0)) off();
    for (const handle of this._handles.values()) this._chart.removePrimitive(handle);
    this._handles.clear();
    this._points.clear();
    this._drag = null;
  }

  private _live = (): boolean => !this._picking && !this._hooks.placing();

  private _study(id: string): IndicatorApi | undefined {
    return this._chart.indicators?.().find(study => study.id === id);
  }

  private _scaleOf = (target: StudyInputTarget): PriceScale | null => {
    const pane = (this._chart.panes?.() ?? [])[target.paneIndex] as TargetPane | undefined;
    return pane && Object.prototype.hasOwnProperty.call(pane.scaleStates(), target.priceScaleId)
      ? pane.scaleFor(target.priceScaleId) : null;
  };

  /** Add, move and retire handles to match the studies on the chart now. */
  private _sync(): void {
    if (this._destroyed) return;
    const seen = new Set<string>();
    const watched = new Set<string>();
    for (const study of this._chart.indicators?.() ?? []) {
      let descriptor;
      try { descriptor = getIndicator(study.indicatorId); } catch { continue; }
      for (const input of descriptor.inputs) {
        if (input.type !== 'price' || input.anchor !== true || input.timeKey === undefined) continue;
        const id = `${PREFIX}${study.id}:${input.key}`;
        watched.add(id);
        this._watch(id, study, { studyId: study.id, priceKey: input.key, timeKey: input.timeKey });
        if (!study.visible()) continue;
        const target = studyInputTarget(this._chart, study, input.key);
        if (target === null) continue;
        seen.add(id);
        let handle = this._handles.get(id);
        if (handle !== undefined && handle.target.paneIndex !== target.paneIndex) {
          this._chart.removePrimitive(handle);
          handle = undefined;
        }
        if (handle === undefined) {
          handle = new AnchorHandle(id, study.id, input.key, input.timeKey, target, this._scaleOf, this._live);
          this._handles.set(id, handle);
          this._chart.addPrimitive(handle, target.paneIndex);
        }
        handle.target = target;
        const settings: Settings = study.settings();
        handle.editable = study.policy().configurable !== false;
        const plot = descriptor.plots[0];
        const color = plot === undefined ? undefined : settings[plotStyleKeys(plot).color];
        handle.color = typeof color === 'string' && color ? color : null;
        // A handle in hand shows where the pointer is, not what is stored.
        if (this._drag?.handle !== handle) {
          handle.time = settings[input.timeKey] as number;
          handle.price = settings[input.key] as number;
        }
        handle.update();
      }
    }
    for (const [id, handle] of this._handles) {
      if (seen.has(id)) continue;
      if (this._drag?.handle === handle) this._drag = null;
      this._chart.removePrimitive(handle);
      this._handles.delete(id);
    }
    for (const id of this._points.keys()) if (!watched.has(id)) this._points.delete(id);
  }

  /**
   * Note the point one anchored input holds now, and record a move someone
   * else wrote since the last sync (a settings dialog's Pick point, a price
   * typed in) as one step, the way a drag is. A study first seen, or seen as
   * a new object under the same id, only has its point noted. A study the
   * user may not configure was moved by its host, whose act is no step.
   */
  private _watch(id: string, study: IndicatorApi, pair: Pair): void {
    const settings: Settings = study.settings();
    const now = { time: settings[pair.timeKey] as number, price: settings[pair.priceKey] as number };
    const known = this._points.get(id);
    this._points.set(id, { study, point: now });
    if (known === undefined || known.study !== study || samePoint(known.point, now)) return;
    if (study.policy().configurable === false || !finitePoint(known.point) || !finitePoint(now)) return;
    const from = known.point;
    this._hooks.record({ undo: () => this._apply(pair, now, from), redo: () => this._apply(pair, from, now) }, true);
  }

  private _refresh(): void { for (const handle of this._handles.values()) handle.update(); }

  private _handle(id: unknown): AnchorHandle | undefined {
    return typeof id === 'string' && id.startsWith(PREFIX) ? this._handles.get(id) : undefined;
  }

  /**
   * The point a pointer means, as the study stores it: the time of the bar
   * under it, since a time between two bars matches none, and both halves
   * held inside the bounds the inputs declare. Null when either is missing.
   */
  private _point(handle: AnchorHandle, time: unknown, price: unknown): Point | null {
    if (typeof time !== 'number' || typeof price !== 'number' || !Number.isFinite(time) || !Number.isFinite(price)) return null;
    const dl = this._chart.dataLayer;
    const bar = dl.indexToTime(Math.round(dl.timeToIndexFloat(time))) ?? time;
    const study = this._study(handle.studyId);
    if (!study || !Number.isFinite(bar)) return null;
    const inputs = getIndicator(study.indicatorId).inputs;
    const bound = (key: string, value: number): number => {
      const input = inputs.find(item => item.key === key) as { min?: number; max?: number } | undefined;
      return Math.min(input?.max ?? Infinity, Math.max(input?.min ?? -Infinity, value));
    };
    return { time: bound(handle.timeKey, bar), price: bound(handle.priceKey, price) };
  }

  /**
   * Move one anchor to a point the way a drag release does, for a control of
   * the host's that sets the point another way (a pick): snapped, held in
   * bounds, refused for a study the user may not configure, and recorded as
   * one step. False when there is no such anchor, the move is refused, or the
   * study already holds the point.
   */
  public move(studyId: string, key: string, time: number, price: number): boolean {
    const handle = this._handles.get(`${PREFIX}${studyId}:${key}`);
    if (handle === undefined || !handle.editable || this._drag?.handle === handle) return false;
    const from = { time: handle.time, price: handle.price }, to = this._point(handle, time, price);
    if (to === null || (to.time === from.time && to.price === from.price) || !this._apply(handle, from, to)) return false;
    this._hooks.record({ undo: () => this._apply(handle, to, from), redo: () => this._apply(handle, from, to) }, false);
    return true;
  }

  private _onDragStart(p: { id?: unknown }): void {
    const handle = this._handle(p.id);
    if (handle === undefined || !handle.editable || !this._live()) return;
    this._drag = { handle, from: { time: handle.time, price: handle.price } };
  }

  private _onDrag(p: { id?: unknown; time?: unknown; price?: unknown }): void {
    const drag = this._drag;
    if (drag === null || drag.handle.id !== p.id) return;
    const at = this._point(drag.handle, p.time, p.price);
    if (at === null) return;
    drag.handle.time = at.time;
    drag.handle.price = at.price;
    drag.handle.update();
  }

  private _onDragEnd(p: { id?: unknown; time?: unknown; price?: unknown }): void {
    const drag = this._drag;
    if (drag === null || drag.handle.id !== p.id) return;
    this._drag = null;
    const { handle, from } = drag;
    const to = this._point(handle, p.time, p.price);
    const study = this._study(handle.studyId);
    if (to === null || study === undefined || (to.time === from.time && to.price === from.price)
      || !this._apply(handle, from, to)) {
      this._sync();
      return;
    }
    this._hooks.record({ undo: () => this._apply(handle, to, from), redo: () => this._apply(handle, from, to) }, false);
  }

  /**
   * Write `to` over `from` in one patch, as the user: a study the user may not
   * configure refuses it. False when the study is gone, refuses, or no longer
   * holds `from` (an edit elsewhere since), which is how an undo step that
   * stopped describing the chart lets the press go on to the one before it.
   */
  private _apply(pair: Pair, from: Point, to: Point): boolean {
    const study = this._study(pair.studyId);
    if (study === undefined) return false;
    const settings = study.settings();
    if (settings[pair.timeKey] !== from.time || settings[pair.priceKey] !== from.price) return false;
    // Noted before the write, so the sync it sets off finds nothing written from outside.
    const noted = this._points.get(`${PREFIX}${pair.studyId}:${pair.priceKey}`);
    const was = noted?.point;
    if (noted !== undefined && noted.study === study) noted.point = to;
    let written = false;
    try { written = study.setSettings({ [pair.timeKey]: to.time, [pair.priceKey]: to.price }); }
    catch { written = false; }
    if (!written && noted !== undefined && was !== undefined && noted.point === to) noted.point = was;
    return written;
  }

  private _cancelDrag(): void {
    if (this._drag === null) return;
    this._drag = null;
    this._sync();
  }
}
