/**
 * SIMPLE example: Price Z-Score.
 *
 * One pane, one plot, one rolling window. Shows the minimum shape of a working
 * indicator: inputs, a plot, a calc that fills every bar, plus `levels` and
 * `range` to make the pane readable.
 *
 * How many standard deviations the source sits from its own rolling mean. Above
 * +2 is stretched, below -2 is stretched the other way.
 */

export default function ({ registerIndicator, sourceValues, sma, stdev, nulls }) {
  registerIndicator({
    id: 'ex-zscore',
    name: 'Z-Score',
    category: 'Custom',
    placement: 'pane',

    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 500, step: 1 },
      { key: 'source', type: 'source', label: 'Source', default: 'close' },
    ],

    plots: [{ key: 'z', type: 'line', title: 'Z', style: { color: '#4f8cff', lineWidth: 2 } }],

    // Reference lines and a fixed pane range, so the scale does not rescale
    // itself every time the series drifts.
    levels: () => [
      { price: 2, title: '+2', color: '#ef5350' },
      { price: 0, title: '0', color: '#8892a6' },
      { price: -2, title: '-2', color: '#26a69a' },
    ],
    range: () => ({ min: -4, max: 4 }),

    calc(bars, settings) {
      // Always coerce: a cleared number field arrives as '' and Number('') is 0,
      // which would make the window length zero.
      const length = Math.max(2, Math.floor(Number(settings.length) || 20))
      const src = sourceValues(bars, settings.source ?? 'close')

      // The shipped helpers return NaN during warmup; `nulls` converts that to
      // the explicit gaps a plot column wants.
      const mean = sma(src, length)
      const sd = stdev(src, length)

      const z = new Array(bars.length).fill(NaN)
      for (let i = 0; i < bars.length; i++) {
        if (!Number.isFinite(mean[i]) || !Number.isFinite(sd[i]) || sd[i] === 0) continue
        z[i] = (src[i] - mean[i]) / sd[i]
      }
      return { z: nulls(z) }
    },
  })
}
