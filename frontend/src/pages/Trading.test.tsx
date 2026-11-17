import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartPane } from '@/components/trading/ChartPane'
import { LAYOUTS } from '@/lib/chart/layouts'
import type { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import type { TradingTerminal } from '@/lib/trading/terminal'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@/test/test-utils'
import Trading from './Trading'

const fake = vi.hoisted(() => ({
  autosave: {
    paused: false,
    capture: () => ({}),
    isPaused: undefined as (() => boolean) | undefined,
  },
  snapshot: {
    phase: 'idle',
    scope: 'focused',
    ownerId: null,
    state: null,
  } as WorkspaceReplaySnapshot,
  callbacks: null as null | { onChange(snapshot: WorkspaceReplaySnapshot): void },
  members: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  destroy: vi.fn(),
  terminal: {
    setWorkspaceTransitionLocked: vi.fn(),
    setArmed: vi.fn(),
    drawStats: () => ({}),
    currentInterval: () => '5m',
    replayPickingBar: () => false,
    loadSymbol: vi.fn(async () => true),
    whenReady: () => fake.ready,
  },
  ready: Promise.resolve(),
  publish: null as null | ((grid: PreparedChartGrid) => void),
  lock: null as null | ((pending: boolean) => void),
  changed: vi.fn(),
  markSaved: vi.fn(),
  missingPane: '',
}))
vi.mock('@/stores/authStore', () => {
  const state = {
    isAuthenticated: true,
    user: { username: 'fixture', broker: 'fixturebroker' },
    logout: () => {},
  }
  // The page reads one field through a selector; the header's account
  // controls, shared with the navbar, read the whole store.
  return {
    useAuthStore: (selector?: (value: typeof state) => unknown) =>
      selector ? selector(state) : state,
  }
})
vi.mock('@/hooks/useProfileMenuItems', async () => {
  const { User, Key } = await import('lucide-react')
  return {
    useProfileMenuItems: () => [
      { href: '/profile', label: 'Profile', icon: User },
      { href: '/apikey', label: 'API Key', icon: Key },
    ],
  }
})
vi.mock('openalgo-charts', () => ({ createLinkGroup: () => ({ setOptions() {}, destroy() {} }) }))
vi.mock('@/hooks/useChartWorkspaceCatalog', () => ({
  useChartWorkspaceCatalog: () => ({ catalog: null, loading: false, pending: false, error: null }),
}))
vi.mock('@/hooks/useWorkspaceAutosave', () => ({
  useWorkspaceAutosave: (options: typeof fake.autosave) => {
    fake.autosave = options
    return { status: 'Unsaved', error: null, changed: fake.changed, markSaved: fake.markSaved }
  },
}))
vi.mock('@/hooks/useWorkspaceGridTransition', () => ({
  useWorkspaceGridTransition: (
    _account: unknown,
    publish: typeof fake.publish,
    lock: typeof fake.lock
  ) => {
    fake.publish = publish
    fake.lock = lock
    return { grids: [], current: null, pending: false }
  },
}))
vi.mock('@/lib/trading/workspaceReplay', () => ({
  WorkspaceReplayCoordinator: class {
    constructor(callbacks: typeof fake.callbacks) {
      fake.callbacks = callbacks
    }
    setMembers = fake.members
    state = () => fake.snapshot
    start = fake.start
    stop = fake.stop
    destroy = fake.destroy
    subscribePick = () => () => {}
  },
}))
vi.mock('@/components/trading/ChartPane', () => ({
  ChartPane: (props: ComponentProps<typeof ChartPane>) => {
    useEffect(() => {
      props.onTerminalChange?.(
        props.paneId,
        fake.missingPane === props.paneId ? null : (fake.terminal as unknown as TradingTerminal)
      )
      return () => props.onTerminalChange?.(props.paneId, null)
    }, [props.paneId, props.onTerminalChange])
    return (
      <>
        <button type="button" onClick={() => props.onReplayStart?.(props.paneId)}>
          Replay {props.paneId}
        </button>
        <button type="button" onClick={() => props.onBeforeSourceChange?.()}>
          Change source {props.paneId}
        </button>
      </>
    )
  },
}))
vi.mock('@/components/trading/DrawingRail', async (importOriginal) => {
  // The real tab, and a stand-in rail that says whether it is folded and
  // offers the fold, so the page's half of folding is what is under test.
  const actual = await importOriginal<typeof import('@/components/trading/DrawingRail')>()
  return {
    ...actual,
    DrawingRail: (props: { folded?: boolean; onFold?(): void }) => (
      <div data-testid="drawing-rail" hidden={props.folded}>
        <button type="button" onClick={props.onFold}>
          Hide drawing tools
        </button>
      </div>
    ),
  }
})
vi.mock('@/components/trading/IndicatorTemplates', () => ({ IndicatorTemplates: () => null }))
vi.mock('@/components/trading/WorkspaceMenu', () => ({ WorkspaceMenu: () => null }))
vi.mock('@/components/trading/dock/TradingDock', () => ({ TradingDock: () => null }))
vi.mock('@/components/trading/RightRail', () => ({ RightRail: () => null, isPanelId: () => false }))

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  fake.snapshot = { phase: 'idle', scope: 'focused', ownerId: null, state: null }
  fake.missingPane = ''
  fake.stop.mockImplementation(() => {
    fake.snapshot = { ...fake.snapshot, phase: 'idle', ownerId: null }
    fake.callbacks?.onChange(fake.snapshot)
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      json: async () => ({
        status: 'success',
        api_key: 'fixture',
        websocket_url: 'ws://fixture.invalid',
      }),
    }))
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
  fake.ready = Promise.resolve()
})

describe('workspace replay page ownership', () => {
  it('cancels a picker before a source change without presenting an active-exit dialog', async () => {
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    act(() => {
      fake.snapshot = { ...fake.snapshot, phase: 'picking', ownerId: 'p0' }
      fake.callbacks?.onChange(fake.snapshot)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Change source p0' }))
    expect(fake.stop).toHaveBeenCalledOnce()
    expect(fake.autosave.paused).toBe(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('refuses replay when any visible grid pane is missing instead of replaying a partial grid', async () => {
    localStorage.setItem('oa-trading-layout', LAYOUTS[1].id)
    fake.missingPane = 'p1'
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    fireEvent.click(screen.getByRole('button', { name: 'Replay p0' }))
    expect(fake.start).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Every visible chart must be ready before replay'
    )
  })

  it('publishes visible members, pauses autosave for every replay phase and resumes on cancellation', async () => {
    const view = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    // The members are published by an effect that can run just after the
    // button appears; on a loaded runner the check used to land in between.
    await waitFor(() =>
      expect(fake.members).toHaveBeenLastCalledWith([{ id: 'p0', terminal: fake.terminal }])
    )
    fireEvent.click(screen.getByRole('button', { name: 'Replay p0' }))
    expect(fake.start).toHaveBeenCalledExactlyOnceWith('p0')
    for (const phase of ['picking', 'loading', 'active'] as const) {
      act(() => {
        fake.snapshot = { ...fake.snapshot, phase, ownerId: 'p0' }
        fake.callbacks?.onChange(fake.snapshot)
        expect(fake.autosave.isPaused?.()).toBe(true)
      })
      expect(fake.autosave.paused).toBe(true)
      expect(() => fake.autosave.capture()).toThrow('Stop replay before saving')
      expect(screen.getAllByRole('region', { name: 'Workspace replay' })).toHaveLength(1)
    }
    fireEvent.click(screen.getByRole('button', { name: 'Stop replay' }))
    expect(fake.autosave.paused).toBe(true)
    expect(fake.stop).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Stay' }))
    expect(fake.autosave.paused).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Replay p0' }))
    fireEvent.click(screen.getByRole('button', { name: 'Leave' }))
    expect(fake.autosave.paused).toBe(false)
    act(() => fake.lock?.(true))
    expect(fake.stop).toHaveBeenCalledTimes(2)
    expect(fake.terminal.setWorkspaceTransitionLocked).toHaveBeenLastCalledWith(true)
    view.unmount()
    expect(fake.destroy).toHaveBeenCalledOnce()
  })
})

describe('bottom bar', () => {
  it('spends one strip on the whole grid, however many charts it holds', async () => {
    const widest = LAYOUTS.reduce((a, b) => (b.cells.length > a.cells.length ? b : a))
    localStorage.setItem('oa-trading-layout', widest.id)
    const { container } = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(screen.getAllByRole('button', { name: /^Replay p/ })).toHaveLength(widest.cells.length)
    expect(container.querySelectorAll('[data-trading-bottombar]')).toHaveLength(1)
    const grid = container.querySelector('[data-trading-bottombar]')?.previousElementSibling
    expect((grid as HTMLElement).style.bottom).toBe('28px')
  })
})

describe('chart grid dividers', () => {
  const gridOf = (container: HTMLElement) =>
    container.querySelector('[data-trading-bottombar]')?.previousElementSibling
      ?.firstElementChild as HTMLElement

  it('opens a layout with nothing stored at equal sizes, with a divider in each gap', async () => {
    localStorage.setItem('oa-trading-layout', 'grid4')
    const { container } = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(gridOf(container).style.gridTemplateColumns).toBe('1fr 1fr')
    expect(gridOf(container).style.gridTemplateRows).toBe('1fr 1fr')
    expect(screen.getAllByRole('separator')).toHaveLength(2)
  })

  it('draws a stored split, and a double-click puts the layout back and forgets it', async () => {
    localStorage.setItem('oa-trading-layout', 'grid4')
    localStorage.setItem(
      'oa-trading-layout-sizes',
      JSON.stringify({ grid4: { columns: [1.5, 0.5], rows: [1, 1] } })
    )
    const { container } = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(gridOf(container).style.gridTemplateColumns).toBe('1.5fr 0.5fr')
    fireEvent.doubleClick(screen.getByRole('separator', { name: 'Resize chart columns' }))
    expect(gridOf(container).style.gridTemplateColumns).toBe('1fr 1fr')
    expect(JSON.parse(localStorage.getItem('oa-trading-layout-sizes')!)).toEqual({})
    expect(fake.changed).toHaveBeenCalled()
  })

  it('offers no divider on a single chart', async () => {
    localStorage.setItem('oa-trading-layout', 'single')
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(screen.queryByRole('separator')).toBeNull()
  })
})

describe('terminal header', () => {
  it('replaces the app navbar with the way out and the account controls, all named', async () => {
    const user = userEvent.setup()
    const { container } = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())

    // The page has no navbar of its own any more: the row is the header.
    expect(container.querySelector('[data-testid="navbar-row"]')).toBeNull()

    const dashboard = screen.getByRole('link', { name: 'Dashboard' })
    expect(dashboard).toHaveAttribute('href', '/dashboard')
    expect(screen.getByRole('button', { name: 'Switch to Analyze mode' })).toBeEnabled()
    expect(screen.getByRole('button', { name: /^Switch to (dark|light) mode$/ })).toBeEnabled()
    const profile = screen.getByRole('button', { name: 'Open user menu' })
    expect(screen.getByText('fixturebroker')).toBeInTheDocument()
    expect(screen.getByText('Live', { exact: true })).toBeInTheDocument()

    // All four sit outside the chart toolbar's scrolling region, so a narrow
    // screen scrolls the chart controls and never these.
    const host = container.querySelector('[data-workspace-toolbar]') as HTMLElement
    for (const control of [
      dashboard,
      profile,
      screen.getByRole('button', { name: 'Switch to Analyze mode' }),
      screen.getByRole('button', { name: /^Switch to (dark|light) mode$/ }),
    ]) {
      expect(host.contains(control)).toBe(false)
      expect(host.parentElement?.contains(control)).toBe(true)
    }

    await user.click(profile)
    const menu = await screen.findByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: 'Profile' })).toBeVisible()
    expect(within(menu).getByRole('menuitem', { name: 'Logout' })).toBeVisible()
  })
})

describe('folding the drawing rail', () => {
  it('folds behind a tab that unfolds it, and remembers the choice across a remount', async () => {
    const user = userEvent.setup()
    const first = render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(screen.getByTestId('drawing-rail')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Show drawing tools' })).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Hide drawing tools' }))
    // Folded, not removed: the rail keeps its tool and its chords.
    expect(screen.getByTestId('drawing-rail')).not.toBeVisible()
    const tab = screen.getByRole('button', { name: 'Show drawing tools' })
    expect(localStorage.getItem('oa-trading-rail-folded')).toBe('1')

    // The tab keeps its press from the chart, whose pointer handling listens
    // above the page's root.
    const pressed = vi.fn()
    document.addEventListener('pointerdown', pressed)
    fireEvent.pointerDown(tab)
    document.removeEventListener('pointerdown', pressed)
    expect(pressed).not.toHaveBeenCalled()

    first.unmount()
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    expect(screen.getByTestId('drawing-rail')).not.toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Show drawing tools' }))
    expect(screen.getByTestId('drawing-rail')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Show drawing tools' })).toBeNull()
    expect(localStorage.getItem('oa-trading-rail-folded')).toBe('0')
  })
})

describe('opening a chart from a link', () => {
  it('loads the linked instrument once the chart is ready, then drops it from the address', async () => {
    let settle = () => {}
    fake.ready = new Promise<void>((resolve) => {
      settle = resolve
    })
    window.history.replaceState(null, '', '/trading?symbol=NIFTY28MAR2420800CE&exchange=NFO')
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    await waitFor(() => expect(window.location.search).toBe(''))
    // Loaded before the chart had a feed, the pane's own first load would
    // overtake it and the trader would land on the wrong instrument.
    expect(fake.terminal.loadSymbol).not.toHaveBeenCalled()

    await act(async () => settle())
    expect(fake.terminal.loadSymbol).toHaveBeenCalledExactlyOnceWith({
      symbol: 'NIFTY28MAR2420800CE',
      exchange: 'NFO',
    })
  })

  it('drops a symbol without its exchange instead of guessing one', async () => {
    window.history.replaceState(null, '', '/trading?symbol=SBIN')
    render(<Trading />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replay p0' })).toBeVisible())
    await waitFor(() => expect(window.location.search).toBe(''))
    expect(fake.terminal.loadSymbol).not.toHaveBeenCalled()
  })
})
