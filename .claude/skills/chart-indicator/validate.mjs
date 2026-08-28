#!/usr/bin/env node
/**
 * Validate a custom chart indicator before it is allowed anywhere near
 * strategies/indicators/.
 *
 * A file in that folder is imported by the live chart. There is no compiler and
 * no type check between writing it and running it, and the runtime is forgiving
 * in exactly the wrong way: a column that is too short, or a plot key that does
 * not match, draws nothing at all rather than raising. So a broken indicator
 * looks like an indicator that "does not work" with no error anywhere.
 *
 * This runs the candidate against the real openalgo-charts build, exercises its
 * calc over several bar shapes, and refuses to install anything that errors.
 *
 * Usage:
 *   node validate.mjs <candidate.js>              check only
 *   node validate.mjs <candidate.js> --install    check, then install on a pass
 */

import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO_ROOT = resolve(import.meta.dirname, '..', '..', '..')
const INSTALL_DIR = join(REPO_ROOT, 'strategies', 'indicators')
/** A React developer already has it here, at the exact pinned version. */
const DEV_CHARTS_ROOT = join(REPO_ROOT, 'frontend', 'node_modules', 'openalgo-charts')
/** Everyone else gets just this one package cached here. Gitignored. */
const CACHE_ROOT = join(import.meta.dirname, '.cache')

/**
 * Find the charting library, without making anyone run `npm install`.
 *
 * The full frontend tree is 560 MB across 521 packages; this script needs two
 * ES modules totalling 368 KB. OpenAlgo users are traders, not React
 * developers, and the whole point of runtime-loaded indicators is that they
 * never need a build. So: use the dev copy if it happens to be there, else a
 * small local cache, else fetch the single package. `openalgo-charts` has zero
 * dependencies, so that is one small tarball and nothing else.
 *
 * The version is read from `frontend/package.json`, so the cache tracks the
 * version the app actually ships and cannot silently validate against a
 * different API.
 */
function pinnedVersion() {
  try {
    const pkg = JSON.parse(readFileSync(join(REPO_ROOT, 'frontend', 'package.json'), 'utf8'))
    const spec = pkg.dependencies?.['openalgo-charts'] ?? pkg.devDependencies?.['openalgo-charts']
    return typeof spec === 'string' ? spec.replace(/^[\^~]/, '') : null
  } catch {
    return null
  }
}

function installedVersion(root) {
  try {
    return JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version ?? null
  } catch {
    return null
  }
}

/**
 * Fetch just this one package into `prefix`.
 *
 * `npm install --prefix` rather than `npm pack` plus `tar`: it is one call, it
 * needs no shell (so nothing has to be quoted, which is where the Windows path
 * with an `@` in it went wrong), and because `openalgo-charts` declares zero
 * dependencies the result is exactly one package and no tree.
 */
function fetchPackage(version, prefix) {
  mkdirSync(prefix, { recursive: true })
  const spec = version ? `openalgo-charts@${version}` : 'openalgo-charts'
  // npm is a .cmd on Windows, and Node refuses to spawn one without a shell.
  // With a shell, nothing is auto-quoted, so the path args are quoted here or a
  // checkout under "Program Files" would split into two arguments.
  const win = process.platform === 'win32'
  const q = (s) => (win ? `"${s}"` : s)
  execFileSync(
    win ? 'npm.cmd' : 'npm',
    ['install', q(spec), '--prefix', q(prefix), '--no-save', '--no-package-lock',
     '--no-audit', '--no-fund', '--loglevel', 'error'],
    { stdio: ['ignore', 'ignore', 'pipe'], shell: win }
  )
}

function resolveCharts() {
  const want = pinnedVersion()

  if (existsSync(join(DEV_CHARTS_ROOT, 'dist', 'openalgo-charts.mjs'))) {
    return { root: DEV_CHARTS_ROOT, source: 'frontend/node_modules' }
  }

  // No '@' in the directory name: it survives every shell and path helper.
  const prefix = join(CACHE_ROOT, `v${want ?? 'latest'}`)
  const cached = join(prefix, 'node_modules', 'openalgo-charts')
  if (existsSync(join(cached, 'dist', 'openalgo-charts.mjs'))) {
    const have = installedVersion(cached)
    if (!want || have === want) return { root: cached, source: 'skill cache' }
  }

  console.log(`Fetching openalgo-charts@${want ?? 'latest'} (one package, no dependencies)...`)
  fetchPackage(want, prefix)
  if (!existsSync(join(cached, 'dist', 'openalgo-charts.mjs'))) {
    throw new Error('fetched package has no dist/openalgo-charts.mjs')
  }
  return { root: cached, source: 'downloaded' }
}

const errors = []
const warnings = []
const notes = []

// Every check runs against 5 fixtures x up to 3 settings variants, so one
// structural defect would otherwise be reported 15 times. Callers pass a key
// naming the defect (not the message, which carries the fixture it was caught
// on) so the first occurrence is reported and the rest collapse into it.
const seen = new Set()
const once = (list) => (m, key) => {
  const k = key ?? m
  if (seen.has(k)) return
  seen.add(k)
  list.push(m)
}
const err = once(errors)
const warn = once(warnings)
const note = once(notes)

// The library's IndicatorInput union. The last five are 1.8.1: 'session',
// 'timeframe' and 'symbol' are strings the indicator parses itself, 'price' and
// 'time' are numbers a host may also resolve from a chart click.
const INPUT_TYPES = new Set([
  'number', 'boolean', 'color', 'text', 'select', 'source',
  'session', 'timeframe', 'symbol', 'price', 'time',
])
const STRING_INPUTS = new Set(['text', 'select', 'source', 'session', 'timeframe', 'symbol'])
const NUMBER_INPUTS = new Set(['number', 'price', 'time'])
const SOURCES = new Set(['open', 'high', 'low', 'close', 'hl2', 'hlc3', 'ohlc4', 'volume'])
const PLACEMENTS = new Set(['onchart', 'pane'])
const MARKER_POSITIONS = new Set(['aboveBar', 'belowBar', 'inBar', 'atPrice'])
const MARKER_SHAPES = new Set([
  'arrowUp', 'arrowDown', 'circle', 'square', 'triangleUp', 'triangleDown',
  'diamond', 'flag', 'text', 'labelUp', 'labelDown',
])
const MARKER_SIZES = new Set(['tiny', 'small', 'medium', 'big'])
const DRAW_KINDS = new Set(['line', 'box', 'label', 'polyline'])

/* ── synthetic bars ────────────────────────────────────────────────────────
 * Five shapes, because the failures cluster at the edges rather than in the
 * middle: an empty series, a series shorter than any sane lookback, a flat
 * series that makes every range zero (division traps), and a two-day series so
 * anything doing per-session or per-day work actually crosses a boundary.
 */
const IST_OFFSET = 5.5 * 3600

function sessionBars(days, perDay, startHour = 9, startMin = 15, stepMin = 5, flat = false) {
  const bars = []
  for (let d = 0; d < days; d++) {
    for (let i = 0; i < perDay; i++) {
      const minutes = startHour * 60 + startMin + i * stepMin
      const t = Date.UTC(2024, 0, 2 + d, 0, minutes) / 1000 - IST_OFFSET
      if (flat) {
        bars.push({ time: t, open: 100, high: 100, low: 100, close: 100, volume: 1000 })
        continue
      }
      // Deterministic wobble: no Math.random, so a failure reproduces exactly.
      const drift = Math.sin((d * perDay + i) / 7) * 12
      const base = 100 + drift + d * 3
      const spread = 1 + Math.abs(Math.cos(i / 5)) * 2
      bars.push({
        time: t,
        open: base,
        high: base + spread,
        low: base - spread,
        close: base + spread / 3,
        volume: 1000 + i * 25,
      })
    }
  }
  return bars
}

const FIXTURES = [
  { label: 'two sessions, 78 bars each', bars: sessionBars(2, 78) },
  { label: 'one session, 78 bars', bars: sessionBars(1, 78) },
  { label: 'three bars', bars: sessionBars(1, 3) },
  { label: 'flat series (zero range)', bars: sessionBars(1, 40, 9, 15, 5, true) },
  { label: 'no bars', bars: [] },
]

/* ── helpers ─────────────────────────────────────────────────────────────── */

function isPlainObject(v) {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Settings variants a user can actually produce from the settings dialog. */
function settingsVariants(descriptor, indicatorDefaults) {
  const base = { ...indicatorDefaults(descriptor) }
  const variants = [{ label: 'defaults', settings: base }]

  // A cleared text or number field arrives as ''. This is the single most
  // common runtime crash: `Number('')` is 0, but `''.trim()` on a number input
  // or a regex against '' takes an unguarded calc down.
  const cleared = { ...base }
  let clearedAny = false
  for (const input of descriptor.inputs ?? []) {
    if (STRING_INPUTS.has(input.type) || NUMBER_INPUTS.has(input.type)) {
      cleared[input.key] = ''
      clearedAny = true
    }
  }
  if (clearedAny) variants.push({ label: 'cleared text/number fields', settings: cleared })

  // Extremes, where an off-by-one in a lookback window shows up.
  const extreme = { ...base }
  let extremeAny = false
  for (const input of descriptor.inputs ?? []) {
    if (NUMBER_INPUTS.has(input.type)) {
      extreme[input.key] = input.min ?? 1
      extremeAny = true
    }
    if (input.type === 'boolean') {
      extreme[input.key] = !input.default
      extremeAny = true
    }
  }
  if (extremeAny) variants.push({ label: 'minimum / flipped inputs', settings: extreme })

  return variants
}

function checkColumn(descriptor, plotKey, col, bars, ctxLabel, primary) {
  const where = `${descriptor.id}: plot '${plotKey}' (${ctxLabel})`
  const k = `${descriptor.id}|${plotKey}`
  if (col === undefined) {
    err(`${where}: calc returned no column for this plot key. The plot will draw nothing.`, `${k}|missing`)
    return
  }
  if (!Array.isArray(col)) {
    err(`${where}: expected an array, got ${typeof col}.`, `${k}|notarray`)
    return
  }
  if (col.length !== bars.length) {
    err(
      `${where}: length ${col.length} but ${bars.length} bars. ` +
        `The runtime indexes by bar, so a mismatch silently truncates or ignores values.`,
      `${k}|length`
    )
    return
  }
  let allGap = true
  for (let i = 0; i < col.length; i++) {
    const v = col[i]
    if (v === null || v === undefined) continue
    if (typeof v !== 'number') {
      err(`${where}: index ${i} is ${typeof v}, expected number | null.`, `${k}|elemtype`)
      return
    }
    if (Number.isFinite(v)) allGap = false
  }
  // Only worth saying on the realistic fixture at default settings. A short or
  // flat series, or a cleared input, produces an all-gap column legitimately,
  // and warning on each combination buries the cases that matter.
  if (allGap && primary && bars.length > 0) {
    warn(
      `${descriptor.id}: plot '${plotKey}' is empty across 156 ordinary bars at default ` +
        `settings. Check the lookback, or that calc actually fills this column.`
    )
  }
}

function checkMarkers(descriptor, out, bars, ctxLabel) {
  const where = `${descriptor.id}: markers (${ctxLabel})`
  const k = `${descriptor.id}|markers`
  if (!Array.isArray(out)) {
    err(`${where}: expected an array, got ${typeof out}.`, `${k}|notarray`)
    return
  }
  const times = new Set(bars.map((b) => b.time))
  for (const m of out) {
    if (!isPlainObject(m)) {
      err(`${where}: every marker must be an object.`, `${k}|notobj`)
      return
    }
    if (!times.has(m.time)) {
      err(`${where}: marker time ${m.time} does not match any bar. Markers anchor to bar times.`, `${k}|time`)
      return
    }
    if (!MARKER_POSITIONS.has(m.position)) {
      err(`${where}: position '${m.position}' is not one of ${[...MARKER_POSITIONS].join(', ')}.`, `${k}|pos`)
      return
    }
    if (!MARKER_SHAPES.has(m.shape)) {
      err(`${where}: shape '${m.shape}' is not a known marker shape.`, `${k}|shape`)
      return
    }
    if (m.size !== undefined && !MARKER_SIZES.has(m.size)) {
      err(`${where}: size '${m.size}' is not one of ${[...MARKER_SIZES].join(', ')}.`, `${k}|size`)
      return
    }
    if (typeof m.color !== 'string' || m.color === '') {
      err(`${where}: every marker needs a colour.`, `${k}|color`)
      return
    }
    if (m.position === 'atPrice' && !Number.isFinite(m.price)) {
      err(`${where}: position 'atPrice' needs a finite numeric price.`, `${k}|price`)
      return
    }
    if (m.position !== 'atPrice' && descriptor.placement === 'onchart') {
      warn(
        `${where}: position '${m.position}' on an 'onchart' indicator anchors to this ` +
          `indicator's own plot line, NOT to the candle. Use 'atPrice' with an explicit ` +
          `price to place a label relative to the bar's high or low.`,
        `${k}|anchor`
      )
    }
  }
}

/* ── the run ─────────────────────────────────────────────────────────────── */

async function main() {
  const args = process.argv.slice(2)
  const install = args.includes('--install')
  const candidatePath = args.find((a) => !a.startsWith('--'))

  if (!candidatePath) {
    console.error('usage: node validate.mjs <candidate.js> [--install]')
    process.exit(2)
  }
  const candidate = resolve(candidatePath)
  if (!existsSync(candidate)) {
    console.error(`No such file: ${candidate}`)
    process.exit(2)
  }
  let charts
  try {
    charts = resolveCharts()
  } catch (e) {
    console.error(
      `Could not get hold of openalgo-charts: ${e.message}\n\n` +
        `The chart itself needs nothing installed. This pre-flight check does,\n` +
        `and it could not fetch the package. Either connect to the network once,\n` +
        `or skip validation and rely on the chart's own checks, which report the\n` +
        `same problems as toasts when the indicator loads.`
    )
    process.exit(2)
  }

  // Import the real library, so every check runs against the build the app ships.
  const core = await import(pathToFileURL(join(charts.root, 'dist', 'openalgo-charts.mjs')).href)
  const tier = await import(
    pathToFileURL(join(charts.root, 'dist', 'openalgo-charts.indicators.mjs')).href
  )

  const builtinIds = new Set(core.registeredIndicators().map((d) => d.id))
  const chartTypes = new Set(core.registeredChartTypes())

  // Load the candidate. A syntax error surfaces here as a rejected import.
  let mod
  try {
    mod = await import(`${pathToFileURL(candidate).href}?t=${Date.now()}`)
  } catch (e) {
    err(`Module failed to load: ${e.message}`)
    return report(install, candidate)
  }

  if (typeof mod.default !== 'function') {
    err(
      'No default-exported function. A custom indicator file must be ' +
        '`export default function ({ registerIndicator, ... }) { ... }`.'
    )
    return report(install, candidate)
  }

  // Capture what the module registers instead of mutating the shared registry.
  const registered = []
  const api = {
    ...core,
    ...tier,
    registerIndicator: (d) => {
      registered.push(d)
    },
  }

  try {
    await mod.default(api)
  } catch (e) {
    err(`The default export threw when called: ${e.message}`)
    return report(install, candidate)
  }

  if (registered.length === 0) {
    err('The module ran but never called registerIndicator.')
    return report(install, candidate)
  }

  for (const d of registered) validateDescriptor(d, { builtinIds, chartTypes, core })

  return report(install, candidate, registered)
}

function validateDescriptor(d, { builtinIds, chartTypes, core }) {
  if (!isPlainObject(d)) {
    err('registerIndicator was called with something that is not a descriptor object.')
    return
  }
  const id = d.id
  if (typeof id !== 'string' || id.trim() === '') {
    err('descriptor.id must be a non-empty string.')
    return
  }
  if (/\s/.test(id)) err(`id '${id}' contains whitespace. Use a kebab-case slug.`)
  if (builtinIds.has(id)) {
    warn(
      `id '${id}' is already a built-in indicator. Custom modules register last, so this ` +
        `OVERRIDES the built-in. Prefix your own ids unless that is deliberate.`
    )
  }
  if (typeof d.name !== 'string' || d.name.trim() === '') err(`${id}: name must be a non-empty string.`)
  if (!PLACEMENTS.has(d.placement)) {
    err(`${id}: placement must be 'onchart' or 'pane', got ${JSON.stringify(d.placement)}.`)
  }
  if (typeof d.calc !== 'function') {
    err(`${id}: calc must be a function.`)
    return
  }

  /* inputs */
  if (!Array.isArray(d.inputs)) {
    err(`${id}: inputs must be an array (use [] when there is nothing to configure).`)
    return
  }
  const inputKeys = new Set()
  for (const input of d.inputs) {
    if (!isPlainObject(input)) {
      err(`${id}: every input must be an object.`)
      return
    }
    if (typeof input.key !== 'string' || input.key === '') {
      err(`${id}: every input needs a key.`)
      return
    }
    if (inputKeys.has(input.key)) err(`${id}: duplicate input key '${input.key}'.`)
    inputKeys.add(input.key)
    if (!INPUT_TYPES.has(input.type)) {
      err(
        `${id}: input '${input.key}' has type '${input.type}', which the settings dialog ` +
          `cannot render. Use one of ${[...INPUT_TYPES].join(', ')}.`
      )
      continue
    }
    if (input.default === undefined) {
      err(`${id}: input '${input.key}' has no default. The Defaults button needs one.`)
    }
    if (typeof input.label !== 'string' || input.label === '') {
      warn(`${id}: input '${input.key}' has no label, so the dialog falls back to the key.`)
    }
    if (NUMBER_INPUTS.has(input.type)) {
      if (typeof input.default !== 'number') {
        err(`${id}: number input '${input.key}' has a non-numeric default.`)
      } else {
        if (input.min !== undefined && input.default < input.min) {
          err(`${id}: input '${input.key}' default ${input.default} is below min ${input.min}.`)
        }
        if (input.max !== undefined && input.default > input.max) {
          err(`${id}: input '${input.key}' default ${input.default} is above max ${input.max}.`)
        }
      }
    }
    if (input.type === 'boolean' && typeof input.default !== 'boolean') {
      err(`${id}: boolean input '${input.key}' has a non-boolean default.`)
    }
    if (input.type === 'select') {
      if (!Array.isArray(input.options) || input.options.length === 0) {
        err(`${id}: select input '${input.key}' needs a non-empty options array.`)
      } else if (!input.options.some((o) => o.value === input.default)) {
        err(`${id}: select input '${input.key}' default is not among its options.`)
      }
    }
    if (input.type === 'source' && !SOURCES.has(input.default)) {
      err(`${id}: source input '${input.key}' default '${input.default}' is not a price source.`)
    }
    if (input.type === 'color' && typeof input.default !== 'string') {
      err(`${id}: color input '${input.key}' needs a string default like '#4f8cff'.`)
    }
  }

  /* plots */
  if (!Array.isArray(d.plots) || d.plots.length === 0) {
    err(`${id}: plots must be a non-empty array.`)
    return
  }
  const plotKeys = new Set()
  for (const plot of d.plots) {
    if (!isPlainObject(plot)) {
      err(`${id}: every plot must be an object.`)
      return
    }
    if (typeof plot.key !== 'string' || plot.key === '') {
      err(`${id}: every plot needs a key.`)
      return
    }
    if (plotKeys.has(plot.key)) err(`${id}: duplicate plot key '${plot.key}'.`)
    plotKeys.add(plot.key)
    if (!chartTypes.has(plot.type)) {
      err(
        `${id}: plot '${plot.key}' has type '${plot.type}', which is not a registered chart ` +
          `type. Single-column plots should use one of: line, line-markers, step, area, ` +
          `histogram, column.`
      )
    }
    if ((typeof plot.title !== 'string' || plot.title === '') && plot.style?.visible !== false) {
      warn(`${id}: plot '${plot.key}' has no title, so the legend has nothing to show.`)
    }
    // colorBy is a function the runtime calls per bar, but it reads like a
    // column reference, so it gets handed a string. The runtime then calls that
    // string and the whole chart dies with 'a is not a function' -- at render
    // time, far from the descriptor, with a minified name that says nothing.
    if (plot.colorBy !== undefined && typeof plot.colorBy !== 'function') {
      err(
        `${id}: plot '${plot.key}' has colorBy as ${typeof plot.colorBy}, but colorBy is a ` +
          `function the runtime calls per bar, not the name of a column. Write ` +
          `colorBy: ({ index, values, settings }) => values.myColumn[index] > 0 ? up : down.`,
        `${id}|${plot.key}|colorBy`
      )
    }
    if (plot.colorKey !== undefined && !inputKeys.has(plot.colorKey)) {
      err(`${id}: plot '${plot.key}' names colorKey '${plot.colorKey}' with no matching input.`)
    }
    // A candle or bar plot is fed by four named columns rather than by its own
    // key. A missing name throws out of addIndicator, so catch it here instead.
    if (plot.ohlc !== undefined) {
      const need = ['open', 'high', 'low', 'close']
      if (!isPlainObject(plot.ohlc) || need.some((k) => typeof plot.ohlc[k] !== 'string')) {
        err(`${id}: plot '${plot.key}' has an ohlc group missing one of open/high/low/close.`)
      }
    }
  }

  /* fills reference real plots, and real colour inputs */
  for (const fill of d.fills ?? []) {
    if (!Array.isArray(fill?.between) || fill.between.length !== 2) {
      err(`${id}: every fill needs 'between: [plotKeyA, plotKeyB]'.`)
      continue
    }
    for (const key of fill.between) {
      if (!plotKeys.has(key)) err(`${id}: fill references plot '${key}', which does not exist.`)
    }
    // A fill takes its colour from an INPUT key, not from a plot's style, so a
    // typo here leaves the ribbon on the library default with nothing to say so.
    for (const prop of ['colorUpKey', 'colorDownKey']) {
      const key = fill[prop]
      if (key !== undefined && !inputKeys.has(key)) {
        err(`${id}: fill ${prop} '${key}' names no input. A fill colour must come from an input.`)
      }
    }
    if (fill.opacity !== undefined && (!Number.isFinite(fill.opacity) || fill.opacity < 0 || fill.opacity > 1)) {
      err(`${id}: fill opacity must be between 0 and 1, got ${fill.opacity}.`)
    }
  }

  /* alerts */
  if (d.alerts !== undefined) {
    if (!Array.isArray(d.alerts)) {
      err(`${id}: alerts must be an array.`)
    } else {
      const alertIds = new Set()
      for (const al of d.alerts) {
        if (!isPlainObject(al)) { err(`${id}: every alert must be an object.`); break }
        if (typeof al.id !== 'string' || al.id === '') err(`${id}: every alert needs an id.`)
        else if (alertIds.has(al.id)) err(`${id}: duplicate alert id '${al.id}'.`)
        alertIds.add(al.id)
        if (typeof al.title !== 'string' || al.title === '') {
          err(`${id}: alert '${al.id}' needs a title; it is what a host shows.`)
        }
        if (typeof al.when !== 'function') err(`${id}: alert '${al.id}' needs a when() predicate.`)
      }
    }
  }

  /* run it */
  const variants = settingsVariants(d, core.indicatorDefaults)
  for (const variant of variants) {
    for (const fixture of FIXTURES) {
      const ctx = `${fixture.label} / ${variant.label}`
      // The one combination an indicator is really expected to produce output
      // for: a realistic two-day series with the settings it ships with.
      //
      // An indicator whose data comes from outside the chart is exempt: with no
      // network here its columns are legitimately empty, and warning about it
      // trains people to ignore the warning that matters.
      const external = typeof d.attach === 'function'
      // A study whose output is a table carries a hidden placeholder plot, only
      // because a descriptor needs one. The built-in seasonality does the same.
      // Its emptiness is the design, not a mistake worth a warning.
      const tableOnly =
        typeof d.table === 'function' && d.plots.every((p) => p.style?.visible === false)
      const primary =
        !external && !tableOnly && fixture === FIXTURES[0] && variant === variants[0]
      const store = {}
      let values
      try {
        values = d.calc(fixture.bars, variant.settings, store)
      } catch (e) {
        err(`${id}: calc threw on ${ctx}: ${e.message}`, `${id}|calc-throw|${e.message}`)
        continue
      }
      // Hand the hooks a recording view of the values so a read of a column
      // that was never produced is caught here rather than rendering a blank.
      const missedReads = new Set()
      const watched = isPlainObject(values)
        ? new Proxy(values, {
            get(target, key) {
              if (typeof key === 'string' && !(key in target)) missedReads.add(key)
              return target[key]
            },
          })
        : values

      if (!isPlainObject(values)) {
        err(`${id}: calc must return an object of columns, got ${typeof values} on ${ctx}.`, `${id}|calc-shape`)
        continue
      }
      // Columns nothing plots are still read: by `table`, `markers`,
      // `background`, `barColors` and `alerts`, none of which the plot checks
      // below can see. A key holding `undefined` is the signature of a built-in
      // read under the wrong plot key, which draws nothing and says nothing.
      if (isPlainObject(values)) {
        for (const [key, col] of Object.entries(values)) {
          if (col === undefined || col === null) {
            err(
              `${id}: calc returned '${key}' as ${col === null ? 'null' : 'undefined'}. ` +
                `A built-in read under the wrong plot key does this: check ` +
                `getIndicator(id).plots for the real column names.`,
              `${id}|${key}|undef`
            )
          } else if (!Array.isArray(col)) {
            err(`${id}: calc returned '${key}' as a ${typeof col}, expected an array.`, `${id}|${key}|notarr`)
          } else if (col.length !== fixture.bars.length) {
            err(
              `${id}: column '${key}' has ${col.length} values for ${fixture.bars.length} bars.`,
              `${id}|${key}|len`
            )
          }
        }
      }

      for (const plot of d.plots) {
        // A candle or bar plot is fed by four named columns, not by its own key.
        if (plot.ohlc && typeof plot.ohlc.close === 'string') {
          for (const k of ['open', 'high', 'low', 'close']) {
            const name = plot.ohlc[k]
            if (typeof name === 'string') checkColumn(d, name, values[name], fixture.bars, ctx, primary)
          }
          continue
        }
        checkColumn(d, plot.key, values[plot.key], fixture.bars, ctx, primary)
      }

      if (typeof d.markers === 'function') {
        try {
          checkMarkers(d, d.markers({ bars: fixture.bars, values: watched, settings: variant.settings }), fixture.bars, ctx)
        } catch (e) {
          err(`${id}: markers threw on ${ctx}: ${e.message}`, `${id}|markers-throw|${e.message}`)
        }
      }
      if (typeof d.levels === 'function') {
        try {
          const levels = d.levels(variant.settings)
          if (!Array.isArray(levels)) err(`${id}: levels must return an array.`)
          else {
            for (const l of levels) {
              if (!Number.isFinite(l?.price)) err(`${id}: every level needs a finite price.`)
            }
          }
        } catch (e) {
          err(`${id}: levels threw on ${ctx}: ${e.message}`)
        }
      }
      if (typeof d.range === 'function') {
        try {
          const r = d.range(variant.settings)
          if (r !== null && r !== undefined) {
            if (!Number.isFinite(r.min) || !Number.isFinite(r.max)) {
              err(`${id}: range must return null or { min, max } with finite numbers.`)
            } else if (r.min >= r.max) {
              err(`${id}: range min ${r.min} is not below max ${r.max}.`)
            }
          }
        } catch (e) {
          err(`${id}: range threw on ${ctx}: ${e.message}`)
        }
      }
      if (typeof d.draws === 'function') {
        try {
          const items = d.draws({ bars: fixture.bars, values: watched, settings: variant.settings })
          if (!Array.isArray(items)) err(`${id}: draws must return an array.`, `${id}|draws-array`)
          else for (const it of items) {
            if (!isPlainObject(it) || !DRAW_KINDS.has(it.kind)) {
              err(`${id}: every drawing needs a kind of ${[...DRAW_KINDS].join(', ')}.`, `${id}|draws-kind`)
              break
            }
            const anchors = it.kind === 'label' ? [it.at]
              : it.kind === 'polyline' ? (it.points || [])
              : [it.from, it.to]
            if (anchors.some((p) => !isPlainObject(p) || !Number.isFinite(p.time) || !Number.isFinite(p.price))) {
              err(`${id}: a '${it.kind}' drawing has an anchor without a finite time and price.`, `${id}|draws-anchor`)
              break
            }
            if (it.kind === 'label' && (typeof it.text !== 'string' || it.text === '')) {
              err(`${id}: a 'label' drawing needs text.`, `${id}|draws-text`)
              break
            }
          }
        } catch (e) {
          err(`${id}: draws threw on ${ctx}: ${e.message}`, `${id}|draws-throw|${e.message}`)
        }
      }
      for (const hook of ['background', 'barColors']) {
        if (typeof d[hook] !== 'function') continue
        try {
          const out = d[hook]({ bars: fixture.bars, values: watched, settings: variant.settings })
          if (!Array.isArray(out)) {
            err(`${id}: ${hook} must return an array.`, `${id}|${hook}-array`)
          } else if (out.length !== fixture.bars.length) {
            err(
              `${id}: ${hook} returned ${out.length} entries for ${fixture.bars.length} bars. ` +
                `It is indexed by bar, so a mismatch shifts the colours off the bars.`,
              `${id}|${hook}-len`
            )
          } else if (out.some((v) => v !== null && v !== undefined && typeof v !== 'string')) {
            err(`${id}: ${hook} entries must be a colour string or null.`, `${id}|${hook}-type`)
          }
        } catch (e) {
          err(`${id}: ${hook} threw on ${ctx}: ${e.message}`, `${id}|${hook}-throw|${e.message}`)
        }
      }
      if (Array.isArray(d.alerts) && fixture.bars.length > 0) {
        for (const al of d.alerts) {
          if (typeof al?.when !== 'function') continue
          try {
            // Judge every bar: a predicate that only survives the middle of the
            // series still fires on bar 0 in production.
            for (let i = 0; i < fixture.bars.length; i++) {
              al.when({ bars: fixture.bars, values: watched, settings: variant.settings, index: i })
            }
          } catch (e) {
            err(`${id}: alert '${al.id}' when() threw on ${ctx}: ${e.message}`, `${id}|alert-throw|${al.id}|${e.message}`)
          }
        }
      }

      if (typeof d.table === 'function') {
        try {
          const t = d.table({ bars: fixture.bars, values: watched, settings: variant.settings })
          if (t !== null && t !== undefined && !Array.isArray(t.rows)) {
            err(`${id}: table must return null or { rows: [...] }.`)
          }
        } catch (e) {
          err(`${id}: table threw on ${ctx}: ${e.message}`)
        }
      }

      // Every hook has now run against the recording view, so anything it
      // reached for that calc never produced is known.
      for (const key of missedReads) {
        err(
          `${id}: a hook read column '${key}', which calc never returned. ` +
            `markers, table, background, barColors and alerts all read columns ` +
            `no plot declares, so nothing else catches this.`,
          `${id}|${key}|phantom`
        )
      }
    }
  }

  /* calcTail must agree with calc, or the live chart drifts from the reload */
  if (typeof d.calcTail === 'function') {
    const bars = FIXTURES[0].bars
    const settings = core.indicatorDefaults(d)
    const store = {}
    const full = d.calc(bars, settings, store)
    const from = bars.length - 1
    let tail
    try {
      tail = d.calcTail(bars, settings, from, full, store)
    } catch (e) {
      err(`${id}: calcTail threw: ${e.message}`)
      tail = null
    }
    if (tail !== null && tail !== undefined) {
      for (const plot of d.plots) {
        const col = tail[plot.key]
        if (!Array.isArray(col)) {
          err(`${id}: calcTail returned no array for plot '${plot.key}'.`)
          continue
        }
        if (col.length !== bars.length - from) {
          err(
            `${id}: calcTail returned ${col.length} values for plot '${plot.key}', ` +
              `expected ${bars.length - from} for indices [${from}, ${bars.length}).`
          )
          continue
        }
        const a = full[plot.key][from]
        const b = col[0]
        const same = (a === null || a === undefined) === (b === null || b === undefined)
        if (same && typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) > 1e-9) {
          err(
            `${id}: calcTail disagrees with calc at index ${from} for plot '${plot.key}' ` +
              `(${a} vs ${b}). The live chart would drift from what a reload shows.`
          )
        }
      }
    }
  }

  note(`${id} (${d.name}): ${d.plots.length} plot(s), ${d.inputs.length} input(s), placement '${d.placement}'`)
}

function report(install, candidate, registered = []) {
  const name = basename(candidate)
  console.log(`\nValidating ${name}\n${'-'.repeat(60)}`)
  for (const n of notes) console.log(`  registered  ${n}`)
  if (warnings.length > 0) {
    console.log('')
    for (const w of warnings) console.log(`  WARNING  ${w}`)
  }
  if (errors.length > 0) {
    console.log('')
    for (const e of errors) console.log(`  ERROR    ${e}`)
  }
  console.log('')

  if (errors.length > 0) {
    console.log(`FAILED: ${errors.length} error(s), ${warnings.length} warning(s). Not installed.`)
    process.exit(1)
  }

  console.log(`PASSED: ${registered.length} indicator(s), ${warnings.length} warning(s).`)
  if (install) {
    mkdirSync(INSTALL_DIR, { recursive: true })
    const dest = join(INSTALL_DIR, name)
    copyFileSync(candidate, dest)
    console.log(`Installed to strategies/indicators/${name}`)
    console.log('Hard-refresh /trading to pick it up.')
  } else {
    console.log('Re-run with --install to copy it into strategies/indicators/.')
  }
  process.exit(0)
}

await main()
