import { afterEach, describe, expect, it, vi } from 'vitest';
import { Instrument, SessionCalendar, type InstrumentMetadata } from '../src/feed/instrument';
import { orderConstraintsForInstrument } from '../src/trade/instrument';
import { validatePrice, validateQuantity } from '../src/trade/validation';
import { CandleBuilder } from '../src/feed/candle-builder';
import { Chart } from '../src/core/chart';
import type { PriceScaleId } from '../src/model/series';
import { fakeDocument } from './helpers/fake-dom';
import { roundToTick } from '../src/helpers/math';
import '../src/indicators/index';

const cash = (): InstrumentMetadata => ({
  symbol: 'CASH', exchange: 'NSE', timezone: 'Asia/Kolkata',
  priceTick: 0.05, pricePrecision: 2, quantityStep: 1,
  intervals: ['1m', '1h', 'D'], hasOpenInterest: false,
  calendar: { sessions: ['0915-1530:23456'], exceptions: { '2026-01-26': [], '2026-01-27': ['1000-1300'] } },
});
const time = (iso: string): number => Date.parse(iso) / 1000;
const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });
function chart(priceScaleId: PriceScaleId = 'right') {
  const doc = fakeDocument();
  const c = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 } });
  charts.push(c); c.applySize(800, 600); c.addSeries('candlestick', { priceScaleId }); return c;
}

describe('instrument metadata', () => {
  it('detaches and freezes metadata while omitting unrelated source fields', () => {
    const source = { ...cash(), apiKey: 'not-metadata', intervals: ['1m', '1h', 'D'],
      calendar: { sessions: ['0915-1530:23456'], exceptions: { '2026-01-26': [] } } };
    const instrument = new Instrument(source);
    source.calendar.sessions[0] = '0000-0000'; source.intervals.push('5m');
    expect(instrument.metadata.calendar.sessions).toEqual(['0915-1530:23456']);
    expect(instrument.metadata.intervals).toEqual(['1m', '1h', 'D']);
    expect(instrument.metadata).not.toHaveProperty('apiKey');
    expect(Object.isFrozen(instrument.metadata)).toBe(true);
    expect(Object.isFrozen(instrument.metadata.calendar.exceptions!['2026-01-26'])).toBe(true);
  });

  it.each([
    { symbol: '' }, { timezone: 'Mars/City' }, { priceTick: 0 }, { priceTick: Infinity },
    { pricePrecision: -1 }, { pricePrecision: 1 }, { quantityStep: NaN }, { quantityStep: 0 },
    { intervals: [] }, { intervals: ['0m'] }, { intervals: ['1m', '1m'] }, { hasOpenInterest: 'yes' },
    { calendar: { sessions: ['9999-9999'] } },
    { calendar: { sessions: [], exceptions: { '2026-02-30': [] } } },
  ])('rejects invalid contract before use: %j', patch => {
    expect(() => new Instrument({ ...cash(), ...patch })).toThrow();
  });

  // A host that logs or shows the refusal sees the same first fault as before
  // SessionCalendar shared this validation: the calendar object is checked
  // straight after the input, and its weekly sessions last.
  it.each([
    [{ timezone: 'Mars/City', calendar: 5 }, 'expected a plain object'],
    [{ priceTick: 0, calendar: Object.defineProperty({}, 'sessions', { get: () => [], enumerable: true }) }, 'accessors are not metadata'],
    [{ symbol: '', calendar: { sessions: ['bad'] } }, 'symbol'],
    [{ exchange: '', calendar: { sessions: ['bad'] } }, 'exchange'],
    [{ quantityStep: 0, calendar: { sessions: ['bad'] } }, 'quantity step'],
    [{ hasOpenInterest: 'yes', calendar: { sessions: ['bad'] } }, 'invalid OI capability'],
    [{ hasOpenInterest: 'yes', calendar: { sessions: [], exceptions: { '2026-02-30': [] } } }, 'invalid exception date'],
    [{ intervals: ['0m'], calendar: { sessions: [], exceptions: { '2026-02-30': [] } } }, 'unsupported interval 0m'],
    [{ timezone: 'Mars/City', calendar: { sessions: ['bad'] } }, 'unknown timezone'],
  ])('reports the first fault of several in a fixed order: %j', (patch, message) => {
    expect(() => new Instrument({ ...cash(), ...patch })).toThrow(new Error(`Invalid instrument: ${message}`));
  });

  it('preserves explicit and unknown OI capabilities independently of observations', () => {
    expect(new Instrument(cash()).metadata.hasOpenInterest).toBe(false);
    expect(new Instrument({ ...cash(), hasOpenInterest: true }).metadata.hasOpenInterest).toBe(true);
    const source = { ...cash(), hasOpenInterest: undefined };
    expect(new Instrument(source).metadata.hasOpenInterest).toBeUndefined();
  });

  it('matches exact provider interval tokens without confusing case or aliases', () => {
    const instrument = new Instrument(cash());
    expect(instrument.supportsInterval('1m')).toBe(true);
    expect(instrument.supportsInterval('1M')).toBe(false);
    expect(instrument.supportsInterval('1d')).toBe(false);
    expect(instrument.supportsInterval('D')).toBe(true);
  });
});

describe('instrument calendar', () => {
  it('honors opening-date closures and short sessions with half-open ends', () => {
    const instrument = new Instrument(cash());
    expect(instrument.sessionAt(time('2026-01-26T05:00:00Z'))).toBeNull();
    expect(instrument.sessionAt(time('2026-01-27T04:29:59Z'))).toBeNull();
    expect(instrument.sessionAt(time('2026-01-27T04:30:00Z'))).toEqual({
      date: '2026-01-27', open: time('2026-01-27T04:30:00Z'), close: time('2026-01-27T07:30:00Z'),
    });
    expect(instrument.sessionAt(time('2026-01-27T07:30:00Z'))).toBeNull();
    expect(instrument.sessionAt(time('2026-01-25T05:00:00Z'))).toBeNull();
  });

  it('keeps lunch breaks absent and overnight sessions on their opening date', () => {
    const split = new Instrument({ ...cash(), timezone: 'UTC', calendar: { sessions: ['0900-1200:23456', '1300-1600:23456'] } });
    expect(split.sessionAt(time('2026-01-28T12:30:00Z'))).toBeNull();
    expect(split.sessionAt(time('2026-01-28T13:00:00Z'))?.open).toBe(time('2026-01-28T13:00:00Z'));
    const overnight = new Instrument({ ...cash(), timezone: 'UTC', calendar: {
      sessions: ['2200-0200:23456'], exceptions: { '2026-01-27': [] },
    } });
    expect(overnight.sessionAt(time('2026-01-27T01:00:00Z'))?.date).toBe('2026-01-26');
    expect(overnight.sessionAt(time('2026-01-28T01:00:00Z'))).toBeNull();
  });

  it('supports continuous crypto sessions across weekends and UTC midnight', () => {
    const instrument = new Instrument({ ...cash(), timezone: 'UTC', calendar: { sessions: ['0000-0000'] } });
    expect(instrument.sessionAt(time('2026-01-25T23:59:59Z'))?.date).toBe('2026-01-25');
    expect(instrument.sessionAt(time('2026-01-26T00:00:00Z'))).toEqual({
      date: '2026-01-26', open: time('2026-01-26T00:00:00Z'), close: time('2026-01-27T00:00:00Z'),
    });
  });

  it('uses IANA offsets per boundary instead of assuming a 24-hour day', () => {
    const instrument = new Instrument({ ...cash(), timezone: 'America/New_York', calendar: { sessions: ['0000-0000'] } });
    const spring = instrument.sessionAt(time('2026-03-08T12:00:00Z'))!;
    const fall = instrument.sessionAt(time('2026-11-01T12:00:00Z'))!;
    expect(spring.close - spring.open).toBe(23 * 3600);
    expect(fall.close - fall.open).toBe(25 * 3600);
  });

  it('keeps a session active when the autumn clock repeats an earlier wall time', () => {
    const instrument = new Instrument({ ...cash(), timezone: 'America/New_York', calendar: { sessions: ['0150-0400'] } });
    expect(instrument.sessionAt(time('2026-11-01T06:15:00Z'))).toEqual({
      date: '2026-11-01', open: time('2026-11-01T05:50:00Z'), close: time('2026-11-01T09:00:00Z'),
    });
  });

  it('rejects nonexistent session boundaries and overlapping active sessions', () => {
    const skipped = new Instrument({ ...cash(), timezone: 'America/New_York', calendar: { sessions: ['0230-0400'] } });
    expect(() => skipped.sessionAt(time('2026-03-08T07:45:00Z'))).toThrow(/boundary/i);
    expect(skipped.sessionAt(time('2026-03-09T07:00:00Z'))?.date).toBe('2026-03-09');
    const overlap = new Instrument({ ...cash(), timezone: 'UTC', calendar: { sessions: ['0900-1200', '1100-1400'] } });
    expect(() => overlap.sessionAt(time('2026-01-28T11:30:00Z'))).toThrow(/overlap/i);
    expect(() => overlap.sessionAt(NaN)).toThrow();
  });

  it('feeds a real candle builder with the resolved session open', () => {
    const instrument = new Instrument(cash()), tickTime = time('2026-01-28T04:50:00Z');
    const session = instrument.sessionAt(tickTime)!;
    const builder = new CandleBuilder({ intervalSec: 3600, sessionAnchorSec: session.open });
    const update = builder.onTick({ time: tickTime, price: 100, ltq: 5, oi: 70 });
    expect(update?.bar.time).toBe(time('2026-01-28T04:45:00Z'));
    expect(update?.bar.oi).toBe(70);
  });
});

describe('the next session', () => {
  it('answers the active window, else the next opening, across breaks, weekends and closed dates', () => {
    const instrument = new Instrument(cash());
    // Inside Wednesday's session: that session.
    expect(instrument.sessionFrom(time('2026-01-28T05:00:00Z'))).toEqual({
      date: '2026-01-28', open: time('2026-01-28T03:45:00Z'), close: time('2026-01-28T10:00:00Z'),
    });
    // At the exclusive close: Thursday's.
    expect(instrument.sessionFrom(time('2026-01-28T10:00:00Z'))?.date).toBe('2026-01-29');
    // Friday evening: Monday, skipping the weekend.
    expect(instrument.sessionFrom(time('2026-01-30T12:00:00Z'))?.date).toBe('2026-02-02');
    // Saturday 24th: Monday 26th is closed and Tuesday 27th is shortened.
    expect(instrument.sessionFrom(time('2026-01-24T06:00:00Z'))).toEqual({
      date: '2026-01-27', open: time('2026-01-27T04:30:00Z'), close: time('2026-01-27T07:30:00Z'),
    });
    const split = new Instrument({ ...cash(), timezone: 'UTC', calendar: { sessions: ['0900-1200:23456', '1300-1600:23456'] } });
    expect(split.sessionFrom(time('2026-01-28T12:30:00Z'))?.open).toBe(time('2026-01-28T13:00:00Z'));
  });

  it('keeps an overnight window on its opening date and returns null when nothing opens', () => {
    const overnight = new Instrument({ ...cash(), timezone: 'UTC', calendar: { sessions: ['2200-0200:23456'] } });
    expect(overnight.sessionFrom(time('2026-01-27T01:00:00Z'))?.date).toBe('2026-01-26');
    expect(overnight.sessionFrom(time('2026-01-27T03:00:00Z'))?.open).toBe(time('2026-01-27T22:00:00Z'));
    const never = new Instrument({ ...cash(), calendar: { sessions: [] } });
    expect(never.sessionFrom(time('2026-01-27T03:00:00Z'))).toBeNull();
    expect(() => never.sessionFrom(NaN)).toThrow(/Invalid instrument/);
  });
});

describe('a session calendar without instrument rules', () => {
  it('validates, detaches and reads like the instrument it could belong to', () => {
    const source = { timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'], exceptions: { '2026-01-26': [] as string[] } };
    const calendar = new SessionCalendar(source);
    source.sessions[0] = '0000-0000';
    expect(calendar.timezone).toBe('Asia/Kolkata');
    expect(calendar.calendar.sessions).toEqual(['0915-1530:23456']);
    expect(Object.isFrozen(calendar.calendar)).toBe(true);
    const instrument = new Instrument(cash());
    for (const at of ['2026-01-24T06:00:00Z', '2026-01-28T05:00:00Z', '2026-01-28T10:00:00Z']) {
      expect(calendar.sessionAt(time(at))).toEqual(new Instrument({ ...cash(), calendar: { sessions: ['0915-1530:23456'], exceptions: { '2026-01-26': [] } } }).sessionAt(time(at)));
    }
    expect(calendar.sessionFrom(time('2026-01-24T06:00:00Z'))?.date).toBe('2026-01-27');
    expect(instrument.sessionFrom(time('2026-01-24T06:00:00Z'))?.date).toBe('2026-01-27');
  });

  it.each([
    [{ timezone: 'Mars/City', sessions: [] }, /Invalid session calendar: unknown timezone/],
    [{ timezone: 'UTC', sessions: ['9999-9999'] }, /Invalid session calendar: invalid session/],
    [{ timezone: 'UTC', sessions: [], exceptions: { '2026-02-30': [] } }, /Invalid session calendar: invalid exception date/],
    [{ sessions: [] }, /Invalid session calendar: timezone/],
    [null, /Invalid session calendar/],
  ])('refuses %j', (input, message) => {
    expect(() => new SessionCalendar(input)).toThrow(message);
  });

  it('reports its own name for a boundary a daylight-saving gap removes', () => {
    const skipped = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0230-0400'] });
    expect(() => skipped.sessionAt(time('2026-03-08T07:45:00Z'))).toThrow(/Invalid session calendar: session boundary/);
    expect(skipped.sessionAt(time('2026-03-09T07:00:00Z'))?.date).toBe('2026-03-09');
  });
});

describe('market phases', () => {
  // NSE-style hours in IST: a 15-minute pre-open and a 30-minute closing session.
  const nse = (): Instrument => new Instrument({ ...cash(), calendar: { ...cash().calendar, preMarketMinutes: 15, postMarketMinutes: 30 } });
  const ist = (local: string): number => time(`${local}+05:30`);
  const span = (phase: string, start: number, end: number) => ({ phase, start, end });
  // US-style hours: pre-open from 04:00 and post-close to 20:00 around 09:30 to
  // 16:00, with Thanksgiving closed and the day after it ending at 13:00.
  const us = (extra: Record<string, unknown> = {}): SessionCalendar => new SessionCalendar({
    timezone: 'America/New_York', sessions: ['0930-1600:23456'], preMarketMinutes: 330, postMarketMinutes: 240,
    exceptions: { '2026-11-26': [], '2026-11-27': ['0930-1300'] }, ...extra,
  });

  it('walks a regular IST day through pre-open, the session, post-close and closed', () => {
    const instrument = nse();
    expect(instrument.phaseSpans(ist('2026-01-28T00:00:00'), ist('2026-01-29T00:00:00'))).toEqual([
      span('closed', ist('2026-01-28T00:00:00'), ist('2026-01-28T09:00:00')),
      span('pre', ist('2026-01-28T09:00:00'), ist('2026-01-28T09:15:00')),
      span('regular', ist('2026-01-28T09:15:00'), ist('2026-01-28T15:30:00')),
      span('post', ist('2026-01-28T15:30:00'), ist('2026-01-28T16:00:00')),
      span('closed', ist('2026-01-28T16:00:00'), ist('2026-01-29T00:00:00')),
    ]);
    const at = (local: string) => instrument.phaseAt(ist(local));
    expect(at('2026-01-28T08:59:59')).toBe('closed');
    expect(at('2026-01-28T09:00:00')).toBe('pre');
    expect(at('2026-01-28T09:14:59')).toBe('pre');
    expect(at('2026-01-28T09:15:00')).toBe('regular');
    expect(at('2026-01-28T15:29:59')).toBe('regular');
    expect(at('2026-01-28T15:30:00')).toBe('post');
    expect(at('2026-01-28T16:00:00')).toBe('closed');
    // IST keeps no daylight saving: the pre-open opens at 03:30 UTC in June too.
    expect(instrument.phaseAt(time('2026-06-17T03:29:59Z'))).toBe('closed');
    expect(instrument.phaseAt(time('2026-06-17T03:30:00Z'))).toBe('pre');
  });

  it('moves the pre-open and post-close with a shortened day and drops them on a holiday', () => {
    const instrument = nse();
    expect(instrument.phaseSpans(ist('2026-01-27T09:30:00'), ist('2026-01-27T14:00:00'))).toEqual([
      span('closed', ist('2026-01-27T09:30:00'), ist('2026-01-27T09:45:00')),
      span('pre', ist('2026-01-27T09:45:00'), ist('2026-01-27T10:00:00')),
      span('regular', ist('2026-01-27T10:00:00'), ist('2026-01-27T13:00:00')),
      span('post', ist('2026-01-27T13:00:00'), ist('2026-01-27T13:30:00')),
      span('closed', ist('2026-01-27T13:30:00'), ist('2026-01-27T14:00:00')),
    ]);
    // Monday the 26th is closed by an exception although Mondays open: the
    // whole local date, midnight to midnight, is a holiday, with no pre-open.
    expect(instrument.phaseSpans(ist('2026-01-25T12:00:00'), ist('2026-01-27T09:00:00'))).toEqual([
      span('closed', ist('2026-01-25T12:00:00'), ist('2026-01-26T00:00:00')),
      span('holiday', ist('2026-01-26T00:00:00'), ist('2026-01-27T00:00:00')),
      span('closed', ist('2026-01-27T00:00:00'), ist('2026-01-27T09:00:00')),
    ]);
    expect(instrument.phaseAt(ist('2026-01-26T09:05:00'))).toBe('holiday');
    expect(instrument.phaseAt(ist('2026-01-26T23:59:59'))).toBe('holiday');
  });

  it('reads a weekend as closed, and an exception closing a weekend date is no holiday', () => {
    expect(nse().phaseAt(ist('2026-01-24T12:00:00'))).toBe('closed');
    const saturday = new Instrument({ ...cash(), calendar: { sessions: ['0915-1530:23456'], exceptions: { '2026-01-31': [] } } });
    expect(saturday.phaseAt(ist('2026-01-31T12:00:00'))).toBe('closed');
  });

  it('follows daylight saving in the calendar zone, per boundary', () => {
    const calendar = us();
    // Friday 6 March 2026, on EST (UTC-5): pre-open 09:00Z, open 14:30Z, close 21:00Z, post to 01:00Z.
    expect(calendar.phaseSpans(time('2026-03-06T08:00:00Z'), time('2026-03-07T02:00:00Z'))).toEqual([
      span('closed', time('2026-03-06T08:00:00Z'), time('2026-03-06T09:00:00Z')),
      span('pre', time('2026-03-06T09:00:00Z'), time('2026-03-06T14:30:00Z')),
      span('regular', time('2026-03-06T14:30:00Z'), time('2026-03-06T21:00:00Z')),
      span('post', time('2026-03-06T21:00:00Z'), time('2026-03-07T01:00:00Z')),
      span('closed', time('2026-03-07T01:00:00Z'), time('2026-03-07T02:00:00Z')),
    ]);
    // Monday 9 March, the day after the clocks went forward, on EDT (UTC-4):
    // every boundary is an hour earlier in UTC and at the same wall time.
    expect(calendar.phaseSpans(time('2026-03-09T07:00:00Z'), time('2026-03-10T01:00:00Z'))).toEqual([
      span('closed', time('2026-03-09T07:00:00Z'), time('2026-03-09T08:00:00Z')),
      span('pre', time('2026-03-09T08:00:00Z'), time('2026-03-09T13:30:00Z')),
      span('regular', time('2026-03-09T13:30:00Z'), time('2026-03-09T20:00:00Z')),
      span('post', time('2026-03-09T20:00:00Z'), time('2026-03-10T00:00:00Z')),
      span('closed', time('2026-03-10T00:00:00Z'), time('2026-03-10T01:00:00Z')),
    ]);
    // And back in November: Friday on EDT, Monday on EST.
    expect(calendar.phaseAt(time('2026-10-30T08:00:00Z'))).toBe('pre');
    expect(calendar.phaseAt(time('2026-11-02T08:00:00Z'))).toBe('closed');
    expect(calendar.phaseAt(time('2026-11-02T09:00:00Z'))).toBe('pre');
    // Thanksgiving is a holiday in New York's own date, and the next day's
    // shortened session carries its post-close from 13:00 to 17:00.
    expect(calendar.phaseAt(time('2026-11-26T15:00:00Z'))).toBe('holiday');
    expect(calendar.phaseAt(time('2026-11-27T18:30:00Z'))).toBe('post');
    expect(calendar.phaseAt(time('2026-11-27T22:00:00Z'))).toBe('closed');
    // Extended hours that run through the spring-forward night last seven
    // hours, from 20:00 EST to 04:00 EDT, not eight.
    const overnight = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'], extendedHours: ['2000-0400'] });
    expect(overnight.phaseSpans(time('2026-03-08T00:00:00Z'), time('2026-03-08T12:00:00Z'))).toEqual([
      span('closed', time('2026-03-08T00:00:00Z'), time('2026-03-08T01:00:00Z')),
      span('extended', time('2026-03-08T01:00:00Z'), time('2026-03-08T08:00:00Z')),
      span('closed', time('2026-03-08T08:00:00Z'), time('2026-03-08T12:00:00Z')),
    ]);
  });

  it('gives the session precedence, then pre-open, post-close and extended hours', () => {
    const calendar = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1700:23456'], preMarketMinutes: 120,
      postMarketMinutes: 120, extendedHours: ['0600-2000:23456'] });
    expect(calendar.phaseSpans(time('2026-01-28T00:00:00Z'), time('2026-01-29T00:00:00Z')).map(s => [s.phase, s.start, s.end])).toEqual([
      ['closed', time('2026-01-28T00:00:00Z'), time('2026-01-28T06:00:00Z')],
      ['extended', time('2026-01-28T06:00:00Z'), time('2026-01-28T07:00:00Z')],
      ['pre', time('2026-01-28T07:00:00Z'), time('2026-01-28T09:00:00Z')],
      ['regular', time('2026-01-28T09:00:00Z'), time('2026-01-28T17:00:00Z')],
      ['post', time('2026-01-28T17:00:00Z'), time('2026-01-28T19:00:00Z')],
      ['extended', time('2026-01-28T19:00:00Z'), time('2026-01-28T20:00:00Z')],
      ['closed', time('2026-01-28T20:00:00Z'), time('2026-01-29T00:00:00Z')],
    ]);
    // An exception closing a date closes its extended hours with it.
    const closed = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1700:23456'], extendedHours: ['0600-2000:23456'], exceptions: { '2026-01-28': [] } });
    expect(closed.phaseAt(time('2026-01-28T06:30:00Z'))).toBe('holiday');
  });

  it('keeps a lunch break closed, with the extended hours around the whole day', () => {
    const split = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1130:23456', '1230-1500:23456'], preMarketMinutes: 30, postMarketMinutes: 30 });
    expect(split.phaseSpans(time('2026-01-28T08:00:00Z'), time('2026-01-28T16:00:00Z')).map(s => s.phase))
      .toEqual(['closed', 'pre', 'regular', 'closed', 'regular', 'post', 'closed']);
    expect(split.phaseAt(time('2026-01-28T12:00:00Z'))).toBe('closed');
    expect(split.phaseAt(time('2026-01-28T15:15:00Z'))).toBe('post');
  });

  it('puts the post-close of an overnight session after its close, on the next date', () => {
    const overnight = new SessionCalendar({ timezone: 'UTC', sessions: ['2200-0200:23456'], postMarketMinutes: 60 });
    // Friday's session opens at 22:00 and closes at 02:00 on Saturday.
    expect(overnight.phaseAt(time('2026-01-31T01:30:00Z'))).toBe('regular');
    expect(overnight.phaseAt(time('2026-01-31T02:30:00Z'))).toBe('post');
    expect(overnight.phaseAt(time('2026-01-31T03:00:00Z'))).toBe('closed');
  });

  it('lays out the dates either side of a range, for hours that spill across midnight into it', () => {
    // A Thursday-night session whose post-close runs through Friday into
    // Saturday: its hours reach two dates past the one it opens on, and are
    // the only hours on either.
    const late = new SessionCalendar({ timezone: 'UTC', sessions: ['2200-0200:5'], postMarketMinutes: 1439 });
    expect(late.phaseAt(time('2026-01-31T01:00:00Z'))).toBe('post');
    expect(late.phaseAt(time('2026-01-31T02:00:00Z'))).toBe('closed');
    // A pre-open that begins the evening before a session opening just after
    // midnight belongs to the next date.
    const early = new SessionCalendar({ timezone: 'UTC', sessions: ['0030-0600:23456'], preMarketMinutes: 60 });
    expect(early.phaseAt(time('2026-02-01T23:45:00Z'))).toBe('pre');
    expect(early.phaseSpans(time('2026-02-01T20:00:00Z'), time('2026-02-01T23:40:00Z'))).toEqual([
      span('closed', time('2026-02-01T20:00:00Z'), time('2026-02-01T23:30:00Z')),
      span('pre', time('2026-02-01T23:30:00Z'), time('2026-02-01T23:40:00Z')),
    ]);
  });

  it('lays out a round-the-clock calendar as one session', () => {
    const crypto = new SessionCalendar({ timezone: 'UTC', sessions: ['0000-0000'] });
    expect(crypto.phaseSpans(time('2026-01-24T05:00:00Z'), time('2026-01-27T05:00:00Z')))
      .toEqual([span('regular', time('2026-01-24T05:00:00Z'), time('2026-01-27T05:00:00Z'))]);
  });

  it('refuses a range it cannot lay out, naming its own kind', () => {
    const instrument = nse(), calendar = us(), t = time('2026-01-28T00:00:00Z');
    expect(() => instrument.phaseSpans(t, t)).toThrow(/Invalid instrument: phase range/);
    expect(() => instrument.phaseSpans(t, t + 401 * 86400)).toThrow(/Invalid instrument: phase range/);
    expect(() => calendar.phaseSpans(t + 60, t)).toThrow(/Invalid session calendar: phase range/);
    expect(() => calendar.phaseSpans(NaN, t)).toThrow(/Invalid session calendar: invalid timestamp/);
    expect(() => calendar.phaseAt(NaN)).toThrow(/Invalid session calendar/);
    expect(instrument.phaseSpans(t, t + 400 * 86400).length).toBeGreaterThan(1000);
  });

  it.each([
    [{ preMarketMinutes: -1 }, 'preMarketMinutes must be whole minutes under a day'],
    [{ preMarketMinutes: 1440 }, 'preMarketMinutes must be whole minutes under a day'],
    [{ postMarketMinutes: 1.5 }, 'postMarketMinutes must be whole minutes under a day'],
    [{ postMarketMinutes: '30' }, 'postMarketMinutes must be whole minutes under a day'],
    [{ extendedHours: ['2500-0100'] }, 'invalid extended hours'],
    [{ extendedHours: '2000-0400' }, 'invalid list'],
  ])('refuses extended hours %j for an instrument and a bare calendar', (patch, message) => {
    expect(() => new Instrument({ ...cash(), calendar: { ...cash().calendar, ...patch } })).toThrow(new Error(`Invalid instrument: ${message}`));
    expect(() => new SessionCalendar({ timezone: 'UTC', sessions: [], ...patch })).toThrow(new Error(`Invalid session calendar: ${message}`));
  });

  it('checks the extended hours after every older field, so an older fault still comes first', () => {
    const bad = { preMarketMinutes: -1, extendedHours: ['bad'] };
    expect(() => new Instrument({ ...cash(), symbol: '', calendar: { sessions: ['bad'], ...bad } })).toThrow(new Error('Invalid instrument: symbol'));
    expect(() => new Instrument({ ...cash(), calendar: { sessions: ['bad'], ...bad } })).toThrow(new Error('Invalid instrument: invalid session'));
    expect(() => new SessionCalendar({ timezone: 'Mars/City', sessions: [], ...bad })).toThrow(/unknown timezone/);
    expect(() => new SessionCalendar({ timezone: 'UTC', sessions: ['bad'], ...bad })).toThrow(/invalid session$/);
  });

  it('keeps a calendar without extended hours in its old shape, and detaches and freezes the new fields', () => {
    expect(Object.keys(new Instrument(cash()).metadata.calendar)).toEqual(['sessions', 'exceptions']);
    expect(Object.keys(new SessionCalendar({ timezone: 'UTC', sessions: [] }).calendar)).toEqual(['sessions', 'exceptions']);
    const source = { timezone: 'UTC', sessions: ['0900-1700:23456'], extendedHours: ['1800-2200:23456'], preMarketMinutes: 0, postMarketMinutes: 45 };
    const calendar = new SessionCalendar(source);
    source.extendedHours[0] = '0000-0000';
    expect(calendar.calendar).toMatchObject({ extendedHours: ['1800-2200:23456'], preMarketMinutes: 0, postMarketMinutes: 45 });
    expect(Object.isFrozen(calendar.calendar.extendedHours)).toBe(true);
    // Zero minutes is no pre-open at all.
    expect(calendar.phaseAt(time('2026-01-28T08:59:00Z'))).toBe('closed');
    expect(calendar.phaseAt(time('2026-01-28T17:30:00Z'))).toBe('post');
    expect(calendar.phaseAt(time('2026-01-28T19:00:00Z'))).toBe('extended');
  });
});

describe('instrument chart and quantity integration', () => {
  it.each(['left', ''] as const)('applies the tick to the actual primary scale %j', priceScaleId => {
    const c = chart(priceScaleId); c.addIndicator('rsi');
    const oscillator = c.panes()[1].priceScale;
    const before = { ...oscillator.options };
    new Instrument(cash()).applyTo(c, '1m');
    expect(c.primarySeries()!.priceScale().options.minMove).toBe(0.05);
    expect(c.primarySeries()!.priceScale().format(100.1)).toBe('100.10');
    expect(oscillator.options).toEqual(before);
  });

  it('sets only the instrument price formatting and keeps oscillator units', () => {
    const c = chart(); c.addIndicator('rsi');
    const before = c.panes()[1].priceScale.format(62.24);
    const instrument = new Instrument({ ...cash(), pricePrecision: 4, hasOpenInterest: true });
    instrument.applyTo(c, '1h');
    expect(c.timezone()).toBe('Asia/Kolkata');
    expect(c.getDataContext()).toMatchObject({ symbol: 'CASH', exchange: 'NSE', interval: '1h', hasOpenInterest: true });
    expect(c.primarySeries()!.priceScale().format(100.1)).toBe('100.1000');
    expect(c.primarySeries()!.priceScale().options.minMove).toBe(0.05);
    expect(c.panes()[1].priceScale.format(62.24)).toBe(before);
  });

  it('rejects stale source application and unsupported intervals before any chart mutation', () => {
    const c = chart(), instrument = new Instrument(cash());
    const before = c.getState();
    expect(() => instrument.applyTo(c, '5m')).toThrow(/interval/i);
    expect(c.getState()).toEqual(before); expect(c.getDataContext()).toBeUndefined();
    c.setDataContext({ symbol: 'OTHER', exchange: 'NSE', interval: '1m' });
    c.primarySeries()!.setData([{ time: 60, open: 1, high: 2, low: 1, close: 2 }]);
    expect(() => instrument.applyTo(c, '1m')).toThrow(/clear/i);
    expect(c.getDataContext()?.symbol).toBe('OTHER');
    c.primarySeries()!.setData([]); instrument.applyTo(c, '1m');
    expect(c.getDataContext()?.symbol).toBe('CASH');
  });

  it('formats tiny crypto prices without changing stored values or quantity units', () => {
    const instrument = new Instrument({ ...cash(), symbol: 'COIN', exchange: 'CRYPTO', priceTick: 0.00000001,
      pricePrecision: 8, quantityStep: 0.001, timezone: 'UTC', calendar: { sessions: ['0000-0000'] } });
    const c = chart(); instrument.applyTo(c, '1m');
    const price = 0.123456789;
    c.primarySeries()!.setData([{ time: 60, open: price, high: price, low: price, close: price }]);
    expect(c.primaryBars()[0].close).toBe(price);
    expect(instrument.formatPrice(price)).toBe('0.12345679');
    expect(instrument.formatPrice(NaN)).toBe('');
    const constraints = orderConstraintsForInstrument(instrument);
    expect(validateQuantity(0.003, constraints).ok).toBe(true);
    expect(validateQuantity(0.0035, constraints).code).toBe('QTY_STEP');
    expect(validatePrice(0.123456789, constraints).price).toBeCloseTo(0.12345679, 10);
    expect(orderConstraintsForInstrument(new Instrument({ ...cash(), quantityStep: 75 })).lotSize).toBe(75);
  });
});

describe('instrument tick schedules', () => {
  // Synthetic rules: 0.02 below 20 and 0.05 from 20. Neither tick divides the
  // other, so the common grid (0.01) is the only honest minimum move.
  const banded = (): InstrumentMetadata => ({
    ...cash(), symbol: 'BANDED', priceTick: 0.01, tickBands: [{ tick: 0.02 }, { from: 20, tick: 0.05 }],
  });

  it('keeps a constant-tick profile byte-identical, with one snapping rule and no schedule', () => {
    const instrument = new Instrument(cash());
    expect(instrument.metadata).not.toHaveProperty('tickBands');
    expect(Object.keys(orderConstraintsForInstrument(instrument))).toEqual(['tickSize', 'lotSize', 'allowFractionalQty']);
    expect(orderConstraintsForInstrument(instrument)).toEqual({ tickSize: 0.05, lotSize: 1, allowFractionalQty: false });
    // A one-band schedule here would be a second rule: its 100.05 against the
    // 100.05000000000001 the order engine's constant tick sends, so a preview
    // made with it would never equal the amended price.
    expect(instrument.tickSchedule).toBeNull();
    expect(validatePrice(100.07, orderConstraintsForInstrument(instrument)).price).toBe(100.05000000000001);
  });

  it('accepts any constant tick the metadata accepts, as it did before schedules', () => {
    // Base metadata takes a tick this large at precision 0; building a schedule
    // for it would throw, although the caller configured nothing new.
    const coarse = new Instrument({ ...cash(), priceTick: 1e16, pricePrecision: 0 });
    expect(coarse.metadata.priceTick).toBe(1e16);
    expect(coarse.tickSchedule).toBeNull();
  });

  it('detaches, freezes and applies a banded schedule to validation', () => {
    const source = banded();
    const bands = source.tickBands as { from?: number; tick: number }[];
    const instrument = new Instrument(source);
    bands[1].tick = 1;
    expect(instrument.metadata.tickBands).toEqual([{ tick: 0.02 }, { from: 20, tick: 0.05 }]);
    expect(Object.isFrozen(instrument.metadata.tickBands)).toBe(true);
    expect(instrument.tickSchedule!.bands).toEqual(instrument.metadata.tickBands);
    const constraints = orderConstraintsForInstrument(instrument);
    expect(constraints.tickSchedule).toBe(instrument.tickSchedule);
    expect(constraints.tickSize).toBe(0.01);
    expect(validatePrice(19.97, constraints).price).toBe(19.98);
    expect(validatePrice(20.03, constraints).price).toBe(20.05);
    // One rule: the schedule the constraints validate with is the instrument's.
    for (const price of [19.97, 19.99, 20, 20.025, 20.03, 20.07]) {
      expect(validatePrice(price, constraints).price).toBe(instrument.tickSchedule!.round(price));
    }
  });

  it('sets the price scale minimum move to the common grid of the schedule and formats every band', () => {
    const c = chart(); c.addIndicator('rsi');
    const oscillator = { ...c.panes()[1].priceScale.options };
    const instrument = new Instrument(banded());
    instrument.applyTo(c, '1m');
    const scale = c.primarySeries()!.priceScale();
    // 0.01, finer than either band's tick: 20.05 is no multiple of 0.02.
    expect(scale.options.minMove).toBe(instrument.tickSchedule!.minMove);
    expect(scale.options.minMove).toBe(0.01);
    // A valid price in the coarse band survives the scale's own snap.
    expect(scale.snapToTick(20.05)).toBeCloseTo(20.05, 10);
    expect(scale.format(20.05)).toBe('20.05');
    expect(c.panes()[1].priceScale.options).toEqual(oscillator);
  });

  it.each<[string, Record<string, unknown>, RegExp]>([
    ['a price tick that is not the common grid', { priceTick: 0.02 }, /price tick 0\.02 must equal the schedule's minimum move 0\.01/],
    ['a price tick finer than the common grid', { priceTick: 0.005, pricePrecision: 3 }, /price tick 0\.005 must equal the schedule's minimum move 0\.01/],
    ['unordered bands', { tickBands: [{ tick: 0.02 }, { from: 40, tick: 0.05 }, { from: 20, tick: 0.1 }] }, /ascending/],
    ['a lower bound on the first band', { tickBands: [{ from: 0, tick: 0.01 }] }, /bands\[0\] covers every lower price/],
    ['bands that are not a list', { tickBands: { tick: 0.01 } }, /1 to 64 bands/],
  ])('rejects %s before use', (_label, patch, message) => {
    expect(() => new Instrument({ ...banded(), ...patch })).toThrow(message);
  });
});

describe('instrument ticks on chart drags', () => {
  const banded = (): InstrumentMetadata => ({
    ...cash(), symbol: 'BANDED', priceTick: 0.01, tickBands: [{ tick: 0.02 }, { from: 20, tick: 0.05 }],
  });
  /** The chart's drag release, as the trading layer subscribed to it. */
  function release(spy: { mock: { calls: unknown[][] } }): (id: string, price: number) => void {
    const calls = spy.mock.calls;
    const end = calls[calls.length - 1][1] as (id: string, price: number, time: number) => void;
    return (id, price) => end(id, price, 0);
  }

  it('hands the schedule to a trading layer built after the instrument was applied', () => {
    const c = chart();
    const drags = vi.spyOn(c, 'subscribeDrag');
    new Instrument(banded()).applyTo(c, '1m');
    // Applying an instrument must not build the layer: it would make every ns-resize line draggable.
    expect(c.hasTrading()).toBe(false);
    const modify = vi.fn();
    c.trading.on('trading:order_modify', modify);
    c.trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 19.98, size: 1 }]);
    release(drags)('ord:o1', 20.031);
    expect(modify).toHaveBeenLastCalledWith({ orderId: 'o1', newPrice: 20.05, previousPrice: 19.98 });
  });

  it('replaces the schedule on a symbol switch and clears it for a constant tick', () => {
    const c = chart();
    const drags = vi.spyOn(c, 'subscribeDrag');
    const modify = vi.fn();
    c.trading.on('trading:order_modify', modify);
    c.trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 19.98, size: 1 }]);
    const end = release(drags);
    new Instrument(banded()).applyTo(c, '1m');
    end('ord:o1', 20.031);
    // The next symbol trades on a constant tick: its drags report the pointer's
    // price, as they always have, not the previous instrument's bands.
    new Instrument(cash()).applyTo(c, '1m');
    end('ord:o1', 20.031);
    new Instrument(banded()).applyTo(c, '1m');
    end('ord:o1', 19.971);
    expect(modify.mock.calls.map(([event]) => event.newPrice)).toEqual([20.05, 20.031, 19.98]);
  });

  it('gives the chart the schedule its alert drags round with, and clears it for a constant tick', () => {
    const c = chart();
    new Instrument(banded()).applyTo(c, '1m');
    expect(c.tickSchedule()?.tickAt(20.03)).toBe(0.05);
    expect(c.snapPrice(0, 20.031)).toBe(20.05);
    new Instrument(cash()).applyTo(c, '1m');
    expect(c.tickSchedule()).toBeNull();
    expect(c.snapPrice(0, 20.031)).toBe(roundToTick(20.031, cash().priceTick));
  });

  it('lets the host override the instrument after applying it', () => {
    const c = chart();
    const drags = vi.spyOn(c, 'subscribeDrag');
    const modify = vi.fn();
    c.trading.on('trading:order_modify', modify);
    c.trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 19.98, size: 1 }]);
    new Instrument(banded()).applyTo(c, '1m');
    c.trading.setTickSchedule(null);
    release(drags)('ord:o1', 20.031);
    expect(modify).toHaveBeenLastCalledWith(expect.objectContaining({ newPrice: 20.031 }));
  });
});
