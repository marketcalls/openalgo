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
 *
 * **This module validates what it loads.** The chart runtime is forgiving in the
 * worst way: a column one element short, or a plot key that does not match what
 * `calc` returns, draws nothing at all and raises nothing anywhere. A trader has
 * no compiler and no build step between writing a file and running it, so the
 * checks live here, where the real library already is, and report as toasts.
 */

/** One module the server is offering. `mtime` busts the browser module cache. */
interface CustomModule {
  file: string
  mtime: number
}

export interface CustomIndicatorLoad {
  /** Modules that registered without throwing, this call only. */
  loaded: string[]
  /** Per-module failures, already formatted for a toast. */
  errors: { file: string; message: string }[]
}

/** Reports a problem found while an indicator is running, not while loading. */
type ProblemReporter = (message: string) => void

const INDEX_URL = '/custom-indicators/index.json'

// Kept in step with the library's IndicatorInput union. 'session', 'timeframe'
// and 'symbol' are strings the indicator parses itself; 'price' and 'time' are
// numbers a host may also let the user pick off the chart.
const INPUT_TYPES = new Set([
  'number',
  'boolean',
  'color',
  'text',
  'select',
  'source',
  'session',
  'timeframe',
  'symbol',
  'price',
  'time',
])
const PLACEMENTS = new Set(['onchart', 'pane'])

/**
 * `file@mtime` of every module already imported and registered.
 *
 * The index is re-read whenever the catalogue is requested, so a file dropped in
 * while the chart is open is picked up on the next picker open with no page
 * reload. This set is what keeps that cheap and quiet: an unchanged module is
 * not re-imported, and its warnings are not repeated.
 */
const processed = new Set<string>()

/**
 * Ids present before any user module ran, captured once.
 *
 * A custom indicator that reuses a built-in id silently replaces it for the
 * whole app. That is a legitimate way to override one, but it is far more often
 * an accident: the catalogue has grown to 102, and ids like `t3`, `smma`,
 * `net-volume` and `standard-deviation` arrived recently enough that a user file
 * written before them can shadow one without either side knowing.
 *
 * Snapshotted before the first user module registers, never after, so a file
 * that is edited and re-loaded is not reported against its own earlier
 * registration.
 */
let builtinIds: ReadonlySet<string> | null = null

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
 * Structural checks on a descriptor, run at registration.
 *
 * Anything returned here is fatal: registering a descriptor the chart cannot
 * drive produces a picker entry that breaks when clicked, which is worse than
 * not appearing at all.
 */
export function descriptorErrors(d: Record<string, unknown>): string[] {
  const out: string[] = []
  const id = typeof d.id === 'string' ? d.id : ''
  if (!id.trim()) out.push('descriptor.id must be a non-empty string')
  else if (/\s/.test(id)) out.push(`id '${id}' contains whitespace`)
  if (typeof d.name !== 'string' || d.name.trim() === '') out.push('descriptor.name is required')
  if (!PLACEMENTS.has(d.placement as string)) {
    out.push("placement must be 'onchart' or 'pane'")
  }
  if (typeof d.calc !== 'function') out.push('calc must be a function')

  if (!Array.isArray(d.inputs)) {
    out.push('inputs must be an array (use [] for none)')
  } else {
    for (const input of d.inputs as Record<string, unknown>[]) {
      if (!input || typeof input.key !== 'string' || input.key === '') {
        out.push('every input needs a key')
        break
      }
      if (!INPUT_TYPES.has(input.type as string)) {
        out.push(`input '${input.key}' has unsupported type '${String(input.type)}'`)
      }
      if (input.default === undefined) out.push(`input '${input.key}' has no default`)
    }
  }

  if (!Array.isArray(d.plots) || d.plots.length === 0) {
    out.push('plots must be a non-empty array')
  } else {
    const keys = new Set<string>()
    for (const plot of d.plots as Record<string, unknown>[]) {
      if (!plot || typeof plot.key !== 'string' || plot.key === '') {
        out.push('every plot needs a key')
        break
      }
      if (keys.has(plot.key)) out.push(`duplicate plot key '${plot.key}'`)
      keys.add(plot.key)
      if (typeof plot.type !== 'string' || plot.type === '') {
        out.push(`plot '${plot.key}' needs a type`)
      }
    }
  }
  return out
}

/**
 * Check one `calc` result against the bars it was given.
 *
 * These are the two failures the runtime swallows. It iterates `0..bars.length`
 * and reads `col[i]`, so a short column reads `undefined` past its end and a
 * missing key empties the series. Either way the plot just stops drawing.
 */
export function calcOutputError(
  values: unknown,
  barCount: number,
  plots: { key: string; ohlc?: { open: string; high: string; low: string; close: string } }[]
): string | null {
  if (typeof values !== 'object' || values === null || Array.isArray(values)) {
    return 'calc must return an object of columns'
  }
  const cols = values as Record<string, unknown>
  for (const plot of plots) {
    // A candle or bar plot is fed by four named columns rather than one keyed
    // by the plot itself, so check those instead.
    const keys = plot.ohlc
      ? [plot.ohlc.open, plot.ohlc.high, plot.ohlc.low, plot.ohlc.close]
      : [plot.key]
    for (const key of keys) {
      const c = cols[key]
      if (c === undefined) return `calc returned no column '${key}' for plot '${plot.key}'`
      if (!Array.isArray(c)) return `column '${key}' is a ${typeof c}, expected an array`
      if (c.length !== barCount) {
        return `column '${key}' returned ${c.length} values for ${barCount} bars`
      }
    }
    if (plot.ohlc) continue
    const col = cols[plot.key]
    if (col === undefined) {
      return `calc returned no column for plot '${plot.key}', so it draws nothing`
    }
    if (!Array.isArray(col)) {
      return `calc returned a ${typeof col} for plot '${plot.key}', expected an array`
    }
    if (col.length !== barCount) {
      return `plot '${plot.key}' returned ${col.length} values for ${barCount} bars`
    }
  }
  return null
}

/**
 * Wrap `calc` so its first real result is checked against the bars.
 *
 * Only the first call, and only once per indicator: the point is to tell the
 * user why nothing is drawing, not to tax every recompute or repeat the same
 * toast on every tick. `this` is forwarded because a descriptor may call
 * `this.calc` from `calcTail`.
 */
function guardCalc(
  descriptor: Record<string, unknown>,
  file: string,
  onProblem: ProblemReporter
): Record<string, unknown> {
  const original = descriptor.calc as (...args: unknown[]) => unknown
  const plots = descriptor.plots as { key: string }[]
  const label = `${file}: ${String(descriptor.id)}`
  let checked = false

  return {
    ...descriptor,
    calc(this: unknown, ...args: unknown[]) {
      const values = original.apply(this, args)
      if (!checked) {
        checked = true
        const bars = args[0]
        const barCount = Array.isArray(bars) ? bars.length : 0
        // An empty series proves nothing, so wait for real bars.
        if (barCount > 0) {
          const problem = calcOutputError(values, barCount, plots)
          if (problem) onProblem(`${label}: ${problem}`)
        }
      }
      return values
    },
  }
}

/**
 * Fetch, import and run every user module that has not been seen yet.
 *
 * Never throws. A missing folder, a logged-out session and a syntax error in one
 * user file all have to leave the other 102 indicators working, so the index is
 * treated as optional and each module is isolated from the next.
 */
export async function loadCustomIndicators(
  opts: { onProblem?: ProblemReporter } = {}
): Promise<CustomIndicatorLoad> {
  const result: CustomIndicatorLoad = { loaded: [], errors: [] }
  const onProblem = opts.onProblem ?? (() => {})

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

  const fresh = modules.filter((m) => !processed.has(`${m.file}@${m.mtime}`))
  if (fresh.length === 0) return result

  // The whole surface of both tiers, so a user module can reach `sma`, `rma`,
  // `highest`, `sourceValues`, the timezone helpers and `createTier2Indicator`
  // without importing anything itself.
  const core = await import('openalgo-charts')
  const api = { ...core, ...(await import('openalgo-charts/indicators')) }

  // After the tier import so every built-in has registered, and before the first
  // user module runs so the snapshot holds built-ins only.
  if (builtinIds === null) {
    builtinIds = new Set(core.registeredIndicators().map((d) => d.id))
  }

  for (const mod of fresh) {
    processed.add(`${mod.file}@${mod.mtime}`)
    try {
      const url = `/custom-indicators/${encodeURIComponent(mod.file)}?v=${mod.mtime}`
      const loaded: unknown = await import(/* @vite-ignore */ url)
      const register = (loaded as { default?: unknown }).default
      if (typeof register !== 'function') {
        throw new Error('module has no default-exported function')
      }

      // Registration is intercepted so a descriptor is checked before it can
      // reach the catalogue, and so `calc` can be wrapped on the way through.
      let registeredAny = false
      await register({
        ...api,
        registerIndicator: (descriptor: Record<string, unknown>) => {
          if (typeof descriptor !== 'object' || descriptor === null) {
            throw new Error('registerIndicator needs a descriptor object')
          }
          const problems = descriptorErrors(descriptor)
          if (problems.length > 0) throw new Error(problems.join('; '))
          // A warning, not an error: overriding a built-in is allowed on
          // purpose, and refusing would break a file that has been doing it
          // deliberately since before the id existed upstream.
          const id = descriptor.id
          if (typeof id === 'string' && builtinIds?.has(id)) {
            onProblem(
              `${mod.file}: id "${id}" replaces the built-in indicator of the same name for the whole app. Rename it unless that override is intended.`
            )
          }
          registeredAny = true
          core.registerIndicator(guardCalc(descriptor, mod.file, onProblem) as never)
        },
      })
      if (!registeredAny) throw new Error('module never called registerIndicator')
      result.loaded.push(mod.file)
    } catch (e) {
      result.errors.push({ file: mod.file, message: messageOf(e) })
    }
  }
  return result
}
