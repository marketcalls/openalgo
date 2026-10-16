/**
 * Simulated intra-bar replay: a displayed bar that no finer bar covers forms over
 * steps along a path through its own prices, instead of landing whole.
 *
 * Asked for directly: a 5-minute bar should form over five steps even where the
 * feed keeps no 1-minute history for that day. Real finer bars still win where
 * they exist, the path never shows a price outside the bar, and the host is told
 * which steps are simulated because those prices were never traded.
 */
import { describe, it, expect } from 'vitest';
import { ReplayController, type ReplayChartHost } from '../src/replay/controller';
import { simulatedForming } from '../src/replay/forming';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';

const T0 = 1735689600;
const MIN = 60;
const FIVE = 5 * MIN;

function stubSeries(initial: readonly Bar[] = []): SeriesApi {
  let data: Bar[] = [...initial];
  return {
    setData: (b: readonly Bar[]) => { data = [...b]; },
    prependData: () => {},
    update: () => {},
    getData: () => data,
    applyOptions: () => {},
    remove: () => {},
    priceScale: () => ({}) as never,
    createMarkers: () => ({ setMarkers: () => {} }) as never,
  } as unknown as SeriesApi;
}

function host(): ReplayChartHost {
  return {
    emit: () => {},
    timeScale: { barSpacing: 8, rightOffset: 0, setBarSpacing: () => {}, setRightOffset: () => {} },
  } as unknown as ReplayChartHost;
}

/** A bar that opened near its low and closed up: the path goes to the low first. */
const up: Bar = { time: T0 + FIVE, open: 100, high: 110, low: 98, close: 108, volume: 1000 };
/** A bar that opened near its high and closed down: the path goes to the high first. */
const down: Bar = { time: T0 + 2 * FIVE, open: 110, high: 111, low: 100, close: 102, volume: 500 };
const first: Bar = { time: T0, open: 99, high: 101, low: 98, close: 100, volume: 800 };

/** Every bar shown while bar `index` forms, first step to close. */
function formation(bars: Bar[], index: number, steps: number, extra: Record<string, unknown> = {}): { shown: Bar[]; simulated: boolean[] } {
  const series = stubSeries(bars);
  const r = new ReplayController(host(), { series, bars, startIndex: index - 1, simulate: { steps }, ...extra });
  const shown: Bar[] = [];
  const simulated: boolean[] = [];
  try {
    for (let s = 0; s < steps; s++) {
      r.step();
      shown.push(series.getData()[index]);
      simulated.push(r.state().simulated);
      expect(r.state().bar).toEqual(shown[s]);
    }
  } finally { r.stop(); }
  return { shown, simulated };
}

describe('a bar without finer data forms over simulated steps', () => {
  it('takes the steps asked for and closes on the bar itself', () => {
    const { shown, simulated } = formation([first, up, down], 1, 5);
    expect(shown).toHaveLength(5);
    expect(shown[4]).toEqual(up);
    expect(simulated).toEqual([true, true, true, true, true]);
  });

  it('runs from the open to the nearer extreme, the other extreme and the close', () => {
    // Path 100 -> 98 -> 110 -> 108 is 16 points long; each of five steps covers 3.2.
    const { shown } = formation([first, up, down], 1, 5);
    const closes = shown.slice(0, 4).map((b) => +b.close.toFixed(6));
    expect(closes).toEqual([99.2, 102.4, 105.6, 108.8]);
    expect(shown[0]).toMatchObject({ open: 100, low: 98, high: 100 });
    expect(shown[3]).toMatchObject({ open: 100, low: 98, high: 108.8 });
    // Opened near its high and closed down: up to the high first.
    const fall = formation([first, up, down], 2, 4).shown;
    expect(fall[0].high).toBe(111);
    expect(fall[0].low).toBeGreaterThan(down.low);
  });

  it('keeps the open, widens only toward the real extremes and never passes them', () => {
    // A seeded walk of real-looking bars: every forming step of every bar.
    let seed = 7;
    const rnd = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const bars: Bar[] = [];
    let c = 1000;
    for (let i = 0; i < 60; i++) {
      const o = c * (1 + (rnd() - 0.5) * 0.004);
      c = o * (1 + (rnd() - 0.5) * 0.02);
      const h = Math.max(o, c) * (1 + rnd() * 0.006);
      const l = Math.min(o, c) * (1 - rnd() * 0.006);
      bars.push({ time: T0 + i * FIVE, open: o, high: h, low: l, close: c, volume: Math.round(1000 + rnd() * 5000) });
    }
    for (let i = 1; i < bars.length; i++) {
      const final = bars[i];
      let prev: Bar | null = null;
      for (let s = 0; s < 4; s++) {
        const b = simulatedForming(final, s, 5, undefined);
        expect(b.open).toBe(final.open);
        expect(b.high).toBeLessThanOrEqual(final.high);
        expect(b.low).toBeGreaterThanOrEqual(final.low);
        expect(Math.max(b.open, b.close)).toBeLessThanOrEqual(b.high);
        expect(Math.min(b.open, b.close)).toBeGreaterThanOrEqual(b.low);
        expect(b.volume).toBeLessThanOrEqual(final.volume as number);
        if (prev) {
          expect(b.high).toBeGreaterThanOrEqual(prev.high);
          expect(b.low).toBeLessThanOrEqual(prev.low);
          expect(b.volume).toBeGreaterThanOrEqual(prev.volume as number);
        }
        prev = b;
      }
    }
  });

  it('holds a flat bar flat', () => {
    const flat: Bar = { time: T0 + FIVE, open: 50, high: 50, low: 50, close: 50, volume: 10 };
    const { shown } = formation([first, flat], 1, 3);
    for (const b of shown) expect(b).toMatchObject({ open: 50, high: 50, low: 50, close: 50 });
  });

  it('shows the open interest known before the bar until the bar closes', () => {
    const withOi = [{ ...first, oi: 900 }, { ...up, oi: 950 }];
    const { shown } = formation(withOi, 1, 4);
    expect(shown.slice(0, 3).map((b) => b.oi)).toEqual([900, 900, 900]);
    expect(shown[3].oi).toBe(950);
  });

  it('lets real finer bars form the bars they cover and simulates only the rest', () => {
    const minutes: Bar[] = [];
    for (let m = 0; m < 5; m++) {
      const o = 100 + m * 0.5;
      minutes.push({ time: up.time + m * MIN, open: o, high: o + 0.8, low: o - 0.3, close: o + 0.4, volume: 150 });
    }
    const bars = [first, { ...up, open: 100, high: 102.8, low: 99.7, close: 102.4, volume: 750 }, down];
    const series = stubSeries(bars);
    const r = new ReplayController(host(), { series, bars, subBars: minutes, startIndex: 0, simulate: { steps: 3 } });
    try {
      r.step();
      expect(r.state()).toMatchObject({ index: 1, subSteps: 5, simulated: false });
      expect(series.getData()[1].close).toBe(minutes[0].close);
      for (let i = 0; i < 4; i++) r.step();
      r.step();
      expect(r.state()).toMatchObject({ index: 2, subIndex: 0, subSteps: 3, simulated: true });
    } finally { r.stop(); }
  });

  it('is off by default: a bar without finer data takes one step', () => {
    const series = stubSeries([first, up, down]);
    const r = new ReplayController(host(), { series, bars: [first, up, down], startIndex: 0 });
    try {
      r.step();
      expect(r.state()).toMatchObject({ index: 1, subIndex: 0, subSteps: 1, simulated: false });
      expect(series.getData()[1]).toEqual(up);
    } finally { r.stop(); }
  });

  it('refuses a step count it cannot use', () => {
    for (const steps of [1, 2.5, 241, Number.NaN]) {
      expect(() => new ReplayController(host(), { series: stubSeries([first, up]), bars: [first, up], simulate: { steps } }))
        .toThrow(/simulate.steps/);
    }
  });
});

describe('simulated steps on the availability clock', () => {
  const end = (seconds: number) => (b: Bar): number => b.time + seconds;

  it('places each step at an even share of the candle and closes at its end', () => {
    const bars = [first, up];
    const series = stubSeries(bars);
    const r = new ReplayController(host(), { series, bars, timing: { barEndTime: end(FIVE) }, simulate: { steps: 4 },
      startTime: T0 + FIVE });
    try {
      expect(r.timePoints()).toEqual([
        T0 + 75, T0 + 150, T0 + 225, T0 + FIVE,
        up.time + 75, up.time + 150, up.time + 225, up.time + FIVE,
      ]);
      r.seekTime(up.time + 160);
      expect(r.state()).toMatchObject({ index: 1, subIndex: 1, subSteps: 4, simulated: true });
      expect(series.getData()[1]).toEqual(simulatedForming(up, 1, 4, undefined));
      expect(series.getData()[1].open).toBe(up.open);
      r.seekTime(up.time + FIVE);
      expect(series.getData()[1]).toEqual(up);
    } finally { r.stop(); }
  });

  it('simulates a daily candle whose hourly bars open after the candle does', () => {
    // A daily candle stamped at midnight over a session that opens at 09:15: the
    // hourly bars leave no forming prefix, so the candle used to land whole.
    const HOUR = 3600, OPEN = 9 * HOUR + 15 * MIN, CLOSE = 15 * HOUR + 30 * MIN;
    const day0: Bar = { time: T0, open: 99, high: 101, low: 98, close: 100, volume: 800 };
    const day1: Bar = { time: T0 + 86400, open: 100, high: 110, low: 98, close: 108, volume: 1000 };
    const hours: Bar[] = [];
    for (let h = 0; h < 7; h++) {
      const o = 100 + h;
      hours.push({ time: day1.time + OPEN + h * HOUR, open: o, high: o + 1, low: o - 1, close: o + 1, volume: 100 });
    }
    const bars = [day0, day1];
    const series = stubSeries(bars);
    const r = new ReplayController(host(), { series, bars, subBars: hours, simulate: { steps: 7 },
      timing: { barEndTime: (b) => b.time + CLOSE, subBarEndTime: (b) => b.time + HOUR },
      startTime: day0.time + CLOSE });
    try {
      r.step();
      expect(r.state()).toMatchObject({ index: 1, subIndex: 0, subSteps: 7, simulated: true });
      expect(series.getData()[1].open).toBe(day1.open);
      for (let i = 0; i < 6; i++) r.step();
      expect(series.getData()[1]).toEqual(day1);
    } finally { r.stop(); }
  });

  it('keeps a real finer prefix rather than simulating a partly covered candle', () => {
    const bars = [first, up];
    const series = stubSeries(bars);
    const sub: Bar = { time: up.time, open: 100, high: 101, low: 99, close: 100.5, volume: 100 };
    const r = new ReplayController(host(), { series, bars, timing: { barEndTime: end(FIVE), subBarEndTime: end(MIN) },
      subBars: [sub], simulate: { steps: 4 }, startTime: up.time + MIN });
    try {
      expect(r.state()).toMatchObject({ index: 1, simulated: false });
      expect(series.getData()[1].close).toBe(100.5);
    } finally { r.stop(); }
  });
});
