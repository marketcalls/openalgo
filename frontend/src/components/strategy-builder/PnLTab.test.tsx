import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { StrategyLeg } from '@/lib/strategyMath'
import { makeFormatCurrency } from '@/lib/utils'
import { PnLTab } from './PnLTab'

const mocks = vi.hoisted(() => ({ useMarketData: vi.fn() }))

vi.mock('@/hooks/useMarketData', () => ({ useMarketData: mocks.useMarketData }))

function closedAtZero(): StrategyLeg {
  return {
    id: 'closed-zero',
    segment: 'OPTION',
    side: 'BUY',
    lots: 1,
    lotSize: 25,
    expiry: '13AUG26',
    strike: 24_600,
    optionType: 'CE',
    price: 100,
    iv: 12,
    active: true,
    symbol: 'NIFTY13AUG2624600CE',
    exitPrice: 0,
  }
}

describe('PnLTab closed-leg boundary', () => {
  it('shows zero exit as closed realised P&L without a live subscription', () => {
    mocks.useMarketData.mockReturnValue({
      data: new Map(),
      isConnected: false,
      isPaused: false,
      isFallbackMode: false,
    })

    render(
      <PnLTab
        legs={[closedAtZero()]}
        fnoExchange="NFO"
        fallbackPrices={{}}
        formatCurrency={makeFormatCurrency(null)}
      />
    )

    expect(screen.getByText('0 open · 1 closed')).toBeVisible()
    expect(screen.getByText('Closed')).toBeVisible()
    expect(screen.getByText('₹0.00')).toBeVisible()
    expect(screen.getAllByText('-₹2,500.00')).toHaveLength(2)
    expect(mocks.useMarketData).toHaveBeenCalledWith(
      expect.objectContaining({ symbols: [], enabled: false })
    )
  })

  it('uses the injected formatter for prices and P&L', () => {
    mocks.useMarketData.mockReturnValue({
      data: new Map(),
      isConnected: false,
      isPaused: false,
      isFallbackMode: false,
    })

    render(
      <PnLTab
        legs={[closedAtZero()]}
        fnoExchange="NFO"
        fallbackPrices={{}}
        formatCurrency={makeFormatCurrency('deltaexchange')}
      />
    )

    expect(screen.getByText('$0.00')).toBeVisible()
    expect(screen.getAllByText('-$2,500.00')).toHaveLength(2)
    expect(screen.getByRole('table')).not.toHaveTextContent('₹')
  })
})
