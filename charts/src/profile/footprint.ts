/**
 * Footprint & order flow (ARCHITECTURE.md §6A, Family C). Per-candle bid/ask
 * volume at each price, delta, and imbalance, plus cumulative delta and
 * stacked-imbalance detection across bars.
 *
 * DATA DEPENDENCY (honest): this needs trade-by-trade data classified bid/ask
 * (was each print at the bid or the ask?). OpenAlgo serves live depth + tick LTP
 * but does not store historical classified trades by default, so footprint is
 * either live-session-only or needs a tick-recorder backend. The computation
 * here is pure and broker-agnostic; feeding it is the integration step.
 */
import type { FootprintBar, FootprintCell } from './profile-model';
import { bucketPrice } from './profile-model';

export interface ClassifiedTrade {
  price: number;
  qty: number;
  /** Whether the print hit the bid (sell-initiated) or the ask (buy-initiated). */
  side: 'bid' | 'ask';
}

/** Options shared by `computeFootprint` and `FootprintAggregator`. */
export interface FootprintBuildOptions {
  /**
   * Count only single prints of at least this raw quantity. Smaller prints still
   * open their row (it shows zero) and still set the bar's open, high, low and
   * close, so the ladder keeps its full range. 0, the default, counts every print.
   */
  minTradeSize?: number;
}

/**
 * The row a price belongs to, as a row index on the `tickSize * rowTicks` grid.
 *
 * The price is first put on its tick (half away from zero), then the tick on
 * its row by round half to even. Rows are centred on multiples of the row size,
 * so a tick exactly between two row centres has to go one way or the other;
 * half to even sends alternate boundaries up and down instead of always up,
 * which keeps a ladder of grouped rows unbiased and matches the reference
 * order flow tooling this footprint is verified against.
 */
function footprintRowIndex(price: number, tickSize: number, rowTicks: number): number {
  const scaled = price / tickSize;
  const tick = Math.sign(scaled) * Math.round(Math.abs(scaled));
  const below = Math.floor(tick / rowTicks);
  const twice = 2 * (tick - below * rowTicks);
  return twice > rowTicks || (twice === rowTicks && below % 2 !== 0) ? below + 1 : below;
}

/** Price at the centre of the row holding `price`, on the same grid as `bucketPrice`. */
export function footprintRowPrice(price: number, tickSize: number, rowTicks: number): number {
  return bucketPrice(footprintRowIndex(price, tickSize, rowTicks) * rowTicks * tickSize, tickSize * rowTicks);
}

/** Internal: validated `minTradeSize`. */
export function minTradeSizeOf(options: FootprintBuildOptions | undefined): number {
  const size = options?.minTradeSize ?? 0;
  if (!Number.isFinite(size) || size < 0) throw new RangeError('Footprint minTradeSize must be nonnegative and finite');
  return size;
}

/**
 * Build one bar's footprint from its classified trades.
 *
 * `rowTicks` is the same multiplier the market profile uses: rows are
 * `tickSize * rowTicks` tall, so a trader can widen bricks without pretending
 * the instrument has a coarser tick. Nifty at 0.1 with 2-point bricks is
 * `computeFootprint(t, trades, 0.1, 20)`.
 */
export function computeFootprint(
  time: number,
  trades: readonly ClassifiedTrade[],
  tickSize: number,
  rowTicks = 1,
  options?: FootprintBuildOptions,
): FootprintBar {
  const row = footprintRowSize(tickSize, rowTicks);
  const minSize = minTradeSizeOf(options);
  if (!Number.isFinite(time)) throw new RangeError('Footprint time must be finite');
  for (const trade of trades) validateClassifiedTrade(trade);
  const map = new Map<number, FootprintCell>();
  const ticks = new Map<number, [number, number]>();
  let delta = 0, minDelta = 0, maxDelta = 0, counted = 0;
  for (const t of trades) {
    const price = footprintRowPrice(t.price, tickSize, rowTicks);
    let cell = map.get(price);
    if (cell === undefined) { cell = { price, bidVol: 0, askVol: 0 }; map.set(price, cell); }
    addTickVolume(ticks, t, tickSize);
    if (t.qty < minSize) continue;
    counted++;
    if (t.side === 'bid') { cell.bidVol += t.qty; delta -= t.qty; }
    else { cell.askVol += t.qty; delta += t.qty; }
    minDelta = Math.min(minDelta, delta);
    maxDelta = Math.max(maxDelta, delta);
  }
  const cells = Array.from(map.values()).sort((a, b) => b.price - a.price);
  const bar: FootprintBar = { time, cells, delta, minDelta, maxDelta, rowSize: row, tradeCount: counted };
  if (trades.length > 0) {
    bar.open = trades[0]!.price;
    bar.close = trades[trades.length - 1]!.price;
    bar.high = bar.low = trades[0]!.price;
    for (const trade of trades) {
      bar.high = Math.max(bar.high, trade.price);
      bar.low = Math.min(bar.low, trade.price);
    }
    bar.auction = auctionAt(ticks, bar.high, bar.low, tickSize);
  }
  return bar;
}

/**
 * Internal: every print's volume at its own tick, before the size filter. Only
 * the bar's two extremes are ever read back, for unfinished auctions.
 */
export function addTickVolume(ticks: Map<number, [number, number]>, trade: ClassifiedTrade, tickSize: number): void {
  const key = Math.round(trade.price / tickSize);
  let at = ticks.get(key);
  if (at === undefined) { at = [0, 0]; ticks.set(key, at); }
  at[trade.side === 'bid' ? 0 : 1] += trade.qty;
}

/** Internal: bid and ask volume of every print at the bar's high and low ticks. */
export function auctionAt(ticks: ReadonlyMap<number, [number, number]>, high: number, low: number, tickSize: number): NonNullable<FootprintBar['auction']> {
  const top = ticks.get(Math.round(high / tickSize)) ?? [0, 0];
  const bottom = ticks.get(Math.round(low / tickSize)) ?? [0, 0];
  return { highBid: top[0], highAsk: top[1], lowBid: bottom[0], lowAsk: bottom[1] };
}

export interface Imbalance {
  price: number;
  side: 'buy' | 'sell';
}

/** Internal shared validation for batch and streaming footprints. */
export function footprintRowSize(tickSize: number, rowTicks: number): number {
  if (!Number.isFinite(tickSize) || tickSize <= 0) throw new RangeError('Footprint tickSize must be positive and finite');
  if (!Number.isSafeInteger(rowTicks) || rowTicks < 1) throw new RangeError('Footprint rowTicks must be a positive integer');
  const row = tickSize * rowTicks;
  if (!Number.isFinite(row)) throw new RangeError('Footprint tickSize * rowTicks must be finite');
  return row;
}

/** Internal shared validation; zero quantity is allowed and still counts as a record. */
export function validateClassifiedTrade(trade: ClassifiedTrade): void {
  if (!Number.isFinite(trade.price)) throw new RangeError('Footprint trade price must be finite');
  if (!Number.isFinite(trade.qty) || trade.qty < 0) throw new RangeError('Footprint trade qty must be nonnegative and finite');
  if (trade.side !== 'bid' && trade.side !== 'ask') throw new TypeError('Footprint trade side must be bid or ask');
}

function observedRowSize(cells: readonly FootprintCell[]): number {
  let row = Infinity;
  for (let i = 1; i < cells.length; i++) {
    const gap = cells[i - 1]!.price - cells[i]!.price;
    if (gap > 0) row = Math.min(row, gap);
  }
  return row;
}

function tolerance(upper: number, lower: number, row: number): number {
  return Math.max(row * 1e-7, Math.max(Math.abs(upper), Math.abs(lower)) * Number.EPSILON * 8);
}

function adjacent(upper: number, lower: number, row: number): boolean {
  return Number.isFinite(row) && upper > lower && Math.abs(upper - lower - row) <= tolerance(upper, lower, row);
}

/** More empty rows than this in one gap means the row step is wrong for the bar, not that rows went untraded. */
export const MAX_EMPTY_ROWS = 1000;

/**
 * The volume a cell is compared with between `upper` and `lower`: the next row's, or
 * zero when rows that never traded lie between them inside the bar. Undefined
 * when the two are closer than a row apart, or further apart than
 * `MAX_EMPTY_ROWS` rows: either is a grid the row size does not describe, so
 * nothing is compared.
 */
function across(upper: number, lower: number, row: number, volume: number): number | undefined {
  if (adjacent(upper, lower, row)) return volume;
  const gap = upper - lower;
  return Number.isFinite(row) && gap > row + tolerance(upper, lower, row) && Math.round(gap / row) - 1 <= MAX_EMPTY_ROWS ? 0 : undefined;
}

/**
 * Diagonal imbalances compare ask at P with bid one row below, and bid at P
 * with ask one row above. A row between the bar's high and low that never
 * traded holds zero volume, so a cell beside it is compared with zero (since
 * 2.6.4; through 2.6.3 such a cell was not compared). The rows beyond the
 * bar's high and low are not compared at all. Supply rowSize for sparse
 * ladders; legacy callers infer the minimum observed gap, which cannot
 * distinguish uniformly missing rows from a coarser grid. Positive volume
 * against a zero opposing volume is an imbalance; zero against zero is not.
 * threshold is the minimum dominant-side quantity (inclusive).
 */
export function diagonalImbalances(cells: readonly FootprintCell[], ratio = 3, rowSize?: number, threshold = 0): Imbalance[] {
  if (!Number.isFinite(ratio) || ratio <= 0) throw new RangeError('Imbalance ratio must be positive and finite');
  if (rowSize !== undefined && (!Number.isFinite(rowSize) || rowSize <= 0)) throw new RangeError('Imbalance rowSize must be positive and finite');
  if (!Number.isFinite(threshold) || threshold < 0) throw new RangeError('Imbalance threshold must be nonnegative and finite');
  const sorted = [...cells].sort((a, b) => b.price - a.price);
  const row = rowSize ?? observedRowSize(sorted);
  const dominates = (volume: number, opposing: number): boolean => volume > 0 && volume >= threshold && volume >= ratio * opposing;
  const out: Imbalance[] = [];
  for (let i = 0; i < sorted.length; i++) {
    const here = sorted[i]!;
    const below = sorted[i + 1];
    const above = sorted[i - 1];
    const bidBelow = below && across(here.price, below.price, row, below.bidVol);
    const askAbove = above && across(above.price, here.price, row, above.askVol);
    if (bidBelow !== undefined && dominates(here.askVol, bidBelow)) out.push({ price: here.price, side: 'buy' });
    if (askAbove !== undefined && dominates(here.bidVol, askAbove)) out.push({ price: here.price, side: 'sell' });
  }
  return out;
}

/** Running cumulative delta across a sequence of footprint bars. */
export function cumulativeDelta(bars: readonly FootprintBar[]): number[] {
  const out: number[] = [];
  let acc = 0;
  for (const b of bars) { acc += b.delta; out.push(acc); }
  return out;
}

export interface StackedImbalance {
  startPrice: number;
  endPrice: number;
  side: 'buy' | 'sell';
  count: number;
}

/** Runs of minStack+ adjacent diagonal imbalances, tracked independently per side. */
export function stackedImbalances(cells: readonly FootprintCell[], ratio = 3, minStack = 3, rowSize?: number, threshold = 0): StackedImbalance[] {
  if (!Number.isSafeInteger(minStack) || minStack < 1) throw new RangeError('Imbalance minStack must be a positive integer');
  const sorted = [...cells].sort((a, b) => b.price - a.price);
  const imb = diagonalImbalances(sorted, ratio, rowSize, threshold);
  const row = rowSize ?? observedRowSize(sorted);
  const out: StackedImbalance[] = [];
  for (const side of ['buy', 'sell'] as const) {
    const prices = new Set(imb.filter((entry) => entry.side === side).map((entry) => entry.price));
    let run: StackedImbalance | undefined;
    const finish = (): void => {
      if (run && run.count >= minStack) out.push(run);
      run = undefined;
    };
    for (const cell of sorted) {
      if (!prices.has(cell.price)) { finish(); continue; }
      if (run && !adjacent(run.endPrice, cell.price, row)) finish();
      if (run) { run.endPrice = cell.price; run.count++; }
      else run = { startPrice: cell.price, endPrice: cell.price, side, count: 1 };
    }
    finish();
  }
  return out.sort((a, b) => b.startPrice - a.startPrice);
}
