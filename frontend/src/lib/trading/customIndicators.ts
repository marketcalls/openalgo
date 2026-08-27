/**
 * Loads the user's own indicator modules from `strategies/indicators` and lets
 * them register into the openalgo-charts catalogue.
 *
 * Called from `terminal.ts:loadIndicators` right after the built-in tier, so
 * every path that can reach `chart.addIndicator` (the picker, `addIndicatorById`
 * and `applyIndicators` restoring a saved layout) sees a custom indicator before
 * it looks anything up. Registering after the built-ins also means a custom
 * indicator that reuses a built-in id overrides it rather than being overridden.
 *
 * These modules are fetched at runtime rather than bundled. `frontend/dist` is
 * built by CI from what is committed, and user indicators are deliberately
 * gitignored, so a bundled one would be erased by the next `git pull`. Coming in
 * over HTTP keeps them out of the build entirely: no Node.js, no rebuild, and an
 * upgrade leaves them alone.
 *
 * A module default-exports a function and is handed the charting API, because a
 * runtime module cannot resolve the bare `openalgo-charts` specifier the way a
 * bundled import can. Passing the API in is what keeps the user's file free of
 * import paths and CDN URLs.
 */

/** One module the server is offering. `mtime` busts the browser module cache. */
interface CustomModule {
  file: string
  mtime: number
}

export interface CustomIndicatorLoad {
  /** Modules that registered without throwing. */
  loaded: string[]
  /** Per-module failures, already formatted for a toast. */
  errors: { file: string; message: string }[]
}

const INDEX_URL = '/custom-indicators/index.json'

function isModuleList(value: unknown): value is CustomModule[] {
  return (
    Array.isArray(value) &&
    value.every(
      (m) => typeof m === 'object' && m !== null && typeof (m as CustomModule).file === 'string'
    )
  )
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/**
 * Fetch, import and run every user module.
 *
 * Never throws. A missing folder, a logged-out session and a syntax error in one
 * user file all have to leave the other 91 indicators working, so the index is
 * treated as optional and each module is isolated from the next.
 */
export async function loadCustomIndicators(): Promise<CustomIndicatorLoad> {
  const result: CustomIndicatorLoad = { loaded: [], errors: [] }

  let modules: CustomModule[]
  try {
    // Without the Accept header an expired session answers with a 302 to the
    // login page, which fetch follows to a 200 of HTML. Asking for JSON gets a
    // straight 401 instead, so a logged-out chart fails fast rather than trying
    // to parse a login page as a module index.
    const res = await fetch(INDEX_URL, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) return result
    const body: unknown = await res.json()
    if (!isModuleList(body)) return result
    modules = body
  } catch {
    // No route, no network, no session. Nothing to load is a normal state here,
    // not a failure worth showing anyone.
    return result
  }
  if (modules.length === 0) return result

  // The whole surface of both tiers, so a user module can reach `sma`, `rma`,
  // `highest`, `sourceValues`, the timezone helpers and `createTier2Indicator`
  // without importing anything itself.
  const api = {
    ...(await import('openalgo-charts')),
    ...(await import('openalgo-charts/indicators')),
  }

  for (const mod of modules) {
    try {
      const url = `/custom-indicators/${encodeURIComponent(mod.file)}?v=${mod.mtime}`
      const loaded: unknown = await import(/* @vite-ignore */ url)
      const register = (loaded as { default?: unknown }).default
      if (typeof register !== 'function') {
        throw new Error('module has no default-exported function')
      }
      await register(api)
      result.loaded.push(mod.file)
    } catch (e) {
      result.errors.push({ file: mod.file, message: messageOf(e) })
    }
  }
  return result
}
