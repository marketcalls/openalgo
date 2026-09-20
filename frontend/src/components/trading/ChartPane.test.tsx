import type { WorkspacePane } from 'openalgo-charts/workspace'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SymbolView, TerminalOptions } from '@/lib/trading/terminal'
import { act, cleanup, fireEvent, render } from '@/test/test-utils'
import { ChartPane } from './ChartPane'

interface Owner {
  options: TerminalOptions
  resolve(): void
  reject(error: Error): void
  destroy: ReturnType<typeof vi.fn>
  setArmed: ReturnType<typeof vi.fn>
  setWorkspaceTransitionLocked: ReturnType<typeof vi.fn>
  setMagnet: ReturnType<typeof vi.fn>
  setDrawStay: ReturnType<typeof vi.fn>
  setDrawTool: ReturnType<typeof vi.fn>
  openAlerts: ReturnType<typeof vi.fn>
}
const fake = vi.hoisted(() => ({ owners: [] as Owner[], toast: vi.fn() }))
vi.mock('@/utils/toast', () => ({
  showToast: { success: fake.toast, error: fake.toast, info: fake.toast },
}))
vi.mock('@/lib/trading/terminal', () => ({
  TradingTerminal: class {
    options: TerminalOptions
    resolve!: () => void
    reject!: (error: Error) => void
    pending = new Promise<void>((resolve, reject) => {
      this.resolve = resolve
      this.reject = reject
    })
    destroy = vi.fn()
    setArmed = vi.fn()
    setWorkspaceTransitionLocked = vi.fn()
    setLinkGroup = vi.fn()
    setDrawTool = vi.fn(async () => {})
    openAlerts = vi.fn(async () => true)
    setMagnet = vi.fn()
    setDrawStay = vi.fn()
    applyTheme = vi.fn()
    gridState = () => ({ vertical: true, horizontal: true })
    volumeVisible = () => false
    drawStats = () => ({
      count: 0,
      canUndo: false,
      canRedo: false,
      hasSelection: false,
      magnet: true,
      stay: true,
      tool: null,
      shortcuts: {},
    })
    constructor(options: TerminalOptions) {
      this.options = options
      fake.owners.push(this)
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
const pane: WorkspacePane = {
  id: 'saved',
  symbol: 'BHEL',
  exchange: 'NSE',
  interval: '5m',
  chartType: 'candlestick',
  chart: { version: 1, indicators: [] },
  settings: {},
  volume: false,
  magnet: 'weak',
  stay: true,
  comparisons: [],
  comparisonMode: 'price',
}
const props = { paneId: 'saved', apiKey: 'fixture', wsUrl: 'ws://fixture.invalid' }
beforeEach(() => {
  fake.owners.length = 0
  fake.toast.mockClear()
})
afterEach(cleanup)

describe('chart pane preparation ownership', () => {
  it('opens the alert source supplied by the chart context event', async () => {
    const view = render(<ChartPane {...props} />)
    const owner = fake.owners[0]
    await act(async () => owner.resolve())
    const source = { kind: 'price' as const, price: 105 }
    act(() =>
      owner.options.callbacks.onContextMenu?.({
        x: 100,
        y: 100,
        items: [],
        profile: null,
        alert: { label: 'Create price alert', source },
      })
    )
    fireEvent.click(view.getByRole('button', { name: 'Create price alert', exact: true }))
    expect(owner.openAlerts).toHaveBeenCalledWith(source)
  })

  it('opens alerts from the pane toolbar', async () => {
    const view = render(<ChartPane {...props} />)
    await act(async () => fake.owners[0].resolve())
    fireEvent.click(view.getByRole('button', { name: 'Alerts', exact: true }))
    expect(fake.owners[0].openAlerts).toHaveBeenCalledOnce()
  })

  it('does not start drawing attachment from the shared rail before a prepared chart exists', async () => {
    const { rerender } = render(
      <ChartPane {...props} initialWorkspacePane={pane} sharedTool={null} />
    )
    const owner = fake.owners[0]
    expect(owner.setDrawTool).not.toHaveBeenCalled()
    await act(async () => owner.resolve())
    rerender(<ChartPane {...props} initialWorkspacePane={pane} sharedTool="trend" />)
    expect(owner.setDrawTool).toHaveBeenCalledWith('trend')
  })
  it('passes the initial document and reports readiness only after terminal initialization', async () => {
    const initialized = vi.fn()
    render(<ChartPane {...props} initialWorkspacePane={pane} onInitialized={initialized} />)
    const owner = fake.owners[0]
    expect(owner.options.initialWorkspacePane).toBe(pane)
    expect(initialized).not.toHaveBeenCalled()
    await act(async () => owner.resolve())
    expect(initialized).toHaveBeenCalledWith('saved', owner)
  })

  it('ignores callbacks and late initialization from a StrictMode owner that was torn down', async () => {
    const initialized = vi.fn(),
      symbol = vi.fn(),
      objects = vi.fn()
    render(
      <ChartPane
        {...props}
        onInitialized={initialized}
        onSymbolChange={symbol}
        onObjectsChange={objects}
      />,
      { reactStrictMode: true }
    )
    const [old, current] = fake.owners
    expect(old.destroy).toHaveBeenCalledOnce()
    symbol.mockClear()
    objects.mockClear()
    const view = { symbol: 'STALE', exchange: 'NSE', productOptions: [] } as unknown as SymbolView
    await act(async () => {
      old.options.callbacks.onSymbolLoaded(view)
      old.options.callbacks.onToast('Stale callback', 'err')
      old.options.callbacks.onObjectsChange?.(null)
      old.resolve()
    })
    expect(symbol).not.toHaveBeenCalled()
    expect(objects).not.toHaveBeenCalled()
    expect(fake.toast).not.toHaveBeenCalled()
    expect(initialized).not.toHaveBeenCalled()
    await act(async () => current.resolve())
    expect(initialized).toHaveBeenCalledWith('saved', current)
  })

  it('reports failed initialization and releases its terminal', async () => {
    const failed = vi.fn(),
      terminal = vi.fn()
    render(
      <ChartPane
        {...props}
        initialWorkspacePane={pane}
        onInitializationError={failed}
        onTerminalChange={terminal}
      />
    )
    const owner = fake.owners[0],
      error = new Error('History unavailable')
    await act(async () => owner.reject(error))
    expect(failed).toHaveBeenCalledWith('saved', error)
    expect(owner.destroy).toHaveBeenCalled()
    expect(terminal).toHaveBeenLastCalledWith('saved', null)
  })

  it('preserves saved drawing preferences during preparation and applies later explicit changes', async () => {
    const { rerender } = render(
      <ChartPane {...props} initialWorkspacePane={pane} sharedMagnet={false} sharedStay={false} />
    )
    const owner = fake.owners[0]
    expect(owner.setMagnet).not.toHaveBeenCalled()
    expect(owner.setDrawStay).not.toHaveBeenCalled()
    await act(async () => owner.resolve())
    rerender(<ChartPane {...props} initialWorkspacePane={pane} sharedMagnet sharedStay />)
    expect(fake.owners).toHaveLength(1)
    expect(owner.setMagnet).toHaveBeenCalledWith(true)
    expect(owner.setDrawStay).toHaveBeenCalledWith(true)
  })

  it('holds the workspace lock and disarms execution while keeping the same prepared owner on publication', async () => {
    const { rerender } = render(
      <ChartPane {...props} initialWorkspacePane={pane} transitionLocked armed />
    )
    const owner = fake.owners[0]
    expect(owner.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(true)
    expect(owner.setArmed).toHaveBeenLastCalledWith(false)
    await act(async () => owner.resolve())
    rerender(
      <ChartPane {...props} initialWorkspacePane={pane} transitionLocked={false} armed={false} />
    )
    expect(fake.owners).toHaveLength(1)
    expect(owner.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(false)
    expect(owner.setArmed).toHaveBeenLastCalledWith(false)
  })
})
