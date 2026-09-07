/**
 * COMPLEX example: Session VWAP with deviation bands and cross signals.
 *
 * Everything the descriptor contract offers, in one indicator:
 *
 *   - per-session state that resets on a calendar boundary, using the zone
 *     helpers rather than the browser's local time
 *   - a text input parsed defensively, and a select input
 *   - bands built from a running variance, not a second pass
 *   - `markers` anchored with `atPrice` so labels sit off the candle
 *   - a signal latch so the same side does not fire twice in a row
 *   - `table` for a per-session summary the plots cannot express
 *   - `calcTail` for the live path, kept consistent with `calc`
 *
 * VWAP resets each session. The bands are standard deviations of price around
 * that running VWAP, so they widen with dispersion rather than with time.
 */

const BUY_COLOR = '#4caf50'
const SELL_COLOR = '#ef5350'

export default function ({
  registerIndicator,
  sourceValues,
  zonedDayIndex,
  isValidTimezone,
  DEFAULT_TIMEZONE,
}) {
  /** The zone the session boundary is read in. Bar times are UTC seconds. */
  function zoneOf(settings) {
    const raw = typeof settings.timezone === 'string' ? settings.timezone.trim() : ''
    return raw && isValidTimezone(raw) ? raw : DEFAULT_TIMEZONE
  }

  /**
   * The whole computation in one pass.
   *
   * Kept as a standalone function because `calc`, `markers` and `calcTail` all
   * need it and none of them can see the others' work.
   */
  function compute(bars, settings) {
    const zone = zoneOf(settings)
    const mult = Number(settings.bandMult) || 2
    const src = sourceValues(bars, settings.source ?? 'hlc3')
    const n = bars.length

    const vwap = new Array(n).fill(null)
    const upper = new Array(n).fill(null)
    const lower = new Array(n).fill(null)
    const sessionBar = new Array(n).fill(0)

    let day = null
    let sumPV = 0
    let sumV = 0
    let sumP2V = 0
    let barsThisSession = 0

    for (let i = 0; i < n; i++) {
      const d = zonedDayIndex(bars[i].time, zone)
      if (d !== day) {
        day = d
        sumPV = 0
        sumV = 0
        sumP2V = 0
        barsThisSession = 0
      }
      barsThisSession++
      sessionBar[i] = barsThisSession

      // Volume can be absent on index series. Falling back to 1 makes this a
      // plain average rather than dividing by zero and blanking the plot.
      const v = Number.isFinite(bars[i].volume) && bars[i].volume > 0 ? bars[i].volume : 1
      const p = src[i]
      if (!Number.isFinite(p)) continue

      sumPV += p * v
      sumV += v
      sumP2V += p * p * v

      const mean = sumPV / sumV
      vwap[i] = mean
      // Variance of a weighted mean, accumulated rather than re-walked. Clamp at
      // zero: floating point can drift a hair negative on a flat session.
      const variance = Math.max(sumP2V / sumV - mean * mean, 0)
      const sd = Math.sqrt(variance)
      upper[i] = mean + mult * sd
      lower[i] = mean - mult * sd
    }

    return { vwap, upper, lower, sessionBar }
  }

  /** Crosses of price through VWAP, one signal per side until the other fires. */
  function signals(bars, values, settings) {
    if (settings.showSignals === false) return []
    const vwap = values.vwap ?? []
    const out = []
    let isLong = false
    let isShort = false

    for (let i = 1; i < bars.length; i++) {
      const prev = vwap[i - 1]
      const cur = vwap[i]
      // Both ends must exist. In JavaScript `5 > null` is true, so an unguarded
      // comparison fires signals through the warmup gap.
      if (prev == null || cur == null) continue

      const crossUp = bars[i - 1].close <= prev && bars[i].close > cur
      const crossDown = bars[i - 1].close >= prev && bars[i].close < cur

      if (crossUp && !isLong) {
        isLong = true
        isShort = false
        out.push({ index: i, side: 'buy' })
      } else if (crossDown && !isShort) {
        isLong = false
        isShort = true
        out.push({ index: i, side: 'sell' })
      }
    }
    return out
  }

  /**
   * Label offset in price. `aboveBar` / `belowBar` anchor to this indicator's
   * own plot line, not to the candle, so a label placed relative to a bar has to
   * use `atPrice` and bring its own gap.
   */
  function markerPad(bars) {
    let sum = 0
    let count = 0
    for (const bar of bars) {
      const range = bar.high - bar.low
      if (Number.isFinite(range) && range > 0) {
        sum += range
        count++
      }
    }
    const mean = count > 0 ? sum / count : 0
    const last = bars.length > 0 ? Math.abs(bars[bars.length - 1].close) : 0
    return Math.max(mean * 0.5, last * 0.0005)
  }

  registerIndicator({
    id: 'ex-session-vwap',
    name: 'Session VWAP Bands',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'source', type: 'source', label: 'Source', default: 'hlc3' },
      { key: 'bandMult', type: 'number', label: 'Band Multiplier', default: 2, min: 0.5, max: 5, step: 0.1 },
      { key: 'timezone', type: 'text', label: 'Session Timezone', default: DEFAULT_TIMEZONE },
      { key: 'showSignals', type: 'boolean', label: 'Show Cross Signals', default: true },
      { key: 'showTable', type: 'boolean', label: 'Show Session Summary', default: true },
      {
        key: 'bandStyle',
        type: 'select',
        label: 'Bands',
        default: 'both',
        options: [
          { label: 'Both', value: 'both' },
          { label: 'Upper only', value: 'upper' },
          { label: 'Hidden', value: 'none' },
        ],
      },
    ],

    plots: [
      { key: 'vwap', type: 'line', title: 'VWAP', style: { color: '#ffa726', lineWidth: 2 } },
      { key: 'upper', type: 'line', title: 'Upper', style: { color: '#4f8cff', lineWidth: 1, lineStyle: 'dashed' } },
      { key: 'lower', type: 'line', title: 'Lower', style: { color: '#4f8cff', lineWidth: 1, lineStyle: 'dashed' } },
    ],

    fills: [{ between: ['upper', 'lower'], colorUp: '#4f8cff', colorDown: '#4f8cff', opacity: 0.06 }],

    calc(bars, settings) {
      const { vwap, upper, lower } = compute(bars, settings)
      const style = settings.bandStyle ?? 'both'
      const blank = new Array(bars.length).fill(null)
      return {
        vwap,
        upper: style === 'none' ? blank : upper,
        lower: style === 'both' ? lower : blank,
      }
    },

    markers({ bars, values, settings }) {
      const pad = markerPad(bars)
      return signals(bars, values, settings).map((sig) => {
        const bar = bars[sig.index]
        return sig.side === 'buy'
          ? {
              time: bar.time,
              position: 'atPrice',
              price: bar.low - pad,
              shape: 'labelUp',
              size: 'small',
              color: BUY_COLOR,
              text: 'Buy',
            }
          : {
              time: bar.time,
              position: 'atPrice',
              price: bar.high + pad,
              shape: 'labelDown',
              size: 'small',
              color: SELL_COLOR,
              text: 'Sell',
            }
      })
    },

    /**
     * A per-session scoreboard. This is not a value per bar, so it has no place
     * in `calc`, whose contract is one column per plot aligned to the bars.
     */
    table({ bars, values, settings }) {
      if (settings.showTable === false || bars.length === 0) return null
      const last = bars.length - 1
      const vwap = values.vwap?.[last]
      if (vwap == null) return null

      const close = bars[last].close
      const diff = close - vwap
      const pct = vwap !== 0 ? (diff / vwap) * 100 : 0
      return {
        rows: [
          ['VWAP', vwap.toFixed(2)],
          ['Close', close.toFixed(2)],
          ['Diff', `${diff >= 0 ? '+' : ''}${diff.toFixed(2)} (${pct.toFixed(2)}%)`],
          ['Side', diff >= 0 ? 'Above' : 'Below'],
        ],
      }
    },

    /**
     * Live path. The runtime calls this when only the tail changed, for indices
     * [fromIndex, bars.length). Recomputing the whole series and slicing keeps it
     * exactly consistent with `calc`, which is the property that matters: a
     * calcTail that drifts makes the live chart disagree with a reload.
     *
     * For a session-anchored accumulator this is honest rather than lazy. The
     * running sums cannot be resumed from the previous output, and `markers`
     * re-runs in full after every recompute anyway.
     */
    calcTail(bars, settings, fromIndex) {
      const full = this.calc(bars, settings)
      const out = {}
      for (const key of Object.keys(full)) out[key] = full[key].slice(fromIndex)
      return out
    },
  })
}
