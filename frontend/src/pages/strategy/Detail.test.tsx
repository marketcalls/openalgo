import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const liveHook = vi.hoisted(() => vi.fn())
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  webClient: { get: rest.get, post: rest.post, patch: vi.fn(), delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

vi.mock('@/api/strategy_module', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/strategy_module')>('@/api/strategy_module')
  return {
    ...actual,
    useStrategyLive: liveHook,
  }
})

vi.mock('@/utils/toast', () => ({ showToast: toast }))

import {
  fetchStrategyOrderbook,
  fetchStrategyPositions,
  fetchStrategyTradebook,
  type StrategyLiveState,
  useBrokerBook,
} from '@/api/strategy_module'
import type { Order, Run, Strategy } from '@/types/strategy_module'
import StrategyDetail, { OrdersTab, PositionsTab, TradesTab } from './Detail'

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

function renderDetail() {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter initialEntries={['/strategy/7']}>
        <Routes>
          <Route path="/strategy/:strategyId" element={<StrategyDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
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
  rest.post.mockReset()
  liveHook.mockReset()
  liveHook.mockReturnValue(live)
  for (const mock of Object.values(toast)) mock.mockReset()
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

    renderWithQuery(
      <OrdersTab strategy={strategy} live={live} orders={[localOrder()]} loading={false} active />
    )

    const symbol = await screen.findByText('NIFTY28MAY2625000CE')
    const row = symbol.closest('tr')
    expect(row).not.toBeNull()
    expect(
      within(row as HTMLTableRowElement).getAllByText('Unavailable').length
    ).toBeGreaterThanOrEqual(4)
    expect(row?.textContent).not.toContain('0.00')
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
  it('uses the finalized run across Live and Positions after a stale checkpoint survives stop', async () => {
    const stoppedStrategy = {
      ...strategy,
      id: 7,
      name: 'Test Strategy Monthly',
      status: 'stopped',
      current_run_id: null,
      updated_at: '2026-08-31T04:15:29.517782+00:00',
    } satisfies Strategy
    const lastRun = {
      id: 12,
      strategy_id: 7,
      mode: 'sandbox',
      broker: null,
      started_at: '2026-08-31T04:15:17.624913+00:00',
      stopped_at: '2026-08-31T04:15:29.517782+00:00',
      stop_reason: 'overall_target',
      pnl_realized: 117,
      pnl_peak: 513,
      pnl_trough: -355.5,
      trigger_source: 'manual',
      webhook_event_id: null,
      resolved_expiries: null,
    } satisfies Run
    const priorRun = {
      ...lastRun,
      id: 11,
      pnl_realized: -733.5,
      pnl_peak: 0,
      pnl_trough: -733.5,
    } satisfies Run
    const staleCheckpoint = {
      id: 99,
      run_id: 12,
      ts: '2026-08-31T04:15:26.713000+00:00',
      pnl_realized: 0,
      pnl_unrealized: 81,
      pnl_total: 81,
      pnl_peak: 135,
      pnl_trough: -355.5,
      lock_floor: null,
      trail_to_entry_active: false,
      leg_state: {},
    }
    liveHook.mockReturnValue({
      ...live,
      status: 'idle',
      runId: 12,
      checkpoint: staleCheckpoint,
      updatedAt: staleCheckpoint.ts,
      curve: [staleCheckpoint],
    })
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies/7') {
        return Promise.resolve({ data: { data: stoppedStrategy } })
      }
      if (url === '/strategy/api/strategies/7/runs') {
        return Promise.resolve({ data: { data: [lastRun, priorRun] } })
      }
      if (url === '/strategy/api/strategies/7/positions') {
        return Promise.resolve({ data: { status: 'success', data: [] } })
      }
      return Promise.resolve({ data: { data: [] } })
    })
    const user = userEvent.setup()

    renderDetail()

    await screen.findByText('Test Strategy Monthly')
    const liveCard = screen.getByText('Live P&L').closest('[data-slot="card"]')
    expect(liveCard).not.toBeNull()
    expect(within(liveCard as HTMLElement).getByText('Realized').parentElement).toHaveTextContent(
      '+117.00'
    )
    expect(within(liveCard as HTMLElement).getByText('Unrealized').parentElement).toHaveTextContent(
      '0.00'
    )
    expect(within(liveCard as HTMLElement).getByText('Total P&L').parentElement).toHaveTextContent(
      '+117.00'
    )
    expect(liveCard).toHaveTextContent('Peak: +513.00')
    expect(liveCard).toHaveTextContent('Trough: -355.50')
    expect(liveCard).toHaveTextContent('Stopped: 31 Aug 2026, 09:45:29 IST')
    expect(liveCard).not.toHaveTextContent('Updated:')
    expect(liveCard).not.toHaveTextContent('+81.00')

    await user.click(screen.getByRole('tab', { name: 'Positions' }))

    const thisRun = await screen.findByText('Realized (this run)')
    expect(thisRun.parentElement).toHaveTextContent('+117.00')
    expect(screen.getByText('Unrealized').parentElement).toHaveTextContent('0.00')
    expect(screen.getByText('Run total').parentElement).toHaveTextContent('+117.00')
    expect(screen.getByText('Cumulative realized').parentElement).toHaveTextContent('-616.50')
    expect(screen.queryByText('+81.00')).not.toBeInTheDocument()
  })

  it('explains that overall MTM thresholds trigger exits rather than guarantee realized P&L', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies/7') {
        return Promise.resolve({
          data: {
            data: { ...strategy, overall_sl_mtm: 500, overall_target_mtm: 500 },
          },
        })
      }
      return Promise.resolve({ data: { data: [] } })
    })
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('tab', { name: 'Risk' }))

    expect(
      screen.getByText(
        /overall sl and overall target trigger exits from ltp-based mtm.*market orders fill at the available bid\/ask.*final realized p&l can differ from the trigger value/i
      )
    ).toBeInTheDocument()
  })

  it('uses the latest finalized run for every broker book after a stale live run survives stop', async () => {
    const stoppedStrategy = {
      ...strategy,
      status: 'stopped',
      current_run_id: null,
    } satisfies Strategy
    const lastRun = {
      id: 12,
      strategy_id: 7,
      mode: 'sandbox',
      broker: null,
      started_at: '2026-08-31T04:15:17.624913+00:00',
      stopped_at: '2026-08-31T04:15:29.517782+00:00',
      stop_reason: 'overall_target',
      pnl_realized: 117,
      pnl_peak: 513,
      pnl_trough: -355.5,
      trigger_source: 'manual',
      webhook_event_id: null,
      resolved_expiries: null,
    } satisfies Run
    liveHook.mockReturnValue({ ...live, status: 'idle', runId: 11 })
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies/7') {
        return Promise.resolve({ data: { data: stoppedStrategy } })
      }
      if (url === '/strategy/api/strategies/7/runs') {
        return Promise.resolve({ data: { data: [lastRun] } })
      }
      if (url.endsWith('/orderbook')) {
        return Promise.resolve({ data: { status: 'success', data: { orders: [] } } })
      }
      return Promise.resolve({ data: { status: 'success', data: [] } })
    })
    const user = userEvent.setup()

    renderDetail()
    await screen.findByText('Broker truth')

    for (const [tab, endpoint] of [
      ['Positions', '/strategy/api/strategies/7/positions'],
      ['Orders', '/strategy/api/strategies/7/orderbook'],
      ['Trades', '/strategy/api/strategies/7/tradebook'],
    ] as const) {
      await user.click(screen.getByRole('tab', { name: tab }))
      await waitFor(() =>
        expect(rest.get).toHaveBeenCalledWith(endpoint, {
          params: { run_id: 12 },
          signal: expect.any(AbortSignal),
        })
      )
    }
  })

  it('renders missing active checkpoint P&L as unknown, including cumulative realized', () => {
    rest.get.mockResolvedValue({ data: { status: 'success', data: [] } })
    const priorRun = { id: 41, pnl_realized: 125 } as Run

    renderWithQuery(
      <PositionsTab
        strategy={strategy}
        live={live}
        orders={[]}
        runs={[priorRun]}
        loading={false}
        active
      />
    )

    for (const label of ['Realized (this run)', 'Unrealized', 'Run total', 'Cumulative realized']) {
      const metric = screen.getByText(label).parentElement
      expect(metric).not.toBeNull()
      expect(metric).toHaveTextContent('—')
      expect(metric).not.toHaveTextContent('0.00')
      expect(metric).not.toHaveTextContent('+125.00')
    }
  })

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
    expect(row?.textContent).not.toContain('+5000.00')
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
            qty: 75,
            status: 'complete',
            filled_qty: 75,
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
    expect(within(row as HTMLTableRowElement).getByText('long')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('50')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('110.00')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('+500.00')).toBeInTheDocument()
  })

  it('keeps a prior-run residual when the broker succeeds with an empty book', async () => {
    rest.get.mockResolvedValue({ data: { status: 'success', data: [] } })

    renderWithQuery(
      <PositionsTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={{ ...live, runId: 43, legs: [] }}
        orders={[
          localOrder({
            id: 20,
            run_id: 41,
            qty: 75,
            status: 'complete',
            filled_qty: 75,
            avg_fill_price: 100,
          }),
          localOrder({
            id: 21,
            run_id: 41,
            kind: 'exit_eod',
            action: 'SELL',
            status: 'complete',
            filled_qty: 50,
            avg_fill_price: 110,
            filled_at: '2026-05-28T03:51:00+00:00',
          }),
        ]}
        runs={[]}
        loading={false}
        active
      />
    )

    const row = (await screen.findByText('NIFTY28MAY2625000CE')).closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getByText('25')).toBeInTheDocument()
    expect(within(row as HTMLTableRowElement).getByText('local/unreconciled')).toBeInTheDocument()
  })

  it('keeps an omitted prior residual beside authoritative current broker quantity', async () => {
    const current = 'NIFTY28MAY2626000CE'
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            symbol: current,
            exchange: 'NFO',
            product: 'NRML',
            quantity: 7,
            average_price: 123,
            ltp: 125,
            pnl: 14,
            source: 'broker',
          },
        ],
      },
    })

    renderWithQuery(
      <PositionsTab
        strategy={{ ...strategy, current_run_id: 43 }}
        live={{ ...live, runId: 43, legs: [] }}
        orders={[
          localOrder({ id: 30, run_id: 41, status: 'complete', filled_qty: 25 }),
          localOrder({
            id: 31,
            run_id: 43,
            symbol: current,
            status: 'complete',
            filled_qty: 25,
          }),
        ]}
        runs={[]}
        loading={false}
        active
      />
    )

    await screen.findByText('broker')
    const currentRow = screen.getByText(current).closest('tr')
    expect(within(currentRow as HTMLTableRowElement).getByText('7')).toBeInTheDocument()
    expect(within(currentRow as HTMLTableRowElement).getByText('broker')).toBeInTheDocument()
    const priorRow = screen.getByText('NIFTY28MAY2625000CE').closest('tr')
    expect(within(priorRow as HTMLTableRowElement).getByText('25')).toBeInTheDocument()
    expect(
      within(priorRow as HTMLTableRowElement).getByText('local/unreconciled')
    ).toBeInTheDocument()
  })

  it('labels shared broker aggregates and retained local owners explicitly', async () => {
    rest.get.mockResolvedValue({
      data: {
        status: 'success',
        data: [
          {
            symbol: 'SHARED',
            exchange: 'NFO',
            product: 'NRML',
            quantity: 50,
            average_price: 100,
            ltp: 101,
            pnl: 50,
            source: 'broker/shared',
          },
          {
            symbol: 'SHARED',
            exchange: 'NFO',
            product: 'NRML',
            quantity: 25,
            average_price: 100,
            ltp: null,
            pnl: null,
            source: 'local/unreconciled',
            position_ref: 'owner-a',
          },
        ],
      },
    })

    renderWithQuery(
      <PositionsTab strategy={strategy} live={live} orders={[]} runs={[]} loading={false} active />
    )

    expect(await screen.findByText('broker/shared')).toBeInTheDocument()
    expect(screen.getByText('local/unreconciled')).toBeInTheDocument()
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

    renderWithQuery(
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

describe('strategy exit action toasts describe proven state only', () => {
  function mockRunningDetailReads(orders: Order[] = []) {
    const detailedStrategy = {
      ...strategy,
      legs: [
        {
          id: 3,
          segment: 'options',
          position: 'B',
          lots: 1,
          option_type: 'CE',
          strike_mode: 'atm',
        },
      ],
    }
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies/7') {
        return Promise.resolve({ data: { data: detailedStrategy } })
      }
      if (url === '/strategy/api/strategies/7/orders') {
        return Promise.resolve({ data: { data: orders } })
      }
      return Promise.resolve({ data: { data: [] } })
    })
  }

  it('shows one ordinary stop action alongside the emergency kill switch', async () => {
    mockRunningDetailReads()

    renderDetail()

    expect(
      await screen.findByRole('button', { name: 'Stop & Close Positions' })
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'KILL SWITCH' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Close All' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('does not promise a flat run before broker fills confirm it', async () => {
    mockRunningDetailReads()
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('button', { name: 'Stop & Close Positions' }))
    expect(
      screen.getByText(/finalised only after broker fills confirm the strategy is flat/i)
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'KILL SWITCH' }))
    expect(
      screen.getByText(/finalised only after broker fills confirm the strategy is flat/i)
    ).toBeInTheDocument()
  })

  it('uses the kill-switch pending message returned by the backend', async () => {
    mockRunningDetailReads()
    rest.post.mockResolvedValue({
      data: {
        webhook_locked: true,
        run_stopped: false,
        stop_pending: true,
        message: 'Webhook locked; exit fills pending',
      },
    })
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('button', { name: 'KILL SWITCH' }))
    await user.click(screen.getByRole('button', { name: 'KILL' }))

    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/7/kill_switch')
    )
    expect(toast.warning).toHaveBeenCalledWith('Webhook locked; exit fills pending')
  })

  it.each([
    {
      button: 'Stop & Close Positions',
      confirm: 'Stop & close positions',
      endpoint: '/strategy/api/strategies/7/stop',
      expected: 'Stop requested — exit orders are pending',
    },
  ])('keeps $button pending when the API accepted only exit intent', async (contract) => {
    mockRunningDetailReads()
    rest.post.mockResolvedValue({
      data: { run_id: 42, stop_pending: true, run_stopped: false, exits: [{ ok: true }] },
    })
    const user = userEvent.setup()

    renderDetail()
    await screen.findByText('Broker truth')
    await user.click(screen.getByRole('button', { name: contract.button }))
    await user.click(screen.getByRole('button', { name: contract.confirm }))

    await waitFor(() => expect(rest.post).toHaveBeenCalledWith(contract.endpoint))
    expect(toast.success).toHaveBeenCalledWith(contract.expected)
  })

  it('keeps an accepted close-leg dispatch pending until run_stopped is true', async () => {
    mockRunningDetailReads([
      localOrder({ status: 'complete', filled_qty: 50, avg_fill_price: 100 }),
    ])
    rest.post.mockResolvedValue({
      data: { run_id: 42, leg_id: 3, run_stopped: false, exits: [{ ok: true }] },
    })
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('button', { name: 'Close leg' }))

    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/7/legs/3/close')
    )
    expect(toast.success).toHaveBeenCalledWith('Leg close requested — exit order is pending')
  })

  it('uses confirmed-flat wording only when close-leg reports run_stopped', async () => {
    mockRunningDetailReads([
      localOrder({ status: 'complete', filled_qty: 50, avg_fill_price: 100 }),
    ])
    rest.post.mockResolvedValue({
      data: { run_id: 42, leg_id: 3, run_stopped: true, exits: [{ ok: true }] },
    })
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('button', { name: 'Close leg' }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1))
    expect(toast.success).toHaveBeenCalledWith('Leg closed — last open leg, run stopped')
  })

  it('warns when a started run has no durable broker acknowledgement', async () => {
    const stoppedStrategy = { ...strategy, status: 'stopped', current_run_id: null }
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies/7') {
        return Promise.resolve({ data: { data: stoppedStrategy } })
      }
      return Promise.resolve({ data: { data: [] } })
    })
    rest.post.mockResolvedValue({
      data: {
        run_id: 42,
        mode: 'sandbox',
        acknowledged: false,
        legs: [{ leg_id: 3, ok: true, status: 'open' }],
      },
    })
    const user = userEvent.setup()

    renderDetail()
    await user.click(await screen.findByRole('button', { name: 'Start run' }))
    await user.click(screen.getByRole('button', { name: 'Start sandbox' }))

    await waitFor(() =>
      expect(rest.post).toHaveBeenCalledWith('/strategy/api/strategies/7/start', { mode: 'sandbox' })
    )
    expect(toast.warning).toHaveBeenCalledWith(
      'Run started, but broker acknowledgement is pending. Check Events and Orders before relying on RMS.'
    )
  })
})
