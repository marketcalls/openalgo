/**
 * The P&L | M2M switch on the P&L Tracker.
 *
 * Off (the default) asks the server for the broker's own P&L, the same basis as
 * the Positions page; on asks for today's M2M. The choice is remembered, the
 * curve reloads when it changes, and the card titles follow it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'

// The chart library draws on a canvas; a permissive fake is enough here.
vi.mock('lightweight-charts', () => {
  const series = new Proxy({}, { get: () => () => undefined })
  const chart: Record<string, unknown> = {
    remove: () => {},
    paneSize: () => ({ height: 300 }),
    addSeries: () => series,
    panes: () => [],
    applyOptions: () => {},
    timeScale: () => new Proxy({}, { get: () => () => undefined }),
    priceScale: () => new Proxy({}, { get: () => () => undefined }),
    subscribeCrosshairMove: () => {},
  }
  return {
    createChart: () => chart,
    BaselineSeries: 'BaselineSeries',
    ColorType: { Solid: 'solid' },
    CrosshairMode: { Normal: 0 },
  }
})
vi.mock('html2canvas-pro', () => ({ default: vi.fn() }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: 'zerodha' } }),
}))
vi.mock('@/stores/themeStore', () => ({ useThemeStore: () => ({ mode: 'dark' }) }))

import PnLTracker from './PnLTracker'

const DATA = {
  current_mtm: 10887.5,
  max_mtm: 10936.25,
  max_mtm_time: '15:08',
  min_mtm: 2184,
  min_mtm_time: '09:15',
  max_drawdown: -1186.25,
  pnl_series: [{ time: 1_760_000_000_000, value: 10887.5 }],
  drawdown_series: [{ time: 1_760_000_000_000, value: 0 }],
}

const fetchMock = vi.fn()

function requestedBases(): string[] {
  return fetchMock.mock.calls
    .filter(([url]) => url === '/pnltracker/api/pnl')
    .map(([, init]) => JSON.parse((init as RequestInit).body as string).basis)
}

describe('PnL Tracker basis switch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      json: async () =>
        url === '/auth/csrf-token' ? { csrf_token: 'tok' } : { status: 'success', data: DATA },
    }))
    vi.stubGlobal('fetch', fetchMock)
  })

  it("starts on the broker's P&L and asks the server for that basis", async () => {
    render(<PnLTracker />)

    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))
    expect(new Set(requestedBases())).toEqual(new Set(['pnl']))
    expect(screen.getByText('Current P&L')).toBeInTheDocument()
  })

  it('asks for M2M when switched on, retitles the cards, and reloads the curve', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    await waitFor(() => expect(requestedBases()).toContain('m2m'))
    expect(await screen.findByText('Current M2M')).toBeInTheDocument()
    expect(screen.getByText('Max M2M')).toBeInTheDocument()
    expect(screen.getByText('Min M2M')).toBeInTheDocument()
  })

  it('remembers the choice and starts on it next time', async () => {
    const first = render(<PnLTracker />)
    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))
    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))
    await waitFor(() => expect(localStorage.getItem('openalgo_pnltracker_basis')).toBe('m2m'))
    first.unmount()

    fetchMock.mockClear()
    render(<PnLTracker />)

    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))
    expect(new Set(requestedBases())).toEqual(new Set(['m2m']))
    expect(screen.getByText('Current M2M')).toBeInTheDocument()
  })
})
