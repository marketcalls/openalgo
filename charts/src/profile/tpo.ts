/**
 * Time Price Opportunity / Market Profile (ARCHITECTURE.md §6A). Buckets
 * intraday bars into TPO periods and counts how many periods traded at each
 * price. Derives POC, Value Area, and the Initial Balance (first periods'
 * range). Derivable from OHLCV intraday bars. Pure + testable.
 */
import type { Bar } from '../model/bar';
import type { TpoResult } from './profile-model';
import { priceBuckets, valueArea } from './profile-model';

/**
 * One TPO profile over all of `bars`, a period every `periodBars` bars. A
 * `periodBars` below 1 counts as 1; otherwise the arguments are taken as
 * given: a `tickSize` that is not a positive finite number gives an empty
 * profile, and `valueAreaPercent` is a fraction that is not clamped.
 */
export function computeTpo(
  bars: readonly Bar[],
  periodBars: number,
  tickSize: number,
  valueAreaPercent = 0.7,
  ibPeriods = 2,
): TpoResult {
  const period = Math.max(1, periodBars);
  const count = new Map<number, number>();
  let ibHigh = -Infinity;
  let ibLow = Infinity;

  const numPeriods = Math.ceil(bars.length / period);
  for (let p = 0; p < numPeriods; p++) {
    const slice = bars.slice(p * period, (p + 1) * period);
    if (slice.length === 0) continue;
    let pHigh = -Infinity;
    let pLow = Infinity;
    for (const b of slice) { pHigh = Math.max(pHigh, b.high); pLow = Math.min(pLow, b.low); }
    if (p < ibPeriods) { ibHigh = Math.max(ibHigh, pHigh); ibLow = Math.min(ibLow, pLow); }
    for (const bkt of priceBuckets(pLow, pHigh, tickSize)) count.set(bkt, (count.get(bkt) ?? 0) + 1);
  }

  const buckets = Array.from(count.entries())
    .map(([price, c]) => ({ price, count: c }))
    .sort((a, b) => b.price - a.price);

  if (buckets.length === 0) {
    return { buckets, poc: 0, vah: 0, val: 0, ib: { high: 0, low: 0 } };
  }

  const total = buckets.reduce((s, b) => s + b.count, 0);
  // `valueArea` hands back indices into `buckets`, which is not empty.
  const va = valueArea(buckets.map((b) => b.count), total * valueAreaPercent);
  return {
    buckets,
    poc: buckets[va.poc]!.price,
    vah: buckets[va.upper]!.price,
    val: buckets[va.lower]!.price,
    ib: { high: ibHigh, low: ibLow },
  };
}
