/**
 * DRAWS example: supply and demand zones from swing pivots.
 *
 * The pattern behind most structure studies, and the one that had nowhere to
 * live before `draws()`: a plot is one value per bar and a level is a
 * horizontal line across the whole pane, so a box spanning a few dozen bars, or
 * a line joining two pivots, could not be expressed at all.
 *
 * Covers `draws` with all four kinds, `pivotHigh` / `pivotLow`, and the anchor
 * rule that matters most:
 *
 *   Anchors are TIMES, never bar indices. Paging history in at the left edge
 *   shifts every index by the page size, so an index-anchored box would slide
 *   off the bars it was drawn from the moment older data arrived. A time is
 *   stable for the life of the bar.
 *
 * A pivot is only confirmed `right` bars after it happened, which is why the
 * newest zone always sits a few bars back. That is honest rather than a bug: a
 * pivot you can see forming is a pivot that can still un-form.
 */

const SUPPLY = '#ef5350'
const DEMAND = '#26a69a'

export default function ({ registerIndicator, pivotHigh, pivotLow, nulls, withAlpha }) {

  registerIndicator({
    id: 'ex-zones-draws',
    name: 'Supply and Demand Zones',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'left', type: 'number', label: 'Pivot Left', default: 5, min: 1, max: 50, step: 1 },
      { key: 'right', type: 'number', label: 'Pivot Right', default: 5, min: 1, max: 50, step: 1 },
      { key: 'zones', type: 'number', label: 'Zones To Keep', default: 3, min: 1, max: 20, step: 1 },
      { key: 'thickness', type: 'number', label: 'Zone Thickness (%)', default: 0.35, min: 0.05, max: 5, step: 0.05 },
      { key: 'connect', type: 'boolean', label: 'Connect Pivots', default: true },
      { key: 'project', type: 'boolean', label: 'Project Last Zone', default: true },
    ],

    // The pivots are plotted as invisible columns so `draws` can read them out
    // of `values`: draws is handed the bars, the values and the settings, and
    // never the store, so anything it needs has to be a column.
    plots: [
      { key: 'ph', type: 'line', title: 'Pivot High', style: { visible: false } },
      { key: 'pl', type: 'line', title: 'Pivot Low', style: { visible: false } },
    ],

    calc(bars, settings) {
      const left = Math.max(1, Math.floor(Number(settings.left) || 5))
      const right = Math.max(1, Math.floor(Number(settings.right) || 5))
      return {
        ph: nulls(pivotHigh(bars.map((b) => b.high), left, right)),
        pl: nulls(pivotLow(bars.map((b) => b.low), left, right)),
      }
    },

    draws({ bars, values, settings }) {
      if (bars.length === 0) return []
      const keep = Math.max(1, Math.floor(Number(settings.zones) || 3))
      const pct = Math.max(0.01, Number(settings.thickness) || 0.35) / 100
      const out = []

      // Walk backwards so "the most recent N" falls out without sorting.
      const collect = (col, kind) => {
        const found = []
        for (let i = bars.length - 1; i >= 0 && found.length < keep; i--) {
          if (col[i] != null) found.push({ i, price: col[i] })
        }
        return found.map((p) => ({ ...p, kind }))
      }
      const highs = collect(values.ph, 'supply')
      const lows = collect(values.pl, 'demand')

      for (const p of [...highs, ...lows]) {
        const colour = p.kind === 'supply' ? SUPPLY : DEMAND
        const half = p.price * pct
        // A zone runs from its pivot to the right edge of the data. Both
        // anchors are bar times, so the box stays welded to its pivot.
        out.push({
          kind: 'box',
          from: { time: bars[p.i].time, price: p.price + half },
          to: { time: bars[bars.length - 1].time, price: p.price - half },
          color: colour,
          fillColor: colour,
          opacity: 0.13,
        })
      }

      // A line joining the last two pivots of a side is the trend of that
      // structure, which a horizontal level cannot say.
      if (settings.connect !== false) {
        for (const side of [highs, lows]) {
          if (side.length < 2) continue
          const [a, b] = side
          out.push({
            kind: 'line',
            from: { time: bars[b.i].time, price: b.price },
            to: { time: bars[a.i].time, price: a.price },
            color: side === highs ? SUPPLY : DEMAND,
            lineWidth: 1.5,
            lineStyle: 'dashed',
            // Carry the slope forward rather than stopping at the last pivot.
            extendRight: settings.project !== false,
          })
        }
      }

      // A polyline through every kept pivot, high to low and back, sketches the
      // swing structure the zones came from.
      const swing = [...highs, ...lows].sort((x, y) => x.i - y.i)
      if (swing.length > 2) {
        out.push({
          kind: 'polyline',
          points: swing.map((p) => ({ time: bars[p.i].time, price: p.price })),
          color: withAlpha('#8892a6', 0.55),
          lineWidth: 1,
        })
      }

      // One label on the newest zone, naming what it is. Labels split on \n.
      const newest = [...highs, ...lows].sort((x, y) => y.i - x.i)[0]
      if (newest) {
        out.push({
          kind: 'label',
          at: { time: bars[newest.i].time, price: newest.price },
          text: `${newest.kind}\n${newest.price.toFixed(2)}`,
          color: newest.kind === 'supply' ? SUPPLY : DEMAND,
        })
      }
      return out
    },
  })
}
