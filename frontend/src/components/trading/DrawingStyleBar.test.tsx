/**
 * The drawing properties bar: where it floats, and what each control writes.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DrawLevels } from '@/lib/trading/drawingActions'
import type { DrawSelection } from '@/lib/trading/terminal'
import { cleanup, fireEvent, render, screen } from '@/test/test-utils'
import { DrawingStyleBar, placeBar } from './DrawingStyleBar'

const SEL: DrawSelection = {
  id: 'd1',
  tool: 'fib-retracement',
  hasText: false,
  color: '#4f8cff',
  lineWidth: 1.5,
  lineStyle: 'solid',
  locked: false,
  name: 'Fib Retracement',
  fill: { on: true, color: '#4f8cff', opacity: 0.06 },
  extend: { left: false, right: false },
  levels: true,
  box: { left: 100, top: 200, right: 300, bottom: 260 },
}

const LEVELS: DrawLevels = {
  levels: [
    { ratio: 0, color: '#787b86' },
    { ratio: 0.618, color: '#089981' },
  ],
  defaults: [{ ratio: 0 }, { ratio: 0.5 }, { ratio: 1 }],
  showLabels: true,
  label: (ratio) => `${ratio * 100}%`,
  color: () => '#787b86',
}

function bar(sel: Partial<DrawSelection> = {}) {
  const handlers = {
    onStyle: vi.fn(),
    onSettings: vi.fn(),
    onDelete: vi.fn(),
    onEditText: vi.fn(),
    onDuplicate: vi.fn(),
    onOrder: vi.fn(),
    onHide: vi.fn(),
    readLevels: vi.fn(() => LEVELS),
    onLevels: vi.fn(),
  }
  render(<DrawingStyleBar sel={{ ...SEL, ...sel }} {...handlers} />)
  return handlers
}

afterEach(cleanup)

describe('where the bar floats', () => {
  const pane = { width: 800, height: 500 }
  const size = { width: 300, height: 36 }

  it('sits centred above the selection', () => {
    expect(placeBar(SEL.box, pane, size)).toEqual({ left: 50, top: 154 })
  })

  it('drops below a selection at the top of the pane', () => {
    expect(placeBar({ left: 100, top: 20, right: 300, bottom: 60 }, pane, size)).toEqual({
      left: 50,
      top: 70,
    })
  })

  it('stays inside the pane and off the time axis', () => {
    const at = placeBar({ left: 760, top: 10, right: 900, bottom: 480 }, pane, size)
    expect(at.left).toBe(800 - 300 - 6)
    expect(at.top).toBe(6)
  })

  it('takes the top centre when the selection has no place on screen', () => {
    expect(placeBar(null, pane, size)).toEqual({ left: 250, top: 6 })
  })
})

describe('what each control writes', () => {
  it('names the selection', () => {
    bar()
    expect(screen.getByRole('toolbar', { name: 'Fib Retracement properties' })).toBeInTheDocument()
  })

  it('turns fill off and changes its opacity on release, once', () => {
    const { onSettings } = bar()
    fireEvent.click(screen.getByRole('button', { name: 'Fill' }))
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onSettings).toHaveBeenLastCalledWith({ 'style.fill': false })

    const slider = screen.getByRole('slider', { name: 'Fill opacity' })
    fireEvent.change(slider, { target: { value: '40' } })
    fireEvent.change(slider, { target: { value: '45' } })
    expect(onSettings).toHaveBeenCalledTimes(1)
    fireEvent.pointerUp(slider)
    expect(onSettings).toHaveBeenLastCalledWith({ 'style.fillOpacity': 0.45 })
  })

  it('extends to either side', () => {
    const { onSettings } = bar()
    fireEvent.click(screen.getByRole('button', { name: 'Extend' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Extend right' }))
    expect(onSettings).toHaveBeenCalledWith({ 'style.extendRight': true })
  })

  it('edits levels, adds one and resets to the tool’s own', () => {
    const { onLevels, onSettings } = bar()
    fireEvent.click(screen.getByRole('button', { name: 'Levels' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show level 61.8%' }))
    expect(onLevels).toHaveBeenLastCalledWith([
      { ratio: 0, color: '#787b86' },
      { ratio: 0.618, color: '#089981', enabled: false },
    ])

    fireEvent.click(screen.getByRole('button', { name: 'Add level' }))
    expect(onLevels.mock.lastCall?.[0].at(-1)).toMatchObject({ ratio: 0.236 })

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(onLevels).toHaveBeenLastCalledWith([{ ratio: 0 }, { ratio: 0.5 }, { ratio: 1 }])

    fireEvent.click(screen.getByRole('checkbox', { name: 'Show labels' }))
    expect(onSettings).toHaveBeenLastCalledWith({ 'style.showLabels': false })
  })

  it('duplicates, orders and hides from More', () => {
    const { onDuplicate, onOrder, onHide } = bar()
    const more = screen.getByRole('button', { name: 'More drawing actions' })
    fireEvent.click(more)
    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }))
    fireEvent.click(more)
    fireEvent.click(screen.getByRole('button', { name: 'Bring to front' }))
    fireEvent.click(more)
    fireEvent.click(screen.getByRole('button', { name: 'Send to back' }))
    fireEvent.click(more)
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }))
    expect(onDuplicate).toHaveBeenCalled()
    expect(onOrder.mock.calls).toEqual([['front'], ['back']])
    expect(onHide).toHaveBeenCalled()
  })

  it('offers no fill, extend or levels on a tool that has none', () => {
    bar({ tool: 'text', fill: null, extend: null, levels: false })
    expect(screen.queryByRole('button', { name: 'Fill' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Extend' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Levels' })).toBeNull()
  })
})
