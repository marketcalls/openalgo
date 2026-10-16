/**
 * "Nice number" tick generation for the price axis (ARCHITECTURE.md §5).
 * Produces round, human-friendly step sizes.
 */

/**
 * Round `x` to a "nice" value: 1, 2, 5 or 10 times a power of ten. The 2.5
 * rung the price axis also uses lives in `nextNiceStep`.
 */
export function niceNum(x: number, round: boolean): number {
  if (x <= 0) return 0;
  const exp = Math.floor(Math.log10(x));
  const f = x / Math.pow(10, exp);
  let nf: number;
  if (round) {
    if (f < 1.5) nf = 1;
    else if (f < 3) nf = 2;
    else if (f < 7) nf = 5;
    else nf = 10;
  } else {
    if (f <= 1) nf = 1;
    else if (f <= 2) nf = 2;
    else if (f <= 5) nf = 5;
    else nf = 10;
  }
  return nf * Math.pow(10, exp);
}

/**
 * The next value up the 1, 2, 2.5, 5, 10 nice ladder. The 2.5 rung matters:
 * without it a 15-point range clamps from step 2 (8 labels) straight to step 5
 * (3 labels), when 2.5 lands exactly on the six the caller asked for.
 */
function nextNiceStep(step: number): number {
  const exp = Math.floor(Math.log10(step));
  const f = step / Math.pow(10, exp);
  for (const rung of [1, 2, 2.5, 5]) {
    if (rung > f * (1 + 1e-9)) return rung * Math.pow(10, exp);
  }
  return 10 * Math.pow(10, exp);
}

/** How many aligned ticks `step` puts inside [min, max]. */
function tickCount(min: number, max: number, step: number): number {
  const start = Math.ceil(min / step) * step;
  const end = Math.floor(max / step) * step;
  return Math.round((end - start) / step) + 1;
}

/**
 * Generate up to ~`maxTicks` nicely-rounded tick values spanning [min, max].
 * Returns ascending values aligned to the chosen step (may sit slightly inside
 * the range). Returns a single midpoint when the range is degenerate.
 */
export function niceTicks(min: number, max: number, maxTicks = 6): number[] {
  if (!isFinite(min) || !isFinite(max) || max <= min) {
    return [Number.isFinite(min) ? min : 0];
  }
  const slots = Math.max(1, maxTicks - 1);
  // Derive the step from the *raw* span. Rounding the span up to a nice number
  // first and then dividing rounds twice (10.5 rounds to 20, then to a step of 5), which costs
  // roughly half the labels the caller asked for: a 10-point range on a 65000
  // instrument came out with three ticks instead of six.
  let step = niceNum((max - min) / slots, true);
  if (!(step > 0)) return [min];
  // `round: true` snaps to the *nearest* nice value, so it can land below the
  // requested density and yield more than `maxTicks` labels. Walk up the nice
  // ladder until the count fits; `maxTicks` is a ceiling, not a target.
  for (let guard = 0; guard < 20 && tickCount(min, max, step) > maxTicks; guard++) {
    step = nextNiceStep(step);
  }
  const start = Math.ceil(min / step) * step;
  const end = Math.floor(max / step) * step;
  const ticks: number[] = [];
  // Guard against floating drift producing a runaway loop.
  const count = Math.round((end - start) / step) + 1;
  for (let i = 0; i < count && i < 1000; i++) {
    const v = start + i * step;
    // Snap tiny floating error so labels read cleanly.
    ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
  }
  return ticks;
}

/** Decimal places implied by a price step / tick size (for label formatting). */
export function precisionForStep(step: number): number {
  if (step <= 0 || !isFinite(step)) return 2;
  if (step >= 1) return 0;
  return Math.min(8, Math.ceil(-Math.log10(step)));
}
