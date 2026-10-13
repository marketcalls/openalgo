import { describe, expect, it } from 'vitest'
import { parseRangeChoice, serializeRangeChoice } from './rangeChoice'

describe('range choice preference', () => {
  it('round-trips a versioned record', () => {
    const raw = serializeRangeChoice({ id: '1Y', interval: 'D' })
    expect(JSON.parse(raw)).toEqual({ v: 1, id: '1Y', interval: 'D' })
    expect(parseRangeChoice(raw)).toEqual({ id: '1Y', interval: 'D' })
  })

  it('reads anything it does not recognise as no range', () => {
    for (const raw of [
      null,
      '',
      'not json',
      'null',
      '"1D"',
      JSON.stringify({ id: '1D', interval: '1m' }),
      JSON.stringify({ v: 2, id: '1D', interval: '1m' }),
      JSON.stringify({ v: 1, id: '<b>', interval: '1m' }),
      JSON.stringify({ v: 1, id: '1D', interval: '' }),
    ])
      expect(parseRangeChoice(raw)).toBeNull()
  })

  it('clears with an empty string', () => {
    expect(serializeRangeChoice(null)).toBe('')
  })
})
