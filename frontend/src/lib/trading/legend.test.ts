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
    ltp: 24451,
    changePct: -0.02,
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

  it('carries every O/H/L/C/V reading plus the LTP', () => {
    const text = flat(input())
    expect(text).toContain('O 24456.30')
    expect(text).toContain('H 24459.50')
    expect(text).toContain('L 24443.70')
    expect(text).toContain('C 24451.00')
    expect(text).toContain('V 12K')
    expect(text).toContain('LTP 24451.00')
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
    const runs = buildChartLegend(input({ bar: null, ltp: null, changePct: null }))
    expect(runs.map((r) => r.text)).toEqual(['NIFTY25AUG26FUT', '· 15m · NFO · lot 65'])
  })

  it('tones the bar readout by candle direction', () => {
    const up = buildChartLegend(input({ bar: { open: 10, high: 12, low: 9, close: 11 } }))
    const down = buildChartLegend(input({ bar: { open: 11, high: 12, low: 9, close: 10 } }))
    expect(up.find((r) => r.text.startsWith('O'))?.tone).toBe('up')
    expect(down.find((r) => r.text.startsWith('O'))?.tone).toBe('down')
  })

  it('signs the change and tones it by direction', () => {
    const gain = buildChartLegend(input({ changePct: 1.234 })).at(-1)
    const loss = buildChartLegend(input({ changePct: -0.02 })).at(-1)
    expect(gain).toEqual({ text: '+1.23%', tone: 'up' })
    expect(loss).toEqual({ text: '-0.02%', tone: 'down' })
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
