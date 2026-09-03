/**
 * Generate the chart indicator catalogue the agent reads.
 *
 * The chart draws with `openalgo-charts`, a JavaScript library, while the agent
 * computes values with `openalgo.ta`, a Python one. They are different
 * catalogues that happen to share a domain: measured here, 102 names against
 * 127, with only 39 in common once naming is normalised. So `alphatrend` and
 * `halftrend` can be DRAWN and never tabulated, and `bbands` and `adxr` can be
 * tabulated and never drawn.
 *
 * Without this file the Python side has no idea which is which. Asked to add
 * AlphaTrend to a chart it consulted the only list it had, the Python one, and
 * reported that the chart's catalogue did not contain it. It does. That failure
 * is the reason this file exists.
 *
 * It is committed rather than generated on demand, for the same reason the
 * OpenUI prompt is: a production server has no Node.js, and a plain `git pull`
 * has to be enough to upgrade the UI.
 *
 * `chartIndicators.test.ts` regenerates and compares, so an `openalgo-charts`
 * upgrade that adds or renames an indicator fails CI here instead of silently
 * leaving the agent describing a catalogue it is no longer being given.
 *
 * Run: node scripts/generate-chart-indicators.mjs
 */

import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, '..', '..', 'docs', 'prompt', 'indicators', 'chart-indicators.md')

/** Read the registry the chart itself uses, after the built-ins register. */
async function catalogue() {
  // The side-effect import is what populates the registry; without it
  // registeredIndicators() answers with an empty set and this file would be
  // generated as a catalogue of nothing.
  await import('openalgo-charts/indicators')
  const core = await import('openalgo-charts')
  const registered = core.registeredIndicators()
  const rows = Array.isArray(registered) ? registered : Object.values(registered)

  return rows
    .map((entry) => (typeof entry === 'string' ? { id: entry } : entry))
    .filter((entry) => entry && entry.id)
    .map((entry) => ({
      id: entry.id,
      name: entry.name || entry.id,
      category: entry.category || 'Other',
      placement: entry.placement || 'pane',
    }))
    .sort((a, b) => a.id.localeCompare(b.id))
}

const rows = await catalogue()
if (rows.length === 0) {
  console.error('No indicators found. Did openalgo-charts/indicators fail to import?')
  process.exit(1)
}

const byCategory = new Map()
for (const row of rows) {
  if (!byCategory.has(row.category)) byCategory.set(row.category, [])
  byCategory.get(row.category).push(row)
}

const lines = [
  '# Chart indicator catalogue',
  '',
  'GENERATED FILE. Do not edit by hand.',
  'Run `node frontend/scripts/generate-chart-indicators.mjs` to regenerate.',
  '',
  'These are the indicators the `/trading` chart can DRAW, from `openalgo-charts`.',
  'They are not the same set as the Python `openalgo.ta` indicators, which compute',
  'VALUES and answer questions like "what is the RSI now". A name in one list is',
  'not necessarily in the other.',
  '',
  `${rows.length} indicators.`,
  '',
]

for (const category of [...byCategory.keys()].sort()) {
  const entries = byCategory.get(category)
  lines.push(`## ${category}`, '')
  for (const entry of entries) {
    const where = entry.placement === 'onchart' ? 'on the price' : 'own pane'
    lines.push(`- \`${entry.id}\` ${entry.name} (${where})`)
  }
  lines.push('')
}

writeFileSync(OUT, `${lines.join('\n')}\n`, 'utf8')
console.log(`Wrote ${rows.length} indicators to ${OUT}`)
