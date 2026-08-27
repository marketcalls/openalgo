#!/usr/bin/env node
/**
 * Coverage check for the chart-indicator skill.
 *
 * Two levels, and the second is the one that matters:
 *
 *   NAMED       the export appears somewhere in the reference docs
 *   DEMONSTRATED the export appears inside a fenced code block or an example
 *
 * An earlier version of this check only tested NAMED, and reported 100% while
 * `getIndicator` was documented as "look one up" and the technique that makes it
 * useful (calling a built-in's own `calc` instead of porting its formula) was
 * taught nowhere. Being mentioned in a table is not the same as being teachable.
 *
 * Usage: node .claude/skills/chart-indicator/coverage.mjs
 */

import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SKILL = import.meta.dirname
const REPO = resolve(SKILL, '..', '..', '..')
const CHARTS = join(REPO, 'frontend', 'node_modules', 'openalgo-charts')

/**
 * The subset an indicator author actually calls.
 *
 * Deliberately not "every export": the API object also carries Chart, panes,
 * feeds, replay and the trading controller, which an indicator has no business
 * touching. Holding those to a demonstrated standard would be noise, and noise
 * is how a check stops being read.
 */
const AUTHOR_FACING = [
  // registration and reuse
  'registerIndicator', 'createTier2Indicator', 'getIndicator', 'hasIndicator',
  'indicatorDefaults', 'registeredIndicators',
  // reading bars
  'sourceValues', 'sourceValue', 'INDICATOR_SOURCES',
  // averages
  'sma', 'wma', 'rma', 'ema', 'smaSeededEma', 'alma', 'vwma', 'swma',
  // extremes and running totals
  'highest', 'lowest', 'highestBars', 'lowestBars', 'rollingSum', 'cumulative',
  // statistics
  'stdev', 'dev', 'linreg', 'percentRank', 'percentileNearestRank', 'correlation',
  'stoch', 'cci', 'roc', 'change', 'connorsStreak', 'nulls',
  // ohlc studies
  'trueRange', 'atr', 'rsi', 'supertrend', 'pivotHigh', 'pivotLow',
  // sessions and calendar
  'parseSessionSpec', 'inSessionAt', 'sessionFlags', 'sessionStartFlags',
  'calendarPeriodFlags', 'utcSecondsToZonedParts', 'zonedDayIndex',
  'isValidTimezone', 'DEFAULT_TIMEZONE', 'isNewZonedDay',
  // timeframes
  'intervalParts', 'isIntradayInterval', 'isDailyInterval', 'isSecondsInterval',
  'isTickInterval',
  // colour, rounding, formatting
  'withAlpha', 'fromGradient', 'roundToTick', 'precisionForStep', 'compactVolume', 'clamp',
]

/**
 * Capabilities, as opposed to call names. A function can be demonstrated while
 * the feature built on it is not: `plot.type` is never an export, and neither
 * is `extendRight` or `isConfirmed`, yet each is something an author has to be
 * shown. Everything added across 1.7.1, 1.8.1 and 1.8.2 is listed here so a
 * release cannot land with the skill silently behind it.
 */
const CAPABILITIES = [
  ["plot type 'line'", "type: 'line'"],
  ["plot type 'line-markers'", "'line-markers'"],
  ["plot type 'step'", "'step'"],
  ["plot type 'area'", "'area'"],
  ["plot type 'histogram'", "'histogram'"],
  ["plot type 'column'", "'column'"],
  ["plot type 'candlestick' via ohlc", "'candlestick'"],
  ['markers-only plots (the circles style)', 'markersOnly'],
  ['marker radius', 'markerRadius'],
  ['dashed plots', "lineStyle: 'dashed'"],
  ['hidden plots', 'visible: false'],
  ['a plot on its own axis', 'priceScaleId'],
  ['per-bar plot colour', 'colorBy'],
  ['plot colour from an input', 'colorKey'],
  ['draws: line', "kind: 'line'"],
  ['draws: box', "kind: 'box'"],
  ['draws: label', "kind: 'label'"],
  ['draws: polyline', "kind: 'polyline'"],
  ['ray extension', 'extendRight'],
  ['levels with data', 'levels(ctx'],
  ['level line width and style', 'lineStyle: '],
  ['one plot on the price pane', 'overlay: true'],
  ['gradient fills', 'gradient'],
  ['fills between plots', 'between:'],
  ['background shading', 'background('],
  ['recolouring the price candles', 'barColors('],
  ['candle plots from four columns', 'ohlc:'],
  ['declared alerts', 'alerts:'],
  ['the alert predicate', 'when:'],
  ['bar state: isNew', 'isNew'],
  ['bar state: isConfirmed', 'isConfirmed'],
  ['bar state: isRealtime', 'isRealtime'],
  ['the calc context', 'store, ctx'],
  ['the instrument tick', 'ctx?.tickSize'],
  ['markers', 'markers('],
  ['marker at an explicit price', "position: 'atPrice'"],
  ['label markers', "shape: 'labelUp'"],
  ['tables', 'table('],
  ['table cell colours', 'bgColor'],
  ['table position', "position: 'top-right'"],
  ['incremental recompute', 'calcTail'],
  ['external data', 'createTier2Indicator'],
  ['the attach lifecycle', 'attach('],
  ['grouped inputs', "group: '"],
  ["input 'number'", "type: 'number'"],
  ["input 'boolean'", "type: 'boolean'"],
  ["input 'color'", "type: 'color'"],
  ["input 'text'", "type: 'text'"],
  ["input 'select'", "type: 'select'"],
  ["input 'source'", "type: 'source'"],
  ["input 'session'", "type: 'session'"],
  ["input 'timeframe'", "type: 'timeframe'"],
  ["input 'symbol'", "type: 'symbol'"],
  ["input 'price'", "type: 'price'"],
  ["input 'time'", "type: 'time'"],
]

const DOCS = ['SKILL.md', 'reference/contract.md', 'reference/api.md',
              'reference/pitfalls.md', 'reference/cookbook.md']

const read = (p) => (existsSync(p) ? readFileSync(p, 'utf8') : '')

const docFiles = DOCS.map((n) => read(join(SKILL, n)))
const prose = docFiles.join('\n')
const fenced = docFiles
  .flatMap((d) => [...d.matchAll(/```[\s\S]*?```/g)].map((m) => m[0]))
  .join('\n')
const exampleDir = join(SKILL, 'examples')
const examples = existsSync(exampleDir)
  ? readdirSync(exampleDir).filter((f) => f.endsWith('.js'))
      .map((f) => read(join(exampleDir, f))).join('\n')
  : ''
const demonstrated = `${fenced}\n${examples}`

const named = AUTHOR_FACING.filter((n) => !prose.includes(n))
const shown = AUTHOR_FACING.filter((n) => !demonstrated.includes(n))

console.log(`author-facing API: ${AUTHOR_FACING.length}`)
console.log(`  named in the docs   : ${AUTHOR_FACING.length - named.length}/${AUTHOR_FACING.length}`)
console.log(`  demonstrated in code: ${AUTHOR_FACING.length - shown.length}/${AUTHOR_FACING.length}`)

// Every name on the real build must also be reachable in the reference, so a
// new export cannot land unmentioned.
let unlisted = []
if (existsSync(join(CHARTS, 'dist', 'openalgo-charts.mjs'))) {
  const core = await import(pathToFileURL(join(CHARTS, 'dist', 'openalgo-charts.mjs')).href)
  const tier = await import(pathToFileURL(join(CHARTS, 'dist', 'openalgo-charts.indicators.mjs')).href)
  const all = Object.keys({ ...core, ...tier })
  unlisted = all.filter((n) => !prose.includes(n))
  console.log(`  every export named   : ${all.length - unlisted.length}/${all.length} (openalgo-charts ${core.VERSION})`)
}

const missingCaps = CAPABILITIES.filter(([, t]) => !demonstrated.includes(t))
console.log(`  capabilities shown  : ${CAPABILITIES.length - missingCaps.length}/${CAPABILITIES.length}`)

const fail = named.length + shown.length + unlisted.length + missingCaps.length
if (named.length) console.log(`\nNOT NAMED (${named.length}): ${named.join(', ')}`)
if (shown.length) console.log(`\nNAMED BUT NEVER DEMONSTRATED (${shown.length}): ${shown.join(', ')}`)
if (unlisted.length) console.log(`\nEXPORTS MISSING FROM THE REFERENCE (${unlisted.length}): ${unlisted.slice(0, 30).join(', ')}`)

if (missingCaps.length) {
  console.log(`
CAPABILITIES NEVER DEMONSTRATED (${missingCaps.length}):`)
  for (const [what, t] of missingCaps) console.log(`  ${what}  (looked for: ${t})`)
}

console.log(fail === 0 ? '\nCOVERAGE COMPLETE' : `\nGAPS: ${fail}`)
process.exit(fail === 0 ? 0 : 1)
