/**
 * The GTT tab under a host that can refuse: the trading dock passes its
 * replay lock, and neither a cancel nor a modify may reach the broker while
 * it says no. The order book page passes nothing and is unchanged.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tradingApi } from '@/api/trading'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import type { GttOrder } from '@/types/trading'
import GttTab from './GttTab'

vi.mock('@/api/trading', async () => {
  const actual = await vi.importActual<typeof import('@/api/trading')>('@/api/trading')
  return {
    ...actual,
    tradingApi: {
      ...actual.tradingApi,
      getGttOrderbook: vi.fn(),
      cancelGttOrder: vi.fn(),
      modifyGttOrder: vi.fn(),
    },
  }
})

vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: null } }),
}))

const getGttOrderbook = vi.mocked(tradingApi.getGttOrderbook)
const cancelGttOrder = vi.mocked(tradingApi.cancelGttOrder)

const gtt: GttOrder = {
  trigger_id: 'T1',
  trigger_type: 'single',
  status: 'active',
  symbol: 'SBIN',
  exchange: 'NSE',
  trigger_prices: [800],
  last_price: 790,
  legs: [{ action: 'BUY', quantity: 10, price: 801, pricetype: 'LIMIT', product: 'CNC' }],
  created_at: '2026-09-04T09:30:00',
  expires_at: '2027-09-04T09:30:00',
}

describe('GttTab under a refusing host', () => {
  beforeEach(() => {
    getGttOrderbook.mockReset()
    cancelGttOrder.mockReset()
    getGttOrderbook.mockResolvedValue({ status: 'success', data: [gtt] } as never)
  })

  it('does not cancel while the host refuses', async () => {
    const refuse = vi.fn(() => true)
    render(<GttTab refuse={refuse} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel GTT T1' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel GTT' }))
    await waitFor(() => expect(refuse).toHaveBeenCalled())
    expect(cancelGttOrder).not.toHaveBeenCalled()
  })

  it('does not open the modify dialog while the host refuses', async () => {
    const refuse = vi.fn(() => true)
    render(<GttTab refuse={refuse} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Modify GTT T1' }))
    expect(refuse).toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('cancels as before once the host allows it', async () => {
    cancelGttOrder.mockResolvedValue({ status: 'success', data: { trigger_id: 'T1' } } as never)
    render(<GttTab refuse={() => false} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel GTT T1' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel GTT' }))
    await waitFor(() => expect(cancelGttOrder).toHaveBeenCalledWith('T1'))
  })
})
