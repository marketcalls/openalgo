/**
 * The chart's navigation motion: the kinetic glide after a flick, the eased
 * wheel zoom, and the autoscale easing either one starts.
 *
 * Its own module because this state (the glides in flight, their clocks and
 * frame counts) belongs to these few methods alone. The chart reaches it
 * through `Chart._motion`, and the motion reaches the chart through
 * `MotionHost`. Members the chart still calls or reads are public on this
 * internal class; no entry point exports the class and the chart holds it in
 * a private field, so none of it reaches the published declarations.
 *
 * Neither glide schedules a frame of its own. The render loop steps them at
 * the top of its frame (`_step`), before it takes the frame's mask, so the
 * paint in that frame shows the step it made. On animation frames of their
 * own, each step asked the loop for a paint that ran in the frame after, so
 * the chart showed every step a frame late and asked for two callbacks per
 * frame.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Chart } from './chart';
import { KineticAnimation } from '../input/kinetic';
import { ZoomGlide } from '../input/zoom-glide';

/** Hard ceiling on glide frames, about ten seconds at 60fps. See `_stepKinetic`. */
const KINETIC_MAX_FRAMES = 600;
/** Same ceiling, same reason, for the zoom glide (see `_stepKinetic`). */
const ZOOM_GLIDE_MAX_FRAMES = 600;

/**
 * The wheel zoom's time constant, in ms: each frame closes 1 - e^(-dt/tau)
 * of the distance still to go, so about 63 percent in one tau.
 */
const ZOOM_CHASE_TAU = 70;
/** A frame gap longer than this (a hidden tab, a stall) counts as this long, so the zoom never leaps. */
const ZOOM_CHASE_MAX_DT = 64;
/** Close enough, in log units (a tenth of a percent of bar spacing): land on the target. */
const ZOOM_CHASE_LAND = 1e-3;

/**
 * The slice of the chart the motion reads and drives. The chart itself is the
 * host: each member carries the name and the type of the chart's own, so the
 * moved code reads as it did in chart.ts, and a member the chart renames or
 * retypes fails to compile here.
 */
export interface MotionHost {
  readonly _navigation: Chart['_navigation'];
  readonly _destroyed: Chart['_destroyed'];
  readonly _loop: Chart['_loop'];
  readonly _timeScale: Chart['_timeScale'];
  _now: Chart['_now'];
  _mutateTimeScale: Chart['_mutateTimeScale'];
  _maybeLoadHistory: Chart['_maybeLoadHistory'];
  invalidate: Chart['invalidate'];
  _emitViewport: Chart['_emitViewport'];
}

/** A kinetic glide in flight: its curve, its clock, how far it has moved the view and the frames it has used. */
interface KineticGlide {
  readonly anim: KineticAnimation;
  readonly start: number;
  travelled: number;
  frames: number;
}

export class ChartMotion {
  private readonly _host: MotionHost;
  private _kinetic: KineticGlide | null = null;
  /**
   * The bar spacing the wheel zoom is heading for, or null with none in
   * flight. Every wheel event moves this target and nothing else; the frames
   * chase it. Applying part of each event on the event itself, and starting a
   * fresh curve per event, made a fast wheel land several bites in one
   * painted frame and gave every notch a jolt: the chase has neither.
   */
  public _zoomTarget: number | null = null;
  private _zoomFocus = 0;
  private _zoomFrames = 0;
  private _zoomLastTime = 0;
  private readonly _animAutoscale: boolean;
  public _autoscaleTime: number | null = null;
  public _autoscaleFrames = 0;
  public _navigationEpoch = 0;

  public constructor(host: MotionHost, animAutoscale: boolean) {
    this._host = host;
    this._animAutoscale = animAutoscale;
  }

  /**
   * Advance both glides by one frame. The render loop calls this before it
   * takes the frame's mask, so what a step invalidates is painted in the same
   * frame. Returns whether a glide is still running: the loop then asks for
   * the next frame once this one is painted.
   */
  public _step(): boolean {
    this._stepZoomGlide();
    this._stepKinetic();
    return this._zoomTarget !== null || this._kinetic !== null;
  }

  /** One zoom step, applied now. Shared by the instant path and each glide frame. */
  public _applyZoom(focusX: number, logFactor: number): void {
    if (this._host._navigation.zoomEnabled === false) return;
    this._beginAutoscaleMotion();
    this._host._mutateTimeScale(() => this._host._timeScale.zoomAtX(focusX, Math.exp(logFactor)));
    this._host._maybeLoadHistory();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emitViewport('zoom');
  }

  /** The part of the wheel zoom not painted yet, as a log factor; 0 with none in flight. */
  public _remainingZoom(): number {
    return this._zoomTarget === null ? 0 : Math.log(this._zoomTarget / this._host._timeScale.barSpacing);
  }

  /**
   * Fold one wheel step into the zoom in flight, or start one.
   *
   * The target accumulates, so a fast spin covers the sum of its notches and a
   * reversal genuinely reverses, and it is bounded here so input at a spacing
   * limit leaves no invisible debt to unwind. Only a zoom that starts from
   * rest moves on the event itself, by what its first frame would have moved
   * (`ZoomGlide.leadFraction`): the chart answers the first notch at once, and
   * the notches that follow only move the target.
   */
  public _retargetZoom(focusX: number, logFactor: number): void {
    if (this._host._navigation.zoomEnabled === false) return;
    const ts = this._host._timeScale;
    const fresh = this._zoomTarget === null;
    const target = ts.constrainBarSpacing((fresh ? ts.barSpacing : this._zoomTarget!) * Math.exp(logFactor)); // set when not fresh
    this._zoomFocus = focusX;
    const remaining = Math.log(target / ts.barSpacing);
    if (remaining === 0) { this._zoomTarget = null; return; }
    this._zoomTarget = target;
    if (fresh) {
      this._zoomLastTime = this._host._now();
      this._zoomFrames = 0;
      const epoch = this._navigationEpoch;
      this._applyZoom(focusX, remaining * ZoomGlide.leadFraction({ tau: ZOOM_CHASE_TAU }));
      if (this._host._destroyed || epoch !== this._navigationEpoch || this._zoomTarget !== target) return;
    }
    this._host._loop.requestFrame();
  }

  private _stepZoomGlide(): void {
    const target = this._zoomTarget;
    if (target === null) return;
    // Cleared rather than left behind: a target still set keeps the loop asking for frames.
    if (this._host._destroyed || this._host._navigation.zoomEnabled === false) { this._zoomTarget = null; return; }
    const ts = this._host._timeScale;
    const now = this._host._now();
    // The real frame time, so the zoom covers the same ground per second at 60Hz and 144Hz.
    const dt = Math.min(ZOOM_CHASE_MAX_DT, Math.max(0, now - this._zoomLastTime));
    this._zoomLastTime = now;
    const remaining = Math.log(target / ts.barSpacing);
    const land = Math.abs(remaining) < ZOOM_CHASE_LAND || ++this._zoomFrames >= ZOOM_GLIDE_MAX_FRAMES;
    const step = land ? remaining : remaining * (1 - Math.exp(-dt / ZOOM_CHASE_TAU));
    const before = ts.barSpacing;
    // A frame that moved nothing still costs a full-pane repaint, so skip it.
    if (step !== 0) this._applyZoom(this._zoomFocus, step);
    if (this._zoomTarget !== target || this._host._destroyed) return;
    // Landed, or held at a spacing limit the target was not clamped to (the
    // range a host set since): either way there is nothing left to chase.
    if (land || (step !== 0 && ts.barSpacing === before)) this._zoomTarget = null;
  }

  public _beginAutoscaleMotion(): void {
    if (!this._animAutoscale || this._autoscaleTime !== null) return;
    this._autoscaleTime = this._host._now() - 16;
    this._autoscaleFrames = 0;
  }

  /**
   * How far this frame's autoscale moves each pane toward its measured range:
   * the whole way unless a navigation motion started an easing, and the whole
   * way once the easing has run 90 frames, so it always lands.
   */
  public _autoscaleFraction(): number {
    const now = this._host._now();
    const fraction = this._autoscaleTime === null || ++this._autoscaleFrames >= 90
      ? 1 : 1 - Math.exp(-Math.max(1, now - this._autoscaleTime) / 80);
    if (this._autoscaleTime !== null) this._autoscaleTime = now;
    return fraction;
  }

  public _stopNavigationMotion(): void {
    this._navigationEpoch++;
    this._stopZoomGlide();
    this._stopKinetic();
    this._autoscaleTime = null;
  }

  /** Stop what a navigation policy just switched off: panning, zooming or both. */
  public _stopDisabled(pan: boolean, zoom: boolean): void {
    if (zoom) {
      this._navigationEpoch++;
      this._stopZoomGlide();
    }
    if (pan) this._stopKinetic();
    this._autoscaleTime = null;
  }

  public _stopZoomGlide(): void {
    this._zoomTarget = null;
  }

  /** Coast after a flick: the render loop moves the view on each frame until the glide stops. */
  public _startKinetic(velocity: number): void {
    if (this._host._navigation.panEnabled === false) return;
    this._stopKinetic();
    const anim = new KineticAnimation(velocity);
    if (anim.durationMs <= 0) return;
    this._kinetic = { anim, start: this._host._now(), travelled: 0, frames: 0 };
    this._host._loop.requestFrame();
  }

  private _stepKinetic(): void {
    const glide = this._kinetic;
    if (glide === null) return;
    if (this._host._destroyed || this._host._navigation.panEnabled === false) { this._kinetic = null; return; }
    const elapsed = this._host._now() - glide.start;
    const dist = glide.anim.distanceAt(elapsed);
    const delta = dist - glide.travelled;
    glide.travelled = dist;
    this._beginAutoscaleMotion();
    this._host._mutateTimeScale(() => this._host._timeScale.setRightOffset(this._host._timeScale.rightOffset - delta / this._host._timeScale.barSpacing));
    this._host._maybeLoadHistory();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    // The glide is a pan like any other and has to say so. Without this the
    // drag emits its last event at the moment the pointer lifts, and everything
    // downstream (a linked chart, a host tracking the visible range) is left on
    // that window while this one coasts on for another few hundred milliseconds.
    this._host._emitViewport('pan');
    // A frame budget as well as a time budget. The glide is bounded in time,
    // but the loop asks for the next frame through the injected scheduler, and
    // a host may run that synchronously with a clock that does not move (the
    // test harness does, deliberately, so a repaint is observable inline).
    // Time-based termination alone then never fires and the frames recurse
    // until the stack goes. A glide is well under a second, so ten seconds of
    // frames is a ceiling no real animation reaches.
    if (this._kinetic === glide && (glide.anim.finished(elapsed) || ++glide.frames >= KINETIC_MAX_FRAMES)) this._kinetic = null;
  }

  public _stopKinetic(): void {
    this._kinetic = null;
  }
}
