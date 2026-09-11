#!/usr/bin/env node
/**
 * Regenerate the complete export index in `reference/api.md`.
 *
 * Why this exists
 * ---------------
 *
 * The index was maintained by hand. It was written against openalgo-charts
 * 1.8.1 and still said "All 337 names" through 2.1.5, by which point the real
 * figure was 363: the eleven built-ins added in 1.8.3 and the render-backend
 * exports added in 2.0.0 were invisible to anyone reading it. `coverage.mjs`
 * had caught this the whole time and nothing ran it.
 *
 * So the index is generated, and the categories that grow on their own are
 * detected from the build rather than listed here:
 *
 *   - a built-in indicator is an object carrying an `id` and `plots`/`calc`,
 *     so the next release's new studies classify themselves
 *   - an indicator group is an array of those
 *   - anything this file does not name falls into "chart infrastructure",
 *     which is truthful for an indicator author and, crucially, still *names*
 *     the export so `coverage.mjs` passes
 *
 * That last point is the whole design. A new export can never again be
 * silently missing from the reference; at worst it is filed under a heading
 * that undersells it, which a human can then move.
 *
 * Usage:
 *   node generate-api-index.mjs           rewrite the index in api.md
 *   node generate-api-index.mjs --check   exit 1 if api.md is out of date (CI)
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SKILL = import.meta.dirname
const REPO = resolve(SKILL, '..', '..', '..')
const API_MD = join(SKILL, 'reference', 'api.md')

const BEGIN = '<!-- BEGIN GENERATED EXPORT INDEX -->'
const END = '<!-- END GENERATED EXPORT INDEX -->'

/**
 * Where to find the library. Same order as validate.mjs: the dev copy if a
 * React developer has it, else the validator's own cache. This script is a
 * maintenance tool rather than the author-facing gate, so it does not fetch.
 */
function chartsRoot() {
  const candidates = [
    join(REPO, 'frontend', 'node_modules', 'openalgo-charts'),
    join(SKILL, '.cache', 'node_modules', 'openalgo-charts'),
  ]
  for (const root of candidates) {
    if (existsSync(join(root, 'dist', 'openalgo-charts.mjs'))) return root
  }
  console.error(
    'openalgo-charts not found. Run the validator once to populate .cache/, or\n' +
      'install the frontend dependencies.',
  )
  process.exit(2)
}

/**
 * The curated buckets, in the order an author meets them.
 *
 * These are hand-ordered on purpose: "the things you call to read bars" is a
 * more useful grouping than anything derivable from a name. Names listed here
 * that no longer exist on the build are reported rather than silently dropped,
 * because a removed export is a docs change somebody has to make.
 */
const CURATED = [
  ['Registration and introspection', [
    'registerIndicator', 'createTier2Indicator', 'registeredIndicators', 'getIndicator',
    'hasIndicator', 'indicatorDefaults', 'indicatorStyleInputs', 'plotStyleKeys',
    'registeredChartTypes', 'getChartType', 'registerChartType', 'registerBuiltinIndicators',
    'INDICATORS_TIER',
  ]],
  ['Reading bars', [
    'sourceValues', 'sourceValue', 'INDICATOR_SOURCES', 'toBar', 'mergeBars',
    'conflateBars', 'conflateItems', 'isWhitespace', 'generateBars', 'FakeDataFeed',
  ]],
  ['Moving averages and statistics', [
    'sma', 'wma', 'rma', 'ema', 'smaSeededEma', 'stdev', 'dev', 'highest', 'lowest',
    'highestBars', 'lowestBars', 'rollingSum', 'cumulative', 'linreg', 'swma', 'alma',
    'vwma', 'percentRank', 'percentileNearestRank', 'correlation', 'nulls',
    'connorsStreak', 'change', 'roc', 'stoch', 'cci', 'pivotHigh', 'pivotLow',
  ]],
  ['OHLC studies', [
    'trueRange', 'atr', 'rsi', 'supertrend', 'emaSeries', 'rsiSeries', 'supertrendSeries',
  ]],
  ['Sessions, time and timeframes', [
    'DEFAULT_TIMEZONE', 'IST_OFFSET_SECONDS', 'isValidTimezone', 'utcSecondsToZonedParts',
    'utcSecondsToIstParts', 'zonedDayIndex', 'zonedWeekIndex', 'zoneOffsetSeconds',
    'isNewZonedDay', 'isNewZonedWeek', 'isNewZonedMonth', 'isNewZonedQuarter',
    'isNewZonedYear', 'isNewZonedPeriod', 'isNewIstDay', 'startOfZonedDay',
    'startOfZonedWeek', 'startOfZonedMonth', 'sessionStartFlags', 'sessionStartIndices',
    'calendarPeriodFlags', 'parseSessionSpec', 'inSessionAt', 'sessionFlags',
    'epochMsToUtcSeconds', 'istStringToUtcSeconds', 'zonedStringToUtcSeconds',
    'zonedWallClockToUtcSeconds', 'utcSecondsToIstDateString', 'utcSecondsToZonedDateString',
    'rowTimeToUtcSeconds', 'barCloseSec', 'bucketStartOf', 'nextBucketStart',
    'isTimeBucketed', 'intervalToSeconds', 'intervalParts', 'isIntradayInterval',
    'isDailyInterval', 'isSecondsInterval', 'isTickInterval', 'isKnownInterval',
    'resolveInterval', 'tryResolveInterval', 'registeredIntervals', 'registerInterval',
    'unregisterInterval', 'UnknownIntervalError',
  ]],
  ['Formatting', [
    'formatIstTime', 'formatIstTimeSeconds', 'formatIstDate', 'formatIstCrosshairLabel',
    'formatZonedTime', 'formatZonedTimeSeconds', 'formatZonedDate',
    'formatZonedCrosshairLabel', 'compactVolume', 'precisionForStep',
  ]],
  ['Colours, numbers and geometry', [
    'withAlpha', 'fromGradient', 'verticalGradient', 'clamp', 'lerp', 'roundToTick',
    'niceTicks', 'autoscaleRange', 'optimalBarWidth', 'snapToDevicePixel', 'bitmapSize',
    'dashPattern', 'markerSizePx', 'effectiveMarkerPx', 'drawShape', 'drawLabel',
    'bestHit', 'tableOrigin', 'watermarkRect', 'resolvePlotMargins',
  ]],
  ['Style and option lists', [
    'INDICATOR_LINE_STYLES', 'INDICATOR_PLOT_STYLES', 'PRICE_SCALE_MODES',
    'PRICE_LEVEL_KINDS', 'DEFAULT_THEME', 'darkTheme', 'lightTheme', 'ALT_PRESET',
    'VERSION', 'version', 'CHART_STATE_VERSION', 'DEFAULT_CANDLE_STYLE',
    'DEFAULT_HISTOGRAM_STYLE', 'DEFAULT_TRADING_COLORS', 'resolveCrosshairStyle',
    'resolveGridStyle', 'resolveScaleStyle', 'seriesStyleForLastPriceLevel',
    'lastPriceLevelFromSeriesStyle', 'IndicatorBackground', 'IndicatorFill',
  ]],
]

const isDescriptor = (v) =>
  v && typeof v === 'object' && !Array.isArray(v) && typeof v.id === 'string' &&
  (Array.isArray(v.plots) || typeof v.calc === 'function')

const isDescriptorGroup = (v) => Array.isArray(v) && v.length > 0 && v.every(isDescriptor)

const fence = (names) => names.map((n) => `\`${n}\``).join(', ')

async function main() {
  const dist = join(chartsRoot(), 'dist')
  const core = await import(pathToFileURL(join(dist, 'openalgo-charts.mjs')).href)
  const tier = await import(pathToFileURL(join(dist, 'openalgo-charts.indicators.mjs')).href)
  const api = { ...core, ...tier }
  const version = core.VERSION

  const all = Object.keys(api).sort((a, b) => a.localeCompare(b))
  const taken = new Set()
  const sections = []

  for (const [title, names] of CURATED) {
    const present = names.filter((n) => n in api)
    const gone = names.filter((n) => !(n in api))
    if (gone.length) {
      console.error(`NOTE: ${title} lists ${gone.length} export(s) no longer on the build: ${gone.join(', ')}`)
    }
    present.forEach((n) => taken.add(n))
    sections.push([title, present, null])
  }

  // Shape-detected, so a release that adds studies updates this on its own.
  const descriptors = all.filter((n) => !taken.has(n) && isDescriptor(api[n]))
  descriptors.forEach((n) => taken.add(n))
  sections.push([
    'Built-in indicator descriptors',
    descriptors,
    'Each is the descriptor object itself, identical to `getIndicator(id)` once\n' +
      '`registerBuiltinIndicators()` has run. Call one\'s `calc` instead of porting its\n' +
      'formula: `getIndicator(\'macd\').calc(bars, settings, {})`. These are also the ids\n' +
      'a custom module can accidentally shadow.',
  ])

  const groups = all.filter((n) => !taken.has(n) && isDescriptorGroup(api[n]))
  groups.forEach((n) => taken.add(n))
  sections.push([
    'Built-in indicator groups',
    groups,
    'Arrays of the descriptors above, as the picker rail groups them.',
  ])

  const rest = all.filter((n) => !taken.has(n))
  sections.push([
    'Chart infrastructure, not for indicators',
    rest,
    'Panes, scales, feeds, drawing primitives, trading controllers, link groups, replay\n' +
      'and the render backends. An indicator describes what to compute and what to plot;\n' +
      'the chart owns these.',
  ])

  const body = [
    `All ${all.length} names on the API object, so nothing is a surprise. Generated from`,
    `the installed openalgo-charts@${version} build by \`generate-api-index.mjs\`; do not`,
    'edit this section by hand.',
    '',
  ]
  for (const [title, names, note] of sections) {
    body.push(`**${title}** (${names.length})`, '')
    if (note) body.push(note, '')
    body.push(fence(names), '')
  }

  const generated = `${BEGIN}\n\n${body.join('\n').trimEnd()}\n\n${END}`

  const md = readFileSync(API_MD, 'utf8')
  const start = md.indexOf(BEGIN)
  const stop = md.indexOf(END)
  if (start === -1 || stop === -1) {
    console.error(`Markers not found in ${API_MD}. Expected ${BEGIN} ... ${END}`)
    process.exit(2)
  }
  const next = md.slice(0, start) + generated + md.slice(stop + END.length)

  const total = sections.reduce((n, [, names]) => n + names.length, 0)
  if (total !== all.length) {
    console.error(`Classified ${total} of ${all.length} exports. Refusing to write.`)
    process.exit(2)
  }

  if (process.argv.includes('--check')) {
    if (next !== md) {
      console.error(
        `reference/api.md is out of date for openalgo-charts ${version}.\n` +
          'Run: node .claude/skills/chart-indicator/generate-api-index.mjs',
      )
      process.exit(1)
    }
    console.log(`api.md index is current for openalgo-charts ${version} (${all.length} exports)`)
    return
  }

  writeFileSync(API_MD, next)
  console.log(`Wrote ${all.length} exports for openalgo-charts ${version}:`)
  for (const [title, names] of sections) console.log(`  ${String(names.length).padStart(4)}  ${title}`)
}

await main()
