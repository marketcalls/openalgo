import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { BrokerAuthSignOut } from './BrokerAuthSignOut'

const navigate = vi.fn()
const logout = vi.fn()
const apiLogout = vi.fn()

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('@/api/auth', () => ({
  authApi: { logout: () => apiLogout() },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ logout }),
}))

vi.mock('@/utils/toast', () => ({
  showToast: { success: vi.fn(), error: vi.fn() },
}))

// jsdom forbids assigning window.location, so swap in a writable stand-in.
const realLocation = window.location
beforeEach(() => {
  Object.defineProperty(window, 'location', {
    value: { href: '' },
    writable: true,
    configurable: true,
  })
})
afterAll(() => {
  Object.defineProperty(window, 'location', { value: realLocation, configurable: true })
})

function renderSignOut() {
  return render(
    <MemoryRouter>
      <BrokerAuthSignOut />
    </MemoryRouter>
  )
}

async function clickSignOut() {
  await userEvent.click(screen.getByRole('button', { name: /sign out/i }))
}

async function confirmLogout() {
  await userEvent.click(screen.getByRole('button', { name: /Yes, Logout/i }))
}

describe('BrokerAuthSignOut', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiLogout.mockResolvedValue(undefined)
  })

  it('always confirms first, because logout can tear down every device', async () => {
    // OpenAlgo allows concurrent devices on one broker feed, and the
    // broker-token-expired reconnect session (issue #1400) reaches this page
    // still carrying logged_in. For that session logout() revokes the broker
    // token, clears sessions on EVERY device and broadcasts force_logout, so an
    // unconfirmed click must never reach the server.
    renderSignOut()

    await clickSignOut()

    expect(await screen.findByText(/Confirm Logout/i)).toBeInTheDocument()
    expect(apiLogout).not.toHaveBeenCalled()
  })

  it('warns with the same wording the dashboard logout uses', async () => {
    renderSignOut()

    await clickSignOut()

    expect(
      await screen.findByText(/All devices connected to this account will be logged out/i)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/All automated orders and running strategies will stop working/i)
    ).toBeInTheDocument()
  })

  it('gives the broker-auth step a way out of the half-logged-in state', async () => {
    renderSignOut()

    await clickSignOut()
    await confirmLogout()

    await waitFor(() => {
      expect(apiLogout).toHaveBeenCalledTimes(1)
      expect(logout).toHaveBeenCalledTimes(1)
      expect(navigate).toHaveBeenCalledWith('/login')
    })
  })

  it('falls back to a real server logout when the XHR call fails', async () => {
    // The XHR can fail with the session still alive (fetchCSRFToken throws ->
    // client.ts posts without a token -> Flask-WTF rejects). Routing to /login
    // would then claim a sign-out that never happened, so the fallback must be
    // a top-level GET /auth/logout that actually clears the server session.
    apiLogout.mockRejectedValue(new Error('csrf rejected'))
    renderSignOut()

    await clickSignOut()
    await confirmLogout()

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1)
      expect(window.location.href).toBe('/auth/logout')
    })
    // Must not pretend the sign-out succeeded via a client-side route change.
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does nothing if the user cancels the dialog', async () => {
    renderSignOut()

    await clickSignOut()
    await userEvent.click(screen.getByRole('button', { name: /^Cancel$/i }))

    expect(apiLogout).not.toHaveBeenCalled()
    expect(logout).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()
  })
})
