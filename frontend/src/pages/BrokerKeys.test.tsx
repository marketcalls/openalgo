import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { InternalAxiosRequestConfig } from 'axios'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { brokerQueryKeys } from '@/api/brokerKeys'
import { webClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { answer } from '@/test/axiosAnswer'
import { showToast } from '@/utils/toast'
import BrokerKeys from './BrokerKeys'

/**
 * These run the real webClient, with an adapter answering like the server, so
 * the CSRF header and the error handling are the ones the page ships with, and
 * a real QueryClient, so the cache the page reads and invalidates is checked.
 */

vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

function entry(broker: string, name: string, overrides: Record<string, unknown> = {}) {
  return {
    broker,
    name,
    source: 'saved',
    api_key: `${broker.slice(0, 4)}12********`,
    api_key_set: true,
    api_secret: '********',
    api_secret_set: true,
    api_key_market: '',
    api_key_market_set: false,
    api_secret_market: '',
    api_secret_market_set: false,
    redirect_url: `http://127.0.0.1:5000/${broker}/callback`,
    enabled: true,
    overridden_by_env: false,
    updated_at: '2026-10-30T10:00:00+00:00',
    ...overrides,
  }
}

const KEYS = {
  brokers: [
    entry('zerodha', 'Zerodha', {
      overridden_by_env: true,
      redirect_url: 'https://algo.example.com/zerodha/callback',
    }),
    entry('angel', 'Angel One'),
    entry('fyers', 'Fyers', { enabled: false }),
    entry('fivepaisaxts', '5 Paisa (XTS)', {
      api_key_market: 'mkt123********',
      api_key_market_set: true,
      api_secret_market: '********',
      api_secret_market_set: true,
    }),
  ],
  env: {
    ...entry('zerodha', 'Zerodha', { source: 'env' }),
    api_key: 'envk12********',
    enabled: undefined,
    overridden_by_env: undefined,
    updated_at: undefined,
  },
  enabled_brokers: [
    { broker: 'zerodha', name: 'Zerodha' },
    { broker: 'angel', name: 'Angel One' },
    { broker: 'fivepaisaxts', name: '5 Paisa (XTS)' },
    { broker: 'dhan', name: 'Dhan' },
    { broker: 'upstox', name: 'Upstox' },
  ],
  live_broker: 'angel',
  default_redirect_urls: {
    zerodha: 'http://127.0.0.1:5000/zerodha/callback',
    angel: 'http://127.0.0.1:5000/angel/callback',
    fivepaisaxts: 'http://127.0.0.1:5000/fivepaisaxts/callback',
    dhan: 'http://127.0.0.1:5000/dhan/callback',
    upstox: 'http://127.0.0.1:5000/upstox/callback',
  },
}

interface Call {
  method: string
  url: string
  body: unknown
  csrf: unknown
}

type Answer = [number, unknown]

let calls: Call[] = []
let respond: (call: Call) => Answer | Promise<Answer>
let client: QueryClient

const originalAdapter = webClient.defaults.adapter

function defaultRespond(call: Call): Answer {
  if (call.method === 'get' && call.url === '/api/broker/keys') {
    return [200, { status: 'success', data: KEYS }]
  }
  if (call.method === 'post' && call.url === '/api/broker/keys') {
    return [200, { status: 'success', message: 'Saved the keys.' }]
  }
  if (call.method === 'delete') return [200, { status: 'success', message: 'Removed the keys.' }]
  if (call.url === '/api/broker/keys/import-env') {
    return [200, { status: 'success', message: 'Copied the Zerodha keys from .env.' }]
  }
  return [404, { status: 'error', message: 'Not found' }]
}

beforeEach(() => {
  vi.clearAllMocks()
  calls = []
  respond = defaultRespond
  webClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const call: Call = {
      method: String(config.method),
      url: String(config.url),
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
      csrf: config.headers?.['X-CSRFToken'],
    }
    calls.push(call)
    const [status, data] = await respond(call)
    return answer(status, data)(config)
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ csrf_token: 'csrf-9' }) }))
  )
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

afterEach(() => {
  webClient.defaults.adapter = originalAdapter
  vi.unstubAllGlobals()
})

function renderPage() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/broker/keys']}>
        <BrokerKeys />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function card(name: string) {
  return screen.findByRole('article', { name: `${name} keys` })
}

function writes() {
  return calls.filter((c) => c.method !== 'get')
}

function listReads() {
  return calls.filter((c) => c.method === 'get' && c.url === '/api/broker/keys')
}

/** Everything the QueryClient holds: every query's data and every mutation's variables. */
function cacheText() {
  return JSON.stringify({
    queries: client
      .getQueryCache()
      .getAll()
      .map((q) => q.state.data),
    mutations: client
      .getMutationCache()
      .getAll()
      .map((m) => m.state.variables),
  })
}

/** Stand-in for the broker login page's cached list, to see it go stale. */
function seedLoginList() {
  client.setQueryData(brokerQueryKeys.config(), {
    broker_name: 'zerodha',
    brokers: [],
    live_broker: 'angel',
  })
}

describe('BrokerKeys', () => {
  it('shows masked keys and what state each broker is in', async () => {
    renderPage()

    const zerodha = await card('Zerodha')
    expect(within(zerodha).getByText('zero12********')).toBeInTheDocument()
    // A secret shows no character of its own.
    expect(within(zerodha).getByText('********')).toBeInTheDocument()
    expect(within(zerodha).getByText('Not used while .env sets this broker')).toBeInTheDocument()
    expect(within(zerodha).queryByText('Logged in')).not.toBeInTheDocument()

    const angel = await card('Angel One')
    expect(within(angel).getByText('Logged in')).toBeInTheDocument()

    const fyers = await card('Fyers')
    expect(within(fyers).getByText('Not enabled in VALID_BROKERS')).toBeInTheDocument()

    const xts = await card('5 Paisa (XTS)')
    expect(within(xts).getByText('mkt123********')).toBeInTheDocument()

    // The .env broker has a card of its own.
    expect(screen.getByText('From .env file')).toBeInTheDocument()
    expect(screen.getByText('envk12********')).toBeInTheDocument()
  })

  it('will not edit or remove the broker that is logged in', async () => {
    renderPage()

    const angel = await card('Angel One')
    expect(within(angel).getByRole('button', { name: 'Edit Angel One keys' })).toBeDisabled()
    expect(within(angel).getByRole('button', { name: 'Remove Angel One keys' })).toBeDisabled()
    expect(within(angel).getByText(/Log out first to change or remove its keys/)).toBeVisible()

    const zerodha = await card('Zerodha')
    expect(within(zerodha).getByRole('button', { name: 'Edit Zerodha keys' })).toBeEnabled()
    expect(within(zerodha).getByRole('button', { name: 'Remove Zerodha keys' })).toBeEnabled()
  })

  it('sends only the fields the trader typed when editing', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Edit Zerodha keys' }))
    expect(screen.getByText('Edit Zerodha keys')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('API secret'), 'new-secret-value')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(writes()).toHaveLength(1))
    const [save] = writes()
    expect(save.method).toBe('post')
    expect(save.url).toBe('/api/broker/keys')
    expect(save.csrf).toBe('csrf-9')
    // An untouched field, the redirect URL included, is left out and kept.
    expect(save.body).toEqual({ broker: 'zerodha', api_secret: 'new-secret-value' })
  })

  it('sends the redirect URL only when the trader changes it', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Edit Zerodha keys' }))
    const redirect = screen.getByLabelText('Redirect URL')
    expect(redirect).toHaveValue('https://algo.example.com/zerodha/callback')
    await userEvent.clear(redirect)
    await userEvent.type(redirect, 'https://new.example.com/zerodha/callback')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({
      broker: 'zerodha',
      redirect_url: 'https://new.example.com/zerodha/callback',
    })
  })

  it('clears every secret input after a save', async () => {
    renderPage()

    // Add mode starts on the first enabled broker with no saved keys.
    await screen.findByText('Add a broker')
    await userEvent.type(screen.getByLabelText('API key'), 'client1:::key1')
    await userEvent.type(screen.getByLabelText('API secret'), 'typed-secret')
    await userEvent.type(screen.getByLabelText('Market data API key'), 'typed-market-key')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(showToast.success).toHaveBeenCalledWith('Saved the keys.'))
    expect(writes()[0].body).toEqual({
      broker: 'dhan',
      api_key: 'client1:::key1',
      api_secret: 'typed-secret',
      api_key_market: 'typed-market-key',
    })
    await waitFor(() => expect(screen.getByLabelText('API key')).toHaveValue(''))
    expect(screen.getByLabelText('API secret')).toHaveValue('')
    expect(screen.getByLabelText('Market data API key')).toHaveValue('')
    expect(screen.getByLabelText('Market data API secret')).toHaveValue('')
    expect(screen.queryByDisplayValue('typed-secret')).not.toBeInTheDocument()
  })

  it('shows the server sentence when a save is refused and keeps it off the list', async () => {
    const refusal = "Dhan API key must be in format: 'client_id:::api_key'"
    respond = (call) =>
      call.method === 'post' ? [400, { status: 'error', message: refusal }] : defaultRespond(call)
    renderPage()

    await screen.findByText('Add a broker')
    expect(screen.getByText('client_id:::api_key')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('API key'), 'no-separator')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(showToast.success).not.toHaveBeenCalled()
    // A refused body is not kept either.
    await waitFor(() => expect(cacheText()).not.toContain('no-separator'))
  })

  it('refuses to add a broker without its API key before asking the server', async () => {
    renderPage()

    await screen.findByText('Add a broker')
    await userEvent.type(screen.getByLabelText('API secret'), 'only-a-secret')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    expect(await screen.findByText('Enter the API key to save this broker.')).toBeInTheDocument()
    expect(writes()).toHaveLength(0)
  })

  it('asks for the market data keys to be removed instead of sending them', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Edit 5 Paisa (XTS) keys' }))
    await userEvent.click(screen.getByLabelText('Remove saved market data keys'))
    expect(screen.getByLabelText('Market data API key')).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ broker: 'fivepaisaxts', clear_market_keys: true })
  })

  it('asks before removing keys, and only then calls the server', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Remove Fyers keys' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Remove the Fyers keys?')).toBeInTheDocument()
    expect(writes()).toHaveLength(0)

    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ method: 'delete', url: '/api/broker/keys/fyers' })
    expect(writes()[0].csrf).toBe('csrf-9')
    await waitFor(() => expect(showToast.success).toHaveBeenCalledWith('Removed the keys.'))
    expect(listReads()).toHaveLength(2)
  })

  it('removes nothing when the confirmation is cancelled', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Remove Fyers keys' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes()).toHaveLength(0)
  })

  it('copies the .env keys into OpenAlgo', async () => {
    renderPage()
    seedLoginList()

    await userEvent.click(await screen.findByRole('button', { name: /Copy to OpenAlgo/i }))

    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ method: 'post', url: '/api/broker/keys/import-env' })
    await waitFor(() =>
      expect(showToast.success).toHaveBeenCalledWith('Copied the Zerodha keys from .env.')
    )
    expect(listReads()).toHaveLength(2)
    expect(client.getQueryState(brokerQueryKeys.config())?.isInvalidated).toBe(true)
  })

  it('re-reads the keys and marks the broker login list stale after a save', async () => {
    renderPage()
    seedLoginList()

    await userEvent.click(await screen.findByRole('button', { name: 'Edit Zerodha keys' }))
    await userEvent.type(screen.getByLabelText('API secret'), 'another-secret')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(listReads()).toHaveLength(2))
    expect(client.getQueryState(brokerQueryKeys.config())?.isInvalidated).toBe(true)
  })

  it('keeps no submitted secret in the query client once a save settles', async () => {
    renderPage()

    await screen.findByText('Add a broker')
    await userEvent.type(screen.getByLabelText('API key'), 'client9:::key9')
    await userEvent.type(screen.getByLabelText('API secret'), 'cache-probe-secret')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    await waitFor(() => expect(showToast.success).toHaveBeenCalled())
    await waitFor(() => expect(cacheText()).not.toContain('cache-probe-secret'))
    expect(cacheText()).not.toContain('client9:::key9')
  })

  it('holds the form while a save is on its way', async () => {
    let finish: (answer: Answer) => void = () => {}
    respond = (call) =>
      call.method === 'post'
        ? new Promise<Answer>((resolve) => {
            finish = resolve
          })
        : defaultRespond(call)
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Edit Zerodha keys' }))
    await userEvent.type(screen.getByLabelText('API secret'), 'slow-secret')
    await userEvent.click(screen.getByRole('button', { name: /Save keys/i }))

    const saving = await screen.findByRole('button', { name: /Saving/i })
    expect(saving).toBeDisabled()
    expect(screen.getByLabelText('API secret')).toBeDisabled()

    finish([200, { status: 'success', message: 'Saved the keys.' }])
    expect(await screen.findByRole('button', { name: /Save keys/i })).toBeEnabled()
  })

  it('leads back to the broker login before a broker is logged in', async () => {
    renderPage()

    expect(await screen.findByRole('link', { name: /Back to broker login/i })).toHaveAttribute(
      'href',
      '/broker'
    )
  })

  it('leads back to the dashboard once a broker is logged in', async () => {
    useAuthStore.setState({
      user: { username: 'trader', broker: 'angel', isLoggedIn: true, loginTime: null },
      isAuthenticated: true,
    })
    renderPage()

    expect(await screen.findByRole('link', { name: /Back to dashboard/i })).toHaveAttribute(
      'href',
      '/dashboard'
    )
  })
})
