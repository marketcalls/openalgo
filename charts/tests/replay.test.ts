import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins
import { Chart } from '../src/core/chart';
import { ReplayController, type ReplayScheduler, type ReplayState } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';

const bars = (n: number, offset = 0): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin((i + offset) / 5) * 10 + i * 0.05;
    return { time: 1700000000 + i * 60, open: c - 0.2, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    raf: { schedule: () => 0 },
    pixelRatio: () => 1,
    shortcuts: false,
  });
  chart.applySize(800, 600);
  return chart;
}

/** A chart with `n` bars loaded on a candlestick series. */
function loaded(n: number): { chart: Chart; series: SeriesApi; data: Bar[] } {
  const chart = makeChart();
  const series = chart.addSeries('candlestick');
  const data = bars(n);
  series.setData(data);
  return { chart, series, data };
}

/**
 * Deterministic clock + timer. `advance` moves the clock and fires every live
 * timer once, the way a coarse (or throttled) host timer behaves; the
 * controller decides how many bars that buys.
 */
class FakeClock {
  public ms = 0;
  private _timers: { cb: () => void }[] = [];

  public readonly now = (): number => this.ms;

  public readonly schedule: ReplayScheduler = (cb) => {
    const timer = { cb };
    this._timers.push(timer);
    return () => { this._timers = this._timers.filter((t) => t !== timer); };
  };

  public advance(ms: number): void {
    this.ms += ms;
    for (const t of [...this._timers]) t.cb();
  }

  public get timers(): number {
    return this._timers.length;
  }
}

describe('ReplayController: playhead', () => {
  it('opens at startIndex with only that prefix on the chart', () => {
    const { chart, series, data } = loaded(20);
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 4 });
    const s = replay.state();
    expect(s).toEqual({ index: 4, total: 20, playing: false, speed: 1, bar: data[4], subIndex: 0, subSteps: 1, simulated: false });
    expect(series.getData()).toHaveLength(5);
    expect(series.getData()[4].time).toBe(data[4].time);
  });

  it('defaults its bar set to the series data already loaded', () => {
    const { chart, series, data } = loaded(12);
    const replay = new ReplayController(chart, { series });
    expect(replay.state().total).toBe(12);
    expect(replay.state().bar).toEqual(data[0]);
    expect(series.getData()).toHaveLength(1);
  });

  it('seek clamps to both ends of the session', () => {
    const { chart, series, data } = loaded(10);
    const replay = new ReplayController(chart, { series, bars: data });
    replay.seek(6);
    expect(replay.state().index).toBe(6);
    replay.seek(999);
    expect(replay.state().index).toBe(9);
    expect(series.getData()).toHaveLength(10);
    replay.seek(-4);
    expect(replay.state().index).toBe(0);
    expect(series.getData()).toHaveLength(1);
  });

  it('step and stepBack move by n and stop at the boundaries', () => {
    const { chart, series, data } = loaded(10);
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 3 });
    replay.step();
    expect(replay.state().index).toBe(4);
    replay.step(3);
    expect(replay.state().index).toBe(7);
    replay.step(50); // past the end
    expect(replay.state().index).toBe(9);
    replay.stepBack(2);
    expect(replay.state().index).toBe(7);
    replay.stepBack(50); // past the start
    expect(replay.state().index).toBe(0);
    expect(series.getData()).toHaveLength(1);
  });

  it('a single-bar session is a legal, immovable replay', () => {
    const { chart, series, data } = loaded(1);
    const replay = new ReplayController(chart, { series, bars: data });
    replay.step();
    replay.stepBack();
    expect(replay.state()).toEqual({ index: 0, total: 1, playing: false, speed: 1, bar: data[0], subIndex: 0, subSteps: 1, simulated: false });
  });

  it('never mutates the caller bar array', () => {
    const { chart, series } = loaded(8);
    const data = Object.freeze(bars(8));
    const replay = new ReplayController(chart, { series, bars: data });
    replay.seek(5);
    replay.stepBack(3);
    replay.seek(7);
    replay.stop();
    expect(data).toHaveLength(8);
    expect(data[7]).toEqual(bars(8)[7]);
  });
});

describe('ReplayController: playback', () => {
  it('advances on the injected clock and pauses itself at the last bar', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(6);
    const seen: number[] = [];
    const ended: ReplayState[] = [];
    chart.on('replay:end', (p) => ended.push(p as ReplayState));
    const replay = new ReplayController(chart, {
      series, bars: data, barMs: 100, now: clock.now, scheduler: clock.schedule,
      onFrame: (s) => seen.push(s.index),
    });

    replay.play();
    expect(replay.state().playing).toBe(true);
    expect(clock.timers).toBe(1);

    clock.advance(100);
    expect(replay.state().index).toBe(1);
    clock.advance(100);
    expect(replay.state().index).toBe(2);

    // A late timer buys the bars its elapsed time paid for, not one per tick.
    clock.advance(200);
    expect(replay.state().index).toBe(4);

    clock.advance(100);
    expect(replay.state().index).toBe(5);
    expect(replay.state().playing).toBe(false);
    expect(clock.timers).toBe(0); // the timer is released, not left spinning
    expect(ended).toHaveLength(1);
    expect(seen).toEqual([0, 1, 2, 4, 5]);

    // Ticks after the end cannot move anything.
    clock.advance(1000);
    expect(replay.state().index).toBe(5);
  });

  it('speed multiplies the bar rate', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(30);
    const replay = new ReplayController(chart, {
      series, bars: data, barMs: 100, now: clock.now, scheduler: clock.schedule,
    });
    replay.play({ speed: 4 });
    expect(replay.state().speed).toBe(4);
    clock.advance(100); // 100ms at 4x = 4 bars
    expect(replay.state().index).toBe(4);
  });

  it('a stalled clock buys nothing, and a very late one is capped', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(200);
    const replay = new ReplayController(chart, {
      series, bars: data, barMs: 100, now: clock.now, scheduler: clock.schedule,
    });
    replay.play();
    clock.advance(0);
    expect(replay.state().index).toBe(0);
    clock.advance(60_000); // came back from a backgrounded tab
    expect(replay.state().index).toBe(10);
  });

  it('pause holds the playhead and play resumes from it', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(20);
    const events: string[] = [];
    for (const name of ['replay:play', 'replay:pause']) chart.on(name, () => events.push(name));
    const replay = new ReplayController(chart, {
      series, bars: data, barMs: 100, now: clock.now, scheduler: clock.schedule,
    });

    replay.play();
    clock.advance(300);
    expect(replay.state().index).toBe(3);

    replay.pause();
    expect(replay.state().playing).toBe(false);
    expect(clock.timers).toBe(0);
    clock.advance(1000);
    expect(replay.state().index).toBe(3); // a paused replay ignores the clock

    replay.play();
    expect(replay.state().playing).toBe(true);
    clock.advance(200);
    expect(replay.state().index).toBe(5);
    expect(events).toEqual(['replay:play', 'replay:pause', 'replay:play']);
    expect(series.getData()).toHaveLength(6);
  });

  it('play on the last bar arms no timer', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(5);
    let ended = 0;
    chart.on('replay:end', () => { ended++; });
    const replay = new ReplayController(chart, {
      series, bars: data, startIndex: 4, barMs: 100, now: clock.now, scheduler: clock.schedule,
    });
    replay.play();
    expect(replay.state().playing).toBe(false);
    expect(clock.timers).toBe(0);
    expect(ended).toBe(1);
  });

  it('emits start, frame and stop for a host transport bar', () => {
    const { chart, series, data } = loaded(10);
    const log: string[] = [];
    for (const name of ['replay:start', 'replay:frame', 'replay:stop']) {
      chart.on(name, (p) => log.push(`${name}@${(p as ReplayState).index}`));
    }
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 2 });
    replay.step();
    replay.step(0); // no movement, no frame
    replay.stop();
    expect(log).toEqual(['replay:start@2', 'replay:frame@2', 'replay:frame@3', 'replay:stop@2']);
  });
});

describe('ReplayController: stop restores', () => {
  it('puts the full dataset and the exact viewport back', () => {
    const { chart, series, data } = loaded(40);
    chart.timeScale.setBarSpacing(11);
    chart.timeScale.setRightOffset(2.5);
    const before = chart.getVisibleLogicalRange();

    const replay = new ReplayController(chart, { series, bars: data, startIndex: 5 });
    expect(series.getData()).toHaveLength(6);
    expect(chart.getVisibleLogicalRange()).not.toEqual(before);
    // The user pans and zooms inside replay; exiting must undo that too.
    chart.timeScale.setBarSpacing(30);
    chart.timeScale.scrollByPixels(120);

    replay.stop();
    expect(series.getData()).toHaveLength(40);
    expect(series.getData()[39].time).toBe(data[39].time);
    expect(chart.timeScale.barSpacing).toBe(11);
    expect(chart.timeScale.rightOffset).toBe(2.5);
    expect(chart.getVisibleLogicalRange()).toEqual(before);
  });

  it('cancels playback, is idempotent, and can be re-entered', () => {
    const clock = new FakeClock();
    const { chart, series, data } = loaded(20);
    const replay = new ReplayController(chart, {
      series, bars: data, startIndex: 2, barMs: 100, now: clock.now, scheduler: clock.schedule,
    });
    replay.play();
    replay.stop();
    expect(replay.state().playing).toBe(false);
    expect(clock.timers).toBe(0);
    expect(series.getData()).toHaveLength(20);

    replay.stop(); // no-op, and it must not re-emit or re-truncate
    expect(series.getData()).toHaveLength(20);

    replay.step(); // re-enters replay from startIndex
    expect(replay.state().index).toBe(3);
    expect(series.getData()).toHaveLength(4);
  });

  it('restores every driven series, not just the primary', () => {
    const chart = makeChart();
    const price = chart.addSeries('candlestick');
    const volume = chart.addSeries('histogram', { paneIndex: 1 });
    const data = bars(30);
    price.setData(data);
    volume.setData(data.map((b) => ({ time: b.time, value: b.volume ?? 0 })));

    const replay = new ReplayController(chart, { series: [price, volume], bars: data, startIndex: 9 });
    // Both series stop at the replay instant, so the shared time axis does not
    // stretch out to a future volume bar.
    expect(price.getData()).toHaveLength(10);
    expect(volume.getData()).toHaveLength(10);
    expect(chart.dataLayer.length).toBe(10);

    replay.stop();
    expect(price.getData()).toHaveLength(30);
    expect(volume.getData()).toHaveLength(30);
    expect(chart.dataLayer.length).toBe(30);
  });

  it('cuts follower series by time, so a shorter one is not over-truncated', () => {
    const chart = makeChart();
    const price = chart.addSeries('candlestick');
    const overlay = chart.addSeries('line');
    const data = bars(20);
    price.setData(data);
    // Starts 10 bars in: at replay index 14 only 5 of its points have happened.
    overlay.setData(data.slice(10).map((b) => ({ time: b.time, value: b.close })));

    const replay = new ReplayController(chart, { series: [price, overlay], bars: data, startIndex: 14 });
    expect(overlay.getData()).toHaveLength(5);
    replay.seek(9);
    expect(overlay.getData()).toHaveLength(0);
    replay.stop();
    expect(overlay.getData()).toHaveLength(10);
  });
});

describe('ReplayController: indicators at a past moment', () => {
  /** The same indicators on a chart that only ever saw the first `n` bars. */
  function reference(data: readonly Bar[], n: number): Record<string, unknown> {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(data.slice(0, n));
    return {
      rsi: chart.addIndicator('rsi', { length: 14 }).values(),
      macd: chart.addIndicator('macd').values(),
      bollinger: chart.addIndicator('bollinger', { length: 20 }).values(),
      supertrend: chart.addIndicator('supertrend').values(),
    };
  }

  it('a seek reconstructs every indicator exactly as it was at that bar', () => {
    const { chart, series, data } = loaded(80);
    const rsi = chart.addIndicator('rsi', { length: 14 });
    const macd = chart.addIndicator('macd');
    const boll = chart.addIndicator('bollinger', { length: 20 });
    const st = chart.addIndicator('supertrend');

    const replay = new ReplayController(chart, { series, bars: data, startIndex: 40 });
    const ref = reference(data, 41);

    expect(rsi.values()).toEqual(ref.rsi);
    expect(macd.values()).toEqual(ref.macd);
    expect(boll.values()).toEqual(ref.bollinger);
    expect(st.values()).toEqual(ref.supertrend);
    // Not just the numbers: the plotted rows are the past ones too, so the
    // indicator's own series cannot hold the shared time axis open at the
    // future bars it used to cover.
    expect(rsi.series('rsi')?.getData()).toHaveLength(41);
    expect(chart.dataLayer.length).toBe(41);
    expect(replay.state().bar).toBe(data[40]);
  });

  it('stepping one bar at a time lands on the same values as loading that prefix', () => {
    const { chart, series, data } = loaded(80);
    const rsi = chart.addIndicator('rsi', { length: 14 });
    const macd = chart.addIndicator('macd');
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 30 });
    for (let i = 0; i < 12; i++) replay.step();
    expect(replay.state().index).toBe(42);

    const ref = reference(data, 43);
    expect(rsi.values()).toEqual(ref.rsi);
    expect(macd.values()).toEqual(ref.macd);
  });

  it('stepping back discards the future it had already seen', () => {
    const { chart, series, data } = loaded(80);
    const rsi = chart.addIndicator('rsi', { length: 14 });
    const boll = chart.addIndicator('bollinger', { length: 20 });
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 70 });
    replay.stepBack(40);
    expect(replay.state().index).toBe(30);

    const ref = reference(data, 31);
    expect(rsi.values()).toEqual(ref.rsi);
    expect(boll.values()).toEqual(ref.bollinger);
    expect(rsi.values().rsi).toHaveLength(31);
  });

  it('stop hands the indicators their full history back', () => {
    const { chart, series, data } = loaded(80);
    const rsi = chart.addIndicator('rsi', { length: 14 });
    const full = [...(rsi.values().rsi ?? [])];
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 20 });
    expect(rsi.values().rsi).toHaveLength(21);
    replay.stop();
    expect(rsi.values().rsi).toEqual(full);
  });
});

describe('ReplayController: wiring', () => {
  it('refuses to run without a series to drive', () => {
    const chart = makeChart();
    expect(() => new ReplayController(chart, {})).toThrow(/series/);
  });

  it('uses the chart primary series when the host can name one', () => {
    const { chart, series, data } = loaded(10);
    // The accessor core does not have yet: a host that offers it needs no
    // `series` option at all.
    const host = {
      emit: (): void => {},
      timeScale: chart.timeScale,
      primarySeries: (): SeriesApi => series,
    };
    const replay = new ReplayController(host, { bars: data, startIndex: 3 });
    expect(replay.state().index).toBe(3);
    expect(series.getData()).toHaveLength(4);
  });

  it('an empty session leaves the chart alone', () => {
    const { chart, series } = loaded(5);
    const replay = new ReplayController(chart, { series, bars: [] });
    expect(replay.state()).toEqual({ index: 0, total: 0, playing: false, speed: 1, bar: null, subIndex: 0, subSteps: 1, simulated: false });
    expect(series.getData()).toHaveLength(5);
    replay.play();
    replay.step();
    expect(series.getData()).toHaveLength(5);
  });
});

describe('ReplayController: a chart destroyed under it', () => {
  /** Counts the `'destroy'` listeners the controller holds on `chart`. */
  function countDestroyListeners(chart: Chart): () => number {
    let live = 0;
    const on = chart.on.bind(chart) as (event: 'destroy', cb: () => void) => () => void;
    (chart as unknown as { on: typeof on }).on = (event, cb) => {
      if (event !== 'destroy') return on(event, cb);
      live++;
      const off = on(event, cb);
      let done = false;
      return () => { if (!done) { done = true; live--; } off(); };
    };
    return () => live;
  }

  it('stops its timer and writes nothing more once the chart is destroyed mid-play', () => {
    const { chart, series, data } = loaded(20);
    const clock = new FakeClock();
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 2, now: clock.now, scheduler: clock.schedule });
    replay.play();
    expect(clock.timers).toBe(1);
    let writes = 0;
    const setData = series.setData.bind(series);
    series.setData = (...args: Parameters<SeriesApi['setData']>) => { writes++; setData(...args); };

    chart.destroy();
    expect(clock.timers).toBe(0);
    expect(replay.state().playing).toBe(false);
    clock.advance(5_000);
    // Nothing to restore to: leaving replay afterwards writes nothing either.
    replay.stop();
    expect(writes).toBe(0);
  });

  it('listens for the chart going away only while it owns the chart data', () => {
    const { chart, series, data } = loaded(20);
    const destroyListeners = countDestroyListeners(chart);
    const clock = new FakeClock();
    const replay = new ReplayController(chart, { series, bars: data, now: clock.now, scheduler: clock.schedule });
    expect(destroyListeners()).toBe(1);
    replay.stop();
    // A stopped controller the host drops is not kept alive by the chart.
    expect(destroyListeners()).toBe(0);
    replay.play();
    expect(destroyListeners()).toBe(1);
    replay.stop();
    replay.stop();
    expect(destroyListeners()).toBe(0);
    const idle = new ReplayController(chart, { series, bars: data, autoStart: false });
    expect(destroyListeners()).toBe(0);
    idle.stop();
    expect(destroyListeners()).toBe(0);
  });
});
