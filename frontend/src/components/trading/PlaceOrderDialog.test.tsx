/**
 * The order ticket the chart opens while One-Click is off. What is pinned:
 * the Lots box reads the lots the ticket carries (a 150-unit ticket on a
 * 75-lot contract is 2, not 1, and it places 150 either way); a caller's own
 * route takes the confirmed order instead of the bare API post; and the
 * dialog can be portalled into the caller, for a fullscreen pane.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tradingApi } from '@/api/trading'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { showToast } from '@/utils/toast'
import { lotsFor, PlaceOrderDialog } from './PlaceOrderDialog'

vi.mock('@/api/trading', async () => {
  const actual = await vi.importActual<typeof import('@/api/trading')>('@/api/trading')
  return {
    ...actual,
    tradingApi: { ...actual.tradingApi, placeOrder: vi.fn() },
  }
})

vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key' }),
}))

vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: () => ({
    data: {
      ltp: 100,
      close: 99,
      change: 1,
      changePercent: 1.01,
      bidPrice: 99.95,
      askPrice: 100.05,
      bidSize: 10,
      askSize: 10,
      depth: undefined,
    },
    isLive: false,
    isConnected: false,
    isLoading: false,
    isPaused: false,
    isFallbackMode: false,
    dataSource: 'none',
    refresh: async () => {},
  }),
}))

const placeOrder = vi.mocked(tradingApi.placeOrder)

const nifty = {
  open: true,
  onOpenChange: () => {},
  symbol: 'NIFTY28MAR2420800CE',
  exchange: 'NFO',
  action: 'BUY' as const,
  quantity: 150,
  lotSize: 75,
  tickSize: 0.05,
  product: 'NRML' as const,
  priceType: 'MARKET' as const,
  strategy: 'chart-trading',
}

describe('lotsFor', () => {
  it('reads the lot count out of a quantity in units', () => {
    expect(lotsFor(150, 75)).toBe(2)
    expect(lotsFor(75, 75)).toBe(1)
    expect(lotsFor(1, 1)).toBe(1)
  })

  it('is one lot when nothing was supplied, as the option chain relies on', () => {
    expect(lotsFor(undefined, 75)).toBe(1)
    expect(lotsFor(150, 0)).toBe(1)
  })
})

describe('PlaceOrderDialog', () => {
  beforeEach(() => {
    placeOrder.mockReset()
  })

  it('shows the lots a units quantity stands for, over the same total', () => {
    render(<PlaceOrderDialog {...nifty} />)
    expect(screen.getByRole('spinbutton')).toHaveValue(2)
    expect(screen.getByText('Total qty: 150')).toBeInTheDocument()
  })

  it('sends the confirmed order through the caller route and never the API', async () => {
    const place = vi.fn(async () => ({ orderId: 'ORD-1' }))
    const onSuccess = vi.fn()
    render(<PlaceOrderDialog {...nifty} place={place} onSuccess={onSuccess} />)
    await userEvent.click(screen.getByRole('button', { name: 'Place BUY Order' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('ORD-1'))
    expect(place).toHaveBeenCalledWith({
      symbol: 'NIFTY28MAR2420800CE',
      exchange: 'NFO',
      action: 'BUY',
      quantity: 150,
      pricetype: 'MARKET',
      product: 'NRML',
    })
    expect(placeOrder).not.toHaveBeenCalled()
  })

  it('shows the route refusal and keeps the ticket open', async () => {
    const reason = 'caller expects live mode but the OpenAlgo server is in analyzer mode'
    const place = vi.fn(async () => {
      throw new Error(reason)
    })
    const onError = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <PlaceOrderDialog {...nifty} place={place} onError={onError} onOpenChange={onOpenChange} />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Place BUY Order' }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(reason))
    expect(showToast.error).toHaveBeenCalledWith(reason, 'orders')
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(placeOrder).not.toHaveBeenCalled()
  })

  it('posts through the API with the key and strategy when no route is given', async () => {
    placeOrder.mockResolvedValue({ status: 'success', orderid: 'ORD-2' } as never)
    const onSuccess = vi.fn()
    render(<PlaceOrderDialog {...nifty} onSuccess={onSuccess} />)
    await userEvent.click(screen.getByRole('button', { name: 'Place BUY Order' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('ORD-2'))
    expect(placeOrder).toHaveBeenCalledWith(
      expect.objectContaining({
        apikey: 'test-api-key',
        strategy: 'chart-trading',
        quantity: 150,
      })
    )
  })

  it('renders inside the container it is given', () => {
    const host = document.createElement('div')
    host.id = 'fullscreen-pane'
    document.body.appendChild(host)
    try {
      render(<PlaceOrderDialog {...nifty} container={host} />)
      expect(host.querySelector('[role="dialog"]')).not.toBeNull()
    } finally {
      host.remove()
    }
  })
})
