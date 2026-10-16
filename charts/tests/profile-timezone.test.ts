/**
 * Profiles on an arbitrary timezone.
 *
 * Three things are being defended here, in order of how expensive they would be
 * to get wrong:
 *
 * 1. The default still is IST. Every grouping this file pins is computed twice,
 *    once by the shipped code and once by a verbatim copy of the v1.2.0
 *    arithmetic kept below, and the two partitions must be the same objects in
 *    the same order.
 * 2. A `TRADING_HOURS` preset selects real instants, not clock readings. Viewing
 *    an NSE chart from New York must move labels and nothing else.
 * 3. An overnight window is still one session, on any clock.
 */
import { describe, it, expect } from 'vitest';
import {
  computeMarketProfile,
  inWindow,
  TRADING_HOURS,
  type MarketProfileSession,
  type SessionWindow,
} from '../src/profile/market-profile';
import { computeVolumeProfileSessions, type VolumeProfileSession } from '../src/profile/volume-profile-family';
import {
  istStringToUtcSeconds,
  utcSecondsToIstParts,
  utcSecondsToZonedParts,
  zonedDayIndex,
  zonedWallClockToUtcSeconds,
} from '../src/feed/time';
import type { Bar } from '../src/model/bar';

const HOUR = 3600;
const DAY = 86400;

const bar = (time: number, low: number, high: number, volume = 100): Bar => ({
  time, open: low, high, low, close: high, volume,
});

/** UTC wall clock to UTC seconds, so an instant in a test reads as an instant. */
const utc = (y: number, m: number, d: number, h = 0, min = 0): number =>
  Math.floor(Date.UTC(y, m - 1, d, h, min) / 1000);

/** A deterministic intraday series: `days` days of half-hourly bars. */
function series(startUtc: number, days: number): Bar[] {
  const out: Bar[] = [];
  const n = days * 48;
  for (let i = 0; i < n; i++) {
    // A slow wave, so levels and the POC actually differ between sessions.
    const base = 100 + ((i * 7) % 23);
    out.push(bar(startUtc + i * 1800, base, base + 4, 100 + (i % 5)));
  }
  return out;
}

// ---------------------------------------------------------------------------
// v1.2.0, copied verbatim. This is the "before" half of every before-and-after
// pin below: if the shipped code stops agreeing with it under the default zone,
// an existing caller's profiles have moved.
// ---------------------------------------------------------------------------

const LEGACY_TRADING_HOURS: Record<string, SessionWindow> = {
  'all-hours': { startMinute: 0, endMinute: 0 },
  'india': { startMinute: 9 * 60 + 15, endMinute: 15 * 60 + 30 },
  'asia': { startMinute: 5 * 60 + 30, endMinute: 11 * 60 + 30 },
  'london': { startMinute: 11 * 60 + 30, endMinute: 17 * 60 + 30 },
  'new-york': { startMinute: 17 * 60 + 30, endMinute: 60 },
  'us-regular': { startMinute: 19 * 60, endMinute: 90 },
};

const legacyPad2 = (n: number): string => (n < 10 ? `0${n}` : `${n}`);

function legacyMinuteOfDay(utcSeconds: number): number {
  const p = utcSecondsToIstParts(utcSeconds);
  return p.hour * 60 + p.minute;
}

function legacyInWindow(utcSeconds: number, w: SessionWindow): boolean {
  if (w.startMinute === w.endMinute) return true;
  const m = legacyMinuteOfDay(utcSeconds);
  return w.startMinute < w.endMinute
    ? m >= w.startMinute && m < w.endMinute
    : m >= w.startMinute || m < w.endMinute;
}

function legacyDayStartOf(utcSeconds: number): number {
  const p = utcSecondsToIstParts(utcSeconds);
  return istStringToUtcSeconds(`${p.year}-${legacyPad2(p.month)}-${legacyPad2(p.day)}`);
}

function legacySessionKey(utcSeconds: number, mode: MarketProfileSession, w?: SessionWindow): number {
  if (mode === 'composite') return 0;
  const p = utcSecondsToIstParts(utcSeconds);
  if (mode === 'month') return istStringToUtcSeconds(`${p.year}-${legacyPad2(p.month)}-01`);
  let dayStart = legacyDayStartOf(utcSeconds);
  if (w !== undefined && w.startMinute > w.endMinute && legacyMinuteOfDay(utcSeconds) < w.endMinute) {
    dayStart -= DAY;
  }
  if (mode === 'day') return dayStart;
  const backToMonday = ((utcSecondsToIstParts(dayStart).weekday + 6) % 7) * DAY;
  return dayStart - backToMonday;
}

/** The v1.2.0 partition as [firstBarTime, lastBarTime] pairs, in first-seen order. */
function legacyPartition(
  bars: readonly Bar[],
  mode: MarketProfileSession,
  w?: SessionWindow,
): [number, number][] {
  const groups = new Map<number, Bar[]>();
  const order: number[] = [];
  for (const b of bars) {
    if (w !== undefined && !legacyInWindow(b.time, w)) continue;
    const k = legacySessionKey(b.time, mode, w);
    let g = groups.get(k);
    if (g === undefined) { g = []; groups.set(k, g); order.push(k); }
    g.push(b);
  }
  return order.map((k) => {
    const g = groups.get(k) as Bar[];
    return [g[0].time, g[g.length - 1].time] as [number, number];
  });
}

const spans = (r: { sessions: { startTime: number; endTime: number }[] }): [number, number][] =>
  r.sessions.map((s) => [s.startTime, s.endTime]);

// ---------------------------------------------------------------------------

describe('Asia/Kolkata through Intl and the IST arithmetic', () => {
  it('resolves the same calendar parts, so the default really is unchanged', () => {
    // Everything below rests on this equality, so it is measured and not assumed.
    // 40-minute steps over a year land on every hour and every half hour in turn.
    const start = utc(2024, 1, 1);
    for (let t = start; t < start + 366 * DAY; t += 2400) {
      expect(utcSecondsToZonedParts(t, 'Asia/Kolkata')).toEqual(utcSecondsToIstParts(t));
    }
    // Including the second, which the parts sweep above never leaves at zero.
    expect(utcSecondsToZonedParts(start + 37, 'Asia/Kolkata')).toEqual(utcSecondsToIstParts(start + 37));
  });
});

describe('TRADING_HOURS written in each market own clock', () => {
  it('every preset that reads a clock carries the zone it is written in', () => {
    expect(TRADING_HOURS['india']).toMatchObject({ startMinute: 555, endMinute: 930, zone: 'Asia/Kolkata' });
    expect(TRADING_HOURS['us-regular']).toMatchObject({ startMinute: 570, endMinute: 960, zone: 'America/New_York' });
    expect(TRADING_HOURS['new-york'].zone).toBe('America/New_York');
    expect(TRADING_HOURS['london'].zone).toBe('Europe/London');
    expect(TRADING_HOURS['asia'].zone).toBe('Asia/Tokyo');
    // all-hours short-circuits before any clock is read, so it needs no zone.
    expect(TRADING_HOURS['all-hours'].zone).toBeUndefined();
  });

  it('selects exactly the v1.2.0 instants through a northern summer week', () => {
    // The legacy table was authored in DST terms: 1140/90 IST is 09:30-16:00 in
    // New York only while EDT is in force. A July week is inside both BST and
    // EDT, so every preset must still pick the same seconds it always did.
    for (const key of Object.keys(TRADING_HOURS)) {
      const now = TRADING_HOURS[key];
      const then = LEGACY_TRADING_HOURS[key];
      const differing: number[] = [];
      for (let t = utc(2024, 7, 8); t < utc(2024, 7, 15); t += 300) {
        if (inWindow(t, now) !== legacyInWindow(t, then)) differing.push(t);
      }
      expect({ key, differing }).toEqual({ key, differing: [] });
    }
  });

  it('keeps the DST-free presets identical in winter too', () => {
    for (const key of ['all-hours', 'india', 'asia']) {
      const now = TRADING_HOURS[key];
      const then = LEGACY_TRADING_HOURS[key];
      const differing: number[] = [];
      for (let t = utc(2024, 1, 8); t < utc(2024, 1, 15); t += 300) {
        if (inWindow(t, now) !== legacyInWindow(t, then)) differing.push(t);
      }
      expect({ key, differing }).toEqual({ key, differing: [] });
    }
  });

  it('opens us-regular at 09:30 New York in both DST phases', () => {
    const w = TRADING_HOURS['us-regular'];
    // July: 09:30 EDT is 13:30 UTC, which is what the legacy number encoded.
    expect(inWindow(utc(2024, 7, 16, 13, 29), w)).toBe(false);
    expect(inWindow(utc(2024, 7, 16, 13, 30), w)).toBe(true);
    expect(inWindow(utc(2024, 7, 16, 19, 59), w)).toBe(true);
    expect(inWindow(utc(2024, 7, 16, 20, 0), w)).toBe(false);
    // January: 09:30 EST is 14:30 UTC. The legacy table opened the US session an
    // hour early for the five winter months, which is the defect being fixed.
    expect(inWindow(utc(2024, 1, 16, 13, 30), w)).toBe(false);
    expect(legacyInWindow(utc(2024, 1, 16, 13, 30), LEGACY_TRADING_HOURS['us-regular'])).toBe(true);
    expect(inWindow(utc(2024, 1, 16, 14, 30), w)).toBe(true);
    expect(inWindow(utc(2024, 1, 16, 20, 59), w)).toBe(true);
    expect(inWindow(utc(2024, 1, 16, 21, 0), w)).toBe(false);
  });

  it('follows London through BST and GMT', () => {
    const w = TRADING_HOURS['london'];
    expect(inWindow(utc(2024, 7, 16, 6, 0), w)).toBe(true);   // 07:00 BST
    expect(inWindow(utc(2024, 7, 16, 5, 59), w)).toBe(false);
    expect(inWindow(utc(2024, 1, 16, 6, 0), w)).toBe(false);  // 06:00 GMT, before the open
    expect(inWindow(utc(2024, 1, 16, 7, 0), w)).toBe(true);
  });
});

describe('a preset is anchored to its market, not to the display', () => {
  // An Indian session that genuinely straddles midnight in New York, so a
  // display-zone bucketing bug cannot hide.
  const opens = [
    istStringToUtcSeconds('2024-01-15 09:15:00'),
    istStringToUtcSeconds('2024-01-16 09:15:00'),
  ];
  const bars = opens.flatMap((t) => [bar(t, 100, 104), bar(t + 2 * HOUR + 45 * 60, 102, 106), bar(t + 5 * HOUR + 45 * 60, 101, 105)]);

  it('really does straddle the New York day (guards the test itself)', () => {
    expect(zonedDayIndex(opens[0], 'America/New_York'))
      .not.toBe(zonedDayIndex(opens[0] + 5 * HOUR + 45 * 60, 'America/New_York'));
  });

  it('gives the same sessions, letters and value area whatever the display zone', () => {
    const opts = { tickSize: 1, session: 'day' as const, blockMinutes: 30, window: TRADING_HOURS['india'] };
    const home = computeMarketProfile(bars, opts);
    const abroad = computeMarketProfile(bars, { ...opts, timezone: 'America/New_York' });
    const tokyo = computeMarketProfile(bars, { ...opts, timezone: 'Asia/Tokyo' });

    expect(home.sessions).toHaveLength(2);
    expect(spans(abroad)).toEqual(spans(home));
    expect(spans(tokyo)).toEqual(spans(home));
    // Letters are anchored to 09:15 Kolkata in every one of them.
    const letters = (r: typeof home): string[][] => r.sessions.map((s) => s.periodDetail.map((p) => p.letter));
    expect(letters(abroad)).toEqual([['A', 'F', 'L'], ['A', 'F', 'L']]);
    expect(letters(abroad)).toEqual(letters(home));
    expect(abroad.sessions.map((s) => s.poc)).toEqual(home.sessions.map((s) => s.poc));
  });

  it('reads a window with no zone on the configured timezone', () => {
    // The same minute counts, unattached to a market: now they mean 09:15-15:30
    // in New York, and the Indian session is nowhere near them.
    const bare: SessionWindow = { startMinute: 9 * 60 + 15, endMinute: 15 * 60 + 30, name: 'Local' };
    const local = computeMarketProfile(bars, { tickSize: 1, window: bare });
    const newYork = computeMarketProfile(bars, { tickSize: 1, window: bare, timezone: 'America/New_York' });
    expect(local.sessions).toHaveLength(2);
    expect(newYork.sessions).toHaveLength(0);
  });

  it('anchors letters to the wall clock across a spring-forward day', () => {
    // 2024-03-10: New York loses an hour at 02:00, so local midnight plus 570
    // minutes is 10:30 and not the 09:30 open. Both bars would collapse into one
    // period if the anchor were computed that way.
    const bars2 = [bar(utc(2024, 3, 10, 13, 30), 100, 102), bar(utc(2024, 3, 10, 14, 0), 101, 103)];
    const s = computeMarketProfile(bars2, {
      tickSize: 1, blockMinutes: 30, window: TRADING_HOURS['us-regular'],
    }).sessions[0];
    expect(s.periodDetail.map((p) => p.letter)).toEqual(['A', 'B']);
  });
});

describe('bucketing resolves on the configured zone', () => {
  const evening = istStringToUtcSeconds('2024-01-15 23:00:00'); // 12:30 in New York
  const night = istStringToUtcSeconds('2024-01-16 01:00:00');   // 14:30 the same NY day
  const bars = [bar(evening, 100, 104), bar(night, 101, 105)];

  it('splits on the IST day by default and on the New York day when asked', () => {
    expect(computeMarketProfile(bars, { tickSize: 1, session: 'day' }).sessions).toHaveLength(2);
    expect(
      computeMarketProfile(bars, { tickSize: 1, session: 'day', timezone: 'America/New_York' }).sessions,
    ).toHaveLength(1);
  });

  it('resolves weeks on the configured zone', () => {
    // Sunday evening IST is still Sunday afternoon in New York, but the bar three
    // hours later has crossed into the Indian Monday and so into the next week.
    const sun = istStringToUtcSeconds('2024-01-14 23:00:00');
    const mon = istStringToUtcSeconds('2024-01-15 02:00:00');
    const week = [bar(sun, 100, 104), bar(mon, 101, 105)];
    expect(computeMarketProfile(week, { tickSize: 1, session: 'week' }).sessions).toHaveLength(2);
    expect(
      computeMarketProfile(week, { tickSize: 1, session: 'week', timezone: 'America/New_York' }).sessions,
    ).toHaveLength(1);
  });

  it('resolves months on the configured zone', () => {
    const jan = istStringToUtcSeconds('2024-01-31 20:00:00');
    const feb = istStringToUtcSeconds('2024-02-01 02:00:00'); // 15:30 on Jan 31 in New York
    const month = [bar(jan, 100, 104), bar(feb, 101, 105)];
    expect(computeMarketProfile(month, { tickSize: 1, session: 'month' }).sessions).toHaveLength(2);
    expect(
      computeMarketProfile(month, { tickSize: 1, session: 'month', timezone: 'America/New_York' }).sessions,
    ).toHaveLength(1);
  });

  it('does the same for the volume profile family', () => {
    const vp = (timezone?: string): number =>
      computeVolumeProfileSessions(bars, { tickSize: 1, session: 'day', timezone }).sessions.length;
    expect(vp()).toBe(2);
    expect(vp('Asia/Kolkata')).toBe(2);
    expect(vp('America/New_York')).toBe(1);
  });

  it('reports the zone it resolved to', () => {
    expect(computeMarketProfile(bars, { tickSize: 1 }).options.timezone).toBe('Asia/Kolkata');
    expect(computeMarketProfile(bars, { tickSize: 1, timezone: 'Europe/London' }).options.timezone).toBe('Europe/London');
    expect(computeVolumeProfileSessions(bars, { tickSize: 1 }).options.timezone).toBe('Asia/Kolkata');
  });

  it('rejects a zone the runtime does not know', () => {
    expect(() => computeMarketProfile(bars, { tickSize: 1, session: 'day', timezone: 'Mars/Olympus' })).toThrow(/time zone/);
  });
});

describe('overnight windows stay one session', () => {
  it('keeps an evening and the following morning together under the default', () => {
    const w: SessionWindow = { startMinute: 23 * 60, endMinute: 2 * 60, name: 'Overnight' };
    const bars = [
      bar(istStringToUtcSeconds('2024-01-15 23:30:00'), 100, 104),
      bar(istStringToUtcSeconds('2024-01-16 00:30:00'), 101, 105),
      bar(istStringToUtcSeconds('2024-01-16 01:30:00'), 102, 106),
      bar(istStringToUtcSeconds('2024-01-16 10:00:00'), 200, 204), // outside, dropped
      bar(istStringToUtcSeconds('2024-01-16 23:30:00'), 103, 107),
    ];
    const { sessions } = computeMarketProfile(bars, { tickSize: 1, blockMinutes: 30, window: w });
    expect(sessions).toHaveLength(2);
    expect(sessions[0].startTime).toBe(istStringToUtcSeconds('2024-01-15 23:30:00'));
    expect(sessions[0].endTime).toBe(istStringToUtcSeconds('2024-01-16 01:30:00'));
    // Anchored to the 23:00 open, so the three bars are periods 1, 3 and 5.
    expect(sessions[0].periodDetail.map((p) => p.letter)).toEqual(['B', 'D', 'F']);
    expect(sessions[0].high).toBe(106);
  });

  it('keeps one whatever clock the window is written on', () => {
    const w: SessionWindow = { startMinute: 20 * 60, endMinute: 2 * 60, zone: 'America/New_York', name: 'US Overnight' };
    const ny = (d: number, h: number, min: number): number =>
      zonedWallClockToUtcSeconds(2024, 1, d, h, min, 0, 'America/New_York');
    const bars = [bar(ny(15, 20, 30), 100, 104), bar(ny(15, 23, 30), 101, 105), bar(ny(16, 1, 30), 102, 106)];
    // Displayed on three different clocks, including the one it is written on.
    for (const timezone of ['Asia/Kolkata', 'America/New_York', 'Europe/London']) {
      const { sessions } = computeMarketProfile(bars, { tickSize: 1, blockMinutes: 30, window: w, timezone });
      expect({ timezone, count: sessions.length }).toEqual({ timezone, count: 1 });
      // Anchored to the 20:00 New York open: 30, 210 and 330 minutes past it.
      expect(sessions[0].periodDetail.map((p) => p.letter)).toEqual(['B', 'H', 'L']);
    }
  });
});

describe('the default partition is the v1.2.0 partition', () => {
  const winter = series(istStringToUtcSeconds('2024-01-10 00:00:00'), 26); // spans a month end
  const summer = series(istStringToUtcSeconds('2024-07-10 00:00:00'), 26);
  const modes: MarketProfileSession[] = ['day', 'week', 'month', 'composite'];

  it('matches bar for bar in every session mode, with no window', () => {
    for (const bars of [winter, summer]) {
      for (const session of modes) {
        expect(spans(computeMarketProfile(bars, { tickSize: 1, session }))).toEqual(legacyPartition(bars, session));
      }
    }
  });

  it('matches through a windowed profile', () => {
    for (const bars of [winter, summer]) {
      for (const session of modes) {
        const got = computeMarketProfile(bars, { tickSize: 1, session, window: TRADING_HOURS['india'] });
        expect(spans(got)).toEqual(legacyPartition(bars, session, LEGACY_TRADING_HOURS['india']));
      }
    }
    // The overnight presets too, in the summer where the legacy numbers held.
    for (const key of ['new-york', 'us-regular', 'london', 'asia', 'all-hours']) {
      const got = computeMarketProfile(summer, { tickSize: 1, session: 'day', window: TRADING_HOURS[key] });
      expect({ key, spans: spans(got) })
        .toEqual({ key, spans: legacyPartition(summer, 'day', LEGACY_TRADING_HOURS[key]) });
    }
  });

  it('matches for the volume profile family', () => {
    const vModes: VolumeProfileSession[] = ['day', 'week', 'month', 'composite'];
    for (const bars of [winter, summer]) {
      for (const session of vModes) {
        expect(spans(computeVolumeProfileSessions(bars, { tickSize: 1, session })))
          .toEqual(legacyPartition(bars, session));
      }
    }
  });
});
