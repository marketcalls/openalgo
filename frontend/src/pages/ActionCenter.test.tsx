/**
 * An approved order whose send was cut off is shown as not confirmed.
 *
 * The backend claims an approved order for sending by writing broker_status
 * "submitting" before the broker call, and replaces it with the broker's answer
 * on every path that returns. A restart or crash between the two leaves the
 * row in "submitting", and the backend never sends it again (see
 * claim_pending_order_for_execution in database/action_center_db.py). Until
 * now the page did not read broker_status at all, so such a row looked like
 * any other approved order and a trader had no reason to check whether it
 * reached the broker before placing it again.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@/test/test-utils'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('@/api/client', () => ({
  webClient: { get: http.get, post: http.post, delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

vi.mock('@/components/socket/SocketProvider', () => ({
  useSocketContext: () => ({ playAlertSound: () => {}, socket: null }),
}))

import ActionCenterPage from './ActionCenter'

type Row = {
  id: number
  symbol: string
  status: 'pending' | 'approved' | 'rejected'
  broker_status: string | null
}

function order({ id, symbol, status, broker_status }: Row) {
  return {
    id,
    strategy: 'TV Alerts',
    api_type: 'placeorder',
    symbol,
    exchange: 'NSE',
    action: 'BUY',
    quantity: 10,
    price: 0,
    price_type: 'MARKET',
    product_type: 'MIS',
    status,
    created_at_ist: '2026-09-23 10:15:00 IST',
    raw_order_data: { symbol, exchange: 'NSE', action: 'BUY', quantity: 10 },
    broker_order_id: null,
    broker_status,
  }
}

function respondWith(rows: Row[]) {
  http.get.mockResolvedValue({
    data: {
      status: 'success',
      data: {
        orders: rows.map(order),
        statistics: {
          total_pending: rows.filter((r) => r.status === 'pending').length,
          total_approved: rows.filter((r) => r.status === 'approved').length,
          total_rejected: 0,
          total_buy_orders: rows.length,
          total_sell_orders: 0,
        },
      },
    },
  })
}

function rowOf(symbol: string) {
  const row = screen.getByText(symbol).closest('tr')
  if (!row) throw new Error(`no row for ${symbol}`)
  return row
}

const NOTICE_TITLE = 'This order may or may not have reached your broker'

describe('Action Center: an order whose send was not confirmed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('says it may or may not have reached the broker, that it will not be sent again, and what to check', async () => {
    respondWith([{ id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' }])
    render(<ActionCenterPage />)

    expect(await screen.findByText(NOTICE_TITLE)).toBeInTheDocument()
    const notice = screen.getByText(NOTICE_TITLE).closest('[role="alert"]') as HTMLElement
    expect(notice).toHaveTextContent('OpenAlgo will not send it again.')
    expect(notice).toHaveTextContent(
      "Check your broker's order book before you place this order again."
    )
    expect(within(rowOf('SBIN')).getByText('Not confirmed')).toBeInTheDocument()
  })

  it('offers no way to send it again', async () => {
    respondWith([
      { id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' },
      { id: 2, symbol: 'INFY', status: 'pending', broker_status: null },
    ])
    render(<ActionCenterPage />)
    await screen.findByText(NOTICE_TITLE)

    // A pending order has approve and reject beside the details toggle. The
    // unconfirmed one has only the toggle and the delete of any finished row.
    expect(within(rowOf('INFY')).getAllByRole('button')).toHaveLength(3)
    const buttons = within(rowOf('SBIN')).getAllByRole('button')
    expect(buttons).toHaveLength(2)
    expect(buttons[0]).toHaveAccessibleName('Expand order details')
    expect(http.post).not.toHaveBeenCalled()
  })

  it('marks each unconfirmed order, and only those', async () => {
    respondWith([
      { id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' },
      { id: 2, symbol: 'TCS', status: 'approved', broker_status: 'submitting' },
      { id: 3, symbol: 'RELIANCE', status: 'approved', broker_status: 'open' },
      { id: 4, symbol: 'HDFCBANK', status: 'approved', broker_status: 'rejected' },
      { id: 5, symbol: 'INFY', status: 'pending', broker_status: null },
    ])
    render(<ActionCenterPage />)
    await screen.findAllByText(NOTICE_TITLE)

    expect(screen.getAllByText(NOTICE_TITLE)).toHaveLength(2)
    expect(within(rowOf('SBIN')).getByText('Not confirmed')).toBeInTheDocument()
    expect(within(rowOf('TCS')).getByText('Not confirmed')).toBeInTheDocument()
    for (const symbol of ['RELIANCE', 'HDFCBANK', 'INFY']) {
      expect(within(rowOf(symbol)).queryByText('Not confirmed')).not.toBeInTheDocument()
    }
  })

  it('looks exactly as before when every approved order has its broker answer', async () => {
    respondWith([
      { id: 3, symbol: 'RELIANCE', status: 'approved', broker_status: 'complete' },
      { id: 4, symbol: 'ITC', status: 'approved', broker_status: null },
    ])
    render(<ActionCenterPage />)
    await screen.findByText('RELIANCE')

    expect(screen.queryByText(NOTICE_TITLE)).not.toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
  })
})
