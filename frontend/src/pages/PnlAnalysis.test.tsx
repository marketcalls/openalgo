/**
 * The merged P&L page: nothing is fetched until a segment and a P&L type are
 * chosen, and one fetch feeds the summary, the strategies, the curve and the
 * breakdown, all narrowed by one set of filters.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor, within } from '@/test/test-utils'

vi.mock('lightweight-charts', () => {
  const series = new Proxy({}, { get: () => () => undefined })
  const chart: Record<string, unknown> = {
    remove: () => {},
    addSeries: () => series,
    panes: () => [],
    applyOptions: () => {},
    timeScale: () => new Proxy({}, { get: () => () => undefined }),
    priceScale: () => new Proxy({}, { get: () => () => undefined }),
    subscribeCrosshairMove: () => {},
    takeScreenshot: () => document.createElement('canvas'),
  }
  return {
    createChart: () => chart,
    BaselineSeries: 'BaselineSeries',
    LineSeries: 'LineSeries',
    HistogramSeries: 'HistogramSeries',
    ColorType: { Solid: 'solid' },
    CrosshairMode: { Normal: 0 },
  }
})
vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'zerodha' } }),
}))
vi.mock('@/stores/themeStore', () => ({ useThemeStore: () => ({ mode: 'light' }) }))

const getPnlHistory = vi.fn()
const getPnlCurve = vi.fn()
vi.mock('@/api/trading', () => ({
  tradingApi: {
    getPnlHistory: (...args: unknown[]) => getPnlHistory(...args),
    getPnlCurve: (...args: unknown[]) => getPnlCurve(...args),
  },
}))

import PnlAnalysis from './PnlAnalysis'

const HISTORY = {
  status: 'success',
  data: {
    start_date: '2026-05-01',
    end_date: '2026-05-31',
    total_realized_pnl: 200,
    trade_count: 1,
    daily: [],
    closed_trades: [
      {
        symbol: 'WOCKPHARMA',
        exchange: 'NSE',
        product: 'CNC',
        entry_action: 'BUY',
        quantity: 45,
        entry_price: 1530.4,
        entry_timestamp: '2026-05-05T15:16:00',
        exit_price: 1915.1,
        exit_timestamp: '2026-05-07T15:15:00',
        realized_pnl: 200,
        strategy: 'EquityBreakoutPositional',
      },
    ],
    open_positions: [],
    total_unrealized_pnl: null,
  },
}

const CURVE = {
  status: 'success',
  data: {
    dates: ['2026-05-05', '2026-05-06', '2026-05-07'],
    by_strategy: {
      EquityBreakoutPositional: { realized: [0, 0, 200], unrealized: [50, 150, 0] },
      Untagged: { realized: [0, 0, 0], unrealized: [30, 30, 30] },
    },
    basis: 'actual_cost',
    base_date: '2026-05-04',
    segment: 'equity',
    notes: { orphan_sells: [], missing_close: [], missing_base: [] },
  },
}

describe('PnlAnalysis', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getPnlHistory.mockResolvedValue(HISTORY)
    getPnlCurve.mockResolvedValue(CURVE)
  })

  it('fetches nothing until a segment and a P&L type are chosen', async () => {
    window.history.pushState({}, '', '/pnl')
    render(<PnlAnalysis />)

    expect(screen.getByText(/choose a segment and a p&l type/i)).toBeInTheDocument()
    const fetchButton = screen.getByRole('button', { name: /fetch the p&l report/i })
    expect(fetchButton).toBeDisabled()
    expect(getPnlHistory).not.toHaveBeenCalled()
  })

  it('shows the summary, strategies, curve and breakdown from one fetch', async () => {
    window.history.pushState(
      {},
      '',
      '/pnl?segment=equity&type=combined&start=2026-05-01&end=2026-05-31'
    )
    render(<PnlAnalysis />)

    await userEvent.click(screen.getByRole('button', { name: /fetch the p&l report/i }))

    await waitFor(() => expect(getPnlHistory).toHaveBeenCalledTimes(1))
    expect(getPnlCurve).toHaveBeenCalledTimes(1)
    // Net P&L = realized 200 + the open level at the end (0 + 30).
    expect(await screen.findByText(/net p&l \(realized \+ unrealized\)/i)).toBeInTheDocument()
    expect(screen.getByText('Strategies')).toBeInTheDocument()
    expect(screen.getByText('Calendar')).toBeInTheDocument()
    expect(screen.getByText('Breakdown')).toBeInTheDocument()
    // Untagged is a strategy like any other.
    expect(screen.getAllByText('Untagged').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EquityBreakoutPositional').length).toBeGreaterThan(0)
  })

  it('shows only the strategies the Filters dialog lets through', async () => {
    window.history.pushState(
      {},
      '',
      '/pnl?segment=equity&type=combined&start=2026-05-01&end=2026-05-31'
    )
    render(<PnlAnalysis />)
    await userEvent.click(screen.getByRole('button', { name: /fetch the p&l report/i }))
    await screen.findByText('Strategies')

    const pane = screen.getByText('Strategies').closest('[data-slot="card"]') as HTMLElement
    // Both strategies are in the pane, with the per-strategy columns.
    expect(within(pane).getByText('Untagged')).toBeInTheDocument()
    expect(within(pane).getByText('Realized')).toBeInTheDocument()
    expect(within(pane).getByText('Unrealized')).toBeInTheDocument()
    expect(within(pane).getByText('Current drawdown')).toBeInTheDocument()
    expect(screen.getByText(/no filters applied/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /open p&l filters/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'EquityBreakoutPositional' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Done' }))

    expect(await screen.findByText(/applied:/i)).toBeInTheDocument()
    // The pane shows only what was selected there.
    await waitFor(() => expect(within(pane).queryByText('Untagged')).not.toBeInTheDocument())
    expect(within(pane).getByText('EquityBreakoutPositional')).toBeInTheDocument()
  })
})
