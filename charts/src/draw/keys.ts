/**
 * Keyboard editing for drawings, as a pure mapping from a key event to the
 * action it means. The engine installs no listener: only the host knows whether
 * the chart has focus, whether a dialog is open, or whether the user is typing
 * into a text box, so the host reads the event, asks this function, and calls
 * the matching `DrawingController` method itself.
 *
 * Modifiers must match exactly, the same rule `matchDrawingShortcut` applies:
 * a chord with an extra modifier belongs to the host or the browser, and an
 * editing action must never shadow it. `Meta` (Cmd) counts as `Ctrl`.
 */

/** The key-event fields the mapping reads. A DOM `KeyboardEvent` satisfies it. */
export interface DrawingKeyEvent {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

export interface DrawingKeyContext {
  /** At least one drawing is selected. */
  hasSelection: boolean;
  /**
   * A drawing is under the pointer without being selected. Copy, cut,
   * duplicate and delete act on it when nothing is selected; nudge does not,
   * because moving something the user has not picked reads as a glitch.
   */
  hasTarget: boolean;
  /** The user is typing (a text box is open). Every key is theirs. */
  editingText: boolean;
  /**
   * A tool is armed. Escape, Enter and Backspace then belong to placement
   * (cancel, finish, drop the last anchor) rather than to the selection.
   */
  placing?: boolean;
}

export type DrawingKeyAction =
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'copy' }
  | { type: 'cut' }
  | { type: 'paste' }
  | { type: 'duplicate' }
  | { type: 'delete' }
  /** Move the selection by a screen distance; `dx` right and `dy` down, in px. */
  | { type: 'nudge'; dx: number; dy: number }
  /** Placement, while a tool is armed: leave it, close the shape, drop the last anchor. */
  | { type: 'cancel' }
  | { type: 'finish' }
  | { type: 'popAnchor' };

/** How far an arrow key moves the selection, plain and with Shift. */
export const NUDGE_STEP_PX = 1;
export const NUDGE_STEP_SHIFT_PX = 10;

export function keyToDrawingAction(e: DrawingKeyEvent, ctx: DrawingKeyContext): DrawingKeyAction | null {
  if (ctx.editingText) return null;
  const key = e.key ?? '';
  if (key === '') return null;
  const mod = e.ctrlKey === true || e.metaKey === true;
  const shift = e.shiftKey === true;
  // Alt chords arm tools (`matchDrawingShortcut`); they never edit.
  if (e.altKey === true) return null;
  // Placement owns these three while a tool is armed: Backspace here drops
  // the last anchor and must never reach the delete branch below.
  if (ctx.placing === true && !mod && !shift) {
    if (key === 'Escape') return { type: 'cancel' };
    if (key === 'Enter') return { type: 'finish' };
    if (key === 'Backspace') return { type: 'popAnchor' };
  }
  const target = ctx.hasSelection || ctx.hasTarget;

  if (mod) {
    switch (key.toLowerCase()) {
      case 'z': return shift ? { type: 'redo' } : { type: 'undo' };
      case 'y': return shift ? null : { type: 'redo' };
      case 'c': return !shift && target ? { type: 'copy' } : null;
      case 'x': return !shift && target ? { type: 'cut' } : null;
      case 'v': return shift ? null : { type: 'paste' };
      case 'd': return !shift && target ? { type: 'duplicate' } : null;
      default: return null;
    }
  }

  if (key === 'Delete' || key === 'Backspace') {
    return !shift && target ? { type: 'delete' } : null;
  }

  if (!ctx.hasSelection) return null;
  const step = shift ? NUDGE_STEP_SHIFT_PX : NUDGE_STEP_PX;
  switch (key) {
    case 'ArrowLeft': return { type: 'nudge', dx: -step, dy: 0 };
    case 'ArrowRight': return { type: 'nudge', dx: step, dy: 0 };
    case 'ArrowUp': return { type: 'nudge', dx: 0, dy: -step };
    case 'ArrowDown': return { type: 'nudge', dx: 0, dy: step };
    default: return null;
  }
}
