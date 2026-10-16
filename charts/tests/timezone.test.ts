/**
 * Timezone support: IST stays the shipped default, but it stops being the
 * assumption. Two things have to hold at once, and both are pinned here.
 *
 *  1. A caller who passes no timezone gets byte-identical output to v1.2.0, and
 *     the Intl path for 'Asia/Kolkata' agrees with the IST_OFFSET_SECONDS
 *     arithmetic that shipped before it.
 *  2. A caller who names a zone gets that zone, DST included.
 */
import { describe, it, expect, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { Pane, type PaneRenderContext } from '../src/core/pane';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { createSeriesRecord } from '../src/model/series';
import type { TickMarkType } from '../src/render/axis';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';
import {
  DEFAULT_TIMEZONE,
  IST_OFFSET_SECONDS,
  formatIstCrosshairLabel,
  formatIstDate,
  formatIstTime,
  formatIstTimeSeconds,
  formatZonedCrosshairLabel,
  formatZonedDate,
  formatZonedTime,
  formatZonedTimeSeconds,
  isNewIstDay,
  isNewZonedDay,
  isNewZonedMonth,
  isNewZonedPeriod,
  isNewZonedQuarter,
  isNewZonedWeek,
  isNewZonedYear,
  isValidTimezone,
  istStringToUtcSeconds,
  sessionStartFlags,
  startOfZonedDay,
  startOfZonedMonth,
  startOfZonedWeek,
  utcSecondsToIstDateString,
  utcSecondsToIstParts,
  utcSecondsToZonedDateString,
  utcSecondsToZonedParts,
  zonedDayIndex,
  zonedStringToUtcSeconds,
  zonedWeekIndex,
  zoneOffsetSeconds,
} from '../src/feed/time';

const IST = 'Asia/Kolkata';
const NY = 'America/New_York';
const LONDON = 'Europe/London';

const utc = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi, s) / 1000);

// ---------------------------------------------------------------------------
// 1. The Intl path for the default zone must reproduce the old arithmetic.
// ---------------------------------------------------------------------------

describe("'Asia/Kolkata' through Intl matches the IST_OFFSET_SECONDS arithmetic", () => {
  /**
   * A year of instants at a stride that is coprime with the day, so the sweep
   * visits every hour and a spread of minutes rather than the same clock time
   * over and over. Plus the instants that actually break naive conversions.
   */
  const samples: number[] = [
    utc(2024, 1, 1, 0, 0, 0), // a UTC midnight (IST 05:30, same day)
    utc(2023, 12, 31, 18, 30, 0), // an IST midnight (UTC is still the old year)
    utc(2024, 2, 29, 0, 0, 0), // leap day, UTC midnight
    utc(2024, 2, 28, 18, 30, 0), // leap day, IST midnight
    utc(2024, 2, 29, 18, 29, 59), // the last second of the leap day in IST
    utc(2024, 3, 10, 7, 0, 0), // US spring-forward instant (a no-op in IST)
    0,
  ];
  const start = utc(2024, 1, 1);
  for (let t = start; t < start + 366 * 86400; t += 3607) samples.push(t);

  it('resolves the same calendar parts', () => {
    for (const t of samples) {
      expect(utcSecondsToZonedParts(t, IST)).toEqual(utcSecondsToIstParts(t));
    }
  });

  it('formats every label identically', () => {
    for (const t of samples) {
      expect(formatZonedTime(t, IST)).toBe(formatIstTime(t));
      expect(formatZonedTimeSeconds(t, IST)).toBe(formatIstTimeSeconds(t));
      expect(formatZonedDate(t, IST)).toBe(formatIstDate(t));
      expect(utcSecondsToZonedDateString(t, IST)).toBe(utcSecondsToIstDateString(t));
      expect(formatZonedCrosshairLabel(t, IST)).toBe(formatIstCrosshairLabel(t));
    }
  });

  it('agrees on where an IST day boundary falls', () => {
    for (let i = 1; i < samples.length; i++) {
      const prev = samples[i - 1];
      const now = samples[i];
      expect(isNewZonedDay(prev, now, IST)).toBe(isNewIstDay(prev, now));
    }
    // And on the boundary itself, from the second either side of it.
    const midnight = utc(2024, 5, 20, 18, 30, 0);
    expect(isNewZonedDay(midnight - 1, midnight, IST)).toBe(true);
    expect(isNewZonedDay(midnight, midnight + 1, IST)).toBe(false);
  });

  it('parses an IST wall-clock string to the same instant', () => {
    for (const s of ['2024-01-01', '2024-02-29 09:15', '2024-02-29T15:30:45', '2023-12-31 23:59:59']) {
      expect(zonedStringToUtcSeconds(s, IST)).toBe(istStringToUtcSeconds(s));
    }
  });

  it('reports the fixed +5:30 offset the arithmetic assumes', () => {
    for (const t of samples) expect(zoneOffsetSeconds(t, IST)).toBe(IST_OFFSET_SECONDS);
  });

  it('defaults every zone-aware helper to IST', () => {
    const t = utc(2024, 2, 29, 12, 0, 0);
    expect(DEFAULT_TIMEZONE).toBe(IST);
    expect(formatZonedTime(t)).toBe(formatIstTime(t));
    expect(utcSecondsToZonedParts(t)).toEqual(utcSecondsToIstParts(t));
    expect(zonedStringToUtcSeconds('2024-02-29 09:15')).toBe(istStringToUtcSeconds('2024-02-29 09:15'));
  });
});

// ---------------------------------------------------------------------------
// 2. The zone-aware helpers themselves.
// ---------------------------------------------------------------------------

describe('zone-aware conversion', () => {
  it('reads an instant in the zone it is asked for', () => {
    const t = utc(2024, 3, 7, 3, 45, 0); // NSE open on 2024-03-07
    expect(formatZonedTime(t, IST)).toBe('09:15');
    expect(formatZonedTime(t, NY)).toBe('22:45'); // the previous evening in New York
    expect(formatZonedDate(t, IST)).toBe('07 Mar');
    expect(formatZonedDate(t, NY)).toBe('06 Mar');
    expect(utcSecondsToZonedDateString(t, NY)).toBe('2024-03-06');
    expect(formatZonedCrosshairLabel(t, NY)).toBe("Wed 06 Mar '24 22:45");
  });

  it('follows DST rather than a fixed offset', () => {
    // The exact class of defect an offset would reintroduce: right in January,
    // an hour wrong in July.
    expect(zoneOffsetSeconds(utc(2024, 1, 15, 12), NY)).toBe(-5 * 3600);
    expect(zoneOffsetSeconds(utc(2024, 7, 15, 12), NY)).toBe(-4 * 3600);
    expect(zoneOffsetSeconds(utc(2024, 1, 15, 12), LONDON)).toBe(0);
    expect(zoneOffsetSeconds(utc(2024, 7, 15, 12), LONDON)).toBe(3600);
    // ...and across the changeover itself, to the second.
    const springForward = utc(2024, 3, 10, 7, 0, 0); // 02:00 EST becomes 03:00 EDT
    expect(formatZonedTime(springForward - 1, NY)).toBe('01:59');
    expect(formatZonedTime(springForward, NY)).toBe('03:00');
  });

  it('round-trips a wall-clock string through the zone that produced it', () => {
    for (const zone of [IST, NY, LONDON, 'Australia/Sydney']) {
      for (const s of ['2024-01-15 09:30:00', '2024-07-15 09:30:00', '2024-11-03 01:30:00']) {
        const t = zonedStringToUtcSeconds(s, zone);
        expect(`${utcSecondsToZonedDateString(t, zone)} ${formatZonedTimeSeconds(t, zone)}`).toBe(s);
      }
    }
  });

  it('anchors a day, a Monday-start week and a month in the zone', () => {
    const t = utc(2024, 3, 7, 3, 45, 0); // Thu 07 Mar IST, Wed 06 Mar NY
    expect(utcSecondsToZonedDateString(startOfZonedDay(t, IST), IST)).toBe('2024-03-07');
    expect(formatZonedTimeSeconds(startOfZonedDay(t, IST), IST)).toBe('00:00:00');
    expect(utcSecondsToZonedDateString(startOfZonedDay(t, NY), NY)).toBe('2024-03-06');
    expect(utcSecondsToZonedDateString(startOfZonedWeek(t, IST), IST)).toBe('2024-03-04');
    expect(utcSecondsToZonedDateString(startOfZonedWeek(t, NY), NY)).toBe('2024-03-04');
    expect(utcSecondsToZonedDateString(startOfZonedMonth(t, NY), NY)).toBe('2024-03-01');
    // A week that contains a DST shift is 169 hours long, so stepping back by
    // fixed days would land on Sunday.
    const afterShift = utc(2024, 3, 14, 12);
    expect(utcSecondsToZonedDateString(startOfZonedWeek(afterShift, NY), NY)).toBe('2024-03-11');
    expect(formatZonedTimeSeconds(startOfZonedWeek(afterShift, NY), NY)).toBe('00:00:00');
  });

  it('rejects a zone the runtime does not know', () => {
    expect(isValidTimezone(NY)).toBe(true);
    expect(isValidTimezone('Mars/Olympus_Mons')).toBe(false);
    expect(() => formatZonedTime(0, 'Mars/Olympus_Mons')).toThrow(/unknown IANA time zone/);
  });
});

describe('calendar boundary tests', () => {
  it('answers day, week, month, quarter and year in the named zone', () => {
    const prev = utc(2024, 3, 31, 20, 0, 0); // 31 Mar 16:00 NY, 01 Apr 01:30 IST
    const now = utc(2024, 4, 1, 2, 0, 0); //  31 Mar 22:00 NY, 01 Apr 07:30 IST
    expect(isNewZonedDay(prev, now, IST)).toBe(false); // both already 01 Apr in IST
    expect(isNewZonedDay(prev, now, NY)).toBe(false); // both still 31 Mar in NY
    expect(isNewZonedMonth(prev, now, IST)).toBe(false);
    expect(isNewZonedQuarter(prev, now, NY)).toBe(false);

    const q2 = utc(2024, 4, 1, 14, 0, 0); // 01 Apr in both zones
    expect(isNewZonedMonth(prev, q2, NY)).toBe(true);
    expect(isNewZonedQuarter(prev, q2, NY)).toBe(true);
    expect(isNewZonedYear(prev, q2, NY)).toBe(false);
    // 31 Dec 22:30 IST / 12:00 NY, then 01 Jan 07:30 IST but still 31 Dec 21:00
    // in New York: the year turns for one zone and not the other.
    expect(isNewZonedYear(utc(2023, 12, 31, 17), utc(2024, 1, 1, 2), IST)).toBe(true);
    expect(isNewZonedYear(utc(2023, 12, 31, 17), utc(2024, 1, 1, 2), NY)).toBe(false);
  });

  it('starts the week on Monday, in the zone, not in UTC', () => {
    // The case that makes a fixed calendar rule wrong: a New York Friday session
    // is already Saturday in IST, and the Sunday-evening reopen is Monday there.
    const nyFriday = utc(2024, 3, 8, 20, 0, 0);
    const nySundayEvening = utc(2024, 3, 10, 22, 0, 0);
    expect(isNewZonedWeek(nyFriday, nySundayEvening, NY)).toBe(false);
    expect(isNewZonedWeek(nyFriday, nySundayEvening, IST)).toBe(true);
    // Monday, not Sunday, opens the week.
    expect(zonedWeekIndex(utc(2024, 3, 4, 12), NY)).toBe(zonedWeekIndex(utc(2024, 3, 8, 12), NY));
    expect(zonedWeekIndex(utc(2024, 3, 3, 12), NY)).toBe(zonedWeekIndex(utc(2024, 3, 4, 12), NY) - 1);
  });

  it('counts whole days in the zone', () => {
    const t = utc(2024, 3, 7, 3, 45, 0);
    expect(zonedDayIndex(t, IST) - zonedDayIndex(t, NY)).toBe(1);
    expect(zonedDayIndex(t, IST)).toBe(Math.floor(utc(2024, 3, 7) / 86400));
  });

  it('dispatches by period name for a caller that carries it as data', () => {
    const prev = utc(2024, 3, 8, 20, 0, 0);
    const now = utc(2024, 3, 10, 22, 0, 0);
    expect(isNewZonedPeriod(prev, now, 'day', NY)).toBe(true);
    expect(isNewZonedPeriod(prev, now, 'week', NY)).toBe(false);
    expect(isNewZonedPeriod(prev, now, 'week', IST)).toBe(true);
    expect(isNewZonedPeriod(prev, now, 'month', NY)).toBe(false);
    expect(isNewZonedPeriod(prev, now, 'quarter', NY)).toBe(false);
    expect(isNewZonedPeriod(prev, now, 'year', NY)).toBe(false);
  });

  it('falls session flags back to the calendar day of the zone it is given', () => {
    // Daily bars: no readable session break, so the calendar rule decides. These
    // land on a Thursday and a Friday in IST but the Wednesday and Thursday
    // evenings in New York, so both zones see two distinct days here...
    const daily = [utc(2024, 3, 7, 3, 45), utc(2024, 3, 8, 3, 45)];
    expect(sessionStartFlags(daily)).toEqual([false, true]);
    expect(sessionStartFlags(daily, NY)).toEqual([false, true]);
    // Naming the default is the same answer as omitting it, over a long run:
    // the omitted form takes the cheap arithmetic path and must not diverge.
    const year = Array.from({ length: 400 }, (_, i) => utc(2024, 1, 1, 3, 45) + i * 86400);
    expect(sessionStartFlags(year)).toEqual(sessionStartFlags(year, IST));
    // ...but two IST-morning bars either side of a New York midnight do not.
    const sameNyDay = [utc(2024, 3, 7, 3, 45), utc(2024, 3, 7, 9, 45)];
    expect(sessionStartFlags(sameNyDay, IST)).toEqual([false, false]);
    const acrossNyMidnight = [utc(2024, 3, 7, 3, 45), utc(2024, 3, 7, 6, 0)];
    expect(sessionStartFlags(acrossNyMidnight, NY)).toEqual([false, true]);
    expect(sessionStartFlags(acrossNyMidnight, IST)).toEqual([false, false]);
  });
});

describe('the parts cache', () => {
  it('calls Intl once per zone per distinct second, however often it is asked', () => {
    // A zone nothing else in this file touches, so the cache starts cold.
    const zone = 'Pacific/Chatham';
    const spy = vi.spyOn(Intl.DateTimeFormat.prototype, 'formatToParts');
    try {
      const t = utc(2024, 3, 7, 3, 45, 0);
      for (let i = 0; i < 500; i++) formatZonedTime(t, zone);
      expect(spy).toHaveBeenCalledTimes(1);
      // The boundary tests alternate between two instants, and the second one
      // becomes the first of the next call: both have to stay resident.
      for (let i = 0; i < 500; i++) isNewZonedDay(t, t + 60, zone);
      expect(spy).toHaveBeenCalledTimes(2);
      // A different label of the same instant is still one resolution.
      formatZonedDate(t, zone);
      formatZonedCrosshairLabel(t, zone);
      expect(spy).toHaveBeenCalledTimes(2);
    } finally {
      spy.mockRestore();
    }
  });

  it('hands every caller its own parts object', () => {
    const t = utc(2024, 3, 7, 3, 45, 0);
    const a = utcSecondsToZonedParts(t, NY);
    a.hour = 99;
    expect(utcSecondsToZonedParts(t, NY).hour).toBe(22);
  });
});

// ---------------------------------------------------------------------------
// 3. The chart: the default must not move, and a named zone must reach the axis.
// ---------------------------------------------------------------------------

/** Hourly bars from `from`, flat so nothing but the time matters. */
function hourlyBars(from: number, count: number): Bar[] {
  return Array.from({ length: count }, (_, i) => ({
    time: from + i * 3600, open: 100, high: 101, low: 99, close: 100,
  }));
}

/** A pane loaded with `bars`, sized so its plot is 544 x 378 media px. */
function loadedPane(bars: Bar[], timezone?: string): { pane: Pane; ctx: PaneRenderContext } {
  const dl = new DataLayer();
  const id = dl.createSeries();
  dl.setSeriesData(id, bars);
  const ts = new TimeScale({ barSpacing: 40 });
  ts.setWidth(544); // 600 wide pane less the 56px price axis
  ts.setBaseIndex(dl.baseIndex);
  const ctx: PaneRenderContext = {
    timeScale: ts, dataLayer: dl, dpr: 1, priceAxisWidth: 56, timeAxisHeight: 22,
    showTimeAxis: true, conflate: false, conflationFactor: 1, theme: darkTheme,
    showVertGrid: false, showHorzGrid: false, timezone,
  };
  const pane = new Pane(fakeDocument());
  pane.addSeries(createSeriesRecord(id, 'candlestick'));
  pane.resize(600, 400, 1);
  pane.autoscale(ctx);
  return { pane, ctx };
}

/** The time-axis labels a pane painted, in draw order. */
function paintedLabels(bars: Bar[], timezone?: string): string[] {
  const { pane, ctx } = loadedPane(bars, timezone);
  pane.paintBase(ctx);
  const rec = pane.base.ctx as unknown as RecordingContext;
  // The time axis is the only text on the strip below the plot.
  const y = 400 - 22 + 4;
  return rec.ops.filter((o) => o.type === 'fillText' && o.args[1] === y).map((o) => o.text ?? '');
}

/** The crosshair time tag a pane painted with the cursor over bar `index`. */
function crosshairLabel(bars: Bar[], index: number, timezone?: string): string {
  const { pane, ctx } = loadedPane(bars, timezone);
  pane.paintTop({ x: ctx.timeScale.indexToX(index), yLocal: 100, showTimeTag: true }, ctx);
  const rec = pane.top.ctx as unknown as RecordingContext;
  const texts = rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');
  // The price tag is drawn first, the time tag second.
  return texts[texts.length - 1];
}

describe('chart timezone', () => {
  // 12 hourly bars from 2024-03-06 12:00 UTC = 17:30 IST, so the window spans an
  // IST midnight (18:30 UTC) and a New York midnight (05:00 UTC).
  const bars = hourlyBars(utc(2024, 3, 6, 12, 0, 0), 12);

  it('labels in IST when no timezone is given, exactly as it did before', () => {
    // Ticks at 15:00, 17:00, 19:00, 21:00 and 23:00 UTC. IST turns the day over
    // at 18:30 UTC, so the third of them is a date and the rest are clocks.
    const expected = ['20:30', '22:30', '07 Mar', '02:30', '04:30'];
    expect(paintedLabels(bars)).toEqual(expected);
    // Passing the default explicitly is the same chart, not a second code path.
    expect(paintedLabels(bars, IST)).toEqual(expected);
    // And each label is what the frozen v1.x arithmetic says it is.
    expect(expected[0]).toBe(formatIstTime(bars[3].time));
    expect(expected[2]).toBe(formatIstDate(bars[7].time));
    expect(expected[4]).toBe(formatIstTime(bars[11].time));
  });

  it('labels in the named zone, moving the date label to that zone midnight', () => {
    // The same ticks read in New York: all still 06 Mar there, so no date label.
    expect(paintedLabels(bars, NY)).toEqual(['10:00', '12:00', '14:00', '16:00', '18:00']);
    // Twelve hours on, the New York day turns over mid-window and the IST one
    // does not: the date label moves to a different bar entirely.
    const later = hourlyBars(utc(2024, 3, 7, 1, 0, 0), 12);
    // The date marks the bar the day turns on, so 01:00 keeps its own label.
    expect(paintedLabels(later, NY))
      .toEqual(['23:00', '07 Mar', '01:00', '03:00', '05:00', '07:00']);
    expect(paintedLabels(later, IST)).toEqual(['09:30', '11:30', '13:30', '15:30', '17:30']);
  });

  it('tags the crosshair in the chart zone too, not only the axis', () => {
    // Bar 7 is 19:00 UTC: 07 Mar 00:30 in IST, still 06 Mar 14:00 in New York.
    expect(crosshairLabel(bars, 7)).toBe(formatIstCrosshairLabel(bars[7].time));
    expect(crosshairLabel(bars, 7)).toBe("Thu 07 Mar '24 00:30");
    expect(crosshairLabel(bars, 7, IST)).toBe("Thu 07 Mar '24 00:30");
    expect(crosshairLabel(bars, 7, NY)).toBe("Wed 06 Mar '24 14:00");
  });

  it('carries the option, the setter and the state round-trip', () => {
    const chart = makeChart({ timezone: NY });
    expect(chart.timezone()).toBe(NY);

    chart.setTimezone(LONDON);
    expect(chart.timezone()).toBe(LONDON);
    chart.applyOptions({ timezone: NY });
    expect(chart.timezone()).toBe(NY);

    const state = chart.getState();
    expect(state.timezone).toBe(NY);

    const restored = makeChart();
    expect(restored.timezone()).toBe(IST);
    expect(restored.restoreState(state).applied).toBe(true);
    expect(restored.timezone()).toBe(NY);
  });

  it('defaults to IST and keeps it out of nobody-asked territory', () => {
    const chart = makeChart();
    expect(chart.timezone()).toBe(IST);
    expect(chart.getState().timezone).toBe(IST);
  });

  it('refuses a zone name the runtime does not know, at the call site', () => {
    expect(() => makeChart({ timezone: 'Mars/Olympus_Mons' })).toThrow(/unknown IANA time zone/);
    const chart = makeChart();
    expect(() => chart.setTimezone('Not/AZone')).toThrow(/unknown IANA time zone/);
    expect(chart.timezone()).toBe(IST); // and leaves the chart on the old one
    // A stale zone in a saved layout must not cost the caller the rest of it.
    const state = { ...chart.getState(), timezone: 'Mars/Olympus_Mons' };
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.timezone()).toBe(IST);
  });

  /**
   * The pane has to hand the axis the zone itself, not a labeller built from
   * it. A host that formats its own labels still gets the `tickMark` hint, and
   * that hint is the axis' answer to "did the day turn over here?": a question
   * only the chart's calendar can settle. Pre-baking a labeller left the hint
   * on IST, so a New York chart told its host the day had turned at 18:30 New
   * York time, in the middle of the trading afternoon.
   */
  it('computes the tickMark hint on the chart zone, not on IST', () => {
    const hints = (timezone?: string): (TickMarkType | undefined)[] => {
      const seen: (TickMarkType | undefined)[] = [];
      const { pane, ctx } = loadedPane(bars, timezone);
      ctx.timeFormatter = (utcSeconds, tickMark): string => {
        seen.push(tickMark);
        return String(utcSeconds);
      };
      pane.paintBase(ctx);
      return seen;
    };

    // Ticks at 15:00, 17:00, 19:00, 21:00 and 23:00 UTC. IST turns the day over
    // at 18:30 UTC, so the 19:00 tick is a day boundary.
    expect(hints()).toEqual(['time', 'time', 'day', 'time', 'time']);
    expect(hints(IST)).toEqual(['time', 'time', 'day', 'time', 'time']);
    // New York turns over at 05:00 UTC, which none of these ticks crosses, so
    // the host is told the whole window is one trading afternoon.
    expect(hints(NY)).toEqual(['time', 'time', 'time', 'time', 'time']);
  });
});

/**
 * A chart that paints synchronously. Both halves matter: without `applySize`
 * every price scale sits on its 0..1 placeholder, and without the synchronous
 * raf no frame has run by the time a call returns.
 */
function makeChart(options: { timezone?: string } = {}): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...options,
  });
  chart.applySize(800, 600);
  return chart;
}
