import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@/test/test-utils'
import BrokerTOTP from './BrokerTOTP'

// A TOTP broker login ends on a full navigation to the dashboard, never an
// SPA route change: the auth store's API key is hydrated only by AuthSync's
// /auth/session-status fetch at app mount, and an SPA navigate leaves every
// order ticket's BUY/SELL disabled until the next full page load (#2417).

const realLocation = window.location
let assigned: string[] = []
let posts: string[] = []

function serve(opts: { refuseCallback?: string } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
      if (url === '/auth/csrf-token') return json({ csrf_token: 'tok' })
      if (init?.method === 'POST') {
        posts.push(url)
        if (url === '/kotak/callback') {
          if (opts.refuseCallback)
            return json({ status: 'error', message: opts.refuseCallback }, 401)
          return json({
            status: 'success',
            message: 'Authentication successful',
            redirect: '/dashboard',
          })
        }
      }
      return json({}, 404)
    })
  )
}

function renderPage(broker = 'kotak') {
  return render(
    <MemoryRouter initialEntries={[`/broker/${broker}/totp`]}>
      <Routes>
        <Route path="/broker/:broker/totp" element={<BrokerTOTP />} />
      </Routes>
    </MemoryRouter>
  )
}

function fillKotakForm() {
  fireEvent.change(screen.getByLabelText(/Mobile Number/), { target: { value: '9876543210' } })
  fireEvent.change(screen.getByLabelText(/MPIN/), { target: { value: '123456' } })
  fireEvent.change(screen.getByLabelText(/TOTP Code/), { target: { value: '654321' } })
}

beforeEach(() => {
  assigned = []
  posts = []
  const loc = { ...realLocation, origin: 'http://127.0.0.1:5000', search: '' }
  Object.defineProperty(loc, 'href', {
    get: () => assigned[assigned.length - 1] ?? 'http://127.0.0.1:5000/broker',
    set: (v: string) => assigned.push(v),
  })
  Object.defineProperty(window, 'location', { configurable: true, value: loc })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  vi.unstubAllGlobals()
})

describe('BrokerTOTP', () => {
  it('completes a login with a full navigation to the dashboard, so AuthSync hydrates the API key (#2417)', async () => {
    serve()
    renderPage()

    fillKotakForm()
    fireEvent.click(screen.getByRole('button', { name: 'Authenticate' }))

    await waitFor(() => expect(posts).toContain('/kotak/callback'))
    await waitFor(() => expect(assigned).toContain('/dashboard'))

    // The form stays busy until the navigation unloads the page: resetting
    // isLoading here would re-enable submit in the gap and let a single-use
    // TOTP code be posted twice.
    expect(screen.getByRole('button', { name: /Authenticating/ })).toBeDisabled()

    // ...unless the page is later restored from bfcache (Back from the
    // dashboard): then the busy state must reset or the form is stuck.
    const pageshow = new Event('pageshow')
    Object.defineProperty(pageshow, 'persisted', { value: true })
    fireEvent(window, pageshow)
    expect(screen.getByRole('button', { name: 'Authenticate' })).toBeEnabled()
  })

  it('stays put and shows the error when the callback refuses the login', async () => {
    serve({ refuseCallback: 'Authentication failed. Please try again.' })
    renderPage()

    fillKotakForm()
    fireEvent.click(screen.getByRole('button', { name: 'Authenticate' }))

    await screen.findByText('Authentication failed. Please try again.')
    expect(assigned).toEqual([])

    // A refused login re-enables the form so the code can be retried.
    expect(screen.getByRole('button', { name: 'Authenticate' })).toBeEnabled()
  })
})
