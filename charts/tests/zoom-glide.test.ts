/**
 * Eased wheel zoom (§3.2, §7).
 *
 * The load-bearing property is that easing must not change WHERE a zoom ends
 * up, only how it gets there: a chart that lands on a different bar spacing
 * depending on whether the animation was interrupted is worse than one that
 * jumps. Hence the exact-landing and compounding assertions below.
 */
import { describe, it, expect } from 'vitest';
import { ZoomGlide, DEFAULT_ZOOM_GLIDE_OPTIONS } from '../src/input/zoom-glide';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

const NOTCH = Math.log(1.1); // one wheel notch

describe('ZoomGlide', () => {
  it('starts at zero and lands exactly on the total', () => {
    const g = new ZoomGlide(NOTCH);
    expect(g.appliedAt(0)).toBe(0);
    expect(g.appliedAt(g.durationMs)).toBeCloseTo(NOTCH, 12);
    // Past the end it stays put rather than overshooting.
    expect(g.appliedAt(g.durationMs * 10)).toBeCloseTo(NOTCH, 12);
  });

  it('is monotonic and decelerating', () => {
    const g = new ZoomGlide(NOTCH);
    let prev = 0;
    let prevDelta = Infinity;
    for (let t = 5; t <= g.durationMs; t += 5) {
      const v = g.appliedAt(t);
      const delta = v - prev;
      expect(v).toBeGreaterThanOrEqual(prev);
      expect(delta).toBeLessThanOrEqual(prevDelta + 1e-12);
      prev = v;
      prevDelta = delta;
    }
  });

  it('eases in log space, so two notches compose multiplicatively', () => {
    // Easing the MULTIPLIER directly would make a half-finished 1.21x glide sit
    // at 1.105x; in log space it sits at sqrt(1.21) = 1.1x, which is what "half
    // way through two notches" should mean.
    const g = new ZoomGlide(NOTCH * 2);
    const half = g.totalLogFactor / 2;
    // Find the time at which half the log distance is covered.
    let t = 0;
    while (g.appliedAt(t) < half && t < g.durationMs) t += 0.1;
    expect(Math.exp(g.appliedAt(t))).toBeCloseTo(1.1, 2);
  });

  it('zooms out symmetrically', () => {
    const out = new ZoomGlide(-NOTCH);
    expect(out.appliedAt(out.durationMs)).toBeCloseTo(-NOTCH, 12);
    expect(Math.exp(out.appliedAt(out.durationMs))).toBeCloseTo(1 / 1.1, 12);
  });

  it('skips the animation for a step too small to see', () => {
    expect(ZoomGlide.shouldAnimate(NOTCH)).toBe(true);
    expect(ZoomGlide.shouldAnimate(DEFAULT_ZOOM_GLIDE_OPTIONS.minLogStep / 2)).toBe(false);
    expect(ZoomGlide.shouldAnimate(-DEFAULT_ZOOM_GLIDE_OPTIONS.minLogStep / 2)).toBe(false);
  });

  describe('add', () => {
    it('accumulates ticks instead of replacing them', () => {
      const g = new ZoomGlide(NOTCH);
      g.add(NOTCH, 0, 0);
      expect(g.totalLogFactor).toBeCloseTo(NOTCH * 2, 12);
      // A fast scroll therefore covers the sum of its notches.
      expect(g.appliedAt(g.durationMs)).toBeCloseTo(NOTCH * 2, 12);
    });

    it('is continuous across a rebase, so no frame sees a jump', () => {
      // The delta the caller applies each frame is appliedAt(now) minus what it
      // applied last frame. If a tick moved the curve under times already
      // sampled, that delta would be against a curve nobody rode, and the chart
      // would jump. Adding must leave appliedAt(now) exactly where it was.
      const g = new ZoomGlide(NOTCH);
      const mid = g.appliedAt(20);
      g.add(NOTCH, mid, 20);
      expect(g.appliedAt(20)).toBeCloseTo(mid, 12);
      // And it keeps moving from there rather than stalling.
      expect(g.appliedAt(30)).toBeGreaterThan(mid);
    });

    it('stays continuous even when a tick reverses direction', () => {
      const g = new ZoomGlide(NOTCH);
      const applied = g.appliedAt(30);
      g.add(-NOTCH * 5, applied, 30);
      // No jump at the rebase instant...
      expect(g.appliedAt(30)).toBeCloseTo(applied, 12);
      // ...and it genuinely reverses: one notch in then five out is four out.
      expect(g.totalLogFactor).toBeCloseTo(-NOTCH * 4, 12);
      expect(g.appliedAt(30 + g.durationMs)).toBeCloseTo(-NOTCH * 4, 12);
    });
  });
});

describe('chart wheel zoom', () => {
  /**
   * A MEASURED chart (applySize, per CLAUDE.md: without it every price scale
   * sits on its 0..1 placeholder) with a controllable clock and a deferred
   * scheduler, so a glide can be stepped frame by frame.
   */
  function makeChart(options: Record<string, unknown> = {}): { chart: Chart; tick: (ms: number) => void } {
    let now = 0;
    let pending: Array<() => void> = [];
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      now: () => now,
      raf: {
        schedule: (cb: () => void) => {
          pending.push(cb);
          return pending.length;
        },
        cancel: () => {},
      },
      ...options,
    });
    chart.applySize(800, 600);
    // Drain the constructor's own remeasure frame before any assertions.
    const drain = (): void => {
      const due = pending;
      pending = [];
      for (const cb of due) cb();
    };
    drain();
    return {
      chart,
      tick: (ms: number): void => {
        now += ms;
        drain();
      },
    };
  }

  /** Drive the handler directly: the fake DOM does not synthesise WheelEvent. */
  const wheel = (chart: Chart, deltaY: number): void => {
    (chart as unknown as { _onWheel: (e: unknown) => void })._onWheel({
      deltaY,
      preventDefault: () => undefined,
      clientX: 400,
      clientY: 300,
    });
  };

  it('moves on the event itself, with no frame of input latency', () => {
    // A glide that starts at zero leaves barSpacing reading its old value to
    // anything that looks synchronously after the wheel. The React terminal
    // does exactly that, so the lead is a compatibility property, not a nicety.
    const { chart } = makeChart({ animZoom: true });
    const before = chart.timeScale.barSpacing;
    wheel(chart, -100);
    expect(chart.timeScale.barSpacing).toBeGreaterThan(before);
  });

  it('reaches the same bar spacing eased as it does instantly', () => {
    const eased = makeChart({ animZoom: true });
    const instant = makeChart({ animZoom: false });
    const before = instant.chart.timeScale.barSpacing;

    wheel(instant.chart, -100);
    const target = instant.chart.timeScale.barSpacing;
    expect(target).toBeGreaterThan(before);

    wheel(eased.chart, -100);
    // Part-way through, it is on its way but not yet there.
    eased.tick(16);
    expect(eased.chart.timeScale.barSpacing).toBeGreaterThan(before);
    expect(eased.chart.timeScale.barSpacing).toBeLessThan(target);

    // Run the glide out; it must land on exactly the instant result.
    for (let i = 0; i < 200; i++) eased.tick(16);
    expect(eased.chart.timeScale.barSpacing).toBeCloseTo(target, 9);
  });

  it('applies the step on one frame when animation is off', () => {
    const { chart } = makeChart({ animZoom: false });
    const before = chart.timeScale.barSpacing;
    wheel(chart, -100);
    expect(chart.timeScale.barSpacing).toBeCloseTo(before * 1.1, 9);
  });

  it('anchors on the right edge when asked to', () => {
    const cursor = makeChart({ animZoom: false, zoomAnchor: 'cursor' });
    const right = makeChart({ animZoom: false, zoomAnchor: 'right' });
    wheel(cursor.chart, -100);
    wheel(right.chart, -100);
    // Same zoom amount either way; the anchor decides what stays put, which
    // shows up as a different right offset.
    expect(right.chart.timeScale.barSpacing).toBeCloseTo(cursor.chart.timeScale.barSpacing, 9);
    expect(right.chart.timeScale.rightOffset).not.toBeCloseTo(cursor.chart.timeScale.rightOffset, 6);
  });

  it('lets wheel events that land between two frames move only the target, never the chart again', () => {
    // A fast wheel delivers several events per frame. Each used to apply a
    // slice of the whole remaining zoom on the event, so three of them in one
    // frame painted about 60 percent of the debt at once: the jump the easing
    // exists to prevent.
    const { chart } = makeChart({ animZoom: true });
    const before = chart.timeScale.barSpacing;
    wheel(chart, -100);
    const afterFirst = chart.timeScale.barSpacing;
    expect(afterFirst).toBeGreaterThan(before);
    wheel(chart, -100);
    wheel(chart, -100);
    expect(chart.timeScale.barSpacing).toBe(afterFirst);
  });

  it('covers the same zoom per second at any frame rate', () => {
    // The step per frame follows the real frame time, so a 120Hz screen is not
    // twice as fast as a 60Hz one.
    const slow = makeChart({ animZoom: true });
    const fast = makeChart({ animZoom: true });
    wheel(slow.chart, -300);
    wheel(fast.chart, -300);
    for (let i = 0; i < 6; i++) slow.tick(16);
    for (let i = 0; i < 12; i++) fast.tick(8);
    const a = Math.log(slow.chart.timeScale.barSpacing);
    const b = Math.log(fast.chart.timeScale.barSpacing);
    expect(Math.abs(a - b)).toBeLessThan(1e-9);
  });

  it('eases a trackpad step too small to see on its own', () => {
    // Small steps used to land whole on the event, so a two-finger zoom tracked
    // the raw event jitter while a wheel notch glided.
    const eased = makeChart({ animZoom: true });
    const instant = makeChart({ animZoom: false });
    wheel(eased.chart, -4);
    wheel(instant.chart, -4);
    const target = instant.chart.timeScale.barSpacing;
    expect(eased.chart.timeScale.barSpacing).toBeLessThan(target);
    for (let i = 0; i < 100; i++) eased.tick(16);
    expect(eased.chart.timeScale.barSpacing).toBeCloseTo(target, 9);
  });

  it('starts each frame from where the last left off, with no spike on a new notch', () => {
    // Every notch used to restart its curve and apply a slice on the event,
    // so the frame after each notch jumped: measured at 5.6 times the frame
    // before it, a sawtooth. Chasing one target the jump is 2.8 times, with
    // notches every 48ms painted at 60fps.
    const { chart, tick } = makeChart({ animZoom: true });
    const moves: number[] = [];
    let last = chart.timeScale.barSpacing;
    for (let notch = 0; notch < 6; notch++) {
      wheel(chart, -100);
      for (let i = 0; i < 3; i++) {
        tick(16);
        const now = chart.timeScale.barSpacing;
        moves.push(Math.log(now / last));
        last = now;
      }
    }
    const jumps = moves.slice(3).map((m, i) => m / moves[i + 2]!);
    expect(Math.max(...jumps)).toBeLessThan(3.5);
  });
});
