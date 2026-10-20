/**
 * A squared-off position offers no Close button.
 *
 * Issue #2054: the red X was rendered on every row, including the rows a
 * broker keeps reporting after a position is closed - quantity 0, realised
 * P&L still attached. Clicking it sent a placesmartorder the engine then
 * refused, logging "No OpenPosition Found. Not placing Exit order.", after the
 * alert channels had already announced it.
 *
 * The page's own header already works this way: Close All is disabled when
 * `stats.total` is 0, and that count deliberately excludes zero-quantity rows.
 * So does the trading dock's position table, whose header comment records the
 * rule - zero-quantity rows "stay visible with their realised figure and no
 * Close". Only this table had missed it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Position } from '@/types/trading'
import { render, screen, within } from '@/test/test-utils'

const mocks = vi.hoisted(() => ({
  getPositions: vi.fn(),
  closePosition: vi.fn(),
}))

vi.mock('@/api/trading', () => ({
  tradingApi: {
    getPositions: mocks.getPositions,
    closePosition: mocks.closePosition,
    closeAllPositions: vi.fn(),
  },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'zerodha' } }),
}))

vi.mock('@/stores/themeStore', () => ({ onModeChange: () => () => {} }))

// The live-price hook owns the WebSocket. Pass the positions straight through
// so the table renders exactly what the API returned.
vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: (positions: Position[]) => ({
    data: positions,
    isLive: false,
    isPaused: false,
  }),
}))

vi.mock('@/hooks/useOrderEventRefresh', () => ({ useOrderEventRefresh: () => {} }))
vi.mock('@/hooks/usePageVisibility', () => ({
  usePageVisibility: () => ({ isVisible: true, wasHidden: false, timeSinceHidden: 0 }),
}))
vi.mock('@/hooks/useSupportedExchanges', () => ({
  useSupportedExchanges: () => ({ isCrypto: false }),
}))

import Positions from './Positions'

const OPEN_POSITION: Position = {
  symbol: 'NIFTY25SEP2625000CE',
  exchange: 'NFO',
  product: 'NRML',
  quantity: -75,
  average_price: 120.5,
  ltp: 98.25,
  pnl: 1668.75,
} as Position

const CLOSED_POSITION: Position = {
  symbol: 'BANKNIFTY25SEP2654000PE',
  exchange: 'NFO',
  product: 'NRML',
  quantity: 0,
  average_price: 210.1,
  ltp: 185.4,
  pnl: -740.0,
} as Position

async function renderPositions(positions: Position[]) {
  mocks.getPositions.mockResolvedValue({ status: 'success', data: positions })
  render(<Positions />)
  // The first row to arrive tells us the fetch has resolved and painted.
  await screen.findByText(positions[0].symbol)
}

describe('Positions close button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('offers Close on a position that is still open', async () => {
    await renderPositions([OPEN_POSITION])

    expect(
      screen.getByRole('button', { name: `Close ${OPEN_POSITION.symbol} position` })
    ).toBeInTheDocument()
  })

  it('THE DEFECT: offers no Close on a position already squared off', async () => {
    await renderPositions([CLOSED_POSITION])

    expect(
      screen.queryByRole('button', { name: `Close ${CLOSED_POSITION.symbol} position` })
    ).not.toBeInTheDocument()
  })

  it('leaves the open row actionable when both are on the page', async () => {
    await renderPositions([OPEN_POSITION, CLOSED_POSITION])

    expect(
      screen.getByRole('button', { name: `Close ${OPEN_POSITION.symbol} position` })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: `Close ${CLOSED_POSITION.symbol} position` })
    ).not.toBeInTheDocument()
  })

  it('never sends a close request for a squared-off position', async () => {
    await renderPositions([CLOSED_POSITION])

    // Nothing on the row can reach the endpoint, so the engine is never asked
    // to exit a position that is not there, and no alert can be raised for it.
    expect(mocks.closePosition).not.toHaveBeenCalled()
  })

  it('keeps the closed row and its realised P&L visible', async () => {
    await renderPositions([CLOSED_POSITION])

    // Hiding the row would lose the realised figure, which is the reason the
    // broker still reports it. Only the action goes.
    expect(screen.getByText(CLOSED_POSITION.symbol)).toBeInTheDocument()
  })

  it('does not colour a zero quantity as a short', async () => {
    await renderPositions([CLOSED_POSITION])

    // Symbol, exchange, product, quantity - the fourth cell of the row.
    const row = screen.getByText(CLOSED_POSITION.symbol).closest('tr')
    expect(row).not.toBeNull()
    const quantityCell = within(row as HTMLElement).getAllByRole('cell')[3]

    expect(quantityCell).toHaveTextContent('0')
    expect(quantityCell.className).toContain('text-muted-foreground')
    expect(quantityCell.className).not.toContain('text-red-600')
  })

  it('treats a string zero quantity as closed, not as open', async () => {
    // The API does not always send a number. Zerodha's position mapping
    // defaults quantity to the string "0", and a strict `!== 0` reads that as
    // an open position - putting the button back on the exact row this guard
    // exists to clear.
    await renderPositions([{ ...CLOSED_POSITION, quantity: '0' } as unknown as Position])

    expect(
      screen.queryByRole('button', { name: `Close ${CLOSED_POSITION.symbol} position` })
    ).not.toBeInTheDocument()
  })

  it('still offers Close when a live quantity arrives as a string', async () => {
    await renderPositions([{ ...OPEN_POSITION, quantity: '-75' } as unknown as Position])

    expect(
      screen.getByRole('button', { name: `Close ${OPEN_POSITION.symbol} position` })
    ).toBeInTheDocument()
  })

  it('disables Close All when every position is squared off', async () => {
    await renderPositions([CLOSED_POSITION])

    expect(screen.getByRole('button', { name: /Close All/ })).toBeDisabled()
  })
})
