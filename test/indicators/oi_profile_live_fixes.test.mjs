/**
 * The OI Profile overlay's refresh, lookup and failure behaviour, driven through
 * attach() with a stubbed backend.
 *
 *   node --test test/indicators/oi_profile_live_fixes.test.mjs
 *
 * Each case pins a defect the overlay had:
 * - every refresh asked twice and showed totals in place of the change bars
 *   while the second answer was on its way;
 * - an underlying with '&' or '-' in its name (M&M, BAJAJ-AUTO) found no
 *   expiries, and an MCX one (CRUDEOIL) was only ever looked for on NFO;
 * - one failed CSRF fetch stopped every later refresh until a page reload;
 * - none of that was ever shown: a profile that could not load was blank.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

const mod = (await import(new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url))).default

const CHAIN = [
  {
    strike: 23300, ce_oi: 8_721_000, pe_oi: 6_893_000, ce_oi_change: 2_637_000, pe_oi_change: 1_542_000,
    ce_legs: [], pe_legs: [],
  },
]
const ok = (body) => ({ ok: true, status: 200, json: async () => body })
const success = { status: 'success', market_open: true, oi_chain: CHAIN }

// The indicator stamps refreshes with Date.now(); moving this offset is how a
// test lets "a whole refresh beat" pass without waiting three minutes.
const realNow = Date.now
let clockOffset = 0
Date.now = () => realNow() + clockOffset

function harness({ symbol = 'NIFTY22SEP26FUT', settings = {}, fetchImpl }) {
  let onVisible = null
  globalThis.document = {
    hidden: false,
    addEventListener: (event, fn) => { if (event === 'visibilitychange') onVisible = fn },
    removeEventListener() {},
  }
  globalThis.fetch = fetchImpl
  let descriptor
  mod({ registerIndicator: (d) => { descriptor = d }, nulls: (a) => a })
  let primitive
  const teardown = descriptor.attach({
    settings: () => ({ barWidth: 140, maxPain: false, strikes: 5, expiries: 1, ...settings }),
    symbol: () => symbol,
    timezone: () => 'Asia/Kolkata',
    addPrimitive: (p) => { primitive = p },
    removePrimitive() {},
    requestRecompute() {},
  })
  const rc = (hoverId = null) => ({
    plotWidth: 800, plotHeight: 400, dpr: 1, hoverId,
    priceScale: { priceToY: (p) => 400 - (p - 23100) / 2 },
  })
  // Everything painted this frame, hovering 23300 (y = 300).
  const texts = () => {
    const out = []
    const noop = () => {}
    const canvas = new Proxy(
      { measureText: (t) => ({ width: t.length * 6 }), fillText: (t) => out.push(t) },
      { get: (t, k) => (k in t ? t[k] : noop), set: () => true }
    )
    primitive.hitTest(760, 300, rc())
    primitive.draw(canvas, rc('oi-profile-strike:23300'))
    return out
  }
  // A visibility change after a full beat is the indicator's own way of
  // refreshing early, so it stands in for the beat timer.
  const nextBeat = () => {
    clockOffset += 10 * 60 * 1000
    onVisible()
  }
  return { teardown, texts, nextBeat }
}

const waitFor = async (check, what, ms = 3000) => {
  const until = realNow() + ms
  while (!check()) {
    if (realNow() > until) throw new Error(`timed out waiting for ${what}`)
    await new Promise((r) => setTimeout(r, 20))
  }
}

const profileCalls = (log) => log.filter((c) => c.url.includes('/oiprofile/api/profile-data'))

test('a routine refresh asks once and keeps the change bars on screen while it runs', async () => {
  const log = []
  let releaseChange = null
  const h = harness({
    settings: { mode: 'change', outline: true },
    fetchImpl: async (url, opts) => {
      const body = opts?.body ? JSON.parse(opts.body) : null
      log.push({ url: String(url), body })
      if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
      if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
      // After the first load, hold the change answer until the test has
      // looked at the screen.
      if (body?.include_change && releaseChange === 'hold') {
        await new Promise((r) => { releaseChange = r })
      }
      return ok(success)
    },
  })
  try {
    await waitFor(() => h.texts().includes('Call OI Chg: 26.37L'), 'first load in change mode')
    // The first load is allowed both passes: fast OI, then the change.
    assert.deepEqual(profileCalls(log).map((c) => c.body.include_change), [false, true])

    log.length = 0
    releaseChange = 'hold'
    h.nextBeat()
    await waitFor(() => typeof releaseChange === 'function', 'the refresh to be in flight')
    // Mid-refresh the screen still shows the change, not the totals.
    assert.ok(h.texts().includes('Call OI Chg: 26.37L'), h.texts().join(' | '))
    releaseChange()
    await waitFor(() => profileCalls(log).length >= 1, 'the refresh to land')
    await new Promise((r) => setTimeout(r, 50))
    assert.deepEqual(profileCalls(log).map((c) => c.body.include_change), [true], 'one request per refresh')
  } finally {
    h.teardown()
  }
})

test('underlyings keep & and - in their names', async () => {
  for (const [symbol, expected] of [['M&M23NOV26FUT', 'M&M'], ['BAJAJ-AUTO23NOV26FUT', 'BAJAJ-AUTO']]) {
    const log = []
    const h = harness({
      symbol,
      settings: { mode: 'oi', outline: false },
      fetchImpl: async (url, opts) => {
        log.push({ url: String(url), body: opts?.body ? JSON.parse(opts.body) : null })
        if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['27-OCT-26'] })
        if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
        return ok(success)
      },
    })
    try {
      await waitFor(() => profileCalls(log).length > 0, `the ${expected} request`)
      assert.equal(profileCalls(log)[0].body.underlying, expected)
      const lookup = log.find((c) => c.url.includes('/search/api/expiries')).url
      assert.ok(lookup.includes(`underlying=${encodeURIComponent(expected)}`), lookup)
    } finally {
      h.teardown()
    }
  }
})

test('Auto finds an MCX underlying that has no options on NFO', async () => {
  const log = []
  const h = harness({
    symbol: 'CRUDEOIL18DEC26FUT',
    settings: { mode: 'oi', outline: false, exchange: 'auto' },
    fetchImpl: async (url, opts) => {
      log.push({ url: String(url), body: opts?.body ? JSON.parse(opts.body) : null })
      if (String(url).includes('/search/api/expiries')) {
        return ok({ expiries: String(url).includes('exchange=MCX') ? ['15-OCT-26'] : [] })
      }
      if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
      return ok(success)
    },
  })
  try {
    await waitFor(() => profileCalls(log).length > 0, 'the CRUDEOIL request')
    assert.equal(profileCalls(log)[0].body.exchange, 'MCX')
    assert.deepEqual(profileCalls(log)[0].body.expiry_dates, ['15OCT26'])
  } finally {
    h.teardown()
  }
})

test('one failed CSRF fetch does not stop later refreshes', async () => {
  const log = []
  let csrfCalls = 0
  const h = harness({
    settings: { mode: 'oi', outline: false },
    fetchImpl: async (url, opts) => {
      log.push({ url: String(url), body: opts?.body ? JSON.parse(opts.body) : null })
      if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
      if (String(url).includes('csrf')) {
        csrfCalls += 1
        if (csrfCalls === 1) throw new TypeError('Failed to fetch')
        return ok({ csrf_token: 't' })
      }
      return ok(success)
    },
  })
  try {
    // Waits on the fetch itself, not on the status line, so this case pins the
    // CSRF retry alone.
    await waitFor(() => csrfCalls === 1, 'the failed CSRF fetch')
    await new Promise((r) => setTimeout(r, 50))
    assert.equal(profileCalls(log).length, 0, 'nothing reached the server without a token')
    h.nextBeat()
    await waitFor(() => profileCalls(log).length > 0, 'a later refresh to reach the server')
    assert.equal(csrfCalls, 2)
    await waitFor(() => h.texts().includes('Call OI: 87.21L'), 'the bars after recovery')
  } finally {
    h.teardown()
  }
})

test('a profile that cannot load says why instead of staying blank', async () => {
  const noExpiries = harness({
    symbol: 'NOSUCHNAME',
    settings: { mode: 'oi', outline: false },
    fetchImpl: async (url) => {
      if (String(url).includes('/search/api/expiries')) return ok({ expiries: [] })
      if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
      return ok(success)
    },
  })
  try {
    await waitFor(
      () => noExpiries.texts().some((t) => t.includes('no option expiries found for NOSUCHNAME')),
      'the no-expiries message'
    )
  } finally {
    noExpiries.teardown()
  }

  // A refresh that fails after a good load keeps the bars and says they are
  // older than they look.
  let fail = false
  const failing = harness({
    settings: { mode: 'oi', outline: false },
    fetchImpl: async (url) => {
      if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
      if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
      if (fail) return { ok: false, status: 500, json: async () => ({}) }
      return ok(success)
    },
  })
  try {
    await waitFor(() => failing.texts().includes('Call OI: 87.21L'), 'the first load')
    assert.ok(failing.texts().some((t) => /^OI Profile: Updated \d{2}:\d{2}$/.test(t)), failing.texts().join(' | '))
    fail = true
    failing.nextBeat()
    await waitFor(
      () => failing.texts().some((t) => t.includes('The last refresh failed; retrying.')),
      'the failed-refresh message'
    )
    assert.ok(failing.texts().includes('Call OI: 87.21L'), 'the last good bars stay up')
  } finally {
    failing.teardown()
  }
})
