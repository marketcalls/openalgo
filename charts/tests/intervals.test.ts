import { describe, it, expect, afterEach } from 'vitest';
import {
  registerInterval,
  unregisterInterval,
  registeredIntervals,
  resolveInterval,
  tryResolveInterval,
  isKnownInterval,
  isTimeBucketed,
  bucketStartOf,
  nextBucketStart,
  UnknownIntervalError,
  intervalParts,
  isSecondsInterval,
  isIntradayInterval,
  isDailyInterval,
  isTickInterval,
} from '../src/feed/intervals';
import { OpenAlgoLiveDataFeed, intervalToSeconds } from '../src/feed/openalgo-live';
import { TickBarAggregator } from '../src/feed/tick-aggregator';
import type { Bar } from '../src/model/bar';

const DAY = 86400;

// Registrations are process-wide, so every test that adds one takes it away.
const disposers: (() => void)[] = [];
function register(code: string, bucketing: Parameters<typeof registerInterval>[0]['bucketing']): void {
  disposers.push(registerInterval({ code, bucketing }));
}
afterEach(() => {
  while (disposers.length > 0) (disposers.pop() as () => void)();
});

// ---------------------------------------------------------------------------
// The regression that matters: a caller who registers nothing sees v1.3.0.
// ---------------------------------------------------------------------------

/** intervalToSeconds exactly as it stood before the registry, as the oracle. */
function legacyIntervalToSeconds(interval: string): number | null {
  const m = /^(\d*)\s*([smhdw])$/i.exec(interval.trim());
  if (m === null) return null; // the old silent 60 fallback, kept separable
  const n = m[1] === '' ? 1 : Number(m[1]);
  const unit = m[2].toLowerCase();
  const mult = unit === 's' ? 1 : unit === 'm' ? 60 : unit === 'h' ? 3600 : unit === 'd' ? 86400 : 604800;
  return n * mult;
}

/**
 * Upper-case `M` is deliberately absent. The old regex folded case, so it read
 * `M` as minutes; every terminal that uses these tokens reads it as a month, and
 * anything gating on "has the next bar closed" then believed a month closed
 * every sixty seconds. It now resolves to nothing, so a host that wants months
 * registers a calendar interval on purpose. See `builtinBucketing`.
 */
function builtinCodes(): string[] {
  const out: string[] = [];
  for (const unit of ['s', 'm', 'h', 'd', 'w', 'S', 'H', 'D', 'W']) {
    for (const count of ['', '0', '1', '2', '3', '5', '10', '15', '30', '45', '60', '120', '240']) {
      out.push(`${count}${unit}`, `${count} ${unit}`, ` ${count}${unit} `);
    }
  }
  return out;
}

describe('built-in interval tokens are untouched by the registry', () => {
  it('resolves every token the old regex accepted to the same seconds', () => {
    const codes = builtinCodes();
    expect(codes.length).toBeGreaterThan(300);
    for (const code of codes) {
      const expected = legacyIntervalToSeconds(code) as number;
      expect(expected).not.toBeNull();
      expect(intervalToSeconds(code)).toBe(expected);
      const { bucketing } = resolveInterval(code);
      expect(bucketing).toEqual({ mode: 'interval', seconds: expected });
    }
  });

  it('will not read upper-case M as minutes', () => {
    // The one intentional break from the old regex. Minutes and months are
    // different by case everywhere else, and guessing minutes is the dangerous
    // direction: it under-states a bar's life by four orders of magnitude.
    expect(tryResolveInterval('M')).toBeNull();
    expect(tryResolveInterval('1M')).toBeNull();
    expect(tryResolveInterval('12M')).toBeNull();
    expect(() => resolveInterval('M')).toThrow(UnknownIntervalError);
    // Lower case is untouched.
    expect(resolveInterval('m').bucketing).toEqual({ mode: 'interval', seconds: 60 });
    expect(resolveInterval('15m').bucketing).toEqual({ mode: 'interval', seconds: 900 });
  });

  it('keeps the documented tokens on their documented values', () => {
    expect(intervalToSeconds('D')).toBe(86400);
    expect(intervalToSeconds('W')).toBe(604800);
    expect(intervalToSeconds('1D')).toBe(86400);
    expect(intervalToSeconds('1W')).toBe(604800);
    expect(intervalToSeconds('1s')).toBe(1);
    expect(intervalToSeconds('1m')).toBe(60);
    expect(intervalToSeconds('5m')).toBe(300);
    expect(intervalToSeconds('1h')).toBe(3600);
    expect(intervalToSeconds('4h')).toBe(14400);
  });

  it('buckets built-ins from the epoch, as the candle builder always did', () => {
    for (const code of builtinCodes()) {
      const seconds = legacyIntervalToSeconds(code) as number;
      if (seconds <= 0) continue; // '0m' was and stays degenerate
      const t = 1_700_000_123;
      const { bucketing } = resolveInterval(code);
      expect(bucketStartOf(bucketing, t)).toBe(Math.floor(t / seconds) * seconds);
      expect(nextBucketStart(bucketing, t)).toBe(Math.floor(t / seconds) * seconds + seconds);
    }
  });

  it('registers nothing of its own', () => {
    expect(registeredIntervals()).toHaveLength(0);
  });

  it('leaves built-ins alone when unrelated codes are registered', () => {
    register('T500', { mode: 'ticks', count: 500 });
    register('MN', { mode: 'calendar', unit: 'month' });
    expect(intervalToSeconds('5m')).toBe(300);
    expect(intervalToSeconds('D')).toBe(86400);
    expect(registeredIntervals().map((d) => d.code)).toEqual(['T500', 'MN']);
  });
});

// ---------------------------------------------------------------------------
// Registered fixed timeframes
// ---------------------------------------------------------------------------

describe('registered fixed intervals', () => {
  it('resolves a code the built-in grammar cannot express', () => {
    expect(isKnownInterval('2h30')).toBe(false);
    register('2h30', { mode: 'interval', seconds: 9000 });
    expect(isKnownInterval('2h30')).toBe(true);
    expect(intervalToSeconds('2h30')).toBe(9000);
    const { bucketing } = resolveInterval('2h30');
    expect(bucketStartOf(bucketing, 9001)).toBe(9000);
  });

  it('honours a session anchor so bars start at the open, not the epoch', () => {
    // 09:15 IST on 2024-01-01 in UTC seconds.
    const open = Date.UTC(2024, 0, 1, 3, 45, 0) / 1000;
    register('45m', { mode: 'interval', seconds: 2700, anchorSec: open });
    const { bucketing } = resolveInterval('45m');
    expect(bucketStartOf(bucketing, open + 10)).toBe(open);
    expect(bucketStartOf(bucketing, open + 2700)).toBe(open + 2700);
    expect(nextBucketStart(bucketing, open + 10)).toBe(open + 2700);
  });

  it('shadows a built-in only while it is registered', () => {
    const off = registerInterval({ code: 'W', bucketing: { mode: 'calendar', unit: 'month', timezone: 'UTC' } });
    expect(resolveInterval('w').bucketing.mode).toBe('calendar');
    off();
    expect(intervalToSeconds('W')).toBe(604800);
  });

  it('matches codes case-insensitively, as the built-in tokens always have', () => {
    register('T500', { mode: 'ticks', count: 500 });
    expect(resolveInterval('t500').bucketing).toEqual({ mode: 'ticks', count: 500 });
  });

  it('rejects a nonsense registration instead of storing it', () => {
    expect(() => registerInterval({ code: '', bucketing: { mode: 'interval', seconds: 60 } })).toThrow();
    expect(() => registerInterval({ code: 'X', bucketing: { mode: 'interval', seconds: 0 } })).toThrow();
    expect(() => registerInterval({ code: 'X', bucketing: { mode: 'ticks', count: 0 } })).toThrow();
    expect(() => registerInterval({ code: 'X', bucketing: { mode: 'volume', perBar: 0 } })).toThrow();
    expect(registeredIntervals()).toHaveLength(0);
  });

  it('unregisters by code as well as by disposer', () => {
    registerInterval({ code: 'ZZ', bucketing: { mode: 'ticks', count: 7 } });
    expect(unregisterInterval('zz')).toBe(true);
    expect(unregisterInterval('zz')).toBe(false);
    expect(isKnownInterval('ZZ')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Calendar periods
// ---------------------------------------------------------------------------

const utc = (y: number, m: number, d = 1, h = 0): number => Date.UTC(y, m - 1, d, h) / 1000;

describe('calendar bucketing', () => {
  it('runs a month bucket from the first to the first, whatever the month is worth', () => {
    register('MN', { mode: 'calendar', unit: 'month', timezone: 'UTC' });
    const { bucketing } = resolveInterval('MN');
    const cases: { inside: number; start: number; next: number; days: number }[] = [
      { inside: utc(2023, 2, 14, 9), start: utc(2023, 2), next: utc(2023, 3), days: 28 }, // short
      { inside: utc(2024, 2, 29, 23), start: utc(2024, 2), next: utc(2024, 3), days: 29 }, // leap
      { inside: utc(2023, 4, 30, 23), start: utc(2023, 4), next: utc(2023, 5), days: 30 },
      { inside: utc(2023, 3, 31, 23), start: utc(2023, 3), next: utc(2023, 4), days: 31 },
    ];
    for (const c of cases) {
      expect(bucketStartOf(bucketing, c.inside)).toBe(c.start);
      expect(nextBucketStart(bucketing, c.inside)).toBe(c.next);
      expect(c.next - c.start).toBe(c.days * DAY);
      // The first instant of the month belongs to it; the last does too.
      expect(bucketStartOf(bucketing, c.start)).toBe(c.start);
      expect(bucketStartOf(bucketing, c.next - 1)).toBe(c.start);
      expect(bucketStartOf(bucketing, c.next)).toBe(c.next);
    }
  });

  it('is not 30 days: consecutive month buckets have different lengths', () => {
    register('MN', { mode: 'calendar', unit: 'month', timezone: 'UTC' });
    const { bucketing } = resolveInterval('MN');
    const lengths = [1, 2, 3, 4].map((m) => {
      const t = utc(2023, m, 10);
      return (nextBucketStart(bucketing, t) as number) - bucketStartOf(bucketing, t);
    });
    expect(lengths).toEqual([31 * DAY, 28 * DAY, 31 * DAY, 30 * DAY]);
  });

  it('anchors quarters on January, April, July and October', () => {
    register('3M', { mode: 'calendar', unit: 'quarter', timezone: 'UTC' });
    const { bucketing } = resolveInterval('3M');
    expect(bucketStartOf(bucketing, utc(2023, 11, 17))).toBe(utc(2023, 10));
    expect(nextBucketStart(bucketing, utc(2023, 11, 17))).toBe(utc(2024, 1));
    expect(bucketStartOf(bucketing, utc(2024, 1, 1))).toBe(utc(2024, 1));
    expect(bucketStartOf(bucketing, utc(2024, 6, 30))).toBe(utc(2024, 4));
  });

  it('runs a year bucket over 366 days in a leap year', () => {
    register('12M', { mode: 'calendar', unit: 'year', timezone: 'UTC' });
    const { bucketing } = resolveInterval('12M');
    const t = utc(2024, 8, 21);
    expect(bucketStartOf(bucketing, t)).toBe(utc(2024, 1));
    expect(nextBucketStart(bucketing, t)).toBe(utc(2025, 1));
    expect((nextBucketStart(bucketing, t) as number) - bucketStartOf(bucketing, t)).toBe(366 * DAY);
  });

  it('groups units when count > 1', () => {
    register('6M', { mode: 'calendar', unit: 'month', count: 6, timezone: 'UTC' });
    const { bucketing } = resolveInterval('6M');
    expect(bucketStartOf(bucketing, utc(2024, 8, 21))).toBe(utc(2024, 7));
    expect(nextBucketStart(bucketing, utc(2024, 8, 21))).toBe(utc(2025, 1));
    expect(bucketStartOf(bucketing, utc(2024, 6, 30))).toBe(utc(2024, 1));
  });

  it('resolves the boundary in the requested zone, not in UTC', () => {
    register('MN', { mode: 'calendar', unit: 'month' });
    const { bucketing } = resolveInterval('MN');
    // 2024-03-01 02:00 UTC is still 2024-02-29 21:00 in New York.
    const t = utc(2024, 3, 1, 2);
    expect(bucketStartOf(bucketing, t, 'UTC')).toBe(utc(2024, 3));
    expect(bucketStartOf(bucketing, t, 'America/New_York')).toBe(utc(2024, 2, 1, 5)); // 00:00 EST
    expect(bucketStartOf(bucketing, t, 'Asia/Kolkata')).toBe(utc(2024, 3, 1) - 19800); // 00:00 IST
    // ... and the leap February is still 29 days long there.
    expect((nextBucketStart(bucketing, t, 'America/New_York') as number)
      - bucketStartOf(bucketing, t, 'America/New_York')).toBe(29 * DAY);
  });

  it('follows the zone pinned on the entry over the zone the caller asks in', () => {
    register('MN-NY', { mode: 'calendar', unit: 'month', timezone: 'America/New_York' });
    const { bucketing } = resolveInterval('MN-NY');
    const t = utc(2024, 3, 1, 2);
    expect(bucketStartOf(bucketing, t, 'UTC')).toBe(utc(2024, 2, 1, 5));
  });

  it('is an hour short across a spring forward, because the month really is', () => {
    register('MN', { mode: 'calendar', unit: 'month', timezone: 'America/New_York' });
    const { bucketing } = resolveInterval('MN');
    const t = utc(2024, 3, 15);
    const span = (nextBucketStart(bucketing, t) as number) - bucketStartOf(bucketing, t);
    expect(span).toBe(31 * DAY - 3600); // March 2024 in New York is 743 hours
  });

  it('defaults to IST when neither the entry nor the caller names a zone', () => {
    register('MN', { mode: 'calendar', unit: 'month' });
    const { bucketing } = resolveInterval('MN');
    expect(bucketStartOf(bucketing, utc(2024, 5, 20))).toBe(utc(2024, 5, 1) - 19800);
  });
});

// ---------------------------------------------------------------------------
// Count-driven bars
// ---------------------------------------------------------------------------

describe('tick and volume bars', () => {
  it('closes a tick bar after N trades', () => {
    register('T3', { mode: 'ticks', count: 3 });
    const { bucketing } = resolveInterval('T3');
    expect(isTimeBucketed(bucketing)).toBe(false);
    expect(nextBucketStart(bucketing, 1000)).toBeNull();

    const agg = new TickBarAggregator(bucketing);
    const opens: number[] = [];
    const prices = [10, 11, 12, 13, 14, 15, 16];
    prices.forEach((price, i) => {
      const u = agg.onTick({ time: 1000 + i, price, qty: 1 });
      if (u.isNew) opens.push(i);
    });
    // Bars of exactly three ticks: 0-2, 3-5, then 6 opens the third.
    expect(opens).toEqual([0, 3, 6]);
    const last = agg.current() as Bar;
    expect(last.time).toBe(1006); // count-driven bars open at their first tick
    expect(last.open).toBe(16);
  });

  it('closes a volume bar after N traded quantity', () => {
    register('V100', { mode: 'volume', perBar: 100 });
    const { bucketing } = resolveInterval('V100');
    const agg = new TickBarAggregator(bucketing);
    agg.onTick({ time: 1, price: 10, qty: 60 });
    expect(agg.onTick({ time: 2, price: 11, qty: 60 }).isNew).toBe(false); // 120 fills this bar
    expect(agg.onTick({ time: 3, price: 12, qty: 10 }).isNew).toBe(true);
    expect((agg.current() as Bar).volume).toBe(10);
  });

  it('will not resume a historical bar for a count-driven timeframe', () => {
    const agg = new TickBarAggregator({ mode: 'ticks', count: 3 });
    agg.seed({ time: 500, open: 1, high: 1, low: 1, close: 1, volume: 9 });
    expect(agg.current()).toBeNull();
  });

  it('resumes a historical bar for a calendar timeframe', () => {
    const agg = new TickBarAggregator({ mode: 'calendar', unit: 'month', timezone: 'UTC' });
    agg.seed({ time: utc(2024, 5), open: 1, high: 4, low: 1, close: 3, volume: 9 });
    const u = agg.onTick({ time: utc(2024, 5, 20), price: 5, qty: 1 });
    expect(u.isNew).toBe(false);
    expect(u.bar.high).toBe(5);
    expect(u.bar.open).toBe(1);
  });
});

describe('TickBarAggregator on a calendar timeframe', () => {
  it('opens a new bar at each month boundary in the aggregator zone', () => {
    const agg = new TickBarAggregator({ mode: 'calendar', unit: 'month' }, { timezone: 'UTC' });
    const times = [utc(2024, 1, 5), utc(2024, 1, 31, 23), utc(2024, 2, 1), utc(2024, 2, 29, 12), utc(2024, 3, 1)];
    const bars: Bar[] = [];
    for (const t of times) {
      const u = agg.onTick({ time: t, price: 100, qty: 1 });
      if (u.isNew) bars.push(u.bar);
    }
    expect(bars.map((b) => b.time)).toEqual([utc(2024, 1), utc(2024, 2), utc(2024, 3)]);
  });

  it('behaves identically to the old aggregator on an interval timeframe', () => {
    const agg = new TickBarAggregator({ mode: 'interval', seconds: 60 });
    const a = agg.onTick({ time: 1000, price: 10, qty: 1 });
    const b = agg.onTick({ time: 1010, price: 12, qty: 2 }); // same 960..1020 bucket
    const c = agg.onTick({ time: 1090, price: 9, qty: 3 });
    expect(a.bar.time).toBe(960);
    expect(b.isNew).toBe(false);
    expect(b.bar.high).toBe(12);
    expect(b.bar.volume).toBe(3);
    expect(c.isNew).toBe(true);
    expect(c.bar.time).toBe(1080);
  });
});

// ---------------------------------------------------------------------------
// Unknown codes
// ---------------------------------------------------------------------------

describe('an unrecognised interval code', () => {
  it('throws instead of quietly becoming one minute', () => {
    for (const code of ['bogus', '', '   ', '5x', '1mm', 'MN', '3d4h']) {
      expect(() => intervalToSeconds(code)).toThrow(UnknownIntervalError);
      expect(() => resolveInterval(code)).toThrow(UnknownIntervalError);
      expect(tryResolveInterval(code)).toBeNull();
      expect(isKnownInterval(code)).toBe(false);
    }
  });

  it('names the offending code, so the message identifies the typo', () => {
    let caught: unknown = null;
    try {
      resolveInterval('15mn');
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(UnknownIntervalError);
    expect((caught as UnknownIntervalError).code).toBe('15mn');
    expect((caught as Error).message).toContain('15mn');
  });

  it('refuses to state seconds for an interval that has none', () => {
    register('MN', { mode: 'calendar', unit: 'month' });
    register('T500', { mode: 'ticks', count: 500 });
    expect(() => intervalToSeconds('MN')).toThrow(/no fixed length/);
    expect(() => intervalToSeconds('T500')).toThrow(/no fixed length/);
    // ... but resolving it works, because bucketing is what callers actually need.
    expect(resolveInterval('MN').bucketing.mode).toBe('calendar');
  });
});

// ---------------------------------------------------------------------------
// The live feed consumes the registry
// ---------------------------------------------------------------------------

interface FakeSocket {
  sent: string[];
  readyState: number;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((e: { data: string }) => void) | null;
  send(d: string): void;
  close(): void;
}

function fakeSocket(): FakeSocket {
  const s: FakeSocket = {
    sent: [], readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send(d: string) { s.sent.push(d); },
    close() { /* nothing to tear down in memory */ },
  };
  return s;
}

function ltpFrame(fields: Record<string, unknown>): { data: string } {
  return { data: JSON.stringify({ data: fields }) };
}

function makeFeed(extra: { volumeMode?: 'ltq-sum' | 'day-delta'; timezone?: string } = {}): {
  feed: OpenAlgoLiveDataFeed;
  sock: () => FakeSocket;
} {
  let sock: FakeSocket | undefined;
  const feed = new OpenAlgoLiveDataFeed({
    apiKey: 'k', baseUrl: '', wsUrl: 'ws://test',
    volumeMode: extra.volumeMode ?? 'ltq-sum',
    timezone: extra.timezone,
    socketFactory: () => (sock = fakeSocket()) as never,
  });
  return { feed, sock: () => sock as FakeSocket };
}

describe('OpenAlgoLiveDataFeed with registered intervals', () => {
  it('builds live monthly bars in the configured zone', () => {
    register('MN', { mode: 'calendar', unit: 'month' });
    const { feed, sock } = makeFeed({ timezone: 'America/New_York' });
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: 'MN', from: 0 }, (b) => bars.push(b));
    const s = sock();
    // 2024-03-01 02:00 UTC is 2024-02-29 21:00 in New York: still February's bar.
    s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, ltq: 5, timestamp: utc(2024, 3, 1, 2) }));
    s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 101, ltq: 5, timestamp: utc(2024, 3, 1, 6) }));
    expect(bars.map((b) => b.time)).toEqual([utc(2024, 2, 1, 5), utc(2024, 3, 1, 5)]);
    expect(bars[0].volume).toBe(5);
  });

  it('builds live tick bars that close on count', () => {
    register('T2', { mode: 'ticks', count: 2 });
    const { feed, sock } = makeFeed();
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: 'T2', from: 0 }, (b) => bars.push(b));
    const s = sock();
    for (let i = 0; i < 5; i++) {
      s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100 + i, ltq: 1, timestamp: 1700000000 + i }));
    }
    expect(bars).toHaveLength(5);
    expect(bars.map((b) => b.time)).toEqual([1700000000, 1700000000, 1700000002, 1700000002, 1700000004]);
  });

  it('diffs cumulative day volume for a registered interval too', () => {
    register('T9', { mode: 'ticks', count: 9 });
    const { feed, sock } = makeFeed({ volumeMode: 'day-delta' });
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: 'T9', from: 0 }, (b) => bars.push(b));
    const s = sock();
    s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, volume: 1000, timestamp: 1700000000 }));
    s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 102, volume: 1500, timestamp: 1700000060 }));
    expect(bars[bars.length - 1].volume).toBe(500); // 1500 - 1000, not the raw cumulative
  });

  it('still builds fixed-interval bars through the candle builder', () => {
    const { feed, sock } = makeFeed();
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1h', from: 0 }, (b) => bars.push(b));
    sock().onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 101, ltq: 2, timestamp: 1700000000 }));
    expect(bars).toHaveLength(1);
    expect(bars[0].time).toBe(Math.floor(1700000000 / 3600) * 3600);
  });

  it('rejects a typo at subscribe time rather than drawing minute bars', () => {
    const { feed } = makeFeed();
    expect(() => feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '15mn', from: 0 }, () => undefined))
      .toThrow(UnknownIntervalError);
  });
});

// ---------------------------------------------------------------------------
// Introspection: what an indicator can ask about the interval it is running on
// ---------------------------------------------------------------------------

describe('interval introspection', () => {
  it('splits a built-in token into a count and a unit', () => {
    expect(intervalParts('15s')).toEqual({ multiplier: 15, unit: 's' });
    expect(intervalParts('1m')).toEqual({ multiplier: 1, unit: 'm' });
    expect(intervalParts('15m')).toEqual({ multiplier: 15, unit: 'm' });
    expect(intervalParts('1h')).toEqual({ multiplier: 1, unit: 'h' });
    expect(intervalParts('D')).toEqual({ multiplier: 1, unit: 'D' });
    expect(intervalParts(' W ')).toEqual({ multiplier: 1, unit: 'W' });
  });

  it('answers off the bucket rather than off the spelling', () => {
    // Two codes for the same bar answer the same, and the coarsest unit that
    // divides the length wins, so 90 seconds stays seconds rather than becoming
    // one and a half minutes.
    expect(intervalParts('120m')).toEqual({ multiplier: 2, unit: 'h' });
    expect(intervalParts('2h')).toEqual(intervalParts('120m'));
    expect(intervalParts('1440m')).toEqual({ multiplier: 1, unit: 'D' });
    expect(intervalParts('90s')).toEqual({ multiplier: 90, unit: 's' });
  });

  it('reads a registered code the built-in grammar never parsed', () => {
    register('Y', { mode: 'calendar', unit: 'year' });
    register('Q', { mode: 'calendar', unit: 'quarter' });
    register('T500', { mode: 'ticks', count: 500 });
    register('V1000', { mode: 'volume', perBar: 1000 });
    // Calendar periods count months, so a quarter is 3 and a year is 12.
    expect(intervalParts('Y')).toEqual({ multiplier: 12, unit: 'M' });
    expect(intervalParts('Q')).toEqual({ multiplier: 3, unit: 'M' });
    expect(intervalParts('T500')).toEqual({ multiplier: 500, unit: 'tick' });
    // Volume has neither a clock length nor a trade count of its own.
    expect(intervalParts('V1000')).toEqual({ multiplier: 1000, unit: 'other' });
  });

  it('answers null for a code nothing resolves', () => {
    // `M` included: a month is never guessed, so it has no parts either.
    for (const code of ['M', 'zz', '', '15mn']) expect(intervalParts(code)).toBeNull();
  });

  it('flags the intervals whose labels need second precision', () => {
    for (const code of ['1s', '15s', '90s']) expect(isSecondsInterval(code)).toBe(true);
    for (const code of ['1m', '5m', 'D', 'W', 'zz']) expect(isSecondsInterval(code)).toBe(false);
  });

  it('flags the fixed-length bars shorter than a day', () => {
    for (const code of ['1s', '1m', '15m', '1h', '23h']) expect(isIntradayInterval(code)).toBe(true);
    for (const code of ['D', '24h', 'W']) expect(isIntradayInterval(code)).toBe(false);
    // Neither a calendar period nor a count-driven bar has a clock length to
    // compare, so both answer false rather than guessing which side they fall.
    register('MN', { mode: 'calendar', unit: 'month' });
    register('T500', { mode: 'ticks', count: 500 });
    expect(isIntradayInterval('MN')).toBe(false);
    expect(isIntradayInterval('T500')).toBe(false);
  });

  it('flags a bar exactly one day long, however it is spelled', () => {
    for (const code of ['D', '1d', '24h', '1440m']) expect(isDailyInterval(code)).toBe(true);
    // Deliberately not "daily or coarser": weekly and monthly answer false, so
    // a caller can branch on the three cases independently.
    for (const code of ['12h', 'W', 'M']) expect(isDailyInterval(code)).toBe(false);
  });

  it('flags a bar that closes on a trade count, and not one that closes on quantity', () => {
    register('T500', { mode: 'ticks', count: 500 });
    register('V1000', { mode: 'volume', perBar: 1000 });
    expect(isTickInterval('T500')).toBe(true);
    expect(isTickInterval('V1000')).toBe(false);
    expect(isTickInterval('1m')).toBe(false);
  });

  it('leaves a registered code answering for the code it shadows', () => {
    // A host whose W is a calendar week, not 604800 seconds from the epoch.
    register('W', { mode: 'calendar', unit: 'month', count: 3 });
    expect(intervalParts('W')).toEqual({ multiplier: 3, unit: 'M' });
    expect(isIntradayInterval('W')).toBe(false);
  });
});
