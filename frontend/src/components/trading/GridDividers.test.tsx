import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseAreas } from '@/lib/trading/gridSizes'
import { act, cleanup, fireEvent, render } from '@/test/test-utils'
import { GridDividers } from './GridDividers'

const cells = parseAreas('"a b" "c d"')
const weights = { columns: [1, 1], rows: [1, 1] }

beforeEach(() => {
  // The layer measures itself: an 808 x 608 grid leaves 400 x 300 for each chart.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: 824,
    height: 624,
    top: 0,
    left: 0,
    right: 824,
    bottom: 624,
    x: 0,
    y: 0,
    toJSON() {},
  } as DOMRect)
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0)
    return 1
  })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('grid dividers', () => {
  it('sits in the gaps between the charts, costing the plot nothing', () => {
    const view = render(
      <GridDividers
        cells={cells}
        weights={weights}
        onChange={() => {}}
        onCommit={() => {}}
        onReset={() => {}}
      />
    )
    const column = view.getByRole('separator', { name: 'Resize chart columns' })
    // 8px padding, a 400px chart, then the 8px gap the divider fills.
    expect(column.style.left).toBe('408px')
    expect(column.style.width).toBe('8px')
    const row = view.getByRole('separator', { name: 'Resize chart rows' })
    expect(row.style.top).toBe('308px')
    expect(row.style.height).toBe('8px')
  })

  it('resizes the charts either side as it is dragged and keeps the split on release', () => {
    const onChange = vi.fn()
    const onCommit = vi.fn()
    const view = render(
      <GridDividers
        cells={cells}
        weights={weights}
        onChange={onChange}
        onCommit={onCommit}
        onReset={() => {}}
      />
    )
    const column = view.getByRole('separator', { name: 'Resize chart columns' })
    act(() => {
      fireEvent.pointerDown(column, { button: 0, clientX: 412, pointerId: 1 })
      fireEvent.pointerMove(column, { clientX: 512, pointerId: 1 })
      fireEvent.pointerUp(column, { clientX: 512, pointerId: 1 })
    })
    expect(onChange).toHaveBeenCalled()
    const kept = onCommit.mock.calls[0][0]
    expect(kept.columns[0]).toBeCloseTo(1.25, 3)
    expect(kept.columns[1]).toBeCloseTo(0.75, 3)
    expect(kept.rows).toEqual([1, 1])
  })

  it('goes back to the layout sizes on a double-click, and moves with the arrow keys', () => {
    const onReset = vi.fn()
    const onCommit = vi.fn()
    const view = render(
      <GridDividers
        cells={cells}
        weights={weights}
        onChange={() => {}}
        onCommit={onCommit}
        onReset={onReset}
      />
    )
    const row = view.getByRole('separator', { name: 'Resize chart rows' })
    fireEvent.doubleClick(row)
    expect(onReset).toHaveBeenCalledOnce()
    fireEvent.keyDown(row, { key: 'ArrowDown' })
    expect(onCommit.mock.calls[0][0].rows[0]).toBeGreaterThan(1)
  })
})
