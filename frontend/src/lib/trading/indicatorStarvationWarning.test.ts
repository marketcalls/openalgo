import { describe, expect, it } from 'vitest'
import { TradingTerminal } from './terminal'

// warnIfStarved is private and needs nothing from a live chart: give it the two
// fields it reads and call it directly.
type Warn = (
  inst: { name: string; values(): Record<string, unknown> },
  descriptor?: { plots?: readonly { style?: { visible?: boolean } }[] }
) => void

function warnedBy(
  values: Record<string, unknown>,
  descriptor?: { plots?: readonly { style?: { visible?: boolean } }[] }
): string[] {
  const toasts: string[] = []
  const self = { rawBars: [{}, {}], toast: (message: string) => toasts.push(message) }
  const warn = (TradingTerminal.prototype as unknown as { warnIfStarved: Warn }).warnIfStarved
  warn.call(self as never, { name: 'Thing', values: () => values }, descriptor)
  return toasts
}

describe('warnIfStarved', () => {
  it('warns when a plotted indicator produced nothing', () => {
    const plots = [{ style: { color: '#fff' } }]
    expect(warnedBy({ ma: [null, null] }, { plots })).toHaveLength(1)
  })

  it('stays quiet for an indicator that draws through its own primitive', () => {
    // Every plot hidden: the columns are placeholders, so empty is correct and
    // permanent. This is the OI Profile shape.
    const plots = [{ style: { visible: false } }]
    expect(warnedBy({ ph: [null, null] }, { plots })).toHaveLength(0)
  })

  it('still warns when only some plots are hidden', () => {
    const plots = [{ style: { visible: false } }, { style: { color: '#fff' } }]
    expect(warnedBy({ a: [null, null], b: [null, null] }, { plots })).toHaveLength(1)
  })

  it('warns when the descriptor is unknown', () => {
    expect(warnedBy({ ma: [null, null] })).toHaveLength(1)
  })
})
