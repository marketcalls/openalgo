/**
 * The latency page's order figures count order calls only (issue #2286).
 *
 * Every wrapped API call (QUOTES, HISTORY, PING, ...) is logged beside the
 * orders. The server marks each log row with is_order and reports the calls it
 * left out of the order stats as non_order_calls.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@/test/test-utils'

const http = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/api/client', () => ({
  webClient: { get: http.get, post: vi.fn(), delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

import LatencyDashboard from './LatencyDashboard'

function log(id: number, order_type: string, total: number, is_order: boolean) {
  return {
    id,
    timestamp: '2026-11-11T10:00:00+05:30',
    order_id: is_order ? `ord-${id}` : 'unknown',
    broker: 'zerodha',
    symbol: 'SBIN',
    order_type,
    rtt_ms: total,
    validation_latency_ms: 0,
    response_latency_ms: 0,
    overhead_ms: 0,
    total_latency_ms: total,
    status: 'SUCCESS',
    error: null,
    is_order,
  }
}

const logs = [
  log(1, 'PLACE', 80, true),
  log(2, 'HISTORY', 1500, false),
  log(3, 'QUOTES', 900, false),
  log(4, 'PING', 5, false),
]

const stats = {
  total_orders: 1,
  non_order_calls: 3,
  success_rate: 100,
  failed_orders: 0,
  avg_total: 80,
  sla_150ms: 100,
  broker_stats: {},
}

function distributionCell(label: string) {
  const heading = screen.getByText(label)
  return within(heading.parentElement as HTMLElement)
}

describe('LatencyDashboard', () => {
  beforeEach(() => {
    http.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith('/stats') ? stats : logs })
    )
  })

  it('builds the latency distribution from order calls only', async () => {
    render(<LatencyDashboard />)

    await screen.findByText('Excellent (<150ms)')
    // The ping (5ms) is not an order, and neither are the slow data calls.
    expect(distributionCell('Excellent (<150ms)').getByText('1')).toBeInTheDocument()
    expect(distributionCell('Slow (>400ms)').getByText('0')).toBeInTheDocument()
  })

  it('says how many data calls the order count leaves out', async () => {
    render(<LatencyDashboard />)

    expect(await screen.findByText('3 other API calls not counted')).toBeInTheDocument()
  })

  it('labels the recent table as API calls, not orders', async () => {
    render(<LatencyDashboard />)

    expect(await screen.findByText('Recent API Calls')).toBeInTheDocument()
    expect(screen.getByText('4 calls, 1 of them orders')).toBeInTheDocument()
    expect(screen.queryByText('4 orders tracked')).not.toBeInTheDocument()
  })
})
