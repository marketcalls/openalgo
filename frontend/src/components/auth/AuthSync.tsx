import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useThemeStore } from '@/stores/themeStore'

interface SessionStatus {
  status?: string
  authenticated?: boolean
  logged_in?: boolean
  user?: string
  broker?: string
  api_key?: string
  active_sessions?: number
}

async function fetchSessionStatus(): Promise<SessionStatus | null> {
  const response = await fetch('/auth/session-status', { credentials: 'include' })
  if (!response.ok) return null
  return (await response.json()) as SessionStatus
}

function isBrokerSession(data: SessionStatus): boolean {
  return data.status === 'success' && !!data.logged_in && !!data.broker
}

/**
 * Copies a broker-logged-in session into the stores: user, API key, broker
 * capabilities, app mode and session count. Everything that reads the API key
 * from the auth store (the order tickets, live quotes) depends on this.
 */
async function applyBrokerSession(data: SessionStatus): Promise<void> {
  useAuthStore.getState().setUser({
    username: data.user ?? '',
    broker: data.broker ?? null,
    isLoggedIn: true,
    loginTime: new Date().toISOString(),
  })
  if (data.api_key) {
    useAuthStore.getState().setApiKey(data.api_key)
  }
  await useBrokerStore.getState().fetchCapabilities()
  await useThemeStore.getState().syncAppMode()
  if (data.active_sessions !== undefined) {
    useSessionStore.getState().setActiveSessionCount(data.active_sessions)
  }
}

/**
 * Re-reads the session after a broker login that completes inside the app
 * (the TOTP and Samco pages). AuthSync only runs on a full page load, and
 * those logins move on without one, so without this the API key, capabilities
 * and app mode stay unset until the trader reloads the page. Returns whether
 * the server reported a broker session.
 */
export async function syncBrokerSession(): Promise<boolean> {
  try {
    const data = await fetchSessionStatus()
    if (!data || !isBrokerSession(data)) return false
    await applyBrokerSession(data)
    return true
  } catch {
    // The next page load syncs it.
    return false
  }
}

interface AuthSyncProps {
  children: React.ReactNode
}

/**
 * AuthSync component that synchronizes Flask session with Zustand store.
 * This ensures the React app knows about authentication state from OAuth callbacks.
 * Also syncs app mode (live/analyzer) from the backend.
 */
export function AuthSync({ children }: AuthSyncProps) {
  const [isChecking, setIsChecking] = useState(true)

  useEffect(() => {
    const syncSession = async () => {
      const { setUser, logout } = useAuthStore.getState()
      const { clearCapabilities } = useBrokerStore.getState()
      try {
        const data = await fetchSessionStatus()

        if (data && isBrokerSession(data)) {
          // Flask session is authenticated with broker - sync to Zustand
          await applyBrokerSession(data)
        } else if (data && data.status === 'success' && data.authenticated && !data.logged_in) {
          // User is logged in but hasn't connected broker yet
          setUser({
            username: data.user ?? '',
            broker: null,
            isLoggedIn: false,
            loginTime: null,
          })
          clearCapabilities()
        } else {
          // Not authenticated, status is not success, or a non-OK response
          // (401, 500, etc.) - clear Zustand store
          logout()
          clearCapabilities()
        }
      } catch (_error) {
        // On error, don't change auth state - let existing state persist
      } finally {
        setIsChecking(false)
      }
    }

    syncSession()
  }, [])

  // Show nothing while checking - prevents flash of wrong content
  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return <>{children}</>
}
