import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { SymbolHeader } from './SymbolHeader'

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

describe('SymbolHeader selectors', () => {
  it('SB-17 reflows the selector group instead of clipping it on narrow screens', () => {
    render(
      <SymbolHeader
        exchanges={[{ value: 'NFO', label: 'NFO' }]}
        selectedExchange="NFO"
        onExchangeChange={vi.fn()}
        underlyings={['NIFTY']}
        selectedUnderlying="NIFTY"
        onUnderlyingChange={vi.fn()}
        underlyingOpen={false}
        onUnderlyingOpenChange={vi.fn()}
        expiries={['13AUG26']}
        selectedExpiry="13AUG26"
        onExpiryChange={vi.fn()}
        spotPrice={24_600}
        futuresPrice={24_620}
        lotSize={75}
        atmIv={12.5}
        daysToExpiry={2}
        onRefresh={vi.fn()}
        isRefreshing={false}
        connectionStatus="stale"
      />
    )

    const header = screen.getByTestId('symbol-header')
    const selectors = screen.getByTestId('symbol-selectors')
    expect(header).not.toHaveClass('overflow-hidden')
    expect(selectors).toHaveClass('grid', 'w-full', 'min-w-0', 'grid-cols-1', 'sm:w-auto')
    expect(selectors).not.toHaveClass('overflow-hidden')
    expect(screen.getByTestId('symbol-metrics')).toHaveClass('overflow-hidden', 'rounded-b-xl')
    for (const name of ['Derivative exchange', 'Underlying', 'Option expiry']) {
      expect(screen.getByRole('combobox', { name })).toHaveClass('w-full', 'min-w-0')
    }
  })

  it('exposes the strategy identity controls by their trading meaning', async () => {
    const onExpiryChange = vi.fn()

    render(
      <SymbolHeader
        exchanges={[
          { value: 'NFO', label: 'NFO' },
          { value: 'BFO', label: 'BFO' },
        ]}
        selectedExchange="NFO"
        onExchangeChange={vi.fn()}
        underlyings={['NIFTY', 'BANKNIFTY']}
        selectedUnderlying="NIFTY"
        onUnderlyingChange={vi.fn()}
        underlyingOpen={false}
        onUnderlyingOpenChange={vi.fn()}
        expiries={['13AUG26', '18AUG26']}
        selectedExpiry="13AUG26"
        onExpiryChange={onExpiryChange}
        spotPrice={24_600}
        futuresPrice={24_620}
        lotSize={75}
        atmIv={12.5}
        daysToExpiry={2}
        onRefresh={vi.fn()}
        isRefreshing={false}
        connectionStatus="stale"
      />
    )

    expect(screen.getByRole('combobox', { name: 'Derivative exchange' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Underlying' })).toHaveTextContent('NIFTY')

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Option expiry' }), {
      key: 'ArrowDown',
    })
    fireEvent.click(await screen.findByRole('option', { name: '18AUG26' }))

    expect(onExpiryChange).toHaveBeenCalledWith('18AUG26')
  })

  it('renders every live connection transition explicitly', () => {
    const props = {
      exchanges: [{ value: 'NFO', label: 'NFO' }],
      selectedExchange: 'NFO',
      onExchangeChange: vi.fn(),
      underlyings: ['NIFTY'],
      selectedUnderlying: 'NIFTY',
      onUnderlyingChange: vi.fn(),
      underlyingOpen: false,
      onUnderlyingOpenChange: vi.fn(),
      expiries: ['13AUG26'],
      selectedExpiry: '13AUG26',
      onExpiryChange: vi.fn(),
      spotPrice: 24_600,
      futuresPrice: 24_620,
      lotSize: 75,
      atmIv: 12.5,
      daysToExpiry: 2,
      onRefresh: vi.fn(),
      isRefreshing: false,
    }

    const { rerender } = render(<SymbolHeader {...props} connectionStatus="idle" />)
    expect(screen.getByText('Idle')).toBeInTheDocument()

    rerender(<SymbolHeader {...props} connectionStatus="refreshing" isRefreshing />)
    expect(screen.getByText('Refreshing')).toBeInTheDocument()

    rerender(<SymbolHeader {...props} connectionStatus="stale" />)
    expect(screen.getByText('Stale')).toBeInTheDocument()

    rerender(<SymbolHeader {...props} connectionStatus="live" />)
    expect(screen.getByText('Live')).toBeInTheDocument()
  })
})
