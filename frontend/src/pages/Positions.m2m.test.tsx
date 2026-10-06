/**
 * The P&L | M2M switch on the Positions page.
 *
 * P&L is the broker's own figure and stays the default, untouched. M2M is
 * today's move only, computed server-side from today's fills and yesterday's
 * close (services/position_m2m.py) and kept live here by adding the current
 * price. The page must not ask for it until it is selected, and must say so when
 * it cannot be worked out instead of showing a wrong figure.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Position } from '@/types/trading'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'

const mocks = vi.hoisted(() => ({
  getPositions: vi.fn(),
  getStrategyAttribution: vi.fn(),
}))

vi.mock('@/api/trading', () => ({
  tradingApi: {
    getPositions: mocks.getPositions,
    getStrategyAttribution: mocks.getStrategyAttribution,
    closePosition: vi.fn(),
    closeAllPositions: vi.fn(),
  },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'zerodha' } }),
}))
vi.mock('@/stores/themeStore', () => ({ onModeChange: () => () => {} }))
vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: (positions: Position[]) => ({ data: positions, isLive: false, isPaused: false }),
}))
vi.mock('@/hooks/useOrderEventRefresh', () => ({ useOrderEventRefresh: () => {} }))
vi.mock('@/hooks/usePageVisibility', () => ({
  usePageVisibility: () => ({ isVisible: true, wasHidden: false, timeSinceHidden: 0 }),
}))
vi.mock('@/hooks/useSupportedExchanges', () => ({
  useSupportedExchanges: () => ({ isCrypto: false }),
}))

import Positions from './Positions'

// acc1 NIFTY06OCT2622350PE NRML on 2026-10-06: carried 195, closed today at 0.25.
// Kite's own P&L was -11,544 (its carried cost was wrong); today's M2M was -4,377.75.
const CARRIED: Position = {
  symbol: 'NIFTY06OCT2622350PE',
  exchange: 'NFO',
  product: 'NRML',
  quantity: 0,
  average_price: 0,
  ltp: 0.05,
  pnl: -11544,
} as Position

const attribution = (row: Record<string, unknown>) => ({
  status: 'success',
  data: {
    kind: 'positions',
    strategies: [],
    m2m_error: null,
    rows: [
      {
        symbol: CARRIED.symbol,
        exchange: 'NFO',
        product: 'NRML',
        quantity: 0,
        average_price: 0,
        slices: [],
        mismatch: false,
        mismatch_reason: null,
        leftover_owner: null,
        ...row,
      },
    ],
  },
})

async function renderPage() {
  mocks.getPositions.mockResolvedValue({ status: 'success', data: [CARRIED] })
  render(<Positions />)
  await screen.findByText(CARRIED.symbol)
}

describe('Positions M2M switch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it("starts on the broker's P&L and does not ask for M2M", async () => {
    await renderPage()

    expect(screen.getByText('Total P&L')).toBeInTheDocument()
    expect(screen.getAllByText(/11,544/).length).toBeGreaterThan(0)
    expect(mocks.getStrategyAttribution).not.toHaveBeenCalled()
  })

  it("asks for M2M when selected and shows today's move instead of the broker figure", async () => {
    mocks.getStrategyAttribution.mockResolvedValue(
      attribution({
        m2m_available: true,
        m2m_fixed: -4377.75,
        m2m: -4377.75,
        overnight_quantity: 195,
        prev_close: 22.7,
      })
    )
    await renderPage()

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    await waitFor(() =>
      expect(mocks.getStrategyAttribution).toHaveBeenCalledWith('test-api-key', 'positions', true)
    )
    expect(await screen.findByText('Total M2M')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText(/4,377\.75/).length).toBeGreaterThan(0))
    expect(screen.queryAllByText(/11,544/)).toHaveLength(0)
  })

  it('says so, and keeps the broker figure, when M2M cannot be worked out', async () => {
    mocks.getStrategyAttribution.mockResolvedValue({
      ...attribution({ m2m_available: false, m2m_reason: 'previous close unavailable' }),
    })
    await renderPage()

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    expect(await screen.findByText(/could not be worked out for 1 of 1/)).toBeInTheDocument()
    expect(screen.getAllByText(/11,544/).length).toBeGreaterThan(0)
  })

  it('notes when the broker P&L of a carried position already is its M2M', async () => {
    mocks.getStrategyAttribution.mockResolvedValue(
      attribution({
        m2m_available: true,
        m2m_fixed: -2918.5,
        m2m: -2918.5,
        overnight_quantity: 130,
        prev_close: 22.7,
        pnl_equals_m2m: true,
      })
    )
    await renderPage()

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    expect(await screen.findByText(/already its M2M/)).toBeInTheDocument()
  })

  it('remembers the choice', async () => {
    mocks.getStrategyAttribution.mockResolvedValue(
      attribution({
        m2m_available: true,
        m2m_fixed: -4377.75,
        overnight_quantity: 195,
        prev_close: 22.7,
      })
    )
    await renderPage()
    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem('openalgo_positions_prefs') ?? '{}').pnlBasis).toBe(
        'm2m'
      )
    )
  })
})
