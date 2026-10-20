/**
 * A claimed order has no recorded broker answer while it is being sent and
 * after an interrupted send. Age alone cannot tell those cases apart, since
 * split and basket orders may send for longer than two minutes.
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
  api_type?: string
  /** Seconds since approval, as the server measures it when the list is read. */
  approved_age_seconds?: number | null | (() => number)
}

/** Old enough to investigate, while a large split order may still be sending. */
const LONG_AGO = 600

function order({ id, symbol, status, broker_status, api_type, approved_age_seconds }: Row) {
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
    api_type: api_type ?? 'placeorder',
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

const NOTICE_TITLE = 'This order may still be sending'

describe('Action Center: a send without a broker answer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('says an old send may still be running and warns against placing it again', async () => {
    respondWith([{ id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' }])
    render(<ActionCenterPage />)

    expect(await screen.findByText(NOTICE_TITLE)).toBeInTheDocument()
    const notice = screen.getByText(NOTICE_TITLE).closest('[role="alert"]') as HTMLElement
    expect(notice).toHaveTextContent('A split or basket order can take longer than two minutes.')
    expect(notice).toHaveTextContent('Do not place this order again while its status is unclear.')
    expect(notice).not.toHaveTextContent('will not send it again')
    expect(within(rowOf('SBIN')).getByText('Status unclear')).toBeInTheDocument()
  })

  it('offers no way to send it again', async () => {
    respondWith([
      { id: 1, symbol: 'SBIN', status: 'approved', broker_status: 'submitting' },
      { id: 2, symbol: 'INFY', status: 'pending', broker_status: null },
    ])
    render(<ActionCenterPage />)
    await screen.findByText(NOTICE_TITLE)

    // A pending order has approve and reject beside the details toggle. The
    // claimed one has only the toggle and the delete of any approved row.
    expect(within(rowOf('INFY')).getAllByRole('button')).toHaveLength(3)
    const buttons = within(rowOf('SBIN')).getAllByRole('button')
    expect(buttons).toHaveLength(2)
    expect(buttons[0]).toHaveAccessibleName('Expand order details')
    expect(http.post).not.toHaveBeenCalled()
  })

  it('marks each overdue claimed order, and only those', async () => {
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
    expect(within(rowOf('SBIN')).getByText('Status unclear')).toBeInTheDocument()
    expect(within(rowOf('TCS')).getByText('Status unclear')).toBeInTheDocument()
    for (const symbol of ['RELIANCE', 'HDFCBANK', 'INFY']) {
      expect(within(rowOf(symbol)).queryByText('Status unclear')).not.toBeInTheDocument()
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
    expect(screen.queryByText('Status unclear')).not.toBeInTheDocument()
  })

  it('does not imply that long-running split and basket sends stopped', async () => {
    respondWith([
      {
        id: 1,
        symbol: 'SBIN',
        status: 'approved',
        broker_status: 'submitting',
        api_type: 'splitorder',
        approved_age_seconds: 180,
      },
      {
        id: 2,
        symbol: 'TCS',
        status: 'approved',
        broker_status: 'submitting',
        api_type: 'basketorder',
        approved_age_seconds: 240,
      },
    ])
    render(<ActionCenterPage />)

    expect(await screen.findAllByText(NOTICE_TITLE)).toHaveLength(2)
    for (const symbol of ['SBIN', 'TCS']) {
      expect(within(rowOf(symbol)).getByText('Status unclear')).toBeInTheDocument()
    }
    for (const notice of screen.getAllByText(NOTICE_TITLE)) {
      const alert = notice.closest('[role="alert"]') as HTMLElement
      expect(alert).toHaveTextContent('Sending may still be in progress')
      expect(alert).not.toHaveTextContent('will not send it again')
    }
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
    expect(screen.queryByText('Status unclear')).not.toBeInTheDocument()
  })

  it('keeps an overdue send uncertain because it may still be running', async () => {
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
    expect(within(rowOf('SBIN')).getByText('Status unclear')).toBeInTheDocument()
    expect(within(rowOf('SBIN')).queryByText('Sending')).not.toBeInTheDocument()
    expect(screen.getByText(NOTICE_TITLE).closest('[role="alert"]')).toHaveTextContent(
      'Do not place this order again while its status is unclear.'
    )
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
