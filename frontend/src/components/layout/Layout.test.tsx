import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import { Layout } from './Layout'

// The chrome around the page is not what these tests are about.
vi.mock('@/components/socket/SocketProvider', () => ({
  SocketProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
vi.mock('./Navbar', () => ({ Navbar: () => null }))
vi.mock('./Footer', () => ({ Footer: () => null }))
vi.mock('./MobileBottomNav', () => ({ MobileBottomNav: () => null }))

function signIn(broker: string | null) {
  useAuthStore.setState({
    user: { username: 'trader', broker, isLoggedIn: broker !== null, loginTime: null },
    isAuthenticated: broker !== null,
  })
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/profile" element={<div>Profile page</div>} />
          <Route path="/dashboard" element={<div>Dashboard page</div>} />
        </Route>
        <Route path="/broker" element={<div>Broker login page</div>} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

afterEach(() => {
  useAuthStore.setState({ user: null, isAuthenticated: false })
})

describe('Layout', () => {
  it('opens Profile for a trader not yet logged in to a broker, to add the keys', () => {
    signIn(null)
    renderAt('/profile')

    expect(screen.getByText('Profile page')).toBeInTheDocument()
  })

  it('keeps a trader with no broker out of every other page', () => {
    // As in OpenAlgo Desktop: the login page sends a signed-in trader on to
    // the broker login.
    signIn(null)
    renderAt('/dashboard')

    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument()
    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('sends a visitor who is not signed in to the login page, Profile included', () => {
    renderAt('/profile')

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('opens every page once a broker is logged in', () => {
    signIn('zerodha')
    renderAt('/dashboard')

    expect(screen.getByText('Dashboard page')).toBeInTheDocument()
  })
})
