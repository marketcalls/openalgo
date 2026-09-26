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
import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils'

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

import ActionCenterPage, { SEND_SETTLE_MS } from './ActionCenter'

type Row = {
  id: number
  symbol: string
  status: 'pending' | 'approved' | 'rejected'
  broker_status: string | null
  /** Seconds since approval, as the server measures it when the list is read. */
  approved_age_seconds?: number | null | (() => number)
}

/** Long past any send: an order still claimed this old was cut off. */
const LONG_AGO = 600

function order({ id, symbol, status, broker_status, approved_age_seconds }: Row) {
  const age =
    typeof approved_age_seconds === 'function'
      ? approved_age_seconds()
      : approved_age_seconds === undefined
        ? status === 'approved'
          ? LONG_AGO
          : null
        : approved_age_seconds
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
    approved_age_seconds: age,
  }
}

function respondWith(rows: Row[]) {
  // Built on every request, so an age given as a function grows as the
  // server's would.
  http.get.mockImplementation(async () => ({
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
  }))
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

describe('Action Center: an order that is still being sent', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('shows a send still under way as sending, with no notice to check the order book', async () => {
    // Approved three seconds ago and waiting on the broker: under gthread the
    // broker's rate limit can hold it for ten seconds before the call is made.
    respondWith([
      {
        id: 1,
        symbol: 'SBIN',
        status: 'approved',
        broker_status: 'submitting',
        approved_age_seconds: 3,
      },
    ])
    render(<ActionCenterPage />)

    expect(await within(await findRow('SBIN')).findByText('Sending')).toBeInTheDocument()
    expect(screen.queryByText(NOTICE_TITLE)).not.toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
  })

  it('shows a send as not confirmed once no send could still be running', async () => {
    const approvedAt = Date.now() - (SEND_SETTLE_MS - 300)
    respondWith([
      {
        id: 1,
        symbol: 'SBIN',
        status: 'approved',
        broker_status: 'submitting',
        approved_age_seconds: () => (Date.now() - approvedAt) / 1000,
      },
    ])
    render(<ActionCenterPage />)

    expect(await within(await findRow('SBIN')).findByText('Sending')).toBeInTheDocument()
    expect(screen.queryByText(NOTICE_TITLE)).not.toBeInTheDocument()

    expect(await screen.findByText(NOTICE_TITLE, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(within(rowOf('SBIN')).getByText('Not confirmed')).toBeInTheDocument()
    expect(within(rowOf('SBIN')).queryByText('Sending')).not.toBeInTheDocument()
  })
})

describe('Action Center: the All Orders tab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('asks for every order, not only the pending ones', async () => {
    respondWith([{ id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' }])
    render(<ActionCenterPage />)
    await screen.findByText('SBIN')
    expect(http.get).toHaveBeenLastCalledWith('/action-center/api/data?status=pending')

    const allTab = screen.getByRole('tab', { name: 'All Orders' })
    fireEvent.mouseDown(allTab)
    fireEvent.click(allTab)

    await waitFor(() =>
      expect(http.get).toHaveBeenLastCalledWith('/action-center/api/data?status=all')
    )
  })
})

async function findRow(symbol: string) {
  const cell = await screen.findByText(symbol)
  const row = cell.closest('tr')
  if (!row) throw new Error(`no row for ${symbol}`)
  return row as HTMLElement
}
