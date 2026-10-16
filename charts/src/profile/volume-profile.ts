/**
 * Volume Profile (ARCHITECTURE.md §6A). Distributes each bar's volume across the
 * price buckets it spans, then derives the Point of Control and Value Area.
 * From OHLCV this is an approximation (uniform spread across the bar's range);
 * exact profiles need tick data. Pure + testable.
 */
import type { Bar } from '../model/bar';
import type { VolumeProfileResult } from './profile-model';
import { priceBuckets, valueArea } from './profile-model';

/**
 * @deprecated Removed in 3.0.0. No function takes this type:
 * {@link computeVolumeProfile} takes the tick size and the value-area fraction
 * as arguments. For an options object, use {@link computeVolumeProfileSessions}
 * with {@link VolumeProfileFamilyOptions} (since 1.0.1).
 */
export interface VolumeProfileOptions {
  tickSize: number;
  /** Fraction of total volume contained in the value area (default 0.7). */
  valueAreaPercent: number;
}

/**
 * One volume profile over all of `bars`, each bar's volume spread evenly
 * across the rows its range spans. Arguments are taken as given, not repaired:
 * a `tickSize` that is not a positive finite number gives an empty profile,
 * and `valueAreaPercent` is a fraction that is not clamped. At 1 the value
 * area grows from the point of control until it holds all the volume, which
 * leaves out rows without volume at its edges; above 1 it takes every row.
 * A profile without any volume has the point of control alone as its area.
 */
export function computeVolumeProfile(
  bars: readonly Bar[],
  tickSize: number,
  valueAreaPercent = 0.7,
): VolumeProfileResult {
  const vol = new Map<number, number>();
  for (const bar of bars) {
    const buckets = priceBuckets(bar.low, bar.high, tickSize);
    const share = (bar.volume ?? 0) / buckets.length;
    for (const b of buckets) vol.set(b, (vol.get(b) ?? 0) + share);
  }
  const buckets = Array.from(vol.entries())
    .map(([price, volume]) => ({ price, volume }))
    .sort((a, b) => b.price - a.price);

  if (buckets.length === 0) {
    return { buckets, poc: 0, vah: 0, val: 0, totalVolume: 0 };
  }

  const total = buckets.reduce((s, b) => s + b.volume, 0);
  // `valueArea` hands back indices into `buckets`, which is not empty.
  const va = valueArea(buckets.map((b) => b.volume), total * valueAreaPercent);
  return {
    buckets,
    poc: buckets[va.poc]!.price,
    vah: buckets[va.upper]!.price,
    val: buckets[va.lower]!.price,
    totalVolume: total,
  };
}
