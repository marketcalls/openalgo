import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
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
  fetchStrategyPositions,
  fetchStrategyTradebook,
  type StrategyLiveState,
  useBrokerBook,
} from '@/api/strategy_module'
import type { Order, Strategy } from '@/types/strategy_module'
import { OrdersTab, PositionsTab, TradesTab } from './Detail'

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
      trigger_price: null,
      order_status: 'complete',
    })
  })

  it('preserves real zeroes but marks invalid broker numerics unavailable', async () => {
    rest.get
      .mockResolvedValueOnce({
        data: {
          status: 'success',
          data: {
            orders: [
              {
                orderid: 'A1',
                quantity: 'not-a-number',
                price: null,
                trigger_price: '0',
              },
            ],
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          status: 'success',
          data: [
            {
              orderid: 'A1',
              quantity: Number.POSITIVE_INFINITY,
              average_price: '',
              trade_value: '0',
            },
          ],
        },
      })

    const orderbook = await fetchStrategyOrderbook(7, 42)
    const tradebook = await fetchStrategyTradebook(7, 42)

    expect(orderbook?.orders[0]).toMatchObject({ quantity: null, price: null, trigger_price: 0 })
    expect(tradebook?.[0]).toMatchObject({
      quantity: null,
      average_price: null,
      trade_value: 0,
    })
  })

  it('normalizes missing and invalid broker position numerics without losing real zero', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            symbol: 'MISSING',
            exchange: 'NFO',
            product: 'NRML',
          },
          {
            symbol: 'INVALID',
            exchange: 'NFO',
            product: 'NRML',
            quantity: false,
            average_price: 'not-a-number',
            ltp: Number.POSITIVE_INFINITY,
            pnl: '',
          },
          {
            symbol: 'ZERO',
            exchange: 'NFO',
            product: 'NRML',
            quantity: '0',
            average_price: 0,
            ltp: '0',
            pnl: 0,
          },
        ],
      },
    })

    const positions = await fetchStrategyPositions(7, 42)

    expect(positions?.[0]).toMatchObject({
      quantity: null,
      average_price: null,
      ltp: null,
      pnl: null,
    })
    expect(positions?.[1]).toMatchObject({
      quantity: null,
      average_price: null,
      ltp: null,
      pnl: null,
    })
    expect(positions?.[2]).toMatchObject({
      quantity: 0,
      average_price: 0,
      ltp: 0,
      pnl: 0,
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
    const { result, rerender } = renderHook(
      ({ runId, active }) => useBrokerBook(7, runId, 'orderbook', fetcher, true, active),
      { initialProps: { runId: 42 as number | null, active: false }, wrapper }
    )

    expect(fetcher).not.toHaveBeenCalled()
    expect(result.current.active).toBe(false)
    rerender({ runId: null, active: true })
    expect(fetcher).not.toHaveBeenCalled()
    expect(result.current.active).toBe(false)
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
  it('does not claim broker truth when no run exists and labels the local audit fallback', async () => {
    renderWithQuery(
      <OrdersTab
        strategy={{ ...strategy, status: 'stopped', current_run_id: null }}
        live={{ ...live, runId: null }}
        orders={[localOrder({ run_id: 41 })]}
        loading={false}
        active
      />
    )

    expect(rest.get).not.toHaveBeenCalled()
    expect(
      screen.getByText(/broker orderbook was not requested because no strategy run is available/i)
    ).toBeInTheDocument()
    expect(screen.getByText('Strategy audit records')).toBeInTheDocument()
    expect(screen.queryByText('Broker-confirmed orders')).not.toBeInTheDocument()
  })

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

  it('renders unavailable broker order numerics without fabricating zero', async () => {
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
              quantity: false,
              price: 'invalid',
              trigger_price: null,
              pricetype: 'MARKET',
              product: 'NRML',
              order_status: 'open',
              timestamp: null,
            },
          ],
          statistics: {},
        },
      },
    })

    const rendered = renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    const symbol = await screen.findByText('NIFTY28MAY2625000CE')
    const row = symbol.closest('tr')
    expect(row).not.toBeNull()
    expect(
      within(row as HTMLTableRowElement).getAllByText('Unavailable').length
    ).toBeGreaterThanOrEqual(4)
    expect(row?.textContent).not.toContain('0.00')
    expect(rendered.container.textContent).not.toContain('â€”')
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

describe('strategy Positions broker truth', () => {
  it('renders invalid broker position numerics and direction as unavailable', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            symbol: 'INVALID',
            exchange: 'NFO',
            product: 'NRML',
            quantity: null,
            average_price: 'bad',
            ltp: Number.NaN,
            pnl: '',
          },
        ],
      },
    })

    renderWithQuery(
      <PositionsTab strategy={strategy} live={live} orders={[]} runs={[]} loading={false} active />
    )

    const symbol = await screen.findByText('INVALID')
    const row = symbol.closest('tr')
    expect(row).not.toBeNull()
    expect(
      within(row as HTMLTableRowElement).getAllByText('Unavailable').length
    ).toBeGreaterThanOrEqual(5)
    expect(within(row as HTMLTableRowElement).queryByText('flat')).not.toBeInTheDocument()
    expect(row?.textContent).not.toContain('NaN')
    expect(row?.textContent).not.toContain('Infinity')
    expect(row?.textContent).not.toContain('0.00')
  })

  it('preserves broker-confirmed numeric zero and classifies zero quantity as flat', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            symbol: 'ZERO',
            exchange: 'NFO',
            product: 'NRML',
            quantity: 0,
            average_price: 0,
            ltp: 0,
            pnl: 0,
          },
        ],
      },
    })

    renderWithQuery(
      <PositionsTab strategy={strategy} live={live} orders={[]} runs={[]} loading={false} active />
    )

    const symbol = await screen.findByText('ZERO')
    const row = symbol.closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getByText('flat')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('0')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getAllByText(/0\.00/).length).toBeGreaterThanOrEqual(
      3
    )
  })

  it('uses the current strategy run consistently when the live frame is stale', async () => {
    rest.get.mockResolvedValue({ data: { status: 'success', data: [] } })

    renderWithQuery(
      <PositionsTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={live}
        orders={[]}
        runs={[]}
        loading={false}
        active
      />
    )

    await waitFor(() =>
      expect(rest.get).toHaveBeenCalledWith('/strategy/api/strategies/7/positions', {
        params: { run_id: 43 },
        signal: expect.any(AbortSignal),
      })
    )
    const header = screen.getByText('Strategy positions').closest('[data-slot="card-header"]')
    expect(header?.textContent).toContain('Run #43.')
    expect(header?.textContent).not.toContain('Run #42.')
  })

  it('does not value the current fallback with legs from a stale prior-run frame', async () => {
    rest.get.mockResolvedValue({
      data: { status: 'error', message: 'Broker session expired' },
    })
    const staleLeg = {
      leg_id: 3,
      position: 'B' as const,
      symbol: 'NIFTY28MAY2625000CE',
      exchange: 'NFO',
      lots: 1,
      qty: 50,
      entry_order_id: 1,
      entry_status: 'complete',
      entry_avg: 100,
      exit_order_id: null,
      exit_kind: null,
      exit_avg: null,
      ltp: 200,
      mtm: 5000,
      realized_pnl: 0,
      status: 'open' as const,
      tick_source: 'ws' as const,
      sl_pts: null,
      target_pts: null,
      trail_x: 0,
      trail_y: 0,
      effective_sl: null,
      effective_target: null,
      trail_active: false,
      highest_price: 200,
      lowest_price: 100,
    }

    renderWithQuery(
      <PositionsTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={{ ...live, runId: 42, legs: [staleLeg] }}
        orders={[
          localOrder({
            run_id: 43,
            status: 'complete',
            filled_qty: 50,
            avg_fill_price: 100,
          }),
        ]}
        runs={[]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText(/broker did not answer/i)).toBeInTheDocument()
    const row = screen.getByText('NIFTY28MAY2625000CE').closest('tr')
    expect(row).not.toBeNull()
    expect(
      within(row as HTMLTableRowElement).getAllByText('Unavailable').length
    ).toBeGreaterThanOrEqual(2)
    expect(row?.textContent).not.toContain('200.00')
    expect(row?.textContent).not.toContain('5,000.00')
    const header = screen.getByText('Strategy positions').closest('[data-slot="card-header"]')
    expect(header?.textContent).toContain('Run #43.')
  })

  it('keeps prior-run fills for residual exposure and lifetime realized fallback', async () => {
    rest.get.mockResolvedValue({
      data: { status: 'error', message: 'Broker session expired' },
    })

    renderWithQuery(
      <PositionsTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={{ ...live, runId: 43, legs: [] }}
        orders={[
          localOrder({
            id: 10,
            run_id: 41,
            status: 'complete',
            filled_qty: 50,
            avg_fill_price: 100,
            filled_at: '2026-05-28T03:50:00+00:00',
          }),
          localOrder({
            id: 11,
            run_id: 41,
            kind: 'exit_eod',
            action: 'SELL',
            status: 'complete',
            filled_qty: 50,
            avg_fill_price: 110,
            filled_at: '2026-05-28T03:51:00+00:00',
          }),
          localOrder({
            id: 12,
            run_id: 43,
            qty: 25,
            status: 'complete',
            filled_qty: 25,
            avg_fill_price: 120,
            filled_at: '2026-05-28T03:52:00+00:00',
          }),
        ]}
        runs={[]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText(/broker did not answer/i)).toBeInTheDocument()
    const row = screen.getByText('NIFTY28MAY2625000CE').closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getByText('25')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('120.00')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('+500.00')).toBeInTheDocument()
  })
})

describe('strategy Tradebook broker truth', () => {
  it('does not claim broker truth when no run exists and labels the local audit fallback', () => {
    renderWithQuery(
      <TradesTab
        strategy={{ ...strategy, status: 'stopped', current_run_id: null }}
        live={{ ...live, runId: null }}
        orders={[
          localOrder({
            run_id: 41,
            status: 'open',
            filled_qty: 5,
            avg_fill_price: null,
          }),
        ]}
        loading={false}
        active
      />
    )

    expect(rest.get).not.toHaveBeenCalled()
    expect(
      screen.getByText(/broker tradebook was not requested because no strategy run is available/i)
    ).toBeInTheDocument()
    expect(screen.getByText('Strategy audit records')).toBeInTheDocument()
    expect(screen.queryByText('Broker-confirmed trades')).not.toBeInTheDocument()
  })

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
        orders={[
          localOrder({
            status: 'rejected',
            filled_qty: 25,
            avg_fill_price: null,
            reject_reason: 'Exchange RMS rejected the remainder',
          }),
        ]}
        loading={false}
        active
      />
    )

    expect(await screen.findByText('Leg 3')).toBeInTheDocument()
    expect(screen.getByText(/rejected.*position-a/i)).toBeInTheDocument()
    expect(screen.getByText('Exchange RMS rejected the remainder')).toBeInTheDocument()
    expect(screen.getByText('Matched')).toBeInTheDocument()
  })

  it('renders invalid broker numerics as unavailable without fabricating zero', async () => {
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
            quantity: 'bad',
            average_price: null,
            trade_value: undefined,
            timestamp: null,
          },
        ],
      },
    })

    const rendered = renderWithQuery(
      <TradesTab
        strategy={strategy}
        live={live}
        orders={[localOrder({ status: 'open', filled_qty: 5, avg_fill_price: null })]}
        loading={false}
        active
      />
    )

    const symbol = await screen.findByText('NIFTY28MAY2625000CE')
    const row = symbol.closest('tr')
    expect(row).not.toBeNull()
    expect(
      within(row as HTMLTableRowElement).getAllByText('Unavailable').length
    ).toBeGreaterThanOrEqual(4)
    expect(row?.textContent).not.toContain('0.00')
    expect(rendered.container.textContent).not.toContain('â€”')
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
