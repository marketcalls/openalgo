/**
 * SIMPLE example: EMA cross signals with a trend filter.
 *
 * Shows the crossing and slope helpers (2.5.4), which read a missing value as
 * no signal, so the warmup of either average can never produce a false cross
 * (pitfall 4 done for you):
 *   - `crossesAbove` and `crossesBelow` for the two directions
 *   - `rising` and `falling` for the trend filter on the slow average
 *   - `crosses` for a cross in either direction that the filter set aside
 *
 * A Buy is the fast EMA crossing above the slow one while the slow one is
 * rising; a Sell is the mirror. A cross against the trend is marked with a
 * small dot, so the filter's effect stays visible.
 */

const BUY_COLOR = '#4caf50'
const SELL_COLOR = '#ef5350'
const SKIP_COLOR = '#8892a6'

export default function ({
  registerIndicator,
  sourceValues,
  ema,
  nulls,
  crossesAbove,
  crossesBelow,
  crosses,
  rising,
  falling,
}) {
  function lengths(settings) {
    const fast = Math.max(1, Math.floor(Number(settings.fast) || 9))
    const slow = Math.max(fast + 1, Math.floor(Number(settings.slow) || 21))
    const slope = Math.max(1, Math.floor(Number(settings.slope) || 3))
    return { fast, slow, slope }
  }

  registerIndicator({
    id: 'ex-ema-cross',
    name: 'EMA Cross Signals',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'fast', type: 'number', label: 'Fast length', default: 9, min: 1, max: 200, step: 1 },
      { key: 'slow', type: 'number', label: 'Slow length', default: 21, min: 2, max: 400, step: 1 },
      { key: 'slope', type: 'number', label: 'Trend bars', default: 3, min: 1, max: 50, step: 1 },
      { key: 'source', type: 'source', label: 'Source', default: 'close' },
    ],

    plots: [
      { key: 'fast', type: 'line', title: 'Fast', style: { color: '#4f8cff', lineWidth: 2 } },
      { key: 'slow', type: 'line', title: 'Slow', style: { color: '#ff9800', lineWidth: 2 } },
    ],

    calc(bars, settings) {
      const { fast, slow } = lengths(settings)
      const src = sourceValues(bars, settings.source ?? 'close')
      return { fast: nulls(ema(src, fast)), slow: nulls(ema(src, slow)) }
    },

    markers({ bars, values, settings }) {
      const { slope } = lengths(settings)
      // A plot column holds null in warmup; the helpers want numbers and read
      // NaN as missing.
      const fast = values.fast.map((v) => (v == null ? NaN : v))
      const slow = values.slow.map((v) => (v == null ? NaN : v))
      const up = crossesAbove(fast, slow)
      const down = crossesBelow(fast, slow)
      const any = crosses(fast, slow)
      const trendUp = rising(slow, slope)
      const trendDown = falling(slow, slope)

      const out = []
      for (let i = 0; i < bars.length; i++) {
        if (!any[i]) continue
        const bar = bars[i]
        const pad = (bar.high - bar.low) * 0.5 || bar.close * 0.001
        if (up[i] && trendUp[i]) {
          out.push({ time: bar.time, position: 'atPrice', price: bar.low - pad, shape: 'labelUp', size: 'small', color: BUY_COLOR, text: 'Buy' })
        } else if (down[i] && trendDown[i]) {
          out.push({ time: bar.time, position: 'atPrice', price: bar.high + pad, shape: 'labelDown', size: 'small', color: SELL_COLOR, text: 'Sell' })
        } else {
          out.push({ time: bar.time, position: 'atPrice', price: bar.close, shape: 'circle', size: 'tiny', color: SKIP_COLOR })
        }
      }
      return out
    },
  })
}
