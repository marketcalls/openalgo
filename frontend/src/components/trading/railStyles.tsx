/**
 * The shared vocabulary of the terminal's two edge rails. Their hover labels
 * are the terminal's one `Tip`, shared with the toolbar.
 *
 * DrawingRail sits on the left and RightRail on the right, and they are on
 * screen together. Two independent copies of "what a rail button looks like"
 * would survive exactly until the first restyle, after which the two edges of
 * the same workspace would quietly disagree. The metrics live here once.
 */

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
