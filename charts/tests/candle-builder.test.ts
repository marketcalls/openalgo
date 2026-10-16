import { describe, it, expect } from 'vitest';
import { CandleBuilder } from '../src/feed/candle-builder';

describe('CandleBuilder bucketing', () => {
  it('opens a new bar at each interval boundary and updates within', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' });
    const a = cb.onTick({ time: 0, price: 10, ltq: 5 })!; // bucket 0
    expect(a.isNew).toBe(true);
    expect(a.bar).toMatchObject({ time: 0, open: 10, high: 10, low: 10, close: 10, volume: 5 });

    const b = cb.onTick({ time: 30, price: 12, ltq: 3 })!; // still bucket 0
    expect(b.isNew).toBe(false);
    expect(b.bar).toMatchObject({ open: 10, high: 12, low: 10, close: 12, volume: 8 });

    const c = cb.onTick({ time: 60, price: 9, ltq: 2 })!; // bucket 60: new bar
    expect(c.isNew).toBe(true);
    expect(c.bar).toMatchObject({ time: 60, open: 9, high: 9, low: 9, close: 9, volume: 2 });
  });

  it('aligns buckets to a session anchor (e.g. 09:15 open)', () => {
    const anchor = 555; // arbitrary session-open second
    const cb = new CandleBuilder({ intervalSec: 300, sessionAnchorSec: anchor });
    expect(cb.bucketStart(anchor)).toBe(anchor);
    expect(cb.bucketStart(anchor + 299)).toBe(anchor);
    expect(cb.bucketStart(anchor + 300)).toBe(anchor + 300);
  });
});

describe('CandleBuilder volume modes', () => {
  it('ltq-sum accumulates last-traded quantity', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' });
    cb.onTick({ time: 0, price: 1, ltq: 10 });
    const u = cb.onTick({ time: 30, price: 1, ltq: 15 })!;
    expect(u.bar.volume).toBe(25);
  });

  it('day-delta diffs cumulative day volume (not the raw cumulative)', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'day-delta' });
    cb.onTick({ time: 0, price: 1, cumDayVolume: 1000 }); // first bar
    const same = cb.onTick({ time: 30, price: 1, cumDayVolume: 1250 })!;
    expect(same.bar.volume).toBe(250); // 1250 - 1000
    const next = cb.onTick({ time: 60, price: 1, cumDayVolume: 1400 })!;
    expect(next.isNew).toBe(true);
    expect(next.bar.volume).toBe(150); // 1400 - 1250 (new bar starts from prior cum)
  });

  it('day-delta handles the daily cumulative reset gracefully', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'day-delta' });
    cb.onTick({ time: 0, price: 1, cumDayVolume: 5000 });
    const afterReset = cb.onTick({ time: 60, price: 1, cumDayVolume: 80 })!; // new day, cum reset
    expect(afterReset.bar.volume).toBe(80); // not negative
  });
});

describe('CandleBuilder late ticks & seam', () => {
  it('keeps seeded volume when the first cumulative quote has no historical baseline', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'day-delta' });
    cb.seed({ time: 600, open: 10, high: 12, low: 9, close: 11, volume: 100 });
    expect(cb.onTick({ time: 630, price: 11.5, cumDayVolume: 10_000 })!.bar.volume).toBe(100);
    expect(cb.onTick({ time: 640, price: 12, cumDayVolume: 10_015 })!.bar.volume).toBe(115);
    expect(cb.onTick({ time: 660, price: 12, cumDayVolume: 10_040 })!.bar.volume).toBe(25);
  });

  it('forgets the prior cumulative baseline when reseeded without one', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'day-delta' });
    cb.onTick({ time: 600, price: 10, cumDayVolume: 1000 });
    cb.seed({ time: 720, open: 10, high: 12, low: 9, close: 11, volume: 50 });
    expect(cb.onTick({ time: 730, price: 11, cumDayVolume: 5000 })!.bar.volume).toBe(50);
    expect(cb.onTick({ time: 740, price: 11, cumDayVolume: 5010 })!.bar.volume).toBe(60);
  });

  it('drops ticks older than the current bar when policy is dropOlderThanPrevBar', () => {
    const cb = new CandleBuilder({ intervalSec: 60, lateTickPolicy: 'dropOlderThanPrevBar' });
    cb.onTick({ time: 600, price: 10, ltq: 1 }); // bucket 600
    const late = cb.onTick({ time: 500, price: 99, ltq: 1 }); // older bucket 480 < 600
    expect(late).toBeNull();
    expect(cb.current()!.close).toBe(10); // unaffected
  });

  it('folds late ticks into the current bar when policy is foldIntoBar', () => {
    const cb = new CandleBuilder({ intervalSec: 60, lateTickPolicy: 'foldIntoBar' });
    cb.onTick({ time: 600, price: 10, ltq: 1 });
    const folded = cb.onTick({ time: 500, price: 15, ltq: 1 })!;
    expect(folded.isNew).toBe(false);
    expect(folded.bar.high).toBe(15); // extended by the late high
  });

  it('seeds from the last historical bar so the first tick continues it', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' });
    cb.seed({ time: 600, open: 10, high: 12, low: 9, close: 11, volume: 100 });
    const u = cb.onTick({ time: 630, price: 13, ltq: 5 })!; // same bucket 600
    expect(u.isNew).toBe(false);
    expect(u.bar).toMatchObject({ open: 10, high: 13, close: 13, volume: 105 });
  });
});

describe('CandleBuilder provisional bars', () => {
  // A chart opened at 10:05:15 seeds the builder with whatever history ended
  // on. When that is the 10:04 bar, the first tick opens 10:05 at its own
  // price, fifteen seconds of trades late. Nothing in the tick stream can say
  // so; the builder has to, or the host repairs the wrong open on every poll.
  it('marks the first bar of a cold builder provisional and the next rollover not', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    const a = cb.onTick({ time: 615, price: 10, ltq: 1 })!;
    expect(a).toMatchObject({ isNew: true, provisional: true });
    expect(cb.isProvisional()).toBe(true);
    const b = cb.onTick({ time: 640, price: 11, ltq: 1 })!;
    expect(b).toMatchObject({ isNew: false, provisional: true });
    // The builder streamed 600 to its end, so 660 opens on its first trade.
    const c = cb.onTick({ time: 660, price: 12, ltq: 1 })!;
    expect(c).toMatchObject({ isNew: true, provisional: false });
    expect(cb.isProvisional()).toBe(false);
  });

  it('is not provisional when the seed is the bucket the ticks land in', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.seed({ time: 600, open: 10, high: 12, low: 9, close: 11, volume: 100 });
    const u = cb.onTick({ time: 630, price: 13, ltq: 5 })!;
    expect(u).toMatchObject({ isNew: false, provisional: false });
    expect(cb.isProvisional()).toBe(false);
    const next = cb.onTick({ time: 660, price: 14, ltq: 5 })!;
    expect(next).toMatchObject({ isNew: true, provisional: false });
  });

  it('is provisional when the first tick rolls over from a seed that was never streamed', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.seed({ time: 540, open: 10, high: 12, low: 9, close: 11, volume: 100 });
    const u = cb.onTick({ time: 615, price: 13, ltq: 5 })!;
    expect(u).toMatchObject({ isNew: true, provisional: true });
    expect(u.bar).toMatchObject({ time: 600, open: 13 });
    expect(cb.onTick({ time: 660, price: 14, ltq: 5 })!.provisional).toBe(false);
  });

  it('reseeding forgets the streamed lineage', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.onTick({ time: 615, price: 10, ltq: 1 });
    cb.seed({ time: 600, open: 9, high: 10, low: 9, close: 10, volume: 7 });
    expect(cb.isProvisional()).toBe(false);
    // A reconnect reseeds from the last known bar; the bucket after it was not streamed.
    expect(cb.onTick({ time: 660, price: 12, ltq: 1 })!.provisional).toBe(true);
  });

  it('reconcile adopts the authoritative open, widens the extremes and keeps the close', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.onTick({ time: 615, price: 10, ltq: 1 });
    cb.onTick({ time: 640, price: 11, ltq: 2 });
    const merged = cb.reconcile({ time: 600, open: 9.5, high: 10.5, low: 9, close: 10.2, volume: 40 })!;
    expect(merged).toEqual({ time: 600, open: 9.5, high: 11, low: 9, close: 11, volume: 40 });
    expect(cb.isProvisional()).toBe(false);
    expect(cb.current()).toEqual(merged);
    // Later ticks build on the corrected bar rather than the first-seen open.
    const u = cb.onTick({ time: 650, price: 12, ltq: 1 })!;
    expect(u.bar).toMatchObject({ open: 9.5, high: 12, low: 9, close: 12, volume: 41 });
    expect(u.provisional).toBe(false);
  });

  it('reconcile keeps a streamed open and only widens the extremes', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.seed({ time: 540, open: 8, high: 9, low: 8, close: 9, volume: 5 });
    cb.onTick({ time: 550, price: 9, ltq: 1 });
    cb.onTick({ time: 600, price: 10, ltq: 1 }); // true open: the builder streamed 540
    const merged = cb.reconcile({ time: 600, open: 99, high: 12, low: 7, close: 8, volume: 0 })!;
    expect(merged).toMatchObject({ open: 10, high: 12, low: 7, close: 10, volume: 1 });
  });

  it('reconcile refuses a bar for a different bucket', () => {
    const cb = new CandleBuilder({ intervalSec: 60 });
    cb.onTick({ time: 615, price: 10, ltq: 1 });
    expect(cb.reconcile({ time: 540, open: 1, high: 2, low: 1, close: 2 })).toBeNull();
    expect(cb.current()).toMatchObject({ time: 600, open: 10 });
    expect(cb.isProvisional()).toBe(true);
    expect(new CandleBuilder().reconcile({ time: 600, open: 1, high: 2, low: 1, close: 2 })).toBeNull();
  });

  it('reconcile moves the day-delta baseline so the next tick cannot shrink the volume', () => {
    const cb = new CandleBuilder({ intervalSec: 60, volumeMode: 'day-delta' });
    cb.onTick({ time: 615, price: 10, cumDayVolume: 1000 }); // baseline 1000, volume 0
    cb.onTick({ time: 620, price: 10, cumDayVolume: 1010 }); // volume 10
    cb.reconcile({ time: 600, open: 10, high: 10, low: 10, close: 10, volume: 300 });
    expect(cb.current()!.volume).toBe(300);
    expect(cb.onTick({ time: 630, price: 10, cumDayVolume: 1015 })!.bar.volume).toBe(305);
  });
});
