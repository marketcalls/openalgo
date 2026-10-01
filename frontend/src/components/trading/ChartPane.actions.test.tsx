/**
 * The chart-area rows of the right-click menu: the study rows, Alerts..., and
 * the order rows for the symbol on the chart. The order rows go through the
 * dock's own functions (orderActions.ts) to the session routes, mocked here
 * at the API, so what is asserted is what would reach the server.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SymbolView, TerminalContextMenu, TerminalOptions } from '@/lib/trading/terminal'
import { act, cleanup, fireEvent, render, waitFor } from '@/test/test-utils'
import { ChartPane } from './ChartPane'
import type { DockOrder, DockPosition } from './dock/blotter'
import { type ChartOrderBridge, ChartOrderBridgeContext } from './dock/chartOrderBridge'

const fake = vi.hoisted(() => ({
  owners: [] as {
    options: TerminalOptions
    resolve(): void
    placeTicket: ReturnType<typeof vi.fn>
    openAlerts: ReturnType<typeof vi.fn>
    openIndicatorSettings: ReturnType<typeof vi.fn>
    removeIndicatorById: ReturnType<typeof vi.fn>
    moveStudyPane: ReturnType<typeof vi.fn>
    setStudyPaneCollapsed: ReturnType<typeof vi.fn>
    historyPress: ReturnType<typeof vi.fn>
  }[],
  toast: vi.fn(),
  api: {
    cancelOrder: vi.fn(),
    closePosition: vi.fn(),
  },
}))
vi.mock('@/utils/toast', () => ({
  showToast: { success: fake.toast, error: fake.toast, info: fake.toast },
}))
vi.mock('@/api/trading', () => ({ tradingApi: fake.api }))
// The ticket itself is tested on its own; here only what it was opened with.
vi.mock('./PlaceOrderDialog', () => ({
  PlaceOrderDialog: (p: Record<string, unknown>) => (
    <div role="dialog" aria-label="Order ticket">
      {`${p.action} ${p.quantity} ${p.product} ${p.priceType} lot ${p.lotSize}`}
    </div>
  ),
}))
vi.mock('@/lib/trading/terminal', () => ({
  TradingTerminal: class {
    options: TerminalOptions
    resolve!: () => void
    pending = new Promise<void>((resolve) => {
      this.resolve = resolve
    })
    destroy = vi.fn()
    setArmed = vi.fn()
    setWorkspaceTransitionLocked = vi.fn()
    setLinkGroup = vi.fn()
    applyTheme = vi.fn()
    placeTicket = vi.fn(async () => ({ orderId: 'T1' }))
    openAlerts = vi.fn(async () => true)
    openIndicatorSettings = vi.fn()
    removeIndicatorById = vi.fn()
    moveStudyPane = vi.fn(() => true)
    setStudyPaneCollapsed = vi.fn(() => true)
    historyPress = vi.fn(() => true)
    replayPickingBar = () => false
    replayLoadingBars = () => false
    gridState = () => ({ vertical: true, horizontal: true })
    volumeVisible = () => true
    drawStats = () => ({
      count: 0,
      canUndo: true,
      canRedo: false,
      hasSelection: false,
      magnet: false,
      stay: false,
      tool: null,
      shortcuts: {},
    })
    constructor(options: TerminalOptions) {
      this.options = options
      fake.owners.push(this as never)
    }
    init() {
      this.options.callbacks.onReady({
        intervalGroups: [],
        interval: '5m',
        chartType: 'candlestick',
      })
      return this.pending
    }
  },
}))

const NIFTY_FUT: SymbolView = {
  symbol: 'NIFTY30OCT26FUT',
  exchange: 'NFO',
  name: 'NIFTY',
  lots: true,
  lotsize: 65,
  tick: 0.1,
  freezeQty: 1755,
  quoteOnly: false,
  productOptions: ['MIS', 'NRML'],
  product: 'NRML',
}
const position = (over: Partial<DockPosition> = {}): DockPosition => ({
  symbol: NIFTY_FUT.symbol,
  exchange: 'NFO',
  product: 'NRML',
  quantity: 260,
  average_price: 25000,
  ltp: 25010,
  pnl: 2600,
  ...over,
})
const order = (over: Partial<DockOrder> = {}): DockOrder => ({
  orderid: 'O1',
  symbol: NIFTY_FUT.symbol,
  exchange: 'NFO',
  action: 'SELL',
  product: 'NRML',
  pricetype: 'LIMIT',
  quantity: 65,
  price: 25100,
  trigger_price: 0,
  order_status: 'open',
  timestamp: '',
  ...over,
})
const menu = (over: Partial<TerminalContextMenu> = {}): TerminalContextMenu => ({
  x: 100,
  y: 100,
  items: [],
  profile: null,
  ...over,
})

function bridgeWith(book: { orders: DockOrder[]; positions: DockPosition[] }) {
  const bridge: ChartOrderBridge & {
    actions: { refuse: ReturnType<typeof vi.fn>; refresh: ReturnType<typeof vi.fn> }
  } = {
    book: () => book,
    actions: { appMode: 'live', refuse: vi.fn(() => false), refresh: vi.fn() },
    freshPositions: vi.fn(async () => book.positions),
  }
  return bridge
}

async function mount(bridge: ChartOrderBridge | null, appMode: 'live' | 'analyzer' = 'live') {
  if (bridge) bridge.actions.appMode = appMode
  const view = render(
    <ChartOrderBridgeContext.Provider value={{ current: bridge }}>
      <ChartPane paneId="p1" apiKey="fixture" wsUrl="ws://fixture.invalid" />
    </ChartOrderBridgeContext.Provider>
  )
  const owner = fake.owners[0]
  await act(async () => owner.resolve())
  act(() => owner.options.callbacks.onSymbolLoaded(NIFTY_FUT))
  return { view, owner }
}

beforeEach(() => {
  fake.owners.length = 0
  fake.toast.mockClear()
  fake.api.cancelOrder.mockReset().mockResolvedValue({ status: 'success' })
  fake.api.closePosition.mockReset().mockResolvedValue({ status: 'success' })
})
afterEach(cleanup)

describe('order rows in the chart menu', () => {
  it('shows none when the symbol is flat and has no working order', async () => {
    const bridge = bridgeWith({
      orders: [order({ order_status: 'complete' }), order({ symbol: 'OTHER' })],
      positions: [position({ quantity: 0 }), position({ symbol: 'OTHER' })],
    })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    expect(view.queryByRole('button', { name: /^Cancel orders/ })).toBeNull()
    expect(view.queryByRole('button', { name: 'Close position' })).toBeNull()
    expect(view.queryByRole('button', { name: /^Close half/ })).toBeNull()
    expect(view.queryByRole('button', { name: /^Reverse/ })).toBeNull()
  })

  it('shows none without the dock', async () => {
    const { view, owner } = await mount(null)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    expect(view.queryByRole('button', { name: 'Close position' })).toBeNull()
  })

  it('closes through the dock route only after a confirmation naming side, quantity and product', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position()] })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))

    expect(fake.api.closePosition).not.toHaveBeenCalled()
    const ask = view.getByRole('alertdialog')
    expect(ask).toHaveTextContent(`Close ${NIFTY_FUT.symbol} NRML position?`)
    expect(ask).toHaveTextContent(`SELL 260 (4 lots) ${NIFTY_FUT.symbol} on NFO, product NRML`)
    expect(ask).toHaveTextContent('Live mode: this goes to your broker.')
    // The safe choice holds the focus.
    expect(view.getByRole('button', { name: 'Keep position' })).toHaveFocus()

    fireEvent.click(view.getByRole('button', { name: 'Keep position' }))
    expect(fake.api.closePosition).not.toHaveBeenCalled()

    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    await waitFor(() =>
      expect(fake.api.closePosition).toHaveBeenCalledWith(NIFTY_FUT.symbol, 'NFO', 'NRML')
    )
    expect(fake.api.closePosition).toHaveBeenCalledTimes(1)
    expect(bridge.actions.refresh).toHaveBeenCalled()
  })

  it('says sandbox in analyzer mode and leaves the destination to the server', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position()] })
    const { view, owner } = await mount(bridge, 'analyzer')
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    expect(view.getByRole('alertdialog')).toHaveTextContent(
      'Analyzer mode is on: this goes to the sandbox, not to your broker.'
    )
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    // The same session route as live: analyzer mode is decided on the server.
    await waitFor(() => expect(fake.api.closePosition).toHaveBeenCalledTimes(1))
    expect(owner.placeTicket).not.toHaveBeenCalled()
  })

  it('refuses while trading is locked, as the dock does', async () => {
    const bridge = bridgeWith({ orders: [order()], positions: [position()] })
    bridge.actions.refuse.mockReturnValue(true)
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    fireEvent.click(view.getByRole('button', { name: 'Close position' }))
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: /^Cancel orders/ }))
    fireEvent.click(view.getByRole('button', { name: 'Cancel order' }))
    await waitFor(() => expect(bridge.actions.refuse).toHaveBeenCalledTimes(2))
    expect(fake.api.closePosition).not.toHaveBeenCalled()
    expect(fake.api.cancelOrder).not.toHaveBeenCalled()
  })

  it('cancels every working order on the symbol, and only those, once confirmed', async () => {
    const bridge = bridgeWith({
      orders: [
        order({ orderid: 'A' }),
        order({ orderid: 'B', action: 'BUY', pricetype: 'SL', trigger_price: 24900 }),
        order({ orderid: 'C', order_status: 'complete' }),
        order({ orderid: 'D', symbol: 'OTHER' }),
      ],
      positions: [],
    })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: `Cancel orders on ${NIFTY_FUT.symbol} (2)` }))
    expect(fake.api.cancelOrder).not.toHaveBeenCalled()
    expect(view.getByRole('alertdialog')).toHaveTextContent('SELL 65 LIMIT at 25100, NRML')
    fireEvent.click(view.getByRole('button', { name: 'Cancel orders' }))
    await waitFor(() => expect(fake.api.cancelOrder).toHaveBeenCalledTimes(2))
    expect(fake.api.cancelOrder.mock.calls.map((c) => c[0])).toEqual(['A', 'B'])
  })

  it('closes half in whole lots on the closing side, through the ticket path', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position({ quantity: -195 })] })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close half' }))
    // Three lots short: half is one lot, bought back.
    expect(view.getByRole('alertdialog')).toHaveTextContent('BUY 65 (1 lot)')
    expect(owner.placeTicket).not.toHaveBeenCalled()
    fireEvent.click(view.getByRole('button', { name: 'Close half' }))
    await waitFor(() =>
      expect(owner.placeTicket).toHaveBeenCalledWith({
        symbol: NIFTY_FUT.symbol,
        exchange: 'NFO',
        action: 'BUY',
        quantity: 65,
        pricetype: 'MARKET',
        product: 'NRML',
      })
    )
    expect(fake.api.closePosition).not.toHaveBeenCalled()
  })

  it('sends nothing for half when the position moved since the menu opened', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position()] })
    vi.mocked(bridge.freshPositions).mockResolvedValue([position({ quantity: 130 })])
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Close half' }))
    fireEvent.click(view.getByRole('button', { name: 'Close half' }))
    await waitFor(() =>
      expect(fake.toast).toHaveBeenCalledWith(
        expect.stringContaining('changed since the menu opened. Nothing was sent.')
      )
    )
    expect(owner.placeTicket).not.toHaveBeenCalled()
  })

  it('greys half on a single lot and reverse on delivery', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position({ quantity: 65 })] })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    expect(view.getByRole('button', { name: 'Close half' })).toBeDisabled()
    cleanup()
    fake.owners.length = 0
    const cnc = bridgeWith({ orders: [], positions: [position({ product: 'CNC' })] })
    const next = await mount(cnc)
    act(() => next.owner.options.callbacks.onContextMenu?.(menu()))
    expect(next.view.getByRole('button', { name: 'Reverse position' })).toBeDisabled()
  })

  it('reverses by closing, then opening the ticket for the new side without sending it', async () => {
    const bridge = bridgeWith({ orders: [], positions: [position()] })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Reverse position' }))
    const ask = view.getByRole('alertdialog')
    expect(ask).toHaveTextContent('not entered until you place that order yourself')
    fireEvent.click(view.getByRole('button', { name: 'Close and open ticket' }))
    await waitFor(() => expect(fake.api.closePosition).toHaveBeenCalledTimes(1))
    // The new side is a filled-in ticket, opened and not sent.
    expect(await view.findByRole('dialog', { name: 'Order ticket' })).toHaveTextContent(
      'SELL 260 NRML MARKET lot 65'
    )
    // One close, never an order of twice the quantity.
    expect(owner.placeTicket).not.toHaveBeenCalled()
  })

  it('opens no ticket when the close was refused', async () => {
    fake.api.closePosition.mockResolvedValue({ status: 'error', message: 'No open position' })
    const bridge = bridgeWith({ orders: [], positions: [position()] })
    const { view, owner } = await mount(bridge)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Reverse position' }))
    fireEvent.click(view.getByRole('button', { name: 'Close and open ticket' }))
    await waitFor(() => expect(fake.toast).toHaveBeenCalledWith('No open position', 'orders'))
    expect(owner.placeTicket).not.toHaveBeenCalled()
    expect(view.queryByRole('dialog', { name: 'Order ticket' })).toBeNull()
  })
})

describe('study rows and Alerts in the chart menu', () => {
  it('names the study and acts on it and its pane', async () => {
    const { view, owner } = await mount(null)
    const study = {
      study: { id: 'rsi-1', name: 'RSI', configurable: true, removable: true },
      pane: {
        index: 1,
        up: { disabled: true, reason: 'The price pane stays on top' },
        down: { disabled: false },
        collapsed: false,
      },
    }
    act(() => owner.options.callbacks.onContextMenu?.(menu({ study })))
    expect(view.getByRole('button', { name: 'Move pane up' })).toBeDisabled()
    fireEvent.click(view.getByRole('button', { name: 'RSI settings...' }))
    expect(owner.openIndicatorSettings).toHaveBeenCalledWith('rsi-1')

    act(() => owner.options.callbacks.onContextMenu?.(menu({ study })))
    fireEvent.click(view.getByRole('button', { name: 'Move pane down' }))
    expect(owner.moveStudyPane).toHaveBeenCalledWith(1, 1)

    act(() => owner.options.callbacks.onContextMenu?.(menu({ study })))
    fireEvent.click(view.getByRole('button', { name: 'Collapse pane' }))
    expect(owner.setStudyPaneCollapsed).toHaveBeenCalledWith(1, true)

    act(() =>
      owner.options.callbacks.onContextMenu?.(
        menu({ study: { ...study, pane: { ...study.pane, collapsed: true } } })
      )
    )
    expect(view.getByRole('button', { name: 'Expand pane' })).toBeInTheDocument()
    fireEvent.click(view.getByRole('button', { name: 'Remove RSI' }))
    expect(owner.removeIndicatorById).toHaveBeenCalledWith('rsi-1')
  })

  it('greys what a protected study does not allow', async () => {
    const { view, owner } = await mount(null)
    act(() =>
      owner.options.callbacks.onContextMenu?.(
        menu({
          study: {
            study: { id: 'v', name: 'VWAP', configurable: false, removable: false },
            pane: null,
          },
        })
      )
    )
    expect(view.getByRole('button', { name: 'VWAP settings...' })).toBeDisabled()
    expect(view.getByRole('button', { name: 'Remove VWAP' })).toBeDisabled()
    expect(view.queryByRole('button', { name: 'Move pane up' })).toBeNull()
  })

  it('opens the alerts list', async () => {
    const { view, owner } = await mount(null)
    act(() => owner.options.callbacks.onContextMenu?.(menu()))
    fireEvent.click(view.getByRole('button', { name: 'Alerts...' }))
    expect(owner.openAlerts).toHaveBeenCalledWith()
  })

  it('undoes chart changes from the toolbar, never naming an order', async () => {
    const { view, owner } = await mount(null)
    const undo = view.getByRole('button', { name: 'Undo chart change' })
    expect(undo.getAttribute('title')).toContain('Orders are never undone')
    fireEvent.click(undo)
    expect(owner.historyPress).toHaveBeenCalledWith('undo')
  })
})
