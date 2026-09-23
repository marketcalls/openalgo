/**
 * One Socket.IO connection per browser tab.
 *
 * Every Socket.IO connection is a long-poll the server keeps waiting. Under the
 * gthread worker each one holds a request thread for as long as the tab is
 * open, so a page that opened its own connection beside SocketProvider's cost
 * one more thread per tab. The Action Center, the WhatsApp page and Historify
 * each did (Historify by calling useSocket() a second time, which also
 * registered every global alert handler twice).
 *
 * These tests mount the real layouts, the real SocketProvider and the real
 * pages, with only socket.io-client and the HTTP layer faked, and assert that
 * io() runs once, that each page's events reach it on that one connection, and
 * that leaving a page removes its handlers without closing the connection the
 * rest of the tab is using.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { type ReactNode, useState } from 'react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { io } from 'socket.io-client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sio = vi.hoisted(() => {
  class Emitter {
    handlers = new Map<string, Set<(...args: unknown[]) => void>>()

    on(event: string, handler: (...args: unknown[]) => void) {
      const set = this.handlers.get(event) ?? new Set()
      set.add(handler)
      this.handlers.set(event, set)
      return this
    }

    off(event: string, handler: (...args: unknown[]) => void) {
      this.handlers.get(event)?.delete(handler)
      return this
    }

    fire(event: string, ...args: unknown[]) {
      for (const handler of [...(this.handlers.get(event) ?? [])]) handler(...args)
    }

    listenerCount(event: string) {
      return this.handlers.get(event)?.size ?? 0
    }
  }

  /** Stands in for a socket.io-client Socket: records handlers and lifecycle. */
  class FakeSocket extends Emitter {
    connected = true
    active = true
    disconnected = false
    io = new Emitter()
    url: string
    opts: Record<string, unknown>

    constructor(url: string, opts: Record<string, unknown>) {
      super()
      this.url = url
      this.opts = opts
    }

    emit() {
      return this
    }

    connect() {
      return this
    }

    disconnect() {
      this.disconnected = true
      this.connected = false
      this.active = false
      return this
    }
  }

  return { FakeSocket, created: [] as FakeSocket[] }
})

vi.mock('socket.io-client', () => ({
  io: vi.fn((url: string, opts: Record<string, unknown>) => {
    const socket = new sio.FakeSocket(url, opts)
    sio.created.push(socket)
    return socket
  }),
}))

const toasts = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}))

vi.mock('sonner', () => ({ toast: toasts, Toaster: () => null }))

const http = vi.hoisted(() => ({
  get: vi.fn(),
  getConfig: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  webClient: { get: http.get, post: vi.fn(), delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

vi.mock('@/api/whatsapp', () => ({
  whatsappApi: {
    getConfig: http.getConfig,
    startPair: vi.fn(),
    unlinkDevice: vi.fn(),
    sendToPhone: vi.fn(),
  },
}))

// The shell around the page is not under test and fetches on its own.
vi.mock('@/components/layout/Navbar', () => ({ Navbar: () => null }))
vi.mock('@/components/layout/Footer', () => ({ Footer: () => null }))
vi.mock('@/components/layout/MobileBottomNav', () => ({ MobileBottomNav: () => null }))
vi.mock('@/hooks/useProfileMenuItems', () => ({ useProfileMenuItems: () => [] }))

import { FullWidthLayout } from '@/components/layout/FullWidthLayout'
import { Layout } from '@/components/layout/Layout'
import { useOrderEventRefresh, useSocketConnection } from '@/hooks/useOrderEventRefresh'
import ActionCenterPage from '@/pages/ActionCenter'
import Historify from '@/pages/Historify'
import WhatsAppIndex from '@/pages/whatsapp/WhatsAppIndex'
import { useAuthStore } from '@/stores/authStore'

/** The provider's global alert handlers, registered once per connection. */
const PROVIDER_EVENTS = [
  'force_logout',
  'master_contract_download',
  'order_event',
  'cancel_order_event',
  'modify_order_event',
  'close_position_event',
  'order_notification',
  'active_sessions_update',
  'analyzer_update',
]

function liveSockets() {
  return sio.created.filter((socket) => !socket.disconnected)
}

function onlySocket() {
  expect(io).toHaveBeenCalledTimes(1)
  expect(liveSockets()).toHaveLength(1)
  return sio.created[0]
}

/** Renders a page and a button that unmounts it without leaving the route. */
function Removable({ children }: { children: ReactNode }) {
  const [shown, setShown] = useState(true)
  return (
    <>
      <button type="button" onClick={() => setShown(false)}>
        remove page
      </button>
      {shown ? children : null}
    </>
  )
}

function renderAt(path: string, routes: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>{routes}</Routes>
    </MemoryRouter>
  )
}

function actionCenterData(orders: unknown[] = []) {
  return {
    data: {
      status: 'success',
      data: {
        orders,
        statistics: {
          total_pending: 0,
          total_approved: 0,
          total_rejected: 0,
          total_buy_orders: 0,
          total_sell_orders: 0,
        },
      },
    },
  }
}

const WHATSAPP_BUNDLE = {
  config: {
    is_paired: false,
    is_active: false,
    own_jid: null,
    own_phone: null,
    bot_username: null,
    owner_user_id: null,
    owner_username: null,
    paired_at: null,
    max_message_length: 4096,
    rate_limit_per_minute: 30,
    broadcast_enabled: false,
  },
  pair_state: {
    status: 'idle',
    qr_data_url: null,
    pair_code: null,
    error: null,
    started_at: null,
    paired_at: null,
  },
}

function historifyFetch(url: string) {
  let body: unknown = { status: 'success', data: [] }
  if (url.includes('historify-intervals')) {
    body = {
      status: 'success',
      storage_intervals: ['1m', 'D'],
      computed_intervals: [],
      all_intervals: ['1m', 'D'],
    }
  } else if (url.includes('/historify/api/stats')) {
    body = {
      status: 'success',
      data: { database_size_mb: 0, total_records: 0, total_symbols: 0, watchlist_count: 0 },
    }
  } else if (url.includes('/historify/api/intervals')) {
    body = { status: 'success', data: { seconds: [], minutes: [], hours: [], days: ['D'] } }
  }
  return Promise.resolve({ ok: true, status: 200, json: async () => body })
}

beforeEach(() => {
  sio.created.length = 0
  vi.mocked(io).mockClear()
  for (const fn of Object.values(toasts)) fn.mockClear()
  http.get.mockReset().mockResolvedValue(actionCenterData())
  http.getConfig.mockReset().mockResolvedValue(WHATSAPP_BUNDLE)
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => historifyFetch(String(input)))
  )
  vi.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(window.HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  localStorage.clear()
  useAuthStore.setState({
    isAuthenticated: true,
    user: { username: 'trader', broker: 'zerodha', isLoggedIn: true, loginTime: null },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('SocketProvider', () => {
  it('opens one polling connection with the settings the pages have always used', () => {
    renderAt(
      '/probe',
      <Route element={<Layout />}>
        <Route path="/probe" element={<p>page</p>} />
      </Route>
    )

    const socket = onlySocket()
    expect(socket.opts).toMatchObject({
      transports: ['polling'],
      upgrade: false,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: true,
    })
    for (const event of PROVIDER_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })

  it('never has two connections open at once when the trader moves between pages', async () => {
    function GoTo({ to }: { to: string }) {
      const navigate = useNavigate()
      return (
        <button type="button" onClick={() => navigate(to)}>
          go {to}
        </button>
      )
    }

    renderAt(
      '/one',
      <Route element={<Layout />}>
        <Route path="/one" element={<GoTo to="/two" />} />
        <Route path="/two" element={<GoTo to="/one" />} />
      </Route>
    )
    expect(liveSockets()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'go /two' }))
    await screen.findByRole('button', { name: 'go /one' })
    expect(liveSockets()).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'go /one' }))
    await screen.findByRole('button', { name: 'go /two' })
    expect(liveSockets()).toHaveLength(1)
  })
})

describe('Action Center on the shared connection', () => {
  function renderActionCenter() {
    return renderAt(
      '/action-center',
      <Route element={<Layout />}>
        <Route
          path="/action-center"
          element={
            <Removable>
              <ActionCenterPage />
            </Removable>
          }
        />
      </Route>
    )
  }

  it('opens no connection of its own', async () => {
    renderActionCenter()
    await screen.findByText('Review and manage pending orders')

    const socket = onlySocket()
    expect(socket.listenerCount('pending_order_created')).toBe(1)
    expect(socket.listenerCount('pending_order_updated')).toBe(1)
  })

  it('still alerts and refreshes when an order is queued', async () => {
    renderActionCenter()
    await screen.findByText('Review and manage pending orders')
    const socket = onlySocket()
    const fetchesBefore = http.get.mock.calls.length

    act(() => {
      socket.fire('pending_order_created', { api_type: 'placeorder', message: 'BUY 75 NIFTY' })
    })

    expect(toasts.warning).toHaveBeenCalledWith('New Order Queued: BUY 75 NIFTY', {
      duration: 5000,
    })
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled()
    await waitFor(() => expect(http.get.mock.calls.length).toBe(fetchesBefore + 1))
  })

  it('still refreshes when an order is approved, rejected or deleted elsewhere', async () => {
    renderActionCenter()
    await screen.findByText('Review and manage pending orders')
    const socket = onlySocket()
    const fetchesBefore = http.get.mock.calls.length

    act(() => {
      socket.fire('pending_order_updated', { action: 'approved', order_id: 7 })
    })

    await waitFor(() => expect(http.get.mock.calls.length).toBe(fetchesBefore + 1))
  })

  it('removes only its own handlers when the trader leaves, and keeps the connection', async () => {
    renderActionCenter()
    await screen.findByText('Review and manage pending orders')
    const socket = onlySocket()

    fireEvent.click(screen.getByRole('button', { name: 'remove page' }))

    expect(socket.listenerCount('pending_order_created')).toBe(0)
    expect(socket.listenerCount('pending_order_updated')).toBe(0)
    expect(socket.io.listenerCount('reconnect_failed')).toBe(0)
    expect(socket.disconnected).toBe(false)
    for (const event of PROVIDER_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })

  it('keeps the shared connection retrying while it is open, as its own connection did', async () => {
    renderActionCenter()
    await screen.findByText('Review and manage pending orders')
    const socket = onlySocket()

    expect(socket.io.listenerCount('reconnect_failed')).toBe(1)
  })
})

describe('WhatsApp page on the shared connection', () => {
  function renderWhatsApp() {
    return renderAt(
      '/whatsapp',
      <Route element={<Layout />}>
        <Route
          path="/whatsapp"
          element={
            <Removable>
              <WhatsAppIndex />
            </Removable>
          }
        />
      </Route>
    )
  }

  const WHATSAPP_EVENTS = [
    'whatsapp_qr',
    'whatsapp_pair_code',
    'whatsapp_paired',
    'whatsapp_pair_status',
    'whatsapp_status',
  ]

  it('opens no connection of its own', async () => {
    renderWhatsApp()
    await screen.findByText('No device linked yet')

    const socket = onlySocket()
    for (const event of WHATSAPP_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })

  it('still shows each new pairing QR as it arrives', async () => {
    renderWhatsApp()
    await screen.findByText('No device linked yet')
    const socket = onlySocket()

    act(() => {
      socket.fire('whatsapp_qr', { data_url: 'data:image/png;base64,AAAA' })
    })

    expect(await screen.findByAltText('WhatsApp pairing QR')).toHaveAttribute(
      'src',
      'data:image/png;base64,AAAA'
    )
  })

  it('removes only its own handlers when the trader leaves, and keeps the connection', async () => {
    renderWhatsApp()
    await screen.findByText('No device linked yet')
    const socket = onlySocket()

    fireEvent.click(screen.getByRole('button', { name: 'remove page' }))

    for (const event of WHATSAPP_EVENTS) expect(socket.listenerCount(event)).toBe(0)
    expect(socket.disconnected).toBe(false)
    for (const event of PROVIDER_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })
})

describe('Historify on the shared connection', () => {
  const HISTORIFY_EVENTS = [
    'historify_progress',
    'historify_job_complete',
    'historify_job_paused',
    'historify_job_cancelled',
    'historify_schedule_created',
    'historify_schedule_updated',
    'historify_schedule_deleted',
    'historify_schedule_execution_started',
    'historify_schedule_execution_complete',
  ]

  function renderHistorify() {
    return renderAt(
      '/historify',
      <Route element={<FullWidthLayout />}>
        <Route
          path="/historify"
          element={
            <Removable>
              <Historify />
            </Removable>
          }
        />
      </Route>
    )
  }

  it('opens no second connection and registers the global alerts only once', async () => {
    renderHistorify()

    const socket = onlySocket()
    await waitFor(() => {
      for (const event of HISTORIFY_EVENTS) expect(socket.listenerCount(event)).toBe(1)
    })
    for (const event of PROVIDER_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })

  it('shows one order alert per order, not two', async () => {
    renderHistorify()
    const socket = onlySocket()

    act(() => {
      socket.fire('order_event', { symbol: 'SBIN', action: 'BUY', orderid: '42' })
    })

    expect(toasts.success).toHaveBeenCalledTimes(1)
    expect(toasts.success).toHaveBeenCalledWith('BUY Order Placed for Symbol: SBIN, Order ID: 42')
  })

  it('still reports a cancelled download job', async () => {
    renderHistorify()
    const socket = onlySocket()
    await waitFor(() => expect(socket.listenerCount('historify_job_cancelled')).toBe(1))

    act(() => {
      socket.fire('historify_job_cancelled', { job_id: 'j1', status: 'cancelled' })
    })

    expect(toasts.info).toHaveBeenCalledWith('Job cancelled', undefined)
  })

  it('removes only its own handlers when the trader leaves, and keeps the connection', async () => {
    renderHistorify()
    const socket = onlySocket()
    await waitFor(() => expect(socket.listenerCount('historify_progress')).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: 'remove page' }))

    for (const event of HISTORIFY_EVENTS) expect(socket.listenerCount(event)).toBe(0)
    expect(socket.disconnected).toBe(false)
    for (const event of PROVIDER_EVENTS) expect(socket.listenerCount(event)).toBe(1)
  })
})

describe('order event hooks on the shared connection', () => {
  it('lets several panels on one page listen without opening a connection each', async () => {
    const panelA = vi.fn()
    const panelB = vi.fn()
    const seen: Array<{ connected: boolean; sameSocket: boolean }> = []

    function Panels() {
      useOrderEventRefresh(panelA, { events: ['order_event', 'close_position_event'], delay: 0 })
      useOrderEventRefresh(panelB, { events: ['order_event', 'analyzer_update'], delay: 0 })
      const { socket, isConnected } = useSocketConnection()
      seen.push({ connected: isConnected, sameSocket: socket === (sio.created[0] ?? null) })
      return <p>panels</p>
    }

    renderAt(
      '/trading',
      <Route element={<Layout />}>
        <Route path="/trading" element={<Panels />} />
      </Route>
    )
    await screen.findByText('panels')

    const socket = onlySocket()
    await waitFor(() => expect(seen.at(-1)).toEqual({ connected: true, sameSocket: true }))

    act(() => {
      socket.fire('order_event', { symbol: 'SBIN', action: 'BUY', orderid: '42' })
    })
    await waitFor(() => {
      expect(panelA).toHaveBeenCalledTimes(1)
      expect(panelB).toHaveBeenCalledTimes(1)
    })
  })
})
