/**
 * Replay is a simulation, and a simulation must not reach a broker.
 *
 * The chart draws Buy and Sell buttons, order lines you drag to re-price, a
 * cancel box and a position close. During replay the candles are a session that
 * finished weeks ago while the buttons quote the live price, so the two things
 * a trader reads before pressing Buy disagree by however far back the playhead
 * is, and neither of them says so. None of those routes was guarded.
 *
 * This pins the property structurally rather than by driving a terminal, which
 * needs a DOM and a broker session: every place that reaches the trade layer
 * from the chart has to consult the lock first. A new order route added without
 * one fails here, which is the failure that matters, because the hole this
 * closes was one handler deep and easy to miss by eye.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// Read from the project root: the test runs through a transform, so
// import.meta.url is not a file URL here.
const SRC = readFileSync(join(process.cwd(), 'src/lib/trading/terminal.ts'), 'utf8')

/** The body of a method or arrow, from its opening line to the matching brace. */
function blockAfter(marker: string): string {
  const at = SRC.indexOf(marker)
  expect(at, `marker not found: ${marker}`).toBeGreaterThan(-1)
  let depth = 0
  let i = SRC.indexOf('{', at)
  const start = i
  for (; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++
    else if (SRC[i] === '}' && --depth === 0) break
  }
  return SRC.slice(start, i + 1)
}

/** A whole call expression, from its opening paren to the matching one. */
function callAfter(marker: string): string {
  const at = SRC.indexOf(marker)
  expect(at, `marker not found: ${marker}`).toBeGreaterThan(-1)
  let depth = 0
  let i = SRC.indexOf('(', at)
  const start = i
  for (; i < SRC.length; i++) {
    if (SRC[i] === '(') depth++
    else if (SRC[i] === ')' && --depth === 0) break
  }
  return SRC.slice(start, i + 1)
}

const guarded = (body: string) =>
  body.includes('refuseWhileReplaying()') || body.includes('tradingLocked()')

describe('no order can leave the chart while replay owns it', () => {
  it('refuses a market order from the on-chart buttons', () => {
    expect(guarded(blockAfter('private async placeFromMenu('))).toBe(true)
  })

  it('refuses closing a position from its pill', () => {
    expect(guarded(blockAfter('async exitPosition()'))).toBe(true)
  })

  it('refuses the modify that a released order-line drag commits', () => {
    // The release is the modify. An earlier attempt guarded only the move,
    // which let the line be dragged and the order re-priced on let-go.
    const drag = callAfter('this.chart.subscribeDrag(')
    const release = drag.slice(drag.indexOf('},'))
    expect(release).toContain('trade!.modify(')
    expect(guarded(release)).toBe(true)
  })

  it('refuses the cancel box on an order line', () => {
    const click = callAfter('this.chart.subscribeClick(')
    const cancel = click.slice(click.indexOf("id.endsWith('::close')"))
    expect(cancel).toContain('.cancel(')
    expect(guarded(cancel)).toBe(true)
  })

  it('locks while a start bar is being picked, not only once it is walking', () => {
    // The shade is up and the future is hidden: the chart is already lying
    // about what is current, before the playhead has moved at all.
    const lock = blockAfter('private tradingLocked()')
    expect(lock).toContain('this.replay !== null')
    expect(lock).toContain('this.replayPicking')
  })

  it('takes the buttons off the chart rather than leaving them live-looking', () => {
    const body = blockAfter('private showTradeButtons(')
    expect(body).toContain('removePrimitive')
    expect(body).toContain('addPrimitive')
  })
})
