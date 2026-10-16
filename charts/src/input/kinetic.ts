/**
 * Kinetic (inertial) scrolling (ARCHITECTURE.md §3.2, §7). After a flick, the
 * view keeps panning and decelerates under friction. Modelled with a closed
 * form so it is deterministic and unit-testable (no Date/rAF inside).
 *
 *   velocity(t) = v0 · e^(−k·t)
 *   distance(t) = (v0 / k) · (1 − e^(−k·t))     // total travel since start
 *
 * Distance is in pixels, t in ms. The caller samples `distanceAt(elapsed)`
 * each frame and pans by the delta since the previous sample.
 */
interface KineticOptions {
  /** Friction constant (1/ms). Larger = stops sooner. */
  friction: number;
  /** Stop when speed drops below this (px/ms). */
  minSpeed: number;
  /** Ignore flicks slower than this (px/ms). */
  triggerSpeed: number;
}

const DEFAULT_KINETIC_OPTIONS: KineticOptions = {
  friction: 0.0055,
  minSpeed: 0.02,
  triggerSpeed: 0.08,
};

export class KineticAnimation {
  private readonly _v0: number;
  private readonly _k: number;
  private readonly _minSpeed: number;
  private readonly _duration: number;

  public constructor(initialSpeed: number, options: Partial<KineticOptions> = {}) {
    const o = { ...DEFAULT_KINETIC_OPTIONS, ...options };
    this._v0 = initialSpeed;
    this._k = o.friction;
    this._minSpeed = o.minSpeed;
    // Time at which speed decays to minSpeed: e^(−k·t) = minSpeed/|v0|.
    const ratio = Math.abs(this._v0) > 0 ? this._minSpeed / Math.abs(this._v0) : 1;
    this._duration = ratio >= 1 ? 0 : -Math.log(ratio) / this._k;
  }

  /** Whether a flick this fast is worth animating. */
  public static shouldAnimate(speed: number, options: Partial<KineticOptions> = {}): boolean {
    const trigger = options.triggerSpeed ?? DEFAULT_KINETIC_OPTIONS.triggerSpeed;
    return Math.abs(speed) >= trigger;
  }

  /** Total signed distance travelled from start to `elapsedMs`. */
  public distanceAt(elapsedMs: number): number {
    const t = Math.min(Math.max(0, elapsedMs), this._duration);
    return (this._v0 / this._k) * (1 - Math.exp(-this._k * t));
  }

  public get durationMs(): number {
    return this._duration;
  }

  public finished(elapsedMs: number): boolean {
    return elapsedMs >= this._duration;
  }
}
