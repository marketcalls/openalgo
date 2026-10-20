import type { Bar } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartStateView } from './chartState'
import { type TerminalCallbacks, TradingTerminal } from './terminal'

// The terminal reports each load to the pane's overlay instead of toasting it.
// Only canvas painting, the socket and the broker boundary are replaced.
const terminals: TradingTerminal[] = []
const bar = (time: number, close: number): Bar => ({
  time,
  open: close - 1,
  high: close + 2,
  low: close - 2,
  close,
  volume: 100,
})
const bars = [bar(60, 100), bar(120, 101), bar(180, 102), bar(240, 103)]

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal(
    'WebSocket',
    class {
      readyState = 0
      send() {}
      close() {
        this.readyState = 3
      }
    }
  )
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})

afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function mount(getBars: () => Promise<Bar[]>) {
  const states: ChartStateView[] = []
  const callbacks: TerminalCallbacks = {
    onReady() {},
    onToast: vi.fn(),
    onWsState() {},
    onSymbolLoaded() {},
    onLtp() {},
    onChartState: (state) => states.push(state),
  }
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks,
  })
  terminals.push(terminal)
  Object.assign(terminal, { rest: { getBars }, cachedBars: null, data: null, interval: '5m' })
  vi.spyOn(terminal, 'api').mockResolvedValue({ data: {} })
  return { terminal, states, callbacks }
}

const pick = { symbol: 'SBIN', exchange: 'NSE' }

describe('chart load state', () => {
  it('reports a failed load to the overlay rather than a toast, and Try again repeats it', async () => {
    const getBars = vi
      .fn<() => Promise<Bar[]>>()
      .mockRejectedValueOnce(new Error('/api/v1/history failed (500): Broker session expired'))
      .mockResolvedValue(bars)
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { terminal, states, callbacks } = mount(getBars)

    expect(await terminal.loadSymbol(pick)).toBe(false)
    expect(states.map((s) => s.kind)).toEqual(['loading', 'error'])
    expect(states[1]).toMatchObject({
      symbol: 'SBIN',
      interval: '5m',
      message: 'Broker session expired',
    })
    expect(callbacks.onToast).not.toHaveBeenCalled()

    terminal.retryLoad()
    await vi.waitFor(() => expect(states.at(-1)?.kind).toBe('ready'))
    expect(states.map((s) => s.kind)).toEqual(['loading', 'error', 'loading', 'ready'])
    expect(getBars).toHaveBeenCalledTimes(2)
    expect(terminal.liveChart()).not.toBeNull()
  })

  it('reports a reply with no bars as no data for that symbol and interval', async () => {
    const { terminal, states, callbacks } = mount(async () => [])
    expect(await terminal.loadSymbol(pick)).toBe(false)
    expect(states.at(-1)).toEqual({ kind: 'empty', symbol: 'SBIN', interval: '5m' })
    expect(callbacks.onToast).not.toHaveBeenCalled()
  })

  it('says nothing for a silent load its caller falls back from', async () => {
    const { terminal, states } = mount(async () => [])
    expect(await terminal.loadSymbol(pick, { silent: true })).toBe(false)
    expect(states.map((s) => s.kind)).toEqual(['loading', 'ready'])
  })

  it('lets only the newest of two overlapping loads speak', async () => {
    let first!: (value: Bar[]) => void
    const getBars = vi
      .fn<() => Promise<Bar[]>>()
      .mockReturnValueOnce(
        new Promise((resolve) => {
          first = resolve
        })
      )
      .mockResolvedValue(bars)
    const { terminal, states } = mount(getBars)
    const older = terminal.loadSymbol(pick)
    await vi.waitFor(() => expect(getBars).toHaveBeenCalledOnce())
    const newer = terminal.loadSymbol({ symbol: 'INFY', exchange: 'NSE' })
    await newer
    first([])
    await older
    expect(states.map((s) => s.kind)).toEqual(['loading', 'loading', 'ready'])
  })
})

describe('reduced motion', () => {
  const reduce = (on: boolean) =>
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: on && query === '(prefers-reduced-motion: reduce)',
        addEventListener() {},
        removeEventListener() {},
      }))
    )

  it('builds the chart without the zoom glide and opens saved state unchanged', async () => {
    reduce(false)
    const normal = mount(async () => bars)
    expect(await normal.terminal.loadSymbol(pick)).toBe(true)
    reduce(true)
    const calm = mount(async () => bars)
    expect(await calm.terminal.loadSymbol(pick)).toBe(true)

    const glide = (terminal: TradingTerminal) =>
      (terminal.liveChart() as unknown as { _animZoom: boolean })._animZoom
    expect(glide(normal.terminal)).toBe(true)
    expect(glide(calm.terminal)).toBe(false)
    // A motion preference is the machine's, not the chart's: nothing about it
    // reaches what a workspace saves, so a saved pane reads back the same.
    expect(calm.terminal.captureWorkspacePane('p0')).toEqual(
      normal.terminal.captureWorkspacePane('p0')
    )
  })
})
