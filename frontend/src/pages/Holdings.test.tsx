/**
 * The strategy filter on Holdings.
 *
 * Nothing changes while "All" is selected, and the chips only appear when the
 * strategy book has a strategy to filter by. Choosing a strategy narrows each
 * holding to that strategy's quantity and average price, and the totals follow.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Holding } from '@/types/trading'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'

const mocks = vi.hoisted(() => ({
  getHoldings: vi.fn(),
  getStrategyAttribution: vi.fn(),
}))

vi.mock('@/api/trading', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/trading')>()
  return {
    ...actual,
    tradingApi: {
      getHoldings: mocks.getHoldings,
      getStrategyAttribution: mocks.getStrategyAttribution,
    },
  }
})
vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'zerodha' } }),
}))
vi.mock('@/stores/themeStore', () => ({ onModeChange: () => () => {} }))
vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: (holdings: Holding[]) => ({ data: holdings, isLive: false, isPaused: false }),
  calculateLiveStats: (_holdings: Holding[], stats: unknown) => stats,
}))
vi.mock('@/hooks/useOrderEventRefresh', () => ({ useOrderEventRefresh: () => {} }))
vi.mock('@/hooks/usePageVisibility', () => ({
  usePageVisibility: () => ({ isVisible: true, wasHidden: false, timeSinceHidden: 0 }),
}))
vi.mock('@/components/trading', () => ({ PlaceOrderDialog: () => null }))

import Holdings from './Holdings'

const INFY: Holding = {
  symbol: 'INFY',
  exchange: 'NSE',
  product: 'CNC',
  quantity: 100,
  average_price: 1500,
  ltp: 1600,
  pnl: 10000,
  pnlpercent: 6.67,
}
const TCS: Holding = {
  symbol: 'TCS',
  exchange: 'NSE',
  product: 'CNC',
  quantity: 20,
  average_price: 3000,
  ltp: 3100,
  pnl: 2000,
  pnlpercent: 3.33,
}
const STATS = {
  totalholdingvalue: 100 * 1600 + 20 * 3100,
  totalinvvalue: 100 * 1500 + 20 * 3000,
  totalprofitandloss: 12000,
  totalpnlpercentage: 5.71,
}

const slice = (strategy: string, quantity: number, average_price: number) => ({
  strategy,
  quantity,
  average_price,
  today_realized_pnl: 0,
  attributed: strategy !== 'Unattributed',
})

// Equity Breakout owns 40 of INFY at 1550; the other 60 of INFY and all of TCS are unclaimed.
const ATTRIBUTION = {
  status: 'success',
  data: {
    kind: 'holdings',
    strategies: ['EquityBreakout'],
    rows: [
      {
        symbol: 'INFY',
        exchange: 'NSE',
        product: 'CNC',
        quantity: 100,
        average_price: 1500,
        slices: [slice('EquityBreakout', 40, 1550), slice('Unattributed', 60, 1466.67)],
        mismatch: false,
        mismatch_reason: null,
        leftover_owner: null,
      },
      {
        symbol: 'TCS',
        exchange: 'NSE',
        product: 'CNC',
        quantity: 20,
        average_price: 3000,
        slices: [slice('Unattributed', 20, 3000)],
        mismatch: false,
        mismatch_reason: null,
        leftover_owner: null,
      },
    ],
  },
}

async function renderHoldings(attribution: unknown) {
  mocks.getHoldings.mockResolvedValue({
    status: 'success',
    data: { holdings: [INFY, TCS], statistics: STATS },
  })
  mocks.getStrategyAttribution.mockResolvedValue(attribution)
  render(<Holdings />)
  await screen.findByText('INFY')
}

describe('Holdings strategy filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows every holding and the broker totals while All is selected', async () => {
    await renderHoldings(ATTRIBUTION)

    expect(await screen.findByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getByText('TCS')).toBeInTheDocument()
    expect(screen.getAllByText(/12,000/).length).toBeGreaterThan(0)
  })

  it('narrows to a strategy: its quantity and cost, and totals of just those rows', async () => {
    await renderHoldings(ATTRIBUTION)
    await userEvent.click(await screen.findByRole('button', { name: 'EquityBreakout' }))

    // INFY shows 40 at 1550; TCS is not this strategy's.
    await waitFor(() => expect(screen.queryByText('TCS')).not.toBeInTheDocument())
    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    // P&L is 40 x (1600 - 1550) = 2,000, no longer the broker's 12,000.
    expect(screen.getAllByText(/2,000/).length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/12,000/)).toHaveLength(0)
  })

  it('shows what no strategy claims under Unattributed', async () => {
    await renderHoldings(ATTRIBUTION)
    await userEvent.click(await screen.findByRole('button', { name: 'Unattributed' }))

    await waitFor(() => expect(screen.getByText('TCS')).toBeInTheDocument())
    expect(screen.getByText('60')).toBeInTheDocument()
    // The 40 shares EquityBreakout owns are not in this view.
    expect(screen.queryByText('40')).not.toBeInTheDocument()
  })

  it('asks for the split again when a strategy is picked, so it is not stale', async () => {
    await renderHoldings(ATTRIBUTION)
    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(1))

    await userEvent.click(await screen.findByRole('button', { name: 'EquityBreakout' }))

    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(2))
  })

  it('falls back to All when the refreshed split no longer has the selected strategy', async () => {
    await renderHoldings(ATTRIBUTION)
    // The next read of the split no longer lists EquityBreakout.
    mocks.getStrategyAttribution.mockResolvedValue({
      status: 'success',
      data: { ...ATTRIBUTION.data, strategies: ['Other'] },
    })

    await userEvent.click(await screen.findByRole('button', { name: 'EquityBreakout' }))

    await waitFor(() => expect(screen.getByText('TCS')).toBeInTheDocument())
    expect(screen.getByText('INFY')).toBeInTheDocument()
    expect(screen.getAllByText(/12,000/).length).toBeGreaterThan(0)
    expect(screen.queryByText('No holdings for this strategy')).not.toBeInTheDocument()
  })

  it('does not re-read the split on every refresh while a strategy is selected', async () => {
    await renderHoldings(ATTRIBUTION)
    await userEvent.click(await screen.findByRole('button', { name: 'EquityBreakout' }))
    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(2))

    await userEvent.click(screen.getByRole('button', { name: /Refresh/ }))
    await waitFor(() => expect(mocks.getHoldings).toHaveBeenCalledTimes(2))

    // The holdings were re-read; the split, read moments ago, was not.
    expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(2)
  })

  it('shows dashes, not zeros, for the totals of a strategy that owns nothing now', async () => {
    await renderHoldings({
      status: 'success',
      data: { ...ATTRIBUTION.data, strategies: ['EquityBreakout', 'Idle'] },
    })

    await userEvent.click(await screen.findByRole('button', { name: 'Idle' }))

    expect(await screen.findByText('No holdings for this strategy')).toBeInTheDocument()
    expect(screen.getAllByText('---').length).toBeGreaterThan(0)
  })

  it('has no strategy chips when the strategy book has no strategies', async () => {
    await renderHoldings({
      status: 'success',
      data: { kind: 'holdings', strategies: [], rows: [] },
    })

    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Unattributed' })).not.toBeInTheDocument()
  })

  it('leaves the page unchanged when the strategy split cannot be fetched', async () => {
    await renderHoldings({ status: 'error', message: 'Strategy book is not initialized' })

    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'All' })).not.toBeInTheDocument()
    expect(screen.getByText('TCS')).toBeInTheDocument()
  })

  it('shares one request when two chips are clicked while a read is still in flight', async () => {
    await renderHoldings(ATTRIBUTION)
    await waitFor(() => expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(1))

    // From here the split is slow to answer.
    let release: (value: unknown) => void = () => {}
    const slow = new Promise((resolve) => {
      release = resolve
    })
    mocks.getStrategyAttribution.mockImplementation(() => slow)

    await userEvent.click(await screen.findByRole('button', { name: 'EquityBreakout' }))
    await userEvent.click(screen.getByRole('button', { name: 'Unattributed' }))

    // The second click joined the read the first one started.
    expect(mocks.getStrategyAttribution).toHaveBeenCalledTimes(2)

    release(ATTRIBUTION)
    await waitFor(() => expect(screen.getByText('TCS')).toBeInTheDocument())
  })
})
