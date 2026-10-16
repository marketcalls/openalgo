/**
 * The one rule for two observations of one bucket (src/feed/candle-builder.ts).
 * The data controller's refresh, its live buffer and pushBar, and the candle
 * builder's reconcile all merge this way, and differ only in which side owns
 * the open, the close and the open interest, which each sets itself.
 */
import { describe, expect, it } from 'vitest';
import { widenBar } from '../src/feed/candle-builder';
import type { Bar } from '../src/model/bar';

/** A seeded random walk of bars, some without a volume or an open interest. */
function walk(count: number, seed: number): Bar[] {
  let state = seed;
  const random = (): number => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
  let close = 1480;
  return Array.from({ length: count }, (_, i) => {
    const open = close;
    close = Math.max(1, open + (random() - 0.5) * 18);
    const bar: Bar = { time: 1_700_000_000 + i * 60, open, high: Math.max(open, close) + random() * 4, low: Math.min(open, close) - random() * 4, close };
    if (random() < 0.7) bar.volume = Math.round(random() * 9000);
    if (random() < 0.5) bar.oi = Math.round(random() * 90000);
    return bar;
  });
}

describe('widenBar', () => {
  it('takes the union of the extremes and the larger volume, and the rest from the base', () => {
    const bases = walk(200, 3), observed = walk(200, 8);
    for (let i = 0; i < bases.length; i++) {
      const base = bases[i]!, other = observed[i]!;
      const merged = widenBar(base, other);
      expect(merged).toEqual({
        ...base,
        high: Math.max(base.high, other.high),
        low: Math.min(base.low, other.low),
        volume: base.volume === undefined && other.volume === undefined ? undefined : Math.max(base.volume ?? 0, other.volume ?? 0),
      });
      expect(merged.open).toBe(base.open);
      expect(merged.close).toBe(base.close);
      expect(merged.oi).toBe(base.oi);
      expect(merged).not.toBe(base);
    }
  });

  it('gives a volume to a bar only when one side had one', () => {
    const [a, b] = walk(2, 5);
    const bare = (bar: Bar): Bar => { const { volume: _v, ...rest } = bar; return rest; };
    expect(widenBar(bare(a!), bare(b!)).volume).toBeUndefined();
    expect(widenBar(bare(a!), { ...b!, volume: 12 }).volume).toBe(12);
    expect(widenBar({ ...a!, volume: 30 }, bare(b!)).volume).toBe(30);
    expect(widenBar({ ...a!, volume: 30 }, { ...b!, volume: 12 }).volume).toBe(30);
  });
});
