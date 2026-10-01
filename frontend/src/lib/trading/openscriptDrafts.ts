/**
 * Unsaved edits, kept per script until they are saved or thrown away.
 *
 * The panel holds one script's text at a time and is unmounted whenever the
 * trader opens another rail panel, so an edit that had not been saved used to
 * be lost twice over: choosing another script replaced it with that script's
 * saved text, and glancing at the watchlist closed the panel with it inside.
 * Neither step asked, and neither said anything had gone.
 *
 * **A draft rather than a warning, because a warning cannot be given in time.**
 * The panel is closed by the rail beside it, which knows nothing about editors,
 * and a switch of script is a menu choice a trader makes while thinking about
 * the other file. Asking "discard your changes?" at either moment stops work to
 * make somebody decide something they did not come to decide. Keeping the text
 * instead means nothing is lost and nothing has to be asked: the draft comes
 * back when the script is opened again, the status bar says it is unsaved, and
 * throwing it away is a separate, deliberate action.
 *
 * **Held in this page, and written through to this browser's storage.** The
 * page's copy is what makes a switch or a closed panel lossless even where
 * storage is refused (private mode, blocked site data, a full quota). Storage
 * is what carries a draft over a reload. It is written a moment after typing
 * stops rather than on every key, and `flushDrafts` writes whatever is still
 * waiting when the panel goes or the page is being left.
 *
 * **A draft remembers what it was typed over**, as a short fingerprint of the
 * saved text rather than a second copy of it. When the saved file has changed
 * underneath a draft (another tab saved it, or it was restored from a backup)
 * the panel can say so before the trader saves over that change without
 * knowing it was there.
 */

const PREFIX = 'oa-trading-script-draft:'

/** Stored names are read back into a URL, so they are held to the panel's own shape. */
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$/

/** How long after the last keystroke a draft is written to storage. */
export const WRITE_DELAY_MS = 400

export interface Draft {
  /** What the trader had typed. */
  readonly text: string
  /** A fingerprint of the saved text the draft was typed over. */
  readonly base: string
}

/** This page's copy, which is the one read first. */
const held = new Map<string, Draft>()
/** Scripts whose draft has changed since it was last written to storage. */
const waiting = new Set<string>()
let timer: ReturnType<typeof setTimeout> | null = null

/**
 * A short fingerprint of a text, to tell whether a saved file has changed.
 *
 * FNV-1a over the UTF-16 code units. It is a hint that the text moved, not a
 * proof that it did not, and a collision costs one missed notice.
 */
export function fingerprintOf(text: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `${text.length.toString(36)}.${hash.toString(36)}`
}

function store(file: string): void {
  const draft = held.get(file)
  try {
    if (draft === undefined) localStorage.removeItem(PREFIX + file)
    else localStorage.setItem(PREFIX + file, JSON.stringify(draft))
  } catch {
    // Storage refused. The page's copy still holds the draft until it closes,
    // which covers a switch of script and a closed panel; only a reload is lost.
  }
}

/** Writes every draft still waiting to storage, now. */
export function flushDrafts(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
  for (const file of waiting) store(file)
  waiting.clear()
}

/**
 * The draft kept for a script, or null when there is none.
 *
 * Validated rather than trusted, because storage is this browser's memory and
 * anything could be in it: a value that is not a draft reads as no draft.
 */
export function readDraft(file: string): Draft | null {
  if (!NAME.test(file)) return null
  const inPage = held.get(file)
  if (inPage !== undefined) return inPage
  try {
    const saved = localStorage.getItem(PREFIX + file)
    if (saved === null) return null
    const parsed: unknown = JSON.parse(saved)
    if (typeof parsed !== 'object' || parsed === null) return null
    const { text, base } = parsed as Record<string, unknown>
    if (typeof text !== 'string' || typeof base !== 'string') return null
    const draft = { text, base }
    held.set(file, draft)
    return draft
  } catch {
    return null
  }
}

/** Whether a script has a draft waiting, for the menu to mark it. */
export function hasDraft(file: string): boolean {
  return readDraft(file) !== null
}

/** Forgets a script's draft, for one that was saved, discarded or deleted. */
export function dropDraft(file: string): void {
  if (!NAME.test(file)) return
  held.delete(file)
  waiting.delete(file)
  store(file)
}

/**
 * Keeps what the trader has typed into a script, or forgets it once it matches
 * the saved text again.
 *
 * Called on every edit, so it only touches this page's copy straight away and
 * leaves storage to a timer.
 */
export function keepDraft(file: string, text: string, saved: string): void {
  if (!NAME.test(file)) return
  if (text === saved) {
    if (held.has(file) || waiting.has(file)) dropDraft(file)
    return
  }
  held.set(file, { text, base: fingerprintOf(saved) })
  waiting.add(file)
  if (timer === null) timer = setTimeout(flushDrafts, WRITE_DELAY_MS)
}

/** Clears this page's copy. For tests, which share one module between cases. */
export function forgetDraftsInPage(): void {
  if (timer !== null) clearTimeout(timer)
  timer = null
  held.clear()
  waiting.clear()
}
