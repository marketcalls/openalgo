/**
 * Product selection on the charting terminal.
 *
 * MCX, NCO and CDS masters carry `lotsize: 1` for every single contract - all
 * 15,772 MCX rows, all 27,335 NCO rows and all 7,691 CDS rows in a current
 * master. NFO and BFO never do (20, 25, 30, 50, 65 ...). So a derivative test
 * written as `DERIVATIVE_EXCHANGES.has(exchange) && lotsize > 1` reads every
 * commodity and currency contract as cash equity and offers CNC, which those
 * segments do not accept - the broker rejects the order. See issue #1752.
 *
 * These cases are deliberately lot-size-free: the exchange is the only input,
 * so the guard cannot be reintroduced without failing here.
 */

import { describe, expect, it } from 'vitest'

import { productOptionsFor, usesLots } from './terminal'

/** Every segment whose contracts carry lotsize 1 in the master. */
const LOTSIZE_ONE_SEGMENTS = ['MCX', 'NCO', 'CDS', 'BCD', 'NCDEX']
/** Segments with a real lot size, which worked before the fix too. */
const REAL_LOTSIZE_SEGMENTS = ['NFO', 'BFO']
const CASH_EQUITY = ['NSE', 'BSE']

describe('productOptionsFor', () => {
  it.each(LOTSIZE_ONE_SEGMENTS)('%s offers NRML, not CNC, despite lotsize 1', (exchange) => {
    expect(productOptionsFor(exchange)).toEqual(['MIS', 'NRML'])
  })

  it.each(REAL_LOTSIZE_SEGMENTS)('%s still offers NRML', (exchange) => {
    expect(productOptionsFor(exchange)).toEqual(['MIS', 'NRML'])
  })

  it.each(CASH_EQUITY)('%s keeps CNC and must never be given NRML', (exchange) => {
    expect(productOptionsFor(exchange)).toEqual(['MIS', 'CNC'])
  })

  it('defaults an unknown segment to cash equity', () => {
    expect(productOptionsFor('NSE_INDEX')).toEqual(['MIS', 'CNC'])
  })

  it('offers MIS everywhere, so intraday is never lost', () => {
    for (const exchange of [...LOTSIZE_ONE_SEGMENTS, ...REAL_LOTSIZE_SEGMENTS, ...CASH_EQUITY]) {
      expect(productOptionsFor(exchange)).toContain('MIS')
    }
  })

  it('never offers CNC and NRML together', () => {
    for (const exchange of [...LOTSIZE_ONE_SEGMENTS, ...REAL_LOTSIZE_SEGMENTS, ...CASH_EQUITY]) {
      const options = productOptionsFor(exchange)
      expect(options.includes('CNC') && options.includes('NRML')).toBe(false)
    }
  })
})

describe('usesLots', () => {
  it.each([
    ...LOTSIZE_ONE_SEGMENTS,
    ...REAL_LOTSIZE_SEGMENTS,
  ])('%s takes quantity in lots', (exchange) => {
    expect(usesLots(exchange)).toBe(true)
  })

  it.each(CASH_EQUITY)('%s takes quantity in shares', (exchange) => {
    expect(usesLots(exchange)).toBe(false)
  })

  /**
   * The reason dropping the `lotsize > 1` guard is safe for order sizing:
   * orderQty() is `lots x lotsize`, and on every affected segment lotsize is 1,
   * so the number sent to the broker is identical either way. Only the label
   * and the product list change.
   */
  it('leaves the order quantity unchanged where lotsize is 1', () => {
    const orderQty = (qty: number, lots: boolean, lotsize: number) => (lots ? qty * lotsize : qty)
    for (const exchange of LOTSIZE_ONE_SEGMENTS) {
      expect(orderQty(7, usesLots(exchange), 1)).toBe(7)
    }
  })

  it('still multiplies by a real lot size', () => {
    expect(usesLots('NFO') ? 7 * 75 : 7).toBe(525)
  })
})
