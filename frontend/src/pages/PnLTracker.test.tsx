/**
 * The P&L | M2M switch on the P&L Tracker.
 *
 * Off (the default) asks the server for the broker's own P&L, the same basis as
 * the Positions page; on asks for today's M2M. The choice is remembered, the
 * curve reloads when it changes, and the card titles follow it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, userEvent, waitFor } from '@/test/test-utils'

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

// What the server says it built, given what was asked for. By default it delivers
// what was asked; a test can make it fall back to the built-in curve.
let deliver: (requested: string) => string = (requested) => requested

function requestedBases(): string[] {
  return fetchMock.mock.calls
    .filter(([url]) => url === '/pnltracker/api/pnl')
    .map(([, init]) => JSON.parse((init as RequestInit).body as string).basis)
}

describe('PnL Tracker basis switch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    deliver = (requested) => requested
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => ({
      ok: true,
      json: async () =>
        url === '/auth/csrf-token'
          ? { csrf_token: 'tok' }
          : {
              status: 'success',
              data: { ...DATA, basis: deliver(JSON.parse(String(init?.body ?? '{}')).basis) },
            },
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

  it('does not title a built-in curve M2M, and says M2M was not delivered', async () => {
    deliver = () => 'legacy'
    render(<PnLTracker />)
    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    await waitFor(() => expect(requestedBases()).toContain('m2m'))
    expect(
      await screen.findByText(/could not be worked out for your positions/)
    ).toBeInTheDocument()
    // The cards say what was delivered: the built-in curve is a P&L curve.
    expect(screen.getByText('Current P&L')).toBeInTheDocument()
    expect(screen.queryByText('Current M2M')).not.toBeInTheDocument()
  })

  it('shows no warning when M2M is delivered', async () => {
    render(<PnLTracker />)
    await waitFor(() => expect(requestedBases().length).toBeGreaterThan(0))

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))

    expect(await screen.findByText('Current M2M')).toBeInTheDocument()
    expect(screen.queryByText(/could not be worked out for your positions/)).not.toBeInTheDocument()
  })

  it('ignores an older response that arrives after a newer one', async () => {
    let releaseSlow: () => void = () => {}
    const slow = new Promise<void>((resolve) => {
      releaseSlow = resolve
    })
    let pnlCalls = 0
    let lateAnswerGiven = false
    // Different figures per basis, so a stale answer would show in the numbers too.
    const figures = { pnl: 3906.5, m2m: 10887.5 } as Record<string, number>
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/auth/csrf-token') return { ok: true, json: async () => ({ csrf_token: 'tok' }) }
      const requested = JSON.parse(String(init?.body ?? '{}')).basis
      pnlCalls += 1
      const isLate = pnlCalls === 1
      // The first request (broker P&L) is slow and answers last.
      if (isLate) await slow
      return {
        ok: true,
        json: async () => {
          if (isLate) lateAnswerGiven = true
          return {
            status: 'success',
            data: { ...DATA, current_mtm: figures[requested], basis: requested },
          }
        },
      }
    })
    render(<PnLTracker />)
    await waitFor(() => expect(requestedBases()).toContain('pnl'))

    await userEvent.click(screen.getByRole('switch', { name: /M2M/ }))
    expect(await screen.findByText('Current M2M')).toBeInTheDocument()

    await waitFor(() => expect(screen.getAllByText(/10,887\.50/).length).toBeGreaterThan(0))

    releaseSlow()
    await waitFor(() => expect(lateAnswerGiven).toBe(true))
    await act(async () => {}) // let React apply (or ignore) what the page just received

    // The late broker-P&L answer changed neither the titles nor the numbers.
    expect(screen.getByText('Current M2M')).toBeInTheDocument()
    expect(screen.queryByText('Current P&L')).not.toBeInTheDocument()
    expect(screen.getAllByText(/10,887\.50/).length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/3,906\.50/)).toHaveLength(0)
  })
})
