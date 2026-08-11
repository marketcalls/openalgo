import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tradingApi } from '@/api/trading'
import type { StrategyLeg } from '@/lib/strategyMath'
import { ExecuteBasketDialog } from './ExecuteBasketDialog'

vi.mock('@/api/trading', async () => {
  const actual = await vi.importActual<typeof import('@/api/trading')>('@/api/trading')
  return {
    ...actual,
    tradingApi: {
      ...actual.tradingApi,
      placeBasketOrder: vi.fn(),
    },
  }
})

vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn() },
}))

const submitBasket = vi.mocked(tradingApi.placeBasketOrder)

function leg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    id: 'leg-a',
    segment: 'OPTION',
    side: 'BUY',
    lots: 2,
    lotSize: 25,
    expiry: '28AUG26',
    strike: 25000,
    optionType: 'CE',
    price: 10.03,
    iv: 12,
    active: true,
    symbol: 'A',
    exchange: 'NFO',
    tickSize: 0.05,
    ...overrides,
  }
}

describe('ExecuteBasketDialog', () => {
  beforeEach(() => {
    submitBasket.mockReset()
    submitBasket.mockResolvedValue({ status: 'success', results: [] })
  })

  it('submits only validated open legs with their own lot and tick metadata', async () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Canonical contracts"
        apiKey="api-key"
        legs={[
          leg({ contractValid: true }),
          leg({
            id: 'leg-b',
            symbol: 'B',
            side: 'SELL',
            lots: 1,
            lotSize: 25,
            price: 101.04,
            tickSize: 0.1,
            contractValid: true,
          }),
          leg({ id: 'closed', symbol: 'CLOSED_SYMBOL', exitPrice: 0, contractValid: true }),
          leg({ id: 'stale', symbol: 'STALE_SYMBOL' }),
        ]}
      />
    )

    expect(screen.queryByText('CLOSED_SYMBOL')).not.toBeInTheDocument()
    expect(screen.queryByText('STALE_SYMBOL')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Execute \(2\)/ }))

    await waitFor(() =>
      expect(submitBasket).toHaveBeenCalledWith('api-key', 'Canonical contracts', [
        {
          symbol: 'A',
          exchange: 'NFO',
          action: 'BUY',
          quantity: 50,
          pricetype: 'LIMIT',
          product: 'NRML',
          price: 10.05,
          trigger_price: 0,
        },
        {
          symbol: 'B',
          exchange: 'NFO',
          action: 'SELL',
          quantity: 25,
          pricetype: 'LIMIT',
          product: 'NRML',
          price: 101,
          trigger_price: 0,
        },
      ])
    )
  })

  it('disables execution when no executable leg remains', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="No executable legs"
        apiKey="api-key"
        legs={[leg({ symbol: 'CLOSED_SYMBOL', exitPrice: 0, contractValid: true })]}
      />
    )

    expect(screen.queryByText('CLOSED_SYMBOL')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Execute \(0\)/ })).toBeDisabled()
  })

  it('excludes legs whose lots or lot size cannot produce an integer broker quantity', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Invalid quantities"
        apiKey="api-key"
        legs={[
          leg({ id: 'zero-lots', contractValid: true, symbol: 'ZERO_LOTS', lots: 0 }),
          leg({
            id: 'fractional-lots',
            contractValid: true,
            symbol: 'FRACTIONAL_LOTS',
            lots: 1.5,
          }),
          leg({
            id: 'zero-lot-size',
            contractValid: true,
            symbol: 'ZERO_LOT_SIZE',
            lotSize: 0,
          }),
          leg({
            id: 'fractional-lot-size',
            contractValid: true,
            symbol: 'FRACTIONAL_LOT_SIZE',
            lotSize: 12.5,
          }),
        ]}
      />
    )

    for (const symbol of ['ZERO_LOTS', 'FRACTIONAL_LOTS', 'ZERO_LOT_SIZE', 'FRACTIONAL_LOT_SIZE']) {
      expect(screen.queryByText(symbol)).not.toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: /Execute \(0\)/ })).toBeDisabled()
    expect(submitBasket).not.toHaveBeenCalled()
  })

  it('SB-18 uses contrast-safe colors for every order and instrument badge state', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Badge contrast"
        apiKey="api-key"
        legs={[
          leg({ contractValid: true, symbol: 'BUY_CALL' }),
          leg({
            id: 'sell-put',
            contractValid: true,
            symbol: 'SELL_PUT',
            side: 'SELL',
            optionType: 'PE',
          }),
          leg({
            id: 'future',
            contractValid: true,
            symbol: 'NIFTY28AUG26FUT',
            segment: 'FUTURE',
            strike: undefined,
            optionType: undefined,
          }),
        ]}
      />
    )

    expect(screen.getAllByText('B')[0]).toHaveClass('bg-emerald-700', 'text-white')
    expect(screen.getByText('S')).toHaveClass('bg-rose-700', 'text-white')
    expect(screen.getByText('CE')).toHaveClass('bg-emerald-700', 'text-white')
    expect(screen.getByText('PE')).toHaveClass('bg-rose-700', 'text-white')
    expect(screen.getByText('FUT')).toHaveClass('bg-sky-700', 'text-white')
  })

  it('preserves row and global choices when live metadata refreshes the same contracts', async () => {
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      exchange: 'NFO',
      strategyName: 'Preserve choices',
      apiKey: 'api-key',
    }
    const initialLegs = [
      leg({ contractValid: true }),
      leg({ id: 'leg-b', symbol: 'B', contractValid: true }),
    ]
    const view = render(<ExecuteBasketDialog {...props} legs={initialLegs} />)

    fireEvent.change(screen.getAllByDisplayValue('2')[0], { target: { value: '3' } })
    fireEvent.change(screen.getAllByDisplayValue('10.05')[0], { target: { value: '12.34' } })
    fireEvent.click(screen.getByRole('button', { name: 'MIS' }))
    fireEvent.click(screen.getByRole('button', { name: 'MKT' }))
    fireEvent.click(screen.getAllByRole('checkbox')[1])

    view.rerender(
      <ExecuteBasketDialog
        {...props}
        legs={initialLegs.map((item) => ({ ...item, marketPrice: 99.5 }))}
      />
    )

    expect(screen.getByDisplayValue('3')).toBeInTheDocument()
    expect(screen.getByDisplayValue('12.34')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')[1]).not.toBeChecked()
    expect(screen.getByRole('button', { name: /Execute \(1\)/ })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /Execute \(1\)/ }))
    await waitFor(() =>
      expect(submitBasket).toHaveBeenCalledWith('api-key', 'Preserve choices', [
        expect.objectContaining({
          symbol: 'A',
          quantity: 75,
          pricetype: 'MARKET',
          product: 'MIS',
          price: 0,
        }),
      ])
    )
  })

  it('rounds decimal and scientific tick prices half-up without binary drift', async () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Precise ticks"
        apiKey="api-key"
        legs={[
          leg({ contractValid: true, symbol: 'LARGE_TICK', price: 101.3, tickSize: 2.5 }),
          leg({
            id: 'decimal-half',
            contractValid: true,
            symbol: 'DECIMAL_HALF',
            price: 0.15,
            tickSize: 0.1,
          }),
          leg({
            id: 'cent-half',
            contractValid: true,
            symbol: 'CENT_HALF',
            price: 1.005,
            tickSize: 0.01,
          }),
          leg({
            id: 'small-tick',
            contractValid: true,
            symbol: 'SMALL_TICK',
            price: 1.5e-7,
            tickSize: 1e-7,
          }),
        ]}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Execute \(4\)/ }))

    await waitFor(() =>
      expect(submitBasket).toHaveBeenCalledWith(
        'api-key',
        'Precise ticks',
        expect.arrayContaining([
          expect.objectContaining({ symbol: 'LARGE_TICK', price: 102.5 }),
          expect.objectContaining({ symbol: 'DECIMAL_HALF', price: 0.2 }),
          expect.objectContaining({ symbol: 'CENT_HALF', price: 1.01 }),
          expect.objectContaining({ symbol: 'SMALL_TICK', price: 2e-7 }),
        ])
      )
    )
  })

  it('does not submit a nonpositive price after tick normalization', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Invalid price"
        apiKey="api-key"
        legs={[leg({ contractValid: true, price: -1, tickSize: 0.1 })]}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Execute \(1\)/ }))

    expect(submitBasket).not.toHaveBeenCalled()
  })

  it('blocks an overflowed tick price instead of submitting its off-tick source value', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={vi.fn()}
        exchange="NFO"
        strategyName="Overflow price"
        apiKey="api-key"
        legs={[leg({ contractValid: true, price: 1.7e308, tickSize: 1e308 })]}
      />
    )

    expect(screen.getByText('A: price is outside the supported tick range')).toBeInTheDocument()
    const execute = screen.getByRole('button', { name: /Execute \(1\)/ })
    expect(execute).toBeDisabled()
    fireEvent.click(execute)
    expect(submitBasket).not.toHaveBeenCalled()
  })
})
