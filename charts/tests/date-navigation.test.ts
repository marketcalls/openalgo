/**
 * Date and range navigation: a host coordinator that loads missing history
 * through the host's own loader and then places the request with the chart's
 * public viewport and time conversion APIs.
 *
 * The fixtures are session-stamped on purpose. Daily bars open at 09:15 in
 * Mumbai, so a date typed as local midnight sits before its own bar, and a
 * rule that picks "the bar that contains the instant" lands on the previous
 * day. Weekends and overnight gaps exist in every fixture because the
 * gapless axis collapses them, and that is where a time-to-index mapping
 * quietly goes wrong.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import { formatZonedDate, zonedWallClockToUtcSeconds } from '../src/feed/time';
import { registerInterval } from '../src/feed/intervals';
import { ReplayController } from '../src/replay/controller';
import { createLinkGroup } from '../src/link/index';
import { DateNavigator, type HistoryReach } from '../src/widget/date-navigator';
import { SessionCalendar } from '../src/feed/instrument';

const ZONE = 'Asia/Kolkata';
const at = (y: number, m: number, d: number, hh = 0, mm = 0): number => zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, ZONE);
const bar = (time: number, close = 100): Bar => ({ time, open: close, high: close + 1, low: close - 1, close, volume: 10 });

/** Weekday daily bars stamped at the 09:15 session open, from `y-m-d` for `count` sessions. */
function dailySessions(y: number, m: number, d: number, count: number): Bar[] {
  const out: Bar[] = [];
  for (let day = 0; out.length < count; day++) {
    const time = at(y, m, d + day, 9, 15);
    const weekday = new Date((time + 5.5 * 3600) * 1000).getUTCDay();
    if (weekday !== 0 && weekday !== 6) out.push(bar(time, 100 + out.length));
  }
  return out;
}

/** Hourly bars 09:15 to 15:15 on each listed date. */
function hourly(dates: ReadonlyArray<[number, number, number]>): Bar[] {
  return dates.flatMap(([y, m, d]) => Array.from({ length: 7 }, (_, h) => bar(at(y, m, d, 9 + h, 15), 200 + h)));
}

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown; requestAnimationFrame?: unknown; cancelAnimationFrame?: unknown };
  g.window ??= {};
  g.requestAnimationFrame ??= (): number => 0;
  g.cancelAnimationFrame ??= (): void => {};
});

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) if (!chart.isDestroyed) chart.destroy(); });

function makeChart(bars: readonly Bar[], interval = '1d', timezone?: string): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...(timezone === undefined ? {} : { timezone }),
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars);
  chart.setDataContext({ symbol: 'NIFTY', exchange: 'NSE', interval });
  charts.push(chart);
  return chart;
}

const centre = (chart: Chart): number => { const view = chart.getVisibleLogicalRange(); return (view.from + view.to) / 2; };
const indexOf = (chart: Chart, time: number): number => chart.dataLayer.timeToIndex(time)!;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}

describe('date placement on loaded history', () => {
  it('centres a loaded date at the current zoom without asking for history', async () => {
    const bars = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(bars);
    chart.setVisibleLogicalRange({ from: 40, to: 60 });
    const loadHistory = vi.fn(async (): Promise<HistoryReach> => 'loaded');
    const navigator = new DateNavigator({ chart, loadHistory });
    const target = bars.find(value => value.time === at(2024, 2, 15, 9, 15))!;
    const result = await navigator.goTo({ from: at(2024, 2, 15) });
    expect(result).toMatchObject({ status: 'placed', from: target.time, to: target.time });
    expect(centre(chart)).toBeCloseTo(indexOf(chart, target.time), 6);
    const view = chart.getVisibleLogicalRange();
    expect(view.to - view.from).toBeCloseTo(20, 6);
    expect(loadHistory).not.toHaveBeenCalled();
  });

  it('reads a weekend date as the next session and keeps the newest bar in reach', async () => {
    const bars = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(bars);
    chart.setVisibleLogicalRange({ from: 0, to: 20 });
    const navigator = new DateNavigator({ chart });
    const monday = at(2024, 2, 19, 9, 15);
    expect(await navigator.goTo({ from: at(2024, 2, 17) })).toMatchObject({ status: 'placed', from: monday });
    expect(centre(chart)).toBeCloseTo(indexOf(chart, monday), 6);
    const last = bars[bars.length - 1].time;
    expect(await navigator.goTo({ from: last })).toMatchObject({ status: 'placed', from: last });
    const view = chart.getVisibleLogicalRange();
    expect(view.to).toBeLessThanOrEqual(bars.length - 1 + 4 + 1e-9);
    expect(view.from).toBeLessThan(bars.length - 1);
  });

  it('finds the intraday bar that contains a time and skips overnight and weekend gaps', async () => {
    const bars = hourly([[2024, 3, 7], [2024, 3, 8], [2024, 3, 11]]);
    const chart = makeChart(bars, '1h');
    chart.setVisibleLogicalRange({ from: 0, to: 10 });
    const navigator = new DateNavigator({ chart });
    expect(await navigator.goTo({ from: at(2024, 3, 8, 11, 40) })).toMatchObject({ status: 'placed', from: at(2024, 3, 8, 11, 15) });
    expect(await navigator.goTo({ from: at(2024, 3, 8, 20, 0) })).toMatchObject({ status: 'placed', from: at(2024, 3, 11, 9, 15) });
    expect(await navigator.goTo({ from: at(2024, 3, 9, 10, 0) })).toMatchObject({ status: 'placed', from: at(2024, 3, 11, 9, 15) });
    const view = chart.getVisibleLogicalRange();
    expect(await navigator.goTo({ from: at(2024, 3, 9), to: at(2024, 3, 10, 23, 59) })).toEqual({ status: 'no-data' });
    expect(chart.getVisibleLogicalRange()).toEqual(view);
    expect(await navigator.goTo({ from: at(2024, 3, 12) })).toEqual({ status: 'no-data' });
    expect(chart.getVisibleLogicalRange()).toEqual(view);
  });

  it('fits an explicit range, centres a short one at the zoom limit and clips one wider than the chart', async () => {
    const bars = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(bars);
    const navigator = new DateNavigator({ chart });
    const first = at(2024, 2, 5, 9, 15);
    const last = at(2024, 2, 16, 9, 15);
    expect(await navigator.goTo({ from: at(2024, 2, 5), to: at(2024, 2, 16, 23, 59) })).toMatchObject({ status: 'placed', from: first, to: last });
    let view = chart.getVisibleLogicalRange();
    expect(view.from).toBeCloseTo(indexOf(chart, first) - 0.5, 6);
    expect(view.to).toBeCloseTo(indexOf(chart, last) + 0.5, 6);
    expect(await navigator.goTo({ from: at(2024, 2, 5), to: at(2024, 2, 6, 23, 59) })).toMatchObject({ status: 'placed' });
    view = chart.getVisibleLogicalRange();
    const mid = indexOf(chart, first) + 0.5;
    expect((view.from + view.to) / 2).toBeCloseTo(mid, 6);
    expect(view.to - view.from).toBeGreaterThan(2);

    const minutes = Array.from({ length: 3000 }, (_, i) => bar(at(2024, 3, 11, 9, 15) + i * 60));
    const dense = makeChart(minutes, '1m');
    const wide = await new DateNavigator({ chart: dense }).goTo({ from: minutes[0].time, to: minutes[2999].time });
    expect(wide).toMatchObject({ status: 'partial', clipped: true, from: minutes[0].time });
    view = dense.getVisibleLogicalRange();
    expect(view.from).toBeCloseTo(-0.5, 6);
    expect(wide.to).toBeLessThan(minutes[2999].time);
  });

  it('rejects intervals without time buckets and malformed requests without moving the view', async () => {
    const off = registerInterval({ code: 'T100', bucketing: { mode: 'ticks', count: 100 } });
    try {
      const bars = dailySessions(2024, 1, 1, 30);
      const chart = makeChart(bars, 'T100');
      const loadHistory = vi.fn(async (): Promise<HistoryReach> => 'loaded');
      const navigator = new DateNavigator({ chart, loadHistory });
      const view = chart.getVisibleLogicalRange();
      expect(await navigator.goTo({ from: at(2023, 6, 1) })).toEqual({ status: 'unsupported' });
      chart.setDataContext({ symbol: 'NIFTY', exchange: 'NSE', interval: 'not-an-interval' });
      expect(await navigator.goTo({ from: at(2023, 6, 1) })).toEqual({ status: 'unsupported' });
      chart.setDataContext({ symbol: 'NIFTY', exchange: 'NSE', interval: '1d' });
      expect(await navigator.goTo({ from: Number.NaN })).toEqual({ status: 'invalid' });
      expect(await navigator.goTo({ from: at(2024, 1, 10), to: at(2024, 1, 5) })).toEqual({ status: 'invalid' });
      expect(loadHistory).not.toHaveBeenCalled();
      expect(chart.getVisibleLogicalRange()).toEqual(view);
      // A host that knows the bars' interval better than the data context can say so.
      chart.setDataContext({ symbol: 'NIFTY', exchange: 'NSE', interval: 'T100' });
      const named = new DateNavigator({ chart, interval: () => '1d' });
      expect(await named.goTo({ from: bars[10].time })).toMatchObject({ status: 'placed', from: bars[10].time });
    } finally { off(); }
  });
});

describe('date placement across daylight saving changes', () => {
  // A day is 23 or 25 hours and a week 167 or 169 around a change, so a bar's
  // end has to come from the calendar, not from its open plus a fixed length.
  const NY = 'America/New_York';
  const local = (y: number, m: number, d: number, hh = 0, mm = 0): number => zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, NY);

  it('lands a date on its own daily bar on both sides of a change', async () => {
    const days = (y: number, m: number, d: number, count: number): Bar[] =>
      Array.from({ length: count }, (_, i) => bar(local(y, m, d + i), 100 + i));
    const spring = days(2024, 3, 4, 14);
    const chart = makeChart(spring, '1d', NY);
    const navigator = new DateNavigator({ chart });
    expect(await navigator.goTo({ from: local(2024, 3, 11) })).toMatchObject({ status: 'placed', from: local(2024, 3, 11) });
    expect(await navigator.goTo({ from: local(2024, 3, 10, 23, 30) })).toMatchObject({ status: 'placed', from: local(2024, 3, 10) });
    expect(await navigator.goTo({ from: local(2024, 3, 11), to: local(2024, 3, 12, 23, 59) }))
      .toMatchObject({ status: 'placed', from: local(2024, 3, 11), to: local(2024, 3, 12) });

    const autumn = makeChart(days(2024, 10, 28, 14), '1d', NY);
    const back = new DateNavigator({ chart: autumn });
    // The 25-hour day: its last hour still belongs to it.
    expect(await back.goTo({ from: local(2024, 11, 3, 23, 30) })).toMatchObject({ status: 'placed', from: local(2024, 11, 3) });
    expect(await back.goTo({ from: local(2024, 11, 4) })).toMatchObject({ status: 'placed', from: local(2024, 11, 4) });
  });

  it('lands a date on its own weekly bar in a week that changes the clock', async () => {
    const weeks = Array.from({ length: 12 }, (_, i) => bar(local(2024, 2, 5 + 7 * i), 100 + i));
    const chart = makeChart(weeks, '1w', NY);
    const navigator = new DateNavigator({ chart });
    expect(await navigator.goTo({ from: local(2024, 3, 11) })).toMatchObject({ status: 'placed', from: local(2024, 3, 11) });
    expect(await navigator.goTo({ from: local(2024, 3, 13) })).toMatchObject({ status: 'placed', from: local(2024, 3, 11) });
    expect(await navigator.goTo({ from: local(2024, 3, 10, 23, 30) })).toMatchObject({ status: 'placed', from: local(2024, 3, 4) });
  });

  it('names the daily bar the axis labels with the date when the feed stamps UTC midnight', async () => {
    // West of UTC a UTC-midnight stamp is the previous evening on this clock,
    // and the axis, crosshair and data window all label it with that earlier
    // date. The date typed is the one read off the axis, so it names that bar.
    const utc = Array.from({ length: 20 }, (_, i) => bar(Date.UTC(2024, 4, 27 + i) / 1000, 100 + i));
    const chart = makeChart(utc, '1d', NY);
    const navigator = new DateNavigator({ chart });
    const placed = await navigator.goTo({ from: local(2024, 6, 5) });
    expect(placed).toMatchObject({ status: 'placed', from: Date.UTC(2024, 5, 6) / 1000 });
    expect(formatZonedDate(placed.from!, NY)).toBe('05 Jun');
    expect(await navigator.goTo({ from: local(2024, 6, 3), to: local(2024, 6, 5, 23, 59) }))
      .toMatchObject({ status: 'placed', from: Date.UTC(2024, 5, 4) / 1000, to: Date.UTC(2024, 5, 6) / 1000 });
  });

  it('keeps a session-stamped daily bar inside a range that ends on its date', async () => {
    const bars = dailySessions(2024, 1, 1, 30);
    const chart = makeChart(bars);
    const navigator = new DateNavigator({ chart });
    // A range end before the 09:15 stamp still names that day's bar, as a start does.
    expect(await navigator.goTo({ from: at(2024, 1, 8), to: at(2024, 1, 12, 8, 0) }))
      .toMatchObject({ status: 'placed', from: at(2024, 1, 8, 9, 15), to: at(2024, 1, 12, 9, 15) });
  });
});

describe('date placement with missing history', () => {
  it('loads older history through the host loader before placing', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    chart.setVisibleLogicalRange({ from: 20, to: 34 });
    const reached: number[] = [];
    const navigator = new DateNavigator({ chart, loadHistory: async time => {
      reached.push(time);
      chart.primarySeries()!.setData(all.filter(value => value.time >= time - 86400 * 3));
      return 'loaded';
    } });
    const target = at(2024, 1, 10, 9, 15);
    const result = await navigator.goTo({ from: at(2024, 1, 10) });
    expect(result).toEqual({ status: 'placed', from: target, to: target });
    expect(reached.length).toBeGreaterThan(0);
    expect(reached[0]).toBeLessThanOrEqual(at(2024, 1, 10));
    expect(centre(chart)).toBeCloseTo(indexOf(chart, target), 6);
  });

  it('keeps exhausted history apart from empty pages and still shows the earliest bar', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    for (const reach of ['exhausted', 'empty', 'limited'] as const) {
      const chart = makeChart(all.slice(30));
      const loadHistory = vi.fn(async (): Promise<HistoryReach> => reach);
      const navigator = new DateNavigator({ chart, loadHistory });
      const result = await navigator.goTo({ from: at(2023, 12, 1) });
      expect(result).toEqual({ status: 'partial', history: reach, from: all[30].time, to: all[30].time });
      expect(loadHistory).toHaveBeenCalledTimes(1);
      expect(centre(chart)).toBeCloseTo(0, 6);
      const view = chart.getVisibleLogicalRange();
      expect(await navigator.goTo({ from: at(2023, 11, 1), to: at(2023, 11, 30) })).toEqual({ status: 'no-data', history: reach });
      expect(chart.getVisibleLogicalRange()).toEqual(view);
    }
  });

  it('stops when a loader reports progress it did not make', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    const loadHistory = vi.fn(async (): Promise<HistoryReach> => 'loaded');
    const result = await new DateNavigator({ chart, loadHistory }).goTo({ from: at(2023, 12, 1) });
    expect(loadHistory).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ status: 'partial', history: 'empty' });
  });

  it('navigates loaded history only without a loader', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    expect(await new DateNavigator({ chart }).goTo({ from: at(2023, 12, 1) }))
      .toEqual({ status: 'partial', history: 'unavailable', from: all[30].time, to: all[30].time });
  });

  it('reports a failed load without placing anything', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    const view = chart.getVisibleLogicalRange();
    const result = await new DateNavigator({ chart, loadHistory: async () => { throw new Error('offline'); } }).goTo({ from: at(2023, 12, 1) });
    expect(result.status).toBe('error');
    expect(result.error?.message).toBe('offline');
    expect(chart.getVisibleLogicalRange()).toEqual(view);
  });
});

describe('date navigation lifecycle', () => {
  it('lets a newer request supersede a pending load', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    const pending = deferred<HistoryReach>();
    const navigator = new DateNavigator({ chart, loadHistory: () => pending.promise });
    const older = navigator.goTo({ from: at(2024, 1, 10) });
    const newer = await navigator.goTo({ from: all[50].time });
    expect(newer).toMatchObject({ status: 'placed', from: all[50].time });
    const view = chart.getVisibleLogicalRange();
    chart.primarySeries()!.setData(all);
    const shifted = chart.getVisibleLogicalRange();
    pending.resolve('loaded');
    expect(await older).toEqual({ status: 'cancelled' });
    expect(chart.getVisibleLogicalRange()).toEqual(shifted);
    expect(view).toBeDefined();
  });

  it('abandons a load when the instrument or interval changes', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    for (const change of [{ symbol: 'BANKNIFTY', exchange: 'NSE', interval: '1d' }, { symbol: 'NIFTY', exchange: 'NSE', interval: '1h' }]) {
      const chart = makeChart(all.slice(30));
      const pending = deferred<HistoryReach>();
      const work = new DateNavigator({ chart, loadHistory: () => pending.promise }).goTo({ from: at(2024, 1, 10) });
      chart.setDataContext(change);
      chart.primarySeries()!.setData(all);
      const view = chart.getVisibleLogicalRange();
      pending.resolve('loaded');
      expect(await work).toEqual({ status: 'cancelled' });
      expect(chart.getVisibleLogicalRange()).toEqual(view);
    }
  });

  it('settles at once when the chart or the navigator is destroyed during a load', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(30));
    const never = new Promise<HistoryReach>(() => {});
    const navigator = new DateNavigator({ chart, loadHistory: () => never });
    const work = navigator.goTo({ from: at(2024, 1, 10) });
    navigator.destroy();
    expect(await work).toEqual({ status: 'cancelled' });
    expect(await navigator.goTo({ from: all[40].time })).toEqual({ status: 'cancelled' });

    const second = makeChart(all.slice(30));
    const pending = deferred<HistoryReach>();
    const running = new DateNavigator({ chart: second, loadHistory: () => pending.promise }).goTo({ from: at(2024, 1, 10) });
    second.destroy();
    pending.resolve('loaded');
    expect(await running).toEqual({ status: 'cancelled' });
  });

  it('follows a host that rebuilds its chart during the load', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    let current = makeChart(all.slice(30));
    const navigator = new DateNavigator({ chart: () => current, loadHistory: async () => {
      const previous = current;
      current = makeChart(all);
      previous.destroy();
      return 'loaded';
    } });
    const target = at(2024, 1, 10, 9, 15);
    expect(await navigator.goTo({ from: at(2024, 1, 10) })).toMatchObject({ status: 'placed', from: target });
    expect(centre(current)).toBeCloseTo(indexOf(current, target), 6);
  });

  it('never loads during replay and never places a bar beyond the replay cursor', async () => {
    const all = dailySessions(2024, 1, 1, 65);
    const chart = makeChart(all.slice(10));
    const loadHistory = vi.fn(async (): Promise<HistoryReach> => 'loaded');
    const navigator = new DateNavigator({ chart, loadHistory });
    const replay = new ReplayController(chart, { startIndex: 20 });
    try {
      expect(chart.primaryBars()).toHaveLength(21);
      expect(await navigator.goTo({ from: all[40].time })).toEqual({ status: 'no-data' });
      expect(await navigator.goTo({ from: at(2023, 12, 1) })).toEqual({ status: 'partial', history: 'unavailable', from: all[10].time, to: all[10].time });
      expect(await navigator.goTo({ from: all[20].time })).toMatchObject({ status: 'placed', from: all[20].time });
      expect(loadHistory).not.toHaveBeenCalled();
    } finally { replay.stop(); }
  });

  it('moves linked charts to the placed window by time', async () => {
    const daily = dailySessions(2024, 1, 1, 65);
    const leader = makeChart(daily);
    const follower = makeChart(hourly(daily.slice(20, 50).map(value => {
      const date = new Date((value.time + 5.5 * 3600) * 1000);
      return [date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()] as [number, number, number];
    })), '1h');
    follower.fitContent();
    const group = createLinkGroup();
    group.add(leader);
    group.add(follower);
    try {
      const before = follower.getVisibleLogicalRange();
      // Twenty sessions fit the plot without reaching the widest bar spacing, so
      // the placed window is exactly the range and the follower's edges can be named.
      const from = at(2024, 2, 5);
      const to = at(2024, 3, 1, 23, 59);
      expect(await new DateNavigator({ chart: leader }).goTo({ from, to })).toMatchObject({ status: 'placed' });
      const after = follower.getVisibleLogicalRange();
      expect(after).not.toEqual(before);
      const firstVisible = follower.dataLayer.indexToTime(Math.ceil(after.from));
      const lastVisible = follower.dataLayer.indexToTime(Math.floor(after.to));
      expect(firstVisible).toBe(at(2024, 2, 5, 9, 15));
      expect(lastVisible).toBe(at(2024, 3, 1, 15, 15));
    } finally { group.destroy(); }
  });
});

describe('history that starts after a gap with no session', () => {
  // A New York stock on an Indian clock: its 09:30 open is 19:00 here, so a
  // month back from a Monday is a Sunday midnight that no session follows
  // until Monday evening. The loaded history starts there and is whole.
  const NY = 'America/New_York';
  const nyCalendar = (): SessionCalendar => new SessionCalendar({ timezone: NY, sessions: ['0930-1600:23456'] });
  /** 30 minute bars through each New York weekday from `start` to `end` (local dates, inclusive). */
  function newYork(start: [number, number, number], end: [number, number, number]): Bar[] {
    const out: Bar[] = [];
    const first = zonedWallClockToUtcSeconds(...start, 12, 0, 0, NY), last = zonedWallClockToUtcSeconds(...end, 12, 0, 0, NY);
    for (let noon = first; noon <= last; noon += 86400) {
      const day = new Date(noon * 1000);
      if (day.getUTCDay() === 0 || day.getUTCDay() === 6) continue;
      const [y, m, d] = [day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate()];
      for (let slot = 0; slot < 13; slot++) out.push(bar(zonedWallClockToUtcSeconds(y, m, d, 9, 30 + slot * 30, 0, NY)));
    }
    return out;
  }
  const bars = newYork([2026, 9, 14], [2026, 10, 12]);
  const sunday = at(2026, 9, 13);

  it('places the range when the calendar has no session before the first bar', async () => {
    const chart = makeChart(bars, '30m', ZONE);
    chart.setSessionCalendar(nyCalendar());
    const result = await new DateNavigator({ chart }).goTo({ from: sunday, to: bars[bars.length - 1]!.time });
    expect(result).toEqual({ status: 'placed', from: bars[0]!.time, to: bars[bars.length - 1]!.time });
  });

  it('asks no loader for history across a weekend no session traded in', async () => {
    const chart = makeChart(bars, '30m', ZONE);
    chart.setSessionCalendar(nyCalendar());
    const loadHistory = vi.fn(async (): Promise<HistoryReach> => 'exhausted');
    const result = await new DateNavigator({ chart, loadHistory }).goTo({ from: sunday, to: bars[bars.length - 1]!.time });
    expect(loadHistory).not.toHaveBeenCalled();
    expect(result.status).toBe('placed');
  });

  it('still reports the gap when a session opened in it', async () => {
    // Monday traded and is missing: the history really is short.
    const chart = makeChart(bars.slice(13), '30m', ZONE);
    chart.setSessionCalendar(nyCalendar());
    expect(await new DateNavigator({ chart }).goTo({ from: sunday, to: bars[bars.length - 1]!.time }))
      .toEqual({ status: 'partial', history: 'unavailable', from: bars[13]!.time, to: bars[bars.length - 1]!.time });
  });

  it('keeps counting the gap as short when the calendar finds no session at all', async () => {
    // A calendar's search has a horizon, so finding nothing does not prove the gap is empty.
    const chart = makeChart(bars, '30m', ZONE);
    chart.setSessionCalendar({ sessionFrom: () => null });
    expect(await new DateNavigator({ chart }).goTo({ from: sunday, to: bars[bars.length - 1]!.time }))
      .toEqual({ status: 'partial', history: 'unavailable', from: bars[0]!.time, to: bars[bars.length - 1]!.time });
  });

  it('keeps counting any gap as short without a calendar', async () => {
    const chart = makeChart(bars, '30m', ZONE);
    expect(await new DateNavigator({ chart }).goTo({ from: sunday, to: bars[bars.length - 1]!.time }))
      .toEqual({ status: 'partial', history: 'unavailable', from: bars[0]!.time, to: bars[bars.length - 1]!.time });
  });
});
