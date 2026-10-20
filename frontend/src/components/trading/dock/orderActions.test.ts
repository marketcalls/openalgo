import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DockOrder, DockPosition } from './blotter'
import { cancelDockOrder, closeDockPosition, type OrderActionContext } from './orderActions'

const fake = vi.hoisted(() => ({
  api: { cancelOrder: vi.fn(), closePosition: vi.fn() },
  toast: { success: vi.fn(), error: vi.fn() },
}))
vi.mock('@/api/trading', () => ({ tradingApi: fake.api }))
vi.mock('@/utils/toast', () => ({ showToast: fake.toast }))

const order = { orderid: '42', symbol: 'SBIN', exchange: 'NSE' } as DockOrder
const position = { symbol: 'SBIN', exchange: 'NSE', product: 'MIS', quantity: 10 } as DockPosition
const ctx = (over: Partial<OrderActionContext> = {}): OrderActionContext => ({
  appMode: 'live',
  refuse: vi.fn(() => false),
  refresh: vi.fn(),
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  fake.api.cancelOrder.mockResolvedValue({ status: 'success' })
  fake.api.closePosition.mockResolvedValue({ status: 'success' })
})

describe('the dock order actions', () => {
  it('cancel sends the order id and reports success', async () => {
    const c = ctx()
    expect(await cancelDockOrder(order, c)).toBe(true)
    expect(fake.api.cancelOrder).toHaveBeenCalledWith('42')
    expect(c.refresh).toHaveBeenCalled()
  })

  it('close sends symbol, exchange and product to the square-off route', async () => {
    expect(await closeDockPosition(position, ctx())).toBe(true)
    expect(fake.api.closePosition).toHaveBeenCalledWith('SBIN', 'NSE', 'MIS')
  })

  it('sends nothing while trading is locked', async () => {
    const c = ctx({ refuse: vi.fn(() => true) })
    expect(await cancelDockOrder(order, c)).toBe(false)
    expect(await closeDockPosition(position, c)).toBe(false)
    expect(fake.api.cancelOrder).not.toHaveBeenCalled()
    expect(fake.api.closePosition).not.toHaveBeenCalled()
  })

  it('leaves analyzer outcomes to the global analyzer toast', async () => {
    fake.api.closePosition.mockResolvedValue({ status: 'error', message: 'No position' })
    expect(await closeDockPosition(position, ctx({ appMode: 'analyzer' }))).toBe(false)
    expect(fake.toast.error).not.toHaveBeenCalled()
    expect(await closeDockPosition(position, ctx({ appMode: 'live' }))).toBe(false)
    expect(fake.toast.error).toHaveBeenCalledWith('No position', 'orders')
  })
})
