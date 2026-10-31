import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BrokerSelect from './BrokerSelect'

/**
 * The broker login page, as OpenAlgo Desktop has it: one dropdown of every
 * configured broker, the active one preselected, picking another makes it
 * active, and the server starts the login. The page never sees a broker key
 * and never builds a broker's sign-in address itself.
 */

interface FetchCall {
  url: string
  init?: RequestInit
}

type Answer = { status: number; body: unknown }

const CONFIG = {
  status: 'success',
  broker_name: 'zerodha',
  broker_api_key: null,
  redirect_url: 'http://127.0.0.1:5000/zerodha/callback',
}

const CONFIGURED = {
  status: 'success',
  data: {
    brokers: [
      { name: 'zerodha', active: true },
      { name: 'angel', active: false },
    ],
    active: 'zerodha',
  },
}

const NOT_CONFIGURED = {
  status: 'error',
  code: 'BROKER_NOT_CONFIGURED',
  message: 'Choose your broker and add its API key in Profile, Broker Configuration.',
}

let calls: FetchCall[] = []
let respond: (url: string, init?: RequestInit) => Answer

function reply(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function serve(overrides: {
  config?: Answer
  configured?: Answer
  login?: Answer
  credentials?: Answer
}) {
  respond = (url) => {
    if (url === '/auth/csrf-token') return { status: 200, body: { csrf_token: 'csrf-123' } }
    if (url === '/auth/broker-config') return overrides.config ?? { status: 200, body: CONFIG }
    if (url === '/api/broker/configured') {
      return overrides.configured ?? { status: 200, body: CONFIGURED }
    }
    if (url === '/api/broker/credentials') {
      return overrides.credentials ?? { status: 200, body: { status: 'success', message: 'ok' } }
    }
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
    value: { href: '', origin: 'http://127.0.0.1:5000', search: '' },
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
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/broker" element={<BrokerSelect />} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

function callsTo(url: string) {
  return calls.filter((c) => c.url === url)
}

describe('BrokerSelect', () => {
  it('lists every configured broker, the active one preselected', async () => {
    renderPage()

    const trigger = await screen.findByRole('combobox')
    expect(trigger).toHaveTextContent('Zerodha')

    await userEvent.click(trigger)
    expect(await screen.findByRole('option', { name: 'Zerodha' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Angel One' })).toBeInTheDocument()
    // Only configured brokers, not the whole catalogue.
    expect(screen.queryByRole('option', { name: 'Fyers' })).not.toBeInTheDocument()
  })

  it('makes a picked broker the active one, then reads the list again', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('combobox'))
    await userEvent.click(await screen.findByRole('option', { name: 'Angel One' }))

    await waitFor(() => expect(callsTo('/auth/broker-config')).toHaveLength(2))
    const [save] = callsTo('/api/broker/credentials')
    expect(save.init?.method).toBe('POST')
    expect((save.init?.headers as Record<string, string>)['X-CSRFToken']).toBe('csrf-123')
    expect((save.init?.body as FormData).get('redirect_url')).toBe(
      'http://127.0.0.1:5000/angel/callback'
    )
    expect(callsTo('/api/broker/configured')).toHaveLength(2)
  })

  it('shows the server sentence when the switch is refused', async () => {
    const refusal = 'A login to Zerodha is under way. Wait for it to finish, then try again.'
    serve({ credentials: { status: 409, body: { status: 'error', message: refusal } } })
    renderPage()

    await userEvent.click(await screen.findByRole('combobox'))
    await userEvent.click(await screen.findByRole('option', { name: 'Angel One' }))

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(callsTo('/auth/broker-config')).toHaveLength(1)
  })

  it('asks the server to start the login and goes where it says', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /Connect Account/i }))

    await waitFor(() => {
      expect(window.location.href).toBe('https://kite.trade/connect/login?api_key=x')
    })
    const [login] = callsTo('/auth/broker/login')
    expect(login.init?.method).toBe('POST')
    expect(JSON.parse(String(login.init?.body))).toEqual({ broker: 'zerodha' })
    expect((login.init?.headers as Record<string, string>)['X-CSRFToken']).toBe('csrf-123')
    // Still held while the browser leaves for the broker: no second click.
    expect(screen.getByRole('button', { name: /Connecting/i })).toBeDisabled()
  })

  it('shows the server sentence when the login is refused', async () => {
    const refusal = 'No API key is saved for Zerodha. Add it in Profile > Broker, then try again.'
    serve({ login: { status: 409, body: { status: 'error', message: refusal } } })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /Connect Account/i }))

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(window.location.href).toBe('')
    expect(screen.getByRole('button', { name: /Connect Account/i })).toBeEnabled()
  })

  it('sends a trader with no broker configured to Profile', async () => {
    serve({
      config: { status: 404, body: NOT_CONFIGURED },
      configured: { status: 200, body: { status: 'success', data: { brokers: [], active: null } } },
    })
    renderPage()

    const button = await screen.findByRole('link', { name: 'Configure broker' })
    expect(button).toHaveAttribute('href', '/profile?tab=broker')
    expect(screen.getByText(NOT_CONFIGURED.message)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Configure another broker' })).not.toBeInTheDocument()
  })

  it('links to Profile to configure another broker', async () => {
    renderPage()

    const link = await screen.findByRole('link', { name: 'Configure another broker' })
    expect(link).toHaveAttribute('href', '/profile?tab=broker')
    expect(screen.queryByRole('link', { name: 'Configure broker' })).not.toBeInTheDocument()
  })

  it.each([
    [
      'login_not_started',
      'This broker login was not started from OpenAlgo, or it took longer than 10 minutes. Start the broker login again.',
    ],
    [
      'broker_unavailable',
      'The broker login could not start. Check its keys in Profile > Broker, then try again.',
    ],
    ['form_expired', 'This login form has expired. Reload the page and try again.'],
    ['login_failed', 'The broker login did not complete. Try again.'],
  ])('turns the callback error code %s into its fixed sentence', async (code, sentence) => {
    renderPage(`/broker?error=${code}`)

    expect(await screen.findByText(sentence)).toBeInTheDocument()
  })

  it('never puts the query text on the page', async () => {
    const planted = 'Your account is blocked. Call 1800 000 000 to restore it'
    renderPage(`/broker?error=${encodeURIComponent(planted)}`)

    expect(
      await screen.findByText('The broker login did not complete. Try again.')
    ).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('1800 000 000')
    expect(screen.queryByText(/account is blocked/i)).not.toBeInTheDocument()
  })

  it('sends a visitor who is not signed in to the login page', async () => {
    serve({ config: { status: 401, body: { status: 'error', message: 'Sign in first.' } } })
    renderPage()

    expect(await screen.findByText('Login page')).toBeInTheDocument()
  })
})
