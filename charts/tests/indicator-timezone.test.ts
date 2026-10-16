/**
 * The four indicators that resolve calendar units, checked against the chart's
 * configured zone.
 *
 * VWAP's coarse anchors, CPR's weekly and monthly frames, TWAP's session
 * fallback and Seasonality's month attribution all used to be IST arithmetic,
 * which is 18:30 UTC and therefore the middle of a US trading day. The two
 * things worth proving are opposites of each other: a caller who passes no zone
 * must get byte-identical numbers to 1.2.0, and a caller on America/New_York
 * must get a month that ends when New York's month ends.
 */
import { describe, it, expect } from 'vitest';
import {
  calendarPeriodFlags, isNewZonedPeriod, utcSecondsToIstParts, utcSecondsToZonedParts,
  IST_OFFSET_SECONDS,
} from '../src/index';
import type { Bar } from '../src/index';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorValues } from '../src/model/indicator-registry';
import type { TableCell } from '../src/primitives/table';
import { VWAP } from '../src/indicators/trend';
import { CPR } from '../src/indicators/studies';
import { TWAP } from '../src/indicators/averages';
import { SEASONALITY } from '../src/indicators/seasonality';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import '../src/indicators/index'; // side effect: registers the built-ins

const NY = 'America/New_York';
const HOUR = 3600;
const DAY = 86400;

const settingsFor = (
  d: IndicatorDescriptor,
  over: Record<string, unknown> = {},
): Record<string, unknown> => ({ ...indicatorDefaults(d), ...over });

const run = (
  d: IndicatorDescriptor,
  bars: readonly Bar[],
  over: Record<string, unknown> = {},
): IndicatorValues => d.calc(bars, settingsFor(d, over), {});

/** A finite reading, or NaN: spares every assertion a null check. */
const at = (values: IndicatorValues, key: string, i: number): number => {
  const v = values[key]?.[i];
  return v === null || v === undefined ? NaN : v;
};

// ── the v1.2.0 rules, reimplemented ──────────────────────────────────────────
//
// Copied from the shipped 1.2.0 sources rather than imported, so the parity
// assertions below compare against what the library actually did and not
// against whatever the current code happens to produce.

const oldIstDay = (t: number): number => Math.floor((t + IST_OFFSET_SECONDS) / DAY);
const oldIstWeek = (t: number): number => Math.floor((oldIstDay(t) - 4) / 7);

type Period = 'week' | 'month' | 'quarter' | 'year';

function oldStartsNewPeriod(kind: Period, prev: number, now: number): boolean {
  if (kind === 'week') return oldIstWeek(prev) !== oldIstWeek(now);
  const a = utcSecondsToIstParts(prev);
  const b = utcSecondsToIstParts(now);
  if (kind === 'year') return a.year !== b.year;
  if (kind === 'quarter') {
    return a.year !== b.year || Math.floor((a.month - 1) / 3) !== Math.floor((b.month - 1) / 3);
  }
  return a.year !== b.year || a.month !== b.month;
}

const PERIODS: readonly Period[] = ['week', 'month', 'quarter', 'year'];

// ── bar builders ─────────────────────────────────────────────────────────────

const utc = (y: number, mo: number, d: number, h = 0, mi = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi) / 1000);

const isWeekend = (t: number): boolean => {
  const day = new Date(t * 1000).getUTCDay();
  return day === 0 || day === 6;
};

/** Every weekday date in `[from, to)`, as the UTC midnight opening it. */
function weekdays(from: number, to: number): number[] {
  const out: number[] = [];
  for (let t = from; t < to; t += DAY) if (!isWeekend(t)) out.push(t);
  return out;
}

/**
 * Five-minute bars for the New York regular session (13:30-20:00 UTC, which is
 * 09:30-16:00 while the city is on EDT), every weekday in the range.
 *
 * Flat at 100 apart from the last ninety minutes of 30 April, which close at
 * 130. That window is exactly the part of the session that falls after 18:30
 * UTC, so it is April in New York and May in IST: the whole bug in one price.
 */
function nyIntraday(): Bar[] {
  const bars: Bar[] = [];
  for (const day of weekdays(utc(2024, 3, 11), utc(2024, 5, 4))) {
    for (let k = 0; k < 78; k++) {
      const time = day + 13.5 * HOUR + k * 300;
      const late = time >= utc(2024, 4, 30, 18, 30) && time < utc(2024, 5, 1);
      const close = late ? 130 : 100;
      bars.push({ time, open: close, high: close + 1, low: close - 1, close, volume: 1000 });
    }
  }
  return bars;
}

/**
 * Daily bars for the same exchange, stamped at the session close (20:00 UTC),
 * which is what a good many daily feeds return. That stamp is past 18:30 UTC,
 * so IST reads every one of these bars as the following calendar day and a
 * month-end bar as belonging to the month after it.
 *
 * March is given a wider range than April so the two frames' pivots differ, and
 * 30 April is the April high so it is obvious which frame swallowed it.
 */
function nyDaily(): Bar[] {
  return weekdays(utc(2024, 3, 1), utc(2024, 5, 11)).map((day) => {
    const time = day + 20 * HOUR;
    const march = time < utc(2024, 4, 1);
    const high = time === utc(2024, 4, 30, 20) ? 200 : march ? 110 : 101;
    return { time, open: 100, high, low: 99, close: 100, volume: 1000 };
  });
}

/** Index of the bar stamped on a given UTC day, or -1. */
const dayIndex = (bars: readonly Bar[], y: number, mo: number, d: number): number =>
  bars.findIndex((b) => b.time >= utc(y, mo, d) && b.time < utc(y, mo, d) + DAY);

/**
 * Hourly bars round the clock for four days, the shape a 24/7 venue produces.
 * Nothing in them marks a session, so every session-anchored study has to fall
 * back to the calendar day, which is the only case where TWAP consults a zone
 * at all. Each bar carries its own index as its price, so a restart is visible
 * as `twap[i] === i`.
 */
function roundTheClock(count = 96): Bar[] {
  return Array.from({ length: count }, (_, i) => {
    const v = i;
    return { time: utc(2024, 4, 1) + i * HOUR, open: v, high: v, low: v, close: v, volume: 1000 };
  });
}

/** Daily bars at the NSE open across seven years, for the parity sweep. */
function nseDaily(): Bar[] {
  return weekdays(utc(2019, 1, 1), utc(2026, 1, 1)).map((day, i) => {
    const close = 100 + (i % 37);
    return { time: day + 3.75 * HOUR, open: close, high: close + 2, low: close - 2, close, volume: 500 };
  });
}

// ── the foundation, before anything is built on it ───────────────────────────

describe('Asia/Kolkata through Intl is the old IST arithmetic', () => {
  it('resolves the same calendar parts', () => {
    for (const bar of nseDaily()) {
      for (const t of [bar.time, bar.time + 6 * HOUR, bar.time + 20 * HOUR + 1799]) {
        expect(utcSecondsToZonedParts(t)).toEqual(utcSecondsToIstParts(t));
      }
    }
  });

  it('draws every period boundary in the same place', () => {
    const times = nseDaily().map((b) => b.time);
    for (const period of PERIODS) {
      expect(calendarPeriodFlags(times, (a, b) => isNewZonedPeriod(a, b, period)))
        .toEqual(calendarPeriodFlags(times, (a, b) => oldStartsNewPeriod(period, a, b)));
    }
  });

  it('draws them in the same place on intraday bars too', () => {
    const times = nyIntraday().map((b) => b.time);
    for (const period of PERIODS) {
      expect(calendarPeriodFlags(times, (a, b) => isNewZonedPeriod(a, b, period)))
        .toEqual(calendarPeriodFlags(times, (a, b) => oldStartsNewPeriod(period, a, b)));
    }
  });
});

// ── VWAP ─────────────────────────────────────────────────────────────────────

describe('VWAP anchors', () => {
  const bars = nyDaily();
  const apr30 = dayIndex(bars, 2024, 4, 30);
  const may1 = dayIndex(bars, 2024, 5, 1);
  /** hlc3 of the 30 April bar, which is what a restart on that bar prints. */
  const APR30_HLC3 = (200 + 99 + 100) / 3;

  it('the default restarts where IST said it did, mid-session on a US symbol', () => {
    // 30 April closes at 20:00 UTC, which IST calls 1 May: the month anchor
    // restarts a day early and prints that bar's own hlc3. Unchanged from 1.2.0,
    // deliberately: a caller who names no zone gets the old numbers.
    const v = run(VWAP, bars, { anchor: 'month' });
    expect(at(v, 'vwap', apr30)).toBeCloseTo(APR30_HLC3, 10);
    // 1 May is the second bar of the frame IST opened on 30 April.
    expect(at(v, 'vwap', may1)).toBeCloseTo((APR30_HLC3 + 100) / 2, 10);
  });

  it('naming the zone keeps the month-end bar inside April', () => {
    const v = run(VWAP, bars, { anchor: 'month', timezone: NY });
    // April has 22 weekdays: 21 bars at hlc3 100 and the 30th at 133.
    expect(at(v, 'vwap', apr30)).toBeCloseTo((21 * 100 + APR30_HLC3) / 22, 10);
    // May restarts on its own first bar, as a month anchor should.
    expect(at(v, 'vwap', may1)).toBeCloseTo(100, 10);
  });

  it('the explicit default is the implicit one', () => {
    for (const anchor of ['session', 'week', 'month', 'quarter', 'year', 'continuous']) {
      expect(run(VWAP, bars, { anchor, timezone: 'Asia/Kolkata' }))
        .toEqual(run(VWAP, bars, { anchor }));
    }
  });

  it('falls back to the default rather than throwing on a zone nobody has heard of', () => {
    expect(run(VWAP, bars, { anchor: 'month', timezone: 'Mars/Olympus_Mons' }))
      .toEqual(run(VWAP, bars, { anchor: 'month' }));
  });
});

// ── CPR ──────────────────────────────────────────────────────────────────────

describe('CPR pivot frames', () => {
  const bars = nyDaily();
  const apr30 = dayIndex(bars, 2024, 4, 30);
  const may1 = dayIndex(bars, 2024, 5, 1);
  const monthly = { pivotMode: 'manual', showDaily: false, showWeekly: false, showMonthly: true };
  /** (H + L + C) / 3 of March, and of April with and without its last day. */
  const MARCH = (110 + 99 + 100) / 3;
  const APRIL_WITHOUT_30TH = (101 + 99 + 100) / 3;
  const APRIL = (200 + 99 + 100) / 3;

  it('the default opens the May frame a day early, exactly as IST always did', () => {
    const v = run(CPR, bars, monthly);
    expect(at(v, 'mPivot', apr30)).toBeCloseTo(APRIL_WITHOUT_30TH, 10);
    expect(at(v, 'mPivot', may1)).toBeCloseTo(APRIL_WITHOUT_30TH, 10);
  });

  it('naming the zone measures April against all of April', () => {
    const v = run(CPR, bars, { ...monthly, timezone: NY });
    // Still inside April, so the frame on show is March's.
    expect(at(v, 'mPivot', apr30)).toBeCloseTo(MARCH, 10);
    // May opens on 1 May and inherits April's real high, the 30th's 200.
    expect(at(v, 'mPivot', may1)).toBeCloseTo(APRIL, 10);
  });

  it('the explicit default is the implicit one', () => {
    for (const over of [monthly, { pivotMode: 'manual', showWeekly: true }, {}]) {
      expect(run(CPR, bars, { ...over, timezone: 'Asia/Kolkata' })).toEqual(run(CPR, bars, over));
    }
  });

  it('leaves the daily frame reading its sessions from the bars', () => {
    // The 1.2.0 fix: a daily frame is a trading session, not a calendar day, so
    // the zone must not reach it on bars that show their own session breaks.
    const intraday = nyIntraday();
    const daily = { pivotMode: 'manual', showDaily: true, showWeekly: false, showMonthly: false };
    expect(run(CPR, intraday, { ...daily, timezone: NY })).toEqual(run(CPR, intraday, daily));
  });
});

// ── TWAP ─────────────────────────────────────────────────────────────────────

describe('TWAP session anchor', () => {
  const bars = roundTheClock();

  it('names no timezone in its input label', () => {
    const anchor = TWAP.inputs.find((i) => i.key === 'anchor');
    expect(anchor?.type).toBe('select');
    const labels = anchor?.type === 'select' ? anchor.options.map((o) => o.label) : [];
    expect(labels).toEqual(['Session', 'Continuous']);
    for (const label of labels) expect(label).not.toMatch(/IST/i);
  });

  it('restarts at IST midnight by default, as it always has', () => {
    // 00:00 IST is 18:30 UTC, so the first bar of the new day is the 19:00 one.
    const v = run(TWAP, bars);
    expect(at(v, 'twap', 19)).toBeCloseTo(19, 10);
    expect(at(v, 'twap', 4)).toBeCloseTo((0 + 1 + 2 + 3 + 4) / 5, 10);
  });

  it('restarts at New York midnight when the chart is on New York', () => {
    const v = run(TWAP, bars, { timezone: NY });
    expect(at(v, 'twap', 4)).toBeCloseTo(4, 10);
    expect(at(v, 'twap', 19)).toBeCloseTo((4 + 19) / 2, 10);
  });

  it('the explicit default is the implicit one', () => {
    expect(run(TWAP, bars, { timezone: 'Asia/Kolkata' })).toEqual(run(TWAP, bars));
  });

  it('ignores the zone where the bars show their own sessions', () => {
    const intraday = nyIntraday();
    expect(run(TWAP, intraday, { timezone: NY })).toEqual(run(TWAP, intraday));
  });
});

// ── Seasonality ──────────────────────────────────────────────────────────────

describe('Seasonality month attribution', () => {
  const bars = nyIntraday();

  const gridOf = (over: Record<string, unknown> = {}): readonly (readonly TableCell[])[] => {
    const settings = settingsFor(SEASONALITY, over);
    const spec = SEASONALITY.table?.({
      bars,
      values: SEASONALITY.calc(bars, settings, {}),
      settings,
    });
    expect(spec).toBeTruthy();
    return spec?.rows ?? [];
  };

  /** The 2024 row's April cell: column 0 is the year, so April is column 4. */
  const april = (over: Record<string, unknown> = {}): TableCell => {
    const rows = gridOf(over);
    const row = rows.find((r) => r[0]?.text === '2024');
    expect(row).toBeTruthy();
    return (row ?? [])[4];
  };

  it('the default loses the last ninety minutes of April to May', () => {
    // April closes at 100 on the 18:25 UTC bar, because everything after 18:30
    // is already May in IST. That is the 1.2.0 answer and it stays the 1.2.0
    // answer for anyone who names no zone.
    expect(april().text).toBe('0.00%');
  });

  it('naming the zone reads April to its own close', () => {
    expect(april({ timezone: NY }).text).toBe('30.00%');
  });

  it('the explicit default is the implicit one', () => {
    expect(gridOf({ timezone: 'Asia/Kolkata' })).toEqual(gridOf());
  });

  it('splits months on the calendar and not on the session', () => {
    // Unlike the VWAP and CPR frames, a month's return is a calendar fact: a
    // session straddling midnight on the last of the month has bars in both
    // months and the earlier ones belong to the earlier month.
    const rows = gridOf({ timezone: NY });
    expect(rows[0]?.[4]?.text).toBe('Apr');
    // March has no predecessor to measure against and May is still forming.
    const row = rows.find((r) => r[0]?.text === '2024') ?? [];
    expect(row[3]?.text).toBe('');
    expect(row[5]?.text).toBe('SKIP');
  });
});


/**
 * The zone has to travel from the chart to the calculation, and there is no
 * argument that carries it: a `calc` is handed `(bars, settings, store)` and
 * never the chart. It rides the settings blob under the reserved `timezone`
 * key, and the piece that must exist for any of the above to matter in a real
 * chart is the one that puts it there.
 */
describe('the chart zone reaches the indicator', () => {
  /**
   * Hourly bars straddling 29 Feb 2024 12:00 UTC onward. The IST month turns
   * over at 18:30 UTC on the 29th and the New York one at 05:00 UTC on the 1st,
   * so a monthly anchor lands on a different bar in each zone. Prices and
   * volumes vary per bar, or every anchor would average to the same number.
   */
  const bars: Bar[] = Array.from({ length: 72 }, (_, i) => {
    const close = 100 + (i % 11);
    return {
      time: Date.UTC(2024, 1, 29, 12, 0, 0) / 1000 + i * HOUR,
      open: close, high: close + 1, low: close - 1, close, volume: 500 + i * 7,
    };
  });

  function chartValues(timezone?: string): IndicatorValues {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      ...(timezone === undefined ? {} : { timezone }),
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(bars);
    const vwap = chart.addIndicator('vwap', { anchor: 'month' });
    return vwap.values();
  }

  it('computes on the chart zone, and on IST when none was named', () => {
    // A chart that names nothing is the 1.2.0 calculation, unchanged.
    expect(chartValues()).toEqual(run(VWAP, bars, { anchor: 'month' }));
    // A chart on New York is the New York calculation, which is a different
    // set of numbers: the monthly anchor resets 10.5 hours later.
    expect(chartValues(NY)).toEqual(run(VWAP, bars, { anchor: 'month', timezone: NY }));
    expect(chartValues(NY)).not.toEqual(chartValues());
  });

  it('recomputes when the zone changes under a live indicator', () => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      pixelRatio: () => 1,
      shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(bars);
    const vwap = chart.addIndicator('vwap', { anchor: 'month' });
    expect(vwap.values()).toEqual(run(VWAP, bars, { anchor: 'month' }));

    chart.setTimezone(NY);
    expect(vwap.values()).toEqual(run(VWAP, bars, { anchor: 'month', timezone: NY }));

    // And the zone stays out of the user's own settings, so a layout saved on
    // this chart does not carry New York onto whatever chart restores it.
    expect(vwap.settings().timezone).toBeUndefined();
    expect(chart.getState().indicators?.[0].settings.timezone).toBeUndefined();
  });
});
