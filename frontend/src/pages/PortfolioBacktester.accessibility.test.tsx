import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@/test/test-utils'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import PortfolioBacktester from './PortfolioBacktester'

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PortfolioBacktester />
    </QueryClientProvider>
  )
}

describe('PortfolioBacktester accessibility', () => {
  it('associates each static label with its control', () => {
    renderPage()

    expect(screen.getByLabelText('Start')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('End')).toHaveAttribute('type', 'date')
    expect(screen.getByRole('combobox', { name: 'Data source' })).toBeInTheDocument()
    expect(screen.getByLabelText('Risk-free rate (%)')).toHaveAttribute('type', 'number')
  })

  it('assigns a unique id to each static control', () => {
    renderPage()

    const start = screen.getByLabelText('Start')
    const end = screen.getByLabelText('End')
    const source = screen.getByLabelText('Data source')
    const riskFree = screen.getByLabelText('Risk-free rate (%)')
    const ids = [start.id, end.id, source.id, riskFree.id]

    expect(ids.every(Boolean)).toBe(true)
    expect(new Set(ids).size).toBe(4)
  })

  it('preserves the static controls change behavior', async () => {
    renderPage()

    const start = screen.getByLabelText('Start')
    const end = screen.getByLabelText('End')
    const source = screen.getByLabelText('Data source')
    const riskFree = screen.getByLabelText('Risk-free rate (%)')

    fireEvent.change(start, { target: { value: '2024-01-02' } })
    fireEvent.change(end, { target: { value: '2025-01-02' } })
    fireEvent.change(riskFree, { target: { value: '6.5' } })
    fireEvent.keyDown(source, { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Historify (local)' }))

    expect(start).toHaveValue('2024-01-02')
    expect(end).toHaveValue('2025-01-02')
    expect(riskFree).toHaveValue(6.5)
    expect(source).toHaveTextContent('Historify (local)')
  })
})
