/**
 * The OHLC readout is built once and rendered twice — into the DOM overlay on
 * the pane, and onto the canvas the PNG export paints. openalgo-charts'
 * `takeScreenshot()` composites only its own pane canvases, so before this
 * builder existed the saved image had no symbol and no O/H/L/C at all; these
 * cases are what keeps the two renderers quoting the same numbers.
 */

import { describe, expect, it } from 'vitest'

import {
  buildChartLegend,
  DN,
  type LegendInput,
  LTP_NEUTRAL,
  legendHtml,
  legendToneStyle,
  lotInfoText,
  UP,
} from './legend'

const fmt = (n: number) => n.toFixed(2)
const fmtVolume = (n: number) => `${n / 1000}K`

function input(patch: Partial<LegendInput> = {}): LegendInput {
  return {
    symbol: 'NIFTY25AUG26FUT',
    interval: '15m',
    exchange: 'NFO',
    lotsize: 65,
    bar: { open: 24456.3, high: 24459.5, low: 24443.7, close: 24451, volume: 12000 },
    prevClose: 24455.5,
    fmt,
    fmtVolume,
    ...patch,
  }
}

/** The runs as one string, i.e. what the reader ends up seeing. */
const flat = (i: LegendInput) =>
  buildChartLegend(i)
    .map((r) => r.text)
    .join(' ')

describe('buildChartLegend', () => {
  it('names the instrument, its timeframe and its exchange', () => {
    expect(flat(input())).toContain('NIFTY25AUG26FUT · 15m · NFO')
  })

  it('carries every O/H/L/C/V reading for the bar it describes', () => {
    const text = flat(input())
    expect(text).toContain('O 24456.30')
    expect(text).toContain('H 24459.50')
    expect(text).toContain('L 24443.70')
    expect(text).toContain('C 24451.00')
    expect(text).toContain('V 12K')
    // No LTP and no day change: every number in the line belongs to this bar.
    expect(text).not.toContain('LTP')
  })

  it('shows the lot size only for a lot-based instrument', () => {
    expect(flat(input())).toContain('· lot 65')
    expect(flat(input({ lotsize: null }))).not.toContain('lot')
  })

  it('omits volume when the chart type does not carry one', () => {
    // Renko and point-and-figure elements are not one bar each.
    expect(flat(input({ bar: { open: 1, high: 2, low: 0.5, close: 1.5 } }))).not.toContain(' V ')
    expect(
      flat(input({ bar: { open: 1, high: 2, low: 0.5, close: 1.5, volume: 0 } }))
    ).not.toContain(' V ')
  })

  it('still names the instrument before any bar or price has arrived', () => {
    const runs = buildChartLegend(input({ bar: null, prevClose: null }))
    expect(runs.map((r) => r.text)).toEqual(['NIFTY25AUG26FUT', '· 15m · NFO · lot 65'])
  })

  it('tones the bar readout by candle direction', () => {
    const up = buildChartLegend(input({ bar: { open: 10, high: 12, low: 9, close: 11 } }))
    const down = buildChartLegend(input({ bar: { open: 11, high: 12, low: 9, close: 10 } }))
    expect(up.find((r) => r.text.startsWith('O'))?.tone).toBe('up')
    expect(down.find((r) => r.text.startsWith('O'))?.tone).toBe('down')
  })

  it("reports the bar's own change, absolute and percent, signed and toned", () => {
    // close 24451 against a previous close of 24455.5: down 4.50, or 0.02%.
    expect(buildChartLegend(input()).at(-1))
      .toEqual({ text: '-4.50 (-0.02%)', tone: 'down' })
    // close 24451 against 24400: up 51.00, or 0.21%.
    expect(buildChartLegend(input({ prevClose: 24400 })).at(-1))
      .toEqual({ text: '+51.00 (+0.21%)', tone: 'up' })
  })

  it('shows no change at all when there is no bar behind this one', () => {
    // The first bar of the loaded history. A change from zero would be a lie,
    // and a change of zero would claim the price did not move.
    const runs = buildChartLegend(input({ prevClose: null }))
    expect(runs.some((r) => r.text.includes('%'))).toBe(false)
  })

  it('carries no padding of its own, so both renderers space the runs', () => {
    for (const run of buildChartLegend(input())) expect(run.text).toBe(run.text.trim())
  })
})

describe('legendHtml', () => {
  it('leaves the symbol on the inherited theme colour and dims the meta', () => {
    const html = legendHtml(buildChartLegend(input()))
    expect(html).toContain('<b>NIFTY25AUG26FUT</b>')
    expect(html).toContain('opacity:.55')
  })

  it('escapes text rather than letting it reach the DOM as markup', () => {
    expect(legendHtml([{ text: '<img src=x onerror=alert(1)>', tone: 'symbol' }])).toBe(
      '<b>&lt;img src=x onerror=alert(1)&gt;</b>'
    )
  })
})

describe('legendToneStyle', () => {
  it('paints the symbol in the app foreground it is given', () => {
    expect(legendToneStyle('symbol', 'rgb(1,2,3)')).toEqual({ color: 'rgb(1,2,3)', alpha: 1 })
  })

  it('dims the meta to the same opacity the overlay uses', () => {
    expect(legendToneStyle('meta', 'rgb(1,2,3)')).toEqual({ color: 'rgb(1,2,3)', alpha: 0.55 })
  })

  it('keeps the direction and last-price colours theme-independent', () => {
    expect(legendToneStyle('up', '#fff').color).toBe(UP)
    expect(legendToneStyle('down', '#fff').color).toBe(DN)
    expect(legendToneStyle('ltp', '#fff').color).toBe(LTP_NEUTRAL)
  })
})

describe('lotInfoText', () => {
  const fno = { lots: true, lotsize: 65, freezeQty: 1800, quoteOnly: false }

  it('spells out what the lots come to in quantity', () => {
    expect(lotInfoText(fno, 1)).toBe('1 × 65 = 65 qty')
    expect(lotInfoText(fno, 3)).toBe('3 × 65 = 195 qty')
  })

  it('warns once the order crosses the exchange freeze quantity', () => {
    expect(lotInfoText(fno, 30)).toContain('freeze 1800')
  })

  it('says nothing for cash equity and marks an index as quote-only', () => {
    expect(lotInfoText({ lots: false, lotsize: 1, freezeQty: 1, quoteOnly: false }, 1)).toBe('')
    expect(lotInfoText({ lots: false, lotsize: 1, freezeQty: 1, quoteOnly: true }, 1)).toBe(
      'quote-only (no trading)'
    )
  })

  it('has nothing to say without an instrument', () => {
    expect(lotInfoText(null, 1)).toBe('')
  })
})

/**
 * The volume readout is also the switch for the bars it reads.
 *
 * A toggle existed all along, in the right-click menu, which is a place you
 * have to already suspect it to find: it was reported as "no provision to turn
 * off the volume". Splitting the volume off the OHLC run is what lets it carry
 * a control, so the two must stay separate.
 */
describe('volume is its own legend run', () => {
  const input = (over: Partial<Parameters<typeof buildChartLegend>[0]> = {}) => ({
    symbol: 'RELIANCE',
    interval: '5m',
    exchange: 'NSE',
    lotsize: null,
    bar: { open: 100, high: 104, low: 99, close: 103, volume: 126_300 },
    prevClose: 99,
    fmt: (n: number) => n.toFixed(2),
    fmtVolume: () => '126.30K',
    ...over,
  })

  it('does not fuse the volume into the OHLC run', () => {
    const runs = buildChartLegend(input() as Parameters<typeof buildChartLegend>[0])
    const ohlc = runs.find((r) => r.text.startsWith('O '))
    expect(ohlc?.text).not.toContain('V ')
    const vol = runs.find((r) => r.action === 'volume')
    expect(vol?.text).toBe('V 126.30K')
  })

  it('renders the volume run as a control, and the others as plain text', () => {
    const html = legendHtml(buildChartLegend(input() as Parameters<typeof buildChartLegend>[0]))
    expect(html).toContain('data-legend-action="volume"')
    expect(html).toContain('Hide volume')
    // One control only: the readout must not become a row of buttons.
    expect(html.match(/data-legend-action/g)).toHaveLength(1)
  })

  it('says which way the switch is set when the bars are off', () => {
    const runs = buildChartLegend(
      input({ volumeHidden: true }) as Parameters<typeof buildChartLegend>[0]
    )
    expect(runs.find((r) => r.action === 'volume')?.dim).toBe(true)
    const html = legendHtml(runs)
    expect(html).toContain('line-through')
    expect(html).toContain('Show volume')
  })

  it('emits no volume run at all on a transformed chart type', () => {
    // Renko and point-and-figure elements are not one bar each, so there is no
    // volume to read and nothing to switch.
    const runs = buildChartLegend(
      input({ bar: { open: 100, high: 104, low: 99, close: 103 } }) as Parameters<
        typeof buildChartLegend
      >[0]
    )
    expect(runs.some((r) => r.action === 'volume')).toBe(false)
    expect(legendHtml(runs)).not.toContain('data-legend-action')
  })
})
