import { describe, expect, it } from 'vitest'
import type { OIProfileChainItem } from '@/api/oi-profile'
import type { SymbolData } from '@/lib/MarketDataManager'
import { applyLiveOi } from './oiProfileLive'

const row = (): OIProfileChainItem => ({
  strike: 100,
  ce_oi: 1000,
  pe_oi: 500,
  ce_oi_change: 200,
  pe_oi_change: 50,
  ce_legs: [{ symbol: 'C1', oi: 1000, base: 800 }],
  pe_legs: [{ symbol: 'P1', oi: 500, base: 450 }],
})

const feed = (entries: Record<string, number>) =>
  new Map<string, SymbolData>(
    Object.entries(entries).map(([sym, oi]) => [
      `NFO:${sym}`,
      { symbol: sym, exchange: 'NFO', data: { oi } },
    ])
  )

describe('applyLiveOi', () => {
  it('replaces OI and re-bases the change for a live leg', () => {
    const { chain, liveLegs } = applyLiveOi([row()], feed({ C1: 1300 }), 'NFO')
    expect(chain[0].ce_oi).toBe(1300)
    expect(chain[0].ce_oi_change).toBe(500)
    expect(chain[0].pe_oi).toBe(500)
    expect(liveLegs).toBe(1)
  })

  it('leaves the polled numbers alone when the feed carries no OI', () => {
    const { chain, liveLegs } = applyLiveOi([row()], feed({}), 'NFO')
    expect(chain[0]).toEqual(row())
    expect(liveLegs).toBe(0)
  })

  it('treats a zero tick as unknown, not as an emptied contract', () => {
    const { chain } = applyLiveOi([row()], feed({ C1: 0 }), 'NFO')
    expect(chain[0].ce_oi).toBe(1000)
  })

  it('does not invent a change when the base is unknown', () => {
    const r = row()
    r.ce_legs = [{ symbol: 'C1', oi: 1000, base: null }]
    const { chain } = applyLiveOi([r], feed({ C1: 1300 }), 'NFO')
    expect(chain[0].ce_oi).toBe(1300)
    expect(chain[0].ce_oi_change).toBe(200)
  })

  it('sums legs across expiries, mixing live and polled', () => {
    const r = row()
    r.ce_legs = [
      { symbol: 'C1', oi: 1000, base: 800 },
      { symbol: 'C2', oi: 400, base: 300 },
    ]
    const { chain } = applyLiveOi([r], feed({ C1: 1100 }), 'NFO')
    expect(chain[0].ce_oi).toBe(1500)
    expect(chain[0].ce_oi_change).toBe(300 + 100)
  })
})
