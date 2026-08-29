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

import { CandleBuilder } from 'openalgo-charts'
import { describe, expect, it } from 'vitest'

import { priceDp } from './format'
import { dedupeIndicators, productOptionsFor, resolveTick, usesLots } from './terminal'

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

/**
 * Where the forming bar's volume comes from.
 *
 * The terminal holds exactly one subscription per symbol, and for anything
 * tradeable that is Depth. A depth payload carries `ltp` but no last-traded
 * quantity, so the builder's 'ltq-sum' mode has nothing to accumulate and the
 * live bar reads 0 on a symbol that is visibly trading. The dual LTP+Depth
 * subscribe that would supply ltq is not an option: brokers whose adapters
 * track one mode per symbol froze the chart on it (issue #1664).
 *
 * So the periodic history reconcile supplies that one field. These cases pin
 * why it re-seeds the builder instead of patching `rawBars` alone.
 */
describe('forming-bar volume', () => {
  const BUCKET = 60
  const bar = (time: number, volume: number) => ({
    time,
    open: 100,
    high: 100,
    low: 100,
    close: 100,
    volume,
  })

  it('stays at zero on a depth-only feed, however many ticks arrive', () => {
    const b = new CandleBuilder({ intervalSec: BUCKET, volumeMode: 'ltq-sum' })
    b.seed(bar(0, 5000))
    // Depth gives a price and no ltq, which is the whole problem.
    b.onTick({ time: BUCKET, price: 101 })
    b.onTick({ time: BUCKET + 30, price: 102 })
    expect(b.current()?.volume).toBe(0)
  })

  it('survives the next tick once re-seeded from history', () => {
    const b = new CandleBuilder({ intervalSec: BUCKET, volumeMode: 'ltq-sum' })
    b.seed(bar(0, 5000))
    b.onTick({ time: BUCKET, price: 101 })
    const cur = b.current()
    expect(cur?.volume).toBe(0)

    // What the reconcile does with the history reading for this bucket.
    b.seed({ ...cur!, volume: 4200 })
    const u = b.onTick({ time: BUCKET + 40, price: 103 })

    // Patching rawBars without re-seeding would lose this: the builder folds
    // the tick into its own copy and writes the stale 0 straight back.
    expect(u?.bar.volume).toBe(4200)
    expect(u?.isNew).toBe(false)
    // The ticks still own the price. History is a poll and lags them.
    expect(u?.bar.close).toBe(103)
  })

  it('starts the next bar clean rather than carrying the correction forward', () => {
    const b = new CandleBuilder({ intervalSec: BUCKET, volumeMode: 'ltq-sum' })
    b.seed(bar(0, 0))
    b.onTick({ time: BUCKET, price: 101 })
    b.seed({ ...b.current()!, volume: 4200 })
    const u = b.onTick({ time: BUCKET * 2, price: 104 })
    expect(u?.isNew).toBe(true)
    expect(u?.bar.volume).toBe(0)
  })
})

describe('resolveTick', () => {
  // Values taken from the live master contract.
  it.each([
    ['NSE_INDEX', 0.0005],
    ['BSE_INDEX', 0.0001],
    ['MCX_INDEX', 0.0005],
    ['GLOBAL_INDEX', 0.0001],
  ])('pins %s to paise, whatever tick the feed supplies', (exchange, fed) => {
    // A sub-paise tick put four decimals on the axis, so NIFTY read 24175.6500.
    expect(resolveTick(exchange, fed)).toBe(0.05)
    expect(priceDp(resolveTick(exchange, fed), 24175)).toBe(2)
  })

  it('leaves a tradeable instrument its real tick', () => {
    expect(resolveTick('NSE', 0.1)).toBe(0.1)
    expect(resolveTick('NFO', 0.05)).toBe(0.05)
  })

  it('keeps four decimals for a currency pair, which genuinely quotes in them', () => {
    // The reason this is exchange-scoped rather than a blanket clamp on fine
    // ticks: USDINR at 0.0025 must keep its precision.
    expect(resolveTick('CDS', 0.0025)).toBe(0.0025)
    expect(priceDp(resolveTick('CDS', 0.0025), 87)).toBe(4)
  })

  it('falls back when the master contract carries nothing usable', () => {
    expect(resolveTick('NSE', 0)).toBe(0.05)
    expect(resolveTick('NSE', undefined)).toBe(0.05)
    expect(resolveTick('NSE', 'nonsense')).toBe(0.05)
  })
})

describe('dedupeIndicators', () => {
  const ema = (period: number) => ({ indicatorId: 'ema', settings: { period } })

  it('collapses an exact repeat, which can only be an accident', () => {
    // Two overlapping symbol loads re-applied the tracked list against one
    // chart, and the doubled list was persisted and doubled again on every
    // rebuild: thirty identical legend rows covering the chart.
    const doubled = [ema(20), ema(20), ema(20)]
    expect(dedupeIndicators(doubled)).toEqual([ema(20)])
  })

  it('keeps two instances that differ in their settings', () => {
    // A 20 and a 50 EMA is a normal thing to want, and they are told apart on
    // the chart, so neither is an accident.
    const pair = [ema(20), ema(50)]
    expect(dedupeIndicators(pair)).toEqual(pair)
  })

  it('keeps different indicators sharing settings', () => {
    const mixed = [
      { indicatorId: 'ema', settings: { period: 20 } },
      { indicatorId: 'sma', settings: { period: 20 } },
    ]
    expect(dedupeIndicators(mixed)).toEqual(mixed)
  })

  it('preserves the order the first of each appeared in', () => {
    const list = [ema(50), ema(20), ema(50), ema(20)]
    expect(dedupeIndicators(list)).toEqual([ema(50), ema(20)])
  })

  it('leaves an empty list alone', () => {
    expect(dedupeIndicators([])).toEqual([])
  })
})
