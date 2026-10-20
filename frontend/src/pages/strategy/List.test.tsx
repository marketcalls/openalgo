import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const rest = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  webClient: rest,
  apiClient: { get: vi.fn(), post: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

import StrategyList from './List'

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderList() {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter>
        <StrategyList />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

const stoppedStrategy = {
  id: 3,
  name: 'test stat',
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
  status: 'stopped',
  current_run_id: null,
  created_at: '2026-08-31T05:53:09+00:00',
  updated_at: '2026-08-31T07:03:57+00:00',
  last_finalized_run: {
    id: 6,
    pnl_realized: -52,
    stopped_at: '2026-08-31T07:03:57+00:00',
  },
}

const staleCheckpoint = {
  id: 1148,
  run_id: 6,
  ts: '2026-08-31T07:03:55+00:00',
  pnl_realized: 0,
  pnl_unrealized: -19.5,
  pnl_total: -19.5,
  pnl_peak: 0,
  pnl_trough: -19.5,
  lock_floor: null,
  trail_to_entry_active: false,
  leg_state: {},
}

beforeEach(() => {
  rest.get.mockReset()
  rest.post.mockReset()
  rest.patch.mockReset()
  rest.delete.mockReset()
})

describe('strategy list P&L', () => {
  it('uses a stopped run’s finalized P&L instead of its stale live checkpoint', async () => {
    rest.get.mockImplementation((url: string) => {
      if (url === '/strategy/api/strategies') {
        return Promise.resolve({ data: { data: [stoppedStrategy] } })
      }
      if (url === '/strategy/api/strategies/3/checkpoints') {
        return Promise.resolve({ data: { data: [staleCheckpoint], run_id: 6 } })
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })

    renderList()

    const name = await screen.findByRole('link', { name: 'test stat' })
    const row = name.closest('tr')
    expect(row).not.toBeNull()
    expect(within(row as HTMLTableRowElement).getAllByText('-52.00')).toHaveLength(2)
    expect(within(row as HTMLTableRowElement).getByText('0.00')).toBeInTheDocument()
    expect(row).not.toHaveTextContent('-19.50')
  })
})
