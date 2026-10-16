/**
 * The shared level palette for the Fibonacci and Gann family.
 *
 * Every ladder tool (retracement, extension, channel, fan, time zone, the Gann
 * fan and box) strokes a list of ratios, and each ratio has a colour the eye
 * expects: 0.618 reads as one thing across every tool, not a different hue per
 * tool. Before this module each tool would have restated those colours, and
 * restated colours drift. This is the one statement; tools take their defaults
 * from it and hosts seed a newly added level from it.
 *
 * Pure: no DOM, no registry. Safe to import from a worker or a settings panel.
 */
import type { FibLevel } from './types';

/**
 * The levels a ladder strokes: the drawing's own, else the tool's default,
 * minus the ones switched off and any with a ratio that is not a number
 * (a hand-edited state file is the usual source). Every family that draws,
 * hit-tests or alerts on a ladder reads its levels through this.
 */
export function activeLevels(own: readonly FibLevel[] | undefined, fallback: readonly FibLevel[]): FibLevel[] {
  return (own ?? fallback).filter((l) => l.enabled !== false && Number.isFinite(l.ratio));
}

/**
 * The colour of a ratio that is an anchor rather than a level (0, 1, 2, 3 are
 * where the measured leg starts and ends, or whole multiples of it) and of any
 * ratio the convention does not name. Neutral on purpose: it is the reference
 * the coloured levels are read against.
 */
export const LEVEL_NEUTRAL = '#787b86';

/**
 * Conventional colours by ratio. Distinctness matters within the sets that
 * appear together (a retracement's 0.236 to 0.786, a Gann box's quarters, an
 * extension's 1.272 to 2.618), not across the whole table.
 */
const CONVENTIONAL: ReadonlyArray<readonly [number, string]> = [
  [0.236, '#f23645'],
  [0.25, '#7e57c2'],
  [0.382, '#ff9800'],
  [0.5, '#4caf50'],
  [0.618, '#089981'],
  [0.75, '#26c6da'],
  [0.786, '#00bcd4'],
  [1.272, '#2962ff'],
  [1.414, '#9c27b0'],
  [1.618, '#e91e63'],
  [2.618, '#ff5252'],
  [3.618, '#9575cd'],
  [4.236, '#64b5f6'],
];

/** Ratios arrive from JSON and arithmetic, so match with a tolerance, not `===`. */
const RATIO_EPS = 1e-6;

/**
 * The conventional colour for a Fibonacci ratio. Anchors (0, 1, 2, 3) and any
 * ratio without a convention come back {@link LEVEL_NEUTRAL}, so a host can call
 * this for every new level and always get a usable colour.
 */
export function levelColor(ratio: number): string {
  if (!Number.isFinite(ratio)) return LEVEL_NEUTRAL;
  for (const [r, color] of CONVENTIONAL) {
    if (Math.abs(r - ratio) <= RATIO_EPS) return color;
  }
  return LEVEL_NEUTRAL;
}

/**
 * A short sequence of colours that stay distinguishable side by side, for
 * tools whose levels are positions rather than ratios: the angles of a Gann
 * fan, the repeats of a cycle. Index `i` wraps, so any count is safe.
 */
export const CYCLE_PALETTE: readonly string[] = [
  '#2962ff', '#f23645', '#089981', '#ff9800',
  '#9c27b0', '#00bcd4', '#e91e63', '#4caf50',
];

/** The `i`th cycle colour. Wraps in both directions; a negative index is fine. */
export function cycleColor(i: number): string {
  const n = CYCLE_PALETTE.length;
  const k = Number.isFinite(i) ? Math.trunc(i) : 0;
  return CYCLE_PALETTE[((k % n) + n) % n]!; // in 0..n-1
}

/** `0.618` as `61.8%`: the text a level prints when it carries no label. */
export function formatRatio(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

/**
 * The label for a Gann angle stored as a price-per-time ratio: `1` is the 1x1,
 * `0.5` the 1x2, `2` the 2x1. Ratios that are not clean reciprocals fall back
 * to the ratio itself, which is still true, just less idiomatic.
 */
export function gannLabel(ratio: number): string {
  if (!Number.isFinite(ratio) || ratio <= 0) return String(ratio);
  if (ratio >= 1) return `${ratio}x1`;
  const inv = 1 / ratio;
  return Math.abs(inv - Math.round(inv)) <= RATIO_EPS ? `1x${Math.round(inv)}` : `${ratio}x1`;
}

function frozen(levels: FibLevel[]): readonly FibLevel[] {
  for (const l of levels) Object.freeze(l);
  return Object.freeze(levels);
}

/** A mutable copy of a default ladder, for a fresh drawing's own `style.levels`. */
export function cloneLevels(levels: readonly FibLevel[]): FibLevel[] {
  return levels.map((l) => ({ ...l }));
}

/** Retracement and extension: the classic ladder, coloured by convention. */
export const DEFAULT_FIB: readonly FibLevel[] = frozen(
  [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].map((ratio) => ({ ratio, color: levelColor(ratio) })),
);

/** Speed fan: rays at the fractions of the leg. No 0 ray, it would be flat. */
export const DEFAULT_FIB_FAN: readonly FibLevel[] = frozen(
  [0.236, 0.382, 0.5, 0.618, 0.786, 1].map((ratio) => ({ ratio, color: levelColor(ratio) })),
);

/** Gann box: quarters plus the golden pair, applied to both axes of the box. */
export const DEFAULT_GANN_BOX: readonly FibLevel[] = frozen(
  [0, 0.25, 0.382, 0.5, 0.618, 0.75, 1].map((ratio) => ({ ratio, color: levelColor(ratio) })),
);

/**
 * Gann fan: the classic angles as price-per-time ratios, 1x8 up to 8x1. These
 * are positions in a sequence rather than Fibonacci ratios, so they take the
 * cycle palette.
 */
export const DEFAULT_GANN_FAN: readonly FibLevel[] = frozen(
  [0.125, 0.25, 0.5, 1, 2, 4, 8].map((ratio, i) => ({ ratio, color: cycleColor(i), label: gannLabel(ratio) })),
);

/**
 * Time zones count bars along the Fibonacci sequence, so `ratio` here is a
 * multiple of the anchor leg, not a fraction of it. No colour is set: there is
 * no convention for "the 13 line", so every zone takes the drawing's own colour
 * until the user gives one its own.
 */
export const DEFAULT_FIB_TIME_ZONE: readonly FibLevel[] = frozen(
  [0, 1, 2, 3, 5, 8, 13, 21, 34, 55].map((ratio) => ({ ratio })),
);
