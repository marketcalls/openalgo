/**
 * The time axis in the chart's configured zone.
 *
 * Every label on every chart used to be an IST reading, including the decision
 * of which bar gets the date rather than the clock. Two things have to hold at
 * once here, and both are pinned below:
 *
 *  1. A chart that names no zone draws exactly the labels v1.2.0 drew, down to
 *     the byte, and reaches Intl not once while doing it.
 *  2. A chart that names a zone turns its day over at that zone's midnight, and
 *     follows the zone through a DST transition rather than a fixed offset.
 */
import { describe, it, expect, vi } from 'vitest';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { drawTimeAxis, type PlotLayout, type TickMarkType } from '../src/render/axis';
import { RecordingContext } from './helpers/fake-ctx';
import { formatIstDate, formatIstTime, utcSecondsToIstParts } from '../src/feed/time';
import type { Bar } from '../src/model/bar';

const IST = 'Asia/Kolkata';
/**
 * The IANA link name for the same zone. It resolves to IST while being a
 * different string, which is the only way to make the axis take its Intl path
 * over a reading the frozen offset arithmetic can also produce: the labels the
 * two paths draw are then directly comparable.
 */
const IST_ALIAS = 'Asia/Calcutta';
const NY = 'America/New_York';
const LONDON = 'Europe/London';

const utc = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi, s) / 1000);

/** Flat bars `stepSec` apart, so nothing but the timestamp can move a label. */
function bars(from: number, count: number, stepSec = 3600): Bar[] {
  return Array.from({ length: count }, (_, i) => ({
    time: from + i * stepSec, open: 100, high: 101, low: 99, close: 100,
  }));
}

const LAYOUT: PlotLayout = {
  plotWidth: 600, plotHeight: 378, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0,
};

/**
 * Draw one frame of the time axis over `data`. Bar spacing 100 against a 600px
 * plot puts the label stride at one bar and every bar on screen, so the test
 * reads a label per bar instead of guessing which ticks survived thinning.
 */
function drawFrame(
  data: Bar[],
  timezone?: string,
  timeFormatter?: (utcSeconds: number, tickMark?: TickMarkType) => string,
): RecordingContext {
  const dl = new DataLayer();
  dl.setSeriesData(dl.createSeries(), data);
  const ts = new TimeScale({ barSpacing: 100 });
  ts.setWidth(LAYOUT.plotWidth);
  ts.setRightOffset(0);
  ts.setBaseIndex(dl.baseIndex);
  const rec = new RecordingContext();
  drawTimeAxis(
    rec as unknown as CanvasRenderingContext2D, ts, dl, LAYOUT, 1, undefined, timeFormatter, timezone,
  );
  return rec;
}

/** The labels one frame painted, in draw order. */
function labels(data: Bar[], timezone?: string): string[] {
  return drawFrame(data, timezone).ops
    .filter((o) => o.type === 'fillText')
    .map((o) => o.text ?? '');
}

/** The tick-mark hints one frame handed a host formatter, in draw order. */
function tickMarks(data: Bar[], timezone?: string): (TickMarkType | undefined)[] {
  const seen: (TickMarkType | undefined)[] = [];
  drawFrame(data, timezone, (_t, tm) => { seen.push(tm); return 'X'; });
  return seen;
}

// Six hourly bars from 15:00 UTC on 06 Mar 2024. IST rolls over to 07 Mar at
// 18:30 UTC, which is inside this window; New York is on 06 Mar throughout.
const OVER_IST_MIDNIGHT = bars(utc(2024, 3, 6, 15), 6);
// Six hourly bars from 02:00 UTC on 07 Mar 2024. Now it is New York that rolls
// over mid-window (05:00 UTC) and IST that does not.
const OVER_NY_MIDNIGHT = bars(utc(2024, 3, 7, 2), 6);

describe('the default zone draws exactly the labels it drew before', () => {
  it('labels in IST when no zone is given', () => {
    // 20:30, 21:30, 22:30, 23:30, 00:30, 01:30 IST. The leftmost tick has no
    // previous tick to compare against and is dated, as it always was, and the
    // 00:30 bar is the IST day boundary.
    expect(labels(OVER_IST_MIDNIGHT)).toEqual(['06 Mar', '21:30', '22:30', '23:30', '07 Mar', '01:30']);
    expect(labels(OVER_NY_MIDNIGHT)).toEqual(['07 Mar', '08:30', '09:30', '10:30', '11:30', '12:30']);
  });

  it('agrees with the frozen v1.x arithmetic bar by bar', () => {
    // Not a second expectation of the same literals: this is the pre-timezone
    // algorithm, re-run here against the IST helpers that shipped in 1.x.
    for (const data of [OVER_IST_MIDNIGHT, OVER_NY_MIDNIGHT, bars(utc(2024, 1, 31, 17), 6)]) {
      const expected = data.map((b, i) => {
        const prev = i === 0 ? undefined : utcSecondsToIstParts(data[i - 1].time);
        const now = utcSecondsToIstParts(b.time);
        const newDay = prev === undefined
          || prev.year !== now.year || prev.month !== now.month || prev.day !== now.day;
        return newDay ? formatIstDate(b.time) : formatIstTime(b.time);
      });
      expect(labels(data)).toEqual(expected);
    }
  });

  it('passing the default explicitly is the same axis, not a second code path', () => {
    expect(labels(OVER_IST_MIDNIGHT, IST)).toEqual(labels(OVER_IST_MIDNIGHT));
    expect(tickMarks(OVER_IST_MIDNIGHT, IST)).toEqual(tickMarks(OVER_IST_MIDNIGHT));
  });

  it('reads the same through Intl as through the offset arithmetic', () => {
    // The alias takes the zoned path, so this compares Intl against the frozen
    // +5:30 arithmetic rather than assuming the two agree.
    for (const data of [OVER_IST_MIDNIGHT, OVER_NY_MIDNIGHT, bars(utc(2024, 12, 31, 17), 6)]) {
      expect(labels(data, IST_ALIAS)).toEqual(labels(data));
      expect(tickMarks(data, IST_ALIAS)).toEqual(tickMarks(data));
    }
  });
});

describe('a named zone turns the day over at its own midnight', () => {
  it('puts no date break where only IST has one', () => {
    // 10:00 to 15:00 EST, all of it 06 Mar in New York.
    expect(labels(OVER_IST_MIDNIGHT, NY))
      .toEqual(['06 Mar', '11:00', '12:00', '13:00', '14:00', '15:00']);
  });

  it('puts the date break at the US midnight, where IST has none', () => {
    // The same six bars IST labels 07:30 through 12:30 on one day span a New
    // York midnight at 05:00 UTC, and the date label moves onto that bar.
    expect(labels(OVER_NY_MIDNIGHT, NY))
      .toEqual(['06 Mar', '22:00', '23:00', '07 Mar', '01:00', '02:00']);
    // Same bars in IST: the leftmost tick is dated because it has nothing to
    // compare against, and nothing after it is, because the IST day never turns.
    expect(labels(OVER_NY_MIDNIGHT, IST).slice(1).every((l) => /^\d\d:\d\d$/.test(l))).toBe(true);
  });
});

describe('DST is followed, not approximated by a fixed offset', () => {
  it('skips the hour a spring-forward removes', () => {
    // New York, 10 Mar 2024: 02:00 local never happens, 01:00 EST is followed by
    // 03:00 EDT. A fixed -5:00 would have printed 02:00 here.
    expect(labels(bars(utc(2024, 3, 10, 5), 6), NY))
      .toEqual(['10 Mar', '01:00', '03:00', '04:00', '05:00', '06:00']);
    // London, 31 Mar 2024: 01:00 GMT is followed by 02:00 BST.
    expect(labels(bars(utc(2024, 3, 30, 22), 6), LONDON))
      .toEqual(['30 Mar', '23:00', '31 Mar', '02:00', '03:00', '04:00']);
  });

  it('repeats the hour a fall-back replays', () => {
    // London, 27 Oct 2024: 01:00 BST and 01:00 GMT are two different instants an
    // hour apart, and both are labelled 01:00. A fixed +1:00 would have read the
    // second of them as 02:00.
    expect(labels(bars(utc(2024, 10, 26, 23), 6), LONDON))
      .toEqual(['27 Oct', '01:00', '01:00', '02:00', '03:00', '04:00']);
  });

  it('keeps the date on the zone calendar across the transition', () => {
    // The London window above crosses midnight before it crosses the DST
    // boundary, and the date lands on the midnight bar, not the DST one.
    const drawn = labels(bars(utc(2024, 3, 30, 22), 6), LONDON);
    expect(drawn.indexOf('31 Mar')).toBe(2); // 00:00 BST-to-be, i.e. 00:00 UTC
  });
});

describe('the tick-mark hint escalates on the zone calendar', () => {
  it('marks the day boundary the zone has, not the one IST has', () => {
    expect(tickMarks(OVER_NY_MIDNIGHT, NY)).toEqual(['day', 'time', 'time', 'day', 'time', 'time']);
    expect(tickMarks(OVER_NY_MIDNIGHT, IST)).toEqual(['day', 'time', 'time', 'time', 'time', 'time']);
    expect(tickMarks(OVER_IST_MIDNIGHT, IST)).toEqual(['day', 'time', 'time', 'time', 'day', 'time']);
    expect(tickMarks(OVER_IST_MIDNIGHT, NY)).toEqual(['day', 'time', 'time', 'time', 'time', 'time']);
  });

  it('marks month and year boundaries on the zone calendar too', () => {
    // 31 Jan 2024, 17:00 UTC onwards: IST enters February at 18:30 UTC, New York
    // is still in January at the right edge of the window.
    const overIstMonth = bars(utc(2024, 1, 31, 17), 6);
    expect(tickMarks(overIstMonth, IST)).toEqual(['day', 'time', 'month', 'time', 'time', 'time']);
    expect(tickMarks(overIstMonth, NY)).toEqual(['day', 'time', 'time', 'time', 'time', 'time']);

    // 31 Dec 2024, 17:00 UTC onwards: the same shape a year up.
    const overIstYear = bars(utc(2024, 12, 31, 17), 6);
    expect(tickMarks(overIstYear, IST)).toEqual(['day', 'time', 'year', 'time', 'time', 'time']);
    expect(tickMarks(overIstYear, NY)).toEqual(['day', 'time', 'time', 'time', 'time', 'time']);

    // And the New York new year, six hours later, which IST spends inside 01 Jan.
    const overNyYear = bars(utc(2025, 1, 1, 3), 6);
    expect(tickMarks(overNyYear, NY)).toEqual(['day', 'time', 'year', 'time', 'time', 'time']);
    expect(tickMarks(overNyYear, IST)).toEqual(['day', 'time', 'time', 'time', 'time', 'time']);
  });

  it('still reports sub-minute resolution, which no zone changes', () => {
    const tenSecond = bars(utc(2024, 3, 7, 2), 6, 10);
    const expected: TickMarkType[] = ['day', 'timeWithSeconds', 'timeWithSeconds',
      'timeWithSeconds', 'timeWithSeconds', 'timeWithSeconds'];
    expect(tickMarks(tenSecond, NY)).toEqual(expected);
    expect(tickMarks(tenSecond)).toEqual(expected);
    // And the axis' own labels carry the seconds in the named zone.
    expect(labels(tenSecond, NY)).toEqual(['06 Mar', '21:00:10', '21:00:20', '21:00:30', '21:00:40', '21:00:50']);
  });
});

describe('the axis does not pay for Intl on every frame', () => {
  it('resolves each tick once, however many frames it draws', () => {
    // A zone nothing else in this file touches, so the parts cache starts cold.
    const zone = 'America/Denver';
    const spy = vi.spyOn(Intl.DateTimeFormat.prototype, 'formatToParts');
    try {
      labels(OVER_NY_MIDNIGHT, zone);
      // Six ticks, six distinct seconds, one resolution each: the labels and the
      // tick-mark comparisons share them.
      expect(spy).toHaveBeenCalledTimes(6);
      for (let frame = 0; frame < 59; frame++) labels(OVER_NY_MIDNIGHT, zone);
      expect(spy).toHaveBeenCalledTimes(6); // a pan of 60 frames adds nothing
    } finally {
      spy.mockRestore();
    }
  });

  it('touches Intl not at all on the default zone', () => {
    const spy = vi.spyOn(Intl.DateTimeFormat.prototype, 'formatToParts');
    try {
      labels(OVER_IST_MIDNIGHT);
      labels(OVER_IST_MIDNIGHT, IST);
      expect(spy).not.toHaveBeenCalled();
    } finally {
      spy.mockRestore();
    }
  });
});

/**
 * The pane geometry tests/timezone.test.ts paints with (600x400 pane, 56px price
 * axis, 22px time axis, bar spacing 40), so the two files are asking the same
 * axis the same question.
 */
function paneGeometryLabels(data: Bar[], timezone?: string): string[] {
  const dl = new DataLayer();
  dl.setSeriesData(dl.createSeries(), data);
  const ts = new TimeScale({ barSpacing: 40 });
  ts.setWidth(544);
  ts.setBaseIndex(dl.baseIndex);
  const rec = new RecordingContext();
  const layout: PlotLayout = {
    plotWidth: 544, plotHeight: 378, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0,
  };
  drawTimeAxis(rec as unknown as CanvasRenderingContext2D, ts, dl, layout, 1, undefined, undefined, timezone);
  return rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');
}

describe('the zone reaches the axis the same way the pane formatter did', () => {
  // Until the pane hands `drawTimeAxis` the zone, a non-default chart gets there
  // through a formatter the pane synthesises. These are the labels that path
  // paints today (tests/timezone.test.ts), so the swap is provably a no-op.
  const march6 = bars(utc(2024, 3, 6, 12), 12);
  const march7 = bars(utc(2024, 3, 7, 1), 12);

  it('draws what the pane draws today, zone for zone', () => {
    expect(paneGeometryLabels(march6)).toEqual(['20:30', '22:30', '07 Mar', '02:30', '04:30']);
    expect(paneGeometryLabels(march6, IST)).toEqual(['20:30', '22:30', '07 Mar', '02:30', '04:30']);
    expect(paneGeometryLabels(march6, NY)).toEqual(['10:00', '12:00', '14:00', '16:00', '18:00']);
    // The date sits at the bar the day actually turns on, not on the first grid
    // tick after it, so 01:00 keeps its own label instead of being overwritten.
    expect(paneGeometryLabels(march7, NY))
      .toEqual(['23:00', '07 Mar', '01:00', '03:00', '05:00', '07:00']);
    expect(paneGeometryLabels(march7, IST)).toEqual(['09:30', '11:30', '13:30', '15:30', '17:30']);
  });
});

describe('a zone the runtime does not know', () => {
  it('costs the labels their zone, never the frame', () => {
    // The chart rejects an unknown zone where it is set, but the axis runs
    // inside the render loop: throwing here would take the whole chart down.
    expect(() => labels(OVER_IST_MIDNIGHT, 'Mars/Olympus_Mons')).not.toThrow();
    expect(labels(OVER_IST_MIDNIGHT, 'Mars/Olympus_Mons')).toEqual(labels(OVER_IST_MIDNIGHT));
  });
});
