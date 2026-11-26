import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrokerList } from '@/api/broker-config'
import { brokerEntry, brokerList, saved } from '@/test/brokerList'
import ProfilePage from './Profile'

/**
 * The Broker tab, as OpenAlgo Desktop has it: a summary of the brokers with
 * links to Select Broker and Broker Configuration, where keys are edited. The
 * web's own server settings (ngrok, Host Server, WebSocket URL) stay here.
 */

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api/client', () => ({
  webClient: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
  fetchCSRFToken: async () => 'csrf-123',
}))

const SERVER_SETTINGS = {
  broker_api_key: '',
  broker_api_secret: '',
  redirect_url: '',
  current_broker: '',
  valid_brokers: ['angel', 'zerodha'],
  ngrok_allow: false,
  host_server: 'http://127.0.0.1:5000',
  websocket_url: 'ws://127.0.0.1:8765',
  server_status: {
    flask: { host: '127.0.0.1', port: '5000' },
    websocket: { host: '127.0.0.1', port: '8765' },
    zmq: { host: '127.0.0.1', port: '5555' },
  },
}

function serve(list: BrokerList) {
  get.mockImplementation(async (url: string) => {
    if (url === '/auth/profile-data') {
      return {
        data: {
          status: 'success',
          data: { username: 'trader', smtp_settings: null, qr_code: null, totp_secret: null },
        },
      }
    }
    if (url === '/api/broker/credentials') {
      return { data: { status: 'success', data: SERVER_SETTINGS } }
    }
    return { data: { status: 'error' } }
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/broker/list'
        ? new Response(JSON.stringify({ status: 'success', data: list }))
        : new Response('{}', { status: 404 })
    )
  )
}

function renderBrokerTab() {
  window.history.pushState({}, '', '/profile?tab=broker')
  return render(
    <MemoryRouter initialEntries={['/profile?tab=broker']}>
      <ProfilePage />
    </MemoryRouter>
  )
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('Profile broker summary', () => {
  it('shows the logged-in broker and the configured ones, with links to both pages', async () => {
    serve(
      brokerList([
        { ...saved(brokerEntry('zerodha', 'Zerodha', 'redirect'), {}), active: true },
        saved(brokerEntry('fyers', 'Fyers', 'redirect'), {}),
        brokerEntry('angel', 'Angel One', 'form'),
      ])
    )
    renderBrokerTab()
    await waitFor(() => expect(screen.getByTestId('broker-logged-in')).toHaveTextContent('Zerodha'))
    await waitFor(() =>
      expect(screen.getByTestId('broker-configured')).toHaveTextContent('FyersZerodha')
    )
    expect(screen.getByRole('link', { name: 'Select Broker' })).toHaveAttribute('href', '/broker')
    expect(screen.getByRole('link', { name: 'Broker Configuration' })).toHaveAttribute(
      'href',
      '/broker/config'
    )
    // No key form here any more.
    expect(screen.queryByRole('button', { name: /save broker credentials/i })).toBeNull()
    expect(screen.queryByPlaceholderText(/enter new api key/i)).toBeNull()
  })

  it('says when no broker is logged in and none is configured', async () => {
    serve(brokerList([brokerEntry('fyers', 'Fyers', 'redirect')]))
    renderBrokerTab()
    await waitFor(() =>
      expect(screen.getByTestId('broker-logged-in')).toHaveTextContent('No broker logged in')
    )
    expect(screen.getByTestId('broker-configured')).toHaveTextContent('None yet')
  })

  it('says changes apply when they are saved on the Broker Configuration page', async () => {
    serve(brokerList([]))
    renderBrokerTab()
    expect(await screen.findByText(/changes apply as soon as you save/i)).toBeInTheDocument()
    expect(screen.queryByText(/require an application restart/i)).toBeNull()
  })
})

describe('Profile server settings', () => {
  it('saves the server settings only, and asks for the restart they need', async () => {
    serve(brokerList([]))
    post.mockResolvedValue({
      data: { status: 'success', message: 'Saved', restart_required: true },
    })
    renderBrokerTab()
    const ws = await screen.findByPlaceholderText('ws://127.0.0.1:8765')
    await userEvent.clear(ws)
    await userEvent.click(ws)
    await userEvent.paste('ws://127.0.0.1:8766')
    await userEvent.click(screen.getByRole('button', { name: /save ngrok settings/i }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [url, payload] = post.mock.calls[0]
    expect(url).toBe('/api/broker/credentials')
    // Server settings only: no broker key ever leaves this page.
    for (const key of Object.keys(payload as object)) {
      expect(['ngrok_allow', 'host_server', 'websocket_url']).toContain(key)
    }
    expect(payload).toMatchObject({ websocket_url: 'ws://127.0.0.1:8766' })
    expect(await screen.findByText('Restart Required')).toBeInTheDocument()
  })
})
