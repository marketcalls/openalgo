/**
 * What this pins about the latency monitor.
 *
 * The page used to put every recorded call into one set of figures and call
 * them orders. An install with 2,607 records and not one order showed
 * "2,607 orders tracked", and a chart loading its history decided the average
 * a trader read as order speed.
 *
 * So the assertions are about which group the page asks for and what it then
 * calls the figures: orders first, each group on its own, and the Excellent to
 * Slow scale only where it means something. The HTTP client is the stub, not
 * the page's own API module, so the group that reaches the server is checked.
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LatencyLog, LatencyStats } from '@/api/latency'
import { renderWithQuery } from '@/test/queryRender'
import LatencyDashboard from './LatencyDashboard'

const http = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/api/client', () => ({ webClient: { get: http.get } }))
vi.mock('@/utils/toast', () => ({ showToast: { success: vi.fn(), error: vi.fn() } }))

const GROUPS = [
  {
    key: 'orders',
    label: 'Orders',
    description: 'Placing, changing and cancelling orders.',
    rated: true,
  },
  { key: 'account', label: 'Account and books', description: 'Books and funds.', rated: false },
  {
    key: 'market_data',
    label: 'Market data',
    description: 'Quotes, depth and price history.',
    rated: false,
  },
  { key: 'all', label: 'All calls', description: 'Every recorded call together.', rated: false },
]

function figures(total: number, avg: number) {
  return {
    total_orders: total,
    failed_orders: 0,
    success_rate: total ? 100 : 0,
    avg_rtt: avg * 0.8,
    avg_overhead: avg * 0.2,
    avg_total: avg,
    p50_total: avg,
    p99_total: avg * 2,
  }
}

/** The server's answer for one group, given how many calls each group holds. */
function stats(group: string, counts: Record<string, number>, extra: Partial<LatencyStats> = {}) {
  const chosen = GROUPS.find((item) => item.key === group) ?? GROUPS[0]
  const total = counts[group] ?? 0
  return {
    group,
    groups: GROUPS.map((item) => ({ ...item, count: counts[item.key] ?? 0 })),
    label: chosen.label,
    description: chosen.description,
    rated: chosen.rated,
    retention_days: group === 'orders' ? null : 7,
    percentile_window_days: 30,
    ...figures(total, group === 'orders' ? 60 : 1200),
    p90_total: 0,
    p95_total: 0,
    sla_100ms: 100,
    sla_150ms: 100,
    sla_200ms: 100,
    distribution: { excellent: total, good: 0, acceptable: 0, slow: 0 },
    endpoints: [],
    broker_stats: {},
    ...extra,
  } as LatencyStats
}

function log(id: number, group: string, endpoint: string, total: number): LatencyLog {
  return {
    id,
    timestamp: '2026-11-14T10:00:00+05:30',
    order_id: group === 'orders' ? `ORD${id}` : 'unknown',
    broker: 'zerodha',
    symbol: 'SBIN',
    order_type: endpoint.toUpperCase(),
    endpoint,
    group,
    rtt_ms: total * 0.8,
    validation_latency_ms: 0,
    response_latency_ms: 0,
    overhead_ms: total * 0.2,
    total_latency_ms: total,
    status: 'SUCCESS',
    error: null,
  }
}

/** Answer the two routes the page calls from a table keyed by group. */
function serve(byGroup: Record<string, { stats: LatencyStats; logs?: LatencyLog[] }>) {
  http.get.mockImplementation(async (url: string, config?: { params?: { group?: string } }) => {
    const group = config?.params?.group ?? 'missing'
    const answer = byGroup[group]
    if (!answer) throw new Error(`no answer for ${url} group=${group}`)
    return { data: url.endsWith('/stats') ? answer.stats : (answer.logs ?? []) }
  })
}

const groupsAsked = (path: string) =>
  http.get.mock.calls.filter(([url]) => url === path).map(([, config]) => config?.params?.group)

beforeEach(() => {
  http.get.mockReset()
})

describe('LatencyDashboard', () => {
  it('opens on orders and reports only orders as orders', async () => {
    const counts = { orders: 3, market_data: 2604, all: 2607 }
    serve({
      orders: { stats: stats('orders', counts), logs: [log(1, 'orders', 'Place order', 60)] },
    })

    renderWithQuery(<LatencyDashboard />)

    const tracked = (await screen.findByText('Orders Tracked')).parentElement as HTMLElement
    expect(within(tracked).getByText('3')).toBeInTheDocument()
    expect(within(tracked).getByText('All time')).toBeInTheDocument()
    expect(groupsAsked('/latency/api/stats')).toEqual(['orders'])
    expect(groupsAsked('/latency/api/logs')).toEqual(['orders'])

    // The other calls are still there to be chosen, with how many there are.
    const selector = screen.getByRole('group', { name: 'Endpoint group' })
    expect(within(selector).getByRole('button', { name: /Orders/ })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(within(selector).getByRole('button', { name: /Market data.*2,604/ })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
    expect(screen.getByText('Fast Orders')).toBeInTheDocument()
    expect(screen.getByText('Performance Levels')).toBeInTheDocument()
  })

  it('says so when no order has been recorded, however many other calls have', async () => {
    serve({ orders: { stats: stats('orders', { orders: 0, market_data: 2607, all: 2607 }) } })

    renderWithQuery(<LatencyDashboard />)

    expect(await screen.findByText(/No orders have been recorded yet\./)).toHaveTextContent(
      'Other calls have been: choose a group above to see them.'
    )
    const tracked = screen.getByText('Orders Tracked').parentElement as HTMLElement
    expect(within(tracked).getByText('0')).toBeInTheDocument()
    expect(screen.queryByText('Performance Levels')).not.toBeInTheDocument()
  })

  it('shows another group on its own, each endpoint apart, without rating it as an order', async () => {
    const counts = { orders: 3, market_data: 20, all: 23 }
    serve({
      orders: { stats: stats('orders', counts) },
      market_data: {
        stats: stats('market_data', counts, {
          endpoints: [
            { type: 'QUOTES', label: 'Quote', ...figures(10, 20) },
            { type: 'HISTORY', label: 'History', ...figures(10, 1000) },
          ],
        }),
        logs: [log(7, 'market_data', 'History', 1200)],
      },
    })

    renderWithQuery(<LatencyDashboard />)
    fireEvent.click(await screen.findByRole('button', { name: /Market data/ }))

    const tracked = (await screen.findByText('Calls Tracked')).parentElement as HTMLElement
    expect(within(tracked).getByText('20')).toBeInTheDocument()
    expect(within(tracked).getByText('Kept for 7 days')).toBeInTheDocument()
    expect(groupsAsked('/latency/api/stats')).toEqual(['orders', 'market_data'])
    expect(groupsAsked('/latency/api/logs')).toEqual(['orders', 'market_data'])

    // The order scale is gone: a one second history download is not a slow order.
    expect(screen.queryByText('Fast Orders')).not.toBeInTheDocument()
    expect(screen.queryByText('Performance Levels')).not.toBeInTheDocument()
    expect(screen.getByText('Average Response Time')).toBeInTheDocument()
    expect(screen.getByText('Recent Calls')).toBeInTheDocument()

    const byEndpoint = screen.getByText('By Endpoint').closest('[data-slot="card"]') as HTMLElement
    const rows = within(byEndpoint).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual([
      'Quote',
      'History',
    ])
    // The average of each, in its own row: 20 ms and a second, not their mean.
    const average = (row: HTMLElement) => within(row).getAllByRole('cell')[3].textContent
    expect(rows.map(average)).toEqual(['20.00ms', '1000.00ms'])
  })

  it('exports the group that is on screen', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const counts = { orders: 1, market_data: 5, all: 6 }
    serve({
      orders: { stats: stats('orders', counts) },
      market_data: { stats: stats('market_data', counts) },
    })

    renderWithQuery(<LatencyDashboard />)
    fireEvent.click(await screen.findByRole('button', { name: /Market data/ }))
    await screen.findByText('Calls Tracked')
    fireEvent.click(screen.getByRole('button', { name: /Export to CSV/ }))

    expect(open).toHaveBeenCalledWith('/latency/export?group=market_data', '_blank')
    open.mockRestore()
  })

  it('describes a call that is not an order without order words', async () => {
    const counts = { orders: 0, market_data: 1, all: 1 }
    serve({
      orders: { stats: stats('orders', counts) },
      market_data: {
        stats: stats('market_data', counts),
        logs: [log(9, 'market_data', 'History', 1200)],
      },
    })

    renderWithQuery(<LatencyDashboard />)
    fireEvent.click(await screen.findByRole('button', { name: /Market data/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Latency Breakdown' })).toBeInTheDocument()
    expect(within(dialog).getByText('Total Response Time')).toBeInTheDocument()
    expect(within(dialog).queryByText(/Order ID/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText('Slow')).not.toBeInTheDocument()
  })

  it('still shows the figures of a server from before groups', async () => {
    // The page files change when an update is pulled; the server changes when
    // it restarts. In between, the answer has none of the new fields.
    http.get.mockImplementation(async (url: string) => ({
      data: url.endsWith('/stats')
        ? { total_orders: 12, failed_orders: 1, success_rate: 91.7, avg_total: 80, sla_150ms: 90 }
        : [{ ...log(4, 'orders', 'Place order', 80), endpoint: undefined, group: undefined }],
    }))

    renderWithQuery(<LatencyDashboard />)

    const tracked = (await screen.findByText('Orders Tracked')).parentElement as HTMLElement
    expect(within(tracked).getByText('12')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Endpoint group' })).not.toBeInTheDocument()
    expect(screen.queryByText('Latency Distribution')).not.toBeInTheDocument()
    expect(await screen.findByText('PLACE ORDER')).toBeInTheDocument()
  })

  it('says what to do when the figures cannot be read', async () => {
    http.get.mockRejectedValue(new Error('network'))

    renderWithQuery(<LatencyDashboard />)

    expect(await screen.findByText(/The latency figures could not be loaded\./)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /Try again/ })).toBeEnabled())
  })
})
