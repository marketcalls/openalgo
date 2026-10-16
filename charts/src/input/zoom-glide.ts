/**
 * Eased wheel zoom (ARCHITECTURE.md §3.2, §7). A wheel tick used to land its
 * whole zoom step on one frame, which reads as the chart jumping rather than
 * moving. This spreads the same step over a short exponential approach, the
 * counterpart to `KineticAnimation` (input/kinetic.ts) for the other half of the viewport.
 *
 *   applied(t) = base + (target − base) · (1 − e^(−t/tau))
 *
 * The work is done in LOG space and the caller exponentiates the per-frame
 * delta, because zoom composes multiplicatively: two 1.1x steps are 1.21x, not
 * 1.2x. Easing the multiplier directly would make the first half of a glide
 * cover more zoom than the second, and a glide interrupted midway would land on
 * a different scale than one left alone.
 *
 * Closed form, so it is deterministic and unit-testable with no Date or rAF
 * inside: the caller samples {@link ZoomGlide.appliedAt} each frame and zooms by
 * the delta since its previous sample.
 */
export interface ZoomGlideOptions {
  /**
   * Time constant in ms. The glide covers ~63% of the distance remaining after
   * each rebase in one tau, and is cut off at `stopFraction`.
   */
  tau: number;
  /** Stop once this much of the remaining distance has been applied. */
  stopFraction: number;
  /**
   * Skip the animation for a step smaller than this, in log units. Below it the
   * glide is a handful of sub-pixel frames nobody can see, and scheduling them
   * costs more than the step is worth.
   */
  minLogStep: number;
}

export const DEFAULT_ZOOM_GLIDE_OPTIONS: ZoomGlideOptions = {
  tau: 55,
  stopFraction: 0.995,
  // A hair under one wheel notch (ln(1.1) = 0.0953), so a single tick still
  // animates but a trackpad's smallest increments do not.
  minLogStep: 0.02,
};

export class ZoomGlide {
  /** Log-space zoom already applied at the last rebase: where the curve starts. */
  private _base = 0;
  /** Log-space zoom to end on, measured from the glide's origin. */
  private _target: number;
  /** Elapsed-ms reading of the last rebase, so the curve restarts from there. */
  private _epoch = 0;
  private readonly _tau: number;
  private readonly _duration: number;

  /** @param totalLogFactor Signed log-space zoom to cover, `Math.log(factor)`. */
  public constructor(totalLogFactor: number, options: Partial<ZoomGlideOptions> = {}) {
    const o = { ...DEFAULT_ZOOM_GLIDE_OPTIONS, ...options };
    this._target = totalLogFactor;
    this._tau = o.tau;
    // t at which (1 − e^(−t/tau)) reaches stopFraction.
    this._duration = -Math.log(1 - o.stopFraction) * o.tau;
  }

  /**
   * The fraction of a step to apply on the input event itself, before any
   * frame runs.
   *
   * A glide that starts at zero adds a frame of input latency to every wheel
   * tick, and leaves `barSpacing` reading its old value to anything that looks
   * synchronously after the event. Both are worse than the jump the easing was
   * meant to fix. The lead is exactly what the first frame would have applied
   * anyway (one 60fps frame of the curve), so the chart responds instantly and
   * the remainder still eases.
   */
  public static leadFraction(options: Partial<ZoomGlideOptions> = {}): number {
    const tau = options.tau ?? DEFAULT_ZOOM_GLIDE_OPTIONS.tau;
    return 1 - Math.exp(-(1000 / 60) / tau);
  }

  /** Whether a step this large is worth animating rather than applying at once. */
  public static shouldAnimate(totalLogFactor: number, options: Partial<ZoomGlideOptions> = {}): boolean {
    const min = options.minLogStep ?? DEFAULT_ZOOM_GLIDE_OPTIONS.minLogStep;
    return Math.abs(totalLogFactor) >= min;
  }

  /**
   * Fold another wheel tick into a glide already running.
   *
   * The target ACCUMULATES, so spinning the wheel fast covers the sum of its
   * notches rather than only the last one, and scrolling back the other way
   * genuinely reverses (five notches out after one notch in ends four notches
   * out, which is what the user asked for).
   *
   * The curve is rebased rather than merely retargeted: it restarts from what
   * has already been applied, at the current time. Without that, changing the
   * target changes `appliedAt` for times ALREADY sampled, so the next frame
   * computes a delta against a curve the caller never rode and the chart
   * jumps, most visibly when a reversal flips the target's sign. Rebasing does
   * not make a stream of ticks crawl, because each tick also pushes the target
   * further away: it is progress toward a FIXED target that resetting would
   * stall.
   *
   * @param appliedSoFar What the caller has already zoomed by, in log units.
   * @param elapsedMs    The clock reading this rebase happens at.
   */
  public add(extraLogFactor: number, appliedSoFar: number, elapsedMs: number): void {
    this._base = appliedSoFar;
    this._target += extraLogFactor;
    this._epoch = elapsedMs;
  }

  /** Signed log-space zoom applied from the glide's origin up to `elapsedMs`. */
  public appliedAt(elapsedMs: number): number {
    const t = elapsedMs - this._epoch;
    if (t <= 0) return this._base;
    if (t >= this._duration) return this._target;
    return this._base + (this._target - this._base) * (1 - Math.exp(-t / this._tau));
  }

  /** Where the glide ends: the accumulated total, from the origin. */
  public get totalLogFactor(): number {
    return this._target;
  }

  public get durationMs(): number {
    return this._duration;
  }

  public finished(elapsedMs: number): boolean {
    return elapsedMs - this._epoch >= this._duration;
  }
}
