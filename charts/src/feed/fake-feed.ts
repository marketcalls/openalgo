import type { Bar } from '../model/bar';
import type { BarsRequest, BarSubscriptionOptions, DataFeed, UnsubscribeFn } from './types';
import { dataVariantError, unsupportedDataVariant } from './data-variant';
import { repeat } from '../helpers/timers';

/** Schedules a repeating callback and returns an unsubscribe. Inject in tests. */
export type FeedScheduler = (cb: () => void, intervalMs: number) => UnsubscribeFn;

/**
 * The feed has one series per instrument and declares no variants, so any
 * other variant would be that series under the wrong label. It is refused.
 */
function refuseVariant(req: BarsRequest): void {
  const unsupported = unsupportedDataVariant(undefined, req.variant);
  if (unsupported) throw dataVariantError(unsupported, req.variant);
}

/**
 * Deterministic, in-memory data feed for tests and demos. No network.
 * Generates a reproducible synthetic OHLC walk from a fixed seed so that
 * pixel-diff and unit tests are stable across runs (no Math.random / Date.now).
 * It serves only its default series: a request naming another data variant is
 * refused with a `DataVariantUnsupportedError`.
 */
export class FakeDataFeed implements DataFeed {
  private readonly intervalSec: number;
  private readonly _schedule: FeedScheduler;

  constructor(intervalSec = 60, scheduler: FeedScheduler = repeat) {
    this.intervalSec = intervalSec;
    this._schedule = scheduler;
  }

  async getBars(req: BarsRequest): Promise<Bar[]> {
    refuseVariant(req);
    const count = 500;
    const start = req.from ?? 1_700_000_000;
    return generateBars(start, count, this.intervalSec);
  }

  /**
   * Emit deterministic synthetic bars on the scheduler (default: a 1s
   * setInterval). This actually streams, so feature detection
   * (`if (feed.subscribeBars)`) is honest. Pass a manual scheduler to drive it
   * by hand in tests, and `opts.tickMs` to change the cadence.
   */
  subscribeBars(req: BarsRequest, onBar: (bar: Bar) => void, opts?: BarSubscriptionOptions & { tickMs?: number }): UnsubscribeFn {
    refuseVariant(req);
    let t = opts?.seedFrom?.time ?? req.from ?? 1_700_000_000;
    let prev = opts?.seedFrom?.close ?? 100;
    let seed = 0x1234567 >>> 0;
    const next = (): number => {
      seed ^= seed << 13; seed >>>= 0;
      seed ^= seed >> 17;
      seed ^= seed << 5; seed >>>= 0;
      return seed / 0xffffffff;
    };
    return this._schedule(() => {
      t += this.intervalSec;
      const open = prev;
      const close = Math.max(1, open + (next() - 0.5) * 2);
      const high = Math.max(open, close) + next();
      const low = Math.max(0.01, Math.min(open, close) - next());
      onBar({ time: t, open, high, low, close, volume: Math.round(1000 + next() * 9000) });
      prev = close;
    }, opts?.tickMs ?? 1000);
  }
}

/** Pure, seeded synthetic bar generator (deterministic: no global randomness). */
export function generateBars(startTime: number, count: number, intervalSec: number): Bar[] {
  const bars: Bar[] = [];
  let price = 100;
  let seed = 0x9e3779b9 >>> 0;
  const next = (): number => {
    // xorshift32: deterministic pseudo-random in [0, 1)
    seed ^= seed << 13; seed >>>= 0;
    seed ^= seed >> 17;
    seed ^= seed << 5; seed >>>= 0;
    return seed / 0xffffffff;
  };
  for (let i = 0; i < count; i++) {
    const drift = (next() - 0.5) * 2;
    const open = price;
    const close = Math.max(1, open + drift);
    const high = Math.max(open, close) + next();
    const low = Math.min(open, close) - next();
    bars.push({
      time: startTime + i * intervalSec,
      open,
      high,
      low,
      close,
      volume: Math.round(1000 + next() * 9000),
    });
    price = close;
  }
  return bars;
}
