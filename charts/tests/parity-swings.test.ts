/**
 * Parity for the swing studies: the percent-reversal ZigZag and the 52 week
 * high and low, against their published definitions.
 *
 * Expectations are worked out by hand on fixtures small enough to follow, with
 * the arithmetic beside them. The ZigZag's last leg repaints by nature, so what
 * a live tick does to it is pinned tick by tick, and its `calcTail` is held to
 * the full `calc` of the same bars. The 52 week window is a calendar window,
 * so it is pinned across a weekend and in a zone other than the default.
 */
import { describe, it, expect } from 'vitest';
import { ZIGZAG, HIGH_LOW_52_WEEK, SWING_INDICATORS } from '../src/indicators/swings';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorDrawing, IndicatorValues } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const DAY = 86400;
const at = (i: number): number => 1735689600 + i * 900;

/** Bars from explicit highs and lows, with open and close at the midpoint. */
const hlBars = (rows: readonly (readonly [number, number])[]): Bar[] =>
  rows.map(([high, low], i) => ({ time: at(i), open: (high + low) / 2, high, low, close: (high + low) / 2, volume: 1000 }));

const settingsOf = (d: IndicatorDescriptor, over: Record<string, unknown> = {}) => ({ ...indicatorDefaults(d), ...over });
const run = (d: IndicatorDescriptor, bars: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(bars, settingsOf(d, over), {});

/** The runtime's splice of a tail onto the held result. */
function splice(held: IndicatorValues, tail: IndicatorValues, from: number, n: number): IndicatorValues {
  const out: Record<string, (number | null)[]> = {};
  for (const key of Object.keys(tail)) out[key] = [...held[key].slice(0, from), ...tail[key]].slice(0, n);
  return out;
}

describe('the swing family', () => {
  it('ships two descriptors', () => {
    expect(SWING_INDICATORS.map((d) => d.id)).toEqual(['zigzag', 'high-low-52-week']);
  });
});

describe('ZigZag', () => {
  // deviation 10 percent.
  //   bar  high  low
  //    0   100   95   both extremes on one bar: no order between them yet
  //    1   104   99   high 104; rise from the low 95 is 9, short of 9.5
  //    2   110  105   high 110; rise 15 >= 9.5: low 95 at bar 0 is the first
  //                   swing point, and the rising leg's end is 110 at bar 2
  //    3   106   98   110 - 98 = 12 >= 11: 110 confirmed, falling leg ends at 98
  //    4    97   90   new low 90: the leg's end moves from bar 3 to bar 4
  //    5    99   92   99 - 90 = 9, exactly 10 percent of 90: 90 confirmed,
  //                   rising leg ends at 99 (at least the deviation reverses)
  //    6   103   98   new high 103: the end moves from bar 5 to bar 6
  //    7   101   94   103 - 94 = 9, short of 10.3: nothing
  const rows: [number, number][] = [[100, 95], [104, 99], [110, 105], [106, 98], [97, 90], [99, 92], [103, 98], [101, 94]];
  const bars = hlBars(rows);
  const s = { deviation: 10 };

  it('marks each swing point at its own bar and the running end of the last leg', () => {
    expect(run(ZIGZAG, bars, s).zigzag).toEqual([95, null, 110, null, 90, null, 103, null]);
  });

  it('draws the confirmed legs in the line style and the last leg dashed', () => {
    const values = run(ZIGZAG, bars, s);
    const legs = ZIGZAG.draws!({ bars, values, settings: settingsOf(ZIGZAG, s) }) as Extract<IndicatorDrawing, { kind: 'line' }>[];
    expect(legs.map((l) => [l.from.price, l.to.price, l.lineStyle])).toEqual([
      [95, 110, 'solid'], [110, 90, 'solid'], [90, 103, 'dashed'],
    ]);
    expect(legs[0].from.time).toBe(bars[0].time);
    expect(legs[2].to.time).toBe(bars[6].time);
    expect(legs.every((l) => l.color === '#2962ff' && l.lineWidth === 2)).toBe(true);
  });

  it('draws the legs in the plot colour, opacity, thickness and line style the Style tab sets', () => {
    const values = run(ZIGZAG, bars, s);
    const settings = settingsOf(ZIGZAG, { ...s, color: '#ff0000', 'zigzag:opacity': 50, 'zigzag:width': 3, 'zigzag:lineStyle': 'dashed' });
    const legs = ZIGZAG.draws!({ bars, values, settings }) as Extract<IndicatorDrawing, { kind: 'line' }>[];
    expect(legs.map((l) => l.lineStyle)).toEqual(['dashed', 'dashed', 'dotted']);
    expect(legs.every((l) => l.color === 'rgba(255,0,0,0.5)' && l.lineWidth === 3)).toBe(true);
  });

  it('lets a bar that makes a new extreme extend the leg even when its other end would reverse it', () => {
    // After bar 2 the rising leg ends at 110. Bar 3 reaches 112 and falls to
    // 95, 17 below: the new high wins, and the leg is not reversed on it.
    const out = run(ZIGZAG, hlBars([[100, 95], [104, 99], [110, 105], [112, 95]]), s).zigzag;
    expect(out).toEqual([95, null, null, 112]);
  });

  it('draws nothing until price has moved the deviation from its first extreme', () => {
    const quiet = hlBars([[100, 95], [101, 96], [102, 97], [103, 98]]);
    expect(run(ZIGZAG, quiet, s).zigzag.every((v) => v === null)).toBe(true);
    expect(ZIGZAG.draws!({ bars: quiet, values: run(ZIGZAG, quiet, s), settings: settingsOf(ZIGZAG, s) })).toEqual([]);
  });

  it('steps over a bar with no high or low, which neither extends nor reverses a leg', () => {
    const holed = hlBars(rows);
    holed[4] = { ...holed[4], high: NaN, low: NaN };
    // Without bar 4 the falling leg runs on from 98 at bar 3 to bar 5's low of
    // 92, and bar 6's high of 103 is 11 above that, over 9.2, so it reverses.
    expect(run(ZIGZAG, holed, s).zigzag).toEqual([95, null, 110, null, null, 92, 103, null]);
  });

  describe('a live tick moves only the last leg, and the tail agrees with a full calc', () => {
    // The held result after the eight bars above, then ticks on bar 7 and one
    // appended bar. After each, the tail spliced onto the held result must be
    // the full calc of the same bars, or the tail must decline.
    const settings = settingsOf(ZIGZAG, s);
    const tick = (list: Bar[], i: number, high: number, low: number): Bar[] => {
      const next = list.slice();
      next[i] = { ...list[i], high, low, open: (high + low) / 2, close: (high + low) / 2 };
      return next;
    };

    it('follows the forming bar and falls back to a full calc exactly when an earlier bar changes', () => {
      const store = {};
      let live = bars.slice();
      let held = ZIGZAG.calc(live, settings, store);
      const step = (next: Bar[], from: number): IndicatorValues | null => {
        const tail = ZIGZAG.calcTail!(next, settings, from, held, store);
        const full = ZIGZAG.calc(next, settings, {});
        if (tail !== null) expect(splice(held, tail, from, next.length)).toEqual(full);
        live = next;
        held = tail === null ? ZIGZAG.calc(next, settings, store) : splice(held, tail, from, next.length);
        expect(held).toEqual(full);
        return tail;
      };

      // Bar 7 ticks to 108: a new high, so the leg's end leaves bar 6 for bar 7.
      // Bar 6 is before the tail and the held result still shows 103 there, so
      // the tail declines and the full calc clears it.
      expect(step(tick(live, 7, 108, 94), 7)).toBeNull();
      expect(held.zigzag).toEqual([95, null, 110, null, 90, null, null, 108]);

      // Bar 7 ticks to 109: the end stays on the forming bar, and the only
      // bar before the tail it touches (6) already reads empty. The tail takes it.
      expect(step(tick(live, 7, 109, 94), 7)).toEqual({ zigzag: [109] });

      // A correction replaces bar 7 with 104 and 95: still above 103, so the
      // end stays on the forming bar, at 104. Still only the forming bar moves.
      expect(step(tick(live, 7, 104, 95), 7)).toEqual({ zigzag: [104] });

      // Another correction: 102 and 92. No new high over 103 now, so bar 6 is the
      // leg's end again, and 103 - 92 = 11 >= 10.3 confirms it and starts a
      // falling leg on bar 7. Bar 6 changes from empty to 103: the tail declines.
      expect(step(tick(live, 7, 102, 92), 7)).toBeNull();
      expect(held.zigzag).toEqual([95, null, 110, null, 90, null, 103, 92]);

      // A new bar with a lower low moves the falling leg's end from bar 7 to 8.
      // Both are in the tail (from 7), so it splices.
      const appended = [...live, { time: at(8), open: 92, high: 93, low: 91, close: 92, volume: 1000 }];
      expect(step(appended, 7)).toEqual({ zigzag: [null, 91] });
      expect(held.zigzag).toEqual([95, null, 110, null, 90, null, 103, null, 91]);
    });
  });
});

describe('52 Week High/Low', () => {
  // Weekly bars on Mondays. The window is the 364 days ending on the bar's day,
  // so on weekly bars it is the bar and the 51 before it, and it covers once
  // the history begins before its first day: bar 52, whose window starts the
  // day after bar 0.
  //   high = 200 - |i - 20|, low = high - 10
  //   bar 52  window 1..52   high peak at bar 20 = 200, low at bar 52 = 158
  //   bar 72  window 21..72  high at bar 21 = 199, low at bar 72 = 138
  const monday = Date.UTC(2024, 0, 1, 3, 45) / 1000;
  const weekly: Bar[] = Array.from({ length: 80 }, (_, i) => {
    const high = 200 - Math.abs(i - 20);
    return { time: monday + i * 7 * DAY, open: high - 5, high, low: high - 10, close: high - 5, volume: 1000 };
  });

  it('is the highest high and lowest low of the 52 weeks ending with the bar', () => {
    const out = run(HIGH_LOW_52_WEEK, weekly);
    expect(out.high[52]).toBe(200);
    expect(out.low[52]).toBe(158);
    expect(out.high[72]).toBe(199);
    expect(out.low[72]).toBe(138);
  });

  it('prints nothing until the loaded history reaches back before the window', () => {
    const out = run(HIGH_LOW_52_WEEK, weekly);
    expect(out.high.slice(0, 52).every((v) => v === null)).toBe(true);
    expect(out.low[51]).toBeNull();
    expect(out.high[52]).not.toBeNull();
    // Half a year of weekly bars never covers a year, so it draws nothing at all.
    const halfYear = weekly.slice(0, 26);
    expect(run(HIGH_LOW_52_WEEK, halfYear).high.every((v) => v === null)).toBe(true);
  });

  it('drops a high exactly 52 weeks after its day, across a weekend', () => {
    // Weekday bars from Monday 2024-01-01. A spike on Friday 2024-03-01 is in
    // the window of Thursday 2025-02-27 (363 days later) and gone on Friday
    // 2025-02-28 (364 days later). A spike on Monday 2024-03-04 is still in the
    // window of Friday 2025-02-28, and gone on the Monday after that weekend.
    const start = Date.UTC(2024, 0, 1, 10) / 1000;
    const days: Bar[] = [];
    for (let t = start; t < Date.UTC(2025, 2, 10) / 1000; t += DAY) {
      const weekday = new Date(t * 1000).getUTCDay();
      if (weekday === 0 || weekday === 6) continue;
      days.push({ time: t, open: 100, high: 101, low: 99, close: 100, volume: 1000 });
    }
    const index = (y: number, m: number, d: number): number => days.findIndex((b) => b.time === Date.UTC(y, m - 1, d, 10) / 1000);
    days[index(2024, 3, 1)] = { ...days[index(2024, 3, 1)], high: 150 };
    days[index(2024, 3, 4)] = { ...days[index(2024, 3, 4)], high: 140 };
    const out = run(HIGH_LOW_52_WEEK, days).high;
    expect(out[index(2025, 2, 27)]).toBe(150);
    expect(out[index(2025, 2, 28)]).toBe(140);
    expect(out[index(2025, 3, 3)]).toBe(101);
  });

  it('counts the 52 weeks in the chart zone, not in UTC', () => {
    // P at 20:00 UTC is already the next day in IST and still the same day in
    // New York. Q, 364 UTC days later at 12:00, is the same day in both.
    //   IST:      P on 2024-01-11, Q on 2025-01-08: 363 days apart, P is inside
    //   New York: P on 2024-01-10, Q on 2025-01-08: 364 days apart, P is out
    const bar = (t: number, high: number): Bar => ({ time: t, open: 100, high, low: 99, close: 100, volume: 1000 });
    const history = [
      bar(Date.UTC(2024, 0, 1, 12) / 1000, 101),
      bar(Date.UTC(2024, 0, 10, 20) / 1000, 150),
      bar(Date.UTC(2024, 5, 3, 12) / 1000, 101),
      bar(Date.UTC(2025, 0, 8, 12) / 1000, 101),
    ];
    expect(run(HIGH_LOW_52_WEEK, history).high[3]).toBe(150);
    expect(run(HIGH_LOW_52_WEEK, history, { timezone: 'Asia/Kolkata' }).high[3]).toBe(150);
    expect(run(HIGH_LOW_52_WEEK, history, { timezone: 'America/New_York' }).high[3]).toBe(101);
  });

  it('skips a bar with no high or low without losing the rest of the window', () => {
    const holed = weekly.slice();
    holed[20] = { ...holed[20], high: NaN, low: NaN };
    const out = run(HIGH_LOW_52_WEEK, holed);
    // The peak at bar 20 is gone, so the window 1..52 peaks at its neighbours.
    expect(out.high[52]).toBe(199);
    expect(out.low[52]).toBe(158);
  });

  it('extends a live tick from the bar before it, as a full calc does', () => {
    const settings = settingsOf(HIGH_LOW_52_WEEK);
    const store = {};
    const held = HIGH_LOW_52_WEEK.calc(weekly, settings, store);
    const next = weekly.slice();
    next[79] = { ...next[79], high: 500, low: 1 };
    const tail = HIGH_LOW_52_WEEK.calcTail!(next, settings, 79, held, store);
    expect(tail).toEqual({ high: [500], low: [1] });
    expect(splice(held, tail!, 79, 80)).toEqual(HIGH_LOW_52_WEEK.calc(next, settings, {}));
  });
});
