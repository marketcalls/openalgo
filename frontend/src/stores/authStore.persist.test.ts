import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The OpenAlgo API key places orders. Anything in localStorage is readable by
 * every script on the origin and survives a browser restart, so the key must
 * live in memory only: AuthSync fetches it again from /auth/session-status on
 * every load. Only the non-secret session fields are persisted.
 */

const STORAGE_KEY = 'openalgo-auth'
const DUMMY_KEY = 'dummy-api-key-not-a-real-secret'

async function loadStore() {
  vi.resetModules()
  const { useAuthStore } = await import('./authStore')
  return useAuthStore
}

function persisted(): Record<string, unknown> | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : null
}

describe('authStore persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('does not write the API key to localStorage', async () => {
    const useAuthStore = await loadStore()
    useAuthStore.getState().login('alice', 'zerodha')
    useAuthStore.getState().setApiKey(DUMMY_KEY)

    const stored = persisted()
    expect(stored).not.toBeNull()
    expect(JSON.stringify(stored)).not.toContain(DUMMY_KEY)
    expect((stored?.state as Record<string, unknown>).apiKey).toBeUndefined()
    expect((stored?.state as Record<string, unknown>).isAuthenticated).toBe(true)
  })

  it('keeps the API key usable in memory during the session', async () => {
    const useAuthStore = await loadStore()
    useAuthStore.getState().setApiKey(DUMMY_KEY)
    expect(useAuthStore.getState().apiKey).toBe(DUMMY_KEY)
  })

  it('drops an API key left in storage by an older version', async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: {
          user: { username: 'alice', broker: 'zerodha', isLoggedIn: true, loginTime: null },
          apiKey: DUMMY_KEY,
          isAuthenticated: true,
        },
        version: 0,
      })
    )

    const useAuthStore = await loadStore()

    expect(useAuthStore.getState().apiKey).toBeNull()
    expect(useAuthStore.getState().user?.username).toBe('alice')
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(localStorage.getItem(STORAGE_KEY)).not.toContain(DUMMY_KEY)
  })

  it('clears the in-memory API key on logout', async () => {
    const useAuthStore = await loadStore()
    useAuthStore.getState().login('alice', 'zerodha')
    useAuthStore.getState().setApiKey(DUMMY_KEY)
    useAuthStore.getState().logout()

    expect(useAuthStore.getState().apiKey).toBeNull()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY)).not.toContain(DUMMY_KEY)
  })
})
