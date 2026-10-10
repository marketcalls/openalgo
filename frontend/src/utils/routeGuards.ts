/**
 * Paths that stay reachable with user-only auth (no broker connected).
 *
 * A misconfigured or disconnected broker must never lock the user out of the
 * screen that fixes it. /profile manages broker credentials, so it has to be
 * usable before any broker is connected.
 */
export const BROKER_AUTH_EXEMPT_PATHS = ['/profile']

export function isBrokerAuthExempt(pathname: string): boolean {
  return BROKER_AUTH_EXEMPT_PATHS.includes(pathname)
}
