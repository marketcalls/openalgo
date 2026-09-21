import type { ComponentProps } from 'react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartPane } from '@/components/trading/ChartPane'
import { LAYOUTS } from '@/lib/chart/layouts'
import type { PreparedChartGrid } from '@/lib/trading/preparedGrid'
import type { TradingTerminal } from '@/lib/trading/terminal'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@/test/test-utils'
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
  terminal: { setWorkspaceTransitionLocked: vi.fn(), setArmed: vi.fn(), drawStats: () => ({}) },
  publish: null as null | ((grid: PreparedChartGrid) => void),
  lock: null as null | ((pending: boolean) => void),
  changed: vi.fn(),
  markSaved: vi.fn(),
  missingPane: '',
}))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ isAuthenticated: true, user: { username: 'fixture' } }),
}))
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
vi.mock('@/components/layout/Navbar', () => ({ Navbar: () => null }))
vi.mock('@/components/trading/DrawingRail', () => ({ DrawingRail: () => null }))
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
    expect(fake.members).toHaveBeenLastCalledWith([{ id: 'p0', terminal: fake.terminal }])
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
