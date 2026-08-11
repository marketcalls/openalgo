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

  it('normalizes decimal and exponent tick sizes without losing precision', async () => {
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
            id: 'small-tick',
            contractValid: true,
            symbol: 'SMALL_TICK',
            price: 1.5e-7,
            tickSize: 1e-7,
          }),
        ]}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Execute \(2\)/ }))

    await waitFor(() =>
      expect(submitBasket).toHaveBeenCalledWith(
        'api-key',
        'Precise ticks',
        expect.arrayContaining([
          expect.objectContaining({ symbol: 'LARGE_TICK', price: 102.5 }),
          expect.objectContaining({ symbol: 'SMALL_TICK', price: 2e-7 }),
        ])
      )
    )
  })
})
