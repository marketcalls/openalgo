/**
 * The drawing controls the rail, the properties bar and the right-click menu
 * drive, against the real draw tier on a real chart.
 *
 * Order lines are not drawings. Every bulk action here (select all, remove
 * all, the eraser, copy and cut) is checked to leave one alone, because a
 * trader who clears their levels must never find a working order's line gone
 * from the chart.
 */
import type { Bar, Chart, PriceLine } from 'openalgo-charts'
import { type DrawingController, toolCursor } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  type DrawStats,
  type SymbolView,
  type TerminalContextMenu,
  TradingTerminal,
} from './terminal'

type State = {
  chart: Chart
  draw: DrawingController
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  chartToolsReady: Promise<void>
  orderLines: Map<string, { line: PriceLine; order: unknown }>
  buildChart(): void
  loadIndicators(): Promise<void>
  showContextMenu(event: unknown): void
}

const terminals: TradingTerminal[] = []

beforeEach(() => {
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
  window.getSelection()?.removeAllRanges()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function mount(symbol = 'INFY') {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const toasts: string[] = []
  const menus: TerminalContextMenu[] = []
  const removeAll: { count: number; symbol: string }[] = []
  const stats: DrawStats[] = []
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
    storageKey: `oa-trading-${symbol}`,
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast: (msg) => toasts.push(msg),
      onContextMenu: (menu) => menus.push(menu),
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
      onDrawRemoveAll: (req) => removeAll.push(req),
      onDrawChange: (s) => stats.push(s),
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  state.loadIndicators = async () => {}
  state.sym = {
    symbol,
    exchange: 'NSE',
    name: symbol,
    lotsize: 1,
    lots: false,
    tick: 0.05,
    freezeQty: 1,
    quoteOnly: false,
    productOptions: ['MIS', 'CNC'],
    product: 'MIS',
  }
  state.interval = '5m'
  state.rawBars = [60, 120, 180, 240].map((time) => ({
    time,
    open: 1500,
    high: 1510,
    low: 1490,
    close: 1500,
    volume: 100,
  }))
  state.buildChart()
  await state.chartToolsReady
  await terminal.setDrawTool(null)
  return { terminal, state, container, toasts, menus, removeAll, stats }
}

function line(state: State, tool = 'trend-line', extra: Record<string, unknown> = {}) {
  return state.draw.add({
    tool,
    paneIndex: 0,
    points: [
      { time: 60, price: 1490 },
      { time: 240, price: 1510 },
    ],
    style: {},
    ...extra,
  }).id
}

/** A working order's line, put on the chart the way the order book does. */
function orderLine(state: State) {
  const priceLine = state.chart.addPriceLine({ price: 1500, color: '#26a69a', id: 'order:o1' })
  state.orderLines.set('o1', { line: priceLine, order: {} })
  return vi.spyOn(state.chart, 'removePrimitive')
}

describe('the armed tool follows the pointer', () => {
  it('shows the tool glyph as the cursor and gives the pointer back after', async () => {
    const { terminal, container } = await mount()

    await terminal.setDrawTool('trend-line')
    expect(container.style.getPropertyValue('--tool-cursor')).toBe(toolCursor('trend-line'))

    await terminal.setDrawTool(null)
    expect(container.style.getPropertyValue('--tool-cursor')).toBe('')
  })

  it('gives the pointer back when the tool ends by itself after a placement', async () => {
    const { terminal, state, container } = await mount()
    await terminal.setDrawTool('trend-line')

    state.draw.setTool(null)

    expect(container.style.getPropertyValue('--tool-cursor')).toBe('')
    expect(terminal.drawStats().tool).toBeNull()
  })
})

describe('eraser', () => {
  it('is armed and ended like a tool, and reported as one', async () => {
    const { terminal, state, container } = await mount()

    await terminal.setDrawTool('eraser')
    expect(state.draw.erasing()).toBe(true)
    expect(terminal.drawStats().tool).toBe('eraser')
    expect(container.style.getPropertyValue('--tool-cursor')).toBe('crosshair')

    await terminal.setDrawTool('trend-line')
    expect(state.draw.erasing()).toBe(false)
    expect(state.draw.activeTool()).toBe('trend-line')

    await terminal.setDrawTool('eraser')
    await terminal.setDrawTool(null)
    expect(state.draw.erasing()).toBe(false)
    expect(terminal.drawStats().tool).toBeNull()
  })
})

describe('select all and remove all', () => {
  it('counts what each would take: hidden and locked are removable, not selectable', async () => {
    const { terminal, state } = await mount()
    const free = line(state)
    line(state, 'trend-line', { locked: true })
    line(state, 'trend-line', { visible: false })

    expect(terminal.drawStats()).toMatchObject({ removable: 3, selectable: 1 })
    terminal.selectAllDrawings()
    expect(state.draw.selection()).toEqual([free])
  })

  it('asks before removing everything, then removes it as one undo step', async () => {
    const { terminal, state, removeAll } = await mount()
    line(state)
    line(state)
    const removed = orderLine(state)

    terminal.requestRemoveAllDrawings()
    expect(removeAll).toEqual([{ count: 2, symbol: 'INFY' }])
    expect(state.draw.drawings()).toHaveLength(2)

    terminal.removeDrawings(true)
    expect(state.draw.drawings()).toHaveLength(0)
    expect(state.orderLines.size).toBe(1)
    expect(removed).not.toHaveBeenCalled()

    terminal.undoDraw()
    expect(state.draw.drawings()).toHaveLength(2)
  })

  it('asks nothing when there is nothing to remove', async () => {
    const { terminal, removeAll } = await mount()
    terminal.requestRemoveAllDrawings()
    expect(removeAll).toEqual([])
  })
})

describe('actions on the selection', () => {
  it('hides it, says where to show it again, and undoes', async () => {
    const { terminal, state, toasts } = await mount()
    const id = line(state)
    state.draw.select(id)

    terminal.hideSelectedDrawings()

    expect(state.draw.get(id)?.visible).toBe(false)
    expect(toasts.at(-1)).toBe('Drawing hidden. Show it again from the Objects panel.')
    terminal.undoDraw()
    expect(state.draw.get(id)?.visible).not.toBe(false)
  })

  it('duplicates and orders it', async () => {
    const { terminal, state } = await mount()
    const first = line(state)
    const second = line(state)
    state.draw.select(second)

    terminal.orderSelectedDrawings('back')
    expect(state.draw.drawings().map((d) => d.id)[0]).toBe(second)

    terminal.duplicateSelectedDrawings()
    expect(state.draw.drawings()).toHaveLength(3)
    expect(state.draw.selection()).not.toContain(first)
  })

  it('writes fill only to the tools that have one, as one undo step', async () => {
    const { terminal, state } = await mount()
    const trend = line(state)
    const box = line(state, 'rectangle')
    state.draw.select([trend, box])

    const before = state.draw.get(box)?.style.fillOpacity

    terminal.setSelectedDrawingSettings({ 'style.fill': true, 'style.fillOpacity': 0.3 })

    expect(state.draw.get(box)?.style).toMatchObject({ fill: true, fillOpacity: 0.3 })
    expect(state.draw.get(trend)?.style.fill).toBeUndefined()
    terminal.undoDraw()
    expect(state.draw.get(box)?.style.fillOpacity).toBe(before)
  })

  it('describes the selection for the properties bar', async () => {
    const { terminal, state } = await mount()
    const trend = line(state)
    state.draw.select(trend)
    expect(terminal.drawSelection()).toMatchObject({
      name: 'Trend Line',
      fill: null,
      extend: { left: false, right: false },
      levels: false,
    })

    terminal.setSelectedDrawingSettings({ 'style.extendRight': true })
    expect(terminal.drawSelection()?.extend).toEqual({ left: false, right: true })

    const fib = line(state, 'fib-retracement')
    state.draw.select(fib)
    expect(terminal.drawSelection()).toMatchObject({ name: 'Fib Retracement', levels: true })
  })

  it('edits a ladder’s levels as one undo step, and resets to the tool’s own', async () => {
    const { terminal, state } = await mount()
    const fib = line(state, 'fib-retracement')
    state.draw.select(fib)
    const levels = terminal.drawLevels()
    expect(levels?.levels.map((l) => l.ratio)).toEqual([0, 0.236, 0.382, 0.5, 0.618, 0.786, 1])
    expect(levels?.label(0.618)).toBe('61.8%')

    terminal.setDrawLevels([{ ratio: 0.5, label: 'Half' }])
    expect(state.draw.get(fib)?.style.levels).toEqual([{ ratio: 0.5, label: 'Half' }])

    terminal.undoDraw()
    expect(state.draw.get(fib)?.style.levels).toHaveLength(7)
    expect(terminal.drawLevels()?.defaults).toHaveLength(7)
  })
})

describe('copy, cut and paste', () => {
  it('copies on one chart and pastes on another', async () => {
    const a = await mount('INFY')
    const b = await mount('TCS')
    const id = line(a.state)
    a.state.draw.select(id)

    expect(a.terminal.handleDrawKey({ key: 'c', ctrlKey: true })).toBe(true)
    await vi.waitFor(() => expect(a.toasts.at(-1)).toMatch(/^Drawing copied\./))

    expect(await b.terminal.pasteDrawings()).toBe(1)
    expect(b.state.draw.drawings()).toHaveLength(1)
    expect(a.state.draw.drawings()).toHaveLength(1)
  })

  it('cuts only once the copy has landed, as one undo step', async () => {
    const { terminal, state } = await mount()
    const id = line(state)
    state.draw.select(id)
    const removed = orderLine(state)

    expect(await terminal.cutDrawings()).toBe(true)
    expect(state.draw.drawings()).toHaveLength(0)
    expect(state.orderLines.size).toBe(1)
    expect(removed).not.toHaveBeenCalled()
    terminal.undoDraw()
    expect(state.draw.drawings()).toHaveLength(1)
  })

  it('leaves Ctrl+C to the page when text is selected', async () => {
    const { terminal, state } = await mount()
    state.draw.select(line(state))
    const text = document.createElement('p')
    text.textContent = 'Order 260930000123'
    document.body.appendChild(text)
    window.getSelection()?.selectAllChildren(text)

    expect(terminal.handleDrawKey({ key: 'c', ctrlKey: true })).toBe(false)
  })

  it('leaves Ctrl+C to the page when no drawing is selected', async () => {
    const { terminal, state } = await mount()
    line(state)
    expect(terminal.handleDrawKey({ key: 'c', ctrlKey: true })).toBe(false)
  })
})

describe('the right-click menu', () => {
  const menuAt = (state: State, target: Record<string, unknown>) =>
    state.showContextMenu({
      preventDefault() {},
      target,
      point: { x: 50, y: 50 },
      paneIndex: 0,
      price: 1500,
      time: 120,
    })

  it('names the drawing that was right-clicked', async () => {
    const { state, menus } = await mount()
    const id = line(state)
    menuAt(state, { kind: 'drawing', id: `draw:${id}` })
    expect(menus.at(-1)?.drawing).toMatchObject({ id, removable: 1 })
  })

  it('offers nothing to act on over empty space, only the counts', async () => {
    const { state, menus } = await mount()
    line(state)
    menuAt(state, { kind: 'none' })
    expect(menus.at(-1)?.drawing).toMatchObject({ id: null, removable: 1 })
  })

  it('treats an order line as not a drawing', async () => {
    const { state, menus } = await mount()
    orderLine(state)
    menuAt(state, { kind: 'priceLine', id: 'order:o1' })
    expect(menus.at(-1)?.drawing?.id).toBeNull()
  })
})

describe('magnet', () => {
  it('takes the three modes and keeps the old switch meaning true and false', async () => {
    const { terminal, state } = await mount()

    terminal.setMagnet('weak')
    expect(state.draw.magnetMode()).toBe('weak')
    expect(terminal.drawStats()).toMatchObject({ magnet: true, magnetMode: 'weak' })
    expect(localStorage.getItem('oa-trading-INFY-magnet-mode')).toBe('weak')

    terminal.setMagnet(false)
    expect(state.draw.magnetMode()).toBe('off')
    terminal.setMagnet(true)
    expect(state.draw.magnetMode()).toBe('strong')
  })
})
