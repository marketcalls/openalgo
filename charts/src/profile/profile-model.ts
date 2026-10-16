/**
 * Profile data model (ARCHITECTURE.md §6A, Family C). Price-bucketed
 * distributions: volume-at-price, time-at-price (TPO), and bid/ask footprint.
 */
export interface VolumeProfileResult {
  /** Volume per price bucket, sorted high to low price. */
  buckets: { price: number; volume: number }[];
  /** Point of control: price bucket with the most volume. */
  poc: number;
  /** Value-area high / low (the price band holding `valueAreaPercent` of volume). */
  vah: number;
  val: number;
  totalVolume: number;
}

export interface TpoResult {
  buckets: { price: number; count: number }[];
  poc: number;
  vah: number;
  val: number;
  /** Initial balance: price range of the first `ibPeriods` periods. */
  ib: { high: number; low: number };
}

export interface FootprintCell {
  price: number;
  bidVol: number;
  askVol: number;
}

export interface FootprintBar {
  time: number;
  cells: FootprintCell[]; // sorted high to low price
  /** Net delta = Σ(askVol − bidVol). */
  delta: number;
  /** Lowest/highest running trade delta within this bar, including initial zero.
   * Absent when only aggregated price rows are available. */
  minDelta?: number;
  maxDelta?: number;
  /** Effective ladder step: instrument tick size multiplied by rowTicks. */
  rowSize?: number;
  /** Actual traded prices, before ladder rounding. Absent for empty/legacy bars. */
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  /** Number of classified trade records counted (those passing any size filter), not occupied rows. */
  tradeCount?: number;
  /**
   * Bid and ask volume of every print, before any size filter, at the bar's
   * exact high and low prices. An extreme that traded on both sides is an
   * unfinished auction. Absent on manually assembled bars.
   */
  auction?: { highBid: number; highAsk: number; lowBid: number; lowAsk: number };
}

/**
 * The prices a run of sessions covers, each session's levels sorted high to
 * low, or null when none has a level: what a session profile autoscales to.
 */
export function sessionsPriceRange(sessions: readonly { readonly levels: readonly { readonly price: number }[] }[]): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  for (const s of sessions) {
    if (s.levels.length === 0) continue;
    max = Math.max(max, s.levels[0]!.price);
    min = Math.min(min, s.levels[s.levels.length - 1]!.price);
  }
  return Number.isFinite(min) ? { min, max } : null;
}

/** Bucket a price to the tick grid. */
export function bucketPrice(price: number, step: number): number {
  return Math.round((Math.round(price / step) * step) * 1e8) / 1e8;
}

/**
 * Inclusive list of bucket prices spanning [low, high]. A step that is not a
 * positive finite number gives no buckets, and so does a range the numbers
 * cannot step through: a step too small to move a price that large, or a
 * price past the largest number.
 */
export function priceBuckets(low: number, high: number, step: number): number[] {
  // A negative step would walk away from `high` and never stop.
  if (!(step > 0) || step === Infinity) return [];
  const lo = bucketPrice(low, step);
  const hi = bucketPrice(high, step);
  // Counted before the walk, which takes the same steps as ever: a step that
  // no longer moves the price, or a price that overflows, would leave a walk
  // that never passes `hi`.
  const count = Math.round((hi - lo) / step) + 1;
  if (!Number.isFinite(count) || lo + step === lo || hi + step === hi) return [];
  const out: number[] = [];
  for (let i = 0, p = lo; i < count; i++, p += step) out.push(bucketPrice(p, step));
  return out;
}

/**
 * Point of control and value area over rows sorted high to low price, as
 * row indices: the POC is the first row with the most weight (a strict `>`,
 * so a tie keeps the higher price), and the area grows from it one row at a
 * time towards the heavier neighbour, the higher one on a tie, until it holds
 * `target`. `upper` is the area's highest-priced row and `lower` its lowest.
 * Every profile in this tier reads its POC and value area here, which is what
 * keeps the semantics the tier documents identical across them. Tier-internal:
 * the tier index does not re-export it.
 */
export function valueArea(weights: readonly number[], target: number): { poc: number; upper: number; lower: number } {
  let poc = 0;
  for (let i = 1; i < weights.length; i++) if (weights[i]! > weights[poc]!) poc = i;
  let upper = poc;
  let lower = poc;
  let acc = weights[poc] ?? 0;
  // Every index stays in 0..weights.length - 1: the loop bound and the guard
  // on each step keep it there.
  while (acc < target && (upper > 0 || lower < weights.length - 1)) {
    const up = upper > 0 ? weights[upper - 1]! : -1;
    const down = lower < weights.length - 1 ? weights[lower + 1]! : -1;
    if (up >= down) acc += weights[--upper]!;
    else acc += weights[++lower]!;
  }
  return { poc, upper, lower };
}
