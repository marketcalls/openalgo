/**
 * Order flow signals read across footprint bars: multiple nodes, big limit
 * orders, absorption, aggressive delta flips, price/delta divergence, zones that
 * extend right until price deals with them, and unfinished auctions. Pure, so a
 * host can drive alerts or a scanner from it without a chart.
 */
import type { FootprintBar, FootprintCell } from './profile-model';
import { valueArea } from './profile-model';
import { stackedImbalances } from './footprint';

/**
 * When a zone stops extending: `'closeInside'` once a closed bar closes inside
 * it or any bar trades right through it, `'traverse'` only when a bar trades
 * through it, `'touch'` as soon as any bar trades into it.
 */
export type FootprintZoneEnd = 'closeInside' | 'traverse' | 'touch';
export type FootprintZoneKind = 'stackedBuy' | 'stackedSell' | 'node' | 'absorption';

export interface FootprintSignalOptions {
  imbalanceRatio: number;
  /** Minimum dominant-side quantity for a diagonal imbalance, raw units. */
  imbalanceThreshold: number;
  /** Adjacent same-side imbalances that form a stacked zone. 0 disables. */
  stackedImbalances: number;
  /** Consecutive bars whose highest-volume row sits at one price. 0 disables, otherwise at least 2. */
  multipleNodeBars: number;
  /** A big limit order is at least this many times the average cell. 0 disables. */
  bigOrderMultiple: number;
  /** Absorption needs bid and ask each at least this many times their average cell. 0 disables. */
  absorptionMultiple: number;
  /** Bars, the current one included, that the average cell is taken over. */
  signalLookback: number;
  /** How near the bar's high or low, in rows, a big order or absorption must be. */
  nearExtremeRows: number;
  /** Bars of opposite delta before an aggressive flip. 0 disables. */
  flipBars: number;
  /** Minimum |delta| of the flip bar, as a percentage of its volume. */
  flipMinDeltaPct: number;
  zoneEnd: FootprintZoneEnd;
  /** Whole bars that must trade completely beyond a zone before it is active for alerts. */
  zoneActiveAfter: number;
  /** Zones start only in the newest this many bars (since 2.6.4). 0, the default, takes every bar. */
  zoneLookback: number;
  /**
   * The newest bar is still forming: its close is not final, so it cannot end a
   * zone by closing inside it, and its high and low are not final, so it gets no
   * unfinished auction yet.
   */
  formingLastBar: boolean;
}

export const DEFAULT_FOOTPRINT_SIGNAL_OPTIONS: FootprintSignalOptions = {
  imbalanceRatio: 3, imbalanceThreshold: 0, stackedImbalances: 3, multipleNodeBars: 2,
  bigOrderMultiple: 3, absorptionMultiple: 2, signalLookback: 10, nearExtremeRows: 3,
  flipBars: 2, flipMinDeltaPct: 8, zoneEnd: 'closeInside', zoneActiveAfter: 1, zoneLookback: 0, formingLastBar: true,
};

export interface FootprintZone {
  kind: FootprintZoneKind;
  /** Time of the bar the zone starts after. */
  time: number;
  /** Price span, from the outer edge of its lowest row to the outer edge of its highest. */
  low: number;
  high: number;
  /** Time of the bar that ended it, or null while it still extends. */
  endTime: number | null;
  /** Time of the bar that made it active for alerts, or null. */
  activeTime: number | null;
  /**
   * Time of the first bar after it became active whose high to low range
   * reached it, which is when an alert fires (since 2.6.4), or null. A bar that
   * jumps across the zone reaches it too, as it would trigger a stop there.
   */
  touchTime: number | null;
}

export interface FootprintAuction {
  /** Time of the bar whose extreme traded on both bid and ask. */
  time: number;
  side: 'high' | 'low';
  price: number;
  /** Time of the first later bar that traded beyond the price, or null. */
  endTime: number | null;
}

export interface FootprintBarSignals {
  time: number;
  /** Its highest-volume row matches a neighbour's: part of a multiple node. */
  node: boolean;
  /** Row price of a big limit order on the bid (near the low) or the ask (near the high). */
  bigBid: number | null;
  bigAsk: number | null;
  /** Row price spans where heavy volume traded on both sides near an extreme. */
  absorption: { low: number; high: number }[];
  /** +1 aggressive buying flip, -1 aggressive selling flip, 0 none. */
  flip: -1 | 0 | 1;
  /** An up bar with negative delta or a down bar with positive delta. */
  divergence: boolean;
}

export interface FootprintSignals {
  bars: FootprintBarSignals[];
  zones: FootprintZone[];
  auctions: FootprintAuction[];
}

const MEDIAN_BARS = 20;
const FLIP_FACTOR = 1.5;
const SWING_BARS = 10;

interface Shape {
  bar: FootprintBar;
  /** Rows low to high price, which is the order the rules count positions in. */
  rows: FootprintCell[];
  row: number;
  high: number;
  low: number;
  volume: number;
  poc: number | null;
  sumBid: number;
  bidCells: number;
  sumAsk: number;
  askCells: number;
}

function shapeOf(bar: FootprintBar): Shape {
  const rows = [...bar.cells].sort((a, b) => a.price - b.price);
  let row = bar.rowSize ?? Infinity;
  for (let i = 1; i < rows.length; i++) row = Math.min(row, rows[i]!.price - rows[i - 1]!.price);
  let volume = 0, sumBid = 0, bidCells = 0, sumAsk = 0, askCells = 0;
  for (const c of rows) {
    volume += c.bidVol + c.askVol;
    if (c.bidVol > 0) { sumBid += c.bidVol; bidCells++; }
    if (c.askVol > 0) { sumAsk += c.askVol; askCells++; }
  }
  const high = bar.high ?? rows[rows.length - 1]?.price ?? 0;
  const low = bar.low ?? rows[0]?.price ?? 0;
  const top = [...rows].reverse();
  const poc = volume > 0 ? top[valueArea(top.map(c => c.bidVol + c.askVol), 0).poc]!.price : null;
  return { bar, rows, row: Number.isFinite(row) ? row : 0, high, low, volume, poc, sumBid, bidCells, sumAsk, askCells };
}

function validate(o: FootprintSignalOptions): void {
  for (const v of [o.imbalanceRatio, o.signalLookback, o.nearExtremeRows]) {
    if (!Number.isFinite(v) || v <= 0) throw new RangeError('Footprint signal ratio and lookbacks must be positive and finite');
  }
  for (const v of [o.imbalanceThreshold, o.bigOrderMultiple, o.absorptionMultiple, o.flipMinDeltaPct]) {
    if (!Number.isFinite(v) || v < 0) throw new RangeError('Footprint signal thresholds must be nonnegative and finite');
  }
  for (const v of [o.stackedImbalances, o.multipleNodeBars, o.flipBars, o.zoneActiveAfter, o.zoneLookback]) {
    if (!Number.isSafeInteger(v) || v < 0) throw new RangeError('Footprint signal counts must be nonnegative integers');
  }
  if (o.multipleNodeBars === 1) throw new RangeError('Footprint multipleNodeBars must be 0 or at least 2');
  if (o.zoneEnd !== 'closeInside' && o.zoneEnd !== 'traverse' && o.zoneEnd !== 'touch') throw new TypeError('Unknown footprint zone end rule');
}

/** Signals for `bars`, oldest first, using {@link DEFAULT_FOOTPRINT_SIGNAL_OPTIONS} for anything not given. */
export function footprintSignals(bars: readonly FootprintBar[], options: Partial<FootprintSignalOptions> = {}): FootprintSignals {
  const o = { ...DEFAULT_FOOTPRINT_SIGNAL_OPTIONS, ...options };
  validate(o);
  const shapes = bars.map(shapeOf);
  const out: FootprintBarSignals[] = shapes.map((s, k) => ({
    time: s.bar.time, node: false, flip: 0,
    divergence: s.bar.open !== undefined && s.bar.close !== undefined
      && ((s.bar.close > s.bar.open && s.bar.delta < 0) || (s.bar.close < s.bar.open && s.bar.delta > 0)),
    ...cellSignals(shapes, k, o),
  }));
  for (let k = 0; k < shapes.length; k++) out[k]!.flip = flipAt(shapes, k, o);
  const zones: FootprintZone[] = [];
  const first = o.zoneLookback > 0 ? shapes.length - o.zoneLookback : 0;
  const zone = (kind: FootprintZoneKind, k: number, lowRow: number, highRow: number): void => {
    if (k < first) return;
    const half = shapes[k]!.row / 2;
    zones.push(resolveZone({ kind, time: shapes[k]!.bar.time, low: lowRow - half, high: highRow + half, endTime: null, activeTime: null, touchTime: null }, shapes, k, o));
  };
  for (let k = 0; k < shapes.length; k++) {
    const s = shapes[k]!;
    if (o.stackedImbalances > 0) {
      for (const run of stackedImbalances(s.bar.cells, o.imbalanceRatio, o.stackedImbalances, s.row || undefined, o.imbalanceThreshold)) {
        zone(run.side === 'buy' ? 'stackedBuy' : 'stackedSell', k, Math.min(run.startPrice, run.endPrice), Math.max(run.startPrice, run.endPrice));
      }
    }
    for (const span of out[k]!.absorption) zone('absorption', k, span.low, span.high);
  }
  markNodes(shapes, out, o, (k) => zone('node', k, shapes[k]!.poc!, shapes[k]!.poc!));
  zones.sort((a, b) => a.time - b.time);
  return { bars: out, zones, auctions: auctions(shapes, o) };
}

/** Big limit orders and absorption, measured against the average cell over the lookback. */
function cellSignals(shapes: readonly Shape[], k: number, o: FootprintSignalOptions): Pick<FootprintBarSignals, 'bigBid' | 'bigAsk' | 'absorption'> {
  const s = shapes[k]!, n = s.rows.length, near = o.nearExtremeRows;
  let sumBid = 0, bidCells = 0, sumAsk = 0, askCells = 0;
  for (let j = Math.max(0, k - o.signalLookback + 1); j <= k; j++) {
    const p = shapes[j]!;
    sumBid += p.sumBid; bidCells += p.bidCells; sumAsk += p.sumAsk; askCells += p.askCells;
  }
  const avgBid = bidCells ? sumBid / bidCells : 0, avgAsk = askCells ? sumAsk / askCells : 0;
  const avgCell = bidCells + askCells ? (sumBid + sumAsk) / (bidCells + askCells) : 0;
  const result: Pick<FootprintBarSignals, 'bigBid' | 'bigAsk' | 'absorption'> = { bigBid: null, bigAsk: null, absorption: [] };
  if (n === 0) return result;
  // The largest bid near the low while sellers dominate the bar, or the largest ask near the high while buyers do.
  let maxBid = 0, maxAsk = 0;
  for (let i = 1; i < n; i++) {
    if (s.rows[i]!.bidVol > s.rows[maxBid]!.bidVol) maxBid = i;
    if (s.rows[i]!.askVol > s.rows[maxAsk]!.askVol) maxAsk = i;
  }
  if (o.bigOrderMultiple > 0 && avgCell > 0) {
    if (s.bar.delta < 0 && maxBid < near && s.rows[maxBid]!.bidVol >= o.bigOrderMultiple * avgCell) result.bigBid = s.rows[maxBid]!.price;
    if (s.bar.delta > 0 && maxAsk >= n - near && s.rows[maxAsk]!.askVol >= o.bigOrderMultiple * avgCell) result.bigAsk = s.rows[maxAsk]!.price;
  }
  if (o.absorptionMultiple > 0 && avgBid > 0 && avgAsk > 0) {
    let start = -1;
    for (let i = 0; i <= n; i++) {
      const c = s.rows[i];
      const heavy = c !== undefined && (i < near || i >= n - near)
        && c.bidVol >= o.absorptionMultiple * avgBid && c.askVol >= o.absorptionMultiple * avgAsk;
      const joins = heavy && start >= 0 && adjacent(s.rows[i - 1]!.price, c.price, s.row);
      if (heavy && (start < 0 || joins)) { if (start < 0) start = i; continue; }
      if (start >= 0) result.absorption.push({ low: s.rows[start]!.price, high: s.rows[i - 1]!.price });
      start = heavy ? i : -1;
    }
  }
  return result;
}

function adjacent(lower: number, upper: number, row: number): boolean {
  return row > 0 && Math.abs(upper - lower - row) <= row * 1e-6;
}

/**
 * Delta turns after `flipBars` bars of the other sign, is a real share of the bar
 * and large against recent bars, and the bar sits at a swing: its extreme over the
 * last few bars is the extreme of the wider window.
 */
function flipAt(shapes: readonly Shape[], k: number, o: FootprintSignalOptions): -1 | 0 | 1 {
  const s = shapes[k]!, delta = s.bar.delta;
  if (o.flipBars === 0 || delta === 0 || k < o.flipBars || s.volume <= 0) return 0;
  const sign = delta > 0 ? 1 : -1;
  for (let j = k - o.flipBars; j < k; j++) if (Math.sign(shapes[j]!.bar.delta) !== -sign) return 0;
  if (Math.abs(delta) / s.volume * 100 < o.flipMinDeltaPct) return 0;
  const recent: number[] = [];
  for (let j = Math.max(0, k - MEDIAN_BARS); j < k; j++) recent.push(Math.abs(shapes[j]!.bar.delta));
  recent.sort((a, b) => a - b);
  if (recent.length && Math.abs(delta) < FLIP_FACTOR * recent[recent.length >> 1]!) return 0;
  let near = sign > 0 ? Infinity : -Infinity, far = near;
  for (let j = Math.max(0, k - SWING_BARS); j <= k; j++) {
    const v = sign > 0 ? shapes[j]!.low : shapes[j]!.high;
    far = sign > 0 ? Math.min(far, v) : Math.max(far, v);
    if (j >= k - o.flipBars) near = sign > 0 ? Math.min(near, v) : Math.max(near, v);
  }
  return near === far ? sign : 0;
}

/** Runs of consecutive bars whose highest-volume row is at one price; the zone starts after the run's last bar. */
function markNodes(shapes: readonly Shape[], out: FootprintBarSignals[], o: FootprintSignalOptions, origin: (k: number) => void): void {
  if (o.multipleNodeBars === 0) return;
  let first = 0;
  for (let k = 1; k <= shapes.length; k++) {
    const a = shapes[k - 1], b = shapes[k];
    if (b !== undefined && a!.poc !== null && b.poc !== null && Math.abs(a!.poc - b.poc) <= Math.max(a!.row, b.row) * 1e-6) continue;
    if (k - first >= o.multipleNodeBars && shapes[first]!.poc !== null) {
      for (let j = first; j < k; j++) out[j]!.node = true;
      origin(k - 1);
    }
    first = k;
  }
}

function resolveZone(zone: FootprintZone, shapes: readonly Shape[], k: number, o: FootprintSignalOptions): FootprintZone {
  let beyond = 0;
  for (let j = k + 1; j < shapes.length; j++) {
    const s = shapes[j]!, close = s.bar.close;
    const closed = !(o.formingLastBar && j === shapes.length - 1);
    const touch = s.high >= zone.low && s.low <= zone.high;
    const traverse = s.high >= zone.high && s.low <= zone.low;
    const inside = closed && close !== undefined && close >= zone.low && close <= zone.high;
    // The bar that ends a zone can still be the first to come back to it.
    if (zone.activeTime !== null && zone.touchTime === null && touch) zone.touchTime = s.bar.time;
    if (o.zoneEnd === 'touch' ? touch : o.zoneEnd === 'traverse' ? traverse : inside || traverse) {
      zone.endTime = s.bar.time;
      return zone;
    }
    if (zone.activeTime === null && (s.low > zone.high || s.high < zone.low) && ++beyond >= o.zoneActiveAfter) zone.activeTime = s.bar.time;
  }
  return zone;
}

/** Bar extremes that traded on both bid and ask, ended by the first later bar trading beyond them. */
function auctions(shapes: readonly Shape[], o: FootprintSignalOptions): FootprintAuction[] {
  const out: FootprintAuction[] = [];
  const last = o.formingLastBar ? shapes.length - 1 : shapes.length;
  for (let k = 0; k < last; k++) {
    const s = shapes[k]!, a = s.bar.auction;
    if (a === undefined) continue;
    for (const side of ['high', 'low'] as const) {
      const both = side === 'high' ? a.highBid > 0 && a.highAsk > 0 : a.lowBid > 0 && a.lowAsk > 0;
      if (!both) continue;
      const price = side === 'high' ? s.high : s.low;
      const eps = Math.max(1, Math.abs(price)) * 1e-9;
      let endTime: number | null = null;
      for (let j = k + 1; j < shapes.length && endTime === null; j++) {
        if (side === 'high' ? shapes[j]!.high > price + eps : shapes[j]!.low < price - eps) endTime = shapes[j]!.bar.time;
      }
      out.push({ time: s.bar.time, side, price, endTime });
    }
  }
  return out;
}
