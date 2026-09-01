/**
 * The shared vocabulary of the terminal's two edge rails.
 *
 * DrawingRail sits on the left and RightRail on the right, and they are on
 * screen together. Two independent copies of "what a rail button looks like"
 * would survive exactly until the first restyle, after which the two edges of
 * the same workspace would quietly disagree. The metrics live here once.
 */

import { cn } from '@/lib/utils'

/** A rail button at rest: 32px square, quiet until hovered. */
export const RAIL_BTN =
  'flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-30'

/**
 * Layered onto RAIL_BTN when the tool is armed or the panel is open.
 *
 * Reported as not differentiated at all. It was applied correctly, but a 15%
 * tint of the accent behind a muted glyph is a shade of grey on a dark ground:
 * the armed tool and the ten resting ones beside it read the same at a glance,
 * which is the only distance this ever gets looked at. A quarter-strength fill,
 * a solid-enough border and the accent on the glyph itself carry it, and the
 * glyphs already stroke with currentColor so the last one costs nothing.
 */
export const RAIL_BTN_ON =
  'border-primary/70 bg-primary/25 text-primary hover:bg-primary/30 hover:text-primary'

/**
 * The stroke weight for a lucide glyph in a rail.
 *
 * DrawingRail's tool icons come from `drawTools`, which already draws at 1.5,
 * so lucide's default of 2 in the right rail put two different stroke weights
 * in identical 18px boxes on the same screen. DrawingRail's own hand-written
 * undo, redo and delete SVGs sit at 1.6 and are not covered by this.
 */
export const RAIL_ICON_STROKE = 1.5

/**
 * Hover label beside a rail button.
 *
 * The native `title` attribute waits about a second and cannot be styled; a
 * rail of identical glyphs needs its names to appear immediately. Rendered
 * inside the rail rather than portalled, so it still paints when a pane is in
 * the Fullscreen top layer.
 *
 * `side` is which way it opens. The right rail has to open left or the viewport
 * edge clips it.
 */
export function RailTip({
  text,
  chord,
  side = 'right',
}: {
  text: string
  chord?: string
  side?: 'left' | 'right'
}) {
  return (
    <span
      role="tooltip"
      className={cn(
        'pointer-events-none absolute top-1/2 z-50 -translate-y-1/2 whitespace-nowrap rounded border bg-popover px-2 py-1 text-[12px] text-popover-foreground opacity-0 shadow-md transition-opacity duration-75 group-hover:opacity-100',
        side === 'right' ? 'left-full ml-2' : 'right-full mr-2'
      )}
    >
      {text}
      {chord && <span className="ml-2 text-muted-foreground">{chord}</span>}
    </span>
  )
}
