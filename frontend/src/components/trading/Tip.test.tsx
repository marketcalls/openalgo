import { afterEach, describe, expect, it, vi } from 'vitest'
import { placeTip } from '@/lib/trading/tipPlacement'
import { act, cleanup, fireEvent, render, screen } from '@/test/test-utils'
import { Tip } from './Tip'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const view = { width: 1366, height: 768 }

describe('where a label goes', () => {
  it('opens on the side asked for when there is room', () => {
    const at = placeTip(
      { left: 100, top: 40, width: 32, height: 32 },
      { width: 120, height: 40 },
      view
    )
    expect(at).toEqual({ left: 56, top: 78, side: 'bottom' })
  })

  it('flips across the control at a window edge', () => {
    const bottom = placeTip(
      { left: 100, top: 740, width: 32, height: 24 },
      { width: 120, height: 40 },
      view,
      'bottom'
    )
    expect(bottom.side).toBe('top')
    expect(bottom.top).toBe(740 - 6 - 40)
    const right = placeTip(
      { left: 1330, top: 300, width: 32, height: 32 },
      { width: 200, height: 40 },
      view,
      'right'
    )
    expect(right.side).toBe('left')
    expect(right.left).toBe(1330 - 6 - 200)
  })

  it('slides along the edge rather than leave the window', () => {
    const at = placeTip(
      { left: 2, top: 40, width: 32, height: 32 },
      { width: 200, height: 40 },
      view
    )
    expect(at.left).toBe(4)
  })
})

describe('the hover label', () => {
  it('shows the name, the shortcut and one line after a short rest, and drops the title', () => {
    vi.useFakeTimers()
    render(
      <Tip tip={{ title: 'Undo drawing', chord: 'Ctrl+Z', sub: 'Takes back the last drawing' }}>
        <button type="button" title="old" aria-label="Undo drawing">
          Undo
        </button>
      </Tip>
    )
    const button = screen.getByRole('button', { name: 'Undo drawing' })
    expect(button).not.toHaveAttribute('title')
    fireEvent.pointerEnter(button)
    expect(screen.queryByRole('tooltip')).toBeNull()
    act(() => vi.advanceTimersByTime(400))
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent('Undo drawing')
    expect(tip).toHaveTextContent('Ctrl+Z')
    expect(tip).toHaveTextContent('Takes back the last drawing')
    expect(button).toHaveAttribute('aria-describedby', tip.id)
  })

  it('hides on a press, on leaving and on Escape', () => {
    vi.useFakeTimers()
    render(
      <Tip tip={{ title: 'Alerts' }}>
        <button type="button">Alerts</button>
      </Tip>
    )
    const button = screen.getByRole('button', { name: 'Alerts' })
    const open = () => {
      fireEvent.pointerEnter(button)
      act(() => vi.advanceTimersByTime(400))
      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    }
    open()
    fireEvent.pointerDown(button)
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.pointerLeave(button)
    open()
    fireEvent.pointerLeave(button)
    expect(screen.queryByRole('tooltip')).toBeNull()
    open()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('never shows on a touch, or while held back', () => {
    vi.useFakeTimers()
    const { rerender } = render(
      <Tip tip={{ title: 'Compare' }} disabled>
        <button type="button">Compare</button>
      </Tip>
    )
    const button = screen.getByRole('button', { name: 'Compare' })
    fireEvent.pointerEnter(button)
    act(() => vi.advanceTimersByTime(400))
    expect(screen.queryByRole('tooltip')).toBeNull()
    rerender(
      <Tip tip={{ title: 'Compare' }}>
        <button type="button">Compare</button>
      </Tip>
    )
    fireEvent.pointerEnter(button, { pointerType: 'touch' })
    act(() => vi.advanceTimersByTime(400))
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
})
