/**
 * The preset range a pane was last placed on (1D, 5D, 1M ...), as the pane
 * keeps it in its own preferences beside its symbol and interval.
 *
 * Stored as a small versioned record so a later shape can be told apart, and
 * read leniently: a pane saved before ranges existed, or anything this build
 * cannot read, simply has no range, which is how every chart opened before.
 * The interval is kept with it because a range holds only while the pane is
 * still on the interval the range chose.
 */
export interface RangeChoice {
  id: string
  interval: string
}

const VERSION = 1

export function parseRangeChoice(raw: string | null): RangeChoice | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as { v?: unknown; id?: unknown; interval?: unknown } | null
    if (
      value?.v !== VERSION ||
      typeof value.id !== 'string' ||
      !/^[A-Za-z0-9]{1,8}$/.test(value.id) ||
      typeof value.interval !== 'string' ||
      !value.interval
    )
      return null
    return { id: value.id, interval: value.interval }
  } catch {
    return null
  }
}

/** The stored form; an empty string clears the choice. */
export function serializeRangeChoice(choice: RangeChoice | null): string {
  return choice ? JSON.stringify({ v: VERSION, id: choice.id, interval: choice.interval }) : ''
}
