import type { Bar, IPrimitive } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProfileLayer } from './profileLayer'

const bar: Bar = { time: 100, open: 10, high: 12, low: 9, close: 11, volume: 100 }

function fixture() {
  let bars = [bar]
  const drawn: Bar[][] = []
  const attached = new Set<IPrimitive>()
  const primitive = {
    zOrder: () => 'normal' as const,
    draw() {},
    setBars(input: readonly Bar[]) {
      drawn.push(input.map((b) => ({ ...b })))
    },
  }
  let resolve!: (value: typeof primitive) => void
  let reject!: (reason: Error) => void
  const pending = new Promise<typeof primitive>((res, rej) => {
    resolve = res
    reject = rej
  })
  const onError = vi.fn()
  const layer = new ProfileLayer({
    host: {
      addPrimitive: (p) => {
        attached.add(p)
      },
      removePrimitive: (p) => {
        attached.delete(p)
      },
    },
    load: () => pending,
    readBars: () => bars,
    onError,
  })
  return {
    layer,
    primitive,
    drawn,
    attached,
    resolve,
    reject,
    onError,
    setBars: (next: Bar[]) => {
      bars = next
    },
  }
}

afterEach(() => vi.useRealTimers())

describe('ProfileLayer', () => {
  it('forwards a session menu only while its profile is attached', async () => {
    const f = fixture()
    const run = vi.fn()
    const contextMenuAt = vi.fn(() => ({
      label: 'Split this day',
      sessionLabel: '8 Sept 2026',
      run,
    }))
    expect(f.layer.contextMenuAt(20, 30)).toBeNull()
    const primitive = { ...f.primitive, contextMenuAt }
    f.resolve(primitive)
    await f.layer.ready
    const action = f.layer.contextMenuAt(20, 30)!
    expect(contextMenuAt).toHaveBeenCalledWith(20, 30)
    expect(action.label).toBe('Split this day')
    action.run()
    expect(run).toHaveBeenCalledTimes(1)
    f.layer.dispose()
    action.run()
    expect(run).toHaveBeenCalledTimes(1)
    expect(f.layer.contextMenuAt(20, 30)).toBeNull()
  })

  it('does not attach a late profile import after its chart is replaced', async () => {
    const f = fixture()
    f.layer.dispose()
    f.resolve(f.primitive)
    await f.layer.ready
    expect(f.attached.size).toBe(0)
    expect(f.drawn).toEqual([])
  })

  it('uses the currently displayed replay prefix when loading finishes', async () => {
    const f = fixture()
    f.setBars([{ ...bar, high: 10, close: 10, volume: 20 }])
    f.resolve(f.primitive)
    await f.layer.ready
    expect(f.drawn).toEqual([[{ ...bar, high: 10, close: 10, volume: 20 }]])
    expect(f.attached.size).toBe(1)
    f.layer.dispose()
  })

  it('coalesces live ticks but applies a backwards replay seek immediately', async () => {
    vi.useFakeTimers()
    const f = fixture()
    f.resolve(f.primitive)
    await f.layer.ready
    f.setBars([bar, { ...bar, time: 200, volume: 400 }])
    f.layer.refresh()
    f.setBars([bar, { ...bar, time: 200, volume: 500 }])
    f.layer.refresh()
    await vi.advanceTimersByTimeAsync(100)
    expect(f.drawn.at(-1)?.at(-1)?.volume).toBe(500)
    expect(f.drawn).toHaveLength(2)
    f.layer.refresh()
    f.setBars([{ ...bar, volume: 40 }])
    f.layer.refresh(true)
    expect(f.drawn.at(-1)).toEqual([{ ...bar, volume: 40 }])
    await vi.advanceTimersByTimeAsync(100)
    expect(f.drawn).toHaveLength(3)
    f.layer.dispose()
  })

  it('removes the primitive and cancels pending live work on disposal', async () => {
    vi.useFakeTimers()
    const f = fixture()
    f.resolve(f.primitive)
    await f.layer.ready
    f.layer.refresh()
    f.layer.dispose()
    f.layer.dispose()
    await vi.advanceTimersByTimeAsync(100)
    expect(f.attached.size).toBe(0)
    expect(f.drawn).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('reports current load failures and ignores a disposed chart failure', async () => {
    const f = fixture()
    const error = new Error('profile chunk unavailable')
    f.reject(error)
    await f.layer.ready
    expect(f.onError).toHaveBeenCalledWith(error)
    const stale = fixture()
    stale.layer.dispose()
    stale.reject(error)
    await stale.layer.ready
    expect(stale.onError).not.toHaveBeenCalled()
  })
})
