/**
 * Filter evaluation is the screener's one piece of real logic, and every way it
 * can be wrong is silent: a crossover that fires a bar late, a warm-up null read
 * as a pass, an inclusive bound read as exclusive. None of those throw, none
 * show up in the UI, and all of them change which symbols a trader looks at.
 */
import { describe, expect, it } from 'vitest'
import { type AlertSpec, type Bar, evaluateFilters, type Filter } from './model'

function bars(count: number): Bar[] {
  return Array.from({ length: count }, (_, i) => ({
    time: 1_700_000_000 + i * 300,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
  }))
}

const noAlerts: AlertSpec[] = []

function valueFilter(partial: Partial<Extract<Filter, { kind: 'value' }>>): Filter {
  return {
    id: 'f1',
    kind: 'value',
    column: 'rsi',
    op: '>',
    rhs: { kind: 'const', value: 50 },
    ...partial,
  } as Filter
}

describe('comparisons', () => {
  it('compares the last bar, not an earlier one', () => {
    const values = { rsi: [90, 10] }
    expect(evaluateFilters([valueFilter({})], bars(2), values, {}, noAlerts)).toBe(false)
    expect(evaluateFilters([valueFilter({ op: '<' })], bars(2), values, {}, noAlerts)).toBe(true)
  })

  it('treats at-least and at-most as inclusive', () => {
    const values = { rsi: [0, 50] }
    expect(evaluateFilters([valueFilter({ op: '>=' })], bars(2), values, {}, noAlerts)).toBe(true)
    expect(evaluateFilters([valueFilter({ op: '<=' })], bars(2), values, {}, noAlerts)).toBe(true)
    expect(evaluateFilters([valueFilter({ op: '>' })], bars(2), values, {}, noAlerts)).toBe(false)
  })

  it('compares column against column index-wise', () => {
    const filter = valueFilter({ rhs: { kind: 'column', key: 'signal' } })
    expect(evaluateFilters([filter], bars(2), { rsi: [1, 9], signal: [99, 4] }, {}, noAlerts)).toBe(
      true
    )
    expect(evaluateFilters([filter], bars(2), { rsi: [9, 1], signal: [0, 4] }, {}, noAlerts)).toBe(
      false
    )
  })
})

describe('between', () => {
  const filter = valueFilter({
    op: 'between',
    rhs: { kind: 'const', value: 30 },
    rhs2: { kind: 'const', value: 70 },
  })

  it('is inclusive at both bounds', () => {
    expect(evaluateFilters([filter], bars(1), { rsi: [30] }, {}, noAlerts)).toBe(true)
    expect(evaluateFilters([filter], bars(1), { rsi: [70] }, {}, noAlerts)).toBe(true)
    expect(evaluateFilters([filter], bars(1), { rsi: [50] }, {}, noAlerts)).toBe(true)
  })

  it('excludes outside', () => {
    expect(evaluateFilters([filter], bars(1), { rsi: [29.9] }, {}, noAlerts)).toBe(false)
    expect(evaluateFilters([filter], bars(1), { rsi: [70.1] }, {}, noAlerts)).toBe(false)
  })
})

describe('crossovers', () => {
  const above = valueFilter({ op: 'crossesAbove', rhs: { kind: 'const', value: 50 } })

  it('fires on the transition bar', () => {
    expect(evaluateFilters([above], bars(2), { rsi: [49, 51] }, {}, noAlerts)).toBe(true)
  })

  it('does not fire on the bar after the transition', () => {
    expect(evaluateFilters([above], bars(2), { rsi: [51, 52] }, {}, noAlerts)).toBe(false)
  })

  it('counts touching the level then breaking it as a cross', () => {
    expect(evaluateFilters([above], bars(2), { rsi: [50, 51] }, {}, noAlerts)).toBe(true)
  })

  it('does not fire when the level is only reached, not passed', () => {
    expect(evaluateFilters([above], bars(2), { rsi: [49, 50] }, {}, noAlerts)).toBe(false)
  })

  it('cannot cross on a single-bar series', () => {
    expect(evaluateFilters([above], bars(1), { rsi: [99] }, {}, noAlerts)).toBe(false)
  })

  it('crossesBelow is the mirror', () => {
    const below = valueFilter({ op: 'crossesBelow', rhs: { kind: 'const', value: 50 } })
    expect(evaluateFilters([below], bars(2), { rsi: [51, 49] }, {}, noAlerts)).toBe(true)
    expect(evaluateFilters([below], bars(2), { rsi: [49, 48] }, {}, noAlerts)).toBe(false)
  })
})

describe('missing readings', () => {
  it('excludes a symbol whose indicator has no value yet', () => {
    const filter = valueFilter({ op: '<' })
    expect(evaluateFilters([filter], bars(2), { rsi: [10, null] }, {}, noAlerts)).toBe(false)
  })

  it('excludes when the previous bar is null and a crossover needs it', () => {
    const filter = valueFilter({ op: 'crossesAbove' })
    expect(evaluateFilters([filter], bars(2), { rsi: [null, 99] }, {}, noAlerts)).toBe(false)
  })

  it('excludes when the column does not exist at all', () => {
    expect(
      evaluateFilters([valueFilter({ column: 'nope' })], bars(2), { rsi: [99, 99] }, {}, noAlerts)
    ).toBe(false)
  })

  it('excludes NaN, which is a gap and not a number', () => {
    expect(evaluateFilters([valueFilter({})], bars(1), { rsi: [NaN] }, {}, noAlerts)).toBe(false)
  })
})

describe('combining', () => {
  it('requires every filter to pass', () => {
    const values = { rsi: [60], adx: [10] }
    const filters: Filter[] = [
      valueFilter({ id: 'a', column: 'rsi', op: '>', rhs: { kind: 'const', value: 50 } }),
      valueFilter({ id: 'b', column: 'adx', op: '>', rhs: { kind: 'const', value: 25 } }),
    ]
    expect(evaluateFilters([filters[0]], bars(1), values, {}, noAlerts)).toBe(true)
    expect(evaluateFilters(filters, bars(1), values, {}, noAlerts)).toBe(false)
  })

  it('passes everything when there are no filters', () => {
    expect(evaluateFilters([], bars(1), { rsi: [1] }, {}, noAlerts)).toBe(true)
  })

  it('rejects an empty series outright', () => {
    expect(evaluateFilters([], [], {}, {}, noAlerts)).toBe(false)
  })
})

describe('alert conditions', () => {
  const alerts: AlertSpec[] = [
    { id: 'buy', title: 'BUY', when: ({ values, index }) => values.sigBuy?.[index] === 1 },
  ]

  it('reads the indicator’s own condition at the last bar', () => {
    const filter: Filter = { id: 'f', kind: 'alert', alertId: 'buy' }
    expect(evaluateFilters([filter], bars(2), { sigBuy: [0, 1] }, {}, alerts)).toBe(true)
    expect(evaluateFilters([filter], bars(2), { sigBuy: [1, 0] }, {}, alerts)).toBe(false)
  })

  it('excludes when the named alert does not exist', () => {
    const filter: Filter = { id: 'f', kind: 'alert', alertId: 'gone' }
    expect(evaluateFilters([filter], bars(1), { sigBuy: [1] }, {}, alerts)).toBe(false)
  })
})
