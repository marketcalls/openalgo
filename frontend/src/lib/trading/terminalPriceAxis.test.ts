/**
 * The price scale's choices live in the pane's chart settings, so they come
 * back after a rebuild and in a workspace, and a pane saved before they
 * existed opens exactly as it did.
 */
import type { Bar, ContextMenuEvent } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SymbolView } from './terminal'
import { type TerminalContextMenu, TradingTerminal } from './terminal'

type State = {
  chartToolsReady: Promise<void>
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  chart: { priceAxisPlacement(pane: number, id: string): { side: string } | null } & Record<
    string,
    unknown
  >
  buildChart(): void
  loadIndicators(): Promise<void>
  showContextMenu(event: ContextMenuEvent): void
}

const MONDAY = Date.UTC(2026, 8, 21, 3, 45) / 1000
const bars: Bar[] = [
  ...[100, 101, 103].map((close, i) => ({
    time: MONDAY + i * 60,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
  })),
  ...[110, 112, 111].map((close, i) => ({
    time: MONDAY + 86_400 + i * 60,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
  })),
]

const terminals: TradingTerminal[] = []

beforeEach(() => {
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
})

/** A pane's storage, holding what an install from before this change saved. */
function prefs(settings: Record<string, unknown>) {
  const values = new Map<string, string>([
    ['oa-trading-p0-chartsettings', JSON.stringify(settings)],
  ])
  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value)
    }),
  }
  return { values, storage }
}

async function mount(storage: Pick<Storage, 'getItem' | 'setItem'>) {
  const menus: TerminalContextMenu[] = []
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    storageKey: 'oa-trading-p0',
    preferences: storage,
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast() {},
      onContextMenu: (menu) => menus.push(menu),
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  state.loadIndicators = async () => {}
  state.sym = {
    symbol: 'SBIN',
    exchange: 'NSE',
    name: 'State Bank of India',
    lotsize: 1,
    lots: false,
    tick: 0.05,
    freezeQty: 0,
    quoteOnly: false,
    productOptions: ['MIS', 'CNC'],
    product: 'MIS',
  }
  state.interval = '1m'
  state.rawBars = bars
  state.buildChart()
  await state.chartToolsReady
  // The saved settings are replayed through a lazy import; let it land.
  await new Promise((resolve) => setTimeout(resolve, 0))
  return { terminal, state, menus }
}

const saved = (values: Map<string, string>) =>
  JSON.parse(values.get('oa-trading-p0-chartsettings') ?? '{}') as Record<string, unknown>

describe('price scale settings on a pane', () => {
  it('opens a pane saved before the price scale menu exactly as before', async () => {
    const { values, storage } = prefs({ 'scales.mode': 'logarithmic' })
    const before = new Map(values)
    const { terminal } = await mount(storage)

    // Nothing is written back, and nothing new is switched on.
    expect(storage.setItem).not.toHaveBeenCalledWith(
      'oa-trading-p0-chartsettings',
      expect.anything()
    )
    expect(values.get('oa-trading-p0-chartsettings')).toBe(
      before.get('oa-trading-p0-chartsettings')
    )
    const menu = terminal.priceAxisMenu()
    expect(menu?.mode).toBe('logarithmic')
    expect(menu?.side).toBe('right')
    for (const level of menu?.levels ?? []) {
      if (level.kind === 'lastPrice') expect(level).toMatchObject({ line: true, tag: true })
      else expect(level).toMatchObject({ line: false, tag: false })
    }
    const settings = await terminal.chartSettings()
    expect(settings?.values['levels.previousClose']).toBe('off')
    expect(settings?.values['priceAxis.side']).toBe('right')
  })

  it('keeps every choice with the pane, and drops one set back to its default', async () => {
    const { values, storage } = prefs({})
    const { terminal } = await mount(storage)

    await terminal.priceAxisCommand({ type: 'mode', mode: 'percentage' })
    await terminal.priceAxisCommand({ type: 'invert' })
    await terminal.priceAxisCommand({ type: 'level', kind: 'previousClose', half: 'tag', on: true })
    await terminal.priceAxisCommand({ type: 'side', side: 'left' })
    expect(saved(values)).toMatchObject({
      'scales.mode': 'percentage',
      'scales.inverted': true,
      'levels.previousClose': 'tag',
      'priceAxis.side': 'left',
    })

    await terminal.priceAxisCommand({ type: 'reset' })
    await terminal.priceAxisCommand({
      type: 'level',
      kind: 'previousClose',
      half: 'tag',
      on: false,
    })
    await terminal.priceAxisCommand({ type: 'side', side: 'right' })
    const after = saved(values)
    for (const key of ['scales.mode', 'scales.inverted', 'levels.previousClose', 'priceAxis.side'])
      expect(after).not.toHaveProperty(key)
  })

  it('brings the levels and the side back when the chart is rebuilt', async () => {
    const { storage } = prefs({ 'levels.sessionHigh': 'both', 'priceAxis.side': 'left' })
    const { terminal, state } = await mount(storage)
    const check = () => {
      const chart = state.chart as unknown as {
        primaryPaneIndex(): number
        priceAxisPlacement(pane: number, id: string): { side: string } | null
      }
      expect(chart.priceAxisPlacement(chart.primaryPaneIndex(), 'right')?.side).toBe('left')
      const high = terminal.priceAxisMenu()?.levels.find((level) => level.kind === 'sessionHigh')
      expect(high).toMatchObject({ line: true, tag: true, available: true })
    }
    check()
    // A theme or chart type switch builds a new chart.
    state.buildChart()
    await state.chartToolsReady
    check()
  })

  it('saves them into a workspace with the rest of the pane settings', async () => {
    const { storage } = prefs({ 'levels.bid': 'line' })
    const { terminal, state } = await mount(storage)
    vi.spyOn(
      state.chart as unknown as { getDataContext(): unknown },
      'getDataContext'
    ).mockReturnValue({ symbol: 'SBIN', exchange: 'NSE', interval: '1m' })
    const pane = terminal.captureWorkspacePane('p0') as { settings?: Record<string, unknown> }
    expect(pane.settings).toMatchObject({ 'levels.bid': 'line' })
  })
})

describe('auto-fit off after a rebuild', () => {
  it('holds a fitted range rather than the blank placeholder', async () => {
    const { storage } = prefs({ 'scales.autoScale': false })
    const { state } = await mount(storage)
    const chart = state.chart as unknown as {
      applySize(width: number, height: number): void
      priceAxisState(pane: number, id: string): { autoFit: boolean; scaled: boolean } | null
    }
    // Nothing has been measured yet, so nothing is pinned yet.
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ autoFit: true, scaled: false })
    // The pane gets a size, as it does on screen, and the first frame fits the data.
    chart.applySize(800, 600)
    await vi.waitFor(() => expect(chart.priceAxisState(0, 'right')?.autoFit).toBe(false))
    expect(chart.priceAxisState(0, 'right')?.scaled).toBe(true)
  })
})

describe('right-click on the price scale', () => {
  it('opens the scale menu rather than the order menu', async () => {
    const { storage } = prefs({})
    const { state, menus } = await mount(storage)
    state.showContextMenu({
      paneIndex: 0,
      point: { x: 790, y: 200 },
      price: 105,
      time: null,
      index: null,
      target: { kind: 'price-scale', id: null, side: 'right', scaleId: 'right' },
      preventDefault() {},
    })
    expect(menus).toHaveLength(1)
    expect(menus[0].axis).toBeDefined()
    expect(menus[0].items).toEqual([])
    expect(menus[0].alert).toBeUndefined()

    // Anywhere else on the plot is still the chart menu.
    state.showContextMenu({
      paneIndex: 0,
      point: { x: 300, y: 200 },
      price: 105,
      time: null,
      index: null,
      target: { kind: 'empty', id: null },
      preventDefault() {},
    })
    expect(menus[1].axis).toBeUndefined()
  })
})
