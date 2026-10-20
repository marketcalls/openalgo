// Detect "the user has a stale frontend bundle open in their browser, and
// CI just rebuilt the dist with new chunk hashes" — the classic SPA failure
// after a deploy. The browser's cached index.html still references
// Historify-OLDHASH.js, but the server only has Historify-NEWHASH.js.
// Lazy import() rejects with a browser-specific error message; we recognise
// any of those and force-reload to fetch the fresh index.html.
//
// See marketcalls/openalgo#1393 for the bug report.

const CHUNK_ERROR_PATTERNS = [
  // Safari: "Importing a module script failed."
  /Importing a module script failed/i,
  // Chrome / Edge
  /Failed to fetch dynamically imported module/i,
  // Firefox
  /error loading dynamically imported module/i,
  // Webpack legacy / generic
  /ChunkLoadError/i,
  // Vite preload helper
  /Unable to preload CSS for/i,
  /Failed to load resource.*\.(?:js|mjs|css)/i,
]

const RELOAD_FLAG = 'openalgo:chunk-reload-attempted'

// How long a reload attempt suppresses the next one. A genuine stale-bundle
// reload fixes itself on the first try, so a second failure inside this window
// means reloading is not going to help - show the error instead of looping.
// Past the window the auto-recovery arms again, so a later deploy in the same
// tab session still self-heals.
const RELOAD_COOLDOWN_MS = 30_000

/** True iff the error message looks like a stale-chunk import failure. */
export function isChunkLoadError(message: string | undefined | null): boolean {
  if (!message) return false
  return CHUNK_ERROR_PATTERNS.some((p) => p.test(message))
}

/**
 * If the error looks like a stale-chunk failure, reload the page to pick up
 * the fresh index.html. Returns true if a reload was triggered (caller should
 * suppress further error UI, since the page is about to navigate).
 *
 * The stored timestamp bounds the retry: a second chunk failure within
 * RELOAD_COOLDOWN_MS does not reload again, so the user sees the real error
 * rather than a page that flashes "Loading new version…" forever.
 *
 * The timestamp is deliberately never cleared on mount. It used to be, from
 * main.tsx — but that ran on *every* page load, including the one the reload
 * itself produced, so the guard was wiped before it could ever apply. The app
 * shell always mounts fine; only the lazy route chunk fails, so the sequence
 * was reload -> mount -> clear -> route fails -> reload, without end. Letting
 * the timestamp age out instead keeps the guard honest while still re-arming
 * for a later deploy in the same tab.
 */
export function tryAutoReloadOnChunkError(message: string | undefined | null): boolean {
  if (!isChunkLoadError(message)) return false

  try {
    const previous = Number(sessionStorage.getItem(RELOAD_FLAG)) || 0
    if (previous && Date.now() - previous < RELOAD_COOLDOWN_MS) {
      // Reloading already failed to fix this. Fall through to the error UI;
      // the user can retry with the manual Reload button.
      return false
    }
    sessionStorage.setItem(RELOAD_FLAG, String(Date.now()))
  } catch {
    // sessionStorage unavailable (private browsing edge cases). Reload anyway;
    // worst case is one extra reload if the chunks are still missing, and the
    // error UI surfaces on the attempt after that.
  }

  // Hard reload — bypasses any in-memory bfcache state.
  window.location.reload()
  return true
}
