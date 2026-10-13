import type { Bar, ReplayState } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'
import { act, cleanup, fireEvent, render, screen } from '@/test/test-utils'
import { WorkspaceReplayBar } from './WorkspaceReplayBar'

afterEach(cleanup)
const callbacks = () => ({
  onScopeChange: vi.fn(),
  onPlay: vi.fn(),
  onPause: vi.fn(),
  onStep: vi.fn(),
  onStepBack: vi.fn(),
  onSeek: vi.fn(),
  onStop: vi.fn(),
})
const picking: WorkspaceReplaySnapshot = {
  phase: 'picking',
  scope: 'focused',
  ownerId: 'left',
  state: null,
}

describe('workspace replay transport', () => {
  it('moves the single transport into the fullscreen chart and restores it on exit', () => {
    const fullscreen = document.createElement('section')
    document.body.append(fullscreen)
    const view = render(
      <WorkspaceReplayBar snapshot={picking} ownerLabel="Chart 1" {...callbacks()} />
    )
    try {
      Object.defineProperty(document, 'fullscreenElement', {
        configurable: true,
        value: fullscreen,
      })
      fireEvent(document, new Event('fullscreenchange'))
      expect(fullscreen.querySelector('[aria-label="Workspace replay"]')).not.toBeNull()
      expect(view.container).toBeEmptyDOMElement()
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
      fireEvent(document, new Event('fullscreenchange'))
      expect(fullscreen).toBeEmptyDOMElement()
      expect(screen.getAllByRole('region', { name: 'Workspace replay' })).toHaveLength(1)
    } finally {
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
      fullscreen.remove()
    }
  })

  it('keeps the captured owner visible and offers cancellation while selecting and loading', () => {
    const handlers = callbacks()
    const view = render(
      <WorkspaceReplayBar snapshot={picking} ownerLabel="Chart 1" {...handlers} />
    )
    expect(screen.getByText('Select a bar on Chart 1')).toBeVisible()
    fireEvent.change(screen.getByLabelText('Replay scope'), { target: { value: 'all' } })
    expect(handlers.onScopeChange).toHaveBeenCalledWith('all')
    view.rerender(
      <WorkspaceReplayBar
        snapshot={{ ...picking, phase: 'loading' }}
        ownerLabel="Chart 1"
        {...handlers}
      />
    )
    expect(screen.getByText('Loading replay history')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Play' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel replay' }))
    expect(handlers.onStop).toHaveBeenCalledOnce()
  })

  it('routes the shared observation transport and exposes errors after replay stops', () => {
    const handlers = callbacks()
    const snapshot: WorkspaceReplaySnapshot = {
      ...picking,
      phase: 'active',
      state: {
        active: true,
        destroyed: false,
        scope: 'focused',
        focusedId: 'left',
        time: 100,
        index: 1,
        total: 4,
        playing: false,
        speed: 1,
        members: [],
      },
    }
    const view = render(
      <WorkspaceReplayBar snapshot={snapshot} ownerLabel="Chart 1" {...handlers} />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next observation' }))
    fireEvent.click(screen.getByRole('button', { name: 'Previous observation' }))
    fireEvent.change(screen.getByLabelText('Replay position'), { target: { value: '2' } })
    expect(handlers.onPlay).toHaveBeenCalledOnce()
    expect(handlers.onStep).toHaveBeenCalledOnce()
    expect(handlers.onStepBack).toHaveBeenCalledOnce()
    expect(handlers.onSeek).toHaveBeenCalledExactlyOnceWith(2)
    view.rerender(
      <WorkspaceReplayBar
        snapshot={{ ...picking, phase: 'idle', ownerId: null }}
        error="No replay history"
        {...handlers}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No replay history')
  })
})

// 1 Oct 2026 10:15 IST.
const T = Date.UTC(2026, 9, 1, 4, 45) / 1000
const member = (patch: Partial<ReplayState> = {}): ReplayState => ({
  index: 1,
  total: 4,
  playing: false,
  speed: 1,
  bar: { time: T, open: 1, high: 2, low: 0, close: 1 } as Bar,
  subIndex: 0,
  subSteps: 1,
  simulated: false,
  ...patch,
})
const active = (state: ReplayState): WorkspaceReplaySnapshot => ({
  ...picking,
  phase: 'active',
  state: {
    active: true,
    destroyed: false,
    scope: 'focused',
    focusedId: 'left',
    time: T + 300,
    index: 1,
    total: 4,
    playing: false,
    speed: 1,
    members: [{ id: 'left', active: true, state }],
  },
})

describe('replay readouts', () => {
  it('shows the playhead bar in IST, without a sub-step or a note on a whole-bar replay', () => {
    const view = render(
      <WorkspaceReplayBar snapshot={active(member())} interval="5m" {...callbacks()} />
    )
    expect(view.container.querySelector('[data-replay-clock]')).toHaveTextContent(
      '01 Oct 2026 10:15 IST'
    )
    expect(view.container.querySelector('[data-replay-substep]')).toBeNull()
    expect(screen.queryByText('Simulated')).toBeNull()
  })

  it('shows the step of a forming bar, and says when its prices are simulated', () => {
    const view = render(
      <WorkspaceReplayBar
        snapshot={active(member({ subIndex: 2, subSteps: 5, simulated: true }))}
        interval="5m"
        {...callbacks()}
      />
    )
    expect(view.container.querySelector('[data-replay-substep]')).toHaveTextContent('3/5')
    expect(screen.getByText('Simulated')).toBeVisible()
  })

  it('names the start bar under the pointer while one is chosen', () => {
    let time: number | null = T
    const listeners = new Set<() => void>()
    const pick = {
      subscribe: (listener: () => void) => {
        listeners.add(listener)
        return () => listeners.delete(listener)
      },
      time: () => time,
    }
    const view = render(
      <WorkspaceReplayBar
        snapshot={picking}
        ownerLabel="Chart 1"
        interval="D"
        pick={pick}
        {...callbacks()}
      />
    )
    expect(view.container.querySelector('[data-replay-picked]')).toHaveTextContent(
      'Start: 01 Oct 2026'
    )
    act(() => {
      time = T + 86400
      for (const listener of listeners) listener()
    })
    expect(view.container.querySelector('[data-replay-picked]')).toHaveTextContent(
      'Start: 02 Oct 2026'
    )
  })
})

describe('replay and Escape', () => {
  it('cancels choosing a start bar, and leaves the side panel to a later press', () => {
    const handlers = callbacks()
    render(<WorkspaceReplayBar snapshot={picking} ownerLabel="Chart 1" {...handlers} />)
    // The page's own Escape closes a side panel unless something says it is open.
    expect(
      document.querySelector('[data-trading-dialog-open="true"][aria-label="Workspace replay"]')
    ).not.toBeNull()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(handlers.onStop).toHaveBeenCalledOnce()
  })

  it('does not end an active replay on Escape', () => {
    const handlers = callbacks()
    render(<WorkspaceReplayBar snapshot={active(member())} {...handlers} />)
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(handlers.onStop).not.toHaveBeenCalled()
  })

  it('closes the leave confirm on Escape and stays in replay', () => {
    const handlers = callbacks()
    const onCancelExit = vi.fn()
    const onConfirmExit = vi.fn()
    render(
      <WorkspaceReplayBar
        snapshot={active(member())}
        confirmExit
        onCancelExit={onCancelExit}
        onConfirmExit={onConfirmExit}
        {...handlers}
      />
    )
    const dialog = screen.getByRole('dialog', { name: 'Leave replay?' })
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onCancelExit).toHaveBeenCalledOnce()
    expect(onConfirmExit).not.toHaveBeenCalled()
    expect(handlers.onStop).not.toHaveBeenCalled()
  })
})
