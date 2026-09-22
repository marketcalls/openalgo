import { type Bar, createChart, ReplayGroup, type SeriesApi } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'

const terminals: TradingTerminal[] = []
const bar = (time: number, close: number): Bar => ({
  time,
  open: close - 1,
  high: close + 1,
  low: close - 2,
  close,
  volume: 100,
})

beforeEach(() => {
  localStorage.clear()
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})
afterEach(() => {
  vi.restoreAllMocks()
  for (const terminal of terminals.splice(0)) terminal.destroy()
})

describe('terminal replay restoration failure isolation', () => {
  it('resumes data and restores live buffers after a chart callback fails, preserving the first error', async () => {
    const container = document.createElement('div')
    const replayChanged = vi.fn()
    const terminal = new TradingTerminal({
      apiKey: 'fixture',
      wsUrl: 'ws://fixture.invalid',
      container,
      legendEl: document.createElement('div'),
      getTheme: () => ({ mode: 'dark', appMode: 'live' }),
      callbacks: {
        onReady() {},
        onToast() {},
        onWsState() {},
        onSymbolLoaded() {},
        onLtp() {},
        onReplayChange: replayChanged,
      },
    })
    terminals.push(terminal)
    const chart = createChart(container, {
      shortcuts: false,
      timeNavigator: false,
      raf: {
        schedule: (callback) => {
          callback()
          return 1
        },
        cancel() {},
      },
    })
    chart.applySize(800, 600)
    const price = chart.addSeries('candlestick'),
      volume = chart.addSeries('histogram', { priceScaleId: '' })
    const data = { setPaused: vi.fn(), destroy() {} }
    const state = terminal as unknown as { rawBars: Bar[]; setPriceData(): void; price: SeriesApi }
    Object.assign(terminal, {
      chart,
      price,
      volume,
      data,
      interval: '1m',
      rawBars: [bar(60, 100), bar(120, 101), bar(180, 102)],
    })
    state.setPriceData()
    terminal.setWorkspaceReplayLocked(true)
    const prepared = await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: new AbortController().signal,
    })
    terminal.setReplayParticipation(1, true)
    const group = new ReplayGroup([prepared.member], { startTime: 180 })
    state.rawBars = [...state.rawBars, bar(240, 150)]
    expect(price.getData().at(-1)?.close).toBe(101)
    group.destroy()

    const first = new Error('Autoscale callback failed'),
      second = new Error('Replay callback failed')
    vi.spyOn(chart, 'setAutoScale').mockImplementationOnce(() => {
      throw first
    })
    replayChanged.mockImplementationOnce(() => {
      throw second
    })
    let thrown: unknown
    try {
      terminal.restoreReplayMember(1)
    } catch (error) {
      thrown = error
    }
    expect(thrown).toBe(first)
    expect(data.setPaused).toHaveBeenLastCalledWith(false)
    expect(price.getData().map((row) => row.close)).toEqual([100, 101, 102, 150])
    expect(volume.getData()).toHaveLength(4)
    expect(replayChanged).toHaveBeenLastCalledWith(null)
    expect(terminal.replayActive()).toBe(false)
    expect(terminal.replayLoadingBars()).toBe(false)
    terminal.setWorkspaceReplayLocked(false)
  })
})
