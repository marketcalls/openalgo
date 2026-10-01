import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'
import { cleanup, fireEvent, render, screen } from '@/test/test-utils'
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
