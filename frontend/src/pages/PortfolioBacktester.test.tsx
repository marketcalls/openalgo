import { fireEvent, render, screen, userEvent } from '@/test/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PortfolioBacktester from './PortfolioBacktester'

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: [], isFetching: false }),
}))

describe('PortfolioBacktester', () => {
  it('associates static control labels and preserves their change behavior', async () => {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
    Element.prototype.setPointerCapture = vi.fn()
    Element.prototype.releasePointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(<PortfolioBacktester />)

    const start = screen.getByLabelText('Start')
    const end = screen.getByLabelText('End')
    const source = screen.getByLabelText('Data source')
    const riskFree = screen.getByLabelText('Risk-free rate (%)')
    const originalIds = [start.id, end.id, source.id, riskFree.id]

    expect(originalIds.every(Boolean)).toBe(true)
    expect(new Set(originalIds).size).toBe(4)

    fireEvent.change(start, { target: { value: '2024-01-02' } })
    fireEvent.change(end, { target: { value: '2025-01-02' } })
    fireEvent.change(riskFree, { target: { value: '6.5' } })
    await user.click(source)
    await user.click(await screen.findByRole('option', { name: 'Historify (local)' }))

    expect(start).toHaveValue('2024-01-02')
    expect(end).toHaveValue('2025-01-02')
    expect(riskFree).toHaveValue(6.5)
    expect(source).toHaveTextContent('Historify (local)')

    rerender(<PortfolioBacktester />)

    expect([
      screen.getByLabelText('Start').id,
      screen.getByLabelText('End').id,
      screen.getByLabelText('Data source').id,
      screen.getByLabelText('Risk-free rate (%)').id,
    ]).toEqual(originalIds)
  })
})
