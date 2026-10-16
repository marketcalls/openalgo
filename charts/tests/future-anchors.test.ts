/**
 * Anchors past the last bar: which time a logical index to the right of the
 * data means, and back.
 *
 * The axis is gapless, so the empty space right of the last candle has no bars
 * to read times from. It used to be extrapolated at the gap between the last
 * two bars, which is the one gap most likely to be a weekend or an overnight
 * close: a Monday opening bar after a Friday close put every future anchor
 * about three days apart. These cases pin the two answers that replace it: the
 * trading calendar when the host supplied one, and otherwise the median of
 * recent bar spacing.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { DataLayer, type SessionCalendarSource } from '../src/model/data-layer';
import { Instrument, SessionCalendar, type InstrumentMetadata } from '../src/feed/instrument';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

const MIN = 60;
/** An IST wall-clock time as UTC seconds. */
const ist = (wall: string): number => Date.parse(`${wall}+05:30`) / 1000;
const bar = (time: number): Bar => ({ time, open: 100, high: 101, low: 99, close: 100 });

/** Five-minute bars covering one IST cash session, 09:15 to 15:25 inclusive. */
function session(date: string, from = '09:15', to = '15:25'): number[] {
  const out: number[] = [];
  for (let t = ist(`${date}T${from}:00`); t <= ist(`${date}T${to}:00`); t += 5 * MIN) out.push(t);
  return out;
}

function layer(times: readonly number[], calendar?: SessionCalendarSource | null): DataLayer {
  const d = new DataLayer();
  d.setSeriesData(d.createSeries(), times.map(bar));
  if (calendar !== undefined) d.setSessionCalendar(calendar);
  return d;
}

const nse = (): SessionCalendar => new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'] });

// 2026-02-02 is a Monday; 2026-02-06 the Friday of that week.
const WEEK = ['2026-02-02', '2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06'];

describe('future anchors without a session calendar', () => {
  it('a Friday-to-Monday gap between the last two daily bars does not set the spacing', () => {
    // Daily bars stamped at IST midnight, Monday to Friday, then the next Monday.
    const times = [...WEEK, '2026-02-09'].map(date => ist(`${date}T00:00:00`));
    const d = layer(times);
    const n = times.length;
    // One bar past Monday is Tuesday, not Thursday.
    expect(d.indexToTimeFloat(n)).toBe(ist('2026-02-10T00:00:00'));
    expect(d.indexToTimeFloat(n + 2)).toBe(ist('2026-02-12T00:00:00'));
    expect(d.timeToIndexFloat(ist('2026-02-10T00:00:00'))).toBe(n);
    expect(d.timeToIndexFloat(ist('2026-02-10T12:00:00'))).toBeCloseTo(n + 0.5, 9);
  });

  it('an intraday overnight gap between the last two bars does not set the spacing', () => {
    // Monday's whole session and Tuesday's opening bar: the last gap is 17h50m.
    const times = [...session('2026-02-02'), ist('2026-02-03T09:15:00')];
    const d = layer(times);
    const n = times.length;
    expect(d.indexToTimeFloat(n)).toBe(ist('2026-02-03T09:20:00'));
    expect(d.indexToTimeFloat(n + 3)).toBe(ist('2026-02-03T09:35:00'));
    expect(d.indexToTimeFloat(n + 0.5)).toBe(ist('2026-02-03T09:22:30'));
    expect(d.timeToIndexFloat(ist('2026-02-03T09:35:00'))).toBe(n + 3);
  });

  it('uses the recent median rather than one outlier when the data has few bars', () => {
    // Thursday, Friday, Monday: two gaps, one of them a weekend.
    const times = ['2026-02-05', '2026-02-06', '2026-02-09'].map(date => ist(`${date}T00:00:00`));
    expect(layer(times).indexToTimeFloat(3)).toBe(ist('2026-02-10T00:00:00'));
  });

  it('leaves the left of the first bar at the first gap', () => {
    // Friday then the whole next week: the first gap is the weekend. Only the
    // right edge changed; positions before the first loaded bar, and the linked
    // ranges built on them, read as they always have.
    const times = ['2026-02-06', '2026-02-09', '2026-02-10', '2026-02-11', '2026-02-12', '2026-02-13']
      .map(date => ist(`${date}T00:00:00`));
    const d = layer(times);
    expect(d.indexToTimeFloat(-1)).toBe(ist('2026-02-03T00:00:00'));
    expect(d.timeToIndexFloat(ist('2026-02-03T00:00:00'))).toBe(-1);
  });

  it('keeps even spacing exactly as before', () => {
    const times = Array.from({ length: 10 }, (_, i) => 1_700_000_000 + i * 300);
    const d = layer(times);
    expect(d.indexToTimeFloat(14)).toBe(1_700_000_000 + 14 * 300);
    expect(d.indexToTimeFloat(-2)).toBe(1_700_000_000 - 2 * 300);
    for (const index of [-3, 9, 9.5, 12.25, 40]) expect(d.timeToIndexFloat(d.indexToTimeFloat(index))).toBeCloseTo(index, 9);
  });
});

describe('future anchors with a session calendar', () => {
  it('a Friday-to-Monday gap: the bar after Friday\'s close is Monday\'s open', () => {
    const times = WEEK.flatMap(date => session(date));
    const d = layer(times, nse());
    const n = times.length;
    expect(d.indexToTimeFloat(n - 1)).toBe(ist('2026-02-06T15:25:00'));
    expect(d.indexToTimeFloat(n)).toBe(ist('2026-02-09T09:15:00'));
    expect(d.indexToTimeFloat(n + 2)).toBe(ist('2026-02-09T09:25:00'));
    // A whole session later: 75 bars a day.
    expect(d.indexToTimeFloat(n + 75)).toBe(ist('2026-02-10T09:15:00'));
    expect(d.timeToIndexFloat(ist('2026-02-09T09:25:00'))).toBe(n + 2);
    expect(d.timeToIndexFloat(ist('2026-02-10T09:15:00'))).toBe(n + 75);
  });

  it('a Friday-to-Monday gap on daily bars skips the weekend', () => {
    const times = [...WEEK, '2026-02-09', '2026-02-10', '2026-02-11', '2026-02-12', '2026-02-13']
      .map(date => ist(`${date}T00:00:00`));
    const d = layer(times, nse());
    const n = times.length;
    expect(d.indexToTimeFloat(n)).toBe(ist('2026-02-16T00:00:00'));
    expect(d.indexToTimeFloat(n + 1)).toBe(ist('2026-02-17T00:00:00'));
    expect(d.indexToTimeFloat(n + 5)).toBe(ist('2026-02-23T00:00:00'));
    expect(d.timeToIndexFloat(ist('2026-02-23T00:00:00'))).toBe(n + 5);
  });

  it('an intraday overnight gap: the bar after the close is the next morning\'s open', () => {
    const times = [...session('2026-02-02'), ...session('2026-02-03')];
    const d = layer(times, nse());
    const n = times.length;
    expect(d.indexToTimeFloat(n)).toBe(ist('2026-02-04T09:15:00'));
    expect(d.indexToTimeFloat(n + 1)).toBe(ist('2026-02-04T09:20:00'));
    // Mid-session data runs on to the close first, then jumps the night.
    const partial = [...session('2026-02-02'), ...session('2026-02-03', '09:15', '15:10')];
    const p = layer(partial, nse());
    const m = partial.length;
    expect(p.indexToTimeFloat(m)).toBe(ist('2026-02-03T15:15:00'));
    expect(p.indexToTimeFloat(m + 2)).toBe(ist('2026-02-03T15:25:00'));
    expect(p.indexToTimeFloat(m + 3)).toBe(ist('2026-02-04T09:15:00'));
  });

  it('an overnight gap in the last two bars no longer spaces the future', () => {
    // The same data as the calendar-free overnight case: Tuesday's first bar last.
    const times = [...session('2026-02-02'), ist('2026-02-03T09:15:00')];
    const d = layer(times, nse());
    expect(d.indexToTimeFloat(times.length)).toBe(ist('2026-02-03T09:20:00'));
  });

  it('skips a date the calendar closes', () => {
    // 2026-02-09 closed: Friday's close is followed by Tuesday's open.
    const calendar = new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'], exceptions: { '2026-02-09': [] } });
    const times = WEEK.flatMap(date => session(date));
    const d = layer(times, calendar);
    expect(d.indexToTimeFloat(times.length)).toBe(ist('2026-02-10T09:15:00'));
    // And a shortened day ends early.
    const short = new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'], exceptions: { '2026-02-09': ['0915-1000'] } });
    const s = layer(times, short);
    expect(s.indexToTimeFloat(times.length + 8)).toBe(ist('2026-02-09T09:55:00'));
    expect(s.indexToTimeFloat(times.length + 9)).toBe(ist('2026-02-10T09:15:00'));
  });

  it('follows a lunch break inside a day', () => {
    const calendar = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1130:23456', '1300-1500:23456'] });
    const utc = (wall: string): number => Date.parse(`${wall}Z`) / 1000;
    const times: number[] = [];
    for (let t = utc('2026-02-03T09:00:00'); t < utc('2026-02-03T11:30:00'); t += 15 * MIN) times.push(t);
    const d = layer(times, calendar);
    expect(d.indexToTimeFloat(times.length - 1)).toBe(utc('2026-02-03T11:15:00'));
    expect(d.indexToTimeFloat(times.length)).toBe(utc('2026-02-03T13:00:00'));
    expect(d.indexToTimeFloat(times.length + 8)).toBe(utc('2026-02-04T09:00:00'));
  });

  it('keeps a feed\'s clock-aligned first bar before a quarter-past open', () => {
    // Hourly bars stamped on the hour, the first one 09:00 for a 09:15 open.
    const times = ['2026-02-02', '2026-02-03'].flatMap(date =>
      ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'].map(h => ist(`${date}T${h}:00`)));
    const d = layer(times, nse());
    expect(d.indexToTimeFloat(times.length)).toBe(ist('2026-02-04T09:00:00'));
    expect(d.indexToTimeFloat(times.length + 1)).toBe(ist('2026-02-04T10:00:00'));
  });

  it('interpolates across the closed hours and round-trips', () => {
    const times = WEEK.flatMap(date => session(date));
    const d = layer(times, nse());
    const n = times.length;
    // Saturday noon lies inside the weekend, between Friday's last bar and Monday's first slot.
    const saturday = d.timeToIndexFloat(ist('2026-02-07T12:00:00'));
    expect(saturday).toBeGreaterThan(n - 1);
    expect(saturday).toBeLessThan(n);
    expect(d.indexToTimeFloat(saturday)).toBeCloseTo(ist('2026-02-07T12:00:00'), 3);
    for (const index of [n - 1, n - 0.5, n, n + 0.25, n + 74.5, n + 300, n + 5000]) {
      expect(d.timeToIndexFloat(d.indexToTimeFloat(index))).toBeCloseTo(index, 6);
    }
  });

  it('stays finite, monotonic and bounded in cost for far-future times', () => {
    const times = WEEK.flatMap(date => session(date));
    const d = layer(times, nse());
    const n = times.length;
    const started = performance.now();
    const far = d.timeToIndexFloat(ist('2031-01-01T10:00:00'));
    const farther = d.timeToIndexFloat(ist('2036-01-01T10:00:00'));
    expect(Number.isFinite(far)).toBe(true);
    expect(farther).toBeGreaterThan(far);
    expect(d.indexToTimeFloat(far)).toBeCloseTo(ist('2031-01-01T10:00:00'), 0);
    let previous = -Infinity;
    for (let i = n - 1; i < n + 20_000; i += 997) {
      const t = d.indexToTimeFloat(i);
      expect(t).toBeGreaterThan(previous);
      previous = t;
    }
    expect(performance.now() - started).toBeLessThan(2000);
  });

  it('ignores a calendar the bars disagree with and falls back to the median', () => {
    // US hours against IST session bars: no bar sits in a New York session.
    const us = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'] });
    const times = [...session('2026-02-02'), ist('2026-02-03T09:15:00')];
    expect(layer(times, us).indexToTimeFloat(times.length)).toBe(ist('2026-02-03T09:20:00'));
  });

  it('never throws from a calendar that throws; the median answers instead', () => {
    const broken: SessionCalendarSource = { sessionFrom: () => { throw new Error('boundary is absent'); } };
    const times = [...session('2026-02-02'), ist('2026-02-03T09:15:00')];
    const d = layer(times, broken);
    expect(d.indexToTimeFloat(times.length)).toBe(ist('2026-02-03T09:20:00'));
    expect(d.timeToIndexFloat(ist('2026-02-03T09:20:00'))).toBe(times.length);
  });

  it('follows a live append and a replaced calendar', () => {
    const times = WEEK.flatMap(date => session(date, '09:15', '15:20'));
    const d = new DataLayer();
    const id = d.createSeries();
    d.setSeriesData(id, times.map(bar));
    d.setSessionCalendar(nse());
    expect(d.indexToTimeFloat(times.length + 1)).toBe(ist('2026-02-09T09:15:00'));
    expect(d.update(id, bar(ist('2026-02-06T15:25:00')))).toBe('append');
    expect(d.indexToTimeFloat(times.length + 1)).toBe(ist('2026-02-09T09:15:00'));
    expect(d.indexToTimeFloat(times.length + 2)).toBe(ist('2026-02-09T09:20:00'));
    d.setSessionCalendar(null);
    expect(d.sessionCalendar).toBeNull();
    expect(d.indexToTimeFloat(times.length + 1)).toBe(ist('2026-02-06T15:30:00'));
  });
});

describe('future anchors when the windows of a day open off one bar grid', () => {
  // A lunch break of 09:00-11:30 and 12:30-15:00: an hourly bar grid on the
  // clock meets the morning opening on a bar and the afternoon one half a bar
  // in, so each window has its own offset from its opening.
  const lunch = (exceptions?: Record<string, string[]>): SessionCalendar =>
    new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1130:23456', '1230-1500:23456'], ...(exceptions ? { exceptions } : {}) });
  const utc = (wall: string): number => Date.parse(`${wall}:00Z`) / 1000;
  const HOURS = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00'];
  const hourly = (dates: readonly string[], hours = HOURS): number[] =>
    dates.flatMap(date => hours.map(h => utc(`${date}T${h}`)));
  const ahead = (d: DataLayer, n: number, count: number): number[] =>
    Array.from({ length: count }, (_, k) => d.indexToTimeFloat(n + k));

  it('keeps every window on the clock when the last bar is in the afternoon', () => {
    const times = hourly(['2026-02-02', '2026-02-03']);
    const d = layer(times, lunch());
    expect(ahead(d, times.length, 7)).toEqual(['2026-02-04T09:00', '2026-02-04T10:00', '2026-02-04T11:00',
      '2026-02-04T12:00', '2026-02-04T13:00', '2026-02-04T14:00', '2026-02-05T09:00'].map(utc));
    for (const k of [0, 3, 6]) expect(d.timeToIndexFloat(d.indexToTimeFloat(times.length + k))).toBe(times.length + k);
  });

  it('keeps every window on the clock when the last bar is in the morning', () => {
    const times = [...hourly(['2026-02-02', '2026-02-03']), ...hourly(['2026-02-04'], ['09:00', '10:00', '11:00'])];
    const d = layer(times, lunch());
    expect(ahead(d, times.length, 4)).toEqual(['2026-02-04T12:00', '2026-02-04T13:00', '2026-02-04T14:00',
      '2026-02-05T09:00'].map(utc));
  });

  it('keeps bars that start again at each opening on those openings', () => {
    // 12:30, not 12:00: this feed restarts its grid after lunch.
    const times = hourly(['2026-02-02', '2026-02-03'], ['09:00', '10:00', '11:00', '12:30', '13:30', '14:30']);
    const d = layer(times, lunch());
    expect(ahead(d, times.length, 7)).toEqual(['2026-02-04T09:00', '2026-02-04T10:00', '2026-02-04T11:00',
      '2026-02-04T12:30', '2026-02-04T13:30', '2026-02-04T14:30', '2026-02-05T09:00'].map(utc));
  });

  it('keeps a half day\'s morning on the clock', () => {
    // Wednesday closes at 11:30.
    const times = hourly(['2026-02-02', '2026-02-03']);
    const d = layer(times, lunch({ '2026-02-04': ['0900-1130'] }));
    expect(ahead(d, times.length, 4)).toEqual(['2026-02-04T09:00', '2026-02-04T10:00', '2026-02-04T11:00',
      '2026-02-05T09:00'].map(utc));
  });

  it('a window whose opening no bar has shown keeps the last bar\'s offset', () => {
    // US hours in New York, two-hour bars from each opening. The bars end
    // before the clocks change on 8 March, so Monday's opening is an hour
    // earlier in UTC than any the bars sat in, and still 09:30 in New York.
    const ny = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'] });
    const et = (wall: string, offset: string): number => Date.parse(`${wall}:00${offset}`) / 1000;
    const times = ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-05', '2026-03-06']
      .flatMap(date => ['09:30', '11:30', '13:30', '15:30'].map(h => et(`${date}T${h}`, '-05:00')));
    const d = layer(times, ny);
    expect(ahead(d, times.length, 5)).toEqual([et('2026-03-09T09:30', '-04:00'), et('2026-03-09T11:30', '-04:00'),
      et('2026-03-09T13:30', '-04:00'), et('2026-03-09T15:30', '-04:00'), et('2026-03-10T09:30', '-04:00')]);
  });
});

describe('the calendar reaches the data layer', () => {
  const charts: Chart[] = [];
  afterEach(() => { for (const c of charts.splice(0)) c.destroy(); });
  const cash = (): InstrumentMetadata => ({
    symbol: 'CASH', exchange: 'NSE', timezone: 'Asia/Kolkata', priceTick: 0.05, pricePrecision: 2,
    quantityStep: 1, intervals: ['5m', 'D'], calendar: { sessions: ['0915-1530:23456'] },
  });

  it('Instrument.applyTo hands its calendar to the chart, and a pointer past the last bar reads its time', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 }, pixelRatio: () => 1 });
    charts.push(chart);
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    const instrument = new Instrument(cash());
    instrument.applyTo(chart, '5m');
    expect(chart.dataLayer.sessionCalendar).toBe(instrument);
    const times = WEEK.flatMap(date => session(date));
    series.setData(times.map(bar));
    const monday = ist('2026-02-09T09:25:00');
    const x = chart.timeToCoordinate(monday);
    expect(chart.coordinateToTime(x)).toBeCloseTo(monday, 3);
    expect(chart.dataLayer.timeToIndexFloat(monday)).toBe(times.length + 2);
  });

  /** A measured chart whose frames wait until `flush`, so a test can see whether anything asked for one. */
  function idleChart(): { chart: Chart; flush: () => void } {
    const frames: (() => void)[] = [];
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, pixelRatio: () => 1,
      raf: { schedule: (cb: () => void) => { frames.push(cb); return frames.length; }, cancel: () => {} } });
    charts.push(chart);
    chart.applySize(800, 600);
    return { chart, flush: () => { while (frames.length) frames.shift()!(); } };
  }

  /** The x each paint gives a time, as a drawing anchored there would be placed. */
  function paintedAt(chart: Chart, time: number): number[] {
    const painted: number[] = [];
    chart.addPrimitive({ zOrder: () => 'top', draw: (_ctx, rc) => { painted.push(rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(time))); } });
    return painted;
  }

  it("an instrument's hours leave with its symbol when the host moves on without one", () => {
    const { chart, flush } = idleChart();
    const series = chart.addSeries('candlestick');
    new Instrument(cash()).applyTo(chart, '5m');
    // The host switches to a round-the-clock symbol it holds no instrument for,
    // and its bars happen to sit inside the cash session's hours.
    chart.setDataContext({ symbol: 'BTCUSD', exchange: 'CRYPTO', interval: '5m' });
    const times = Array.from({ length: 40 }, (_, i) => ist('2026-02-04T12:00:00') + i * 5 * MIN);
    series.setData(times.map(bar));
    flush();
    // Ten bars on is fifty minutes later, not the cash market's next morning.
    expect(chart.dataLayer.indexToTimeFloat(times.length - 1 + 10)).toBe(times[times.length - 1] + 50 * MIN);
    expect(chart.dataLayer.sessionCalendar).toBeNull();
  });

  it("keeps an instrument's hours across an interval change, and a host calendar across a symbol change", () => {
    const { chart } = idleChart();
    chart.addSeries('candlestick');
    const instrument = new Instrument(cash());
    instrument.applyTo(chart, '5m');
    chart.setDataContext({ symbol: 'CASH', exchange: 'NSE', interval: 'D' });
    expect(chart.dataLayer.sessionCalendar).toBe(instrument);
    const next = new Instrument({ ...cash(), symbol: 'NEXT' });
    next.applyTo(chart, '5m');
    expect(chart.dataLayer.sessionCalendar).toBe(next);
    // Venue hours a host set itself are the host's to replace.
    const venue = nse();
    chart.dataLayer.setSessionCalendar(venue);
    chart.setDataContext({ symbol: 'OTHER', exchange: 'NSE', interval: '5m' });
    expect(chart.dataLayer.sessionCalendar).toBe(venue);
  });

  it('SessionCalendar.applyTo repaints what an idle chart already shows past the last bar', () => {
    const { chart, flush } = idleChart();
    const times = WEEK.flatMap(date => session(date));
    chart.addSeries('candlestick').setData(times.map(bar));
    const monday = ist('2026-02-09T09:25:00');
    const painted = paintedAt(chart, monday);
    flush();
    const before = painted.length;
    // Hours that arrive after the chart went idle, as metadata fetched late does.
    nse().applyTo(chart);
    flush();
    expect(painted.length).toBeGreaterThan(before);
    expect(painted[painted.length - 1]).toBe(chart.timeScale.indexToX(times.length + 2));
  });

  it('re-applying an instrument with new hours repaints an idle chart', () => {
    const { chart, flush } = idleChart();
    const series = chart.addSeries('candlestick');
    new Instrument(cash()).applyTo(chart, '5m');
    const times = WEEK.flatMap(date => session(date));
    series.setData(times.map(bar));
    const tuesday = ist('2026-02-10T09:25:00');
    const painted = paintedAt(chart, tuesday);
    flush();
    const before = painted.length;
    // The same symbol and interval, now with Monday closed.
    new Instrument({ ...cash(), calendar: { sessions: ['0915-1530:23456'], exceptions: { '2026-02-09': [] } } }).applyTo(chart, '5m');
    flush();
    expect(painted.length).toBeGreaterThan(before);
    expect(painted[painted.length - 1]).toBe(chart.timeScale.indexToX(times.length + 2));
  });

  it('chart.setSessionCalendar moves what an idle chart already shows past the last bar', () => {
    const { chart, flush } = idleChart();
    const times = WEEK.flatMap(date => session(date));
    chart.addSeries('candlestick').setData(times.map(bar));
    const monday = ist('2026-02-09T09:25:00');
    const painted = paintedAt(chart, monday);
    flush();
    const before = painted.length;
    const where = painted[before - 1];
    // A host setting hours it built itself, with no Instrument or applyTo involved.
    chart.setSessionCalendar(nse());
    flush();
    expect(painted.length).toBeGreaterThan(before);
    expect(painted[painted.length - 1]).toBe(chart.timeScale.indexToX(times.length + 2));
    expect(painted[painted.length - 1]).not.toBe(where);
    // And null drops them the same way: the anchor goes back to the median spacing.
    const withHours = painted.length;
    chart.setSessionCalendar(null);
    flush();
    expect(chart.dataLayer.sessionCalendar).toBeNull();
    expect(painted.length).toBeGreaterThan(withHours);
    expect(painted[painted.length - 1]).toBe(where);
  });

  it('dataLayer.setSessionCalendar stays the path that asks for no frame', () => {
    const { chart, flush } = idleChart();
    const times = WEEK.flatMap(date => session(date));
    chart.addSeries('candlestick').setData(times.map(bar));
    const painted = paintedAt(chart, ist('2026-02-09T09:25:00'));
    flush();
    const before = painted.length;
    chart.dataLayer.setSessionCalendar(nse());
    flush();
    // Set, but not painted until something else asks for a frame.
    expect(chart.dataLayer.sessionCalendar).not.toBeNull();
    expect(painted.length).toBe(before);
  });

  it('chart.setSessionCalendar does nothing to a destroyed chart', () => {
    const { chart } = idleChart();
    chart.destroy();
    expect(() => chart.setSessionCalendar(nse())).not.toThrow();
    expect(chart.dataLayer.sessionCalendar).toBeNull();
  });
});
