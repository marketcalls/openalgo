/**
 * The committed chart indicator catalogue, and the tier boundary it exists for.
 *
 * `docs/prompt/indicators/chart-indicators.md` is what tells the agent which
 * indicators the `/trading` chart can DRAW. It is committed rather than
 * generated on demand, because a production server has no Node.js and a plain
 * `git pull` has to be enough to upgrade the UI. That is also how it goes
 * stale: bump `openalgo-charts`, gain an indicator, and nothing anywhere
 * notices that the list the model is being handed no longer matches the
 * registry the chart is running.
 *
 * So this regenerates it from the real registry and compares. The rendering
 * comes from the generator itself rather than being restated here, or the two
 * would drift and the comparison would start proving nothing.
 *
 * The tier boundary is the whole reason the file exists. Asked to add
 * AlphaTrend, the agent consulted the only catalogue it had, the Python
 * `openalgo.ta` one, and reported that the chart did not have it. The chart
 * does. The two lists overlap and neither contains the other, so the last test
 * pins a name from each side of that gap.
 */

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { catalogue, OUT, render } from '../../../scripts/generate-chart-indicators.mjs'

/** The committed file, with Windows checkouts normalised to what the generator writes. */
function committed(): string {
  return readFileSync(OUT, 'utf8').replace(/\r\n/g, '\n')
}

describe('the committed chart indicator catalogue', () => {
  it('is exactly what the live openalgo-charts registry generates', async () => {
    const rows = await catalogue()
    expect(rows.length).toBeGreaterThan(0)
    expect(render(rows)).toBe(committed())
  })

  it('lists every registered indicator and invents none', async () => {
    const rows = await catalogue()
    const listed = [...committed().matchAll(/^- `([a-z0-9-]+)` /gm)].map((m) => m[1])
    expect(listed.sort()).toEqual(rows.map((row) => row.id).sort())
    expect(committed()).toContain(`${rows.length} indicators.`)
  })

  it('carries the names the Python indicator catalogue does not have', async () => {
    const ids = new Set((await catalogue()).map((row) => row.id))
    // The failure this file was written for: both of these are drawable and
    // neither is in `openalgo.ta`, so a refusal read off the Python list is
    // wrong about the chart.
    expect(ids.has('alphatrend')).toBe(true)
    expect(ids.has('halftrend')).toBe(true)
    // And the other direction, so the boundary is pinned from both sides:
    // `openalgo.ta` computes these and the chart cannot draw them.
    expect(ids.has('bbands')).toBe(false)
    expect(ids.has('adxr')).toBe(false)
  })
})
