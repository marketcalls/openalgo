import { describe, expect, it } from 'vitest'
import { conditionHolds } from './inputConditions'

describe('which controls a settings form shows', () => {
  const values = { 'transform.mode': 'atr', 'transform.reversal': 3 }

  it('reads is and isNot, one value or several', () => {
    expect(conditionHolds({ key: 'transform.mode', is: 'atr' }, values)).toBe(true)
    expect(conditionHolds({ key: 'transform.mode', is: 'fixed' }, values)).toBe(false)
    expect(conditionHolds({ key: 'transform.mode', is: ['fixed', 'atr'] }, values)).toBe(true)
    expect(conditionHolds({ key: 'transform.mode', isNot: 'fixed' }, values)).toBe(true)
    expect(conditionHolds({ key: 'transform.mode', isNot: ['fixed', 'atr'] }, values)).toBe(false)
  })

  it('combines with all and any', () => {
    const mode = { key: 'transform.mode', is: 'atr' } as const
    const reversal = { key: 'transform.reversal', is: 4 } as const
    expect(conditionHolds({ all: [mode, reversal] }, values)).toBe(false)
    expect(conditionHolds({ any: [mode, reversal] }, values)).toBe(true)
  })
})
