/**
 * Which product a node uses when nobody picked one.
 *
 * MIS squares off at the close; NRML carries. On a cash segment MIS is right -
 * a Flow order on NSE is nearly always intraday. On a derivative it is not: an
 * NFO or MCX position is ordinarily carried, and MIS there is an auto
 * square-off the author never asked for. Every node shipped MIS regardless of
 * segment, so an F&O workflow had to be corrected node by node and any node
 * missed traded intraday without saying so.
 *
 * What follows is a default and not an override. A product the author picked is
 * stored on the node and wins, which is what leaves a deliberately intraday NFO
 * order alone - and what leaves every already-saved workflow sending exactly
 * what it sent before, since the old editor wrote an explicit product onto
 * every node it created.
 */

import { describe, expect, it } from 'vitest'
import {
  DEFAULT_NODE_DATA,
  DERIVATIVE_EXCHANGES,
  EXCHANGES,
  OPTION_NODE_PRODUCT,
  defaultProductForExchange,
} from './constants'

const CASH_AND_INDEX = ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX', 'CRYPTO']

describe('the rule', () => {
  it.each([...DERIVATIVE_EXCHANGES])('carries a position on %s', (exchange) => {
    expect(defaultProductForExchange(exchange)).toBe('NRML')
  })

  it.each(CASH_AND_INDEX)('stays intraday on %s', (exchange) => {
    expect(defaultProductForExchange(exchange)).toBe('MIS')
  })

  it.each(['nfo', ' NFO ', 'NfO'])('reads %s the way the exchange list spells it', (value) => {
    expect(defaultProductForExchange(value)).toBe('NRML')
  })

  it.each(['', '   ', undefined, null])('falls back to intraday for %s', (value) => {
    /** Carrying a position the author expected squared off is the costlier
     * mistake, so a value that names no segment never guesses NRML. */
    expect(defaultProductForExchange(value)).toBe('MIS')
  })

  it('names only exchanges the editor actually offers', () => {
    const offered = new Set(EXCHANGES.map((e) => e.value))
    for (const exchange of DERIVATIVE_EXCHANGES) expect(offered.has(exchange)).toBe(true)
  })

  it('leaves index pseudo-exchanges out', () => {
    /** No order is ever placed on one. Listing them would only make the options
     * nodes look as though they followed their `exchange` field. */
    for (const pseudo of ['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX']) {
      expect(DERIVATIVE_EXCHANGES.has(pseudo)).toBe(false)
    }
  })
})

describe('what a new node ships with', () => {
  it.each([
    'placeOrder',
    'smartOrder',
    'splitOrder',
    'closePositions',
    'positionCheck',
    'openPosition',
    'basketOrder',
    'margin',
  ] as const)('stores no product on %s, so the exchange decides', (node) => {
    /** A stored MIS is indistinguishable from a chosen one, so shipping it
     * would pin every node to intraday before its exchange was even picked. */
    expect(DEFAULT_NODE_DATA[node]).not.toHaveProperty('product')
  })

  it.each(['optionsOrder', 'optionsMultiOrder'] as const)('carries on %s', (node) => {
    /** An option is a derivative whatever the node's `exchange` says - that
     * field names where the underlying is quoted (NSE_INDEX), not where the
     * option trades. */
    expect(DEFAULT_NODE_DATA[node].product).toBe(OPTION_NODE_PRODUCT)
    expect(OPTION_NODE_PRODUCT).toBe('NRML')
    expect(defaultProductForExchange(DEFAULT_NODE_DATA[node].exchange)).toBe('MIS')
  })
})
