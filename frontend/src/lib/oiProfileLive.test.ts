import { describe, expect, it } from 'vitest'
import type { OIProfileChainItem } from '@/api/oi-profile'
import { applyLiveOi, type LiveOi, liveOiKey } from './oiProfileLive'

const NOW = 1_000_000

const row = (): OIProfileChainItem => ({
  strike: 100,
  ce_oi: 1000,
  pe_oi: 500,
  ce_oi_change: 200,
  pe_oi_change: 50,
  ce_legs: [{ symbol: 'C1', oi: 1000, base: 800 }],
  pe_legs: [{ symbol: 'P1', oi: 500, base: 450 }],
})

const feed = (entries: Record<string, number>, at = NOW) =>
  new Map<string, LiveOi>(
    Object.entries(entries).map(([sym, oi]) => [liveOiKey('NFO', sym), { oi, at }])
  )

describe('applyLiveOi', () => {
  it('replaces OI and re-bases the change for a live leg', () => {
    const { chain, liveLegs } = applyLiveOi([row()], feed({ C1: 1300 }), 'NFO', NOW)
    expect(chain[0].ce_oi).toBe(1300)
    expect(chain[0].ce_oi_change).toBe(500)
    expect(chain[0].pe_oi).toBe(500)
    expect(liveLegs).toBe(1)
  })

  it('leaves the polled numbers alone when the feed carries no OI', () => {
    const { chain, liveLegs } = applyLiveOi([row()], feed({}), 'NFO', NOW)
    expect(chain[0]).toEqual(row())
    expect(liveLegs).toBe(0)
  })

  it('treats a zero tick as unknown, not as an emptied contract', () => {
    const { chain } = applyLiveOi([row()], feed({ C1: 0 }), 'NFO', NOW)
    expect(chain[0].ce_oi).toBe(1000)
  })

  it('a leg without an anchor adds nothing to the change, as on the server', () => {
    const r = row()
    r.ce_oi_change = 0
    r.ce_legs = [{ symbol: 'C1', oi: 1000, base: null }]
    const { chain } = applyLiveOi([r], feed({ C1: 1300 }), 'NFO', NOW)
    expect(chain[0].ce_oi).toBe(1300)
    expect(chain[0].ce_oi_change).toBe(0)
  })

  it('one unanchored leg does not freeze the anchored ones beside it', () => {
    const r = row()
    r.ce_legs = [
      { symbol: 'C1', oi: 1000, base: 800 },
      { symbol: 'C2', oi: 400, base: null },
    ]
    const { chain } = applyLiveOi([r], feed({ C1: 1100 }), 'NFO', NOW)
    expect(chain[0].ce_oi).toBe(1500)
    expect(chain[0].ce_oi_change).toBe(300)
  })

  it('sums legs across expiries, mixing live and polled', () => {
    const r = row()
    r.ce_legs = [
      { symbol: 'C1', oi: 1000, base: 800 },
      { symbol: 'C2', oi: 400, base: 300 },
    ]
    const { chain } = applyLiveOi([r], feed({ C1: 1100 }), 'NFO', NOW)
    expect(chain[0].ce_oi).toBe(1500)
    expect(chain[0].ce_oi_change).toBe(300 + 100)
  })

  it('a tick older than the max age falls back to the polled number', () => {
    const stale = feed({ C1: 1300 }, NOW - 10_000)
    expect(applyLiveOi([row()], stale, 'NFO', NOW, 5_000).chain[0].ce_oi).toBe(1000)
    expect(applyLiveOi([row()], stale, 'NFO', NOW, 60_000).chain[0].ce_oi).toBe(1300)
  })

  it('matches ticks whatever the case of the symbol and exchange', () => {
    const r = row()
    r.ce_legs = [{ symbol: 'nifty13oct2622600ce', oi: 1000, base: 800 }]
    const ticks = new Map<string, LiveOi>([
      [liveOiKey('NFO', 'NIFTY13OCT2622600CE'), { oi: 1300, at: NOW }],
    ])
    expect(applyLiveOi([r], ticks, 'nfo', NOW).chain[0].ce_oi).toBe(1300)
  })
})
