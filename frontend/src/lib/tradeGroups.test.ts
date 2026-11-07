import { describe, expect, it } from 'vitest'
import type { Trade } from '@/types/trading'
import { groupTradesByOrder, MIXED_STRATEGY, ungrouped } from './tradeGroups'

const fill = (over: Partial<Trade>): Trade => ({
  symbol: 'CYIENT',
  exchange: 'NSE',
  action: 'BUY',
  quantity: 10,
  average_price: 100,
  trade_value: 1000,
  product: 'CNC',
  orderid: 'O1',
  timestamp: '30 Sept 2026, 03:13:35 pm',
  ...over,
})

describe('groupTradesByOrder', () => {
  it('folds the fills of one order into a single row with summed quantity and weighted price', () => {
    const groups = groupTradesByOrder([
      fill({ id: 1, tradeid: 'a', quantity: 10, average_price: 100, trade_value: 1000 }),
      fill({ id: 2, tradeid: 'b', quantity: 30, average_price: 102, trade_value: 3060 }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0].fills).toHaveLength(2)
    expect(groups[0].trade.quantity).toBe(40)
    expect(groups[0].trade.trade_value).toBe(4060)
    expect(groups[0].trade.average_price).toBeCloseTo(101.5, 6)
    expect(groups[0].trade.id).toBe(1)
  })

  it('keeps different orders, symbols and actions apart', () => {
    const groups = groupTradesByOrder([
      fill({ id: 1, orderid: 'O1' }),
      fill({ id: 2, orderid: 'O2' }),
      fill({ id: 3, orderid: 'O1', symbol: 'OTHER' }),
      fill({ id: 4, orderid: 'O1', action: 'SELL' }),
    ])
    expect(groups).toHaveLength(4)
  })

  it('never merges fills that have no order id', () => {
    const groups = groupTradesByOrder([fill({ id: 1, orderid: '' }), fill({ id: 2, orderid: '' })])
    expect(groups).toHaveLength(2)
  })

  it('keeps first-appearance order so a sorted list stays sorted', () => {
    const groups = groupTradesByOrder([
      fill({ id: 1, orderid: 'B' }),
      fill({ id: 2, orderid: 'A' }),
      fill({ id: 3, orderid: 'B' }),
    ])
    expect(groups.map((g) => g.trade.orderid)).toEqual(['B', 'A'])
  })

  it('shows the common tag, flags a partly tagged order, and marks conflicting tags', () => {
    const partial = groupTradesByOrder([
      fill({ id: 1, strategy: 'EquityBreakoutPositional' }),
      fill({ id: 2 }),
    ])[0]
    expect(partial.trade.strategy).toBe('EquityBreakoutPositional')
    expect(partial.partiallyTagged).toBe(true)

    const all = groupTradesByOrder([
      fill({ id: 1, strategy: 'X' }),
      fill({ id: 2, strategy: 'X' }),
    ])[0]
    expect(all.partiallyTagged).toBe(false)

    const mixed = groupTradesByOrder([
      fill({ id: 1, strategy: 'X' }),
      fill({ id: 2, strategy: 'Y' }),
    ])[0]
    expect(mixed.trade.strategy).toBe(MIXED_STRATEGY)
  })

  it('leaves a lone fill untouched', () => {
    const only = fill({ id: 9, tradeid: 't9' })
    const [group] = groupTradesByOrder([only])
    expect(group.trade).toBe(only)
  })
})

describe('ungrouped', () => {
  it('returns one group per fill', () => {
    expect(ungrouped([fill({ id: 1 }), fill({ id: 2 })])).toHaveLength(2)
  })
})
