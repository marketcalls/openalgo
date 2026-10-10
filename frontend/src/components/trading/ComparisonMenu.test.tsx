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
      visible: true,
    },
    {
      id: 'two',
      symbol: 'BHEL',
      exchange: 'NSE',
      label: 'NSE:BHEL',
      color: '#ee8844',
      status: 'error',
      error: 'No comparison history',
      visible: true,
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
    fireEvent.change(screen.getByLabelText('Comparison scale'), { target: { value: 'percent' } })
    expect(mode).toHaveBeenCalledExactlyOnceWith('percent')
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

describe('comparison rows', () => {
  const ready: TerminalComparisonState = {
    mode: 'indexed',
    items: [
      {
        id: 'one',
        symbol: 'INFY',
        exchange: 'NSE',
        label: 'NSE:INFY',
        color: '#6688ff',
        status: 'ready',
        visible: true,
        close: 1523.4,
        change: -0.42,
      },
      {
        id: 'two',
        symbol: 'TCS',
        exchange: 'NSE',
        label: 'NSE:TCS',
        color: '#ee8844',
        status: 'ready',
        visible: false,
      },
      {
        id: 'three',
        symbol: 'BHEL',
        exchange: 'NSE',
        label: 'NSE:BHEL',
        color: '#22d3ee',
        status: 'error',
        error: 'No comparison history for this interval',
        visible: true,
      },
    ],
  }

  it('offers all four scales and explains the one chosen', () => {
    const mode = vi.fn()
    render(
      <ComparisonMenu
        state={ready}
        search={async () => []}
        onAdd={async () => {}}
        onRemove={() => {}}
        onModeChange={mode}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Comparisons' }))
    const select = screen.getByLabelText('Comparison scale') as HTMLSelectElement
    expect([...select.options].map((option) => option.text)).toEqual([
      'Price',
      'Percentage',
      'Indexed to 100',
      'Own scale',
    ])
    expect(select.value).toBe('indexed')
    expect(screen.getByText('Every line starts at 100')).toBeVisible()
    fireEvent.change(select, { target: { value: 'own' } })
    expect(mode).toHaveBeenCalledExactlyOnceWith('own')
  })

  it('shows the value and change, hides and shows a line, and retries a failed one', async () => {
    const toggle = vi.fn()
    const retry = vi.fn().mockRejectedValue(new Error('Still no history'))
    render(
      <ComparisonMenu
        state={ready}
        search={async () => []}
        onAdd={async () => {}}
        onRemove={() => {}}
        onModeChange={() => {}}
        onToggle={toggle}
        onRetry={retry}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Comparisons' }))
    expect(screen.getByText('1,523.40')).toBeVisible()
    expect(screen.getByText('-0.42%')).toBeVisible()
    expect(screen.getByText('Hidden')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Hide NSE:INFY' }))
    expect(toggle).toHaveBeenCalledWith('one', false)
    fireEvent.click(screen.getByRole('button', { name: 'Show NSE:TCS' }))
    expect(toggle).toHaveBeenCalledWith('two', true)
    expect(screen.queryByRole('button', { name: 'Retry NSE:INFY' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry NSE:BHEL' }))
    expect(retry).toHaveBeenCalledExactlyOnceWith('three')
    await waitFor(() =>
      expect(screen.getAllByRole('alert').at(-1)).toHaveTextContent('Still no history')
    )
  })
})
