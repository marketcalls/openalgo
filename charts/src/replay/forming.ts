import type { Bar } from '../model/bar';

/**
 * The partial bar replay shows while a displayed bar forms: what the finer bars
 * consumed so far say, held inside the displayed bar the bucket closes on.
 *
 * A bucket closes on the displayed bar verbatim, so every step before it has to
 * be a bar that can still grow into that one, the way a live candle grows: its
 * open is its first trade and never moves, its high only rises, its low only
 * falls and its volume only adds. Two feeds disagree in practice (an exchange's
 * official open against the first minute's open, a vendor's minute extremes
 * against its daily ones, minute volumes that do not sum to the day's). Taking
 * the forming values from the finer feed alone let the open jump when the bucket
 * closed and the high fall back, and an indicator read off the forming bar saw a
 * price the closed bar then denied.
 *
 * So the open is the displayed bar's from the first step, the finer extremes and
 * close are held inside the displayed bar's range, and volume stops at the
 * displayed bar's. Where the feeds agree nothing is held, and each step is
 * exactly the aggregate of the finer bars so far.
 *
 * `raw` is that aggregate; its open is not used. A displayed bar without finite
 * prices has no range to hold anything inside, and `raw` is returned as it is.
 */
export function formingWithin(raw: Bar, final: Bar): Bar {
  const open = final.open;
  const top = Math.max(final.high, final.open, final.close);
  const bottom = Math.min(final.low, final.open, final.close);
  if (!Number.isFinite(open) || !Number.isFinite(top) || !Number.isFinite(bottom)) return raw;
  const hold = (v: number): number => (v > top ? top : v < bottom ? bottom : v);
  const close = hold(raw.close);
  const bar: Bar = {
    time: final.time,
    open,
    high: Math.max(open, hold(raw.high), close),
    low: Math.min(open, hold(raw.low), close),
    close,
  };
  if (raw.volume !== undefined) {
    bar.volume = final.volume !== undefined && Number.isFinite(final.volume) ? Math.min(raw.volume, final.volume) : raw.volume;
  }
  // Open interest is a level read at each finer bar, not a quantity that grows
  // toward the close, so the latest revealed reading stands as it is.
  if (raw.oi !== undefined) bar.oi = raw.oi;
  return bar;
}

/**
 * Fold one finer bar into a running aggregate. The extremes take the finer bar's
 * open and close as well as its high and low, so a finer bar whose close lies
 * outside its own range cannot widen one step and let the next one narrow again.
 */
export function foldFiner(into: Bar, sub: Bar): void {
  const high = Math.max(sub.high, sub.open, sub.close);
  const low = Math.min(sub.low, sub.open, sub.close);
  if (high > into.high) into.high = high;
  if (low < into.low) into.low = low;
  into.close = sub.close;
  into.volume = (into.volume ?? 0) + (sub.volume ?? 0);
  // Open interest is a level; retain the last reading, never a sum.
  if (sub.oi !== undefined) into.oi = sub.oi;
}

/** A running aggregate started from its first finer bar, stamped with the bucket's time. */
export function startFiner(sub: Bar, time: number): Bar {
  const bar: Bar = {
    time, open: sub.open,
    high: Math.max(sub.high, sub.open, sub.close),
    low: Math.min(sub.low, sub.open, sub.close),
    close: sub.close, volume: sub.volume ?? 0,
  };
  if (sub.oi !== undefined) bar.oi = sub.oi;
  return bar;
}

/**
 * Step `step` (0-based) of `steps` for a bar that no finer bar covers, formed
 * along a simulated path. The last step is the bar itself, so callers ask this
 * only for the steps before it.
 *
 * The path runs from the open to the extreme nearer it, across to the other
 * extreme and on to the close (on a tie, low first when the bar closes up and
 * high first when it closes down), and each step covers the same share of that
 * distance. The bar keeps its open from the first step, reaches its real high
 * and low, and its extremes only widen, as a traded bar's do. The order of the
 * extremes is an assumption, not a record: a bar's prices say where it went and
 * not when, which is why replay reports these steps as simulated. Volume grows
 * in proportion. Open interest holds `oi`, the last reading known before the
 * bar, because the bar's own is not known until it closes.
 */
export function simulatedForming(final: Bar, step: number, steps: number, oi?: number): Bar {
  const { open, high, low, close } = final;
  const t = Math.min(1, (step + 1) / steps);
  const lowFirst = open - low < high - open || (open - low === high - open && close >= open);
  const path: [number, number, number, number] = lowFirst ? [open, low, high, close] : [open, high, low, close];
  let left = t * (Math.abs(path[1] - path[0]) + Math.abs(path[2] - path[1]) + Math.abs(path[3] - path[2]));
  let price = open;
  let top = open;
  let bottom = open;
  for (let i = 1; i < path.length && left > 0; i++) { // `i` and `i - 1` stay inside the path
    const leg = Math.abs(path[i]! - path[i - 1]!);
    if (left >= leg) {
      price = path[i]!;
      left -= leg;
    } else {
      price = path[i - 1]! + Math.sign(path[i]! - path[i - 1]!) * left;
      left = 0;
    }
    if (price > top) top = price;
    if (price < bottom) bottom = price;
  }
  const raw: Bar = { time: final.time, open, high: top, low: bottom, close: price };
  if (final.volume !== undefined && Number.isFinite(final.volume)) {
    const share = final.volume * t;
    raw.volume = Number.isInteger(final.volume) ? Math.floor(share) : share;
  }
  if (oi !== undefined) raw.oi = oi;
  return formingWithin(raw, final);
}
