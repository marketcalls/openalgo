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
 * Computed over the WHOLE chain, never the strikes that happen to be on
 * screen: max pain is a property of the open interest, and one that moved
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
 * Half the height of one strike row, in pixels. Few strikes on screen get fat
 * readable rows; a crowded pane gets thin ones that cannot overlap.
 */
function rowHalfHeight(rows) {
  const n = rows.length
  if (n < 5) return 20
  if (n < 10) return 15
  if (n < 15) return 10
  if (n < 20) return 7.5
  const gap = Math.abs(rows[n - 1].y - rows[0].y) / n / 2
  return Math.max(2, Math.min(5, gap))
}

/**
 * The settings that change what the server is asked for. A change to any of
 * them has to refetch; a change to anything else (colours, bar width, the
 * markers) only has to repaint, which happens on the next frame anyway.
 */
function dataKey(settings, symbol) {
  return [
    resolveUnderlying(settings, symbol),
    resolveExchange(settings, resolveUnderlying(settings, symbol)),
    String(settings.expiryDate ?? '').toUpperCase(),
    String(settings.expiries ?? 1),
    String(settings.strikes ?? 25),
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
    .replace(/[^A-Z0-9]/g, '')
}

/**
 * The F&O exchange the underlying's options live on. Left on Auto - which is
 * the default - the BSE indices go to BFO and everything else to NFO, so a
 * SENSEX chart needs no setting at all. A saved 'NFO' or 'BFO' still wins.
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

export default function ({ registerIndicator, nulls }) {
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
      { key: 'maxPain', type: 'boolean', label: 'Max Pain Marker', default: true, group: 'Display' },
      { key: 'barWidth', type: 'number', label: 'Max Bar Width (px)', default: 140, min: 20, max: 400, step: 10, group: 'Display' },
      { key: 'opacity', type: 'number', label: 'Bar Opacity (%)', default: 55, min: 10, max: 100, step: 5, group: 'Display' },
      { key: 'refreshSeconds', type: 'number', label: 'Refresh (seconds)', default: 180, min: 60, max: 900, step: 30, group: 'Display' },
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
          const chain = state.chain
          if (!Array.isArray(chain) || chain.length === 0) return

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
          const scheme = COLOR_SCHEMES[settings.colors] ?? COLOR_SCHEMES.sensibull
          const key = state.valueMode === 'oi' ? 'ce_oi' : 'ce_oi_change'
          const putKey = state.valueMode === 'oi' ? 'pe_oi' : 'pe_oi_change'
          const geom = layout(rc, settings)
          if (!geom) return
          const { rows, halfPx, scale, originX, rightEdge, maxWidthPx, minVal } = geom

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
                `Max Pain ${strike}`,
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
              return csrfToken
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
      let expiryCache = []
      let expiryCachedAt = 0

      // `expiryDate` is a comma-separated pick list, the way Sensibull ticks
      // its expiries. A single value is the old override and still works.
      const resolveExpiries = async (settings, exchange, underlying) => {
        const picked = String(settings.expiryDate ?? '')
          .toUpperCase()
          .split(',')
          .map((e) => e.replace(/[^A-Z0-9]/g, ''))
          .filter(Boolean)
        if (picked.length) return picked

        const count = Math.min(6, Math.max(1, Math.floor(Number(settings.expiries) || 1)))
        const key = `${exchange}|${underlying}|${count}`
        const fresh = Date.now() - expiryCachedAt < EXPIRY_CACHE_MS
        if (key !== expiryCacheKey || expiryCache.length === 0 || !fresh) {
          expiryCache = await fetchNearestExpiries(exchange, underlying, count)
          expiryCacheKey = key
          expiryCachedAt = Date.now()
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
      const applyChain = (body, valueMode, hasChange) => {
        const chain = Array.isArray(body.oi_chain) ? body.oi_chain : null
        state.chain = chain
        state.valueMode = valueMode
        state.hasChange = hasChange
        state.maxPain = chain ? maxPainStrike(chain) : null
        ctx.requestRecompute()
      }

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
        const exchange = resolveExchange(settings, underlying)
        state.mode = settings.mode === 'oi' ? 'oi' : 'change'
        watchedKey = dataKey(settings, ctx.symbol?.())
        if (!underlying) {
          state.chain = null
          return
        }

        try {
          const expiries = await resolveExpiries(settings, exchange, underlying)
          if (stale()) return
          if (expiries.length === 0) {
            state.chain = null
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
            if (!res.ok || stale()) return null
            const body = await res.json()
            if (stale() || body?.status !== 'success') return null
            return body
          }

          // Open interest comes back in well under a second. The change
          // columns need yesterday's close for every leg, which is one broker
          // history call each on the first request of the session - so draw
          // the fast answer straight away and upgrade it when the slow one
          // lands, rather than showing an empty chart while it runs.
          const oiBody = await request(false)
          if (!oiBody) return
          applyChain(oiBody, 'oi', false)
          state.marketOpen = oiBody.market_open !== false

          // The change columns carry yesterday's open interest too, so the
          // outline needs them even when the bars themselves show OI.
          const wantsChange = state.mode !== 'oi' || settings.outline !== false
          if (!wantsChange) return

          const changeBody = await request(true)
          if (!changeBody) return
          applyChain(changeBody, state.mode === 'oi' ? 'oi' : 'change', true)
          // An underlying nobody has looked at today has no previous-session
          // OI cached for its legs. The backend fetches those in the
          // background rather than holding the request, so the change columns
          // arrive over the next few beats instead of all at once.
          state.changePending = changeBody.oi_change_pending === true
        } catch {
          // A failed poll is not worth tearing the indicator down for.
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
      const watcher = setInterval(() => {
        if (cancelled) return
        const next = dataKey(ctx.settings(), ctx.symbol?.())
        if (next === watchedKey) return
        watchedKey = next
        // A changed instrument invalidates what is on screen; clear it rather
        // than leave the previous underlying's bars up while the new one loads.
        state.chain = null
        state.maxPain = null
        state.changePending = false
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
        document.removeEventListener('visibilitychange', onVisible)
        ctx.removePrimitive(primitive)
      }
    },
  })
}
