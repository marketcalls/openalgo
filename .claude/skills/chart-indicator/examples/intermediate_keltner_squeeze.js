/**
 * INTERMEDIATE example: Keltner Squeeze.
 *
 * Adds everything a multi-plot overlay needs: several plots on one descriptor,
 * a shaded band between two of them (`fills`), a per-bar colour on a histogram
 * (`colorBy`), a boolean input that switches part of the drawing off, and a
 * second price scale so the squeeze histogram does not fight the price axis.
 *
 * Bollinger Bands inside Keltner Channels means volatility has compressed and a
 * range is coiling. The histogram is the width of the Bollinger band relative to
 * the Keltner channel: below 1 the bands are inside the channel, which is the
 * squeeze.
 */

export default function ({ registerIndicator, sourceValues, sma, stdev, atr, nulls }) {
  registerIndicator({
    id: 'ex-keltner-squeeze',
    name: 'Keltner Squeeze',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 200, step: 1 },
      { key: 'bbMult', type: 'number', label: 'Bollinger Mult', default: 2, min: 0.5, max: 5, step: 0.1 },
      { key: 'kcMult', type: 'number', label: 'Keltner Mult', default: 1.5, min: 0.5, max: 5, step: 0.1 },
      { key: 'source', type: 'source', label: 'Source', default: 'close' },
      { key: 'showSqueeze', type: 'boolean', label: 'Show Squeeze Histogram', default: true },
    ],

    plots: [
      { key: 'basis', type: 'line', title: 'Basis', style: { color: '#8892a6', lineWidth: 1 } },
      { key: 'bbUpper', type: 'line', title: 'BB Upper', style: { color: '#4f8cff', lineWidth: 1.5 } },
      { key: 'bbLower', type: 'line', title: 'BB Lower', style: { color: '#4f8cff', lineWidth: 1.5 } },
      { key: 'kcUpper', type: 'line', title: 'KC Upper', style: { color: '#ffa726', lineWidth: 1, lineStyle: 'dashed' } },
      { key: 'kcLower', type: 'line', title: 'KC Lower', style: { color: '#ffa726', lineWidth: 1, lineStyle: 'dashed' } },
      {
        key: 'squeeze',
        type: 'histogram',
        title: 'Squeeze',
        // Its own axis: a ratio near 1 has nothing to do with the price range,
        // and sharing the right scale would flatten the price series.
        priceScaleId: 'squeeze',
        style: { color: '#26a69a', base: 0 },
        // Red while the bands sit inside the channel, which is the signal.
        colorBy: ({ value }) => (value < 1 ? '#ef5350' : '#26a69a'),
      },
    ],

    // The band between the two Bollinger lines. A pair of lines and a filled
    // region are not the same picture: the fill is what makes the compression
    // readable at a glance.
    fills: [{ between: ['bbUpper', 'bbLower'], colorUp: '#4f8cff', colorDown: '#4f8cff', opacity: 0.08 }],

    calc(bars, settings) {
      const length = Math.max(2, Math.floor(Number(settings.length) || 20))
      const bbMult = Number(settings.bbMult) || 2
      const kcMult = Number(settings.kcMult) || 1.5
      const src = sourceValues(bars, settings.source ?? 'close')

      const basis = sma(src, length)
      const dev = stdev(src, length)
      // `atr` and `trueRange` take three separate price arrays, NOT a bars
      // array. Passing bars is the single easiest mistake to make here.
      const range = atr(
        bars.map((b) => b.high),
        bars.map((b) => b.low),
        bars.map((b) => b.close),
        length
      )

      const n = bars.length
      const bbUpper = new Array(n).fill(NaN)
      const bbLower = new Array(n).fill(NaN)
      const kcUpper = new Array(n).fill(NaN)
      const kcLower = new Array(n).fill(NaN)
      const squeeze = new Array(n).fill(NaN)

      for (let i = 0; i < n; i++) {
        if (!Number.isFinite(basis[i])) continue
        if (Number.isFinite(dev[i])) {
          bbUpper[i] = basis[i] + bbMult * dev[i]
          bbLower[i] = basis[i] - bbMult * dev[i]
        }
        if (Number.isFinite(range[i])) {
          kcUpper[i] = basis[i] + kcMult * range[i]
          kcLower[i] = basis[i] - kcMult * range[i]
        }
        // Guard the divide: a flat series gives a zero-width channel.
        const kcWidth = kcUpper[i] - kcLower[i]
        if (settings.showSqueeze !== false && Number.isFinite(kcWidth) && kcWidth > 0) {
          squeeze[i] = (bbUpper[i] - bbLower[i]) / kcWidth
        }
      }

      return {
        basis: nulls(basis),
        bbUpper: nulls(bbUpper),
        bbLower: nulls(bbLower),
        kcUpper: nulls(kcUpper),
        kcLower: nulls(kcLower),
        squeeze: nulls(squeeze),
      }
    },
  })
}
