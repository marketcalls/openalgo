/**
 * OI Profile — live open interest bars pinned to the right edge of the pane,
 * matching Sensibull's own OI Profile overlay.
 *
 * The first version used `draws()` box geometry (time+price anchored), which
 * scrolls with the data — fine for a trendline anchored to a pivot, wrong
 * here: Sensibull's bars stay glued to the screen's right edge regardless of
 * pan/zoom. That's screen-space, not data-space, so `draws()` cannot express
 * it (its anchors are always `{time, price}`). `ctx.addPrimitive()` is the
 * documented escape hatch for exactly this — a raw `IPrimitive` with its own
 * `draw(ctx, rc)` gets `rc.plotWidth` (the pane's pixel width, screen space)
 * and `rc.priceScale.priceToY(price)` (price -> pixel, always current), so
 * "flush against the right edge" is just `x = rc.plotWidth - barWidthPx`,
 * recomputed every frame.
 *
 * This also means the calc/store/draws round-trip from the first version
 * (broadcasting the chain onto the last bar's plot slot, since draws() never
 * sees `store`) is gone entirely: the primitive's `draw()` reads a plain
 * closure variable updated directly by the poller in `attach()`. No plot
 * column carries the data any more; `plots` still needs one entry (the
 * contract requires at least one), so it's a hidden no-op line.
 *
 * Expiries: like Sensibull, the profile can sum several expiries. Leave the
 * pick list blank and it fetches the nearest N option expiries for the
 * underlying itself; tick the ones you want to pin it to exactly those.
 *
 * Load: the strike window is a setting (5/10/25/50 around ATM) because every
 * strike is two legs to quote and, for the change columns, one broker history
 * call each - narrowing it is the fastest thing a user can do about load.
 * Beyond that: the exchange republishes open interest every few minutes, so polling
 * faster than that buys nothing and costs a multiquote over ~80 legs each
 * time. This asks for no candles (the chart already has bars), refreshes on a
 * three-minute beat with a random 0-10s offset so many open charts do not
 * stampede the broker in the same instant, and refreshes not at all while the
 * tab is hidden or the market is closed. The backend shares one answer across
 * every client for a short TTL, so a second chart on the same underlying is
 * free.
 */

const RED = '#ef4444'
const GREEN = '#22c55e'
const ZERO_LINE_COLOR = '#94a3b8'
const OUTLINE_COLOR = '#e2e8f0'
const MAX_PAIN_COLOR = '#eab308'
const TOOLTIP_BG = 'rgba(23, 23, 23, 0.94)'
const TOOLTIP_FG = '#f8fafc'
const HOVER_ID = 'oi-profile-strike:'

// Open interest is read in lakhs and crores by everyone who trades these, and
// that is how Sensibull prints it, so "26.37L" rather than "2,637,000".
function formatLakh(value) {
  const n = Number(value) || 0
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs >= 1e7) return `${sign}${(abs / 1e7).toFixed(2)}Cr`
  if (abs >= 1e5) return `${sign}${(abs / 1e5).toFixed(2)}L`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(2)}K`
  return `${sign}${Math.round(abs)}`
}

// "+26.37L (+43.3%)": the day's change in OI, signed, and its size against
// what the strike carried into the day. A strike that carried nothing in has
// no percentage to give, so it reads "new".
function changeText(oi, prev) {
  const chg = (Number(oi) || 0) - (Number(prev) || 0)
  const sign = chg > 0 ? '+' : ''
  const pct = prev > 0 ? `${sign}${((chg / prev) * 100).toFixed(1)}%` : 'new'
  return `${sign}${formatLakh(chg)} (${pct})`
}

// Sensibull reads calls as resistance and paints them red; the rest of
// OpenAlgo, including the /oiprofile page, paints calls green. Both are in
// use, so the chart offers both rather than picking a side.
const COLOR_SCHEMES = {
  sensibull: { ce: RED, pe: GREEN },
  openalgo: { ce: GREEN, pe: RED },
}

/**
 * The strike where option buyers lose the most, which is where the writers
 * would rather see expiry settle. Payoff to holders at each candidate
 * settlement, summed over every strike; the cheapest one wins.
 *
 * Computed over every strike the profile fetched (Strikes Around ATM either
 * side), never just the ones that happen to be on screen. It is not the whole
 * option chain: open interest beyond that window is left out, so the marker
 * is labelled as window-limited. A wider window moves it closer to the
 * full-chain figure. Never the on-screen strikes: max pain is a property of
 * the open interest, and one that moved
 * every time the user zoomed would be worse than none at all.
 *
 * ponytail: O(strikes^2) over the ~41 rows the chain carries, which is under
 * two thousand operations, and it is memoised per chain - move it to the
 * service only if the chain ever grows by an order of magnitude.
 */
function maxPainStrike(chain) {
  let best = null
  for (const settle of chain) {
    const settleStrike = Number(settle.strike)
    if (!Number.isFinite(settleStrike)) continue
    let pain = 0
    for (const r of chain) {
      const strike = Number(r.strike)
      if (!Number.isFinite(strike)) continue
      if (settleStrike > strike) pain += (Number(r.ce_oi) || 0) * (settleStrike - strike)
      if (settleStrike < strike) pain += (Number(r.pe_oi) || 0) * (strike - settleStrike)
    }
    if (best === null || pain < best.pain) best = { strike: settleStrike, pain }
  }
  return best?.strike ?? null
}

/**
 * The chain as one expiry sees it, for max pain.
 *
 * Max pain is where ONE expiry settles. With several expiries combined, the
 * bars sum their open interest per strike, and a max pain taken over that sum
 * is a blend no contract ever settles at. So it is taken over the legs of the
 * nearest expiry alone, picked by symbol prefix (NIFTY + 22SEP26), each at its
 * live OI where `legOi` has one.
 *
 * Returns null when the chain carries no legs to filter, so the caller keeps
 * the summed chain rather than computing max pain over nothing.
 */
export function nearestExpiryRows(chain, prefix, legOi = (leg) => Number(leg.oi) || 0) {
  if (!prefix) return null
  const p = String(prefix).toUpperCase()
  let sawLeg = false
  const rows = chain.map((row) => {
    const sum = (legs) => {
      let total = 0
      for (const leg of legs ?? []) {
        if (!String(leg.symbol).toUpperCase().startsWith(p)) continue
        sawLeg = true
        total += legOi(leg)
      }
      return total
    }
    return { strike: row.strike, ce_oi: sum(row.ce_legs), pe_oi: sum(row.pe_legs) }
  })
  return sawLeg ? rows : null
}

export { maxPainStrike }

/**
 * Half the height of one strike row, in pixels. Few strikes on screen get fat
 * readable rows; a crowded pane gets thin ones that cannot overlap.
 */
function rowHalfHeight(rows) {
  const n = rows.length
  // Never taller than the real spacing between neighbouring strikes. The
  // sizes below assume a full-height pane; in a small pane (a multi-chart
  // grid) a 20px half row over strikes 12px apart drew every row over its
  // neighbours.
  let minGap = Infinity
  for (let i = 1; i < n; i++) minGap = Math.min(minGap, Math.abs(rows[i].y - rows[i - 1].y))
  const fit = Number.isFinite(minGap) ? Math.max(1.5, minGap / 2) : Infinity
  let half
  if (n < 5) half = 20
  else if (n < 10) half = 15
  else if (n < 15) half = 10
  else if (n < 20) half = 7.5
  else half = Math.max(2, Math.min(5, Math.abs(rows[n - 1].y - rows[0].y) / n / 2))
  return Math.min(half, fit)
}

/**
 * The settings that change what the server is asked for. A change to any of
 * them clears the chart and refetches; a change to anything else (colours, bar
 * width, the markers) only has to repaint, which happens on the next frame.
 *
 * Mode and the outline are not here: they choose which columns of the same
 * answer are drawn. Keying on them cleared the chart and refetched both passes
 * on every toggle, although the change columns were usually already loaded.
 * viewKey() handles them.
 */
function dataKey(settings, symbol) {
  return [
    resolveUnderlying(settings, symbol),
    resolveExchange(settings, resolveUnderlying(settings, symbol)),
    String(settings.expiryDate ?? '').toUpperCase(),
    String(settings.expiries ?? 1),
    String(settings.strikes ?? 25),
  ].join('|')
}

/** The settings that only choose what is drawn from the data already held. */
function viewKey(settings) {
  return [
    settings.mode === 'oi' ? 'oi' : 'change',
    settings.outline === false ? 'plain' : 'outline',
  ].join('|')
}

/** The chart's own symbol is a good default: NIFTY30OCT25FUT -> NIFTY. */
function resolveUnderlying(settings, symbol) {
  const typed = String(settings.underlying ?? '').trim().toUpperCase()
  if (typed) return typed
  return String(symbol ?? '')
    .toUpperCase()
    // A future or an option charted on its own is still a view of its
    // underlying, so strip the contract off and profile what it is written on.
    // Without the option case, charting TMPV29SEP26320CE asked the backend for
    // the strikes of an option, which cannot exist: two failed calls and two
    // console errors every time an option was charted.
    .replace(/\d{2}[A-Z]{3}\d{2}FUT$/, '')
    .replace(/\d{2}[A-Z]{3}\d{2}[\d.]*(?:CE|PE)$/, '')
    // '&' and '-' are part of real underlyings (M&M, BAJAJ-AUTO). Stripping
    // them asked for "MM" and "BAJAJAUTO", which have no expiries, and the
    // profile stayed blank on those charts.
    .replace(/[^A-Z0-9&-]/g, '')
}

/** Whether the Exchange setting is left on Auto (or was never set). */
function isAutoExchange(settings) {
  const typed = String(settings.exchange ?? '').trim().toUpperCase()
  return !typed || typed === 'AUTO'
}

// Where Auto looks for an underlying's options when its first guess has none.
const FNO_EXCHANGES = ['NFO', 'BFO', 'MCX']

/** HH:MM in the chart's zone, for the status line. */
function clockTime(ms, timeZone) {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timeZone || undefined,
    }).format(ms)
  } catch {
    return new Date(ms).toTimeString().slice(0, 5)
  }
}

/**
 * The F&O exchange to try first for the underlying's options. Left on Auto -
 * which is the default - the BSE indices go to BFO and everything else to NFO,
 * so a SENSEX chart needs no setting at all; an underlying with no options
 * there (CRUDEOIL, GOLD) is then found on the other F&O exchanges by
 * resolveExpiries. A saved 'NFO', 'BFO' or 'MCX' always wins.
 */
function resolveExchange(settings, underlying) {
  const typed = String(settings.exchange ?? '').trim().toUpperCase()
  if (typed && typed !== 'AUTO') return typed
  return /^(SENSEX|BANKEX)/.test(underlying) ? 'BFO' : 'NFO'
}

/** Nearest `count` option expiries for an underlying, as DDMMMYY. */
async function fetchNearestExpiries(exchange, underlying, count) {
  const url =
    `/search/api/expiries?exchange=${encodeURIComponent(exchange)}` +
    `&underlying=${encodeURIComponent(underlying)}&instrumenttype=options`
  const res = await fetch(url, { credentials: 'same-origin' })
  if (!res.ok) return []
  const body = await res.json()
  const list = Array.isArray(body?.expiries) ? body.expiries : []
  // The search API answers 26-NOV-25; the profile endpoint wants 26NOV25.
  return list.slice(0, count).map((e) => String(e).replace(/-/g, '').toUpperCase())
}

/**
 * Lay live OI over a polled chain. Mirrors frontend/src/lib/oiProfileLive.ts,
 * so the chart and the /oiprofile page never disagree about a strike:
 * - a contract with a usable tick takes the tick's OI, everything else keeps
 *   the polled number;
 * - a 0 tick is unknown (some adapters send 0 for "not in this packet"), never
 *   an emptied contract;
 * - a tick older than `maxAgeMs` is no longer live, so a feed that goes quiet
 *   falls back to the polled number instead of freezing on its last value;
 * - the change is the sum over contracts with a known anchor (`base`) of
 *   `oi - base`, exactly as the server builds it.
 *
 * `liveOi` maps an uppercased symbol to `{ oi, at }` (epoch ms).
 */
export function overlayLiveOi(chain, liveOi, now = Date.now(), maxAgeMs = Number.POSITIVE_INFINITY) {
  let live = 0
  const tickFor = (symbol) => {
    const t = liveOi.get(String(symbol).toUpperCase())
    if (!t || !(t.oi > 0) || now - t.at > maxAgeMs) return null
    return t.oi
  }
  const next = chain.map((row) => {
    const out = { ...row }
    for (const side of ['ce', 'pe']) {
      const legs = row[`${side}_legs`]
      if (!Array.isArray(legs) || legs.length === 0) continue
      let total = 0
      let change = 0
      let sawLive = false
      for (const leg of legs) {
        const tick = tickFor(leg.symbol)
        const oi = tick ?? (Number(leg.oi) || 0)
        total += oi
        if (tick !== null) {
          sawLive = true
          live += 1
        }
        if (leg.base != null) change += oi - leg.base
      }
      if (!sawLive) continue
      out[`${side}_oi`] = total
      out[`${side}_oi_change`] = change
    }
    return out
  })
  return { chain: next, live }
}

export default function ({ registerIndicator, nulls, subscribeQuotes }) {
  registerIndicator({
    id: 'oi-profile-live',
    name: 'OI Profile',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'underlying', type: 'text', label: 'Underlying', default: '', group: 'Instrument' },
      {
        key: 'exchange', type: 'select', label: 'Exchange', default: 'auto', group: 'Instrument',
        options: [
          { label: 'Auto', value: 'auto' },
          { label: 'NFO', value: 'NFO' },
          { label: 'BFO', value: 'BFO' },
          { label: 'MCX', value: 'MCX' },
        ],
      },
      { key: 'expiries', type: 'number', label: 'Expiries To Combine', default: 1, min: 1, max: 6, step: 1, group: 'Instrument' },
      { key: 'expiryDate', type: 'expiries', label: 'Expiry Used', default: '', group: 'Instrument' },
      {
        key: 'mode', type: 'select', label: 'Mode', default: 'oi', group: 'Display',
        options: [
          { label: 'Open Interest', value: 'oi' },
          { label: 'Change in OI (Daily)', value: 'change' },
        ],
      },
      {
        key: 'colors', type: 'select', label: 'Colours', default: 'sensibull', group: 'Display',
        options: [
          { label: 'Calls red, Puts green', value: 'sensibull' },
          { label: 'Calls green, Puts red', value: 'openalgo' },
        ],
      },
      {
        key: 'strikes', type: 'select', label: 'Strikes Around ATM', default: '25', group: 'Instrument',
        options: [
          { label: '5', value: '5' },
          { label: '10', value: '10' },
          { label: '25', value: '25' },
          { label: '50', value: '50' },
        ],
      },
      { key: 'outline', type: 'boolean', label: 'Previous Session Outline', default: true, group: 'Display' },
      { key: 'maxPain', type: 'boolean', label: 'Max Pain Marker (strikes fetched)', default: true, group: 'Display' },
      { key: 'barWidth', type: 'number', label: 'Max Bar Width (px)', default: 140, min: 20, max: 400, step: 10, group: 'Display' },
      { key: 'opacity', type: 'number', label: 'Bar Opacity (%)', default: 55, min: 10, max: 100, step: 5, group: 'Display' },
      { key: 'refreshSeconds', type: 'number', label: 'Refresh (seconds)', default: 180, min: 60, max: 900, step: 30, group: 'Display' },
      { key: 'statusLine', type: 'boolean', label: 'Status Line (last update, problems)', default: true, group: 'Display' },
    ],

    // Required by the contract (at least one plot); the real drawing is the
    // addPrimitive() overlay below, so this stays invisible.
    plots: [{ key: 'ph', type: 'line', title: 'OI Profile', style: { visible: false } }],

    calc(bars) {
      return { ph: nulls(new Array(bars.length).fill(NaN)) }
    },

    attach(ctx) {
      let cancelled = false
      let timer = null
      let csrfToken = null
      // What the primitive actually reads each frame. Updated by the poller,
      // read fresh on every draw() call — no recompute plumbing needed.
      // `mode` is what the user asked for; `valueMode` is what the numbers on
      // screen actually are. They differ for the second or two between the
      // fast open-interest answer and the slower change answer.
      const state = {
        chain: null,
        mode: 'oi',
        valueMode: 'oi',
        hasChange: false,
        maxPain: null,
        marketOpen: true,
        // Set from the backend: some legs' previous-session OI is still being
        // fetched, so the change columns are incomplete and the next beat
        // should come soon rather than in three minutes.
        changePending: false,
        // What the status line says. `updatedAt` is when the last chain landed;
        // `problem` is why the latest attempt did not, or null when it did.
        updatedAt: 0,
        problem: null,
        loadingFor: '',
        // Set from each answer. `nearestPrefix` names the nearest expiry's
        // contracts (NIFTY22SEP26) when several expiries are combined, so max
        // pain can be taken over that expiry alone; null for a single expiry.
        nearestPrefix: null,
        nearestExpiry: '',
        optionsExchange: '',
        atmStrike: null,
      }

      // Where every bar lands this frame. draw() paints from it and hitTest()
      // reads the same numbers, so the row the tooltip names is the row under
      // the cursor rather than a second, slightly different, calculation.
      const layout = (rc, settings) => {
        const chain = state.chain
        if (!Array.isArray(chain) || chain.length === 0) return null

        const key = state.valueMode === 'oi' ? 'ce_oi' : 'ce_oi_change'
        const putKey = state.valueMode === 'oi' ? 'pe_oi' : 'pe_oi_change'
        const rightEdge = rc.plotWidth
        const paneHeight = rc.plotHeight
        // Read live: a width typed into the settings dialog should move the
        // bars on the next frame, not on the next poll three minutes away.
        const maxWidthPx = Math.min(rightEdge * 0.6, Math.max(20, Number(settings.barWidth) || 140))

        // Only strikes whose price is on screen are worth a rectangle. A
        // zoomed-in chart then draws a handful of rows instead of forty.
        const rows = []
        for (const s of chain) {
          const strike = Number(s.strike)
          if (!Number.isFinite(strike)) continue
          const y = rc.priceScale.priceToY(strike)
          if (y == null || Number.isNaN(y) || y < -20 || y > paneHeight + 20) continue
          rows.push({
            strike,
            y,
            ce: Number(s[key]) || 0,
            pe: Number(s[putKey]) || 0,
            // Total OI regardless of the view, for max pain; and what the
            // strike carried into the day, which is simply the total less
            // what changed during it.
            ceOi: Number(s.ce_oi) || 0,
            peOi: Number(s.pe_oi) || 0,
            cePrev: (Number(s.ce_oi) || 0) - (Number(s.ce_oi_change) || 0),
            pePrev: (Number(s.pe_oi) || 0) - (Number(s.pe_oi_change) || 0),
          })
        }
        if (rows.length === 0) return null
        rows.sort((a, b) => a.y - b.y)

        // Change in OI is signed, so the scale spans both sides of zero and
        // the origin moves inward. Without this an unwind and a build draw
        // the same bar.
        let maxVal = 0
        let minVal = 0
        for (const r of rows) {
          maxVal = Math.max(maxVal, r.ce, r.pe)
          minVal = Math.min(minVal, r.ce, r.pe)
        }
        const span = maxVal - minVal || 1
        const scale = maxWidthPx / span
        const originX = rightEdge - Math.abs(minVal) * scale

        // Row height follows how many strikes share the pane, so rows never
        // merge into a smear when the chart is zoomed out.
        const halfPx = rowHalfHeight(rows)
        return { rows, halfPx, scale, originX, rightEdge, maxWidthPx, minVal, maxVal }
      }

      // The strike whose pair of bars straddles this y, or null.
      const rowAt = (geom, y) =>
        geom.rows.find((r) => y >= r.y - geom.halfPx && y <= r.y + geom.halfPx) ?? null

      // Where the cursor was when the chart last hit-tested us. Only read
      // while `rc.hoverId` says the pointer is still on one of our rows, so
      // it cannot go stale: the chart clears hoverId when the pointer leaves.
      let hoverPoint = null

      // The strikes the last frame actually drew, lowest and highest. The live
      // feed streams the legs around these rather than the whole chain.
      let visibleRange = null

      // One line, written for a trader: when the bars were last refreshed, or
      // why they are not there. Every failure used to be silent, so a profile
      // that could not load looked the same as one with nothing to show.
      const statusText = () => {
        const p = state.problem
        const hasChain = Array.isArray(state.chain) && state.chain.length > 0
        const updated = state.updatedAt
          ? `Updated ${clockTime(state.updatedAt, ctx.timezone?.())}`
          : ''
        if (p?.kind === 'no-expiries') {
          return `OI Profile: no option expiries found for ${p.underlying}. Check the Underlying and Exchange settings.`
        }
        if (p?.kind === 'failed') {
          return hasChain
            ? `OI Profile: ${updated}. The last refresh failed; retrying.`
            : `OI Profile: could not load ${p.underlying}; retrying.`
        }
        if (!hasChain) return state.loadingFor ? `OI Profile: loading ${state.loadingFor}` : ''
        let text = `OI Profile: ${updated}`
        // Change mode with no change columns yet shows totals for now; say so
        // rather than let them pass for the change.
        if (state.mode !== 'oi' && (state.changePending || !state.hasChange)) {
          text += ', change still loading'
        }
        if (!state.marketOpen) text += ' (market closed)'
        // Put/call ratio over every strike fetched (Strikes Around ATM either
        // side), the one number most readers look for first.
        let ce = 0
        let pe = 0
        for (const r of state.chain) {
          ce += Number(r.ce_oi) || 0
          pe += Number(r.pe_oi) || 0
        }
        if (ce > 0) text += ` | PCR ${(pe / ce).toFixed(2)}`
        return text
      }

      const drawStatus = (canvasCtx, rc, dpr, settings) => {
        const text = statusText()
        if (!text) return
        const fontPx = 10
        canvasCtx.save()
        canvasCtx.font = `${fontPx * dpr}px ui-sans-serif, system-ui, sans-serif`
        canvasCtx.textBaseline = 'top'
        const w = canvasCtx.measureText(text).width / dpr
        const pad = 4
        // Left of the bar column, not over it: at the top right it hid the
        // bars of whichever strike sat near the top of the pane. Seen on the
        // live chart, not in a test. A pane too narrow for both gives the
        // line its left edge.
        const barColumn = Math.min(rc.plotWidth * 0.6, Math.max(20, Number(settings.barWidth) || 140))
        const x = Math.max(4, rc.plotWidth - barColumn - w - pad * 2 - 10)
        const y = 6
        canvasCtx.globalAlpha = 0.85
        canvasCtx.fillStyle = TOOLTIP_BG
        canvasCtx.beginPath()
        canvasCtx.roundRect(x * dpr, y * dpr, (w + pad * 2) * dpr, (fontPx + pad * 2) * dpr, 4 * dpr)
        canvasCtx.fill()
        canvasCtx.globalAlpha = 1
        canvasCtx.fillStyle = state.problem ? MAX_PAIN_COLOR : TOOLTIP_FG
        canvasCtx.fillText(text, (x + pad) * dpr, (y + pad) * dpr)
        canvasCtx.restore()
      }

      const primitive = {
        zOrder() {
          return 'top'
        },

        // Hovering a strike names it, the way Sensibull's profile does. The
        // chart owns hover state - it calls this as the pointer moves and
        // reports the winner back on `rc.hoverId` - so there is no listener
        // to add and nothing to clean up when the pointer leaves.
        hitTest(x, y, rc) {
          const geom = layout(rc, ctx.settings())
          if (!geom) return null
          // Only over the bars themselves, not the whole width of the pane.
          if (x < geom.rightEdge - geom.maxWidthPx || x > geom.rightEdge) return null
          const row = rowAt(geom, y)
          if (!row) return null
          hoverPoint = { x, y }
          return {
            externalId: `${HOVER_ID}${row.strike}`,
            zOrder: 'top',
            // Honest distance, so a price line actually under the cursor
            // still wins the pick instead of being swallowed by the profile.
            distance: Math.abs(y - row.y),
          }
        },

        draw(canvasCtx, rc) {
          // The canvas is sized in device pixels while the scales answer in
          // CSS pixels, so every coordinate is worked out in CSS pixels and
          // multiplied by `dpr` at the moment it is painted. Skip that and the
          // whole profile lands at half scale in the top-left on a retina
          // screen, which is exactly what it looks like: drawn, but nowhere
          // near the price it belongs to.
          const dpr = rc.dpr || 1
          // Read at paint time, so flipping the scheme repaints immediately
          // instead of waiting for the next poll.
          const settings = ctx.settings()

          // Painted before the early return below: an empty profile is exactly
          // when the reader most needs to be told why.
          if (settings.statusLine !== false) drawStatus(canvasCtx, rc, dpr, settings)

          const chain = state.chain
          if (!Array.isArray(chain) || chain.length === 0) return
          const scheme = COLOR_SCHEMES[settings.colors] ?? COLOR_SCHEMES.sensibull
          const key = state.valueMode === 'oi' ? 'ce_oi' : 'ce_oi_change'
          const putKey = state.valueMode === 'oi' ? 'pe_oi' : 'pe_oi_change'
          const geom = layout(rc, settings)
          if (!geom) return
          const { rows, halfPx, scale, originX, rightEdge, maxWidthPx, minVal } = geom
          let lo = Infinity
          let hi = -Infinity
          for (const r of rows) {
            lo = Math.min(lo, r.strike)
            hi = Math.max(hi, r.strike)
          }
          visibleRange = { lo, hi }

          canvasCtx.save()
          // Read live, so dragging the slider repaints on the next frame.
          const barAlpha = Math.min(1, Math.max(0.1, (Number(settings.opacity) || 55) / 100))
          canvasCtx.globalAlpha = barAlpha
          const bar = (value, top, color) => {
            const width = value * scale
            if (Math.abs(width) < 0.5) return
            canvasCtx.beginPath()
            canvasCtx.fillStyle = color
            canvasCtx.fillRect(
              (width >= 0 ? originX - width : originX) * dpr,
              top * dpr,
              Math.abs(width) * dpr,
              Math.max(1, halfPx - 1) * dpr
            )
            canvasCtx.closePath()
          }
          for (const r of rows) {
            bar(r.ce, r.y - halfPx, scheme.ce)
            bar(r.pe, r.y + 1, scheme.pe)
          }

          // Yesterday's open interest, outlined over today's bar: the gap
          // between the two edges is the day's build or unwind, without
          // having to switch the view to read it. Only meaningful while the
          // bars are open interest - on a change scale there is no such thing
          // as a previous total.
          if (settings.outline !== false && state.valueMode === 'oi' && state.hasChange) {
            canvasCtx.globalAlpha = 0.9
            canvasCtx.strokeStyle = OUTLINE_COLOR
            canvasCtx.lineWidth = Math.max(1, dpr)
            canvasCtx.setLineDash([3 * dpr, 2 * dpr])
            const outline = (value, top) => {
              const width = value * scale
              if (Math.abs(width) < 1.5) return
              canvasCtx.strokeRect(
                (width >= 0 ? originX - width : originX) * dpr,
                top * dpr,
                Math.abs(width) * dpr,
                Math.max(1, halfPx - 1) * dpr
              )
            }
            for (const r of rows) {
              outline(r.cePrev, r.y - halfPx)
              outline(r.pePrev, r.y + 1)
            }
            canvasCtx.setLineDash([])
          }

          // Max pain: where the most option value expires worthless. Taken
          // over the whole chain and cached with it, so panning and zooming
          // cost nothing and never move the line.
          if (settings.maxPain !== false) {
            const strike = state.maxPain
            const row = rows.find((r) => r.strike === strike)
            if (row) {
              canvasCtx.globalAlpha = 0.9
              canvasCtx.strokeStyle = MAX_PAIN_COLOR
              canvasCtx.lineWidth = Math.max(1, dpr)
              canvasCtx.setLineDash([5 * dpr, 3 * dpr])
              canvasCtx.beginPath()
              canvasCtx.moveTo((rightEdge - maxWidthPx) * dpr, row.y * dpr)
              canvasCtx.lineTo(rightEdge * dpr, row.y * dpr)
              canvasCtx.stroke()
              canvasCtx.setLineDash([])
              canvasCtx.fillStyle = MAX_PAIN_COLOR
              canvasCtx.font = `${10 * dpr}px ui-sans-serif, system-ui, sans-serif`
              canvasCtx.textBaseline = 'bottom'
              canvasCtx.fillText(
                // With expiries combined, say which one it is for: it is the
                // nearest expiry's, not the summed bars'.
                state.nearestPrefix
                  ? `Max Pain ${strike} (${state.nearestExpiry})`
                  : `Max Pain ${strike}`,
                (rightEdge - maxWidthPx) * dpr,
                (row.y - 2) * dpr
              )
            }
          }

          // The zero rule, drawn only when something is negative.
          if (minVal < 0) {
            canvasCtx.globalAlpha = 0.5
            canvasCtx.lineWidth = dpr
            canvasCtx.beginPath()
            canvasCtx.moveTo(originX * dpr, (rows[0].y - halfPx * 2) * dpr)
            canvasCtx.lineTo(originX * dpr, (rows[rows.length - 1].y + halfPx * 2) * dpr)
            canvasCtx.strokeStyle = ZERO_LINE_COLOR
            canvasCtx.stroke()
            canvasCtx.closePath()
          }
          // The hovered strike, named. `rc.hoverId` is the chart's own pick,
          // so this appears and disappears with the pointer without the
          // indicator tracking it.
          const hoveredStrike =
            typeof rc.hoverId === 'string' && rc.hoverId.startsWith(HOVER_ID)
              ? Number(rc.hoverId.slice(HOVER_ID.length))
              : null
          const hoveredRow =
            hoveredStrike != null && hoverPoint
              ? rows.find((r) => r.strike === hoveredStrike)
              : null
          if (hoveredRow) {
            // Named for what the bars currently are. Showing "Chg" over totals
            // (or the reverse) is worse than showing nothing: the reader has
            // no way to tell it is wrong.
            const isChange = state.valueMode !== 'oi'
            const lines = [
              { text: `Strike: ${hoveredRow.strike}`, color: null },
              {
                text: `Call OI${isChange ? ' Chg' : ''}: ${formatLakh(hoveredRow.ce)}`,
                color: scheme.ce,
              },
              {
                text: `Put OI${isChange ? ' Chg' : ''}: ${formatLakh(hoveredRow.pe)}`,
                color: scheme.pe,
              },
            ]
            // The other half of the picture, so one hover answers both "how
            // much is there" and "how much of it is today's": the change (with
            // its size against what the strike carried in) under Open
            // Interest, the totals under Change in OI, and the strike's PCR.
            if (isChange) {
              lines.push({
                text: `Totals: Call ${formatLakh(hoveredRow.ceOi)}, Put ${formatLakh(hoveredRow.peOi)}`,
                color: null,
              })
            } else if (state.hasChange) {
              lines.push(
                { text: `Call Chg: ${changeText(hoveredRow.ceOi, hoveredRow.cePrev)}`, color: scheme.ce },
                { text: `Put Chg: ${changeText(hoveredRow.peOi, hoveredRow.pePrev)}`, color: scheme.pe }
              )
            }
            if (hoveredRow.ceOi > 0) {
              lines.push({ text: `PCR: ${(hoveredRow.peOi / hoveredRow.ceOi).toFixed(2)}`, color: null })
            }

            canvasCtx.globalAlpha = 1
            const fontPx = 11
            canvasCtx.font = `${fontPx * dpr}px ui-sans-serif, system-ui, sans-serif`
            const padPx = 8
            const linePx = fontPx + 5
            const swatchPx = 8
            const textWidth = Math.max(
              ...lines.map((l) => canvasCtx.measureText(l.text).width / dpr)
            )
            const boxW = textWidth + padPx * 2 + swatchPx + 6
            const boxH = lines.length * linePx + padPx * 2 - 4

            // Sits to the left of the bars, where it covers the empty margin
            // rather than the profile the reader is pointing at. Clamped so
            // it cannot slide off the top or bottom of the pane.
            let boxX = Math.min(hoverPoint.x, rightEdge - maxWidthPx) - boxW - 10
            if (boxX < 4) boxX = Math.min(hoverPoint.x + 14, rightEdge - boxW - 4)
            const boxY = Math.max(4, Math.min(hoveredRow.y - boxH / 2, rc.plotHeight - boxH - 4))

            canvasCtx.fillStyle = TOOLTIP_BG
            canvasCtx.beginPath()
            canvasCtx.roundRect(boxX * dpr, boxY * dpr, boxW * dpr, boxH * dpr, 6 * dpr)
            canvasCtx.fill()

            canvasCtx.textBaseline = 'top'
            lines.forEach((line, i) => {
              const lineY = boxY + padPx - 2 + i * linePx
              let textX = boxX + padPx
              if (line.color) {
                canvasCtx.fillStyle = line.color
                canvasCtx.fillRect(
                  textX * dpr,
                  (lineY + 2) * dpr,
                  swatchPx * dpr,
                  swatchPx * dpr
                )
                textX += swatchPx + 6
              }
              canvasCtx.fillStyle = TOOLTIP_FG
              canvasCtx.fillText(line.text, textX * dpr, lineY * dpr)
            })
          }

          canvasCtx.restore()
        },
      }

      ctx.addPrimitive(primitive)

      let csrfPromise = null
      const getCsrfToken = async (forceRefresh) => {
        if (csrfToken && !forceRefresh) return csrfToken
        if (!csrfPromise || forceRefresh) {
          csrfPromise = fetch('/auth/csrf-token', { credentials: 'same-origin' })
            .then((res) => (res.ok ? res.json() : null))
            .then((body) => {
              csrfToken = body?.csrf_token ?? null
              // No token is not an answer to keep: ask again next time.
              if (!csrfToken) csrfPromise = null
              return csrfToken
            })
            .catch((err) => {
              // A network blip must not be cached. Kept, the rejected promise
              // was handed back on every later beat without a new request, so
              // one failed fetch stopped the profile until the page reloaded.
              csrfPromise = null
              throw err
            })
        }
        return csrfPromise
      }

      const postProfileData = async (payload, isRetry) => {
        const token = await getCsrfToken(!!isRetry)
        const res = await fetch('/oiprofile/api/profile-data', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'X-CSRFToken': token } : {}),
          },
          body: JSON.stringify(payload),
        })
        if (res.status === 400 && !isRetry) return postProfileData(payload, true)
        return res
      }

      // Nearest-expiry lookups are cached per underlying+exchange+count so a
      // three-minute beat does not re-ask the symbol database every time. The
      // list does go stale - an expiry drops out of it the moment it expires -
      // so the cache is held for half an hour, not for the life of the page.
      const EXPIRY_CACHE_MS = 30 * 60 * 1000
      let expiryCacheKey = null
      let expiryCache = { exchange: '', expiries: [] }
      let expiryCachedAt = 0
      // The exchange Auto found an underlying's options on, so a hand-picked
      // expiry list for CRUDEOIL is asked of MCX rather than of NFO.
      const foundOn = new Map()

      // `expiryDate` is a comma-separated pick list, the way Sensibull ticks
      // its expiries. A single value is the old override and still works.
      // Answers { exchange, expiries }: on Auto the exchange is whichever one
      // actually lists options for the underlying.
      const resolveExpiries = async (settings, underlying) => {
        const preferred = resolveExchange(settings, underlying)
        const auto = isAutoExchange(settings)
        const picked = String(settings.expiryDate ?? '')
          .toUpperCase()
          .split(',')
          .map((e) => e.replace(/[^A-Z0-9]/g, ''))
          .filter(Boolean)
        if (picked.length) {
          const exchange = auto ? (foundOn.get(underlying) ?? preferred) : preferred
          return { exchange, expiries: picked }
        }

        const count = Math.min(6, Math.max(1, Math.floor(Number(settings.expiries) || 1)))
        const key = `${auto ? 'AUTO' : preferred}|${underlying}|${count}`
        const fresh = Date.now() - expiryCachedAt < EXPIRY_CACHE_MS
        if (key !== expiryCacheKey || expiryCache.expiries.length === 0 || !fresh) {
          let answer = {
            exchange: preferred,
            expiries: await fetchNearestExpiries(preferred, underlying, count),
          }
          // Auto's first guess is only a guess: CRUDEOIL has no options on NFO
          // and used to draw nothing at all. One cheap symbol-database lookup
          // per exchange, and only when the guess came back empty.
          if (answer.expiries.length === 0 && auto) {
            for (const exchange of FNO_EXCHANGES) {
              if (exchange === preferred) continue
              const expiries = await fetchNearestExpiries(exchange, underlying, count)
              if (expiries.length > 0) {
                answer = { exchange, expiries }
                break
              }
            }
          }
          if (answer.expiries.length > 0) foundOn.set(underlying, answer.exchange)
          // An empty answer for the instrument already on screen is far more
          // likely a lookup hiccup than expiries vanishing: keep the last good
          // list (and its age, so the next beat asks again) rather than blank
          // a chart that was right a moment ago.
          if (answer.expiries.length > 0 || key !== expiryCacheKey) {
            expiryCache = answer
            expiryCacheKey = key
            expiryCachedAt = Date.now()
          }
        }
        return expiryCache
      }

      // Only one chain request may be in flight, and only the newest one may
      // land: a user switching underlying while a slow change pass is running
      // would otherwise get the previous instrument's open interest painted
      // over the new one.
      let generation = 0
      let inFlight = false
      let lastFetchAt = 0

      // Everything derived from a chain is derived once, here, rather than on
      // every animation frame.
      // `meta` is what the request was for: the nearest expiry's symbol prefix
      // when several expiries are combined (for max pain), else null.
      const applyChain = (body, valueMode, hasChange, meta = {}) => {
        const chain = Array.isArray(body.oi_chain) ? body.oi_chain : null
        polledChain = chain
        state.valueMode = valueMode
        state.hasChange = hasChange
        state.marketOpen = body.market_open !== false
        state.updatedAt = Date.now()
        state.problem = null
        state.nearestPrefix = meta.prefix ?? null
        state.nearestExpiry = meta.expiry ?? ''
        state.optionsExchange = body.options_exchange ?? ''
        state.atmStrike = Number.isFinite(Number(body.atm_strike)) ? Number(body.atm_strike) : null
        syncLive()
        redraw()
      }

      // Live open interest. Where the broker's feed carries `oi`, the ticks
      // keep the bars current between polls at no cost to the broker API, over
      // the page's one shared socket. A host without `subscribeQuotes`, or a
      // feed that never sends `oi`, leaves the polled numbers exactly as they were.
      let polledChain = null
      const liveOi = new Map()
      let liveDirty = false
      // One subscription per streamed leg, symbol -> unsubscribe, so a change
      // in which legs are wanted adds and drops only the difference.
      const liveSubs = new Map()
      let liveExchange = ''

      // At most this many legs stream at once. The broker feed is shared with
      // every chart and watchlist on the account (about 3,000 symbols per
      // broker), and the whole chain was up to 1,212 legs (50 strikes either
      // side, six expiries). The legs streamed are the ones around the strikes
      // on screen, which is where a live number can be seen at all.
      const MAX_LIVE_LEGS = 160
      // Strikes beyond the visible edge still streamed, so a small pan does not
      // start with stale bars at the edge.
      const LIVE_MARGIN_STRIKES = 3

      // The live OI of one leg if a fresh tick holds it, else its polled OI.
      const legOi = (leg) => {
        const t = liveOi.get(String(leg.symbol).toUpperCase())
        if (t && t.oi > 0 && Date.now() - t.at <= beatSeconds() * 1000) return t.oi
        return Number(leg.oi) || 0
      }

      const redraw = () => {
        const chain = polledChain
        // A tick older than one refresh beat no longer counts as live: when the
        // next poll lands, a contract whose feed went quiet shows the poll.
        state.chain =
          chain && liveOi.size
            ? overlayLiveOi(chain, liveOi, Date.now(), beatSeconds() * 1000).chain
            : chain
        if (state.chain) {
          const nearest = chain ? nearestExpiryRows(chain, state.nearestPrefix, legOi) : null
          state.maxPain = maxPainStrike(nearest ?? state.chain)
        } else {
          state.maxPain = null
        }
        ctx.requestRecompute()
      }

      const onTick = (tick) => {
        const oi = Number(tick?.data?.oi)
        // A 0 is "not carried" on some brokers, so it must not replace the
        // last good value; that one ages out on its own if the feed stops.
        if (!(oi > 0)) return
        // When OI last arrived, not when this tick did: the host merges
        // ticks, so a price-only tick re-sends the old OI and must not keep
        // it fresh. An older host without the stamp falls back to now.
        const at = Number(tick.data.oi_updated_at) || Date.now()
        const key = String(tick.symbol).toUpperCase()
        const prev = liveOi.get(key)
        liveOi.set(key, { oi, at })
        if (prev?.oi !== oi) liveDirty = true
      }

      const stopLive = () => {
        for (const unsubscribe of liveSubs.values()) unsubscribe()
        liveSubs.clear()
        liveOi.clear()
        liveExchange = ''
      }

      // The legs worth streaming: those of the strikes nearest the middle of
      // the screen (or ATM, before the first frame), out to the visible edges
      // plus a margin, capped at MAX_LIVE_LEGS.
      const wantedLegs = (chain) => {
        const rows = (chain ?? []).filter((r) => Number.isFinite(Number(r.strike)))
        if (rows.length === 0) return new Set()
        const strikes = rows.map((r) => Number(r.strike)).sort((a, b) => a - b)
        let step = Infinity
        for (let i = 1; i < strikes.length; i++) {
          const d = strikes[i] - strikes[i - 1]
          if (d > 0) step = Math.min(step, d)
        }
        if (!Number.isFinite(step)) step = 0
        let lo = -Infinity
        let hi = Infinity
        let centre
        if (visibleRange) {
          lo = visibleRange.lo - LIVE_MARGIN_STRIKES * step
          hi = visibleRange.hi + LIVE_MARGIN_STRIKES * step
          centre = (visibleRange.lo + visibleRange.hi) / 2
        } else {
          centre = state.atmStrike ?? strikes[Math.floor(strikes.length / 2)]
        }
        const near = rows
          .filter((r) => Number(r.strike) >= lo && Number(r.strike) <= hi)
          .sort((a, b) => Math.abs(Number(a.strike) - centre) - Math.abs(Number(b.strike) - centre))
        const wanted = new Set()
        for (const row of near) {
          for (const leg of [...(row.ce_legs ?? []), ...(row.pe_legs ?? [])]) {
            if (wanted.size >= MAX_LIVE_LEGS) return wanted
            if (leg?.symbol) wanted.add(leg.symbol)
          }
        }
        return wanted
      }

      // Bring the streamed legs in line with wantedLegs(). Only the difference
      // is subscribed or dropped: a recentred chain or a pan keeps every leg
      // still in view streaming, with its last tick. Replacing the whole set
      // dropped every live number whenever ATM moved one strike.
      const syncLive = () => {
        const exchange = state.optionsExchange
        if (typeof subscribeQuotes !== 'function' || !exchange || !state.marketOpen || !polledChain) {
          stopLive()
          return
        }
        if (liveExchange && liveExchange !== exchange) stopLive()
        liveExchange = exchange
        const wanted = wantedLegs(polledChain)
        for (const [symbol, unsubscribe] of liveSubs) {
          if (wanted.has(symbol)) continue
          unsubscribe()
          liveSubs.delete(symbol)
          if (liveOi.delete(String(symbol).toUpperCase())) liveDirty = true
        }
        for (const symbol of wanted) {
          if (liveSubs.has(symbol)) continue
          liveSubs.set(symbol, subscribeQuotes([{ symbol, exchange }], onTick))
        }
      }

      // Ticks arrive far faster than bars need repainting; fold them in on a
      // slow beat instead of recomputing on every one. The same beat follows
      // the visible strikes, so a pan or zoom streams what is now on screen.
      const LIVE_REDRAW_MS = 2000
      const liveTimer = setInterval(() => {
        if (cancelled) return
        if (liveSubs.size || polledChain) syncLive()
        if (!liveDirty) return
        liveDirty = false
        redraw()
      }, LIVE_REDRAW_MS)

      // `force` is for a settings change: the run already in flight is for
      // settings nobody is looking at any more, so it is abandoned rather than
      // waited for. Bumping the generation is what abandons it - its own
      // `stale()` checks then stop it applying anything.
      const fetchChain = async (force) => {
        if (inFlight && !force) return
        inFlight = true
        const mine = ++generation
        lastFetchAt = Date.now()
        try {
          await runFetch(mine)
        } finally {
          if (mine === generation) inFlight = false
        }
      }

      const runFetch = async (mine) => {
        const stale = () => cancelled || mine !== generation
        const settings = ctx.settings()
        const underlying = resolveUnderlying(settings, ctx.symbol?.())
        state.mode = settings.mode === 'oi' ? 'oi' : 'change'
        watchedKey = dataKey(settings, ctx.symbol?.())
        if (!underlying) {
          polledChain = null
          stopLive()
          state.chain = null
          state.hasChange = false
          state.problem = null
          state.loadingFor = ''
          return
        }
        state.loadingFor = underlying
        if (!state.chain) ctx.requestRecompute()

        try {
          const { exchange, expiries } = await resolveExpiries(settings, underlying)
          if (stale()) return
          // Nothing to ask for. Leave the screen as it is: a changed
          // instrument was already cleared by the settings watcher, and an
          // unchanged one keeps its last good chain through a failed lookup.
          // Say so, though: a blank profile with no reason was the worst of it.
          if (expiries.length === 0) {
            state.problem = { kind: 'no-expiries', underlying }
            ctx.requestRecompute()
            return
          }

          const request = async (includeChange) => {
            const res = await postProfileData({
              underlying,
              exchange,
              expiry_date: expiries[0],
              expiry_dates: expiries,
              interval: '5m',
              days: 1,
              strike_count: Math.max(1, Math.floor(Number(settings.strikes) || 25)),
              include_change: includeChange,
              // The chart already has its bars; fetching futures candles here
              // costs a broker history call per refresh for nothing.
              include_candles: false,
            })
            if (stale()) return null
            if (!res.ok) throw new Error(`profile request answered ${res.status}`)
            const body = await res.json()
            if (stale()) return null
            if (body?.status !== 'success') throw new Error('profile request was refused')
            return body
          }

          // The change columns carry yesterday's open interest too, so the
          // outline needs them even when the bars themselves show OI.
          const wantsChange = state.mode !== 'oi' || settings.outline !== false

          // Several expiries combined: max pain is taken over the nearest one's
          // contracts alone, which share this symbol prefix (NIFTY22SEP26).
          const meta =
            expiries.length > 1 ? { prefix: `${underlying}${expiries[0]}`, expiry: expiries[0] } : {}

          // Open interest comes back in well under a second. The change
          // columns need yesterday's close for every leg, which is one broker
          // history call each on the first request of the session - so on a
          // first load, draw the fast answer straight away and upgrade it when
          // the slow one lands, rather than showing an empty chart while it
          // runs.
          //
          // Only on a first load. Once change columns are on screen, a routine
          // refresh asks once: the change answer already carries the open
          // interest. Asking twice cost two option-chain quotes per beat (the
          // server caches the two shapes separately) and, in between, swapped
          // the change bars for totals and dropped the outline for as long as
          // the second request took - up to twenty seconds every refresh.
          if (!wantsChange || !state.hasChange) {
            const oiBody = await request(false)
            if (!oiBody) return
            applyChain(oiBody, 'oi', false, meta)
            if (!wantsChange) return
          }

          const changeBody = await request(true)
          if (!changeBody) return
          applyChain(changeBody, state.mode === 'oi' ? 'oi' : 'change', true, meta)
          // An underlying nobody has looked at today has no previous-session
          // OI cached for its legs. The backend fetches those in the
          // background rather than holding the request, so the change columns
          // arrive over the next few beats instead of all at once.
          state.changePending = changeBody.oi_change_pending === true
        } catch {
          // A failed poll is not worth tearing the indicator down for, but it
          // is worth saying: the bars on screen (if any) are now older than
          // they look. The next beat retries on its own.
          if (stale()) return
          state.problem = { kind: 'failed', underlying }
          ctx.requestRecompute()
        }
      }

      // The refresh beat, rescheduled after each attempt rather than a fixed
      // interval: a slow response cannot stack requests on top of itself.
      const beatSeconds = () => Math.max(60, Number(ctx.settings().refreshSeconds) || 180)

      // While the backend is still filling in anchors, come back far sooner
      // than the normal beat - the columns are visibly incomplete until then.
      const PENDING_BEAT_SECONDS = 15

      const scheduleNext = (seconds) => {
        if (cancelled) return
        if (timer) clearTimeout(timer)
        // Up to 10s of jitter, so every chart open on this underlying does not
        // ask at the same instant.
        const secs = seconds ?? (state.changePending ? PENDING_BEAT_SECONDS : beatSeconds())
        timer = setTimeout(beat, secs * 1000 + Math.random() * 10000)
      }

      // A closed market cannot move, so the beat stretches rather than stops.
      // Stopping outright is a trap: `state.marketOpen` is only ever updated
      // by a fetch, so a chart left open overnight would never learn that the
      // next session had started.
      const CLOSED_BEAT_SECONDS = 15 * 60

      const beat = async () => {
        // Nothing on screen to update: skip the fetch and come back later.
        if (!document.hidden) await fetchChain()
        // A pending anchor pass outranks the closed-market stretch only while
        // the market is open; a closed market has nothing left to fill.
        scheduleNext(state.marketOpen ? undefined : CLOSED_BEAT_SECONDS)
      }

      // The settings dialog gives no change event, so the watcher polls the
      // one string that decides what gets requested. A second is far below
      // what a person notices, and comparing a joined string costs nothing.
      const SETTINGS_POLL_MS = 1000
      let watchedKey = dataKey(ctx.settings(), ctx.symbol?.())
      let watchedView = viewKey(ctx.settings())

      // Mode or outline changed: draw the other columns of what is already
      // held. Only when the change columns are missing does it fetch them, and
      // without clearing the bars on screen.
      const applyView = () => {
        const settings = ctx.settings()
        state.mode = settings.mode === 'oi' ? 'oi' : 'change'
        const wantsChange = state.mode !== 'oi' || settings.outline !== false
        if (state.hasChange || !wantsChange) {
          state.valueMode = state.hasChange ? state.mode : 'oi'
          ctx.requestRecompute()
          return
        }
        ctx.requestRecompute()
        fetchChain(true).finally(() => scheduleNext())
      }

      const watcher = setInterval(() => {
        if (cancelled) return
        const settings = ctx.settings()
        const next = dataKey(settings, ctx.symbol?.())
        if (next === watchedKey) {
          const view = viewKey(settings)
          if (view !== watchedView) {
            watchedView = view
            applyView()
          }
          return
        }
        watchedKey = next
        watchedView = viewKey(settings)
        // A changed instrument invalidates what is on screen; clear it rather
        // than leave the previous underlying's bars up while the new one loads.
        polledChain = null
        stopLive()
        state.chain = null
        state.maxPain = null
        state.changePending = false
        // The new selection has no change columns yet, so its first load takes
        // the fast open-interest pass again.
        state.hasChange = false
        state.problem = null
        state.updatedAt = 0
        ctx.requestRecompute()
        fetchChain(true).finally(() => scheduleNext())
      }, SETTINGS_POLL_MS)

      fetchChain().finally(() => scheduleNext())

      // A tab brought back to the front should not wait out the rest of a beat
      // it slept through - but flicking between tabs must not turn into a
      // request each time either.
      const onVisible = () => {
        if (document.hidden) return
        const since = state.marketOpen ? beatSeconds() * 1000 : CLOSED_BEAT_SECONDS * 1000
        if (Date.now() - lastFetchAt < since) return
        fetchChain().finally(() => scheduleNext())
      }
      document.addEventListener('visibilitychange', onVisible)

      return () => {
        cancelled = true
        if (timer) clearTimeout(timer)
        clearInterval(watcher)
        clearInterval(liveTimer)
        stopLive()
        document.removeEventListener('visibilitychange', onVisible)
        ctx.removePrimitive(primitive)
      }
    },
  })
}
