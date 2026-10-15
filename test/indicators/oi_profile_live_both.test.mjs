/**
 * The OI Profile's Both mode: open interest and the day's change on screen at
 * once, as two columns on their own scales, both kept current by the live feed.
 *
 *   node --test test/indicators/oi_profile_live_both.test.mjs
 */
import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'

const indicator = await import(new URL('../../strategies/indicators/oi_profile_live.js', import.meta.url))
const mod = indicator.default
// Each test expects a cold start, not the previous test's remembered answer.
beforeEach(() => indicator.forgetAnswers())

const ok = (body) => ({ ok: true, status: 200, json: async () => body })

// Two strikes, so the scale is set by the bigger one and a tick on the smaller
// one moves its bars by a measurable amount. 23300 sits at y = 300, 23350 at
// y = 275; with two rows 25px apart each half row is 12.5px, so a call bar's
// top is y - 12.5 and a put bar's is y + 1.
const CHAIN = [
  {
    strike: 23300, ce_oi: 1000, pe_oi: 2000, ce_oi_change: 200, pe_oi_change: -500,
    ce_legs: [{ symbol: 'NIFTY22SEP2623300CE', oi: 1000, base: 800 }],
    pe_legs: [{ symbol: 'NIFTY22SEP2623300PE', oi: 2000, base: 2500 }],
  },
  {
    strike: 23350, ce_oi: 5000, pe_oi: 4000, ce_oi_change: 4000, pe_oi_change: 1000,
    ce_legs: [{ symbol: 'NIFTY22SEP2623350CE', oi: 5000, base: 1000 }],
    pe_legs: [{ symbol: 'NIFTY22SEP2623350PE', oi: 4000, base: 3000 }],
  },
]
const success = { status: 'success', market_open: true, options_exchange: 'NFO', atm_strike: 23300, oi_chain: CHAIN }

function harness({ settings, fetchImpl, plotWidth = 800, priceToY = (p) => 400 - (p - 23100) / 2 }) {
  globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} }
  globalThis.fetch = fetchImpl
  const ticks = new Map()
  const subscribeQuotes = (symbols, onTick) => {
    for (const s of symbols) ticks.set(s.symbol, onTick)
    return () => { for (const s of symbols) ticks.delete(s.symbol) }
  }
  let descriptor
  mod({ registerIndicator: (d) => { descriptor = d }, nulls: (a) => a, subscribeQuotes })
  let primitive
  const teardown = descriptor.attach({
    settings: () => ({ barWidth: 140, maxPain: false, strikes: 5, expiries: 1, opacity: 55, ...settings }),
    symbol: () => 'NIFTY22SEP26FUT',
    timezone: () => 'Asia/Kolkata',
    addPrimitive: (p) => { primitive = p },
    removePrimitive() {},
    requestRecompute() {},
  })
  const rc = (hoverId) => ({
    plotWidth, plotHeight: 400, dpr: 1, hoverId,
    priceScale: { priceToY },
  })
  const frame = (hoverId = null) => {
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
    if (hoverId) primitive.hitTest(plotWidth - 20, 300, rc(null))
    primitive.draw(canvas, rc(hoverId))
    return { texts, rects }
  }
  const tick = (symbol, oi) => ticks.get(symbol)?.({ symbol, data: { oi, oi_updated_at: Date.now() } })
  return { teardown, frame, tick, ticks }
}

const routine = (log = []) => async (url, opts) => {
  const body = opts?.body ? JSON.parse(opts.body) : null
  log.push({ url: String(url), body })
  if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
  if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
  return ok(success)
}

const waitFor = async (check, what, ms = 4000) => {
  const until = Date.now() + ms
  while (!check()) {
    if (Date.now() > until) throw new Error(`timed out waiting for ${what}`)
    await new Promise((r) => setTimeout(r, 20))
  }
}

// The call bar of strike 23300 in the column whose x range is [from, to].
const callBar = (rects, from, to) =>
  rects.find((r) => r.y === 300 - 12.5 && r.h === 11.5 && r.x >= from - 0.01 && r.x + r.w <= to + 0.01)

test('Both draws open interest and the change as two labelled columns', async () => {
  const h = harness({ settings: { mode: 'both', outline: true }, fetchImpl: routine() })
  try {
    await waitFor(() => h.frame().texts.includes('Change in OI'), 'the change column')
    const { texts, rects } = h.frame()
    assert.ok(texts.includes('Open Interest'), texts.join(' | '))
    // Open interest at the right edge, where the single view has it
    // (660-800), the change to its left with a 14px gap (506-646).
    const oi = callBar(rects, 660, 800)
    const chg = callBar(rects, 506, 646)
    assert.ok(oi, 'call OI bar in the right-hand column')
    assert.ok(chg, 'call change bar in the left-hand column')
    // Each on its own scale: 1000 of a 5000 maximum is 28px of 140.
    assert.equal(Math.round(oi.w), 28)
    // The change column spans -500..4000, so 200 is 140 * 200 / 4500.
    assert.equal(Math.round(chg.w * 100) / 100, Math.round((140 * 200 / 4500) * 100) / 100)
    // A negative change (the 23300 put unwound 500) draws right of the zero.
    const putChg = rects.find((r) => r.y === 301 && r.x >= 506 && r.x + r.w <= 646.01)
    const zeroX = 646 - (500 * 140) / 4500
    assert.ok(Math.abs(putChg.x - zeroX) < 0.01, `put unwind starts at the zero rule (${putChg.x} vs ${zeroX})`)

    // One hover names both halves.
    const hover = h.frame('oi-profile-strike:23300').texts
    for (const line of ['Call OI: 1.00K', 'Put OI: 2.00K', 'Call Chg: +200 (+25.0%)', 'Put Chg: -500 (-20.0%)']) {
      assert.ok(hover.includes(line), `${line} in ${hover.join(' | ')}`)
    }
  } finally {
    h.teardown()
  }
})

test('a live tick moves the open interest and the change together', async () => {
  const h = harness({ settings: { mode: 'both', outline: false }, fetchImpl: routine() })
  try {
    await waitFor(() => h.frame().texts.includes('Change in OI'), 'Both on screen')
    await waitFor(() => h.ticks.has('NIFTY22SEP2623300CE'), 'the leg to stream')
    const before = h.frame().rects
    const oiBefore = callBar(before, 660, 800).w
    const chgBefore = callBar(before, 506, 646).w

    // 1000 -> 3000 calls written at 23300: OI 3000 of 5000, change 2200.
    h.tick('NIFTY22SEP2623300CE', 3000)
    await waitFor(() => Math.round(callBar(h.frame().rects, 660, 800)?.w ?? 0) === 84, 'the OI bar to grow', 5000)
    const after = h.frame().rects
    assert.equal(Math.round(callBar(after, 660, 800).w), 84, `OI ${oiBefore} -> 84`)
    const chgAfter = callBar(after, 506, 646).w
    assert.ok(chgAfter > chgBefore * 5, `change ${chgBefore} -> ${chgAfter}`)
    assert.equal(Math.round(chgAfter), Math.round((140 * 2200) / 4500))
  } finally {
    h.teardown()
  }
})

test('switching to Both repaints from what is held, without asking again', async () => {
  const log = []
  const settings = { mode: 'oi', outline: true }
  const h = harness({ settings, fetchImpl: routine(log) })
  try {
    await waitFor(() => h.frame('oi-profile-strike:23300').texts.some((t) => t.startsWith('Call Chg:')), 'change loaded')
    assert.ok(!h.frame().texts.includes('Change in OI'), 'one column in Open Interest mode')
    const asked = log.filter((c) => c.url.includes('profile-data')).length
    settings.mode = 'both'
    await waitFor(() => h.frame().texts.includes('Change in OI'), 'the second column', 3000)
    assert.equal(log.filter((c) => c.url.includes('profile-data')).length, asked, 'no refetch for a view change')
    settings.mode = 'oi'
    await waitFor(() => !h.frame().texts.includes('Change in OI'), 'back to one column', 3000)
  } finally {
    h.teardown()
  }
})

test('a narrow pane splits its bar share between the two columns', async () => {
  // 300px pane: one column may take 60% (180px). Two 140px columns would
  // cover the candles, so each gets (180 - 14) / 2 = 83px.
  const h = harness({ settings: { mode: 'both', outline: false }, fetchImpl: routine(), plotWidth: 300 })
  try {
    await waitFor(() => h.frame().texts.includes('Change in OI'), 'Both on screen')
    const { rects } = h.frame()
    const bars = rects.filter((r) => r.h === 11.5)
    const leftmost = Math.min(...bars.map((r) => r.x))
    assert.ok(leftmost >= 300 - 180 - 0.01, `bars start at ${leftmost}, inside the 180px share`)
    assert.equal(Math.round(callBar(rects, 217, 300).w), Math.round((83 * 1000) / 5000))
  } finally {
    h.teardown()
  }
})

test('max pain is named in the status line when its strike is off screen', async () => {
  // Max pain here is 23350 (writers lose 50,000 there against 200,000 at
  // 23300). Scroll so only 23300 is on screen: 23350 lands at y = -110.
  const h = harness({
    settings: { mode: 'both', outline: false, maxPain: true },
    fetchImpl: routine(),
    priceToY: (p) => (p === 23300 ? 300 : -110),
  })
  try {
    await waitFor(() => h.frame().texts.some((t) => t.includes('| Max Pain 23350')), 'max pain in the status line')
    const { texts } = h.frame()
    assert.ok(!texts.includes('Max Pain 23350'), 'no marker for a strike that is not on screen')
  } finally {
    h.teardown()
  }
})

test('a change not yet known says so instead of showing zero', async () => {
  // As the server sends it while yesterday's OI is still being fetched: every
  // contract's base is null and the strike's change is 0.
  const pending = CHAIN.map((r) => ({
    ...r,
    ce_oi_change: 0,
    pe_oi_change: 0,
    ce_legs: r.ce_legs.map((l) => ({ ...l, base: null })),
    pe_legs: r.pe_legs.map((l) => ({ ...l, base: null })),
  }))
  const h = harness({
    settings: { mode: 'both', outline: true },
    fetchImpl: async (url, opts) => {
      if (String(url).includes('/search/api/expiries')) return ok({ expiries: ['22-SEP-26'] })
      if (String(url).includes('csrf')) return ok({ csrf_token: 't' })
      return ok({ ...success, oi_chain: pending, oi_change_pending: true })
    },
  })
  try {
    await waitFor(() => h.frame('oi-profile-strike:23300').texts.includes('Call Chg: loading'), 'the loading note')
    const { texts } = h.frame('oi-profile-strike:23300')
    assert.ok(texts.includes('Put Chg: loading'), texts.join(' | '))
    assert.ok(!texts.some((t) => /Chg: 0/.test(t)), `no zero change: ${texts.join(' | ')}`)
    assert.ok(texts.some((t) => t.includes('change still loading')), 'the status line says so too')
  } finally {
    h.teardown()
  }
})

test('a fresh instance after the settings dialog paints at once and asks nothing', async () => {
  // /trading's dialog applies Ok by removing the indicator and attaching a new
  // one. That new instance used to start blank and ask for both passes again.
  const log = []
  const first = harness({ settings: { mode: 'oi', outline: true }, fetchImpl: routine(log) })
  await waitFor(() => first.frame('oi-profile-strike:23300').texts.some((t) => t.startsWith('Call Chg:')), 'first load')
  first.teardown()
  const asked = log.filter((c) => c.url.includes('profile-data')).length

  const second = harness({ settings: { mode: 'both', outline: true }, fetchImpl: routine(log) })
  try {
    // Painted synchronously from the remembered answer: no wait at all.
    const { texts } = second.frame('oi-profile-strike:23300')
    assert.ok(texts.includes('Change in OI'), `both columns at once: ${texts.join(' | ')}`)
    assert.ok(texts.includes('Call Chg: +200 (+25.0%)'), texts.join(' | '))
    await new Promise((r) => setTimeout(r, 300))
    assert.equal(log.filter((c) => c.url.includes('profile-data')).length, asked, 'no request for an answer seconds old')
  } finally {
    second.teardown()
  }
})
