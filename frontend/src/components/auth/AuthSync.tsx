import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

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
  const { setUser, setApiKey, logout } = useAuthStore()
  const { syncAppMode } = useThemeStore()

  useEffect(() => {
    const syncSession = async () => {
      try {
        const response = await fetch('/auth/session-status', {
          credentials: 'include',
        })

        if (response.ok) {
          const data = await response.json()

          if (data.status === 'success' && data.logged_in && data.broker) {
            // Flask session is authenticated with broker - sync to Zustand
            setUser({
              username: data.user,
              broker: data.broker,
              isLoggedIn: true,
              loginTime: new Date().toISOString(),
            })
            // Store the API key for trading API calls
            if (data.api_key) {
              setApiKey(data.api_key)
            }
            // Also sync app mode from backend
            await syncAppMode()
          } else if (data.status === 'success' && data.authenticated && !data.logged_in) {
            // User is logged in but hasn't connected broker yet
            setUser({
              username: data.user,
              broker: null,
              isLoggedIn: false,
              loginTime: null,
            })
          } else {
            // Not authenticated or status is not success - clear Zustand store
            logout()
          }
        } else {
          // Any non-OK response (401, 500, etc.) - clear Zustand store
          logout()
        }
      } catch (error) {
        // On error, don't change auth state - let existing state persist
      } finally {
        setIsChecking(false)
      }
    }

    syncSession()
  }, [setUser, setApiKey, logout, syncAppMode])

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
