/**
 * Reading a strategy's books off whatever the platform answered.
 *
 * Every test names the wrong implementation it catches. The one that matters is
 * `rowsOf`: a book whose rows are under a key this did not know renders as "no
 * orders", which a trader reads as a strategy that has done nothing rather than
 * as a bug.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('./client', () => ({ webClient: { get: (...a: unknown[]) => get(...a) } }))

const { strategyOrderbook, strategyPositions, strategyTradebook } = await import(
  './openscriptRunner'
)

beforeEach(() => vi.clearAllMocks())

function answers(data: unknown, status = 'success') {
  get.mockResolvedValue({ data: { status, data } })
}

describe('finding the rows', () => {
  it('reads orders, trades and positions out of their own key', async () => {
    answers({ orders: [{ orderid: '1' }] })
    expect((await strategyOrderbook('x.oscript')).rows).toHaveLength(1)

    answers({ trades: [{ orderid: '1' }, { orderid: '2' }] })
    expect((await strategyTradebook('x.oscript')).rows).toHaveLength(2)

    answers({ positions: [{ symbol: 'TCS' }] })
    expect((await strategyPositions('x.oscript')).rows).toHaveLength(1)
  })

  it('reads a book that spells positions positionbook', async () => {
    // Catches one spelling assumed. Two services here answer positions under
    // different keys, and the wrong guess draws an empty table.
    answers({ positionbook: [{ symbol: 'TCS' }] })
    expect((await strategyPositions('x.oscript')).rows).toHaveLength(1)
  })

  it('reads a bare list, which is what some books answer', async () => {
    answers([{ orderid: '1' }])
    expect((await strategyOrderbook('x.oscript')).rows).toHaveLength(1)
  })

  it('answers no rows rather than throwing on a shape it does not know', async () => {
    for (const shape of [null, undefined, 'text', 7, {}]) {
      answers(shape)
      expect((await strategyOrderbook('x.oscript')).rows).toEqual([])
    }
  })
})

describe('what a book says when it cannot be read', () => {
  it('passes the service refusal through in its own words', async () => {
    // Catches a message replaced by a generic one. The service refuses for
    // reasons a trader can act on, and rewording loses the actionable half.
    get.mockResolvedValue({ data: { status: 'error', message: 'Sandbox is not enabled' } })

    const book = await strategyOrderbook('x.oscript')

    expect(book.problem).toBe('Sandbox is not enabled')
    expect(book.rows).toEqual([])
  })

  it('answers a problem rather than throwing when the request fails', async () => {
    // Catches an exception reaching the panel. One unreadable book must not
    // take down the surface a trader is using to decide whether to stop
    // something that is trading.
    get.mockRejectedValue(new Error('offline'))

    const book = await strategyTradebook('x.oscript')

    expect(book.problem).toBeTruthy()
    expect(book.rows).toEqual([])
  })
})

describe('the statistics', () => {
  it('carries them when the book has them and null when it does not', async () => {
    answers({ orders: [], statistics: { total_orders: 3 } })
    expect((await strategyOrderbook('x.oscript')).statistics).toEqual({ total_orders: 3 })

    answers({ trades: [] })
    expect((await strategyTradebook('x.oscript')).statistics).toBeNull()
  })
})

describe('the request', () => {
  it('asks the route for that book and encodes the name', async () => {
    answers({ orders: [] })
    await strategyOrderbook('my strategy.oscript')
    expect(get.mock.calls[0][0]).toBe('/openscript/runner/orderbook/my%20strategy.oscript')
  })
})
