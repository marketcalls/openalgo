/**
 * overlayLiveOi lays live feed OI over the polled chain on the /trading chart.
 * The rules match frontend/src/lib/oiProfileLive.ts, so the chart overlay and
 * the /oiprofile page never disagree about the same strike.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

const { overlayLiveOi } = await import(
  new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url)
)

const row = () => ({
  strike: 100,
  ce_oi: 1000,
  pe_oi: 500,
  ce_oi_change: 200,
  pe_oi_change: 50,
  ce_legs: [{ symbol: 'C1', oi: 1000, base: 800 }],
  pe_legs: [{ symbol: 'P1', oi: 500, base: 450 }],
})

test('a live leg replaces OI and re-bases the change', () => {
  const { chain, live } = overlayLiveOi([row()], new Map([['C1', 1300]]))
  assert.equal(chain[0].ce_oi, 1300)
  assert.equal(chain[0].ce_oi_change, 500)
  assert.equal(chain[0].pe_oi, 500)
  assert.equal(live, 1)
})

test('no live OI leaves the polled numbers alone', () => {
  const { chain, live } = overlayLiveOi([row()], new Map())
  assert.deepEqual(chain[0], row())
  assert.equal(live, 0)
})

test('a zero tick is unknown, not an emptied contract', () => {
  assert.equal(overlayLiveOi([row()], new Map([['C1', 0]])).chain[0].ce_oi, 1000)
})

test('an unknown base keeps the polled change', () => {
  const r = row()
  r.ce_legs = [{ symbol: 'C1', oi: 1000, base: null }]
  const { chain } = overlayLiveOi([r], new Map([['C1', 1300]]))
  assert.equal(chain[0].ce_oi, 1300)
  assert.equal(chain[0].ce_oi_change, 200)
})

test('legs from several expiries mix live and polled', () => {
  const r = row()
  r.ce_legs = [
    { symbol: 'C1', oi: 1000, base: 800 },
    { symbol: 'C2', oi: 400, base: 300 },
  ]
  const { chain } = overlayLiveOi([r], new Map([['C1', 1100]]))
  assert.equal(chain[0].ce_oi, 1500)
  assert.equal(chain[0].ce_oi_change, 400)
})

test('attach() subscribes to the legs, repaints from a tick, unsubscribes on teardown', async () => {
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
  const chain = [
    {
      strike: 23300, ce_oi: 8_721_000, pe_oi: 6_893_000, ce_oi_change: 0, pe_oi_change: 0,
      ce_legs: [{ symbol: 'NIFTY22SEP2623300CE', oi: 8_721_000, base: null }],
      pe_legs: [{ symbol: 'NIFTY22SEP2623300PE', oi: 6_893_000, base: null }],
    },
  ]
  globalThis.fetch = async (url) => {
    if (String(url).includes('/search/api/expiries'))
      return { ok: true, json: async () => ({ expiries: ['22-SEP-26'] }) }
    if (String(url).includes('csrf')) return { ok: true, json: async () => ({ csrf_token: 't' }) }
    return {
      ok: true, status: 200,
      json: async () => ({ status: 'success', market_open: true, options_exchange: 'NFO', oi_chain: chain }),
    }
  }
  const mod = (await import(new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url))).default

  let subscribed = null
  let onTick = null
  let unsubscribed = 0
  let descriptor
  mod({
    registerIndicator: (d) => { descriptor = d },
    nulls: (a) => a,
    subscribeQuotes: (symbols, cb) => {
      subscribed = symbols
      onTick = cb
      return () => { unsubscribed += 1 }
    },
  })

  const settings = { barWidth: 140, colors: 'sensibull', maxPain: false, outline: false, mode: 'oi', strikes: 5, expiries: 1 }
  let primitive
  const teardown = descriptor.attach({
    settings: () => settings, symbol: () => 'NIFTY22SEP26FUT',
    addPrimitive: (p) => { primitive = p }, removePrimitive: () => {}, requestRecompute: () => {},
  })
  await new Promise((r) => setTimeout(r, 60))

  // teardown in finally: a failed assertion must not leave the indicator's
  // timers holding the process open.
  try {
  assert.deepEqual(
    subscribed.map((s) => `${s.exchange}:${s.symbol}`).sort(),
    ['NFO:NIFTY22SEP2623300CE', 'NFO:NIFTY22SEP2623300PE']
  )

  const rc = (hoverId = null) => ({
    plotWidth: 800, plotHeight: 400, dpr: 1, hoverId,
    priceScale: { priceToY: (p) => 400 - (p - 23100) / 2 },
    timeScale: {}, dataLayer: {}, priceAxisWidth: 60, theme: {},
  })
  const tooltip = () => {
    const texts = []
    const noop = () => {}
    const c = new Proxy({ measureText: (t) => ({ width: t.length * 6 }), fillText: (t) => texts.push(t) },
      { get: (t, k) => (k in t ? t[k] : noop), set: () => true })
    primitive.hitTest(760, 300, rc())
    primitive.draw(c, rc('oi-profile-strike:23300'))
    return texts
  }

  assert.ok(tooltip().includes('Call OI: 87.21L'))
  onTick({ symbol: 'NIFTY22SEP2623300CE', exchange: 'NFO', data: { oi: 9_000_000 } })
  await new Promise((r) => setTimeout(r, 2200)) // one redraw beat
  assert.ok(tooltip().includes('Call OI: 90.00L'), tooltip().join(' | '))
  assert.ok(tooltip().includes('Put OI: 68.93L'), 'a leg with no tick keeps its polled OI')
  } finally {
    teardown()
  }
  assert.equal(unsubscribed, 1)
})

test('a host without subscribeQuotes still loads and polls', async () => {
  const mod = (await import(new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url))).default
  let descriptor
  mod({ registerIndicator: (d) => { descriptor = d }, nulls: (a) => a })
  const teardown = descriptor.attach({
    settings: () => ({ mode: 'oi', strikes: 5, expiries: 1, outline: false }),
    symbol: () => 'NIFTY22SEP26FUT',
    addPrimitive: () => {}, removePrimitive: () => {}, requestRecompute: () => {},
  })
  await new Promise((r) => setTimeout(r, 60))
  teardown()
})
