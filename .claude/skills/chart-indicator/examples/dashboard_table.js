/**
 * 4x5 Indicator Table with Color-Coded Trend.
 *
 * A dashboard rather than a study: ten readings in a grid pinned to a corner,
 * with the last two cells interpreting the moving averages and MACD as a trend
 * and colouring themselves accordingly.
 *
 * Notes on the translation:
 *
 * 1. `table.new(pos, 4, 5)` plus a wall of `table.cell` calls becomes a single
 *    `table(ctx)` returning a grid. It is already only evaluated for the drawn
 *    state, so the `barstate.islast` guard has nothing to do here.
 * 2. A descriptor needs at least one plot, and this study plots nothing. It
 *    carries one hidden all-null column, the same shape the built-in
 *    seasonality study uses for exactly this reason.
 * 3. Nothing here reimplements MACD, Bollinger, RSI, ATR or OBV. A built-in is
 *    a descriptor, and a descriptor has a `calc`, so `getIndicator('macd')
 *    .calc(bars, settings, {})` returns the same columns the built-in plots.
 *    Reusing them means this table cannot drift from the MACD a user also has
 *    on the chart, and it is far less code than porting each formula.
 * 4. Volume and OBV are formatted with `compactVolume`, so a cell reads 39.20K
 *    rather than 39204. The original prints the raw number, which does not fit
 *    a table cell on a liquid symbol.
 */

const HEADER_BG = '#1f3a8a'
const UP = '#26a69a'
const DOWN = '#ef5350'
const FLAT = '#b8a300'
const STRONG_UP = '#00e676'
const WEAK_DOWN = '#8e2b52'

export default function ({
  registerIndicator,
  getIndicator,
  indicatorDefaults,
  sourceValues,
  sma,
  nulls,
  compactVolume,
  withAlpha,
}) {
  /**
   * Run a built-in and hand back its columns.
   *
   * The 91 built-ins are descriptors, and a descriptor is data plus a `calc`,
   * so any of them doubles as a calculation. `indicatorDefaults` fills in every
   * key the descriptor declares, and `overrides` changes only the periods this
   * table exposes, which keeps working if the built-in gains a setting later.
   */
  function runBuiltin(id, bars, overrides = {}) {
    const d = getIndicator(id)
    return d.calc(bars, { ...indicatorDefaults(d), ...overrides }, {})
  }

  const num = (v, dp = 2) => (v == null || !Number.isFinite(v) ? '-' : v.toFixed(dp))

  /**
   * Volume of the most recent bar that actually traded.
   *
   * The last bar is often one the live feed has just opened, so its volume is
   * still 0. Reporting that is technically true and useless: the cell reads
   * "Volume: 0" on a symbol visibly trading. Walking back to the last bar with
   * volume answers the question the cell is actually asking.
   */
  function lastVolume(bars) {
    for (let i = bars.length - 1; i >= 0 && i > bars.length - 5; i--) {
      const v = bars[i].volume
      if (Number.isFinite(v) && v > 0) return v
    }
    return bars.length ? (bars[bars.length - 1].volume ?? null) : null
  }

  registerIndicator({
    id: 'oa-indicator-table',
    name: '4x5 Indicator Table',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'showTable', type: 'boolean', label: 'Show Table', default: true, group: 'Table' },
      {
        key: 'position', type: 'select', label: 'Position', default: 'top-right', group: 'Table',
        options: [
          { label: 'Top Right', value: 'top-right' },
          { label: 'Top Left', value: 'top-left' },
          { label: 'Bottom Right', value: 'bottom-right' },
          { label: 'Bottom Left', value: 'bottom-left' },
        ],
      },
      { key: 'borderColor', type: 'color', label: 'Border', default: '#5a6b8c', group: 'Table' },
      { key: 'textColor', type: 'color', label: 'Text', default: '#e6e9ef', group: 'Table' },
      { key: 'fontSize', type: 'number', label: 'Font Size', default: 11, min: 8, max: 20, step: 1, group: 'Table' },

      { key: 'smaFast', type: 'number', label: 'SMA Fast', default: 20, min: 1, max: 500, step: 1, group: 'Periods' },
      { key: 'smaSlow', type: 'number', label: 'SMA Slow', default: 50, min: 1, max: 500, step: 1, group: 'Periods' },
      { key: 'emaFast', type: 'number', label: 'EMA Fast', default: 20, min: 1, max: 500, step: 1, group: 'Periods' },
      { key: 'emaSlow', type: 'number', label: 'EMA Slow', default: 50, min: 1, max: 500, step: 1, group: 'Periods' },
      { key: 'rsiLen', type: 'number', label: 'RSI Length', default: 14, min: 2, max: 200, step: 1, group: 'Periods' },
      { key: 'macdFast', type: 'number', label: 'MACD Fast', default: 12, min: 1, max: 200, step: 1, group: 'Periods' },
      { key: 'macdSlow', type: 'number', label: 'MACD Slow', default: 26, min: 1, max: 400, step: 1, group: 'Periods' },
      { key: 'macdSignal', type: 'number', label: 'MACD Signal', default: 9, min: 1, max: 200, step: 1, group: 'Periods' },
      { key: 'atrLen', type: 'number', label: 'ATR Length', default: 14, min: 1, max: 200, step: 1, group: 'Periods' },
      { key: 'bbLen', type: 'number', label: 'Bollinger Length', default: 20, min: 2, max: 400, step: 1, group: 'Periods' },
      { key: 'bbMult', type: 'number', label: 'Bollinger Mult', default: 2, min: 0.1, max: 10, step: 0.1, group: 'Periods' },
    ],

    // Nothing is drawn on the price pane: every reading lives in the table. A
    // descriptor still needs a plot, so this one carries a hidden empty column.
    plots: [{ key: 'none', type: 'line', title: '', style: { visible: false } }],

    calc(bars, settings) {
      const n = bars.length
      const int = (k, d) => Math.max(1, Math.floor(Number(settings[k]) || d))
      const close = sourceValues(bars, 'close')

      // Five built-ins, run as calculations. Nothing below reimplements a
      // formula the library already ships and tests.
      const macd = runBuiltin('macd', bars, {
        fastPeriod: int('macdFast', 12),
        slowPeriod: int('macdSlow', 26),
        signalPeriod: int('macdSignal', 9),
      })
      const bb = runBuiltin('bollinger', bars, {
        length: int('bbLen', 20),
        stdDev: Number(settings.bbMult) || 2,
      })
      const rsiOut = runBuiltin('rsi', bars, { length: int('rsiLen', 14) })
      const atrOut = runBuiltin('atr', bars, { period: int('atrLen', 14) })
      const obvOut = runBuiltin('obv', bars)

      // The moving averages are a one-line rolling mean either way, so they
      // stay local rather than paying four descriptor round trips.
      return {
        none: new Array(n).fill(null),
        smaFast: nulls(sma(close, int('smaFast', 20))),
        smaSlow: nulls(sma(close, int('smaSlow', 50))),
        // Every moving-average built-in plots under the key 'ma', not under its
        // own name. Reading `.ema` yields undefined, and a missing column draws
        // nothing at all: check `getIndicator(id).plots` before assuming a key.
        emaFast: runBuiltin('ema', bars, { length: int('emaFast', 20) }).ma,
        emaSlow: runBuiltin('ema', bars, { length: int('emaSlow', 50) }).ma,
        rsi: rsiOut.rsi,
        macd: macd.macd,
        signal: macd.signal,
        hist: macd.histogram,
        atr: atrOut.atr,
        bbUpper: bb.upper,
        bbMiddle: bb.basis,
        bbLower: bb.lower,
        obv: obvOut.obv,
      }
    },

    table({ bars, values, settings }) {
      if (settings.showTable === false || bars.length === 0) return null
      const i = bars.length - 1
      const at = (k) => values[k]?.[i] ?? null
      const text = String(settings.textColor ?? '#e6e9ef')

      const close = bars[i].close
      const smaFast = at('smaFast')
      const smaSlow = at('smaSlow')
      const macd = at('macd')
      const signal = at('signal')

      // The two interpreted cells. Both fall back to a neutral read while their
      // inputs are still warming up, rather than claiming a trend from nulls.
      const maTrend = (() => {
        if (smaFast == null || smaSlow == null) return ['MA Trend: -', '#5a6b8c']
        if (close > smaSlow && smaFast > smaSlow) return ['MA Trend: Uptrend', UP]
        if (close < smaSlow && smaFast < smaSlow) return ['MA Trend: Downtrend', DOWN]
        return ['MA Trend: Sideways', FLAT]
      })()

      const macdTrend = (() => {
        if (macd == null || signal == null) return ['MACD Trend: -', '#5a6b8c']
        if (macd > signal && macd > 0) return ['MACD Trend: Strong Uptrend', STRONG_UP]
        if (macd > signal && macd < 0) return ['MACD Trend: Weak Uptrend', UP]
        if (macd < signal && macd < 0) return ['MACD Trend: Strong Downtrend', DOWN]
        return ['MACD Trend: Weak Downtrend', WEAK_DOWN]
      })()

      const head = (t) => ({ text: t, bgColor: withAlpha(HEADER_BG, 0.55), textColor: text, bold: true, align: 'center' })
      const cell = (t) => ({ text: t, textColor: text, align: 'left' })
      const verdict = ([t, colour]) => ({ text: t, bgColor: withAlpha(colour, 0.35), textColor: text, align: 'left' })

      return {
        rows: [
          [head('Moving Averages'), head('Oscillators'), head('Volatility'), head('Volume & Trend')],
          [cell(`SMA${settings.smaFast}: ${num(at('smaFast'))}`), cell(`RSI: ${num(at('rsi'))}`),
           cell(`ATR: ${num(at('atr'))}`), cell(`Volume: ${lastVolume(bars) == null ? '-' : compactVolume(lastVolume(bars))}`)],
          [cell(`SMA${settings.smaSlow}: ${num(at('smaSlow'))}`), cell(`MACD: ${num(macd)}`),
           cell(`BB Upper: ${num(at('bbUpper'))}`), cell(`OBV: ${at('obv') == null ? '-' : compactVolume(at('obv'))}`)],
          [cell(`EMA${settings.emaFast}: ${num(at('emaFast'))}`), cell(`Signal: ${num(signal)}`),
           cell(`BB Middle: ${num(at('bbMiddle'))}`), verdict(maTrend)],
          [cell(`EMA${settings.emaSlow}: ${num(at('emaSlow'))}`), cell(`MACD Hist: ${num(at('hist'))}`),
           cell(`BB Lower: ${num(at('bbLower'))}`), verdict(macdTrend)],
        ],
        options: {
          position: String(settings.position ?? 'top-right'),
          fontSize: Math.max(8, Math.floor(Number(settings.fontSize) || 11)),
          borderColor: String(settings.borderColor ?? '#5a6b8c'),
          borderWidth: 1,
          cellWidth: [150, 150, 150, 175],
          cellHeight: 22,
        },
      }
    },
  })
}
