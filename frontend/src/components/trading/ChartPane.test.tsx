import type { WorkspacePane } from 'openalgo-charts/workspace'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SymbolView, TerminalOptions } from '@/lib/trading/terminal'
import { act, cleanup, fireEvent, render, within } from '@/test/test-utils'
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
  createAlertAt: ReturnType<typeof vi.fn>
  addComparison: ReturnType<typeof vi.fn>
  removeComparison: ReturnType<typeof vi.fn>
  setComparisonMode: ReturnType<typeof vi.fn>
  exportDataCsv: ReturnType<typeof vi.fn>
  startReplay: ReturnType<typeof vi.fn>
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
    createAlertAt = vi.fn(async () => true)
    addComparison = vi.fn(async () => {})
    removeComparison = vi.fn()
    setComparisonMode = vi.fn()
    exportDataCsv = vi.fn(() => 'time,close\n1,10')
    startReplay = vi.fn()
    replayPickingBar = () => false
    replayLoadingBars = () => false
    search = async () => []
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
  it('disables CSV during replay selection and history loading, then allows the active prefix', async () => {
    const snapshot = {
      phase: 'picking' as const,
      scope: 'all' as const,
      ownerId: 'saved',
      state: null,
    }
    const view = render(<ChartPane {...props} workspaceReplay={snapshot} />)
    await act(async () => fake.owners[0].resolve())
    fireEvent.click(view.getByRole('button', { name: 'Chart snapshot' }))
    const csv = view.getByRole('button', { name: 'Download CSV' })
    expect(csv).toBeDisabled()
    expect(csv).toHaveAttribute(
      'title',
      'Finish selecting and loading replay before exporting data'
    )
    fireEvent.click(csv)
    expect(fake.owners[0].exportDataCsv).not.toHaveBeenCalled()
    view.rerender(<ChartPane {...props} workspaceReplay={{ ...snapshot, phase: 'loading' }} />)
    expect(csv).toBeDisabled()
    view.rerender(<ChartPane {...props} workspaceReplay={{ ...snapshot, phase: 'active' }} />)
    expect(csv).toBeEnabled()
  })

  it('exports only the selected chart CSV and releases the download URL', async () => {
    const create = vi.fn(() => 'blob:chart-csv'),
      revoke = vi.fn()
    vi.stubGlobal(
      'URL',
      class extends URL {
        static createObjectURL = create
        static revokeObjectURL = revoke
      }
    )
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      const host = render(<div data-testid="csv-toolbar" />).getByTestId('csv-toolbar')
      const panes = (focused: string) => (
        <>
          <ChartPane {...props} paneId="left" toolbarHost={host} focused={focused === 'left'} />
          <ChartPane {...props} paneId="right" toolbarHost={host} focused={focused === 'right'} />
        </>
      )
      const view = render(panes('left'))
      await act(async () => fake.owners.forEach((owner) => owner.resolve()))
      view.rerender(panes('right'))
      fireEvent.click(within(host).getByRole('button', { name: 'Chart snapshot' }))
      fireEvent.click(view.getByRole('button', { name: 'Download CSV' }))
      expect(fake.owners[0].exportDataCsv).not.toHaveBeenCalled()
      expect(fake.owners[1].exportDataCsv).toHaveBeenCalledOnce()
      expect(create).toHaveBeenCalledWith(expect.any(Blob))
      expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:chart-csv')
      expect(click).toHaveBeenCalledOnce()
      expect(document.querySelector('a[download]')).toBeNull()
    } finally {
      click.mockRestore()
      vi.unstubAllGlobals()
    }
  })

  it('keeps comparisons on the selected toolbar and updates the selected terminal mode', async () => {
    const host = render(<div data-testid="compare-toolbar" />).getByTestId('compare-toolbar')
    const panes = (focused: string) => (
      <>
        <ChartPane {...props} paneId="left" toolbarHost={host} focused={focused === 'left'} />
        <ChartPane {...props} paneId="right" toolbarHost={host} focused={focused === 'right'} />
      </>
    )
    const view = render(panes('left'))
    await act(async () => fake.owners.forEach((owner) => owner.resolve()))
    act(() =>
      fake.owners[1].options.callbacks.onComparisonsChange?.({
        mode: 'price',
        items: [
          {
            id: 'right-comparison',
            symbol: 'INFY',
            exchange: 'NSE',
            label: 'NSE:INFY',
            color: '#4488ff',
            status: 'ready',
          },
        ],
      })
    )
    view.rerender(panes('right'))
    expect(view.getAllByRole('button', { name: 'Comparisons' })).toHaveLength(1)
    fireEvent.click(within(host).getByRole('button', { name: 'Comparisons' }))
    fireEvent.change(view.getByLabelText('Comparison scale'), { target: { value: 'percentage' } })
    fireEvent.click(view.getByRole('button', { name: 'Remove NSE:INFY' }))
    expect(fake.owners[1].setComparisonMode).toHaveBeenCalledExactlyOnceWith('percentage')
    expect(fake.owners[1].removeComparison).toHaveBeenCalledExactlyOnceWith('right-comparison')
    expect(fake.owners[0].setComparisonMode).not.toHaveBeenCalled()
  })

  it('delegates replay to the workspace owner and suppresses duplicate local transports', async () => {
    const start = vi.fn()
    const view = render(
      <ChartPane
        {...props}
        onReplayStart={start}
        workspaceReplay={{ phase: 'loading', scope: 'all', ownerId: 'saved', state: null }}
      />
    )
    await act(async () => fake.owners[0].resolve())
    act(() =>
      fake.owners[0].options.callbacks.onReplayChange?.({
        playing: false,
        speed: 1,
        index: 0,
        total: 2,
        subIndex: 0,
        subSteps: 1,
        bar: null,
      })
    )
    fireEvent.click(view.getByRole('button', { name: 'Replay', exact: true }))
    expect(start).toHaveBeenCalledExactlyOnceWith('saved')
    expect(fake.owners[0].startReplay).not.toHaveBeenCalled()
    expect(view.queryByRole('button', { name: 'Play' })).toBeNull()
    expect(view.queryByText('Loading replay history')).toBeNull()
    expect(view.getByRole('button', { name: 'Comparisons' })).toBeDisabled()
  })

  it('shares one toolbar and routes actions without recreating either terminal', async () => {
    const host = render(<div data-testid="shared-toolbar" />).getByTestId('shared-toolbar')
    const panes = (active: string) => (
      <>
        <ChartPane {...props} paneId="left" toolbarHost={host} focused={active === 'left'} />
        <ChartPane {...props} paneId="right" toolbarHost={host} focused={active === 'right'} />
      </>
    )
    const view = render(panes('left'))
    await act(async () => fake.owners.forEach((owner) => owner.resolve()))
    expect(view.getAllByRole('toolbar', { name: 'Chart controls' })).toHaveLength(1)
    fireEvent.click(within(host).getByRole('button', { name: 'Alerts', exact: true }))
    expect(fake.owners[0].openAlerts).toHaveBeenCalledOnce()
    expect(fake.owners[1].openAlerts).not.toHaveBeenCalled()
    view.rerender(panes('right'))
    fireEvent.click(within(host).getByRole('button', { name: 'Alerts', exact: true }))
    expect(fake.owners[1].openAlerts).toHaveBeenCalledOnce()
    expect(fake.owners).toHaveLength(2)
    expect(fake.owners.every((owner) => owner.destroy.mock.calls.length === 0)).toBe(true)
  })

  it('keeps controls absent until their shared host is available', () => {
    const view = render(<ChartPane {...props} toolbarHost={null} focused />)
    expect(view.queryByRole('button', { name: 'Alerts', exact: true })).toBeNull()
  })

  it('selects the pane through keyboard focus and exposes the selected pane', async () => {
    const focus = vi.fn()
    const view = render(<ChartPane {...props} paneLabel="Chart 2" focused onFocusPane={focus} />)
    await act(async () => fake.owners[0].resolve())
    const chart = view.getByRole('region', { name: 'Chart 2', exact: true })
    expect(chart).toHaveAttribute('tabindex', '0')
    expect(chart).toHaveAttribute('data-chart-focused', 'true')
    fireEvent.focus(chart)
    expect(focus).toHaveBeenLastCalledWith(fake.owners[0], 'saved')
  })

  it('moves the controls inside their fullscreen chart and returns them on exit', async () => {
    const host = render(<div data-testid="shared-toolbar" />).getByTestId('shared-toolbar')
    const view = render(<ChartPane {...props} toolbarHost={host} focused paneLabel="Chart 1" />)
    await act(async () => fake.owners[0].resolve())
    const chart = view.getByRole('region', { name: 'Chart 1', exact: true })
    expect(within(host).getByRole('button', { name: 'Alerts', exact: true })).toBeVisible()
    try {
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: chart })
      fireEvent(document, new Event('fullscreenchange'))
      expect(host).toBeEmptyDOMElement()
      fireEvent.click(within(chart).getByRole('button', { name: 'Alerts', exact: true }))
      expect(fake.owners[0].openAlerts).toHaveBeenCalledOnce()
    } finally {
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
      fireEvent(document, new Event('fullscreenchange'))
    }
    expect(within(host).getByRole('button', { name: 'Alerts', exact: true })).toBeVisible()
    expect(fake.owners).toHaveLength(1)
  })

  it('keeps the external toolbar inert while its workspace is locked', () => {
    const host = render(<div data-testid="shared-toolbar" />).getByTestId('shared-toolbar')
    render(<ChartPane {...props} toolbarHost={host} focused transitionLocked />)
    expect(within(host).getByRole('toolbar', { name: 'Chart controls' })).toHaveAttribute('inert')
  })

  /**
   * The gesture makes the alert; it does not open a form about it.
   *
   * The price is the one thing a form would ask for and pointing at it has
   * already given it, so a dialog here is a confirmation step on a decision
   * already made and it costs the gesture the only thing it is for. The form
   * stays on the toolbar for an alert that needs more than the defaults.
   */
  it('makes the alert the chart context event named, without opening a form', async () => {
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
    expect(owner.createAlertAt).toHaveBeenCalledWith(source)
    expect(owner.openAlerts).not.toHaveBeenCalled()
  })

  it('offers no second alert entry in the menu', async () => {
    // One gesture, one meaning. A second entry a line below the first, spelled
    // almost the same and doing something else, is a choice nobody wants to
    // make mid-gesture. The form is on the toolbar.
    const view = render(<ChartPane {...props} />)
    const owner = fake.owners[0]
    await act(async () => owner.resolve())
    act(() =>
      owner.options.callbacks.onContextMenu?.({
        x: 100,
        y: 100,
        items: [],
        profile: null,
        alert: { label: 'Create price alert', source: { kind: 'price' as const, price: 105 } },
      })
    )
    expect(view.getByRole('button', { name: 'Create price alert', exact: true })).toBeVisible()
    expect(view.queryByRole('button', { name: /^Create alert/ })).not.toBeInTheDocument()
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
