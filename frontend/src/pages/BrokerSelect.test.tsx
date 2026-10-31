import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { brokerQueryKeys } from '@/api/brokerKeys'
import BrokerSelect from './BrokerSelect'

/**
 * The broker login page lists the brokers the server says are configured and
 * asks the server to start the login. It never sees a broker API key and
 * never builds a broker's sign-in address itself.
 */

interface FetchCall {
  url: string
  init?: RequestInit
}

const CONFIG = {
  status: 'success',
  broker_name: 'zerodha',
  broker_api_key: null,
  redirect_url: 'http://127.0.0.1:5000/zerodha/callback',
  brokers: [
    { broker: 'zerodha', name: 'Zerodha', source: 'env' },
    { broker: 'angel', name: 'Angel One', source: 'saved' },
  ],
  live_broker: null,
}

let calls: FetchCall[] = []
let client: QueryClient
let respond: (url: string, init?: RequestInit) => { status: number; body: unknown }

function reply(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function serve(overrides: {
  config?: { status: number; body: unknown }
  login?: { status: number; body: unknown }
}) {
  respond = (url) => {
    if (url === '/auth/csrf-token') return { status: 200, body: { csrf_token: 'csrf-123' } }
    if (url === '/auth/broker-config') return overrides.config ?? { status: 200, body: CONFIG }
    if (url === '/auth/broker/login') {
      return (
        overrides.login ?? {
          status: 200,
          body: { status: 'success', url: 'https://kite.trade/connect/login?api_key=x' },
        }
      )
    }
    return { status: 404, body: {} }
  }
}

// jsdom forbids assigning window.location, so swap in a writable stand-in.
const realLocation = window.location
beforeEach(() => {
  calls = []
  serve({})
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      const { status, body } = respond(url, init)
      return reply(status, body)
    })
  )
  Object.defineProperty(window, 'location', {
    value: { href: '' },
    writable: true,
    configurable: true,
  })
})
afterEach(() => {
  vi.unstubAllGlobals()
})
afterAll(() => {
  Object.defineProperty(window, 'location', { value: realLocation, configurable: true })
})

function renderPage(path = '/broker') {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/broker" element={<BrokerSelect />} />
          <Route path="/login" element={<div>Login page</div>} />
          <Route path="/broker/keys" element={<div>Broker keys page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function configReads() {
  return calls.filter((c) => c.url === '/auth/broker-config')
}

async function connectButton() {
  return screen.findByRole('button', { name: /Connect Account/i })
}

describe('BrokerSelect', () => {
  it('lists every configured broker and marks the one set in .env', async () => {
    renderPage()

    const trigger = await screen.findByRole('combobox')
    // The preselected broker is the server's broker_name.
    expect(trigger).toHaveTextContent('Zerodha (from .env)')

    await userEvent.click(trigger)
    expect(await screen.findByRole('option', { name: 'Zerodha (from .env)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Angel One' })).toBeInTheDocument()
  })

  it('asks the server to start the login and goes where it says', async () => {
    renderPage()

    await userEvent.click(await connectButton())

    await waitFor(() => {
      expect(window.location.href).toBe('https://kite.trade/connect/login?api_key=x')
    })
    const login = calls.find((c) => c.url === '/auth/broker/login')
    expect(login?.init?.method).toBe('POST')
    expect(JSON.parse(String(login?.init?.body))).toEqual({ broker: 'zerodha' })
    expect((login?.init?.headers as Record<string, string>)['X-CSRFToken']).toBe('csrf-123')
    // Still held while the browser leaves for the broker: no second click.
    expect(screen.getByRole('button', { name: /Connecting/i })).toBeDisabled()
  })

  it('shows the server sentence when the login is refused', async () => {
    const refusal =
      'OpenAlgo is logged in to Angel One. Log out first, then log in to another broker.'
    serve({ login: { status: 409, body: { status: 'error', message: refusal } } })
    renderPage()

    await userEvent.click(await connectButton())

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(window.location.href).toBe('')
  })

  it('turns a known callback error code into its fixed sentence', async () => {
    renderPage('/broker?error=login_not_started')

    expect(
      await screen.findByText(
        'This broker login was not started from OpenAlgo, or it took longer than 10 minutes. Start the broker login again.'
      )
    ).toBeInTheDocument()
  })

  it('never puts the query text on the page', async () => {
    const planted = 'Your account is blocked. Call 1800 000 000 to restore it'
    renderPage(`/broker?error=${encodeURIComponent(planted)}`)

    expect(
      await screen.findByText('The broker login did not complete. Try again.')
    ).toBeInTheDocument()
    expect(screen.queryByText(/account is blocked/i)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('1800 000 000')
  })

  it('sends a trader with no broker set up to add keys', async () => {
    serve({ config: { status: 200, body: { ...CONFIG, broker_name: null, brokers: [] } } })
    renderPage()

    const link = await screen.findByRole('link', { name: /Add broker keys/i })
    expect(link).toHaveAttribute('href', '/broker/keys')
    expect(screen.getByText('No broker is set up yet')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Connect Account/i })).not.toBeInTheDocument()
  })

  it('links to the broker keys page below the form', async () => {
    renderPage()

    const link = await screen.findByRole('link', { name: 'Manage broker keys' })
    expect(link).toHaveAttribute('href', '/broker/keys')
  })

  it('says another device holds a different broker', async () => {
    serve({ config: { status: 200, body: { ...CONFIG, live_broker: 'angel' } } })
    renderPage()

    expect(
      await screen.findByText(/OpenAlgo is logged in to Angel One on another device/)
    ).toBeInTheDocument()
  })

  it('ends the other device session only after the trader confirms', async () => {
    let live: string | null = 'angel'
    respond = (url) => {
      if (url === '/auth/csrf-token') return { status: 200, body: { csrf_token: 'csrf-123' } }
      if (url === '/auth/broker-config') {
        return { status: 200, body: { ...CONFIG, live_broker: live } }
      }
      if (url === '/auth/broker/end-session') {
        live = null
        return {
          status: 200,
          body: {
            status: 'success',
            message: 'Logged out of Angel One. Choose a broker to log in.',
          },
        }
      }
      return { status: 404, body: {} }
    }
    renderPage()
    // The keys page's cached badges must go stale too once the session ends.
    client.setQueryData(brokerQueryKeys.keys(), { brokers: [], live_broker: 'angel' })

    await userEvent.click(await screen.findByRole('button', { name: 'End the Angel One session' }))
    // The first click only asks; nothing is sent until the trader confirms.
    expect(calls.some((c) => c.url === '/auth/broker/end-session')).toBe(false)
    await userEvent.click(await screen.findByRole('button', { name: 'End the session' }))

    expect(
      await screen.findByText('Logged out of Angel One. Choose a broker to log in.')
    ).toBeInTheDocument()
    const ended = calls.find((c) => c.url === '/auth/broker/end-session')
    expect(ended?.init?.method).toBe('POST')
    expect((ended?.init?.headers as Record<string, string>)['X-CSRFToken']).toBe('csrf-123')
    await waitFor(() => {
      expect(screen.queryByText(/on another device/)).not.toBeInTheDocument()
    })
    // The list was read again, not patched by hand.
    expect(configReads()).toHaveLength(2)
    expect(client.getQueryState(brokerQueryKeys.keys())?.isInvalidated).toBe(true)
  })

  it('sends a visitor who is not signed in to the login page', async () => {
    serve({ config: { status: 401, body: { status: 'error', message: 'Sign in first.' } } })
    renderPage()

    expect(await screen.findByText('Login page')).toBeInTheDocument()
    // A 401 answers the same the second time; it is not retried.
    expect(configReads()).toHaveLength(1)
  })

  it('retries a failed broker list once, then says it could not load', async () => {
    serve({ config: { status: 500, body: { status: 'error' } } })
    renderPage()

    expect(
      await screen.findByText(
        'The broker list could not be loaded. Reload the page to try again.',
        undefined,
        { timeout: 4000 }
      )
    ).toBeInTheDocument()
    expect(configReads()).toHaveLength(2)
  })
})
