/**
 * SHADED ZONES example: Supertrend with a trend-coloured ribbon.
 *
 * How to shade the area between two series, the way Supertrend and HalfTrend do
 * it, where the band flips sides and recolours as the trend turns.
 *
 * The trick is in the plots, not in the fills. Split the level across two plots,
 * `up` and `down`, and give each one `null` while the other is active. The line
 * renderer breaks across the gap, so the level recolours at a flip on its own.
 * Then declare one fill per side. A fill only draws where BOTH of its endpoints
 * are non-null, so each ribbon appears only during its own trend, with no
 * per-bar colour logic anywhere:
 *
 *     plots:  up ──────╮        ╭────── up
 *                      ╰ down ──╯
 *     fills:  [up, upEdge]      -> drawn only while `up` is non-null
 *             [down, downEdge]  -> drawn only while `down` is non-null
 *
 * Setting `colorUpKey` and `colorDownKey` to the SAME input keeps a ribbon one
 * colour regardless of which endpoint happens to be on top. Point them at two
 * different inputs instead and the band recolours where the two series cross,
 * which is what you want for a spread or a ribbon between two moving averages.
 *
 * Note the colour inputs. Normally you let the chart generate style controls
 * from `plot.style`, but a fill takes `colorUpKey` / `colorDownKey`, which name
 * an INPUT key. A shaded indicator therefore has to declare its colours as
 * inputs, and the plots reference the same ones through `colorKey` so the line
 * and its ribbon can never drift apart.
 */

export default function ({ registerIndicator, supertrend, atr, nulls }) {
  registerIndicator({
    id: 'ex-shaded-trend-zone',
    name: 'Shaded Trend Zone',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'atrPeriod', type: 'number', label: 'ATR Period', default: 10, min: 1, max: 200, step: 1 },
      { key: 'multiplier', type: 'number', label: 'Multiplier', default: 3, min: 0.5, max: 20, step: 0.1 },
      { key: 'zoneWidth', type: 'number', label: 'Zone Width (ATR)', default: 1, min: 0, max: 10, step: 0.1 },
      { key: 'showZone', type: 'boolean', label: 'Show Shaded Zone', default: true },
      // Declared because the fills below reference them by key. Without inputs
      // to point at, a fill has no colour to use.
      { key: 'upColor', type: 'color', label: 'Uptrend', default: '#26a69a' },
      { key: 'downColor', type: 'color', label: 'Downtrend', default: '#ef5350' },
    ],

    plots: [
      // The level, split so it recolours at a flip. Each carries null while the
      // other is active.
      { key: 'up', type: 'line', title: 'Trend Up', colorKey: 'upColor', style: { lineWidth: 2 } },
      { key: 'down', type: 'line', title: 'Trend Down', colorKey: 'downColor', style: { lineWidth: 2 } },
      // The far edge of each ribbon. Thin, because the fill is the point of it.
      { key: 'upEdge', type: 'line', title: 'Zone Up', colorKey: 'upColor', style: { lineWidth: 1 } },
      { key: 'downEdge', type: 'line', title: 'Zone Down', colorKey: 'downColor', style: { lineWidth: 1 } },
    ],

    // One ribbon per side, each locked to a single colour.
    fills: [
      { between: ['up', 'upEdge'], colorUpKey: 'upColor', colorDownKey: 'upColor', opacity: 0.15 },
      { between: ['down', 'downEdge'], colorUpKey: 'downColor', colorDownKey: 'downColor', opacity: 0.15 },
    ],

    calc(bars, settings) {
      const n = bars.length
      const period = Math.max(1, Math.floor(Number(settings.atrPeriod) || 10))
      const mult = Number(settings.multiplier) || 3
      const width = Number(settings.zoneWidth) || 0
      const showZone = settings.showZone !== false

      const up = new Array(n).fill(NaN)
      const down = new Array(n).fill(NaN)
      const upEdge = new Array(n).fill(NaN)
      const downEdge = new Array(n).fill(NaN)
      if (n === 0) return { up: nulls(up), down: nulls(down), upEdge: nulls(upEdge), downEdge: nulls(downEdge) }

      // `supertrend` takes bars; `atr` takes three separate arrays.
      const st = supertrend(bars, period, mult)
      const range = atr(
        bars.map((b) => b.high),
        bars.map((b) => b.low),
        bars.map((b) => b.close),
        period
      )

      for (let i = 0; i < n; i++) {
        const point = st[i]
        if (!point || !Number.isFinite(point.value)) continue
        const offset = showZone && Number.isFinite(range[i]) ? range[i] * width : 0

        // direction -1 is an uptrend, +1 a downtrend.
        if (point.direction === -1) {
          up[i] = point.value
          // The ribbon sits above the support line during an uptrend.
          if (showZone) upEdge[i] = point.value + offset
        } else {
          down[i] = point.value
          // and below the resistance line during a downtrend.
          if (showZone) downEdge[i] = point.value - offset
        }
      }

      return {
        up: nulls(up),
        down: nulls(down),
        upEdge: nulls(upEdge),
        downEdge: nulls(downEdge),
      }
    },
  })
}
