/**
 * TIER-2 example: an indicator whose data is not on the chart.
 *
 * Every other example is a pure function of the bars. This one plots something
 * the chart has never seen: open interest, a put-call ratio, a sentiment score,
 * anything your own API can answer. `calc` is synchronous and pure, so it cannot
 * fetch. Two shapes solve that.
 *
 * SHAPE 1, `createTier2Indicator`, is the one to reach for. You supply `fetch`
 * and it hands back an ordinary descriptor, so panes, settings, levels and
 * removal all behave identically. The alignment rule is the part worth knowing:
 * each bar takes the most recent external point at or before its own time.
 * Never interpolated, never forward-looking, and bars before the first point
 * are null. That is what stops an hourly series from quietly leaking a value
 * backwards into minutes it could not have known.
 *
 * SHAPE 2, `attach`, is the manual version, shown at the bottom. Use it when the
 * data streams rather than arrives once, or when you need the teardown for
 * something else. The rule there is that `attach` returns its own cleanup, and
 * everything it started must stop in it: a symbol change tears the instance down
 * and a leaked socket or timer outlives it.
 */

export default function ({ registerIndicator, createTier2Indicator }) {
  /* ── Shape 1: fetch once per window ──────────────────────────────────── */

  registerIndicator(
    createTier2Indicator({
      id: 'ex-external-oi',
      name: 'Open Interest (external)',
      category: 'Custom',
      placement: 'pane',

      inputs: [
        { key: 'symbol', type: 'symbol', label: 'Symbol', default: '' },
        { key: 'endpoint', type: 'text', label: 'Endpoint', default: '/api/v1/oi' },
      ],

      plots: [{ key: 'oi', type: 'line', title: 'OI', style: { color: '#ffa726', lineWidth: 2 } }],

      // Changing either of these invalidates the fetched series. Anything not
      // listed only re-runs the alignment, which is cheap.
      refetchOn: ['symbol', 'endpoint'],

      async fetch({ settings, from, to }) {
        const symbol = String(settings.symbol ?? '').trim()
        // No symbol is a normal state while the user is still typing, not an
        // error. Returning nothing draws nothing.
        if (!symbol) return []

        const url = `${settings.endpoint}?symbol=${encodeURIComponent(symbol)}&from=${from}&to=${to}`
        const res = await fetch(url, { credentials: 'same-origin' })
        if (!res.ok) return []
        const rows = await res.json()
        if (!Array.isArray(rows)) return []

        // One point per observation: a UTC-seconds time, and a value per plot
        // key. Times need not line up with bars; the runtime aligns them.
        return rows
          .filter((r) => Number.isFinite(r?.time) && Number.isFinite(r?.oi))
          .map((r) => ({ time: r.time, values: { oi: r.oi } }))
      },
    })
  )

  /* ── Shape 2: the manual lifecycle ───────────────────────────────────── */

  registerIndicator({
    id: 'ex-external-manual',
    name: 'External (manual attach)',
    category: 'Custom',
    placement: 'pane',
    inputs: [{ key: 'symbol', type: 'symbol', label: 'Symbol', default: '' }],
    plots: [{ key: 'v', type: 'line', title: 'Value' }],

    /**
     * Runs once per instance. Fetch into `store`, then ask for a recompute:
     * `calc` runs again and reads what you put there.
     */
    attach(ctx) {
      let cancelled = false
      const timer = setInterval(() => {
        if (cancelled) return
        const symbol = String(ctx.settings().symbol ?? '').trim()
        if (!symbol) return
        fetch(`/api/v1/quotes?symbol=${encodeURIComponent(symbol)}`, { credentials: 'same-origin' })
          .then((r) => (r.ok ? r.json() : null))
          .then((body) => {
            if (cancelled || !body) return
            // Keyed by bar time so `calc` can look each one up.
            const store = ctx.store
            store.points = store.points ?? new Map()
            store.points.set(ctx.now(), Number(body.ltp))
            ctx.requestRecompute()
          })
          .catch(() => {
            // A failed poll is not worth tearing the indicator down for.
          })
      }, 5000)

      // Everything started above stops here. Without this the timer survives a
      // symbol change and keeps polling for an indicator nobody can see.
      return () => {
        cancelled = true
        clearInterval(timer)
      }
    },

    calc(bars, settings, store) {
      const points = store.points
      const v = new Array(bars.length).fill(null)
      if (!points || points.size === 0) return { v }

      // Last known value at or before each bar: the same rule Tier 2 applies
      // for you, written out.
      const times = [...points.keys()].sort((a, b) => a - b)
      let k = 0
      let last = null
      for (let i = 0; i < bars.length; i++) {
        while (k < times.length && times[k] <= bars[i].time) last = points.get(times[k++])
        v[i] = last
      }
      return { v }
    },
  })
}
