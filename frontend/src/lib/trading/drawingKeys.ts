/**
 * Which keystrokes the chart may read as drawing commands.
 *
 * The rail listens on the window, because a canvas cannot take focus and the
 * gesture is "select a drawing, press the key". That makes every key on the
 * page a candidate, so the rule for refusing one has to be strict: a key typed
 * into a field, pressed inside a dialog or the order ticket, or pressed while
 * any menu or dialog is open belongs to that surface, never to the chart.
 */

/** Anything a trader types into. */
const TYPING =
  'input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="textbox"]'

/** Surfaces that own their keys while focus is inside them. */
const SURFACE = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]'

/**
 * Surfaces that own the keyboard while they are open, wherever focus is. The
 * same list the page's Escape handler yields to, plus the pane's own lightweight
 * dialogs (indicator settings, the order ticket), which publish themselves
 * through `data-trading-dialog-open`.
 */
const OPEN_SURFACE =
  '[data-trading-dialog-open="true"],' +
  '[data-state="open"][role="dialog"],' +
  '[role="alertdialog"],' +
  '[data-state="open"][data-slot="popover-content"],' +
  '[data-state="open"][role="menu"],' +
  '[data-state="open"][role="listbox"]'

/** Whether a key event may be read as a chart command at all. */
export function chartMayTakeKey(e: Pick<KeyboardEvent, 'target'>): boolean {
  const target = e.target as (Element & { isContentEditable?: boolean }) | null
  // `closest` is called defensively: a keystroke with nothing focused is
  // delivered to the document, which has no `closest`.
  if (target?.isContentEditable || target?.closest?.(`${TYPING}, ${SURFACE}`)) return false
  const doc = target?.ownerDocument ?? (typeof document === 'undefined' ? null : document)
  return !doc?.querySelector(OPEN_SURFACE)
}

/**
 * Whether the page has text selected. Copy and cut then belong to the text:
 * a trader who highlighted an order id and pressed Ctrl+C must get the id, not
 * the trend line still selected on the chart behind it.
 */
export function pageHasTextSelection(doc: Document = document): boolean {
  const selection = doc.getSelection?.()
  return !!selection && !selection.isCollapsed && selection.toString().trim() !== ''
}

/** The modifier a shortcut is written with on this machine. */
export const MOD_KEY: 'Cmd' | 'Ctrl' =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')
    ? 'Cmd'
    : 'Ctrl'
