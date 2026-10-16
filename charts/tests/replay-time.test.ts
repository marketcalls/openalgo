import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import { addComparison } from '../src/compare/controller';

const T = 1700000000;
const bar = (time: number, close = 100, volume = 10, oi?: number): Bar => ({
  time: T + time, open: close - 1, high: close + 2, low: close - 2, close, volume,
  ...(oi === undefined ? {} : { oi }),
});
const end = (seconds: number) => (value: Bar) => value.time + seconds;
function loaded(data: Bar[]) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc,
    raf: { schedule: () => 0 }, pixelRatio: () => 1, shortcuts: false });
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(data);
  return { chart, series };
}

describe('availability-time replay', () => {
  it('keeps a later history empty until its first candle is available', () => {
    const data = [bar(300), bar(600)];
    const { chart, series } = loaded(data);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300) }, startTime: T + 120 });
    expect(series.getData()).toEqual([]);
    expect(replay.state()).toMatchObject({ index: -1, bar: null });
    replay.seekTime(T + 599);
    expect(series.getData()).toEqual([]);
    replay.seekTime(T + 600);
    expect(series.getData()).toEqual([data[0]]);
    replay.seekTime(T);
    expect(series.getData()).toEqual([]);
    replay.stop();
    expect(series.getData()).toEqual(data);
  });

  it('aligns different intervals by availability, not by opening or array index', () => {
    const fast = loaded([bar(0), bar(60), bar(120), bar(180), bar(240)]);
    const slow = loaded([bar(0), bar(300)]);
    const a = new ReplayController(fast.chart, { timing: { barEndTime: end(60) }, startTime: T + 120 });
    const b = new ReplayController(slow.chart, { timing: { barEndTime: end(300) }, startTime: T + 120 });
    expect(fast.series.getData()).toHaveLength(2);
    expect(slow.series.getData()).toHaveLength(0);
    a.seekTime(T + 300); b.seekTime(T + 300);
    expect(fast.series.getData()).toHaveLength(5);
    expect(slow.series.getData()).toHaveLength(1);
  });

  it('does not move forward on a backward or zero step before the first observation', () => {
    const { chart, series } = loaded([bar(300), bar(600)]);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300) }, startTime: T });
    replay.stepBack();
    expect(series.getData()).toEqual([]);
    replay.step(0);
    expect(series.getData()).toEqual([]);
    expect(replay.time()).toBe(T);
  });

  it('forms only from available finer bars and replaces the aggregate exactly at the declared end', () => {
    // The finer bars lie inside the displayed one, so each step is exactly their
    // aggregate; a feed that disagrees is held inside it (see the test below).
    const data: Bar[] = [{ time: T, open: 100, high: 106, low: 98, close: 104, volume: 1000, oi: 90 }, bar(300, 1100)];
    const subs = [bar(0, 101, 10, 0), bar(60, 103, 20, 7), bar(120, 102, 30)];
    const { chart, series } = loaded(data);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300), subBarEndTime: end(60) },
      subBars: subs, startTime: T + 60 });
    expect(replay.state()).toMatchObject({ index: 0, subIndex: 0, subSteps: 4 });
    expect(series.getData()).toEqual([subs[0]]);
    replay.seekTime(T + 120);
    expect(series.getData()[0]).toEqual({ time: T, open: 100, high: 105, low: 99, close: 103, volume: 30, oi: 7 });
    replay.seekTime(T + 299);
    expect(series.getData()[0]).toMatchObject({ close: 102, volume: 60, oi: 7 });
    expect(replay.time()).toBe(T + 299);
    replay.seekTime(T + 300);
    expect(series.getData()).toEqual([data[0]]);
    expect(replay.state()).toMatchObject({ subIndex: 3, subSteps: 4 });
    expect(subs[0]).toEqual(bar(0, 101, 10, 0));
    expect(data[0]).toEqual({ time: T, open: 100, high: 106, low: 98, close: 104, volume: 1000, oi: 90 });
  });

  it('forms inside the candle it closes on when the finer feed disagrees with it', () => {
    // The official open against the first minute's, minutes that run past the
    // candle's extremes and outweigh its volume: the forming bar keeps the open it
    // closes with and only widens toward the closed bar, never back from it.
    const final: Bar = { time: T, open: 100, high: 104, low: 98, close: 103, volume: 100 };
    const data = [final, bar(300, 110)];
    const subs: Bar[] = [
      { time: T, open: 100.4, high: 101, low: 97.5, close: 100.8, volume: 40 },
      { time: T + 60, open: 100.8, high: 104.6, low: 100.5, close: 104.2, volume: 50 },
      { time: T + 120, open: 104.2, high: 104.3, low: 102.5, close: 103.1, volume: 30 },
    ];
    const { chart, series } = loaded(data);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300), subBarEndTime: end(60) },
      subBars: subs, startTime: T + 60 });
    const seen: Bar[] = [];
    for (const at of [T + 60, T + 120, T + 180, T + 300]) {
      replay.seekTime(at);
      seen.push(series.getData()[0]);
      expect(replay.state().bar).toEqual(series.getData()[0]);
    }
    expect(seen[0]).toEqual({ time: T, open: 100, high: 101, low: 98, close: 100.8, volume: 40 });
    expect(seen[3]).toEqual(final);
    seen.forEach((b, k) => {
      expect(b.open).toBe(100);
      expect(b.high).toBeLessThanOrEqual(final.high);
      expect(b.low).toBeGreaterThanOrEqual(final.low);
      expect(b.volume).toBeLessThanOrEqual(100);
      if (k === 0) return;
      expect(b.high).toBeGreaterThanOrEqual(seen[k - 1].high);
      expect(b.low).toBeLessThanOrEqual(seen[k - 1].low);
      expect(b.volume).toBeGreaterThanOrEqual(seen[k - 1].volume as number);
    });
  });

  it('ignores finer bars crossing a bucket and does not stretch them over a history gap', () => {
    const data = [bar(0), bar(900)];
    const { chart, series } = loaded(data);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300), subBarEndTime: end(120) },
      subBars: [bar(240, 99.5), bar(600, 100.5), bar(900, 101)], startTime: T + 299 });
    expect(series.getData()).toEqual([]);
    expect(replay.timePoints()).toEqual([T + 300, T + 1020, T + 1200]);
    replay.seekTime(T + 800);
    expect(series.getData()).toEqual([data[0]]);
    replay.seekTime(T + 1020);
    expect(series.getData()[1].close).toBe(101);
  });

  it('withholds incomplete finer prefixes and keeps absent OI absent', () => {
    const { chart, series } = loaded([{ time: T, open: 100, high: 106, low: 98, close: 104, volume: 1000, oi: 90 }, bar(300, 1100)]);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300), subBarEndTime: end(60) },
      subBars: [bar(0, 101), bar(120, 800), bar(360, 900)], startTime: T + 240 });
    expect(series.getData()[0]).toMatchObject({ close: 101, high: 103 });
    expect(series.getData()[0]).not.toHaveProperty('oi');
    expect(replay.timePoints()).toEqual([T + 60, T + 300, T + 600]);
    replay.seekTime(T + 500);
    expect(series.getData()).toHaveLength(1);
  });

  it('cuts independent followers and comparisons before notifying the host', () => {
    const data = [bar(0, 999), bar(300, 1100)];
    const { chart, series } = loaded(data);
    const follower = chart.addSeries('histogram', { priceScaleId: '' });
    follower.setData(data);
    const comparison = addComparison(chart, { symbol: 'ALT', bars: data });
    const frames: { primary: number; follower: number; comparison: boolean }[] = [];
    const replay = new ReplayController(chart, { series: [series, follower],
      timing: { barEndTime: end(300), subBarEndTime: end(60) }, subBars: [bar(0, 101)], startTime: T,
      onFrame: () => frames.push({ primary: series.getData().length, follower: follower.getData().length,
        comparison: comparison.barAt(T) !== null }) });
    expect(frames[frames.length - 1]).toEqual({ primary: 0, follower: 0, comparison: false });
    replay.seekTime(T + 60);
    expect(frames[frames.length - 1]).toEqual({ primary: 1, follower: 0, comparison: false });
    replay.seekTime(T + 300);
    expect(frames[frames.length - 1]).toEqual({ primary: 1, follower: 1, comparison: true });
    replay.stop();
    expect(follower.getData()).toEqual(data);
    expect(comparison.barAt(T + 300)).not.toBeNull();
  });

  it('prepares without changing data and restores its original viewport on stop', () => {
    const data = [bar(0), bar(300)];
    const { chart, series } = loaded(data);
    chart.timeScale.setBarSpacing(9); chart.timeScale.setRightOffset(4);
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300) }, autoStart: false });
    expect(series.getData()).toEqual(data);
    replay.seekTime(T + 300);
    chart.timeScale.setBarSpacing(12); chart.timeScale.setRightOffset(0);
    replay.stop(); replay.stop();
    expect(series.getData()).toEqual(data);
    expect(chart.timeScale.barSpacing).toBe(9);
    expect(chart.timeScale.rightOffset).toBe(4);
    replay.seekTime(T + 300);
    expect(series.getData()).toEqual([data[0]]);
  });

  it('steps over observations, seeks complete bars and drives them with the existing playback clock', () => {
    const { chart } = loaded([bar(0, 200), bar(300, 300)]);
    let now = 0, tick: (() => void) | undefined, cancelled = 0;
    const replay = new ReplayController(chart, { timing: { barEndTime: end(300), subBarEndTime: end(60) },
      subBars: [bar(0), bar(60), bar(300)], startTime: T, now: () => now,
      scheduler: callback => { tick = callback; return () => { cancelled++; }; } });
    replay.step(); expect(replay.time()).toBe(T + 60);
    replay.step(); expect(replay.time()).toBe(T + 120);
    replay.stepBack(); expect(replay.time()).toBe(T + 60);
    replay.seek(0); expect(replay.time()).toBe(T + 300);
    replay.play({ speed: 2 });
    now = 500; tick!(); expect(replay.time()).toBe(T + 360);
    now = 1000; tick!(); expect(replay.time()).toBe(T + 600);
    expect(replay.state().playing).toBe(false);
    expect(cancelled).toBe(1);
  });

  it.each([NaN, Infinity, T - 1, T + 601])('rejects invalid/overlapping end %s before changing the chart', value => {
    const data = [bar(0), bar(300)];
    const { chart, series } = loaded(data);
    expect(() => new ReplayController(chart, { timing: { barEndTime: () => value } })).toThrow(/replay.*time/i);
    expect(series.getData()).toEqual(data);
  });

  it('requires explicit finer availability and timing for time-based calls', () => {
    const data = [bar(0), bar(300)];
    const { chart, series } = loaded(data);
    expect(() => new ReplayController(chart, { timing: { barEndTime: end(300) }, subBars: [bar(0)] })).toThrow(/subBarEndTime/);
    expect(series.getData()).toEqual(data);
    const legacy = new ReplayController(chart);
    expect(() => legacy.seekTime(T + 60)).toThrow(/timing/);
    legacy.stop();
    expect(() => new ReplayController(chart, { startTime: T + 60 })).toThrow(/timing/);
  });

  it('accepts explicitly close-stamped bars and an empty history', () => {
    const { chart, series } = loaded([bar(0), bar(300)]);
    const replay = new ReplayController(chart, { timing: { barEndTime: value => value.time }, startTime: T });
    expect(series.getData()).toHaveLength(1);
    expect(() => replay.seekTime(NaN)).toThrow(/time/);
    const empty = loaded([]);
    const blank = new ReplayController(empty.chart, { timing: { barEndTime: end(60) }, startTime: T });
    expect(blank.state().bar).toBeNull();
    expect(blank.timePoints()).toEqual([]);
    blank.play(); blank.step(); blank.stop();
    expect(empty.series.getData()).toEqual([]);
  });
});
