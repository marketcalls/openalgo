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

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { CandleBuilder } from 'openalgo-charts'
import { describe, expect, it } from 'vitest'

import { priceDp } from './format'
import {
  buildOrderTicket,
  dedupeIndicators,
  ORDER_COOLDOWN_MS,
  orderUnits,
  productOptionsFor,
  resolveTick,
  type SymbolView,
  usesLots,
} from './terminal'

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

  it('CRYPTO is a derivative segment: NRML, never CNC', () => {
    expect(productOptionsFor('CRYPTO')).toEqual(['MIS', 'NRML'])
    expect(usesLots('CRYPTO')).toBe(true)
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

/**
 * One-Click off: a click opens a ticket instead of placing. The ticket has to
 * carry exactly what the armed path would have sent, or a trader who reads
 * the chart, disarms, and confirms is confirming a different order from the
 * one the chart was about to fire. These pin the two against each other
 * through the one sizing function and the one price mapping they share.
 */
describe('orderUnits', () => {
  it('multiplies lots out on a derivative segment', () => {
    expect(orderUnits(2, true, 75)).toBe(150)
  })

  it('passes shares through on cash equity', () => {
    expect(orderUnits(7, false, 1)).toBe(7)
  })

  it('floors to whole lots and never below one', () => {
    expect(orderUnits(2.9, true, 50)).toBe(100)
    expect(orderUnits(0, true, 50)).toBe(50)
    expect(orderUnits(Number.NaN, false, 1)).toBe(1)
  })
})

describe('buildOrderTicket', () => {
  const fno: SymbolView = {
    symbol: 'NIFTY28MAR2420800CE',
    exchange: 'NFO',
    name: 'NIFTY',
    lots: true,
    lotsize: 75,
    tick: 0.05,
    freezeQty: 1800,
    quoteOnly: false,
    productOptions: ['MIS', 'NRML'],
    product: 'NRML',
  }
  const cash: SymbolView = {
    ...fno,
    symbol: 'SBIN',
    exchange: 'NSE',
    lots: false,
    lotsize: 1,
    productOptions: ['MIS', 'CNC'],
    product: 'CNC',
  }

  it('sizes the ticket the way the armed path sizes the order', () => {
    const t = buildOrderTicket({
      sym: fno,
      qty: 2,
      product: 'NRML',
      side: 'BUY',
      type: 'MARKET',
      price: 0,
    })
    expect(t.quantity).toBe(orderUnits(2, fno.lots, fno.lotsize))
    expect(t.quantity).toBe(150)
    expect(t.lotSize).toBe(75)
    expect(t.tickSize).toBe(0.05)
  })

  it('carries the pane product and the terminal strategy tag through', () => {
    const t = buildOrderTicket({
      sym: cash,
      qty: 10,
      product: 'MIS',
      side: 'SELL',
      type: 'MARKET',
      price: 0,
    })
    expect(t).toMatchObject({
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'SELL',
      quantity: 10,
      lotSize: 1,
      product: 'MIS',
      strategy: 'chart-trading',
    })
  })

  it('sends no price on a market order, the way placeFromMenu does', () => {
    const t = buildOrderTicket({
      sym: fno,
      qty: 1,
      product: 'MIS',
      side: 'BUY',
      type: 'MARKET',
      price: 123.45,
    })
    expect(t.priceType).toBe('MARKET')
    expect(t.price).toBeUndefined()
    expect(t.triggerPrice).toBeUndefined()
  })

  it('puts the clicked price on a limit and nothing on its trigger', () => {
    const t = buildOrderTicket({
      sym: fno,
      qty: 1,
      product: 'MIS',
      side: 'BUY',
      type: 'LIMIT',
      price: 123.45,
    })
    expect(t.priceType).toBe('LIMIT')
    expect(t.price).toBe(123.45)
    expect(t.triggerPrice).toBeUndefined()
  })

  it('puts the clicked price on both fields of a stop, as the armed path does', () => {
    // placeFromMenu sends price and triggerPrice both equal to the row's price
    // for SL; the ticket must show the trader the same two numbers.
    const t = buildOrderTicket({
      sym: fno,
      qty: 1,
      product: 'MIS',
      side: 'SELL',
      type: 'SL',
      price: 120,
    })
    expect(t.priceType).toBe('SL')
    expect(t.price).toBe(120)
    expect(t.triggerPrice).toBe(120)
  })

  it('gives a stop-market only its trigger', () => {
    const t = buildOrderTicket({
      sym: fno,
      qty: 1,
      product: 'MIS',
      side: 'SELL',
      type: 'SL-M',
      price: 120,
    })
    expect(t.price).toBeUndefined()
    expect(t.triggerPrice).toBe(120)
  })
})

/**
 * Where the fork sits. Read from the source, the way replayTradingLock.test.ts
 * does, because driving a terminal needs a DOM and a broker: every guard the
 * armed path applies has to run before the ticket opens, and the cooldown has
 * to sit on the armed placement alone.
 */
describe('placeFromMenu forks after its guards', () => {
  const SRC = readFileSync(join(process.cwd(), 'src/lib/trading/terminal.ts'), 'utf8')
  const at = SRC.indexOf('private async placeFromMenu(')
  const body = at === -1 ? '' : SRC.slice(at, SRC.indexOf('async exitPosition()', at))
  const ticketAt = body.indexOf('onOrderTicket(')
  const placeAt = body.indexOf('trade.place(')

  it('opens the ticket only after replay, quote-only, freeze and stop-side checks', () => {
    expect(at).toBeGreaterThan(-1)
    expect(ticketAt).toBeGreaterThan(-1)
    for (const guard of ['refuseWhileReplaying()', 'quoteOnly', 'freezeQty', 'stop must be']) {
      const guardAt = body.indexOf(guard)
      expect(guardAt, guard).toBeGreaterThan(-1)
      expect(guardAt, guard).toBeLessThan(ticketAt)
    }
  })

  it('never reaches the broker on the disarmed path', () => {
    expect(placeAt).toBeGreaterThan(ticketAt)
    expect(body.slice(ticketAt, placeAt)).toContain('return')
    const forkAt = body.indexOf('this.armed')
    expect(forkAt).toBeGreaterThan(-1)
    expect(forkAt).toBeLessThan(ticketAt)
  })

  it('applies the scalping cooldown to the armed placement', () => {
    expect(ORDER_COOLDOWN_MS).toBe(120)
    const coolAt = body.indexOf('ORDER_COOLDOWN_MS')
    expect(coolAt).toBeGreaterThan(ticketAt)
    expect(coolAt).toBeLessThan(placeAt)
  })
})

/**
 * The confirmed ticket goes back out through the terminal's feed, which
 * asserts the page's mode against the server before it posts, exactly as
 * the armed path does. A ticket that posted straight to the API would be
 * the one order route on the page deciding on the server's global switch.
 */
describe('placeTicket keeps the mode assertion', () => {
  const SRC = readFileSync(join(process.cwd(), 'src/lib/trading/terminal.ts'), 'utf8')
  const at = SRC.indexOf('async placeTicket(')
  const body = at === -1 ? '' : SRC.slice(at, SRC.indexOf('async exitPosition()', at))

  it('places through the trade feed with the page mode', () => {
    expect(at).toBeGreaterThan(-1)
    expect(body).toContain('this.trade.place(')
    expect(body).toContain('mode: this.tradeMode()')
    expect(body).toContain('this.tradingLocked()')
  })

  it('is the route the pane hands its ticket', () => {
    const pane = readFileSync(join(process.cwd(), 'src/components/trading/ChartPane.tsx'), 'utf8')
    const dialogAt = pane.indexOf('<PlaceOrderDialog')
    expect(dialogAt).toBeGreaterThan(-1)
    const dialog = pane.slice(dialogAt, pane.indexOf('/>', dialogAt))
    expect(dialog).toContain('place={')
    expect(dialog).toContain('.placeTicket(')
    expect(dialog).toContain('container={menuHost}')
    expect(pane).not.toContain('tradingApi.placeOrder')
  })
})
