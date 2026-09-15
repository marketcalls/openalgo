import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { useBrokerStore } from '@/stores/brokerStore'
import type { SearchRow } from '@/lib/trading/terminal'
import { SymbolSearchDialog } from './SymbolSearchDialog'

const ROWS: SearchRow[] = [
  { symbol: 'NIFTY100EW', exchange: 'NSE', name: 'KOTAKMAMC - NIFTY100EW' },
  { symbol: 'NIFTY100QUALTY30', exchange: 'NSE_INDEX', name: 'NIFTY100 Quality30' },
  { symbol: 'NIFTY18AUG2622350CE', exchange: 'NFO', name: 'NIFTY' },
]

function renderDialog(onPick: (row: SearchRow) => void = () => {}) {
  return render(
    <SymbolSearchDialog
      open
      onOpenChange={() => {}}
      search={async () => ROWS}
      onPick={onPick}
    />
  )
}

describe('SymbolSearchDialog', () => {
  beforeEach(() => {
    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'IN_stock',
        supported_exchanges: ['NSE', 'BSE', 'NFO', 'NSE_INDEX', 'BSE_INDEX'],
        leverage_config: false,
      },
      isLoaded: true,
    })
  })

  it('ranks an index above a same-scoring cash-equity match in ALL results', async () => {
    renderDialog()

    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY')

    await waitFor(() => expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument())

    // Dialog content is portaled to document.body, not the render() container.
    const symbols = Array.from(
      document.body.querySelectorAll('button[data-idx] span:first-child')
    ).map((el) => el.textContent)
    const indexPos = symbols.indexOf('NIFTY100QUALTY30')
    const cashPos = symbols.indexOf('NIFTY100EW')
    expect(indexPos).toBeGreaterThanOrEqual(0)
    expect(indexPos).toBeLessThan(cashPos)
  })

  it('shows an Index chip when the broker supports index exchanges', () => {
    renderDialog()

    expect(screen.getByRole('button', { name: 'Index' })).toBeInTheDocument()
  })

  it('filters to only index rows when the Index chip is selected', async () => {
    renderDialog()

    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY')
    await waitFor(() => expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Index' }))

    expect(screen.getByText('NIFTY100QUALTY30')).toBeInTheDocument()
    expect(screen.queryByText('NIFTY100EW')).not.toBeInTheDocument()
    expect(screen.queryByText('NIFTY18AUG2622350CE')).not.toBeInTheDocument()
  })

  /**
   * Symbol arithmetic. The operators build an expression in the box, and Enter
   * charts it instead of whatever the result list happens to be showing: those
   * rows match the last leg typed, so loading one would silently discard the
   * expression.
   */
  it('picks the expression on Enter rather than the highlighted row', async () => {
    const picked: SearchRow[] = []
    renderDialog((row) => picked.push(row))

    const box = screen.getByLabelText('Search symbol')
    await userEvent.type(box, 'NIFTY100EW/NIFTY100QUALTY30')
    await waitFor(() => expect(screen.getByText(/Press Enter to chart/)).toBeInTheDocument())
    await userEvent.type(box, '{Enter}')

    expect(picked).toHaveLength(1)
    expect(picked[0].symbol).toBe('NIFTY100EW/NIFTY100QUALTY30')
    expect(picked[0].expression).toBe(true)
  });

  it('still picks an ordinary row when the box holds a plain symbol', async () => {
    const picked: SearchRow[] = []
    renderDialog((row) => picked.push(row))

    const box = screen.getByLabelText('Search symbol')
    await userEvent.type(box, 'NIFTY')
    // Wait for a real result row, not merely for buttons to exist: the chips
    // and the operator keys are buttons too, so counting them passed before the
    // debounced search had returned anything to select.
    await waitFor(() => expect(screen.getByText('NIFTY100EW')).toBeInTheDocument())
    await userEvent.type(box, '{Enter}')

    expect(picked).toHaveLength(1)
    expect(picked[0].expression).toBeUndefined()
    expect(picked[0].exchange).not.toBe('')
  });

  it('the operator keys write into the box and the reciprocal wraps it', async () => {
    renderDialog()
    const box = screen.getByLabelText('Search symbol') as HTMLInputElement

    await userEvent.type(box, 'NIFTY100EW')
    await userEvent.click(screen.getByLabelText('Divide'))
    await userEvent.type(box, 'NIFTY100QUALTY30')
    expect(box.value).toBe('NIFTY100EW/NIFTY100QUALTY30')

    await userEvent.click(screen.getByLabelText('Reciprocal'))
    expect(box.value).toBe('1/(NIFTY100EW/NIFTY100QUALTY30)')
  });

  it('offers every operator the engine parses, exponentiation included', () => {
    renderDialog()
    for (const name of ['Divide', 'Subtract', 'Add', 'Multiply', 'Exponentiation', 'Reciprocal']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
  });

  it('warns that a computed chart cannot be traded', async () => {
    renderDialog()
    await userEvent.type(screen.getByLabelText('Search symbol'), 'NIFTY100EW/NIFTY100QUALTY30')
    await waitFor(() =>
      expect(screen.getByText(/cannot be traded/)).toBeInTheDocument()
    )
  });
})
