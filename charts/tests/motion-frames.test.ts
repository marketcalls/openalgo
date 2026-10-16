/**
 * One animation loop (ARCHITECTURE.md §3.2).
 *
 * The kinetic glide after a flick and the eased wheel zoom used to schedule
 * their own animation frames beside the render loop's. A step moved the time
 * scale inside its own callback and asked the render loop for a paint, which
 * ran in the frame after, so every frame of a glide asked for two callbacks
 * and showed the step before. These tests run a glide frame by frame and
 * check that each frame asks for exactly one callback and paints the time
 * scale that frame moved to.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { Pane } from '../src/core/pane';
import { KineticAnimation } from '../src/input/kinetic';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => {
  vi.restoreAllMocks();
  for (const chart of charts.splice(0)) chart.destroy();
});

/** A measured chart whose frames run by hand, counting every frame request. */
function fixture(options: Partial<ChartOptions> = {}) {
  let now = 0;
  let id = 0;
  let requests = 0;
  const queue = new Map<number, () => void>();
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, now: () => now,
    raf: {
      schedule: cb => { requests++; queue.set(++id, cb); return id; },
      cancel: key => { queue.delete(key); },
    },
    ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 500 }, (_, i) => ({
    time: 1_700_000_000 + i * 60, open: 100, high: 101 + (i % 5), low: 99 - (i % 3), close: 100.5,
  })));
  chart.setVisibleLogicalRange({ from: 300, to: 399 });
  /** Run one frame; returns how many callbacks it asked for. */
  const frame = (): number => {
    now += 16;
    const before = requests;
    const due = [...queue.entries()];
    for (const [key, cb] of due) if (queue.delete(key)) cb();
    return requests - before;
  };
  for (let i = 0; i < 50 && queue.size > 0; i++) frame();
  expect(queue.size).toBe(0);
  return { chart, frame, queue };
}

/**
 * Run frames until the chart asks for none, recording per frame how many
 * callbacks it asked for and what the price pane painted against `read`.
 */
function trace(chart: Chart, frame: () => number, read: () => number): { requests: number[]; painted: (number | null)[]; after: number[] } {
  const pane = chart.panes()[0];
  let painted: number | null = null;
  const spy = vi.spyOn(Pane.prototype, 'paintBase').mockImplementation(function (this: Pane) {
    if (this === pane) painted = read();
  });
  const out = { requests: [] as number[], painted: [] as (number | null)[], after: [] as number[] };
  for (let i = 0; i < 200; i++) {
    painted = null;
    const asked = frame();
    out.requests.push(asked);
    out.painted.push(painted);
    out.after.push(read());
    if (asked === 0) break;
  }
  spy.mockRestore();
  return out;
}

const wheel = (chart: Chart, deltaY: number): void => {
  (chart as unknown as { _onWheel: (e: unknown) => void })._onWheel({
    clientX: 400, clientY: 200, deltaX: 0, deltaY, deltaMode: 0, preventDefault() {},
  });
};

describe('the kinetic glide', () => {
  it('asks for one frame per frame and paints the step it made in that frame', () => {
    const f = fixture();
    const start = f.chart.timeScale.rightOffset;
    const spacing = f.chart.timeScale.barSpacing;
    (f.chart as unknown as { _startKinetic(v: number): void })._startKinetic(1.5);
    const t = trace(f.chart, f.frame, () => f.chart.timeScale.rightOffset);
    const moving = t.requests.slice(0, -1);
    expect(moving.length).toBeGreaterThan(10);
    expect(new Set(moving)).toEqual(new Set([1]));
    expect(t.requests[t.requests.length - 1]).toBe(0);
    // The frame that ends the glide is its last step, with no empty frame after it.
    expect(t.after[t.after.length - 1]).not.toBe(t.after[t.after.length - 2]);
    // Every frame that moved the view painted where it moved to.
    for (let i = 0; i < t.after.length; i++) {
      if (i === 0 || t.after[i] !== t.after[i - 1]) expect(t.painted[i]).toBe(t.after[i]);
    }
    // And it still travels exactly the closed-form distance.
    const anim = new KineticAnimation(1.5);
    expect(start - f.chart.timeScale.rightOffset).toBeCloseTo(anim.distanceAt(anim.durationMs) / spacing, 9);
  });

  it('leaves no frame asked for once stopped', () => {
    const f = fixture();
    (f.chart as unknown as { _startKinetic(v: number): void })._startKinetic(1.5);
    f.frame();
    f.chart.setVisibleLogicalRange({ from: 100, to: 199 });
    f.frame();
    expect(f.frame()).toBe(0);
    expect(f.queue.size).toBe(0);
    expect(f.chart.getVisibleLogicalRange()).toEqual({ from: 100, to: 199 });
  });
});

describe('the wheel-zoom glide', () => {
  it('asks for one frame per frame and paints the step it made in that frame', () => {
    const f = fixture({ animZoom: true });
    const before = f.chart.timeScale.barSpacing;
    const instant = fixture({ animZoom: false });
    wheel(instant.chart, -100);
    wheel(f.chart, -100);
    const t = trace(f.chart, f.frame, () => f.chart.timeScale.barSpacing);
    const moving = t.requests.slice(0, -1);
    expect(moving.length).toBeGreaterThan(5);
    expect(new Set(moving)).toEqual(new Set([1]));
    expect(t.after[t.after.length - 1]).not.toBe(t.after[t.after.length - 2]);
    for (let i = 0; i < t.after.length; i++) {
      if (i === 0 || t.after[i] !== t.after[i - 1]) expect(t.painted[i]).toBe(t.after[i]);
    }
    expect(f.chart.timeScale.barSpacing).toBeGreaterThan(before);
    expect(f.chart.timeScale.barSpacing).toBeCloseTo(instant.chart.timeScale.barSpacing, 9);
  });
});
