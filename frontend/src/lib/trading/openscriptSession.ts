/**
 * Which script the panel was last on, and which ones before that.
 *
 * The panel is unmounted whenever another panel is up, so without this it
 * forgets everything the moment you glance at the watchlist. Coming back to an
 * empty editor and a list to hunt through is the small friction that stops
 * people writing studies: the file you were editing thirty seconds ago is
 * almost always the file you want.
 *
 * Recents rather than a full list in the panel, because the list was costing a
 * quarter of the panel's height to show scripts nobody was looking at. Three,
 * because that is how many fit in a menu above the rest without a scroll and
 * how many a person actually moves between while working on one thing.
 *
 * Everything here tolerates storage being unavailable. A browser in private
 * mode, with site data blocked, or simply out of quota throws on access, and a
 * panel that will not open because it could not remember a file name is a far
 * worse failure than one that opens on nothing.
 */

const LAST_KEY = 'oa-trading-script-open'
const RECENT_KEY = 'oa-trading-script-recent'

/** How many recent scripts the menu offers above the rest. */
export const RECENT_LIMIT = 3

/** Stored names are read back into a URL, so they are held to the same shape. */
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.oscript$/

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Nothing to do and nothing worth saying: the panel works without this.
  }
}

/**
 * The script the panel was last on, if it still looks like a script name.
 *
 * Validated rather than trusted. What comes back is whatever is in this
 * browser's storage, which the panel turns into a request for a file, and a
 * name that would not pass the panel's own rule must not pass here either.
 */
export function readLastOpened(): string | null {
  const saved = read(LAST_KEY)
  return saved !== null && NAME.test(saved) ? saved : null
}

export function writeLastOpened(file: string | null): void {
  write(LAST_KEY, file)
}

/** The recent scripts, newest first, filtered to names that are still valid. */
export function readRecents(): string[] {
  const saved = read(RECENT_KEY)
  if (saved === null) return []
  try {
    const parsed: unknown = JSON.parse(saved)
    if (!Array.isArray(parsed)) return []
    const out: string[] = []
    for (const entry of parsed) {
      if (typeof entry === 'string' && NAME.test(entry) && !out.includes(entry)) out.push(entry)
      if (out.length === RECENT_LIMIT) break
    }
    return out
  } catch {
    return []
  }
}

/**
 * Records that a script was opened, and answers with the new recents.
 *
 * Returned rather than only written, so the caller renders from the same list
 * that was stored instead of reading it back and hoping the two agree.
 */
export function noteOpened(file: string, previous: readonly string[] = readRecents()): string[] {
  if (!NAME.test(file)) return [...previous]
  const next = [file, ...previous.filter((one) => one !== file)].slice(0, RECENT_LIMIT)
  write(RECENT_KEY, JSON.stringify(next))
  writeLastOpened(file)
  return next
}

/**
 * Drops a script from both, for one that has been deleted.
 *
 * Without this the menu keeps offering a file that is gone, and reopening the
 * panel restores it as the last one open: the editor then asks the server for
 * a script that no longer exists and shows the failure as though the trader
 * had done something wrong.
 */
export function forgetScript(file: string, previous: readonly string[] = readRecents()): string[] {
  const next = previous.filter((one) => one !== file)
  write(RECENT_KEY, JSON.stringify(next))
  if (readLastOpened() === file) writeLastOpened(null)
  return next
}
