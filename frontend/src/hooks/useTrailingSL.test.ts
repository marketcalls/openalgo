import { describe, expect, it } from 'vitest'
import { evaluateTrail, type SLState } from './useTrailingSL'

const sl = (o: Partial<SLState>): SLState => ({
  symbol: 'NIFTY16JUN2623600CE',
  exchange: 'NFO',
  product: 'NRML',
  side: 'BUY',
  entry: 100,
  quantity: 65,
  initialSl: 90,
  trailingEnabled: false,
  trailingStep: 0,
  highestPrice: 100,
  lowestPrice: 100,
  currentSl: 90,
  target: 0,
  active: true,
  ...o,
})

describe('evaluateTrail', () => {
  describe('stop-loss', () => {
    it('long breaches at/below the stop', () => {
      expect(evaluateTrail(sl({ currentSl: 95 }), 95).reason).toBe('sl')
      expect(evaluateTrail(sl({ currentSl: 95 }), 94).breached).toBe(true)
    })
    it('long holds above the stop', () => {
      expect(evaluateTrail(sl({ currentSl: 95 }), 96).breached).toBe(false)
    })
    it('short breaches at/above the stop', () => {
      const r = evaluateTrail(sl({ side: 'SELL', currentSl: 105, initialSl: 105 }), 106)
      expect(r.breached).toBe(true)
      expect(r.reason).toBe('sl')
    })
  })

  describe('target', () => {
    it('long target breaches at/above', () => {
      const r = evaluateTrail(sl({ target: 120 }), 120)
      expect(r.breached).toBe(true)
      expect(r.reason).toBe('target')
    })
    it('short target breaches at/below', () => {
      const r = evaluateTrail(sl({ side: 'SELL', currentSl: 200, initialSl: 200, target: 80 }), 80)
      expect(r.breached).toBe(true)
      expect(r.reason).toBe('target')
    })
  })

  describe('trailing', () => {
    it('long trail raises the stop and does not breach', () => {
      const r = evaluateTrail(sl({ trailingEnabled: true, trailingStep: 3, currentSl: 90 }), 110)
      expect(r.breached).toBe(false)
      expect(r.next.currentSl).toBe(107) // highest(110) - step(3)
    })
    it('long trailed stop then breaches on pullback', () => {
      const s = sl({ trailingEnabled: true, trailingStep: 3, currentSl: 90 })
      const r1 = evaluateTrail(s, 110)
      const r2 = evaluateTrail(r1.next, 106.9)
      expect(r2.breached).toBe(true)
      expect(r2.reason).toBe('sl')
    })
    it('long trail only ratchets up (never loosens)', () => {
      const s = sl({ trailingEnabled: true, trailingStep: 3, currentSl: 107, highestPrice: 110 })
      const r = evaluateTrail(s, 108) // pullback but above stop
      expect(r.next.currentSl).toBe(107)
    })
    it('short trail lowers the stop', () => {
      const r = evaluateTrail(
        sl({ side: 'SELL', currentSl: 110, trailingEnabled: true, trailingStep: 3 }),
        90
      )
      expect(r.breached).toBe(false)
      expect(r.next.currentSl).toBe(93) // lowest(90) + step(3)
    })
  })
})
