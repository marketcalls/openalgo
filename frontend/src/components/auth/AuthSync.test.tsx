/**
 * Issue 2417: a broker login that completes inside the app (the TOTP and
 * Samco pages) moves on without a page reload, so AuthSync never ran for it
 * and the API key stayed unset; every order ticket's button was disabled
 * until the trader reloaded. syncBrokerSession re-reads the session for them.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'
import { useThemeStore } from '@/stores/themeStore'
import { syncBrokerSession } from './AuthSync'

function respondWith(body: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok, json: async () => body }) as Response)
  )
}

describe('syncBrokerSession', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, apiKey: null, isAuthenticated: false })
    vi.spyOn(useBrokerStore.getState(), 'fetchCapabilities').mockResolvedValue()
    vi.spyOn(useThemeStore.getState(), 'syncAppMode').mockResolvedValue()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads the API key, capabilities and app mode after an in-app login', async () => {
    respondWith({
      status: 'success',
      logged_in: true,
      user: 'trader',
      broker: 'angel',
      api_key: 'key-123',
      active_sessions: 1,
    })
    await expect(syncBrokerSession()).resolves.toBe(true)
    expect(useAuthStore.getState().apiKey).toBe('key-123')
    expect(useAuthStore.getState().user?.broker).toBe('angel')
    expect(useBrokerStore.getState().fetchCapabilities).toHaveBeenCalled()
    expect(useThemeStore.getState().syncAppMode).toHaveBeenCalled()
  })

  it('changes nothing when the server reports no broker session', async () => {
    respondWith({ status: 'success', authenticated: true, logged_in: false })
    await expect(syncBrokerSession()).resolves.toBe(false)
    expect(useAuthStore.getState().apiKey).toBeNull()
  })

  it('changes nothing when the request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('offline')
      })
    )
    await expect(syncBrokerSession()).resolves.toBe(false)
    expect(useAuthStore.getState().apiKey).toBeNull()
  })
})
