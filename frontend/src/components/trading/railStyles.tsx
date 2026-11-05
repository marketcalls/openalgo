/**
 * The shared vocabulary of the terminal's two edge rails. Their hover labels
 * are the terminal's one `Tip`, shared with the toolbar.
 *
 * DrawingRail sits on the left and RightRail on the right, and they are on
 * screen together. Two independent copies of "what a rail button looks like"
 * would survive exactly until the first restyle, after which the two edges of
 * the same workspace would quietly disagree. The metrics live here once, and
 * the look itself in `.oa-rail` in index.css, which follows the engine's
 * reference host: 32 by 30 buttons, quiet at rest, a raised surface under the
 * pointer, and a soft accent fill for the selected one.
 */

/** A rail button. Its states come from the stylesheet. */
export const RAIL_BTN = 'oa-rail__btn'

/**
 * Layered onto RAIL_BTN when a panel is open or a tool is armed. A button
 * that carries `aria-pressed` gets the same look from the attribute, so it
 * needs no class.
 *
 * Reported once as not differentiated at all: a faint tint behind a muted
 * glyph is a shade of grey on a dark ground. The accent on the glyph itself
 * is what carries it, and in the analyzer the violet edge as well.
 */
export const RAIL_BTN_ON = 'is-on'

/** The right rail's glyph box: the 16px the chrome set is drawn for. */
export const RAIL_GLYPH_PX = 16
