import { Navigate, Outlet, useLocation } from 'react-router'
import { SocketProvider } from '@/components/socket/SocketProvider'
import { isPreBrokerPath } from '@/lib/brokerProfiles'
import { useAuthStore } from '@/stores/authStore'
import { Footer } from './Footer'
import { MobileBottomNav } from './MobileBottomNav'
import { Navbar } from './Navbar'

export function Layout() {
  const { isAuthenticated, user } = useAuthStore()
  const { pathname } = useLocation()

  // AuthSync has already synced Flask session with Zustand store
  // So we just need to check the Zustand store state
  // A trader signed in with their password but not yet connected to a broker
  // (isAuthenticated is only true once a broker is connected) can open
  // Profile, to add the broker keys.
  const preBroker = Boolean(user?.username) && isPreBrokerPath(pathname)

  if (!isAuthenticated && !preBroker) {
    return <Navigate to="/login" replace />
  }

  // If logged in but no broker selected, redirect to broker selection.
  if (!user?.broker && !preBroker) {
    return <Navigate to="/broker" replace />
  }

  return (
    <SocketProvider>
      <div className="min-h-screen bg-background flex flex-col">
        <Navbar />
        <main className="container mx-auto px-4 py-6 pb-24 md:pb-6 flex-1">
          <Outlet />
        </main>
        <Footer className="hidden md:block" />
        <MobileBottomNav />
      </div>
    </SocketProvider>
  )
}

export function PublicLayout() {
  return (
    <div className="min-h-screen bg-background">
      <Outlet />
    </div>
  )
}
