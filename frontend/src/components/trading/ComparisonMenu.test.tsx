import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TerminalComparisonState } from '@/lib/trading/terminal'
import { cleanup, fireEvent, render, screen, waitFor } from '@/test/test-utils'
import { ComparisonMenu } from './ComparisonMenu'

vi.mock('./SymbolSearchDialog', () => ({
  SymbolSearchDialog: (props: {
    open: boolean
    mode: string
    title: string
    onPick: (row: { symbol: string; exchange: string }) => void
  }) =>
    props.open ? (
      <button
        type="button"
        aria-label={props.title}
        data-mode={props.mode}
        onClick={() => props.onPick({ symbol: 'INFY', exchange: 'NSE' })}
      >
        Choose INFY
      </button>
    ) : null,
}))
afterEach(cleanup)
const state: TerminalComparisonState = {
  mode: 'price',
  items: [
    {
      id: 'one',
      symbol: 'INFY',
      exchange: 'NSE',
      label: 'NSE:INFY',
      color: '#6688ff',
      status: 'loading',
    },
    {
      id: 'two',
      symbol: 'BHEL',
      exchange: 'NSE',
      label: 'NSE:BHEL',
      color: '#ee8844',
      status: 'error',
      error: 'No comparison history',
    },
  ],
}

describe('selected chart comparisons', () => {
  it('reports loading and missing history, and removes each comparison independently', () => {
    const remove = vi.fn(),
      mode = vi.fn()
    render(
      <ComparisonMenu
        state={state}
        search={async () => []}
        onAdd={async () => {}}
        onRemove={remove}
        onModeChange={mode}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Comparisons' }))
    expect(screen.getByText('Loading history')).toBeVisible()
    expect(screen.getByText('No comparison history')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Remove NSE:BHEL' }))
    expect(remove).toHaveBeenCalledExactlyOnceWith('two')
    fireEvent.change(screen.getByLabelText('Comparison scale'), { target: { value: 'percentage' } })
    expect(mode).toHaveBeenCalledExactlyOnceWith('percentage')
  })

  it('uses comparison search and reports a rejected add without an unhandled rejection', async () => {
    const add = vi.fn().mockRejectedValue(new Error('History unavailable'))
    render(
      <ComparisonMenu
        state={{ mode: 'price', items: [] }}
        search={async () => []}
        onAdd={add}
        onRemove={() => {}}
        onModeChange={() => {}}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Comparisons' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add comparison' }))
    const choose = screen.getByRole('button', { name: 'Add comparison symbol' })
    expect(choose).toHaveAttribute('data-mode', 'comparison')
    fireEvent.click(choose)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('History unavailable'))
    expect(add).toHaveBeenCalledExactlyOnceWith('INFY', 'NSE')
  })
})
