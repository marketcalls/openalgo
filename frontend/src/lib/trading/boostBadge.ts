/**
 * How a backend rank-movement event is shown, in one place.
 *
 * Two scripts already drifted from the engine by restating its rule, and this
 * table is the same hazard on the frontend: the TradeFinder panel and the boost
 * strikes panel must agree on what counts as a badge and what it looks like, or
 * a stock appears in one and not the other.
 */

export interface BadgeStyle {
  text: string
  className: string
}

/** Salient events worth a chip. CLIMBING/FALLING/NEW/NORMAL/ABSENT are absent
 * on purpose: the rank-delta arrow already covers small moves, and a symbol
 * that has left the list has no current event at all. */
export const MOVEMENT_BADGE: Record<string, BadgeStyle> = {
  EXTREME_JUMP: { text: 'JUMP', className: 'text-amber-500' },
  LARGE_JUMP: { text: 'JUMP', className: 'text-amber-400' },
  FAST_CLIMB: { text: 'FAST', className: 'text-emerald-500' },
  TOP5_ENTRY: { text: '→T5', className: 'text-emerald-500' },
  TOP10_ENTRY: { text: '→T10', className: 'text-emerald-500' },
  TOP20_ENTRY: { text: '→T20', className: 'text-emerald-400' },
  TOP5_RE_ENTRY: { text: '↻T5', className: 'text-emerald-500' },
  TOP10_RE_ENTRY: { text: '↻T10', className: 'text-emerald-500' },
  TOP20_RE_ENTRY: { text: '↻T20', className: 'text-emerald-400' },
  SUSTAINED_TOP5: { text: '◆T5', className: 'text-sky-400' },
  SUSTAINED_TOP10: { text: '◆T10', className: 'text-sky-400' },
  SUSTAINED_TOP20: { text: '◆T20', className: 'text-sky-500' },
  TOP5_EXIT: { text: 'T5×', className: 'text-red-500' },
  TOP10_EXIT: { text: 'T10×', className: 'text-red-500' },
  TOP20_EXIT: { text: 'T20×', className: 'text-red-500' },
  FAST_DROP: { text: 'DROP', className: 'text-red-500' },
  CLEAN_RUN_UP: { text: 'RUN↑', className: 'text-emerald-500' },
  CLEAN_RUN_DOWN: { text: 'RUN↓', className: 'text-red-500' },
}

export function badgeFor(event: string | undefined): BadgeStyle | undefined {
  return event ? MOVEMENT_BADGE[event] : undefined
}

/** A minute-of-day as a clock time: 574 reads as 09:34. */
export function minuteOfDay(min: number): string {
  return `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`
}
