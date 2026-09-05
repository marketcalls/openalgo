import { describe, expect, it } from 'vitest'
import { riskError } from './riskValidation'

describe('calculator risk validation', () => {
  it('accepts both long and short protective levels', () => {
    expect(riskError('BUY', 100, 90, 110, 5)).toBeNull()
    expect(riskError('SELL', 100, 110, 90, 5)).toBeNull()
  })
  it('rejects nonfinite, nonpositive and inverted levels', () => {
    expect(riskError('BUY', 100, -1)).toBeTruthy()
    expect(riskError('BUY', 100, NaN)).toBeTruthy()
    expect(riskError('BUY', 100, 110)).toBeTruthy()
    expect(riskError('SELL', 100, undefined, 110)).toBeTruthy()
    expect(riskError('BUY', 100, undefined, undefined, 0)).toBeTruthy()
  })
  it('requires an entry basis only when validating absolute risk prices', () => {
    expect(riskError('BUY', null, 90)).toBeTruthy()
    expect(riskError('BUY', null)).toBeNull()
  })
})
