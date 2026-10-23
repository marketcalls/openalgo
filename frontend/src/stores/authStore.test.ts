/**
 * syncApiKey re-reads the key after a login the SPA handles without a page
 * load. What is pinned: a key the session returns lands in the store, and a
 * failed or keyless read never clears the key already there.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './authStore'

const fetchMock = vi.fn()

describe('syncApiKey', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    useAuthStore.setState({ apiKey: null })
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('stores the key the session returns', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: 'success', logged_in: true, api_key: 'k-1' }))
    )
    await useAuthStore.getState().syncApiKey()
    expect(fetchMock).toHaveBeenCalledWith('/auth/session-status', { credentials: 'include' })
    expect(useAuthStore.getState().apiKey).toBe('k-1')
  })

  it('keeps the current key when the session returns none', async () => {
    useAuthStore.setState({ apiKey: 'old' })
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ status: 'success', broker_session_expired: true }))
    )
    await useAuthStore.getState().syncApiKey()
    expect(useAuthStore.getState().apiKey).toBe('old')
  })

  it('keeps the current key when the request fails', async () => {
    useAuthStore.setState({ apiKey: 'old' })
    fetchMock.mockRejectedValue(new Error('offline'))
    await useAuthStore.getState().syncApiKey()
    expect(useAuthStore.getState().apiKey).toBe('old')

    fetchMock.mockResolvedValue(new Response('', { status: 500 }))
    await useAuthStore.getState().syncApiKey()
    expect(useAuthStore.getState().apiKey).toBe('old')
  })
})
