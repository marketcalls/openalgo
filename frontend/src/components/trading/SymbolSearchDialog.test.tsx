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

function renderDialog() {
  return render(
    <SymbolSearchDialog
      open
      onOpenChange={() => {}}
      search={async () => ROWS}
      onPick={() => {}}
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
})
