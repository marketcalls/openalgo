/**
 * Roving focus along one row of controls: the arithmetic every toolbar, tab
 * list and menu of the widget repeats, so the keys mean the same everywhere.
 * Each caller keeps its own side effects (focusing, activating, claiming the
 * key), which differ on purpose: a tab list shows its tab as the focus
 * lands, a toolbar only focuses.
 */

/**
 * Where `key` moves the focus from item `at` of `count`, or -1 when it moves
 * nothing. `keys` are the row's back and forward arrows, which wrap; Home and
 * End go to the ends. From no item (`at` -1) nothing moves, unless
 * `fromNone`: then forward starts at the first item and back at the last.
 */
export function rovingIndex(key: string, at: number, count: number, keys: readonly [back: string, forward: string], fromNone = false): number {
  if (count === 0 || (at < 0 && !fromNone)) return -1;
  if (key === keys[1]) return (at + 1) % count;
  if (key === keys[0]) return at < 0 ? count - 1 : (at - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return -1;
}
