/**
 * OHLC PLOT example: Heikin Ashi drawn as candles by an indicator.
 *
 * Every other example returns one number per bar per plot. A candle needs four,
 * so a plot may instead name four columns:
 *
 *   plots: [{ key: 'ha', type: 'candlestick', ohlc: { open, high, low, close } }]
 *
 * The plot `key` is only a label for the legend. The four names inside `ohlc`
 * are what `calc` must actually return, and all four must be `bars.length` long.
 * A missing or short column throws out of `addIndicator` rather than drawing
 * nothing, which is the one place the runtime is deliberately loud.
 *
 * Heikin Ashi is the natural first case: it is a smoothing of the candles
 * themselves, so anything less than a candle loses the point.
 */

export default function ({ registerIndicator }) {
  registerIndicator({
    id: 'ex-heikin-ashi',
    name: 'Heikin Ashi',
    category: 'Custom',
    // 'onchart' puts it over the real candles. Set the price series to a line,
    // or hide it, unless you want both.
    placement: 'onchart',

    inputs: [
      { key: 'smooth', type: 'number', label: 'Pre-smooth', default: 1, min: 1, max: 50, step: 1 },
    ],

    plots: [
      {
        key: 'ha',
        type: 'candlestick',
        title: 'Heikin Ashi',
        ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' },
        style: { upColor: '#26a69a', downColor: '#ef5350', borderVisible: false },
      },
    ],

    calc(bars) {
      const n = bars.length
      const o = new Array(n).fill(null)
      const h = new Array(n).fill(null)
      const l = new Array(n).fill(null)
      const c = new Array(n).fill(null)
      if (n === 0) return { o, h, l, c }

      // haClose is the bar's own average; haOpen is the running midpoint of the
      // previous synthetic candle, which is what does the smoothing. The first
      // bar has no previous, so it seeds from the real open and close.
      let prevOpen = (bars[0].open + bars[0].close) / 2
      let prevClose = (bars[0].open + bars[0].high + bars[0].low + bars[0].close) / 4

      for (let i = 0; i < n; i++) {
        const b = bars[i]
        const close = (b.open + b.high + b.low + b.close) / 4
        const open = i === 0 ? prevOpen : (prevOpen + prevClose) / 2
        // The synthetic extremes must contain the synthetic body, or the wick
        // ends up inside the candle it is supposed to bound.
        o[i] = open
        c[i] = close
        h[i] = Math.max(b.high, open, close)
        l[i] = Math.min(b.low, open, close)
        prevOpen = open
        prevClose = close
      }
      return { o, h, l, c }
    },
  })
}
