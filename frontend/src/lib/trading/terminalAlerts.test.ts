import type { AlertController, Bar, Chart, SeriesApi } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart
  price: SeriesApi
  draw: DrawingController
  alerts: AlertController
  chartToolsReady: Promise<void>
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  buildChart(): void
  loadIndicators(): Promise<void>
  syncIndicators(): void
  beginReplayAt(index: number): Promise<void>
  loadReplaySubBars(): Promise<Bar[] | null>
}

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
})
const terminals: TradingTerminal[] = []
beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
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
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

async function mount() {
  const onToast = vi.fn()
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: { onReady() {}, onToast, onWsState() {}, onSymbolLoaded() {}, onLtp() {} },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  // Replace the custom-module network lookup, keeping built-in calculations real.
  state.loadIndicators = async () => {}
  state.sym = {
    symbol: 'NIFTY29SEP26FUT',
    exchange: 'NFO',
    name: 'Nifty Futures',
    lotsize: 65,
    lots: true,
    tick: 0.05,
    freezeQty: 1800,
    quoteOnly: false,
    productOptions: ['MIS', 'NRML'],
    product: 'MIS',
  }
  state.interval = '1m'
  state.rawBars = [bar(60, 100), bar(120, 100), bar(180, 100), bar(240, 100)]
  state.buildChart()
  await state.chartToolsReady
  return { terminal, state, onToast }
}

describe('terminal alert integration', () => {
  it('pauses alerts and order routes from symbol lookup through failed history', async () => {
    const { terminal, state, onToast } = await mount()
    state.alerts.add({
      id: 'price',
      title: 'Old market',
      source: { kind: 'price', price: 105 },
      policy: 'onTouch',
    })
    let metadata!: (value: object) => void
    const place = vi.fn()
    Object.assign(state, {
      rest: { getBars: async () => [] },
      api: () =>
        new Promise((resolve) => {
          metadata = resolve
        }),
      trade: { place },
    })
    const loading = terminal.loadSymbol({ symbol: 'OTHER', exchange: 'NSE' })
    const order = {
      symbol: 'OTHER',
      exchange: 'NSE',
      action: 'BUY',
      quantity: 1,
      product: 'MIS',
      pricetype: 'MARKET',
    } as const
    await expect(terminal.placeTicket(order)).rejects.toThrow(/history|loading/i)
    state.price.update(bar(240, 110))
    expect(onToast).not.toHaveBeenCalledWith('Old market', 'ok')
    metadata({ data: { symbol: 'OTHER', exchange: 'NSE' } })
    expect(await loading).toBe(false)
    await expect(terminal.placeTicket(order)).rejects.toThrow(/history|unavailable/i)
    expect(place).not.toHaveBeenCalled()
    state.price.update(bar(300, 120))
    expect(state.alerts.list()[0].state).toBe('armed')
  })

  it('opens shared dialogs over the viewport and releases them with the chart', async () => {
    const { terminal, state } = await mount()
    expect(await terminal.openAlerts()).toBe(true)
    expect(terminal.alertDialogOpen()).toBe(true)
    const root = document.querySelector<HTMLElement>('.oac-alert-host')!
    expect(root.parentElement).toBe(document.body)
    expect(root.style.position).toBe('fixed')
    expect(root.dataset.tradingDialogOpen).toBe('true')
    expect(root.textContent).toContain('Create alert')
    expect(await terminal.openAlerts({ kind: 'price', price: 105 })).toBe(true)
    expect(root.textContent).toContain('Bar close')
    terminal.destroy()
    expect(terminal.alertDialogOpen()).toBe(false)
    expect(root.isConnected).toBe(false)
    expect(state.alerts).toBeNull()
  })

  it('delivers live events locally and retains a triggered once record across reload', async () => {
    const a = await mount()
    expect(a.state.alerts).toBeDefined()
    a.state.alerts.add({
      id: 'price',
      title: 'Breakout',
      source: { kind: 'price', price: 105 },
      condition: 'crossingUp',
      policy: 'onTouch',
    })
    a.state.price.update(bar(240, 106))
    expect(a.onToast).toHaveBeenCalledWith('Breakout', 'ok')
    expect(JSON.parse(localStorage.getItem('oa-trading-alerts')!).alerts[0].state).toBe('triggered')
    a.terminal.destroy()
    const b = await mount()
    expect(b.state.alerts.list()[0]).toMatchObject({ id: 'price', state: 'triggered' })
    expect(b.onToast).not.toHaveBeenCalled()
    b.state.price.update(bar(300, 110))
    expect(b.onToast).not.toHaveBeenCalled()
  })

  it('preserves a study anchor through rebuild and reload without evaluating history', async () => {
    const a = await mount()
    const study = a.state.chart.addIndicator('ema', { length: 1 })
    a.state.syncIndicators()
    a.state.alerts.add({
      id: 'study',
      source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 105 },
      condition: 'crossingUp',
    })
    a.state.buildChart()
    await a.state.chartToolsReady
    expect(a.state.chart.indicators()[0].id).toBe(study.id)
    expect(a.state.alerts.list().map((item) => item.id)).toEqual(['study'])
    a.terminal.destroy()
    const b = await mount()
    expect(b.state.chart.indicators()[0].id).toBe(study.id)
    expect(b.state.alerts.list().map((item) => item.id)).toEqual(['study'])
    expect(b.onToast).not.toHaveBeenCalled()
    b.state.price.update(bar(240, 106))
    b.state.price.update(bar(300, 106))
    expect(b.state.alerts.list()[0].state).toBe('triggered')
  })

  it('keeps drawing anchors and unrelated alerts when applying a study template', async () => {
    const { terminal, state } = await mount()
    await terminal.setDrawTool('horizontal-line')
    const line = state.draw.add({
      id: 'level',
      tool: 'horizontal-line',
      paneIndex: 0,
      style: {},
      points: [{ time: 240, price: 105 }],
    })
    state.alerts.add({ id: 'drawing', source: { kind: 'drawing', drawingId: line.id } })
    state.alerts.add({ id: 'price', source: { kind: 'price', price: 110 } })
    const study = state.chart.addIndicator('ema', { length: 1 })
    state.alerts.add({
      id: 'study',
      source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 105 },
    })
    const incoming = [
      { indicatorId: 'ema', instanceId: study.id, settings: { length: 2 }, paneIndex: 0 },
    ]
    await terminal.applyIndicatorTemplate(incoming, 'append')
    expect(state.chart.indicators()[0].id).toBe(study.id)
    expect(state.chart.indicators()[1].id).not.toBe(study.id)
    expect(state.draw.get('level')).toBeDefined()
    expect(state.alerts.list().map((item) => item.id)).toEqual(['drawing', 'price', 'study'])
    expect(terminal.captureIndicatorTemplate().every((item) => !item.instanceId)).toBe(true)
    await terminal.applyIndicatorTemplate(incoming, 'replace')
    expect(state.draw.get('level')).toBeDefined()
    expect(state.alerts.list().map((item) => item.id)).toEqual(['drawing', 'price'])
  })

  it('restores drawings before their alerts and removes their alerts on deletion', async () => {
    const a = await mount()
    await a.terminal.setDrawTool('horizontal-line')
    a.state.draw.add({
      id: 'level',
      tool: 'horizontal-line',
      paneIndex: 0,
      style: {},
      points: [{ time: 240, price: 105 }],
    })
    a.state.alerts.add({ id: 'drawing', source: { kind: 'drawing', drawingId: 'level' } })
    a.state.buildChart()
    await a.state.chartToolsReady
    expect(a.state.draw.get('level')).toBeDefined()
    expect(a.state.alerts.list().map((item) => item.id)).toEqual(['drawing'])
    a.terminal.destroy()
    const b = await mount()
    expect(b.state.draw.get('level')).toBeDefined()
    expect(b.state.alerts.list().map((item) => item.id)).toEqual(['drawing'])
    expect(b.onToast).not.toHaveBeenCalled()
    b.state.draw.remove('level')
    expect(b.state.alerts.list()).toEqual([])
  })

  it('suppresses evaluation throughout replay selection, loading, playback and resume', async () => {
    const { terminal, state, onToast } = await mount()
    state.alerts.add({ id: 'price', source: { kind: 'price', price: 105 }, policy: 'onTouch' })
    terminal.startReplay()
    state.price.update(bar(240, 110))
    expect(onToast).not.toHaveBeenCalled()
    terminal.cancelReplayPick()
    let finish!: (bars: null) => void
    state.loadReplaySubBars = () =>
      new Promise((resolve) => {
        finish = resolve
      })
    const loading = state.beginReplayAt(0)
    state.price.update(bar(240, 120))
    expect(onToast).not.toHaveBeenCalled()
    finish(null)
    await loading
    terminal.replayStep(3)
    terminal.stopReplay()
    expect(onToast).not.toHaveBeenCalled()
    expect(state.alerts.list()[0].state).toBe('armed')
    state.price.update(bar(300, 110))
    expect(state.alerts.list()[0].state).toBe('triggered')
  })
})
