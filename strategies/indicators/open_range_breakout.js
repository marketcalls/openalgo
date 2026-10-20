/**
 * Open Range Breakout.
 *
 * The opening range is the high and low of a fixed early window. Once the window
 * closes, both levels are frozen for the rest of the day and traded as breakout
 * triggers: a Buy when a bar's high crosses above the range high, a Sell when a
 * bar's low crosses under the range low, one signal per side until the opposite
 * one fires.
 *
 * Ported from a widely published study of the same name, with two deliberate
 * departures:
 *
 * 1. The range comes from the chart's own bars inside the window, not from a
 *    `request.security` call on a separate resolution. `calc` is handed one bar
 *    array and nothing else. It is also the more honest calculation: the
 *    original reads a whole 60-minute bar, so a 0915-0945 window with the
 *    resolution left at 60 returns the 0915-1015 high, which is thirty minutes
 *    of lookahead. Deriving from the window's own bars cannot do that, and it
 *    stays correct at any chart timeframe short enough to divide the window.
 * 2. `linewidth` is dropped. The chart generates a thickness control per plot
 *    from `style.lineWidth`, so a hand-rolled input would be a second width
 *    field fighting the first.
 *
 * `alertcondition` has no equivalent here, so the signals surface as chart
 * markers only.
 *
 * Full guide: docs/custom-indicators.md
 */

/** Colours matching the original study. */
const LEVEL_HIGH_COLOR = '#ff5252'
const LEVEL_LOW_COLOR = '#00e676'
const BUY_COLOR = '#4caf50'
const SELL_COLOR = '#ff5252'

export default function ({
  registerIndicator,
  utcSecondsToZonedParts,
  zonedDayIndex,
  isValidTimezone,
  DEFAULT_TIMEZONE,
}) {
  /** `'0915-1015'` to minutes-from-midnight bounds. Null when unparseable. */
  function parseSession(raw) {
    const m = /^(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})$/.exec(String(raw).trim())
    if (!m) return null
    const [sh, sm, eh, em] = [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])]
    if (sh > 23 || eh > 23 || sm > 59 || em > 59) return null
    return { start: sh * 60 + sm, end: eh * 60 + em }
  }

  /**
   * The zone the session string is read in. Bar times are UTC seconds and a
   * session is wall clock at the exchange, so the two only line up through a
   * zone. Falls back to the chart default rather than silently producing no
   * range at all.
   */
  function zoneOf(settings) {
    const raw = typeof settings.timezone === 'string' ? settings.timezone.trim() : ''
    return raw && isValidTimezone(raw) ? raw : DEFAULT_TIMEZONE
  }

  /**
   * Half-open bounds. A bar stamped exactly at the end time opens the breakout
   * window rather than closing the range, which is the usual session-window
   * convention. The second branch covers a window that wraps midnight.
   */
  function inSession(minuteOfDay, start, end) {
    return end > start
      ? minuteOfDay >= start && minuteOfDay < end
      : minuteOfDay >= start || minuteOfDay < end
  }

  /** Both levels, null on every bar where no completed range applies. */
  function computeOrb(bars, settings) {
    const orbHigh = new Array(bars.length).fill(null)
    const orbLow = new Array(bars.length).fill(null)
    const win = parseSession(settings.session ?? '')
    if (!win || bars.length === 0) return { orbHigh, orbLow }

    const zone = zoneOf(settings)
    let wasIn = false
    let runHigh = Number.NEGATIVE_INFINITY
    let runLow = Number.POSITIVE_INFINITY
    let levelHigh = null
    let levelLow = null

    for (let i = 0; i < bars.length; i++) {
      const parts = utcSecondsToZonedParts(bars[i].time, zone)
      const isIn = inSession(parts.hour * 60 + parts.minute, win.start, win.end)

      if (isIn && !wasIn) {
        runHigh = Number.NEGATIVE_INFINITY
        runLow = Number.POSITIVE_INFINITY
      }
      if (isIn) {
        if (bars[i].high > runHigh) runHigh = bars[i].high
        if (bars[i].low < runLow) runLow = bars[i].low
      } else if (wasIn && Number.isFinite(runHigh)) {
        // The first bar after the window closed. This is the original's
        // `endofsession` bar, where `valuewhen` latches the level.
        levelHigh = runHigh
        levelLow = runLow
      }

      // Hidden while the range is still forming, so the line starts at the
      // breakout window instead of running back across its own session.
      orbHigh[i] = isIn ? null : levelHigh
      orbLow[i] = isIn ? null : levelLow
      wasIn = isIn
    }
    return { orbHigh, orbLow }
  }

  /**
   * Breakout crossings, already de-repeated.
   *
   * Recomputed here rather than carried over from `calc`, because `markers` is
   * handed only the bars, the plotted values and the settings. It is a second
   * O(n) pass over data `calc` just walked, which is also why this descriptor
   * ships no `calcTail`: markers re-run in full after every recompute, so an
   * incremental price path would save nothing.
   */
  function computeSignals(bars, values, settings) {
    const hi = values.orbHigh ?? []
    const lo = values.orbLow ?? []
    const zone = zoneOf(settings)
    const out = []
    let isLong = false
    let isShort = false
    let prevWasNewDay = false

    for (let i = 1; i < bars.length; i++) {
      const newDay = zonedDayIndex(bars[i].time, zone) !== zonedDayIndex(bars[i - 1].time, zone)

      // `ta.crossover` / `ta.crossunder` against the plotted level. Both ends of
      // each comparison have to be present: a not-available value compares false
      // against everything, so nothing fires while the range is still forming.
      const [prevHigh, curHigh] = [hi[i - 1], hi[i]]
      const [prevLow, curLow] = [lo[i - 1], lo[i]]
      let buy =
        prevHigh != null && curHigh != null && bars[i - 1].high <= prevHigh && bars[i].high > curHigh
      let sell =
        prevLow != null && curLow != null && bars[i - 1].low >= prevLow && bars[i].low < curLow

      // exrem: one signal per direction until the other side fires.
      buy = buy && !isLong
      sell = sell && !isShort
      if (buy) {
        isLong = true
        isShort = false
      }
      if (sell) {
        isLong = false
        isShort = true
      }
      // The original resets the latch on the bar *after* the day turns, and the
      // reset runs last, so it also clears a latch set on that same bar. Kept as
      // written: under any session that ends after the open no signal can fire
      // that early in the day, so the off-by-one bar is unreachable in practice.
      if (prevWasNewDay) {
        isLong = false
        isShort = false
      }

      if (buy) out.push({ index: i, side: 'buy' })
      if (sell) out.push({ index: i, side: 'sell' })
      prevWasNewDay = newDay
    }
    return out
  }

  /**
   * How far off the candle a signal label sits, in price.
   *
   * `aboveBar` / `belowBar` anchor to the series the markers hang off, and for
   * an indicator that is its own plot, so both labels would end up pinned to the
   * ORB line rather than to the candle that broke it. `atPrice` is the only
   * position that takes an absolute price, and it adds no padding of its own, so
   * the gap has to come from here.
   *
   * Half a typical bar range keeps the label clear of the wick at any price
   * scale, from a 24000 index to a 100 rupee stock, without hardcoding a tick
   * count. The floor covers a run of dojis, where the mean range collapses.
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
    id: 'oa-open-range-breakout',
    name: 'Open Range Breakout',
    category: 'Custom',
    placement: 'onchart',
    inputs: [
      { key: 'session', type: 'text', label: 'Breakout Timings', default: '0915-1015' },
      { key: 'showSignals', type: 'boolean', label: 'Show Buy/Sell Labels', default: true },
      { key: 'timezone', type: 'text', label: 'Session Timezone', default: DEFAULT_TIMEZONE },
    ],
    plots: [
      {
        key: 'orbHigh',
        type: 'line',
        title: 'ORB High',
        style: { color: LEVEL_HIGH_COLOR, lineWidth: 2 },
      },
      {
        key: 'orbLow',
        type: 'line',
        title: 'ORB Low',
        style: { color: LEVEL_LOW_COLOR, lineWidth: 2 },
      },
    ],
    calc: (bars, settings) => computeOrb(bars, settings),
    markers({ bars, values, settings }) {
      if (settings.showSignals === false) return []
      const pad = markerPad(bars)
      const out = []
      for (const sig of computeSignals(bars, values, settings)) {
        const bar = bars[sig.index]
        out.push(
          sig.side === 'buy'
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
        )
      }
      return out
    },
  })
}
