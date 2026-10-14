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

function harness({ symbol = 'NIFTY22SEP26FUT', settings = {}, fetchImpl, subscribeQuotes }) {
  let onVisible = null
  globalThis.document = {
    hidden: false,
    addEventListener: (event, fn) => { if (event === 'visibilitychange') onVisible = fn },
    removeEventListener() {},
  }
  globalThis.fetch = fetchImpl
  let descriptor
  mod({ registerIndicator: (d) => { descriptor = d }, nulls: (a) => a, subscribeQuotes })
  let primitive
  const teardown = descriptor.attach({
    settings: () => ({ barWidth: 140, maxPain: false, strikes: 5, expiries: 1, ...settings }),
    symbol: () => symbol,
    timezone: () => 'Asia/Kolkata',
    addPrimitive: (p) => { primitive = p },
    removePrimitive() {},
    requestRecompute() {},
  })
  const rc = (hoverId = null, priceToY = (p) => 400 - (p - 23100) / 2) => ({
    plotWidth: 800, plotHeight: 400, dpr: 1, hoverId,
    priceScale: { priceToY },
  })
  // One painted frame: every text and every filled bar (x, y, w, h).
  const frame = (hoverId = 'oi-profile-strike:23300', priceToY) => {
    const texts = []
    const rects = []
    const noop = () => {}
    const canvas = new Proxy(
      {
        measureText: (t) => ({ width: t.length * 6 }),
        fillText: (t) => texts.push(t),
        fillRect: (x, y, w, h) => rects.push({ x, y, w, h }),
      },
      { get: (t, k) => (k in t ? t[k] : noop), set: () => true }
    )
    primitive.hitTest(760, 300, rc(null, priceToY))
    primitive.draw(canvas, rc(hoverId, priceToY))
    return { texts, rects }
  }
  // Everything painted this frame, hovering 23300 (y = 300).
  const texts = () => frame().texts
  // A visibility change after a full beat is the indicator's own way of
  // refreshing early, so it stands in for the beat timer.
  const nextBeat = () => {
    clockOffset += 10 * 60 * 1000
    onVisible()
  }
  return { teardown, texts, frame, nextBeat }
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
    assert.ok(
      failing.texts().some((t) => /^OI Profile: Updated \d{2}:\d{2}( \| PCR \d+\.\d{2})?$/.test(t)),
      failing.texts().join(' | ')
    )
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

// ---------------------------------------------------------------------------
// Second round: what is drawn, and what is streamed.
// ---------------------------------------------------------------------------

const routine = (body) => async (url) => {
  if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
  if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
  return ok(typeof body === 'function' ? body() : body)
}

test('switching Mode or the outline repaints from data already held, without clearing or refetching', async () => {
  const log = []
  const settings = { mode: 'change', outline: true }
  const serve = routine(success)
  const h = harness({
    settings,
    fetchImpl: async (url, opts) => {
      log.push({ url: String(url), body: opts?.body ? JSON.parse(opts.body) : null })
      return serve(url)
    },
  })
  try {
    await waitFor(() => h.texts().includes('Call OI Chg: 26.37L'), 'change mode loaded')
    await new Promise((r) => setTimeout(r, 50))
    log.length = 0
    const onScreen = []
    settings.mode = 'oi'
    await waitFor(() => {
      const t = h.texts()
      onScreen.push(t.includes('Strike: 23300'))
      return t.includes('Call OI: 87.21L')
    }, 'OI mode')
    settings.outline = false
    await new Promise((r) => setTimeout(r, 1300))
    settings.mode = 'change'
    await waitFor(() => {
      const t = h.texts()
      onScreen.push(t.includes('Strike: 23300'))
      return t.includes('Call OI Chg: 26.37L')
    }, 'change mode again')
    assert.ok(onScreen.every(Boolean), 'the bars never left the screen')
    assert.equal(profileCalls(log).length, 0, 'no request for data already held')
  } finally {
    h.teardown()
  }
})

test('with expiries combined, max pain is the nearest expiry\'s, and says so', async () => {
  // Summed over both expiries max pain is 23300; over 22SEP26 alone it is 23200.
  const chain = [
    {
      strike: 23200, ce_oi: 1000, pe_oi: 0, ce_oi_change: 0, pe_oi_change: 0,
      ce_legs: [{ symbol: 'NIFTY22SEP2623200CE', oi: 1000, base: null }], pe_legs: [],
    },
    {
      strike: 23300, ce_oi: 0, pe_oi: 5010, ce_oi_change: 0, pe_oi_change: 0, ce_legs: [],
      pe_legs: [
        { symbol: 'NIFTY22SEP2623300PE', oi: 10, base: null },
        { symbol: 'NIFTY29SEP2623300PE', oi: 5000, base: null },
      ],
    },
  ]
  const h = harness({
    settings: { mode: 'oi', outline: false, maxPain: true, expiryDate: '22SEP26,29SEP26' },
    fetchImpl: routine({ status: 'success', market_open: true, oi_chain: chain }),
  })
  try {
    await waitFor(() => h.frame(null).texts.some((t) => t.startsWith('Max Pain')), 'the max pain marker')
    const labels = h.frame(null).texts.filter((t) => t.startsWith('Max Pain'))
    assert.deepEqual(labels, ['Max Pain 23200 (22SEP26)'])
  } finally {
    h.teardown()
  }
})

test('bars are never taller than the space between strikes', async () => {
  // The three strikes 10px apart, as in a small pane of a multi-chart grid.
  const tight = (p) => 200 - (p - 23300) / 10
  const multi = { status: 'success', market_open: true, oi_chain: [
    { strike: 23200, ce_oi: 5_000_000, pe_oi: 4_000_000, ce_oi_change: 0, pe_oi_change: 0 },
    { strike: 23300, ce_oi: 8_721_000, pe_oi: 6_893_000, ce_oi_change: 0, pe_oi_change: 0 },
    { strike: 23400, ce_oi: 3_000_000, pe_oi: 2_000_000, ce_oi_change: 0, pe_oi_change: 0 },
  ] }
  const h2 = harness({ settings: { mode: 'oi', outline: false }, fetchImpl: routine(multi) })
  try {
    await waitFor(() => h2.frame(null, tight).rects.length >= 6, 'the bars')
    const { rects } = h2.frame(null, tight)
    // Each strike's call bar sits above its line and its put bar below, so
    // half the 10px spacing is all either may take.
    assert.ok(rects.every((r) => r.h <= 5), rects.map((r) => r.h).join(','))
  } finally {
    h2.teardown()
  }
})

test('the tooltip gives both totals and change, with the strike PCR; the status line gives the overall PCR', async () => {
  const settings = { mode: 'oi', outline: true }
  const h = harness({ settings, fetchImpl: routine(success) })
  try {
    await waitFor(() => h.texts().some((t) => t.startsWith('Call Chg:')), 'the change columns')
    const oiView = h.texts()
    assert.ok(oiView.includes('Call OI: 87.21L'), oiView.join(' | '))
    assert.ok(oiView.includes('Call Chg: +26.37L (+43.3%)'), oiView.join(' | '))
    assert.ok(oiView.includes('Put Chg: +15.42L (+28.8%)'), oiView.join(' | '))
    assert.ok(oiView.includes('PCR: 0.79'), oiView.join(' | '))
    assert.ok(oiView.some((t) => /^OI Profile: Updated \d{2}:\d{2} \| PCR 0\.79$/.test(t)), oiView.join(' | '))

    settings.mode = 'change'
    await waitFor(() => h.texts().includes('Call OI Chg: 26.37L'), 'change mode')
    assert.ok(h.texts().includes('Totals: Call 87.21L, Put 68.93L'), h.texts().join(' | '))
  } finally {
    h.teardown()
  }
})

test('live OI streams the legs around the strikes on screen and changes them by difference', async () => {
  const subs = new Map()
  let subCalls = 0
  let unsubCalls = 0
  const subscribeQuotes = (symbols) => {
    subCalls += symbols.length
    for (const s of symbols) subs.set(s.symbol, (subs.get(s.symbol) ?? 0) + 1)
    return () => {
      unsubCalls += symbols.length
      for (const s of symbols) subs.set(s.symbol, subs.get(s.symbol) - 1)
    }
  }
  const active = () => [...subs].filter(([, n]) => n > 0).map(([s]) => s)
  const strikeOf = (s) => Number(s.slice('NIFTY22SEP26'.length, -2))
  // 121 strikes, 242 legs, ATM in the middle.
  let first = 20300
  const chainFor = () =>
    Array.from({ length: 121 }, (_, i) => first + i * 50).map((k) => ({
      strike: k, ce_oi: 1000, pe_oi: 1000, ce_oi_change: 0, pe_oi_change: 0,
      ce_legs: [{ symbol: `NIFTY22SEP26${k}CE`, oi: 1000, base: null }],
      pe_legs: [{ symbol: `NIFTY22SEP26${k}PE`, oi: 1000, base: null }],
    }))
  const h = harness({
    settings: { mode: 'oi', outline: false },
    subscribeQuotes,
    fetchImpl: routine(() => ({
      status: 'success', market_open: true, options_exchange: 'NFO', atm_strike: 23300, oi_chain: chainFor(),
    })),
  })
  try {
    await waitFor(() => active().length > 0, 'the first subscriptions')
    // Before any frame: capped, and centred on ATM.
    assert.equal(active().length, 160, `streamed ${active().length} of 242 legs`)
    assert.ok(active().every((s) => Math.abs(strikeOf(s) - 23300) <= 40 * 50))

    // After a frame: the legs on screen (23100-23900 here) and 3 strikes
    // either side, 23 strikes in all.
    h.frame(null)
    await waitFor(() => active().length === 46, 'the visible legs', 4000)
    assert.ok(active().every((s) => strikeOf(s) >= 22950 && strikeOf(s) <= 24050))

    // ATM moves a strike and the chain is recentred: the legs still on
    // screen keep streaming, nothing is dropped and resubscribed.
    const before = { sub: subCalls, unsub: unsubCalls }
    first = 20350
    h.nextBeat()
    await new Promise((r) => setTimeout(r, 300))
    h.frame(null)
    await new Promise((r) => setTimeout(r, 2300))
    assert.equal(subCalls - before.sub, 0, 'no new subscription for a leg already streaming')
    assert.equal(unsubCalls - before.unsub, 0, 'nothing dropped that is still on screen')
  } finally {
    h.teardown()
  }
  assert.equal(active().length, 0, 'teardown drops every leg')
})
