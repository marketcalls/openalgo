// Runnable check for the OI Profile overlay's hover tooltip, driven through the
// real poller path with a stubbed backend.
//
//   node test/indicators/oi_profile_live.test.mjs
//
// The chart-indicator skill's validate.mjs proves the descriptor registers;
// this proves the part a user actually touches - hovering a strike - still
// names the right strike, follows the Open Interest / Change in OI mode, and
// prints the lakh figures Sensibull's own profile prints.
import assert from 'node:assert/strict'

globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }

const CHAIN = [
  { strike: 23200, ce_oi: 6_082_700, pe_oi: 9_376_575, ce_oi_change: 1_833_455, pe_oi_change: 2_762_175 },
  { strike: 23300, ce_oi: 8_721_000, pe_oi: 6_893_000, ce_oi_change: 2_637_000, pe_oi_change: 1_542_000 },
  { strike: 23400, ce_oi: 5_000_000, pe_oi: 3_000_000, ce_oi_change: -400_000, pe_oi_change: 120_000 },
]
let lastBody = null
globalThis.fetch = async (url, opts) => {
  if (opts?.body) lastBody = JSON.parse(opts.body)
  if (String(url).includes('/search/api/expiries'))
    return { ok: true, json: async () => ({ expiries: ['22-SEP-26'] }) }
  if (String(url).includes('csrf')) return { ok: true, json: async () => ({ csrf_token: 't' }) }
  return { ok: true, status: 200, json: async () => ({ status: 'success', market_open: true, oi_chain: CHAIN }) }
}

const mod = (await import(new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url))).default
let descriptor
mod({ registerIndicator: (d) => { descriptor = d }, nulls: (a) => a })

const settings = { barWidth: 140, colors: 'sensibull', maxPain: false, outline: false, mode: 'change', strikes: 5, expiries: 1 }
let primitive
const ctx = {
  settings: () => settings, symbol: () => 'NIFTY22SEP26FUT',
  addPrimitive: (p) => { primitive = p }, removePrimitive: () => {}, requestRecompute: () => {},
}
const teardown = descriptor.attach(ctx)
await new Promise((r) => setTimeout(r, 60))   // let the two-pass poll land

const rc = (hoverId = null) => ({
  plotWidth: 800, plotHeight: 400, dpr: 1, hoverId,
  priceScale: { priceToY: (p) => 400 - (p - 23100) / 2 },
  timeScale: {}, dataLayer: {}, priceAxisWidth: 60, theme: {},
})
const canvas = () => {
  const texts = []
  const noop = () => {}
  return new Proxy({ texts, measureText: (t) => ({ width: t.length * 6 }), fillText: (t) => texts.push(t) },
    { get: (t, k) => (k in t ? t[k] : noop), set: () => true })
}

// 23300 sits at y = 400 - 100 = 300. Bars hug the right edge (800).
const hit = primitive.hitTest(760, 300, rc())
assert.ok(hit, 'cursor over a strike bar must register a hit')
assert.equal(hit.externalId, 'oi-profile-strike:23300', hit.externalId)

assert.equal(primitive.hitTest(100, 300, rc()), null, 'cursor left of the bars must not hit')

// Change mode: the tooltip names the change, in lakhs, like Sensibull.
let c = canvas()
primitive.draw(c, rc('oi-profile-strike:23300'))
assert.ok(c.texts.includes('Strike: 23300'), c.texts.join(' | '))
assert.ok(c.texts.includes('Call OI Chg: 26.37L'), c.texts.join(' | '))
assert.ok(c.texts.includes('Put OI Chg: 15.42L'), c.texts.join(' | '))

// No hover -> no tooltip.
c = canvas()
primitive.draw(c, rc(null))
assert.equal(c.texts.length, 0, 'no hoverId must paint no tooltip')

// Open Interest mode: totals, and the label drops "Chg".
// The settings dialog fires no change event, so the indicator polls it once a
// second and refetches. The tooltip follows the bars, so it changes with them.
settings.mode = 'oi'
await new Promise((r) => setTimeout(r, 1400))
primitive.hitTest(760, 300, rc())
c = canvas()
primitive.draw(c, rc('oi-profile-strike:23300'))
assert.ok(c.texts.includes('Call OI: 87.21L'), c.texts.join(' | '))
assert.ok(c.texts.includes('Put OI: 68.93L'), c.texts.join(' | '))

// A negative change keeps its sign.
settings.mode = 'change'
await new Promise((r) => setTimeout(r, 1400))
primitive.hitTest(760, 250, rc())      // 23400 -> y = 250
c = canvas()
primitive.draw(c, rc('oi-profile-strike:23400'))
assert.ok(c.texts.includes('Call OI Chg: -4.00L'), c.texts.join(' | '))

// Ticked expiries are a comma list, and every one of them is asked for; a
// single value is the old single-expiry override and still works.
settings.expiryDate = '22SEP26, 29SEP26'
await new Promise((r) => setTimeout(r, 1400))
assert.deepEqual(lastBody.expiry_dates, ['22SEP26', '29SEP26'], JSON.stringify(lastBody))

settings.expiryDate = '06OCT26'
await new Promise((r) => setTimeout(r, 1400))
assert.deepEqual(lastBody.expiry_dates, ['06OCT26'], JSON.stringify(lastBody))

// Exchange left on Auto: the chart's own symbol picks the underlying, and the
// BSE indices go to BFO without anyone setting anything.
settings.exchange = 'auto'
settings.expiryDate = ''
await new Promise((r) => setTimeout(r, 1400))
assert.equal(lastBody.underlying, 'NIFTY', JSON.stringify(lastBody))
assert.equal(lastBody.exchange, 'NFO', JSON.stringify(lastBody))

settings.underlying = 'SENSEX'
await new Promise((r) => setTimeout(r, 1400))
assert.equal(lastBody.exchange, 'BFO', JSON.stringify(lastBody))

teardown()
console.log('OK: hover tooltip names the strike, matches mode, formats in lakhs; expiry picks are summed')
