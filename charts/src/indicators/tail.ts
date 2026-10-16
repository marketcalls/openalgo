/**
 * The incremental path (`calcTail`) for the built-in studies, and the one rule
 * every one of them keeps: a tail spliced onto the previous result reads, value
 * for value, what a full `calc` of the same bars returns. Not close to it: the
 * same numbers, NaN and signed zero included, because a live chart shows the
 * spliced answer and a reload shows the full one, and a user comparing the two
 * must not find a difference.
 *
 * Two shapes cover the built-ins.
 *
 * A study whose value at a bar reads a bounded run of bars before it (a moving
 * window) runs its own `calc` over just that run. No second copy of the formula
 * exists to drift from the first.
 *
 * A study that carries state from bar to bar (an exponential average, a running
 * total, a stop and reverse) resumes from a checkpoint: the state after the bar
 * before the tail. The previous tail leaves it; after a full `calc`, which is
 * what runs on a load, a history change or a settings change, the first tail
 * rebuilds it once by walking the history from bar 0. Every later tick costs a
 * step or two.
 *
 * A variant of the second places a value on a bar only once later bars confirm
 * it (the ZigZag in ./swings). It resumes its walk from the same checkpoint and,
 * in place of the check below, compares the few earlier bars that walk can
 * still rewrite with what the runtime holds.
 *
 * Either way the tail also recomputes the bar before it and compares that with
 * the result the runtime still holds. A disagreement means the held result is
 * not this study's own (a descriptor that copied a built-in's tail and reshaped
 * its output) or the history moved under it, and the tail declines so the full
 * `calc` runs. A study that keeps disagreeing stops being offered the tail.
 *
 * The tail is not enumerable on the descriptor, so `{ ...SMA, calc }` does not
 * carry it. A spread that adds a column, blanks the forming bar or passes other
 * settings to the built-in would otherwise have its own `calc` skipped on every
 * tick, and neither check above sees all of those. Such a descriptor keeps the
 * full `calc` it had before the built-ins had tails; copying `calcTail` across
 * is an explicit choice.
 */
import type { Bar, IndicatorDescriptor, IndicatorStore, IndicatorValues, IndicatorSettings } from 'openalgo-charts';

type Calc = IndicatorDescriptor['calc'];
export type Tail = NonNullable<IndicatorDescriptor['calcTail']>;
export type Cell = number | null;

/** The state after bar `index`, and the outputs that bar produced. */
interface Checkpoint { key: string; index: number; time: number; state: unknown; row: Cell[] }

/** Which full `calc` last ran on an instance's store, and where its tail stands. */
interface Claim { owner: Calc; misses: number; at?: Checkpoint }

// Keyed by the store, which the runtime keeps for the instance's lifetime, so
// nothing is written into the store itself and a descriptor that reads its own
// keys there never meets these.
const claims = new WeakMap<object, Claim>();

/** Disagreements in a row before the tail stops being tried for an instance. */
const MISSES = 3;

/** A finite value as a result cell, anything else as the gap `nulls` would make it. */
export const cell = (v: number): Cell => (Number.isFinite(v) ? v : null);

/** A window length the tails accept: the kernels' fast paths need a positive safe integer. */
export const whole = (v: number): boolean => Number.isSafeInteger(v) && v > 0;

/**
 * Wrap a built-in's `calc` so that it records, on the store it is handed, that
 * it ran. The tail resumes only from its own study's full result: a descriptor
 * that copies a built-in's tail and supplies a different `calc` never sets the
 * mark, and the copied tail declines.
 */
function owned(calc: Calc): Calc {
  return (bars, settings, store, ctx) => {
    if (typeof store === 'object' && store !== null) {
      const prior = claims.get(store);
      claims.set(store, { owner: calc, misses: prior?.owner === calc ? prior.misses : 0 });
    }
    return calc(bars, settings, store, ctx);
  };
}

/**
 * A tail that also declines when the held result has a column it does not
 * write. The runtime keeps only the columns a tail returns, so splicing would
 * drop that column from the plot. Such a column can only come from another
 * `calc`, which will write it again next time, so the tail stops for good.
 */
function keyed(tail: Tail): Tail {
  return (bars, settings, from, previous, store, ctx) => {
    const out = tail(bars, settings, from, previous, store, ctx);
    if (out === null) return null;
    for (const key of Object.keys(previous)) {
      if (!Object.prototype.hasOwnProperty.call(out, key)) {
        const claim = typeof store === 'object' && store !== null ? claims.get(store) : undefined;
        if (claim !== undefined) claim.misses = MISSES;
        return null;
      }
    }
    return out;
  };
}

/**
 * A built-in with its tail: its `calc` marks the store, and `tail(calc)` resumes
 * from that result. The tail goes on as a property a spread does not copy.
 */
export function withTail(descriptor: IndicatorDescriptor, tail: (calc: Calc) => Tail): IndicatorDescriptor {
  const out: IndicatorDescriptor = { ...descriptor, calc: owned(descriptor.calc) };
  Object.defineProperty(out, 'calcTail', {
    value: keyed(tail(descriptor.calc)), enumerable: false, writable: true, configurable: true,
  });
  return out;
}

/** The claim a tail may continue from, if its own `calc` made it. */
export function claimOf(store: IndicatorStore, owner: Calc, bars: readonly Bar[], from: number): Claim | undefined {
  if (typeof store !== 'object' || store === null || !Number.isSafeInteger(from) || from < 0 || from >= bars.length) {
    return undefined;
  }
  const claim = claims.get(store);
  return claim !== undefined && claim.owner === owner && claim.misses < MISSES ? claim : undefined;
}

/** Count a disagreement and decline. */
function miss(claim: Claim): null {
  claim.misses++;
  return null;
}

/** A deep copy of plain state: numbers, flags, arrays and records of them. */
function copy<T>(value: T): T {
  if (Array.isArray(value)) return value.map(copy) as T;
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value)) out[key] = copy((value as Record<string, unknown>)[key]);
    return out as T;
  }
  return value;
}

/** Whether bar `from - 1`'s outputs, `row` in `keys` order, are what the runtime holds. */
function agrees(previous: IndicatorValues, keys: readonly string[], row: readonly Cell[], from: number): boolean {
  if (from === 0) return true;
  for (let k = 0; k < keys.length; k++) {
    const held = previous[keys[k]!];
    if (held === undefined || held.length < from || !Object.is(held[from - 1] ?? null, row[k])) return false;
  }
  return true;
}

/**
 * The checkpoint a tail from `from` resumes, when the last tail left it
 * exactly there. `from` has passed `claimOf`, so it indexes a bar, and so does
 * the one before it when it is above zero.
 */
export function resumable(claim: Claim, key: string, bars: readonly Bar[], from: number): Checkpoint | undefined {
  const at = claim.at;
  return at !== undefined && at.key === key && at.index === from - 1 &&
    (from === 0 || at.time === bars[from - 1]!.time) ? at : undefined;
}

/**
 * Settle a result computed over `bars.slice(from - at)`: check its value at the
 * bar before the tail against the held result, then hand back `[from, n)`.
 */
export function settle(claim: Claim, part: IndicatorValues, at: number, previous: IndicatorValues, from: number): IndicatorValues | null {
  const out: Record<string, Cell[]> = {};
  for (const key of Object.keys(part)) {
    const col = part[key]!;
    if (from > 0) {
      const held = previous[key];
      if (held === undefined || held.length < from || !Object.is(held[from - 1] ?? null, col[at - 1] ?? null)) return miss(claim);
    }
    out[key] = col.slice(at) as Cell[];
  }
  claim.misses = 0;
  return out;
}

/**
 * The tail of a study whose value at a bar reads only the `lookback` bars
 * before it: its own `calc` over the run that covers the tail and the bar
 * before it. `lookback` returns null for settings the tail does not cover.
 */
export function windowTail(calc: Calc, lookback: (s: Readonly<IndicatorSettings>) => number | null): Tail {
  return (bars, settings, from, previous, store, ctx) => {
    const claim = claimOf(store, calc, bars, from);
    const back = lookback(settings);
    if (claim === undefined || back === null) return null;
    const start = Math.max(0, from - 1 - back);
    return settle(claim, calc(start === 0 ? bars : bars.slice(start), settings, store, ctx), from - start, previous, from);
  };
}

/** A study as a state machine over bars, for `machineTail`. */
export interface Machine<S> {
  /** Output keys, in the order `step` writes them into its row. */
  keys: readonly string[];
  /** The state before bar 0. */
  start(): S;
  /**
   * Advance over bar `i`, writing that bar's outputs into `row`. `i` always
   * indexes a bar: `machineTail` walks its bars, and `stepAll` is given their
   * count.
   */
  step(state: S, i: number, row: Cell[]): void;
  /**
   * Called once the state stands at the bar before the tail. False declines
   * the tail without counting a disagreement: the bars ahead would change what
   * the held result says about the bars behind.
   */
  ready?(state: S): boolean;
}

/**
 * The tail of a stateful study: resume at the bar before `from`, from the last
 * checkpoint or from bar 0, and step through `[from, n)`. The state after bar
 * `n - 2` is kept for the next call, which starts at the bar after it: the
 * last bar is the one a tick replaces.
 */
export function machineTail<S>(
  owner: Calc, key: string, machine: Machine<S>,
  bars: readonly Bar[], from: number, previous: IndicatorValues, store: IndicatorStore,
): IndicatorValues | null {
  const claim = claimOf(store, owner, bars, from);
  if (claim === undefined) return null;
  const at = resumable(claim, key, bars, from);
  let state: S;
  let row: Cell[];
  if (at !== undefined) {
    state = copy(at.state as S);
    row = at.row.slice();
  } else {
    state = machine.start();
    row = machine.keys.map(() => null);
    for (let i = 0; i < from; i++) machine.step(state, i, row);
  }
  if (!agrees(previous, machine.keys, row, from)) return miss(claim);
  if (machine.ready?.(state) === false) return null;
  const n = bars.length;
  const cols = machine.keys.map(() => new Array<Cell>(n - from));
  // `row` and `cols` hold one entry per key, and `i` indexes a bar.
  for (let i = from; i < n; i++) {
    if (i === n - 1) claim.at = { key, index: i - 1, time: i > 0 ? bars[i - 1]!.time : NaN, state: copy(state), row: row.slice() };
    machine.step(state, i, row);
    for (let k = 0; k < cols.length; k++) cols[k]![i - from] = row[k] as Cell;
  }
  claim.misses = 0;
  const out: Record<string, Cell[]> = {};
  machine.keys.forEach((k, j) => { out[k] = cols[j]!; });
  return out;
}

/**
 * The full result of a study written only as a machine: every bar stepped from
 * bar 0. Its `calc` and its tail then walk one piece of arithmetic, so the two
 * cannot drift apart the way a batch kernel and its stepper copy can.
 */
export function stepAll<S>(machine: Machine<S>, n: number): IndicatorValues {
  const state = machine.start();
  const row: Cell[] = machine.keys.map(() => null);
  const cols = machine.keys.map(() => new Array<Cell>(n));
  // As in `machineTail`, `row` and `cols` hold one entry per key.
  for (let i = 0; i < n; i++) {
    machine.step(state, i, row);
    for (let k = 0; k < cols.length; k++) cols[k]![i] = row[k] as Cell;
  }
  const out: Record<string, Cell[]> = {};
  machine.keys.forEach((k, j) => { out[k] = cols[j]!; });
  return out;
}
