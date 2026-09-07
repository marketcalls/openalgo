/**
 * SESSIONS example: an opening range, using what the library now ships.
 *
 * This is the same study as `strategies/indicators/open_range_breakout.js`,
 * rewritten to show what stopped being your job:
 *
 *   parseSessionSpec   parses '0915-1015', and '0930-1600:23456' with a
 *                      weekday filter, and a window that wraps midnight
 *   inSessionAt        membership for one bar, half-open at the end, so a bar
 *                      stamped exactly at the close opens the breakout window
 *                      rather than joining the range
 *   ctx (4th arg)      the chart's timezone, interval and bar state, none of
 *                      which an indicator could see before
 *
 * The older version hand-rolled a regex, a minute-of-day comparison and a
 * midnight wrap, about forty lines, and still did not handle weekday filters.
 * Prefer this shape for anything session-anchored.
 */

const HIGH_COLOR = '#ff5252'
const LOW_COLOR = '#00e676'

export default function ({
  registerIndicator,
  parseSessionSpec,
  inSessionAt,
  isIntradayInterval,
  DEFAULT_TIMEZONE,
}) {
  registerIndicator({
    id: 'ex-session-range',
    name: 'Session Range',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      // A dedicated input type since 1.8.1. The host renders it and hints the
      // shape; the indicator still parses it, which is why the guard below
      // matters.
      { key: 'window', type: 'session', label: 'Range Window', default: '0915-1015' },
      { key: 'showSignals', type: 'boolean', label: 'Show Breakout Labels', default: true },
    ],

    plots: [
      { key: 'rangeHigh', type: 'line', title: 'Range High', style: { color: HIGH_COLOR, lineWidth: 2 } },
      { key: 'rangeLow', type: 'line', title: 'Range Low', style: { color: LOW_COLOR, lineWidth: 2 } },
    ],

    calc(bars, settings, store, ctx) {
      const n = bars.length
      const rangeHigh = new Array(n).fill(null)
      const rangeLow = new Array(n).fill(null)

      const spec = parseSessionSpec(String(settings.window ?? ''))
      // An unparseable window draws nothing rather than throwing: the user is
      // mid-edit in a text box, which is not an error condition.
      if (!spec || n === 0) return { rangeHigh, rangeLow }

      // A session window is meaningless on a daily or weekly chart, where one
      // bar already spans the whole session. Knowing the interval at all is new.
      if (ctx?.interval && !isIntradayInterval(ctx.interval)) return { rangeHigh, rangeLow }

      const zone = ctx?.timezone ?? DEFAULT_TIMEZONE
      let wasIn = false
      let runHigh = Number.NEGATIVE_INFINITY
      let runLow = Number.POSITIVE_INFINITY
      let high = null
      let low = null

      for (let i = 0; i < n; i++) {
        const isIn = inSessionAt(bars[i].time, spec, zone)

        if (isIn && !wasIn) {
          runHigh = Number.NEGATIVE_INFINITY
          runLow = Number.POSITIVE_INFINITY
        }
        if (isIn) {
          if (bars[i].high > runHigh) runHigh = bars[i].high
          if (bars[i].low < runLow) runLow = bars[i].low
        } else if (wasIn && Number.isFinite(runHigh)) {
          // First bar after the window closed: the range is final.
          high = runHigh
          low = runLow
        }

        // Hidden while the range is still forming, so the level starts at the
        // breakout rather than running back through its own session.
        rangeHigh[i] = isIn ? null : high
        rangeLow[i] = isIn ? null : low
        wasIn = isIn
      }
      return { rangeHigh, rangeLow }
    },

    markers({ bars, values, settings }) {
      if (settings.showSignals === false) return []
      const hi = values.rangeHigh
      const lo = values.rangeLow

      // Scale the label gap to the instrument: half a mean bar range reads the
      // same on a 24000 index and a 100 rupee stock.
      let sum = 0
      let count = 0
      for (const b of bars) {
        const r = b.high - b.low
        if (Number.isFinite(r) && r > 0) { sum += r; count++ }
      }
      const pad = Math.max(count ? (sum / count) * 0.5 : 0, Math.abs(bars.at(-1)?.close ?? 0) * 0.0005)

      const out = []
      let long = false
      let short = false
      for (let i = 1; i < bars.length; i++) {
        // Both ends must exist: a not-available value compares false against
        // everything in the language this was ported from, but in JavaScript
        // `5 > null` is true, which would fire through the whole warmup.
        const ph = hi[i - 1]
        const ch = hi[i]
        const pl = lo[i - 1]
        const cl = lo[i]
        const up = ph != null && ch != null && bars[i - 1].high <= ph && bars[i].high > ch
        const down = pl != null && cl != null && bars[i - 1].low >= pl && bars[i].low < cl

        if (up && !long) {
          long = true
          short = false
          out.push({
            time: bars[i].time, position: 'atPrice', price: bars[i].low - pad,
            shape: 'labelUp', size: 'small', color: '#4caf50', text: 'Buy',
          })
        } else if (down && !short) {
          long = false
          short = true
          out.push({
            time: bars[i].time, position: 'atPrice', price: bars[i].high + pad,
            shape: 'labelDown', size: 'small', color: '#ef5350', text: 'Sell',
          })
        }
      }
      return out
    },

    alerts: [
      {
        id: 'range-break-up',
        title: 'Broke above the session range',
        when: ({ bars, values, index: i }) => {
          if (i < 1) return false
          const p = values.rangeHigh[i - 1]
          const c = values.rangeHigh[i]
          return p != null && c != null && bars[i - 1].high <= p && bars[i].high > c
        },
      },
      {
        id: 'range-break-down',
        title: 'Broke below the session range',
        when: ({ bars, values, index: i }) => {
          if (i < 1) return false
          const p = values.rangeLow[i - 1]
          const c = values.rangeLow[i]
          return p != null && c != null && bars[i - 1].low >= p && bars[i].low < c
        },
      },
    ],
  })
}
