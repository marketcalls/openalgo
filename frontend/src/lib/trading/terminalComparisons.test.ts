import {
  type Bar,
  type BarsRequest,
  comparisonController,
  createChart,
  exportChartDataCsv,
  type OpenAlgoWsFeed,
  ReplayController,
  type SocketLike,
} from 'openalgo-charts'
import type { WorkspaceComparison } from 'openalgo-charts/workspace'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TerminalComparisons } from './terminalComparisons'

const bar = (time: number, close: number, volume = 10): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume,
})
const spec = (id = 'other', exchange = 'NSE'): WorkspaceComparison => ({
  id,
  symbol: 'OTHER',
  exchange,
  color: '#eeaa00',
  visible: true,
})
const context = { interval: '1m', from: 60, to: 240, timezone: 'Asia/Kolkata' }
const charts: ReturnType<typeof createChart>[] = []
const helpers: TerminalComparisons[] = []

class Socket implements SocketLike {
  readyState = 0
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  sent: Record<string, unknown>[] = []
  closed = false
  send(data: string) {
    this.sent.push(JSON.parse(data))
  }
  close() {
    this.closed = true
    this.readyState = 3
  }
  open() {
    this.readyState = 1
    this.onopen?.()
    this.receive({ type: 'auth', status: 'success' })
  }
  receive(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
  tick(price: number, time: number, exchange = 'NSE') {
    this.receive({ data: { symbol: 'OTHER', exchange, ltp: price, timestamp: time } })
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function chart() {
  const result = createChart(document.createElement('div'), {
    shortcuts: false,
    timeNavigator: false,
    raf: {
      schedule(callback) {
        callback()
        return 1
      },
      cancel() {},
    },
  })
  result.applySize(800, 500)
  result.addSeries('candlestick').setData([bar(60, 100), bar(120, 110), bar(180, 120)])
  charts.push(result)
  return result
}

function helper(
  getBars = vi.fn(async (_request: BarsRequest) => [bar(60, 200), bar(120, 220), bar(180, 240)])
) {
  const sockets: Socket[] = []
  const onChange = vi.fn()
  const instance = new TerminalComparisons({
    feed: { getBars },
    now: () => 240,
    onChange,
    ws: {
      url: 'ws://comparison.invalid',
      apiKey: 'synthetic',
      heartbeat: { timeoutMs: 0 },
      reconnect: { baseDelayMs: 10, maxDelayMs: 10, jitter: false },
      socketFactory: () => {
        const socket = new Socket()
        sockets.push(socket)
        return socket
      },
    },
  })
  helpers.push(instance)
  return { instance, sockets, onChange, getBars }
}

beforeEach(() => {
  vi.useFakeTimers()
  const canvas = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvas as unknown as CanvasRenderingContext2D
  )
})

afterEach(() => {
  for (const instance of helpers.splice(0)) instance.destroy()
  for (const instance of charts.splice(0)) instance.destroy()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('terminal comparison ownership', () => {
  it.each([
    'linear',
    'logarithmic',
  ] as const)('restores the underlying %s price scale after saving and removing a comparison', async (mode) => {
    const { instance } = helper()
    const original = chart()
    original.setPriceScaleOptions({ mode })
    await instance.replace([spec()], 'percent')
    await instance.bind(original, context)
    expect(original.priceScaleOptions().mode).toBe('percentage')
    const before = original.getState()
    const setOptions = vi.spyOn(original.panes()[0].priceScale, 'setOptions')
    const saved = instance.captureBaseState()
    expect(setOptions).not.toHaveBeenCalled()
    expect(original.getState()).toEqual(before)
    const restored = chart()
    restored.restoreState(JSON.parse(JSON.stringify(saved)))
    const next = helper().instance
    await next.replace(instance.specs(), instance.mode)
    await next.bind(restored, context)
    next.remove('other')
    expect(restored.priceScaleOptions().mode).toBe(mode)
  })

  it('preserves a user scale choice made while comparing through mode changes and capture', async () => {
    const { instance } = helper()
    const target = chart()
    await instance.replace([spec()], 'percent')
    await instance.bind(target, context)
    target.setPriceScaleOptions({ mode: 'logarithmic', inverted: true })
    instance.setMode('price')
    instance.setMode('percent')
    const saved = instance.captureBaseState()
    expect(saved.panes?.[0].priceScale).toMatchObject({ mode: 'logarithmic', inverted: true })
    instance.remove('other')
    expect(target.priceScaleOptions()).toMatchObject({ mode: 'logarithmic', inverted: true })
  })

  it('detaches persisted specs and registers common-baseline comparisons for CSV', async () => {
    const { instance, getBars, sockets } = helper()
    const input = spec()
    await instance.replace([input], 'percent')
    input.symbol = 'MUTATED'
    const target = chart()
    await instance.bind(target, context)
    expect(getBars).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'OTHER',
        exchange: 'NSE',
        interval: '1m',
        from: 60,
        to: 240,
      })
    )
    expect(instance.specs()[0].symbol).toBe('OTHER')
    instance.specs()[0].symbol = 'MUTATED AGAIN'
    expect(instance.specs()[0].symbol).toBe('OTHER')
    expect(comparisonController(target).baseline).toBe('common')
    expect(comparisonController(target).mode).toBe('percentage')
    expect(instance.rows(120)[0].close).toBe(220)
    expect(exportChartDataCsv(target)).toContain('OTHER')
    expect(sockets).toHaveLength(1)
  })

  it('shares one dedicated socket and filters equal symbols by exchange', async () => {
    const { instance, sockets } = helper()
    await instance.replace([spec('cash'), spec('other-venue', 'BSE')], 'price')
    await instance.bind(chart(), context)
    expect(sockets).toHaveLength(1)
    sockets[0].open()
    sockets[0].tick(280, 190, 'BSE')
    expect(instance.rows(180).map((row) => row.close)).toEqual([240, 280])
    sockets[0].tick(999, 195, 'UNKNOWN')
    expect(instance.rows(180).map((row) => row.close)).toEqual([240, 280])
    expect(sockets[0].sent.filter((message) => message.action === 'subscribe')).toHaveLength(2)
  })

  it('normalizes duplicate history and reseeds repaired bars without a stale live rollback', async () => {
    const getBars = vi.fn(async (_request: BarsRequest) => [
      bar(180, 200),
      bar(60, 100),
      bar(180, 240),
    ])
    const { instance, sockets, onChange } = helper(getBars)
    await instance.replace([spec()], 'price')
    const target = chart()
    await instance.bind(target, context)
    const handle = comparisonController(target).list()[0]
    expect(handle.barAt(180)?.close).toBe(240)
    sockets[0].open()
    onChange.mockClear()
    sockets[0].tick(250, 190)
    sockets[0].tick(260, 195)
    expect(handle.barAt(180)?.close).toBe(260)
    expect(onChange).not.toHaveBeenCalled()
    getBars.mockResolvedValue([bar(60, 100), bar(120, 220), bar(180, 245, 100)])
    await instance.refresh()
    expect(handle.barAt(180)?.close).toBe(245)
    sockets[0].tick(247, 200)
    expect(handle.barAt(180)).toMatchObject({ open: 245, high: 260, close: 247, volume: 100 })
  })

  it('rejects unavailable staged history while retaining a visible error and allowing retry', async () => {
    const getBars = vi.fn(async (_request: BarsRequest): Promise<Bar[]> => {
      throw new Error('History unavailable')
    })
    const { instance } = helper(getBars)
    await instance.replace([spec()], 'percent')
    await expect(instance.bind(chart(), context)).rejects.toThrow('History unavailable')
    expect(instance.rows()[0]).toMatchObject({
      status: 'error',
      error: 'History unavailable',
      close: null,
    })
    getBars.mockResolvedValue([bar(60, 200), bar(120, 220)])
    await instance.refresh()
    expect(instance.rows(120)[0]).toMatchObject({ status: 'ready', close: 220 })
    await expect(instance.add({ ...spec('next'), symbol: 'NEXT' })).resolves.toBeUndefined()
    expect(instance.specs()).toHaveLength(2)
  })

  it('retains history with a stale status after repair failure and repairs after reconnect', async () => {
    const { instance, getBars, sockets } = helper()
    await instance.replace([spec()], 'price')
    await instance.bind(chart(), context)
    sockets[0].open()
    getBars.mockRejectedValueOnce(new Error('Repair failed'))
    await instance.refresh()
    expect(instance.rows(180)[0]).toMatchObject({
      status: 'stale',
      close: 240,
      error: 'Repair failed',
    })
    sockets[0].close()
    sockets[0].onclose?.()
    await vi.advanceTimersByTimeAsync(10)
    expect(sockets[0].closed).toBe(true)
    expect(sockets).toHaveLength(2)
    sockets[1].open()
    await vi.advanceTimersByTimeAsync(0)
    expect(instance.rows(180)[0]).toMatchObject({ status: 'ready', close: 240 })
    expect(getBars).toHaveBeenCalledTimes(3)
  })

  it('aborts and ignores a removed source even when transport ignores its signal', async () => {
    const late = deferred<Bar[]>()
    const getBars = vi.fn((_request: BarsRequest) => late.promise)
    const { instance } = helper(getBars)
    await instance.replace([spec()], 'price')
    const target = chart()
    const loading = instance.bind(target, context)
    await vi.advanceTimersByTimeAsync(0)
    const signal = getBars.mock.calls[0][0].signal
    instance.remove('other')
    expect(signal?.aborted).toBe(true)
    late.resolve([bar(120, 999)])
    await loading
    expect(instance.specs()).toEqual([])
    expect(comparisonController(target).list()).toEqual([])
  })

  it('preserves definitions across a chart generation and rejects stale history writes', async () => {
    const late = deferred<Bar[]>()
    const getBars = vi
      .fn(async (_request: BarsRequest) => [bar(60, 200), bar(120, 220)])
      .mockImplementationOnce(() => late.promise)
    const { instance } = helper(getBars)
    await instance.replace([{ ...spec(), visible: false }], 'percent')
    const first = chart()
    const oldBinding = instance.bind(first, context)
    await vi.advanceTimersByTimeAsync(0)
    const second = chart()
    await instance.bind(second, { ...context, interval: '5m' })
    late.resolve([bar(120, 999)])
    await oldBinding
    expect(comparisonController(first).list()).toEqual([])
    expect(comparisonController(second).mode).toBe('percentage')
    expect(second.getState().series?.some((series) => series.style?.visible === false)).toBe(true)
    expect(instance.specs()).toEqual([{ ...spec(), visible: false }])
    instance.setVisible('other', true)
    expect(instance.rows(120)[0].close).toBe(220)
  })

  it('keeps aligned readings inside the replay prefix as live data advances', async () => {
    const { instance, sockets } = helper()
    await instance.replace([spec()], 'price')
    const target = chart()
    await instance.bind(target, context)
    sockets[0].open()
    const replay = new ReplayController(target, { startIndex: 0 })
    sockets[0].tick(999, 190)
    expect(instance.rows(180)[0].close).toBeNull()
    expect(instance.rows(60)[0].close).toBe(200)
    replay.stop()
    expect(instance.rows(180)[0].close).toBe(999)
  })

  it.each([
    'D',
    'M',
    '1M',
    '1mo',
  ])('keeps calendar %s authoritative without inventing tick buckets', async (interval) => {
    const { instance, sockets, getBars } = helper()
    await instance.replace([spec()], 'price')
    await instance.bind(chart(), { ...context, interval })
    expect(getBars).toHaveBeenCalledWith(expect.objectContaining({ interval }))
    expect(sockets).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(getBars).toHaveBeenCalledTimes(2)
  })

  it('releases socket, history polling and callbacks on last removal and destruction', async () => {
    const { instance, sockets, getBars, onChange } = helper()
    await instance.replace([spec()], 'price')
    const target = chart()
    await instance.bind(target, context)
    sockets[0].open()
    instance.setVisibleHost(false)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(1)
    instance.remove('other')
    expect(sockets[0].closed).toBe(true)
    expect(sockets[0].sent.some((message) => message.action === 'unsubscribe')).toBe(true)
    instance.destroy()
    onChange.mockClear()
    sockets[0].tick(999, 180)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(1)
    expect(onChange).not.toHaveBeenCalled()
    expect(comparisonController(target).list()).toEqual([])
  })

  it('keeps an incoming live observation newer than a pending history repair', async () => {
    const { instance, sockets, getBars } = helper()
    await instance.replace([spec()], 'price')
    await instance.bind(chart(), context)
    sockets[0].open()
    const repair = deferred<Bar[]>()
    getBars.mockImplementationOnce(() => repair.promise)
    const refreshing = instance.refresh()
    await vi.advanceTimersByTimeAsync(0)
    sockets[0].tick(290, 195)
    repair.resolve([bar(60, 200), bar(120, 220), bar(180, 250, 90)])
    await refreshing
    expect(instance.rows(180)[0].close).toBe(290)
    sockets[0].tick(291, 200)
    expect(instance.rows(180)[0].close).toBe(291)
  })

  it('rejects duplicate sources and invalid context before replacing working ownership', async () => {
    const { instance, sockets } = helper()
    await instance.replace([spec()], 'price')
    const target = chart()
    await instance.bind(target, context)
    await expect(instance.replace([spec(), spec('duplicate')], 'price')).rejects.toThrow(
      'Duplicate'
    )
    await expect(instance.bind(chart(), { ...context, interval: 'bad' })).rejects.toThrow('Invalid')
    expect(instance.rows(180)[0].close).toBe(240)
    expect(comparisonController(target).list()).toHaveLength(1)
    expect(sockets[0].closed).toBe(false)
  })

  it('releases stream and timers when the chart is destroyed before the helper', async () => {
    const { instance, sockets, getBars } = helper()
    await instance.replace([spec()], 'price')
    const target = chart()
    await instance.bind(target, context)
    target.destroy()
    expect(sockets[0].closed).toBe(true)
    expect(instance.specs()).toEqual([spec()])
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(1)
  })

  it('releases every old resource when one comparison removal throws during rebind', async () => {
    const { instance, sockets, getBars } = helper()
    const target = chart()
    await instance.replace([spec('cash'), spec('venue', 'BSE')], 'price')
    await instance.bind(target, context)
    sockets[0].open()
    const failure = new Error('Renderer removal failed')
    vi.spyOn(comparisonController(target).list()[0], 'remove').mockImplementationOnce(() => {
      throw failure
    })
    const unsubscribe = vi.spyOn(sockets[0], 'send').mockImplementation(() => {
      throw new Error('Unsubscribe send failed')
    })
    await expect(instance.bind(chart(), context)).rejects.toBe(failure)
    expect(unsubscribe).toHaveBeenCalledTimes(2)
    expect(sockets[0].closed).toBe(true)
    const count = getBars.mock.calls.length
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(count)
  })

  it('closes the stream and other history owners after an unsubscribe send exception', async () => {
    const { instance, sockets, getBars } = helper()
    await instance.replace([spec('cash'), spec('venue', 'BSE')], 'price')
    await instance.bind(chart(), context)
    sockets[0].open()
    const failure = new Error('Socket send failed')
    vi.spyOn(sockets[0], 'send').mockImplementation(() => {
      throw failure
    })
    expect(() => instance.detach()).toThrow(failure)
    expect(sockets[0].closed).toBe(true)
    expect(instance.rows().every((row) => row.status === 'idle')).toBe(true)
    const count = getBars.mock.calls.length
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(count)
  })

  it('forgets a closing stream and definitions even when close reports an exception', async () => {
    const { instance, sockets, getBars, onChange } = helper()
    await instance.replace([spec()], 'price')
    await instance.bind(chart(), context)
    sockets[0].open()
    const stream = (instance as unknown as { socket: OpenAlgoWsFeed }).socket
    const close = stream.close.bind(stream)
    const failure = new Error('Stream close failed')
    const closing = vi.spyOn(stream, 'close').mockImplementation(() => {
      close()
      throw failure
    })
    expect(() => instance.destroy()).toThrow(failure)
    expect(sockets[0].closed).toBe(true)
    expect(instance.specs()).toEqual([])
    onChange.mockClear()
    instance.destroy()
    sockets[0].tick(999, 190)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(getBars).toHaveBeenCalledTimes(1)
    expect(onChange).not.toHaveBeenCalled()
    expect(closing).toHaveBeenCalledTimes(1)
  })

  it('returns resource counts to baseline through 100 repeated bindings', async () => {
    const { instance, sockets } = helper()
    const target = chart()
    await instance.replace([spec()], 'percent')
    const baseline = vi.getTimerCount()
    for (let index = 0; index < 100; index++) {
      await instance.bind(target, context)
      sockets.at(-1)!.open()
      instance.detach()
      expect(comparisonController(target).list()).toHaveLength(0)
    }
    expect(sockets).toHaveLength(100)
    expect(sockets.filter((socket) => !socket.closed)).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(baseline)
    expect(target.getState().series).toHaveLength(1)
  })
})
