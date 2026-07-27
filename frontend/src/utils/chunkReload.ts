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

/** True iff the error message looks like a stale-chunk import failure. */
export function isChunkLoadError(message: string | undefined | null): boolean {
  if (!message) return false
  return CHUNK_ERROR_PATTERNS.some((p) => p.test(message))
}

/**
 * If the error looks like a stale-chunk failure, force-reload the page
 * once per browser tab session to pick up the fresh index.html. Returns
 * true if a reload was triggered (caller should suppress further error
 * UI rendering, since the page is about to navigate).
 *
 * The session-storage flag prevents an infinite reload loop in the rare
 * case where the new index.html *also* fails to import a chunk (server
 * misconfiguration, partial deploy) — after one attempt, fall through
 * to the normal error UI so the user can see what's wrong.
 */
export function tryAutoReloadOnChunkError(message: string | undefined | null): boolean {
  if (!isChunkLoadError(message)) return false

  try {
    if (sessionStorage.getItem(RELOAD_FLAG)) {
      // Already tried once this session — surface the real error instead
      // of looping. User clicks the manual Reload button if they want
      // to retry.
      return false
    }
    sessionStorage.setItem(RELOAD_FLAG, String(Date.now()))
  } catch {
    // sessionStorage unavailable (private browsing edge cases).
    // Reload anyway; worst case is one extra reload if the chunks are
    // still missing — error UI will then surface as expected.
  }

  // Hard reload — bypasses any in-memory bfcache state.
  window.location.reload()
  return true
}

/**
 * Clear the reload-attempted flag. Called once on successful app mount —
 * if we got here, the new bundle loaded fine, so future stale-chunk
 * errors in this tab can retry the auto-reload trick.
 */
export function clearChunkReloadFlag(): void {
  try {
    sessionStorage.removeItem(RELOAD_FLAG)
  } catch {
    // ignore
  }
}
