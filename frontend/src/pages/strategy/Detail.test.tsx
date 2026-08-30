import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  webClient: { get: rest.get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

import {
  fetchStrategyOrderbook,
  fetchStrategyTradebook,
  type StrategyLiveState,
  useBrokerBook,
} from '@/api/strategy_module'
import type { Order, Strategy } from '@/types/strategy_module'
import { OrdersTab, TradesTab } from './Detail'

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

let hookClient = client()

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={hookClient}>{children}</QueryClientProvider>
}

function renderWithQuery(ui: ReactNode) {
  return render(<QueryClientProvider client={client()}>{ui}</QueryClientProvider>)
}

const strategy = {
  id: 7,
  name: 'Broker truth',
  strategy_kind: 'batch',
  direction: 'both',
  universe_tab: 'weekly_monthly',
  underlying: 'NIFTY',
  underlying_exchange: 'NSE_INDEX',
  strategy_type: 'intraday',
  entry_time: null,
  exit_time: null,
  product: 'NRML',
  pricetype: 'MARKET',
  overall_sl_mtm: null,
  overall_target_mtm: null,
  lock_profit: null,
  trail_sl_to_entry: false,
  scheduler: null,
  live_enabled: false,
  webhook_locked: false,
  webhook_ip_allowlist: null,
  daily_loss_limit_inr: null,
  status: 'running',
  current_run_id: 42,
  created_at: '2026-05-28T03:45:00+00:00',
  updated_at: '2026-05-28T03:45:00+00:00',
  legs: [],
} satisfies Strategy

const live = {
  status: 'polling',
  runId: 42,
  checkpoint: null,
  legs: [],
  updatedAt: null,
  curve: [],
  isFetching: false,
  error: null,
  refresh: vi.fn(),
} satisfies StrategyLiveState

function localOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: 1,
    run_id: 42,
    leg_id: 3,
    kind: 'entry',
    broker_order_id: 'A1',
    position_ref: 'position-a',
    symbol: 'NIFTY28MAY2625000CE',
    exchange: 'NFO',
    action: 'BUY',
    qty: 50,
    pricetype: 'MARKET',
    price: 100,
    trigger_price: 0,
    status: 'open',
    placed_at: '2026-05-28T03:50:00+00:00',
    filled_at: null,
    avg_fill_price: null,
    filled_qty: null,
    reject_reason: null,
    ...overrides,
  }
}

beforeEach(() => {
  rest.get.mockReset()
  hookClient = client()
})

describe('broker book requests and cache ownership', () => {
  it('passes run_id to the broker tradebook request', async () => {
    rest.get.mockResolvedValue({ data: { status: 'success', data: [] } })

    await fetchStrategyTradebook(7, 42)

    expect(rest.get).toHaveBeenCalledWith('/strategy/api/strategies/7/tradebook', {
      params: { run_id: 42 },
      signal: undefined,
    })
  })

  it('normalizes broker order rows without borrowing local field values', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: {
          orders: [
            {
              orderid: 123,
              symbol: ' NIFTY28MAY2625000CE ',
              exchange: 'NFO',
              action: 'buy',
              quantity: '25',
              price: '101.50',
              trigger_price: null,
              pricetype: 'MARKET',
              product: 'NRML',
              order_status: 'Complete',
              timestamp: '09:20:01',
            },
          ],
          statistics: null,
        },
      },
    })

    const book = await fetchStrategyOrderbook(7, 42)

    expect(book?.orders[0]).toMatchObject({
      orderid: '123',
      symbol: 'NIFTY28MAY2625000CE',
      action: 'BUY',
      quantity: 25,
      price: 101.5,
      trigger_price: 0,
      order_status: 'complete',
    })
  })

  it('isolates run cache entries and ignores a stale prior-run response', async () => {
    let resolveFirst!: (value: string[] | null) => void
    let resolveSecond!: (value: string[] | null) => void
    const first = new Promise<string[] | null>((resolve) => {
      resolveFirst = resolve
    })
    const second = new Promise<string[] | null>((resolve) => {
      resolveSecond = resolve
    })
    const signals = new Map<number, AbortSignal>()
    const fetcher = vi.fn((_strategyId: number, runId?: number, signal?: AbortSignal) => {
      if (runId !== undefined && signal) signals.set(runId, signal)
      return runId === 41 ? first : second
    })

    const { result, rerender } = renderHook(
      ({ runId }) => useBrokerBook(7, runId, 'tradebook', fetcher, false, true),
      { initialProps: { runId: 41 }, wrapper }
    )
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(7, 41, expect.any(AbortSignal)))

    rerender({ runId: 42 })
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(7, 42, expect.any(AbortSignal)))
    expect(signals.get(41)?.aborted).toBe(true)

    await act(async () => resolveFirst(['old run']))
    expect(result.current.rows).toBeNull()

    await act(async () => resolveSecond(['current run']))
    await waitFor(() => expect(result.current.rows).toEqual(['current run']))
  })

  it('does not fetch while the tab is inactive or there is no run', () => {
    const fetcher = vi.fn(async () => [])
    const { rerender } = renderHook(
      ({ runId, active }) => useBrokerBook(7, runId, 'orderbook', fetcher, true, active),
      { initialProps: { runId: 42 as number | null, active: false }, wrapper }
    )

    expect(fetcher).not.toHaveBeenCalled()
    rerender({ runId: null, active: true })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('cancels an in-flight request when its tab becomes inactive', async () => {
    let requestSignal: AbortSignal | undefined
    const fetcher = vi.fn((_strategyId: number, _runId?: number, signal?: AbortSignal) => {
      requestSignal = signal
      return new Promise<string[] | null>(() => {})
    })
    const { rerender } = renderHook(
      ({ active }) => useBrokerBook(7, 42, 'orderbook', fetcher, true, active),
      { initialProps: { active: true }, wrapper }
    )
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce())

    rerender({ active: false })

    await waitFor(() => expect(requestSignal?.aborted).toBe(true))
  })
})

describe('strategy Orderbook broker truth', () => {
  it('uses the strategy current run while a stale live frame still names the prior run', async () => {
    rest.get.mockResolvedValue({
      data: { status: 'success', data: { orders: [], statistics: {} } },
    })

    renderWithQuery(
      <OrdersTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={live}
        orders={[]}
        loading={false}
        active
      />
    )

    await waitFor(() =>
      expect(rest.get).toHaveBeenCalledWith('/strategy/api/strategies/7/orderbook', {
        params: { run_id: 43 },
        signal: expect.any(AbortSignal),
      })
    )
    expect(await screen.findByText(/broker reports no orders for run #43/i)).toBeInTheDocument()
  })

  it('renders broker values first with local context and a visible disagreement', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: {
          orders: [
            {
              orderid: 'A1',
              symbol: 'NIFTY28MAY2625000CE',
              exchange: 'NFO',
              action: 'BUY',
              quantity: 25,
              price: 101,
              trigger_price: 0,
              pricetype: 'MARKET',
              product: 'NRML',
              order_status: 'complete',
              timestamp: '28-May-2026 09:20:01',
            },
          ],
          statistics: {},
        },
      },
    })

    renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    expect(await screen.findByText('Broker-confirmed orders')).toBeInTheDocument()
    expect(screen.getByText('25')).toBeInTheDocument()
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('entry')).toBeInTheDocument()
    expect(screen.getByText(/disagrees: quantity, price, status/i)).toBeInTheDocument()
  })

  it('labels local fallback when the broker endpoint is unavailable', async () => {
    rest.get.mockResolvedValue({
      data: { status: 'error', message: 'Broker session expired' },
    })

    renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    expect(
      await screen.findByText(/broker unavailable.*showing recorded strategy audit, which may lag/i)
    ).toBeInTheDocument()
    expect(screen.getByText('Strategy audit records')).toBeInTheDocument()
    expect(screen.queryByText('Broker-confirmed orders')).not.toBeInTheDocument()
  })

  it('treats an empty broker answer as available and still exposes local audit history', async () => {
    rest.get.mockResolvedValue({
      data: { status: 'success', data: { orders: [], statistics: {} } },
    })

    renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    expect(await screen.findByText(/broker reports no orders for run #42/i)).toBeInTheDocument()
    expect(screen.getByText('Strategy audit records')).toBeInTheDocument()
    expect(screen.queryByText(/broker unavailable/i)).not.toBeInTheDocument()
  })

  it('announces broker loading instead of showing a false empty state', () => {
    rest.get.mockReturnValue(new Promise(() => {}))

    renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    expect(screen.getByText(/loading broker orderbook/i)).toBeInTheDocument()
    expect(screen.queryByText(/broker reports no orders/i)).not.toBeInTheDocument()
  })
})

describe('strategy Tradebook broker truth', () => {
  it('renders broker fills as primary and preserves exact local leg context', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            orderid: 'A1',
            symbol: 'NIFTY28MAY2625000CE',
            exchange: 'NFO',
            product: 'NRML',
            action: 'BUY',
            quantity: 25,
            average_price: 101,
            trade_value: 2525,
            timestamp: '09:20:01',
          },
        ],
      },
    })

    renderWithQuery(
      <TradesTab
        strategy={strategy}
        live={live}
        orders={[localOrder({ status: 'complete', filled_qty: 50, avg_fill_price: 100 })]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText('Broker-confirmed trades')).toBeInTheDocument()
    expect(screen.getByText('2525.00')).toBeInTheDocument()
    expect(screen.getByText('Leg 3')).toBeInTheDocument()
    expect(screen.getByText(/disagrees: quantity, average price/i)).toBeInTheDocument()
  })

  it('matches a broker fill to a rejected local order with explicit filled quantity', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            orderid: 'A1',
            symbol: 'NIFTY28MAY2625000CE',
            exchange: 'NFO',
            product: 'NRML',
            action: 'BUY',
            quantity: 25,
            average_price: 103,
            trade_value: 2575,
            timestamp: '09:20:01',
          },
        ],
      },
    })

    renderWithQuery(
      <TradesTab
        strategy={strategy}
        live={live}
        orders={[localOrder({ status: 'rejected', filled_qty: 25, avg_fill_price: null })]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText('Leg 3')).toBeInTheDocument()
    expect(screen.getByText(/rejected.*position-a/i)).toBeInTheDocument()
    expect(screen.getByText('Matched')).toBeInTheDocument()
  })

  it('falls back to priced and unpriced terminal partial fills but omits zero-fill deaths', async () => {
    rest.get.mockResolvedValue({ data: { status: 'error', message: 'Session expired' } })

    renderWithQuery(
      <TradesTab
        strategy={strategy}
        live={live}
        orders={[
          localOrder({
            id: 2,
            symbol: 'BANKNIFTY28MAY2650000CE',
            status: 'rejected',
            filled_qty: 25,
            avg_fill_price: 100,
          }),
          localOrder({
            id: 3,
            symbol: 'FINNIFTY28MAY2625000PE',
            status: 'cancelled',
            filled_qty: 10,
            avg_fill_price: null,
          }),
          localOrder({
            id: 4,
            symbol: 'SBIN',
            status: 'rejected',
            filled_qty: null,
            avg_fill_price: 500,
          }),
        ]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText('Strategy audit records')).toBeInTheDocument()
    expect(screen.getByText('BANKNIFTY28MAY2650000CE')).toBeInTheDocument()
    const unpricedRow = screen.getByText('FINNIFTY28MAY2625000PE').closest('tr')
    expect(unpricedRow).not.toBeNull()
    expect(unpricedRow?.textContent).not.toContain('0.00')
    expect(screen.queryByText('SBIN')).not.toBeInTheDocument()
  })
})
