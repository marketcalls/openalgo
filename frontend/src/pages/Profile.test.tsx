import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'
import ProfilePage from './Profile'

/**
 * The Broker tab, as OpenAlgo Desktop has it: the current broker's keys, and a
 * form that saves keys for the chosen broker. Choosing another broker makes it
 * the active one and sends the trader to log in to it.
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

const SAVED_IN_OPENALGO = {
  broker_api_key: 'angel1********',
  broker_api_key_raw_length: 0,
  broker_api_key_set: true,
  broker_api_secret: '********',
  broker_api_secret_raw_length: 0,
  broker_api_secret_set: true,
  broker_api_key_market: '',
  broker_api_key_market_raw_length: 0,
  broker_api_key_market_set: false,
  broker_api_secret_market: '',
  broker_api_secret_market_raw_length: 0,
  broker_api_secret_market_set: false,
  redirect_url: 'http://127.0.0.1:5000/angel/callback',
  current_broker: 'angel',
  valid_brokers: ['angel', 'zerodha'],
  ngrok_allow: false,
  host_server: 'http://127.0.0.1:5000',
  websocket_url: 'ws://127.0.0.1:8765',
}

let credentials: Record<string, unknown>

function serveCredentials() {
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
      return { data: { status: 'success', data: credentials } }
    }
    return { data: { status: 'error' } }
  })
}

function credentialReads() {
  return get.mock.calls.filter(([url]) => url === '/api/broker/credentials').length
}

const assign = vi.fn()
const realLocation = window.location

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  assign.mockReset()
  credentials = { ...SAVED_IN_OPENALGO }
  serveCredentials()
  // The broker page links here with ?tab=broker.
  Object.defineProperty(window, 'location', {
    value: { href: '', origin: 'http://127.0.0.1:5000', search: '?tab=broker', assign },
    writable: true,
    configurable: true,
  })
})
afterAll(() => {
  Object.defineProperty(window, 'location', { value: realLocation, configurable: true })
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/profile?tab=broker']}>
      <ProfilePage />
    </MemoryRouter>
  )
}

describe('Profile broker tab', () => {
  it('opens on the tab the broker page links to', async () => {
    renderPage()

    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
  })

  it('says a key saved in OpenAlgo is set, without a length', async () => {
    renderPage()

    expect(await screen.findAllByText('Currently set')).toHaveLength(2)
    expect(screen.queryByText(/chars/)).not.toBeInTheDocument()
  })

  it('shows the length of a key read from .env, and a key that is not set', async () => {
    credentials = {
      ...SAVED_IN_OPENALGO,
      broker_api_key: 'zkey12********',
      broker_api_key_raw_length: 16,
      broker_api_secret: '',
      broker_api_secret_raw_length: 0,
      broker_api_secret_set: false,
      current_broker: 'zerodha',
    }
    renderPage()

    expect(await screen.findByText('Current: 16 chars')).toBeInTheDocument()
    expect(screen.getByText('Not currently set')).toBeInTheDocument()
  })

  it('reads the saved keys again after a save, and needs no restart for them', async () => {
    post.mockResolvedValue({
      data: {
        status: 'success',
        message: 'Saved.',
        restart_required: false,
        broker_switched: false,
      },
    })
    renderPage()

    // One paste, not a keystroke per character: each re-renders the whole page.
    await userEvent.click(await screen.findByPlaceholderText('Enter new API key'))
    await userEvent.paste('new-angel-key')
    await userEvent.click(screen.getByRole('button', { name: /Save Broker Credentials/i }))

    await waitFor(() => expect(credentialReads()).toBe(2))
    const form = post.mock.calls[0][1] as FormData
    expect(post.mock.calls[0][0]).toBe('/api/broker/credentials')
    expect(form.get('broker_api_key')).toBe('new-angel-key')
    expect(form.get('redirect_url')).toBeNull()
    expect(screen.queryByText('Restart Required')).not.toBeInTheDocument()
    expect(assign).not.toHaveBeenCalled()
    // The typed key is cleared and never shown back.
    expect(screen.queryByDisplayValue('new-angel-key')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('new-ang')
  })

  it('asks for a restart when the keys went to .env', async () => {
    post.mockResolvedValue({
      data: { status: 'success', message: 'Saved.', restart_required: true },
    })
    renderPage()

    await userEvent.click(await screen.findByPlaceholderText('Enter new API key'))
    await userEvent.paste('k')
    await userEvent.click(screen.getByRole('button', { name: /Save Broker Credentials/i }))

    expect(await screen.findByText('Restart Required')).toBeInTheDocument()
  })

  it('gives a first broker on a server the address the app is served from', async () => {
    // No broker saved yet: nothing to take the host from.
    credentials = { ...SAVED_IN_OPENALGO, redirect_url: '', current_broker: '' }
    Object.defineProperty(window, 'location', {
      value: { href: '', origin: 'https://algo.example.com', search: '?tab=broker', assign },
      writable: true,
      configurable: true,
    })
    post.mockResolvedValue({
      data: { status: 'success', message: 'Saved.', broker_switched: true },
    })
    renderPage()

    await userEvent.click((await screen.findAllByRole('combobox'))[0])
    await userEvent.click(await screen.findByRole('option', { name: 'Zerodha' }))
    await userEvent.click(screen.getByPlaceholderText('Enter new API key'))
    await userEvent.paste('zkey')
    await userEvent.click(screen.getByRole('button', { name: /Save Broker Credentials/i }))

    await waitFor(() => expect(post).toHaveBeenCalled())
    const form = post.mock.calls[0][1] as FormData
    expect(form.get('redirect_url')).toBe('https://algo.example.com/zerodha/callback')
  })

  it('sends the trader to log in after choosing another broker', async () => {
    post.mockResolvedValue({
      data: { status: 'success', message: 'Saved.', broker_switched: true },
    })
    renderPage()

    await userEvent.click((await screen.findAllByRole('combobox'))[0])
    await userEvent.click(await screen.findByRole('option', { name: 'Zerodha' }))
    await userEvent.click(screen.getByPlaceholderText('Enter new API key'))
    await userEvent.paste('zkey')
    await userEvent.click(screen.getByRole('button', { name: /Save Broker Credentials/i }))

    await waitFor(() => expect(assign).toHaveBeenCalledWith('/broker'))
    const form = post.mock.calls[0][1] as FormData
    expect(form.get('redirect_url')).toBe('http://127.0.0.1:5000/zerodha/callback')
    expect(screen.queryByText('Restart Required')).not.toBeInTheDocument()
  })
})
