import { describe, expect, it } from 'vitest'
import { openInterestCapability } from './openInterest'

describe('instrument open-interest capability', () => {
  it('uses derivative segments and omits cash and index placeholders', () => {
    for (const exchange of ['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX']) {
      expect(openInterestCapability(exchange)).toBe(true)
    }
    for (const exchange of ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX']) {
      expect(openInterestCapability(exchange)).toBe(false)
    }
    expect(openInterestCapability('CUSTOM')).toBeUndefined()
  })

  it('distinguishes crypto spot and derivatives using instrument metadata', () => {
    expect(openInterestCapability('CRYPTO')).toBeUndefined()
    expect(openInterestCapability('CRYPTO', { instrumenttype: 'SPOT' })).toBe(false)
    for (const instrumenttype of ['FUT', 'CE', 'PE', 'PERPFUT']) {
      expect(openInterestCapability('CRYPTO', { instrumenttype })).toBe(true)
    }
    expect(openInterestCapability('CUSTOM', { hasOpenInterest: false })).toBe(false)
    expect(openInterestCapability('CUSTOM', { hasOpenInterest: true })).toBe(true)
  })
})
