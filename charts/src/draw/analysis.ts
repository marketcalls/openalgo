/** Pure OHLCV analysis. Inputs are sorted by ascending UTC timestamp. */
import type { Bar } from 'openalgo-charts';

/** Partial results have unavailable anchor history, missing volume or unusable prices. */
export type AnalysisStatus = 'ready' | 'partial' | 'missing-volume' | 'zero-volume' | 'empty' | 'invalid-data';
export type AnchoredVwapSource = 'hlc3' | 'close' | 'hl2' | 'ohlc4';
export interface AnchoredVwapOptions { source?: AnchoredVwapSource }
export interface AnchoredVwapPoint {
  time: number;
  value: number;
  /** Volume-weighted population standard deviation of the selected source. */
  deviation: number;
  /** Do not connect a line across an omitted observation. */
  breakBefore: boolean;
}
export interface AnchoredVwapResult {
  status: AnalysisStatus;
  /** The requested anchor precedes the earliest supplied bar. */
  historyPartial: boolean;
  points: AnchoredVwapPoint[];
  missingVolumeBars: number;
  invalidPriceBars: number;
}
export interface FixedRangeVolumeProfileOptions {
  /** Requested price rows, rounded and clamped to 4..200. Fewer rows are used when prices cannot represent distinct edges. Default 48. */
  rows?: number;
  /** Percentage of volume in the contiguous area around the POC, 1..100. Default 70. */
  valueArea?: number;
}
export interface AnalysisProfileRow { low: number; high: number; volume: number; valueArea: boolean }
export interface FixedRangeVolumeProfileResult {
  status: AnalysisStatus;
  /** The requested range begins before the earliest supplied bar. */
  historyPartial: boolean;
  rows: AnalysisProfileRow[];
  totalVolume: number;
  /** Midpoint of the largest row. Ties choose the lower price. */
  poc: number | null;
  valueAreaLow: number | null;
  valueAreaHigh: number | null;
  missingVolumeBars: number;
  invalidPriceBars: number;
}

export function analysisNumber(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
}

/**
 * In time-sorted `bars`, the index of the first bar at or after `time`, or
 * with `upper` the first after it: a window found without scanning the
 * loaded history around it.
 */
export function timeBound(bars: readonly { time: number }[], time: number, upper = false): number {
  let lo = 0, hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (upper ? bars[mid]!.time <= time : bars[mid]!.time < time) lo = mid + 1; // mid < hi <= length
    else hi = mid;
  }
  return lo;
}
function status(count: number, weighted: boolean, missing: number, invalid: number, historyPartial: boolean): AnalysisStatus {
  if (count === 0) return 'empty';
  if (weighted) return historyPartial || missing > 0 || invalid > 0 ? 'partial' : 'ready';
  if (missing > 0) return 'missing-volume';
  return invalid > 0 ? 'invalid-data' : 'zero-volume';
}
function sourcePrice(bar: Bar, source: AnchoredVwapSource): number {
  switch (source) {
    case 'close': return bar.close;
    case 'hl2': return bar.low / 2 + bar.high / 2;
    case 'ohlc4': return bar.open / 4 + bar.high / 4 + bar.low / 4 + bar.close / 4;
    default: return bar.high / 3 + bar.low / 3 + bar.close / 3;
  }
}

/**
 * Accumulate from the first bar at or after the anchor, including the live tail.
 * Missing volume is omitted and reported; zero volume adds no statistical weight.
 * Recompute on each call so mutations of the forming candle are always visible.
 */
export function anchoredVwapAnalysis(
  bars: readonly Bar[], anchorTime: number, options: AnchoredVwapOptions = {},
): AnchoredVwapResult {
  const result: AnchoredVwapResult = { status: 'empty', historyPartial: false, points: [], missingVolumeBars: 0, invalidPriceBars: 0 };
  if (!Number.isFinite(anchorTime)) return result;
  result.historyPartial = bars.length > 0 && anchorTime < bars[0]!.time;
  const start = timeBound(bars, anchorTime);
  let weight = 0, scale = 0, origin = 0, mean = 0, m2 = 0, gap = false;
  for (let i = start; i < bars.length; i++) {
    const bar = bars[i]!, volume = bar.volume; // i is in range
    if (volume === undefined || !Number.isFinite(volume) || volume < 0) {
      result.missingVolumeBars++; gap = true; continue;
    }
    const price = sourcePrice(bar, options.source ?? 'hlc3');
    if (!Number.isFinite(price)) { result.invalidPriceBars++; gap = true; continue; }
    if (volume > 0) {
      if (weight === 0) origin = price;
      // Scale weights before multiplication, and center prices before Welford's
      // update. Large prices and volumes need not destroy a small price variance.
      if (volume > scale) {
        const ratio = scale / volume;
        weight *= ratio; m2 *= ratio; scale = volume;
      }
      const w = volume / scale, next = weight + w, delta = (price - origin) - mean;
      mean += delta * (w / next);
      m2 += w * delta * ((price - origin) - mean);
      weight = next;
    }
    if (weight > 0) {
      const value = origin + mean, deviation = Math.sqrt(Math.max(0, m2 / weight));
      if (!Number.isFinite(value) || !Number.isFinite(deviation)) {
        return { ...result, status: 'invalid-data', points: [] };
      }
      result.points.push({ time: bar.time, value, deviation, breakBefore: gap });
      gap = false;
    }
  }
  result.status = status(bars.length - start, weight > 0, result.missingVolumeBars, result.invalidPriceBars, result.historyPartial);
  return result;
}

/**
 * Estimate a volume histogram over the inclusive timestamp range. Each candle's
 * volume is uniform over low..high; this is not trade-by-trade volume. Difference
 * arrays distribute interior rows without visiting each row per candle. Row
 * lookup is bounded by 200 edges: O(bars log(rows) + rows).
 */
export function fixedRangeVolumeProfileAnalysis(
  bars: readonly Bar[], fromTime: number, toTime: number, options: FixedRangeVolumeProfileOptions = {},
): FixedRangeVolumeProfileResult {
  const result: FixedRangeVolumeProfileResult = {
    status: 'empty', historyPartial: false, rows: [], totalVolume: 0, poc: null, valueAreaLow: null, valueAreaHigh: null,
    missingVolumeBars: 0, invalidPriceBars: 0,
  };
  if (!Number.isFinite(fromTime) || !Number.isFinite(toTime)) return result;
  result.historyPartial = bars.length > 0 && Math.min(fromTime, toTime) < bars[0]!.time;
  const start = timeBound(bars, Math.min(fromTime, toTime)), end = timeBound(bars, Math.max(fromTime, toTime), true);
  let low = Infinity, high = -Infinity, compensation = 0;
  for (let i = start; i < end; i++) {
    const bar = bars[i]!, volume = bar.volume; // end <= length
    if (volume === undefined || !Number.isFinite(volume) || volume < 0) { result.missingVolumeBars++; continue; }
    const lo = bar.low, hi = bar.high;
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi < lo) { result.invalidPriceBars++; continue; }
    low = Math.min(low, lo); high = Math.max(high, hi);
    const corrected = volume - compensation, total = result.totalVolume + corrected;
    compensation = (total - result.totalVolume) - corrected;
    result.totalVolume = total;
  }
  result.status = status(end - start, result.totalVolume > 0, result.missingVolumeBars, result.invalidPriceBars, result.historyPartial);
  if (!Number.isFinite(result.totalVolume) || (result.totalVolume > 0 && !Number.isFinite(high - low))) {
    return { ...result, status: 'invalid-data', totalVolume: 0 };
  }
  if (result.totalVolume <= 0) return result;
  const requested = Math.round(analysisNumber(options.rows, 48, 4, 200));
  const boundaries = [low];
  for (let i = 1; i < requested; i++) {
    const edge = low + (high - low) * (i / requested);
    if (edge > boundaries[boundaries.length - 1]! && edge < high) boundaries.push(edge); // never empty
  }
  boundaries.push(high);
  const count = boundaries.length - 1, step = (high - low) / count;
  // Rows are 0..count-1 and their edges 0..count, and every index below is one
  // of them: a row found by `index`, a loop bound, or a step toward the peak's
  // neighbours that the loop condition allows.
  const edges = (i: number): number => boundaries[i]!;
  const volumes = new Float64Array(count), changes = new Float64Array(count + 1);
  const index = (price: number): number => {
    let lo = 0, hi = count;
    while (lo < hi) {
      const mid = (lo + hi + 1) >>> 1;
      if (boundaries[mid]! <= price) lo = mid;
      else hi = mid - 1;
    }
    return Math.min(count - 1, lo);
  };
  for (let i = start; i < end; i++) {
    const bar = bars[i]!, v = bar.volume, lo = bar.low, hi = bar.high;
    if (v === undefined || !Number.isFinite(v) || v <= 0 || !Number.isFinite(lo) || !Number.isFinite(hi) || hi < lo) continue;
    // Normalized weights avoid overflowing an interior-row density when the
    // total volume is finite but prices have very narrow representable ranges.
    const weight = v / result.totalVolume;
    const first = index(lo), last = index(hi);
    if (first === last) { volumes[first]! += weight; continue; }
    const span = hi - lo;
    volumes[first]! += weight * ((edges(first + 1) - lo) / span);
    volumes[last]! += weight * ((hi - edges(last)) / span);
    if (last > first + 1) {
      const interior = weight * (step / span);
      changes[first + 1]! += interior; changes[last]! -= interior;
    }
  }
  let running = 0, peak = 0;
  for (let i = 0; i < count; i++) {
    running += changes[i]!;
    const interior = count === 1 ? 0 : running * ((edges(i + 1) - edges(i)) / step);
    volumes[i] = Math.max(0, Math.min(1, volumes[i]! + interior)) * result.totalVolume;
    if (volumes[i]! > volumes[peak]!) peak = i;
    result.rows.push({ low: edges(i), high: edges(i + 1), volume: volumes[i]!, valueArea: false });
  }
  let left = peak, right = peak, area = volumes[peak]!;
  const target = result.totalVolume * (analysisNumber(options.valueArea, 70, 1, 100) / 100);
  while (area < target && (left > 0 || right < count - 1)) {
    const below = left > 0 ? volumes[left - 1]! : -1, above = right < count - 1 ? volumes[right + 1]! : -1;
    if (below >= above) area += volumes[--left]!;
    else area += volumes[++right]!;
  }
  for (let i = left; i <= right; i++) result.rows[i]!.valueArea = true;
  result.poc = edges(peak) / 2 + edges(peak + 1) / 2;
  result.valueAreaLow = edges(left); result.valueAreaHigh = edges(right + 1);
  return result;
}
