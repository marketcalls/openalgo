/**
 * What an edit changed, read off two versions of a drawing: the one anchor a
 * points patch moved, and a history step's change laid over the drawing as
 * it stands now. Pure, and kept apart from the controller so it can grow
 * without the controller growing with it.
 */
import type { DrawingPoint } from './types';

/**
 * The index of the one anchor that differs between two sets, or null when
 * none or several do. What a tool's constraint is told a points patch moved.
 */
export function changedAnchor(prev: readonly DrawingPoint[], next: readonly DrawingPoint[]): number | null {
  if (prev.length !== next.length) return null;
  let found: number | null = null;
  for (let i = 0; i < next.length; i++) {
    if (prev[i]!.time === next[i]!.time && prev[i]!.price === next[i]!.price) continue; // equal lengths
    if (found !== null) return null;
    found = i;
  }
  return found;
}

/**
 * `current` with only what differs between `before` and `after` applied, key
 * by key and into nested records. A history step is replayed this way rather
 * than by putting `after` back whole, so a field it never touched keeps what
 * happened to it since: a later edit made on a linked chart, say.
 */
export function historyPatch(current: unknown, before: unknown, after: unknown): unknown {
  if (JSON.stringify(before) === JSON.stringify(after)) return current;
  if (before === null || after === null || typeof before !== 'object' || typeof after !== 'object'
    || Array.isArray(before) || Array.isArray(after)) return after;
  const left = before as Record<string, unknown>;
  const right = after as Record<string, unknown>;
  const result = { ...(current as Record<string, unknown> | undefined) };
  for (const key of new Set([...Object.keys(left), ...Object.keys(right)])) {
    if (JSON.stringify(left[key]) === JSON.stringify(right[key])) continue;
    if (!(key in right)) delete result[key];
    else result[key] = historyPatch(result[key], left[key], right[key]);
  }
  return result;
}
