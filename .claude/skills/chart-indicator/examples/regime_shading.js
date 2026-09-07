/**
 * REGIME example: shade the pane, repaint the candles, raise an alert.
 *
 * Three capabilities that did not exist before 1.8.1, and the ones a ported
 * study most often needs:
 *
 *   background()  one colour per bar, painted behind the plots
 *   barColors()   one colour per bar, painted onto the MAIN price candles
 *   alerts        a declared condition the chart watches for you
 *
 * The study itself is deliberately plain: price against its own mean, with a
 * band of indecision around it that neither shades nor paints. What matters is
 * the shape of the three hooks, not the signal.
 *
 * All three are indexed by bar and must be exactly `bars.length` long. One
 * short and every colour lands on the wrong bar, which reads as an indicator
 * that is subtly wrong rather than one that is broken.
 */

const UP = '#26a69a'
const DOWN = '#ef5350'
/** The pane wash is the same hue at low alpha, so the candles stay readable. */
const UP_WASH = '#26a69a1f'
const DOWN_WASH = '#ef53501f'

export default function ({ registerIndicator, sourceValues, sma, stdev, nulls, withAlpha }) {
  /**
   * Which regime a bar is in: 1 above, -1 below, 0 inside the deadband.
   *
   * Computed once and read by all three hooks. They each receive the same
   * `values`, so deriving the regime from a plotted column keeps them in step
   * rather than each re-deciding and drifting apart.
   */
  function regimeAt(values, i) {
    const r = values.regime[i]
    return r == null ? null : r
  }

  registerIndicator({
    id: 'ex-regime-shading',
    name: 'Regime Shading',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 400, step: 1 },
      { key: 'deadband', type: 'number', label: 'Deadband (sd)', default: 0.25, min: 0, max: 3, step: 0.05 },
      { key: 'source', type: 'source', label: 'Source', default: 'close' },
      { key: 'shade', type: 'boolean', label: 'Shade Background', default: true },
      { key: 'paint', type: 'boolean', label: 'Paint Candles', default: true },
    ],

    plots: [
      { key: 'mean', type: 'line', title: 'Mean', style: { color: '#8892a6', lineWidth: 1.5 } },
      // The regime column is the shared source of truth for the three hooks.
      // Plotted as a hidden line rather than kept in `store`, because `background`,
      // `barColors` and `alerts` are all handed `values` and none of them is
      // handed `store`.
      { key: 'regime', type: 'line', title: 'Regime', style: { visible: false } },
    ],

    calc(bars, settings) {
      const length = Math.max(2, Math.floor(Number(settings.length) || 20))
      const band = Math.max(0, Number(settings.deadband) || 0)
      const src = sourceValues(bars, settings.source ?? 'close')

      const mean = sma(src, length)
      const sd = stdev(src, length)
      const regime = new Array(bars.length).fill(NaN)

      for (let i = 0; i < bars.length; i++) {
        if (!Number.isFinite(mean[i]) || !Number.isFinite(sd[i])) continue
        const edge = sd[i] * band
        // Inside the deadband the regime is 0, so a series oscillating around
        // its mean does not strobe the whole pane.
        if (src[i] > mean[i] + edge) regime[i] = 1
        else if (src[i] < mean[i] - edge) regime[i] = -1
        else regime[i] = 0
      }
      return { mean: nulls(mean), regime: nulls(regime) }
    },

    background({ bars, values, settings }) {
      if (settings.shade === false) return bars.map(() => null)
      return bars.map((_, i) => {
        const r = regimeAt(values, i)
        // null, not a transparent colour: null skips the band entirely rather
        // than painting an invisible one over every bar.
        if (r === null || r === 0) return null
        return r > 0 ? UP_WASH : DOWN_WASH
      })
    },

    barColors({ bars, values, settings }) {
      if (settings.paint === false) return bars.map(() => null)
      return bars.map((_, i) => {
        const r = regimeAt(values, i)
        // Inside the deadband the candle keeps its own up/down colour, which is
        // what `null` means here.
        if (r === null || r === 0) return null
        return r > 0 ? UP : DOWN
      })
    },

    alerts: [
      {
        id: 'regime-up',
        title: 'Regime turned up',
        message: 'Price crossed above its mean band',
        when: ({ values, index }) => {
          if (index < 1) return false
          const prev = regimeAt(values, index - 1)
          const now = regimeAt(values, index)
          return prev !== null && now === 1 && prev !== 1
        },
      },
      {
        id: 'regime-down',
        title: 'Regime turned down',
        when: ({ values, index }) => {
          if (index < 1) return false
          const prev = regimeAt(values, index - 1)
          const now = regimeAt(values, index)
          return prev !== null && now === -1 && prev !== -1
        },
      },
    ],

    // A level derived from the data rather than from a setting, which is what
    // `levels(ctx)` made possible: the mean as it stands on the last bar.
    levels(ctx) {
      const values = ctx.values
      const bars = ctx.bars ?? []
      if (!values || bars.length === 0) return []
      const last = values.mean[bars.length - 1]
      if (last == null) return []
      return [{ price: last, title: 'mean', color: withAlpha('#8892a6', 0.9), lineStyle: 'dotted' }]
    },
  })
}
