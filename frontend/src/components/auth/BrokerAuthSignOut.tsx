import { LogOut } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { authApi } from '@/api/auth'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

/**
 * Sign-out control for the broker-authentication step.
 *
 * OpenAlgo logs in over two stages: the OpenAlgo password login, then the
 * broker OAuth/TOTP login that unlocks /dashboard. The broker pages render
 * outside `Layout`, so they have no `Navbar` and therefore no logout control.
 * Combined with `POST /auth/login` redirecting back to /broker whenever a
 * `user` is already in the session, that left no way out of the half-logged-in
 * state short of typing /auth/logout or clearing cookies.
 *
 * Uses the same `LogoutConfirmDialog` as the dashboard, deliberately. OpenAlgo
 * supports up to MAX_SESSIONS_PER_USER concurrent devices sharing one broker
 * feed, and a session that still carries `logged_in` reaches these pages too:
 * the broker-token-expired reconnect flow (issue #1400) is admitted by
 * `broker_login()`. For that session `blueprints/auth.py:logout()` takes the
 * full teardown path — revoke the broker token, `clear_user_sessions()` across
 * every device, broadcast `force_logout`. Confirming unconditionally means a
 * click here can never silently tear down another device's live trading
 * session, and it keeps the warning identical to the one users already know
 * from the navbar.
 */
export function BrokerAuthSignOut() {
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const [isSigningOut, setIsSigningOut] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  const performSignOut = async () => {
    setIsSigningOut(true)
    try {
      await authApi.logout()
      logout()
      showToast.success('Signed out')
      navigate('/login')
    } catch {
      // The XHR path can fail with the server session still alive: if
      // fetchCSRFToken() throws, client.ts deliberately sends the POST without
      // a token and Flask-WTF rejects it. Clearing local state and routing to
      // /login here would leave the user believing they had signed out while
      // the session cookie stayed valid.
      //
      // Fall back to a top-level navigation instead, which actually completes
      // the sign-out: GET /auth/logout clears the session and redirects to the
      // login page, is not CSRF-validated (Flask-WTF never validates GET), and
      // is accepted by _is_foreign_initiated() because a click from our own
      // page is same-origin.
      logout()
      window.location.href = '/auth/logout'
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setShowConfirm(true)}
        disabled={isSigningOut}
        className="text-muted-foreground hover:text-foreground hover:underline inline-flex items-center gap-1 disabled:opacity-60"
      >
        <LogOut className="h-3 w-3" />
        {isSigningOut ? 'Signing out...' : 'Sign out'}
      </button>
      <LogoutConfirmDialog
        open={showConfirm}
        onOpenChange={setShowConfirm}
        onConfirm={performSignOut}
      />
    </>
  )
}
