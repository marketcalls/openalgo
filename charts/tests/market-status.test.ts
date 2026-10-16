/**
 * Market status derived from a session calendar, for a host that supplies
 * none. A readout reads a phase and the instant it changes: an answer that is
 * right at 10:00 and silently stale at 15:30 is the failure being guarded.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { Instrument, SessionCalendar, type InstrumentMetadata } from '../src/feed/instrument';
import { calendarMarketPhase, marketStatusAt, partitionPhases, type SessionPhaseSource } from '../src/feed/market-status';
import { computePriceLevels } from '../src/primitives/price-levels';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

const time = (iso: string): number => Date.parse(iso) / 1000;
const ist = (local: string): number => time(`${local}+05:30`);
const nse = (): InstrumentMetadata => ({
  symbol: 'CASH', exchange: 'NSE', timezone: 'Asia/Kolkata', priceTick: 0.05, pricePrecision: 2, quantityStep: 1,
  intervals: ['1m', '5m'],
  calendar: {
    sessions: ['0915-1530:23456'], preMarketMinutes: 15, postMarketMinutes: 30,
    // Republic Day closed, and the next day shortened.
    exceptions: { '2026-01-26': [], '2026-01-27': ['1000-1300'] },
  },
});

describe('market status at an instant', () => {
  const instrument = new Instrument(nse());
  const status = (local: string) => instrument.marketStatusAt(ist(local));

  it.each([
    ['2026-01-28T08:00:00', { phase: 'closed', changesAt: '2026-01-28T09:00:00', nextPhase: 'pre', opensAt: '2026-01-28T09:15:00', closesAt: '2026-01-28T15:30:00' }],
    ['2026-01-28T09:05:00', { phase: 'pre', changesAt: '2026-01-28T09:15:00', nextPhase: 'regular', opensAt: '2026-01-28T09:15:00', closesAt: '2026-01-28T15:30:00' }],
    ['2026-01-28T09:15:00', { phase: 'regular', changesAt: '2026-01-28T15:30:00', nextPhase: 'post', opensAt: '2026-01-28T09:15:00', closesAt: '2026-01-28T15:30:00' }],
    ['2026-01-28T12:47:13', { phase: 'regular', changesAt: '2026-01-28T15:30:00', nextPhase: 'post', opensAt: '2026-01-28T09:15:00', closesAt: '2026-01-28T15:30:00' }],
    ['2026-01-28T15:45:00', { phase: 'post', changesAt: '2026-01-28T16:00:00', nextPhase: 'closed', opensAt: '2026-01-29T09:15:00', closesAt: '2026-01-29T15:30:00' }],
    // Friday evening: the weekend runs into the Monday holiday, and the next
    // opening is Tuesday's shortened session.
    ['2026-01-23T20:00:00', { phase: 'closed', changesAt: '2026-01-26T00:00:00', nextPhase: 'holiday', opensAt: '2026-01-27T10:00:00', closesAt: '2026-01-27T13:00:00' }],
    ['2026-01-26T11:00:00', { phase: 'holiday', changesAt: '2026-01-27T00:00:00', nextPhase: 'closed', opensAt: '2026-01-27T10:00:00', closesAt: '2026-01-27T13:00:00' }],
    ['2026-01-27T12:59:59', { phase: 'regular', changesAt: '2026-01-27T13:00:00', nextPhase: 'post', opensAt: '2026-01-27T10:00:00', closesAt: '2026-01-27T13:00:00' }],
  ])('at %s IST', (local, expected) => {
    expect(status(local)).toEqual({
      ...expected,
      changesAt: ist(expected.changesAt), opensAt: ist(expected.opensAt), closesAt: ist(expected.closesAt),
    });
  });

  it('follows daylight saving in a zone that has it', () => {
    const ny = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'], preMarketMinutes: 330, postMarketMinutes: 240 });
    // Sunday 8 March 2026, the day the clocks go forward: Monday's pre-open
    // opens at 04:00 EDT, 08:00 UTC, where the Friday before opened at 09:00 UTC.
    expect(ny.marketStatusAt(time('2026-03-08T12:00:00Z'))).toEqual({
      phase: 'closed', changesAt: time('2026-03-09T08:00:00Z'), nextPhase: 'pre',
      opensAt: time('2026-03-09T13:30:00Z'), closesAt: time('2026-03-09T20:00:00Z'),
    });
    expect(ny.marketStatusAt(time('2026-03-06T08:30:00Z')).changesAt).toBe(time('2026-03-06T09:00:00Z'));
  });

  it('has no next change for a round-the-clock market, or for one that never opens', () => {
    const crypto = new SessionCalendar({ timezone: 'UTC', sessions: ['0000-0000'] });
    expect(crypto.marketStatusAt(time('2026-01-28T10:00:00Z')))
      .toEqual({ phase: 'regular', changesAt: null, nextPhase: null, opensAt: null, closesAt: null });
    const never = new SessionCalendar({ timezone: 'UTC', sessions: [] });
    expect(never.marketStatusAt(time('2026-01-28T10:00:00Z')))
      .toEqual({ phase: 'closed', changesAt: null, nextPhase: null, opensAt: null, closesAt: null });
  });

  it('throws near a date whose window a clock change removes, as the docs say, and answers away from it', () => {
    // 02:30 does not exist in New York on Sunday 8 March 2026.
    const gap = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0230-1600'] });
    const day = (offset: number): number => time('2026-03-08T15:00:00Z') + offset * 86400;
    for (const offset of [-15, -1, 0, 4]) expect(() => gap.marketStatusAt(day(offset))).toThrow(/session boundary is absent/);
    for (const offset of [-16, 5]) expect(gap.marketStatusAt(day(offset)).phase).toBe('regular');
    for (const offset of [-1, 2]) expect(() => gap.phaseAt(day(offset))).toThrow(/session boundary is absent/);
    for (const offset of [-2, 3]) expect(gap.phaseAt(day(offset))).toBe('regular');
  });

  it('answers the same from the free function, for any source that lays out phases', () => {
    const at = ist('2026-01-28T09:05:00');
    expect(marketStatusAt(instrument, at)).toEqual(instrument.marketStatusAt(at));
    // Hours with `sessionFrom` alone cannot say, and neither can nothing.
    expect(marketStatusAt({ sessionFrom: () => null } as never, at)).toBeNull();
    expect(marketStatusAt(null, at)).toBeNull();
    // A host's own source that leaves the instant uncovered reads as closed.
    const gappy: SessionPhaseSource = { phaseSpans: () => [] };
    expect(marketStatusAt(gappy, at)).toEqual({ phase: 'closed', changesAt: null, nextPhase: null, opensAt: null, closesAt: null });
  });
});

describe('the status of the hours a chart was given', () => {
  const charts: Chart[] = [];
  afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

  it('reads the instrument applied to a chart, and nothing once the chart drops it', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 } });
    charts.push(chart); chart.applySize(800, 600); chart.addSeries('candlestick');
    const at = ist('2026-01-28T15:45:00');
    expect(marketStatusAt(chart.dataLayer.sessionCalendar, at)).toBeNull();
    new Instrument(nse()).applyTo(chart, '1m');
    expect(marketStatusAt(chart.dataLayer.sessionCalendar, at)?.phase).toBe('post');
    chart.setDataContext({ symbol: 'OTHER', exchange: 'NSE', interval: '1m' });
    expect(marketStatusAt(chart.dataLayer.sessionCalendar, at)).toBeNull();
  });
});

describe('phase partition', () => {
  it('cuts a range into consecutive spans by precedence and merges neighbours in one phase', () => {
    expect(partitionPhases(0, 100, [
      { rank: 3, start: -50, end: 40 },   // extended, clipped at the range start
      { rank: 0, start: 20, end: 30 },    // regular inside it wins
      { rank: 0, start: 30, end: 35 },    // and an abutting window merges with it
      { rank: 4, start: 60, end: 200 },   // holiday, clipped at the end
      { rank: 2, start: 70, end: 80 },    // post-close beats the holiday
      { rank: 1, start: 120, end: 130 },  // wholly outside: dropped
    ])).toEqual([
      { phase: 'extended', start: 0, end: 20 },
      { phase: 'regular', start: 20, end: 35 },
      { phase: 'extended', start: 35, end: 40 },
      { phase: 'closed', start: 40, end: 60 },
      { phase: 'holiday', start: 60, end: 70 },
      { phase: 'post', start: 70, end: 80 },
      { phase: 'holiday', start: 80, end: 100 },
    ]);
    expect(partitionPhases(0, 10, [])).toEqual([{ phase: 'closed', start: 0, end: 10 }]);
  });
});

describe('a price-levels phase classifier from the calendar', () => {
  // One New York day of 30-minute bars from 04:00 to 20:00 EDT, a random walk.
  const ny = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'], preMarketMinutes: 330, postMarketMinutes: 240 });
  let seed = 7;
  const random = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const bars: Bar[] = [];
  for (let t = time('2026-06-17T08:00:00Z'), close = 212.4; t < time('2026-06-18T00:00:00Z'); t += 1800) {
    const open = close; close = +(open * (1 + (random() - 0.5) * 0.006)).toFixed(2);
    bars.push({ time: t, open, high: Math.max(open, close) + 0.1, low: Math.min(open, close) - 0.1, close, volume: 1000 });
  }

  it('classifies each bar by the calendar and feeds the extended-hours levels', () => {
    const phase = calendarMarketPhase(ny);
    const phases = bars.map(bar => phase(bar));
    // 04:00 to 09:30 is eleven bars, 09:30 to 16:00 thirteen, 16:00 to 20:00 eight.
    expect(phases.filter(p => p === 'pre')).toHaveLength(11);
    expect(phases.filter(p => p === 'regular')).toHaveLength(13);
    expect(phases.filter(p => p === 'post')).toHaveLength(8);
    const levels = computePriceLevels({ bars, anchorTime: bars[bars.length - 1].time, timezone: 'America/New_York', marketPhase: phase });
    expect(levels.preMarketOpen).toBe(bars[0].open);
    expect(levels.preMarketClose).toBe(bars[10].close);
    expect(levels.postMarketOpen).toBe(bars[24].open);
    expect(levels.postMarketClose).toBe(bars[31].close);
  });

  it('asks the calendar once for a week of bars, and again only outside it', () => {
    let calls = 0;
    const counting: SessionPhaseSource = { phaseSpans: (from, to) => { calls++; return ny.phaseSpans(from, to); } };
    const phase = calendarMarketPhase(counting);
    for (let frame = 0; frame < 3; frame++) for (const bar of bars) phase(bar);
    expect(calls).toBe(1);
    expect(phase({ ...bars[0], time: bars[0].time + 30 * 86400 })).toBe('pre');
    expect(calls).toBe(2);
    // Out of order is still right, only slower.
    expect(phase({ ...bars[0], time: bars[0].time + 30 * 86400 + 6 * 3600 })).toBe('regular');
    expect(phase({ ...bars[0], time: bars[0].time + 30 * 86400 })).toBe('pre');
  });

  it('reads extended hours, closed hours and a calendar that cannot answer as unknown', () => {
    const overnight = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1700:23456'], extendedHours: ['1800-2200:23456'] });
    const phase = calendarMarketPhase(overnight);
    expect(phase({ ...bars[0], time: time('2026-06-17T19:00:00Z') })).toBeNull();
    expect(phase({ ...bars[0], time: time('2026-06-17T23:00:00Z') })).toBeNull();
    expect(phase({ ...bars[0], time: NaN })).toBeNull();
    const broken = calendarMarketPhase({ phaseSpans: () => { throw new Error('no hours'); } });
    expect(broken(bars[0])).toBeNull();
  });
});
