/**
 * The two series the backtest chart draws, held to the conversion that fails
 * without throwing.
 *
 * Each test names the wrong implementation it catches. The chart itself is not
 * rendered here: the engine is a canvas library and what it is handed is the
 * part that can be wrong while looking entirely normal on screen.
 */

import { describe, expect, it } from 'vitest'
import { compress, seriesFrom } from './BacktestChart'

/** One point of the report's curve: milliseconds, as the record carries it. */
function point(msAt: number, equity: number, drawdown: number) {
  return { time: 1_700_000_000_000 + msAt, equity, drawdown }
}

describe('seriesFrom', () => {
  it('converts the record milliseconds into the axis seconds', () => {
    // THE ONE THAT MATTERS. The report counts milliseconds and the chart's time
    // axis counts seconds. Handed milliseconds the axis places every point tens
    // of thousands of years out, and the curve draws as a flat line against one
    // edge with no error anywhere.
    const { equity } = seriesFrom([point(0, 100, 0), point(60_000, 110, 0)])

    expect(equity[0].time).toBe(1_700_000_000)
    expect(equity[1].time).toBe(1_700_000_060)
  })

  it('keeps drawdown negative rather than flipping it', () => {
    // Catches a flip to absolute values. The record states drawdown as zero or
    // negative, and drawing it upward puts the worst moment of a run at the top
    // of its own pane, which reads as the best.
    const { drawdown } = seriesFrom([point(0, 100, 0), point(1000, 90, -10)])

    expect(drawdown[1].value).toBe(-10)
  })

  it('drops a point with no time instead of placing it at the epoch', () => {
    // Catches a null time coerced to 0. One such point drags the axis back to
    // 1970 and squashes the entire curve into the last pixel column.
    const { equity } = seriesFrom([
      { time: null, equity: 100, drawdown: 0 },
      point(0, 110, 0),
    ])

    expect(equity).toHaveLength(1)
    expect(equity[0].time).toBe(1_700_000_000)
  })

  it('drops a point whose value is absent without dropping its neighbours', () => {
    const { equity, drawdown } = seriesFrom([
      point(0, 100, 0),
      { time: 1_700_000_001_000, equity: null, drawdown: -5 },
      point(2000, 120, 0),
    ])

    expect(equity).toHaveLength(2)
    // The drawdown at that point is a real figure and is kept even though the
    // equity beside it is not: they are two series, not two columns of one row.
    expect(drawdown).toHaveLength(3)
  })

  it('answers empty series for an empty curve rather than throwing', () => {
    expect(seriesFrom([])).toEqual({ equity: [], drawdown: [], drawdownPercent: [] })
  })
})

describe('drawdown as a share of its peak', () => {
  it('measures each drawdown against the high it fell from', () => {
    // Equity 90,000 after falling 10,000 from a 1,00,000 high is -10%.
    const { drawdownPercent } = seriesFrom([point(0, 100000, 0), point(1000, 90000, -10000)])
    expect(drawdownPercent.map((p) => p.value)).toEqual([0, -10])
  })
})

describe('compress, the whole run in the width of the chart', () => {
  // A two-month run on one-minute bars, with one deep trough and one high.
  const long = Array.from({ length: 30_000 }, (_, i) => ({
    time: 1_700_000_000 + i * 60,
    value: i === 12_345 ? -500 : i === 23_456 ? 900 : Math.sin(i / 500) * 100,
  }))

  it('keeps about two points a slice, from the first bar to the last', () => {
    const out = compress(long, 160)
    expect(out.length).toBeLessThanOrEqual(2 * 160 + 2)
    expect(out[0]).toEqual(long[0])
    expect(out[out.length - 1]).toEqual(long[long.length - 1])
  })

  it('never smooths away the deepest trough or the highest peak', () => {
    const values = compress(long, 160).map((p) => p.value)
    expect(Math.min(...values)).toBe(-500)
    expect(Math.max(...values)).toBe(900)
  })

  it('hands the time axis each time once, in order', () => {
    const times = compress(long, 160).map((p) => p.time)
    expect(times.every((time, i) => i === 0 || time > times[i - 1])).toBe(true)
  })

  it('leaves a short run as it is', () => {
    const short = long.slice(0, 100)
    expect(compress(short, 160)).toEqual(short)
  })
})
