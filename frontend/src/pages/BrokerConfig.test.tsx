import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrokerKeyField, BrokerList } from '@/api/broker-config'
import { brokerEntry, brokerList, saved } from '@/test/brokerList'
import { renderWithQuery } from '@/test/queryRender'
import { fireEvent, screen, waitFor } from '@/test/test-utils'
import BrokerConfig from './BrokerConfig'

// Broker Configuration, as in OpenAlgo Desktop. One key set per broker;
// saved values are shown masked, with separate replacement inputs where a
// blank one keeps what is saved.

interface Call {
  url: string
  method: string
  body: unknown
}

let calls: Call[] = []
let list: BrokerList

const MARKET: BrokerKeyField[] = [
  {
    key: 'api_key_market',
    label: 'Market Data App Key',
    hint: 'Quotes and the live feed need it.',
    secret: false,
    required: false,
    saved: null,
  },
  {
    key: 'api_secret_market',
    label: 'Market Data Secret Key',
    hint: 'From the same XTS account.',
    secret: true,
    required: false,
    saved: null,
  },
]

function serve(answer: Record<string, unknown> = { status: 'success', message: 'Saved.' }) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
      if (url === '/api/broker/list') return json({ status: 'success', data: list })
      if (url === '/auth/csrf-token') return json({ csrf_token: 'tok' })
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      return json(answer)
    })
  )
}

function renderPage(broker?: string) {
  window.history.pushState({}, '', broker ? `/broker/config?broker=${broker}` : '/broker/config')
  return renderWithQuery(<BrokerConfig />)
}

const select = () => screen.findByRole('combobox', { name: 'Broker' })

beforeEach(() => {
  calls = []
  list = brokerList([
    brokerEntry('zerodha', 'Zerodha', 'redirect'),
    brokerEntry('angel', 'Angel One', 'form', {
      fields: [
        {
          key: 'api_key',
          label: 'SmartAPI Key',
          hint: 'The API key of your SmartAPI app.',
          secret: false,
          required: true,
          saved: null,
        },
      ],
    }),
    brokerEntry('fivepaisaxts', '5 Paisa (XTS)', 'saved_keys', {
      fields: [...brokerEntry('x', 'x', 'saved_keys').fields, ...MARKET],
    }),
    saved(brokerEntry('fyers', 'Fyers', 'redirect'), { api_key: 'APP***100', api_secret: '***' }),
  ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('Broker Configuration', () => {
  it('lists every broker and marks the configured and the active one', async () => {
    list = brokerList([
      brokerEntry('zerodha', 'Zerodha', 'redirect'),
      saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}),
      { ...saved(brokerEntry('angel', 'Angel One', 'form'), {}), active: true },
    ])
    serve()
    renderPage()
    const options = [...(await select()).querySelectorAll('option')].map((o) => o.textContent)
    expect(options).toEqual([
      'Select a broker...',
      'Angel One (Active)',
      'Fyers (Configured)',
      'Zerodha',
    ])
  })

  it('asks a redirect broker for its keys and redirect URL, prefilled with the automatic one', async () => {
    serve()
    renderPage('zerodha')
    expect(await screen.findByTestId('broker-banner')).toHaveTextContent(
      "Login with Zerodha takes you to Zerodha's login page"
    )
    expect(screen.getByLabelText('API Key')).toBeInTheDocument()
    expect(screen.getByLabelText('API Secret')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Redirect URL')).toHaveValue(
      'http://127.0.0.1:5000/zerodha/callback'
    )
    expect(screen.queryByLabelText('Market Data App Key')).toBeNull()
  })

  it("shows only a form broker's own keys, labelled its way, and no redirect URL", async () => {
    serve()
    renderPage('angel')
    expect(await screen.findByLabelText('SmartAPI Key')).toBeInTheDocument()
    expect(screen.queryByLabelText('API Secret')).toBeNull()
    expect(screen.queryByLabelText('Redirect URL')).toBeNull()
    expect(screen.getByTestId('broker-banner')).toHaveTextContent('opens a short form')
  })

  it('asks an XTS broker for its market data keys too', async () => {
    serve()
    renderPage('fivepaisaxts')
    expect(await screen.findByLabelText(/Market Data App Key/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Market Data Secret Key/)).toHaveAttribute('type', 'password')
    expect(screen.getByTestId('broker-banner')).toHaveTextContent('one click')
  })

  it('shows what is saved masked, with empty replacement inputs', async () => {
    serve()
    renderPage('fyers')
    expect(await screen.findByTestId('saved-api_key')).toHaveTextContent('Saved: APP***100')
    const key = screen.getByLabelText('API Key')
    expect(key).toHaveValue('')
    expect(key).toHaveAttribute('placeholder', 'Leave blank to keep the saved value.')
    expect(screen.getByLabelText('API Secret')).toHaveValue('')
  })

  it('saves only what was typed: a blank key keeps the saved value', async () => {
    serve({ status: 'success', message: 'Saved your Fyers settings.' })
    renderPage('fyers')
    fireEvent.change(await screen.findByLabelText('API Secret'), { target: { value: 'newsecret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Saved your Fyers settings.')).toBeInTheDocument()
    expect(calls).toEqual([
      {
        url: '/api/broker/credentials/fyers',
        method: 'PUT',
        body: { api_secret: 'newsecret' },
      },
    ])
  })

  it("needs every required key on a broker's first save", async () => {
    serve()
    renderPage('zerodha')
    fireEvent.change(await screen.findByLabelText('API Key'), { target: { value: 'k1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Enter the API Secret to save Zerodha.')).toBeInTheDocument()
    expect(calls).toEqual([])
  })

  it('clears what was typed when the broker changes', async () => {
    serve()
    renderPage('fyers')
    fireEvent.change(await screen.findByLabelText('API Key'), {
      target: { value: 'typed-for-fyers' },
    })
    fireEvent.change(await select(), { target: { value: 'zerodha' } })
    await waitFor(() =>
      expect(screen.getByTestId('broker-banner')).toHaveTextContent('Login with Zerodha')
    )
    expect(screen.getByLabelText('API Key')).toHaveValue('')
    fireEvent.change(await select(), { target: { value: 'fyers' } })
    await waitFor(() =>
      expect(screen.getByTestId('broker-banner')).toHaveTextContent('Login with Fyers')
    )
    expect(screen.getByLabelText('API Key')).toHaveValue('')
  })

  it('goes back to the automatic redirect URL by sending it empty', async () => {
    list = brokerList([
      {
        ...saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}),
        redirect_url: 'https://abc.ngrok.app/zerodha/callback',
        redirect_url_is_default: false,
      },
    ])
    serve()
    renderPage('zerodha')
    expect(await screen.findByLabelText('Redirect URL')).toHaveValue(
      'https://abc.ngrok.app/zerodha/callback'
    )
    fireEvent.click(screen.getByRole('button', { name: /use automatic/i }))
    expect(screen.getByLabelText('Redirect URL')).toHaveValue(
      'http://127.0.0.1:5000/zerodha/callback'
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls).toEqual([
        { url: '/api/broker/credentials/zerodha', method: 'PUT', body: { redirect_url: '' } },
      ])
    )
  })

  it('forgets a broker after confirming', async () => {
    serve({ status: 'success', message: 'Forgot your Fyers keys.' })
    renderPage('fyers')
    fireEvent.click(await screen.findByRole('button', { name: 'Forget this broker' }))
    expect(await screen.findByText('Forget Fyers?')).toBeInTheDocument()
    expect(screen.queryByText(/signs you out of Fyers/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
    expect(await screen.findByText('Forgot your Fyers keys.')).toBeInTheDocument()
    expect(calls).toEqual([
      { url: '/api/broker/credentials/fyers', method: 'DELETE', body: undefined },
    ])
  })

  it('confirms that forgetting the logged-in broker signs out of it', async () => {
    list = brokerList([{ ...saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}), active: true }])
    serve({ status: 'success', message: 'Signed out of Fyers and forgot its keys.' })
    renderPage('fyers')
    fireEvent.click(await screen.findByRole('button', { name: 'Forget this broker' }))
    expect(
      await screen.findByText(/Forgetting it signs you out of Fyers first/)
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByText('Forget Fyers?')).toBeNull())
    expect(calls).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Forget this broker' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out and forget' }))
    await waitFor(() =>
      expect(calls).toEqual([
        {
          url: '/api/broker/credentials/fyers?sign_out=true',
          method: 'DELETE',
          body: undefined,
        },
      ])
    )
  })

  // FLOW-04: a session belongs to the keys it signed in with.
  it("confirms that new keys end the logged-in broker's session, then saves", async () => {
    list = brokerList([{ ...saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}), active: true }])
    serve({
      status: 'success',
      message: 'Saved your Fyers keys and ended its session.',
      signed_out: true,
    })
    renderPage('fyers')
    fireEvent.change(await screen.findByLabelText('API Secret'), { target: { value: 'rotated' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(
      await screen.findByText(
        /Saving new keys for Fyers ends your Fyers session. Open positions and orders stay with Fyers./
      )
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByText('End your Fyers session?')).toBeNull())
    expect(calls).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    fireEvent.click(await screen.findByRole('button', { name: 'End session and save' }))
    await waitFor(() =>
      expect(calls).toEqual([
        {
          url: '/api/broker/credentials/fyers?sign_out=true',
          method: 'PUT',
          body: { api_secret: 'rotated' },
        },
      ])
    )
    expect(await screen.findByText(/ended its session/)).toBeInTheDocument()
  })

  it("saves a logged-in broker's redirect URL without ending its session", async () => {
    list = brokerList([{ ...saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}), active: true }])
    serve()
    renderPage('fyers')
    fireEvent.change(await screen.findByLabelText('Redirect URL'), {
      target: { value: 'https://abc.ngrok.app/fyers/callback' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(calls).toEqual([
        {
          url: '/api/broker/credentials/fyers',
          method: 'PUT',
          body: { redirect_url: 'https://abc.ngrok.app/fyers/callback' },
        },
      ])
    )
    expect(screen.queryByText('End your Fyers session?')).toBeNull()
  })

  it('says the automatic redirect URL is the Host Server URL', async () => {
    serve()
    renderPage('zerodha')
    expect(await screen.findByText(/Automatic: your Host Server URL\./)).toBeInTheDocument()
  })

  it('says forgetting removes the keys from OpenAlgo', async () => {
    serve()
    renderPage('fyers')
    fireEvent.click(await screen.findByRole('button', { name: 'Forget this broker' }))
    expect(
      await screen.findByText(/This removes the saved Fyers keys from OpenAlgo\./)
    ).toBeInTheDocument()
  })

  it('offers no API plan (the plan selector comes in a later change)', async () => {
    serve()
    renderPage('fyers')
    expect(await screen.findByLabelText('API Key')).toBeInTheDocument()
    expect(screen.queryByLabelText('API plan')).toBeNull()
  })
})
