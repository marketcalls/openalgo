import type { SeriesAttachedParameter, Time } from 'lightweight-charts'
import { describe, expect, it } from 'vitest'
import {
  BarCountdown,
  barSecondsLeft,
  type CountdownBar,
  formatCountdown,
  padToPrice,
} from './scalpingCountdown'

// 09:15:00 IST on a trading day, in the scalper's IST-shifted time base.
const OPEN = 1_761_556_500 + 19_800
// A space as wide as a digit; what pads the countdown to the price's width.
const FS = String.fromCharCode(0x2007)

describe('barSecondsLeft', () => {
  it('counts the forming bar down to its close', () => {
    expect(barSecondsLeft(OPEN, 60, OPEN)).toBe(60)
    expect(barSecondsLeft(OPEN, 60, OPEN + 18)).toBe(42)
    expect(barSecondsLeft(OPEN, 300, OPEN + 299.5)).toBe(0.5)
  })

  it('carries on against the current bucket when the last bar has not ticked yet', () => {
    // Last bar opened 09:15, the clock is at 09:17:20: 40s left in the 09:17 bar.
    expect(barSecondsLeft(OPEN, 60, OPEN + 140)).toBe(40)
    // Exactly on a close the next bar has its full interval to run.
    expect(barSecondsLeft(OPEN, 900, OPEN + 900)).toBe(900)
  })

  it('reads a clock running behind the bar as time still to go', () => {
    expect(barSecondsLeft(OPEN, 60, OPEN - 2)).toBe(62)
  })

  it('refuses inputs that cannot produce a count', () => {
    expect(barSecondsLeft(OPEN, 0, OPEN)).toBeNull()
    expect(barSecondsLeft(OPEN, -60, OPEN)).toBeNull()
    expect(barSecondsLeft(Number.NaN, 60, OPEN)).toBeNull()
    expect(barSecondsLeft(OPEN, 60, Number.POSITIVE_INFINITY)).toBeNull()
  })
})

describe('formatCountdown', () => {
  it('shows minutes and seconds, rounding a part second up', () => {
    expect(formatCountdown(42)).toBe('00:42')
    expect(formatCountdown(0.2)).toBe('00:01')
    expect(formatCountdown(899)).toBe('14:59')
    expect(formatCountdown(0)).toBe('00:00')
  })

  it('adds hours only when an hour or more is left', () => {
    expect(formatCountdown(3600)).toBe('01:00:00')
    expect(formatCountdown(3661)).toBe('01:01:01')
  })

  it('shows a placeholder when there is no count', () => {
    expect(formatCountdown(null)).toBe('--:--')
    expect(formatCountdown(Number.NaN)).toBe('--:--')
  })
})

describe('padToPrice', () => {
  it('centres the countdown to the width of the price above it', () => {
    expect(padToPrice('08:13', '94.7078')).toBe(`${FS}08:13${FS}`)
    expect(padToPrice('08:13', '24121.12')).toBe(`${FS}08:13${FS}${FS}`)
  })

  it('leaves a countdown as wide as the price alone', () => {
    expect(padToPrice('00:42', '85.40')).toBe('00:42')
    expect(padToPrice('01:00:00', '85.40')).toBe('01:00:00')
  })
})

describe('BarCountdown', () => {
  const setup = (bar: CountdownBar | null, now: number) => {
    let updates = 0
    const primitive = new BarCountdown({
      lastBar: () => bar,
      intervalSec: () => 60,
      now: () => now,
      upColor: 'up',
      downColor: 'down',
    })
    const param = {
      series: {
        priceToCoordinate: (price: number) => price * 2,
        priceFormatter: () => ({ format: (price: number) => price.toFixed(2) }),
      },
      requestUpdate: () => {
        updates++
      },
    } as unknown as SeriesAttachedParameter<Time>
    primitive.attached(param)
    primitive.updateAllViews()
    return { view: primitive.priceAxisViews()[0], primitive, updates: () => updates }
  }

  it('sits one pixel below the last price tag, in the bar colour', () => {
    const { view } = setup({ time: OPEN, close: 100, up: false }, OPEN + 18)
    expect(view.visible?.()).toBe(true)
    expect(view.text()).toBe(`00:42${FS}`)
    expect(view.coordinate()).toBe(201)
    expect(view.backColor()).toBe('down')
    expect(view.tickVisible?.()).toBe(false)
  })

  it('draws nothing while the chart has no bars', () => {
    const { view } = setup(null, OPEN)
    expect(view.visible?.()).toBe(false)
  })

  it('asks the chart to repaint on refresh, and stops once detached', () => {
    const { primitive, updates } = setup({ time: OPEN, close: 100, up: true }, OPEN)
    primitive.refresh()
    expect(updates()).toBe(1)
    primitive.detached()
    primitive.refresh()
    expect(updates()).toBe(1)
  })
})
