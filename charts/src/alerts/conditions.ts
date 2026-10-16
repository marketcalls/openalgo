import type { AlertCondition } from './types';

export const CONDITIONS: readonly AlertCondition[] = [
  'crossing', 'crossingUp', 'crossingDown', 'greaterThan', 'lessThan', 'enteringRange', 'leavingRange',
];

export function numericMatch(condition: AlertCondition, previous: number | undefined, current: number,
  lower: number, upper: number | undefined, previousLower = lower, previousUpper = upper): boolean {
  if (!Number.isFinite(current)) return false;
  if (condition === 'greaterThan') return current > lower;
  if (condition === 'lessThan') return current < lower;
  if (previous === undefined || !Number.isFinite(previous)) return false;
  const up = previous <= previousLower && current > lower;
  const down = previous >= previousLower && current < lower;
  if (condition === 'crossing') return up || down;
  if (condition === 'crossingUp') return up;
  if (condition === 'crossingDown') return down;
  const wasInside = previous >= previousLower && previous <= previousUpper!;
  const isInside = current >= lower && current <= upper!;
  return condition === 'enteringRange' ? !wasInside && isInside : wasInside && !isInside;
}

/** Newly observed extrema prove contact without inventing an intrabar path order. */
export function touchMatch(condition: AlertCondition, previous: number, low: number, high: number,
  lower: number, upper: number | undefined, previousLower = lower, previousUpper = upper): number | undefined {
  if (![previous, low, high].every(Number.isFinite)) return undefined;
  const up = previous <= previousLower && high > lower;
  const down = previous >= previousLower && low < lower;
  switch (condition) {
    case 'crossing': return up || down ? lower : undefined;
    case 'crossingUp': return up ? lower : undefined;
    case 'crossingDown': return down ? lower : undefined;
    case 'greaterThan': return high > lower ? high : undefined;
    case 'lessThan': return low < lower ? low : undefined;
    case 'enteringRange':
      if (previous < previousLower && high >= lower) return lower;
      if (previous > previousUpper! && low <= upper!) return upper;
      return undefined;
    case 'leavingRange':
      if (previous < previousLower || previous > previousUpper!) return undefined;
      if (low < lower) return lower;
      return high > upper! ? upper : undefined;
    case 'matches': return undefined;
  }
}
