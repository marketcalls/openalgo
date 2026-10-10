import { describe, expect, it, vi } from 'vitest'
import type { InputPick } from './terminal'
import { TradingTerminal } from './terminal'

/** Just enough chart for a pick: its clock, its events and `beginPick`. */
function terminalWith() {
  const listeners = new Map<string, (event: unknown) => void>()
  const calls: { kind: string; cb: (value: unknown) => void; where?: unknown }[] = []
  const cancel = vi.fn()
  const chart = {
    timezone: () => 'Asia/Kolkata',
    on: (name: string, cb: (event: unknown) => void) => {
      listeners.set(name, cb)
      return () => listeners.delete(name)
    },
    beginPick: (kind: string, cb: (value: unknown) => void, where?: unknown) => {
      calls.push({ kind, cb, where })
      return cancel
    },
  }
  const terminal = Object.create(TradingTerminal.prototype) as TradingTerminal
  Object.assign(terminal, { chart, destroyed: false })
  return { terminal, calls, cancel, end: (value: unknown) => listeners.get('pick:end')?.({ value }) }
}

describe('picking a study input on the chart', () => {
  it('takes one click for a price paired with a time, with the wall clock in the chart zone', () => {
    const { terminal, calls } = terminalWith()
    const got: (InputPick | null)[] = []
    terminal.pickInput({ key: 'level', type: 'price', label: 'Level', timeKey: 'at' }, (value) =>
      got.push(value)
    )
    expect(calls[0].kind).toBe('point')
    // 2023-11-14 22:13:20 UTC is 2023-11-15 03:43 in India.
    calls[0].cb({ time: 1_700_000_000, price: 101.5 })
    expect(got).toEqual([{ price: 101.5, time: 1_700_000_000, clock: '2023-11-15 03:43' }])
  })

  it('picks a lone price on the scale a study names, and a time for a time input', () => {
    const { terminal, calls } = terminalWith()
    const got: (InputPick | null)[] = []
    terminal.pickInput(
      { key: 'level', type: 'price', label: 'Level', pick: { paneIndex: 2 } },
      (value) => got.push(value)
    )
    expect(calls[0]).toMatchObject({ kind: 'price', where: { paneIndex: 2 } })
    calls[0].cb(250)
    terminal.pickInput({ key: 'start', type: 'timestamp', label: 'Start' }, (value) =>
      got.push(value)
    )
    expect(calls[1].kind).toBe('time')
    calls[1].cb(1_700_000_000)
    expect(got).toEqual([{ price: 250 }, { time: 1_700_000_000, clock: '2023-11-15 03:43' }])
  })

  it('answers null once when the pick is cancelled, by the form or by the chart', () => {
    const { terminal, cancel, end } = terminalWith()
    const got: (InputPick | null)[] = []
    const stop = terminal.pickInput({ key: 'level', type: 'price', label: 'Level' }, (value) =>
      got.push(value)
    )
    stop()
    expect(cancel).toHaveBeenCalledOnce()
    terminal.pickInput({ key: 'level', type: 'price', label: 'Level' }, (value) => got.push(value))
    end(null)
    expect(got).toEqual([null, null])
  })
})
