/**
 * A deterministic, seeded tape for the order flow page. Every footprint on the
 * page is aggregated from these prints, so the examples can be compared with
 * one another and each load shows the same picture.
 *
 * The tape is scripted rather than random-walked: each one-minute bar follows a
 * path of price waypoints with its own buying and selling pressure, so the
 * structures the examples explain (stacked imbalances, a row the price jumped
 * over, absorption at a high, a big bid near a low, a shared point of control,
 * a delta flip and an up bar with negative delta) are all on the tape on
 * purpose instead of by luck. All prices and sizes are simulated.
 */

/** One print with its aggressor side: `ask` lifted the offer, `bid` hit the bid. */
export interface OrderFlowPrint {
  time: number;
  price: number;
  qty: number;
  side: 'bid' | 'ask';
}

/** An OHLCV bar for the market and volume profile examples. */
export interface ProfileBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** One-point ticks around a synthetic index near 24,000. */
export const OF_TICK = 1;
export const OF_BASE = 24000;
export const OF_BAR_SECONDS = 60;
/** 09:15 in India (03:45 UTC) on a fixed day, so the session letters start at A. */
export const OF_START = Date.UTC(2026, 8, 9, 3, 45) / 1000;
/** Bars of history every static footprint example loads. */
export const OF_HISTORY_BARS = 14;
/** Quantity units per lot in the lot display example. */
export const OF_LOT = 25;

interface BarScript {
  /** Price waypoints as ticks from the base: open, then each turn, then close. */
  path: number[];
  /** Ticks per move for each segment; 2 leaves every other row untraded. */
  steps?: number[];
  /** Chance a print is a buy while the price is rising, and while it is falling. */
  buyUp: number;
  buyDown: number;
  /** Prints at each level the path passes. */
  dwell: number;
  /** A large resting order traded at one level. */
  big?: { at: number; side: 'bid' | 'ask'; lots: number };
  /** Levels where both sides trade heavily against each other. */
  absorb?: { at: number[]; lots: number };
  /** A level the bar keeps coming back to, which becomes its point of control. */
  node?: { at: number; lots: number };
}

// The order matters: two selling bars come before the bar that flips delta, two
// bars share a point of control, and the zones that form early are revisited
// by later bars so the live example has touches to report.
const SCRIPTS: readonly BarScript[] = [
  { path: [0, 4, -3, 2], buyUp: 0.6, buyDown: 0.4, dwell: 3 },
  { path: [2, -1, 9], steps: [1, 2], buyUp: 0.86, buyDown: 0.35, dwell: 3 },
  { path: [9, 7, 15, 13], buyUp: 0.84, buyDown: 0.45, dwell: 3 },
  { path: [13, 16, 12, 14], buyUp: 0.55, buyDown: 0.45, dwell: 3, absorb: { at: [15, 16], lots: 34 } },
  { path: [14, 15, 8, 10], buyUp: 0.4, buyDown: 0.22, dwell: 3 },
  { path: [10, 11, 4, 6], buyUp: 0.42, buyDown: 0.2, dwell: 3, big: { at: 5, side: 'bid', lots: 150 } },
  { path: [6, 4, 12, 11], buyUp: 0.84, buyDown: 0.45, dwell: 3 },
  { path: [11, 14, 9, 12], buyUp: 0.58, buyDown: 0.42, dwell: 3, node: { at: 12, lots: 22 } },
  { path: [12, 15, 10, 12], buyUp: 0.56, buyDown: 0.44, dwell: 3, node: { at: 12, lots: 24 } },
  { path: [12, 10, 17, 16], buyUp: 0.3, buyDown: 0.18, dwell: 3 },
  { path: [16, 17, 5, 7], steps: [1, 2, 1], buyUp: 0.55, buyDown: 0.12, dwell: 3 },
  { path: [7, 8, 1, 3], buyUp: 0.4, buyDown: 0.2, dwell: 3 },
  { path: [3, 7, 0, 5], buyUp: 0.62, buyDown: 0.4, dwell: 3 },
  { path: [5, 4, 11, 10], buyUp: 0.8, buyDown: 0.42, dwell: 3 },
];

/** xorshift32: small, fast and the same on every engine. */
function generator(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13; state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5; state >>>= 0;
    return state / 4294967296;
  };
}

/**
 * `bars` one-minute bars of prints. Bars past the scripted ones repeat the
 * scripts on the same prices, which is what brings the price back into zones
 * the earlier bars left behind.
 */
export function orderFlowTape(bars = OF_HISTORY_BARS, seed = 20261014): OrderFlowPrint[] {
  const random = generator(seed);
  // Mostly small prints with an occasional large one, so a trade size filter
  // has something to remove and something to keep.
  const lots = (scale = 1) => {
    const small = 1 + Math.floor(random() * random() * 9);
    return Math.max(1, Math.round((random() < 0.07 ? 12 + random() * 26 : small) * scale));
  };
  const out: OrderFlowPrint[] = [];
  for (let b = 0; b < bars; b++) {
    const script = SCRIPTS[b % SCRIPTS.length]!;
    const prints: Omit<OrderFlowPrint, 'time'>[] = [];
    const at = (offset: number) => OF_BASE + offset * OF_TICK;
    const push = (offset: number, side: 'bid' | 'ask', qty: number) => prints.push({ price: at(offset), qty, side });
    for (let s = 0; s < script.path.length - 1; s++) {
      const from = script.path[s]!, to = script.path[s + 1]!;
      const step = (script.steps?.[s] ?? 1) * Math.sign(to - from);
      const buy = to > from ? script.buyUp : script.buyDown;
      for (let level = from; step > 0 ? level <= to : level >= to; level += step) {
        // The first segment opens on its first level; later ones start where the last ended.
        if (s > 0 && level === from) continue;
        for (let k = 0; k < script.dwell; k++) push(level, random() < buy ? 'ask' : 'bid', lots());
        if (script.node && level === script.node.at) {
          push(level, 'ask', script.node.lots);
          push(level, 'bid', Math.round(script.node.lots * 0.9));
        }
        if (script.absorb && script.absorb.at.includes(level)) {
          push(level, 'ask', script.absorb.lots);
          push(level, 'bid', script.absorb.lots + 4);
        }
        if (script.big && level === script.big.at) push(level, script.big.side, script.big.lots);
      }
    }
    const start = OF_START + b * OF_BAR_SECONDS;
    // Spread the bar's prints over its minute, in order, so every print lands inside it.
    prints.forEach((print, i) => out.push({ ...print, time: start + Math.floor(i * (OF_BAR_SECONDS - 1) / prints.length) }));
  }
  return out;
}

/** The prints with every quantity in raw units of `lot`, as a feed that reports shares would send them. */
export function inQuantityUnits(prints: readonly OrderFlowPrint[], lot = OF_LOT): OrderFlowPrint[] {
  return prints.map(print => ({ ...print, qty: print.qty * lot }));
}

/**
 * Five-minute bars for `sessions` days of 09:15 to 15:30 in India: a walk that
 * is pulled back toward each day's centre so the profiles build a body and
 * not a ramp, the same shape the full-size profile demo uses.
 */
export function profileSessions(sessions = 3, seed = 42): ProfileBar[] {
  const random = generator(seed);
  const centres = [70, 25, 50, 10, 40];
  const out: ProfileBar[] = [];
  for (let day = 0; day < sessions; day++) {
    const open = Date.UTC(2026, 8, 7 + day, 3, 45) / 1000;
    const centre = OF_BASE + centres[day % centres.length]!;
    let price = centre, drift = 0;
    for (let i = 0; i < 75; i++) {
      drift = Math.max(-3, Math.min(3, drift + (random() - 0.5) * 1.4));
      drift -= (price - centre) * 0.012;
      const o = price;
      const c = o + drift + (random() - 0.5) * 7;
      const h = Math.max(o, c) + random() * 6;
      const l = Math.min(o, c) - random() * 6;
      price = c;
      const round = (value: number) => Math.round(value * 20) / 20;
      out.push({ time: open + i * 300, open: round(o), high: round(h), low: round(l), close: round(c),
        volume: Math.round(2000 + random() ** 2 * 26000) });
    }
  }
  return out;
}
