/**
 * A backtest's fills as marks on the price, held to what a reader relies on.
 *
 * Every test names the wrong implementation it catches. The label's two lines
 * and the arrow's direction are what a trader reads at a glance, so getting
 * either backwards is a chart that says the opposite of what happened.
 */

import { describe, expect, it } from 'vitest'
import { chartMarkersFrom, labelFor, natureOf, signedSize } from './backtestMarkers'

const AT = 1_700_000_000_000

function fill(over: Partial<Record<string, unknown>> = {}) {
  return {
    time: AT,
    kind: 'entry',
    side: 'buy',
    units: 2,
    price: 100,
    tag: 'MomLE',
    tradeIndex: 1,
    ...over,
  }
}

describe('the signed size', () => {
  it('writes a buy with an explicit plus and a sell with a minus', () => {
    // Catches the sign dropped. A column holding 2 and -2 reads as a typo, and
    // a column of bare numbers does not say which way the order went at all.
    expect(signedSize('buy', 2)).toBe('+2')
    expect(signedSize('sell', 2)).toBe('-2')
  })

  it('takes the direction from the side and never from the sign of the size', () => {
    // Catches a size that is already negative being negated twice. The report
    // states units as a magnitude and the side as the direction.
    expect(signedSize('sell', -2)).toBe('-2')
    expect(signedSize('buy', -2)).toBe('+2')
  })
})

describe('the label', () => {
  it('puts what the fill did against the arrow and the size on the far side', () => {
    // Catches the two lines swapped. What the fill did is the line a reader
    // matches against the price, so it is nearest the thing it marks: above a
    // bar that is the lower line, below a bar the upper one.
    expect(labelFor(fill({ side: 'sell' }), true)).toBe('-2\nShort')
    expect(labelFor(fill(), false)).toBe('Long\n+2')
  })

  it('draws the same label whatever the tag was, including none', () => {
    // The tag is a position name the language forces a close to repeat from
    // its entry, so it distinguishes nothing between the two orders of a round
    // trip and belongs nowhere on the chart.
    expect(labelFor(fill({ tag: '' }), false)).toBe('Long\n+2')
    expect(labelFor(fill({ tag: 'anything' }), false)).toBe('Long\n+2')
  })
})

describe('the marks', () => {
  it('points an entry at the bar: a buy under it and a sell over it', () => {
    // Catches the arrows inverted, which is the one defect that makes the chart
    // state the opposite of what the run did.
    const [buy] = chartMarkersFrom([fill({ side: 'buy' })])
    const [sell] = chartMarkersFrom([fill({ side: 'sell' })])

    expect(buy.shape).toBe('arrowUp')
    expect(buy.position).toBe('belowBar')
    expect(sell.shape).toBe('arrowDown')
    expect(sell.position).toBe('aboveBar')
  })

  it('mirrors an exit, so a round trip visibly opens and closes', () => {
    // Catches exits drawn the same way up as entries, which leaves a column of
    // identical arrows that cannot be read as pairs.
    const [entry] = chartMarkersFrom([fill({ kind: 'entry', side: 'buy' })])
    const [exit] = chartMarkersFrom([fill({ kind: 'exit', side: 'buy' })])

    expect(entry.position).toBe('belowBar')
    expect(exit.position).toBe('aboveBar')
  })

  it('converts the record milliseconds into the axis seconds', () => {
    // The same conversion the curve needs, and the same silent failure: marks
    // dated 1970 sit off the left edge and the chart looks like it drew none.
    expect(chartMarkersFrom([fill()])[0].time).toBe(1_700_000_000)
  })

  it('drops a fill with no time or no price rather than placing it at zero', () => {
    // Catches absence read as zero. A mark at time 0 drags the axis to 1970 and
    // a mark at price 0 sits at the bottom of the pane pretending to be a fill.
    expect(chartMarkersFrom([fill({ time: null })])).toHaveLength(0)
    expect(chartMarkersFrom([fill({ price: null })])).toHaveLength(0)
  })

  it('gives each fill a stable id, so redrawing replaces rather than stacks', () => {
    // Catches ids that collide or that change between runs: the first stacks
    // two runs of marks on one chart, the second leaves the old ones behind.
    const twice = chartMarkersFrom([
      fill({ tradeIndex: 1, kind: 'entry' }),
      fill({ tradeIndex: 1, kind: 'exit' }),
    ])
    expect(new Set(twice.map((m) => m.id)).size).toBe(2)
    expect(chartMarkersFrom([fill()])[0].id).toBe(chartMarkersFrom([fill()])[0].id)
  })

  it('colours by direction so a mark reads without a legend', () => {
    const [buy] = chartMarkersFrom([fill({ side: 'buy' })], { up: 'U', down: 'D' })
    const [sell] = chartMarkersFrom([fill({ side: 'sell' })], { up: 'U', down: 'D' })

    expect(buy.color).toBe('U')
    expect(sell.color).toBe('D')
  })
})

describe('a reversal, which puts two fills on one bar', () => {
  /** The two fills a stop and reverse strategy emits at one flip. */
  const closingLong = { time: 1, kind: 'exit', side: 'sell', units: 1, tag: 'StUp', price: 100 }
  const openingShort = { time: 1, kind: 'entry', side: 'sell', units: 1, tag: 'StDn', price: 100 }

  it('never draws the tag, because it names a position and not an order', () => {
    // THE DEFECT. `close(tag = "StUp")` means "close whatever StUp is holding",
    // so a close is required to repeat its entry's tag: the language has no
    // other way to say which position to flatten. Drawing it put the same word
    // on both orders of a round trip, where it distinguished nothing, and put
    // the name of a long beside a sell on every reversal.
    expect(labelFor(closingLong, false)).not.toContain('StUp')
    expect(labelFor(openingShort, true)).not.toContain('StDn')
  })

  it('says what each fill did, which is the thing not written anywhere else', () => {
    expect(labelFor(closingLong, false)).toBe('Exit long\n-1')
    expect(labelFor(openingShort, true)).toBe('-1\nShort')
  })

  it('reads kind and side together, because neither alone is the answer', () => {
    // A sell opens a short and closes a long. Reading only the side would put
    // the same word on the two opposite ends of a trade.
    expect(natureOf({ kind: 'entry', side: 'buy' })).toBe('Long')
    expect(natureOf({ kind: 'entry', side: 'sell' })).toBe('Short')
    expect(natureOf({ kind: 'exit', side: 'sell' })).toBe('Exit long')
    expect(natureOf({ kind: 'exit', side: 'buy' })).toBe('Exit short')
  })

  it('makes the pair on one bar read as two orders and not a contradiction', () => {
    // Both fills are real and both belong on the chart: a reversal is a close
    // and an open, and the broker will report two orders.
    const marks = chartMarkersFrom([closingLong, openingShort])

    expect(marks).toHaveLength(2)
    expect(marks[0].text).toContain('Exit long')
    expect(marks[1].text).toContain('Short')
    expect(marks[1].text).not.toContain('Exit')
    // Separated on the price, so the pair does not overprint at one point.
    expect(marks[0].position).not.toBe(marks[1].position)
  })

  it('still ids the two fills of one reversal apart', () => {
    // They share a bar, a price and a side. An id that collided would let one
    // replace the other and the chart would draw a reversal as a single order.
    const marks = chartMarkersFrom([
      { ...closingLong, tradeIndex: 1 },
      { ...openingShort, tradeIndex: 2 },
    ])

    expect(marks[0].id).not.toBe(marks[1].id)
  })

  it('needs no tag at all, since it never used one', () => {
    expect(labelFor({ ...closingLong, tag: '' }, false)).toBe('Exit long\n-1')
    expect(labelFor({ ...openingShort, tag: undefined }, true)).toBe('-1\nShort')
  })
})
