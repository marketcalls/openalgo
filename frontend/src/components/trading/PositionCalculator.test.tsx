import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { PositionCalculator } from './PositionCalculator'

const mocks = vi.hoisted(() => ({ cash: 10000 }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: (select: (s: unknown) => unknown) =>
    select({ apiKey: 'test', user: { broker: 'test' } }),
}))
vi.mock('@/api/trading', () => ({
  tradingApi: {
    getFunds: async () => ({ status: 'success', data: { availablecash: mocks.cash } }),
  },
}))
vi.mock('@/api/intradayLeverage', () => ({
  intradayLeverageApi: {
    getMultiplier: async () => ({ status: 'success', data: { multiplier: 1 } }),
  },
}))
vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: () => ({ data: { ltp: 100 }, isLoading: false }),
}))

const props = {
  open: true,
  onOpenChange: vi.fn(),
  symbol: 'SBIN',
  exchange: 'NSE',
  side: 'BUY' as const,
  ltp: 100,
}

beforeEach(() => {
  mocks.cash = 10000
})

it('preserves the clicked limit price and type through confirmation', async () => {
  const confirm = vi.fn()
  render(
    <PositionCalculator
      {...props}
      quantity={20}
      orderType="LIMIT"
      price={105}
      onConfirm={confirm}
    />
  )
  const buy = screen.getByRole('button', { name: /BUY 20/ })
  await waitFor(() => expect(buy).toBeEnabled())
  await userEvent.click(buy)
  expect(confirm).toHaveBeenCalledWith(
    expect.objectContaining({ quantity: 20, price: 105, orderType: 'LIMIT' })
  )
})

it('allows the full holding exit with zero cash and rejects overselling', async () => {
  mocks.cash = 0
  const confirm = vi.fn()
  render(
    <PositionCalculator
      {...props}
      side="SELL"
      quantity={70}
      maxExitQuantity={70}
      tradeType="OVERNIGHT"
      onConfirm={confirm}
    />
  )
  const sell = screen.getByRole('button', { name: /SELL 70/ })
  await waitFor(() => expect(sell).toBeEnabled())
  await userEvent.click(sell)
  expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ quantity: 70, product: 'CNC' }))
})

it('rejects a manually entered partial lot instead of silently changing order size', async () => {
  render(
    <PositionCalculator {...props} exchange="NFO" lotSize={10} quantity={35} onConfirm={vi.fn()} />
  )
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('whole multiple of 10'))
  expect(screen.getByRole('button', { name: /BUY 35/ })).toBeDisabled()
})

it('does not offer an unsupported GTT entry', () => {
  render(<PositionCalculator {...props} onConfirm={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'GTT' })).not.toBeInTheDocument()
})
