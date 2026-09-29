/**
 * Reading what a strategy is holding, from the shapes this platform sends.
 *
 * The two that matter are the shape and the spelling. A positions answer comes
 * back as a bare list from one service and as an object from another, and a
 * reader that knows one reports an empty book for the other. Every field has
 * more than one spelling across broker modules. Both failures render as a
 * strategy holding nothing, which is indistinguishable from a strategy that is
 * flat, so neither can be caught by looking at the screen.
 */

import { describe, expect, it } from 'vitest'
import { positionFrom, rowsOfPositions, summaryOf } from './strategyPosition'

const TCS = { symbol: 'TCS', exchange: 'NSE', quantity: 1, average_price: 2108.6, pnl: 0.5 }

describe('finding the rows', () => {
  it('reads a bare list, which is what the positions services answer', () => {
    // THE SHAPE THAT BROKE THE SERVER SIDE. The sandbox and the live position
    // book both put the rows directly under `data`.
    expect(rowsOfPositions([TCS])).toHaveLength(1)
  })

  it('reads a list wrapped under a name, which other modules use', () => {
    for (const key of ['positions', 'positionbook', 'net', 'data']) {
      expect(rowsOfPositions({ [key]: [TCS] })).toHaveLength(1)
    }
  })

  it('answers nothing for a shape it does not know rather than throwing', () => {
    for (const shape of [null, undefined, 'text', 7, {}, { positions: 'nope' }]) {
      expect(rowsOfPositions(shape)).toEqual([])
    }
  })

  it('drops anything in the list that is not a row', () => {
    expect(rowsOfPositions([TCS, null, 'text', 7])).toHaveLength(1)
  })
})

describe('reading one row', () => {
  it('takes the direction from the sign and reports the size positive', () => {
    // THE ONE THAT MATTERS. A short is a negative quantity in a book. One place
    // treating the minus as direction and another as amount flips a position.
    expect(positionFrom({ ...TCS, quantity: -2 }).side).toBe('short')
    expect(positionFrom({ ...TCS, quantity: -2 }).quantity).toBe(2)
    expect(positionFrom({ ...TCS, quantity: 2 }).side).toBe('long')
    expect(positionFrom({ ...TCS, quantity: 2 }).quantity).toBe(2)
  })

  it('calls a squared off row flat rather than long', () => {
    expect(positionFrom({ ...TCS, quantity: 0 }).side).toBe('flat')
  })

  it('reads every field by each spelling a module in this platform uses', () => {
    // Catches one spelling assumed. A quantity read by the wrong name is zero,
    // which reports a flat position on a strategy that is holding something.
    const other = { tradingsymbol: 'TCS', brexchange: 'NSE', netqty: -3, avgprice: 100, unrealised: -7 }
    const read = positionFrom(other)

    expect(read.symbol).toBe('TCS')
    expect(read.exchange).toBe('NSE')
    expect(read.side).toBe('short')
    expect(read.quantity).toBe(3)
    expect(read.averagePrice).toBe(100)
    expect(read.profit).toBe(-7)
  })

  it('keeps a missing price and a missing profit absent rather than zero', () => {
    // Zero is a real profit. Showing one for a row the broker said nothing
    // about claims the strategy is exactly break even.
    const read = positionFrom({ symbol: 'TCS', exchange: 'NSE', quantity: 1 })

    expect(read.averagePrice).toBeNull()
    expect(read.profit).toBeNull()
  })
})

describe('the summary a panel shows', () => {
  it('shows what is still held and counts what has closed', () => {
    // A book keeps a squared off row at zero carrying the profit it made.
    // Listing it says the strategy is in something it is not; dropping its
    // profit says the day was flat.
    const answered = {
      data: [
        { ...TCS, quantity: 1, pnl: 0.5 },
        { symbol: 'INFY', exchange: 'NSE', quantity: 0, pnl: 12 },
      ],
    }

    const out = summaryOf(answered)

    expect(out.positions.map((one) => one.symbol)).toEqual(['TCS'])
    expect(out.profit).toBe(12.5)
    expect(out.profitIsPlatforms).toBe(false)
  })

  it('prefers the total the platform stated over adding the rows up', () => {
    // The platform knows about realised profit on rows that are no longer
    // there, which adding up what is on screen cannot see.
    const out = summaryOf({ data: [TCS], total_pnl: 4.2 })

    expect(out.profit).toBe(4.2)
    expect(out.profitIsPlatforms).toBe(true)
  })

  it('reads the real sandbox envelope, field for field', () => {
    // Taken from sandbox/position_manager.py, which answers `data` as the list
    // and puts its totals beside it.
    const out = summaryOf({
      status: 'success',
      data: [{ symbol: 'TCS', exchange: 'NSE', quantity: 1, average_price: 2108.6, pnl: 0.5 }],
      total_pnl: 0.9,
      total_unrealized_pnl: 0.5,
      total_today_realized_pnl: 0.4,
      mode: 'analyze',
    })

    expect(out.positions).toHaveLength(1)
    expect(out.positions[0].side).toBe('long')
    expect(out.profit).toBe(0.9)
    expect(out.profitIsPlatforms).toBe(true)
  })

  it('answers an empty summary for a book that could not be read', () => {
    for (const shape of [null, undefined, {}, { data: {} }, 'text']) {
      const out = summaryOf(shape)
      expect(out.positions).toEqual([])
    }
  })
})
