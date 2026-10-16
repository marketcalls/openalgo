/**
 * Intra-bar replay: a displayed bar forms in front of the user instead of
 * appearing complete.
 *
 * Asked for directly: with a 1-minute base interval under a 5-minute chart, one
 * 5-minute bar should take five steps. Replay without it slices a prefix of the
 * displayed bars, so every step lands a finished candle and the moment a trader
 * is practising for -- watching a bar build and deciding before it closes --
 * never happens.
 *
 * The rule that makes it safe to mix two feeds: the last step of a bucket emits
 * the displayed bar verbatim, so a bucket always closes on exactly the number
 * the chart shows without this option, whatever the finer feed says.
 */
import { describe, it, expect } from 'vitest';
import { ReplayController, type ReplayChartHost } from '../src/replay/controller';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';

const T0 = 1735689600; // a round epoch, so bucket arithmetic reads plainly
const MIN = 60;
const FIVE = 5 * MIN;

/** A series that records what it was last handed. */
function stubSeries(initial: readonly Bar[] = []): SeriesApi & { data: Bar[] } {
  let data: Bar[] = [...initial];
  const api = {
    setData: (b: readonly Bar[]) => { data = [...b]; },
    prependData: () => {},
    update: () => {},
    getData: () => data,
    applyOptions: () => {},
    remove: () => {},
    priceScale: () => ({}) as never,
    createMarkers: () => ({ setMarkers: () => {} }) as never,
  } as unknown as SeriesApi & { data: Bar[] };
  Object.defineProperty(api, 'data', { get: () => data });
  return api;
}

function host(): ReplayChartHost & { events: string[] } {
  const events: string[] = [];
  return {
    events,
    emit: (e: string) => { events.push(e); },
    timeScale: {
      barSpacing: 8, rightOffset: 0,
      setBarSpacing: () => {}, setRightOffset: () => {},
    },
  } as ReplayChartHost & { events: string[] };
}

/** `n` five-minute bars, each built from five one-minute bars. */
function session(n: number): { display: Bar[]; sub: Bar[] } {
  const display: Bar[] = [];
  const sub: Bar[] = [];
  for (let d = 0; d < n; d++) {
    const base = 100 + d * 10;
    const mins: Bar[] = [];
    for (let m = 0; m < 5; m++) {
      // A rising bucket, so open/high/low/close are all distinguishable, and each
      // minute a real one: its close inside its own high and low.
      const o = base + m;
      mins.push({ time: T0 + d * FIVE + m * MIN, open: o, high: o + 1.5, low: o - 0.5, close: o + 1, volume: 10 });
    }
    sub.push(...mins);
    display.push({
      time: T0 + d * FIVE,
      open: mins[0].open,
      high: Math.max(...mins.map((b) => b.high)),
      low: Math.min(...mins.map((b) => b.low)),
      close: mins[4].close,
      volume: 50,
    });
  }
  return { display, sub };
}

describe('a 5-minute bar over 1-minute data takes five steps', () => {
  it('reveals only the latest available sub-bar open interest until the bucket completes', () => {
    const { display, sub } = session(3);
    display[1].oi = 140;
    display[2].oi = 400;
    for (let i = 0; i < 5; i++) sub[5 + i].oi = 100 + i * 10;
    const series = stubSeries(display);
    const replay = new ReplayController(host(), { series, bars: display, subBars: sub, startIndex: 0 });
    try {
      for (const expected of [100, 110, 120, 130, 140]) {
        replay.step();
        expect(series.getData()[1].oi).toBe(expected);
        expect(replay.state().bar?.oi).toBe(expected);
      }
      for (let i = 0; i < 4; i++) {
        replay.step();
        expect(series.getData()[2].oi).toBeUndefined();
      }
      replay.step();
      expect(series.getData()[2].oi).toBe(400);
    } finally { replay.stop(); }
  });

  it('reports five steps and advances through them one at a time', () => {
    const { display, sub } = session(6);
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, subBars: sub, startIndex: 2 });

    // A seek (which is what startIndex is) lands on a completed bar.
    expect(r.state().subSteps).toBe(5);
    expect(r.state().subIndex).toBe(4);
    expect(r.state().index).toBe(2);

    // Five steps to cross one displayed bar, not one.
    r.step();
    expect(r.state()).toMatchObject({ index: 3, subIndex: 0 });
    for (let i = 1; i <= 3; i++) {
      r.step();
      expect(r.state()).toMatchObject({ index: 3, subIndex: i });
    }
    r.step();
    expect(r.state()).toMatchObject({ index: 3, subIndex: 4 });
    r.step();
    expect(r.state()).toMatchObject({ index: 4, subIndex: 0 });
  });

  it('grows the forming bar rather than showing it complete', () => {
    const { display, sub } = session(6);
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, subBars: sub, startIndex: 2 });

    r.step(); // bar 3, first minute
    const shown = series.getData();
    expect(shown).toHaveLength(4);
    const forming = shown[3];
    const firstMinute = sub[3 * 5];
    expect(forming.time).toBe(display[3].time);     // still bucket 3, not a new bar
    expect(forming.open).toBe(firstMinute.open);
    expect(forming.close).toBe(firstMinute.close);
    expect(forming.close).not.toBe(display[3].close); // the point: not the final close
    expect(forming.volume).toBe(10);

    // Three minutes in: extremes and volume have accumulated.
    r.step();
    r.step();
    const mid = series.getData()[3];
    expect(mid.open).toBe(firstMinute.open);
    expect(mid.high).toBe(Math.max(...sub.slice(15, 18).map((b) => b.high)));
    expect(mid.low).toBe(Math.min(...sub.slice(15, 18).map((b) => b.low)));
    expect(mid.close).toBe(sub[17].close);
    expect(mid.volume).toBe(30);
  });

  it('closes the bucket on the displayed bar itself, not on the aggregate', () => {
    // The guarantee that lets two feeds be mixed: however the 1-minute and
    // 5-minute series disagree, a closed bar is the one the chart would show
    // without intra-bar replay.
    const { display, sub } = session(4);
    // Make the finer feed disagree, the way two vendor endpoints do.
    const tampered = sub.map((b) => ({ ...b, high: b.high + 99, close: b.close + 99 }));
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, subBars: tampered, startIndex: 0 });

    r.step(); r.step(); r.step(); r.step(); r.step(); // through bar 1 to its close
    expect(r.state()).toMatchObject({ index: 1, subIndex: 4 });
    expect(series.getData()[1]).toEqual(display[1]);
  });

  it('steps back through the forming bar and across the boundary', () => {
    const { display, sub } = session(5);
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, subBars: sub, startIndex: 2 });

    r.step(); r.step(); // bar 3, minute 1
    expect(r.state()).toMatchObject({ index: 3, subIndex: 1 });
    r.stepBack();
    expect(r.state()).toMatchObject({ index: 3, subIndex: 0 });
    r.stepBack();
    // Back across the boundary lands on the last step of the previous bar.
    expect(r.state()).toMatchObject({ index: 2, subIndex: 4 });
    expect(series.getData()[2]).toEqual(display[2]);
  });

  it('gives a bucket the finer feed does not cover a single step', () => {
    // A gap in the 1-minute session costs that bar its formation, not its
    // existence: it still appears, complete, in one step.
    const { display, sub } = session(4);
    const holed = sub.filter((b) => b.time < T0 + 2 * FIVE || b.time >= T0 + 3 * FIVE);
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, subBars: holed, startIndex: 1 });

    r.step();
    expect(r.state()).toMatchObject({ index: 2, subIndex: 0, subSteps: 1 });
    expect(series.getData()[2]).toEqual(display[2]);
    r.step();
    expect(r.state()).toMatchObject({ index: 3, subIndex: 0, subSteps: 5 });
  });

  it('holds followers at the last completed bucket while a bar forms', () => {
    // A volume histogram is summed, not OHLC-merged, so the controller will not
    // guess: it stops the follower at the last closed bar and hands the host the
    // partial through `bar` to drive its own.
    const { display, sub } = session(5);
    const price = stubSeries(display);
    const vol = display.map((b) => ({ time: b.time, open: 0, high: b.volume ?? 0, low: 0, close: b.volume ?? 0 }));
    const volume = stubSeries(vol);
    const r = new ReplayController(host(), { series: [price, volume], bars: display, subBars: sub, startIndex: 2 });

    r.step(); // bar 3 forming
    expect(price.getData()).toHaveLength(4);
    expect(volume.getData()).toHaveLength(3); // through bar 2 only
    expect(r.state().bar?.volume).toBe(10);   // the partial, for the host to use

    for (let i = 0; i < 4; i++) r.step(); // close bar 3
    expect(r.state()).toMatchObject({ index: 3, subIndex: 4 });
    expect(volume.getData()).toHaveLength(4); // follower catches up on the close
  });

  it('plays to the end of the last bar, not the start of it', () => {
    const { display, sub } = session(3);
    const series = stubSeries(display);
    const events: string[] = [];
    const h = host();
    h.emit = (e: string) => { events.push(e); };
    const tick: { fn: (() => void) | null } = { fn: null };
    let clock = 0;
    const r = new ReplayController(h, {
      series, bars: display, subBars: sub, startIndex: 2, barMs: 10,
      now: () => clock,
      scheduler: (cb) => { tick.fn = cb; return () => { tick.fn = null; }; },
    });
    r.seek(2);
    // Rewind to the start of the last bar, then play it out step by step.
    for (let i = 0; i < 4; i++) r.stepBack();
    expect(r.state()).toMatchObject({ index: 2, subIndex: 0 });
    r.play();
    for (let i = 0; i < 6; i++) { clock += 10; tick.fn?.(); }
    expect(r.state()).toMatchObject({ index: 2, subIndex: 4 });
    expect(events).toContain('replay:end');
  });

  it('is inert without subBars, so every existing host is unchanged', () => {
    const { display } = session(6);
    const series = stubSeries(display);
    const r = new ReplayController(host(), { series, bars: display, startIndex: 2 });
    expect(r.state()).toMatchObject({ subIndex: 0, subSteps: 1 });
    r.step();
    expect(r.state()).toMatchObject({ index: 3, subIndex: 0 });
    expect(series.getData()[3]).toEqual(display[3]);
  });
});

/**
 * The finer feed disagreeing with the displayed one the way real feeds do: the
 * displayed open is the exchange's official open while the first minute opened a
 * little higher, the minutes run past the displayed extremes, and their volumes
 * sum to more than the displayed bar's.
 */
function disagreeing(n: number): { display: Bar[]; sub: Bar[] } {
  const { display, sub } = session(n);
  return { display, sub: sub.map((b) => ({ ...b, open: b.open + 0.3, high: b.high + 0.8, low: b.low - 0.8, volume: 15 })) };
}

/** Every bar shown for bucket 1, one per step from its first to its close. */
function formation(display: Bar[], sub: Bar[]): { shown: Bar[]; reported: Bar[] } {
  const series = stubSeries(display);
  const r = new ReplayController(host(), { series, bars: display, subBars: sub, startIndex: 0 });
  const shown: Bar[] = [];
  const reported: Bar[] = [];
  try {
    for (let s = 0; s < 5; s++) {
      r.step();
      shown.push(series.getData()[1]);
      reported.push(r.state().bar as Bar);
    }
  } finally { r.stop(); }
  return { shown, reported };
}

describe('a forming bar grows the way a live one does when the feeds disagree', () => {
  it('keeps the open it closes with, from the first step', () => {
    // A candle's open is its first trade and never moves. Taking it from the
    // first minute made it jump to the displayed open when the bucket closed,
    // on every bar where the two feeds disagree.
    const { display, sub } = disagreeing(4);
    const { shown, reported } = formation(display, sub);
    for (const bar of [...shown, ...reported]) expect(bar.open).toBe(display[1].open);
    expect(shown[4]).toEqual(display[1]);
  });

  it('never lowers a high, raises a low or takes back volume on the way to the close', () => {
    const { display, sub } = disagreeing(4);
    const { shown, reported } = formation(display, sub);
    const final = display[1];
    expect(reported).toEqual(shown);
    shown.forEach((b, k) => {
      // Every step is a bar that could still grow into the closed one.
      expect(b.high).toBeLessThanOrEqual(final.high);
      expect(b.low).toBeGreaterThanOrEqual(final.low);
      expect(b.volume).toBeLessThanOrEqual(final.volume as number);
      expect(Math.max(b.open, b.close)).toBeLessThanOrEqual(b.high);
      expect(Math.min(b.open, b.close)).toBeGreaterThanOrEqual(b.low);
      if (k === 0) return;
      expect(b.high).toBeGreaterThanOrEqual(shown[k - 1].high);
      expect(b.low).toBeLessThanOrEqual(shown[k - 1].low);
      expect(b.volume).toBeGreaterThanOrEqual(shown[k - 1].volume as number);
    });
  });

  it('still follows the finer feed wherever it lies inside the displayed bar', () => {
    // Holding the forming bar inside the closed one must not flatten it: with
    // feeds that agree, every step is exactly the aggregate of the minutes so far.
    const { display, sub } = session(4);
    const { shown } = formation(display, sub);
    const minutes = sub.slice(5, 10);
    shown.slice(0, 4).forEach((b, k) => {
      const seen = minutes.slice(0, k + 1);
      expect(b).toEqual({
        time: display[1].time, open: minutes[0].open,
        high: Math.max(...seen.map((m) => m.high)), low: Math.min(...seen.map((m) => m.low)),
        close: seen[k].close, volume: 10 * (k + 1),
      });
    });
  });
});
