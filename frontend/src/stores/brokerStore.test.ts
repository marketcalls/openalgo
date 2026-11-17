/**
 * The capabilities request is shared while it is in flight: the navbar and its
 * account controls both ask at mount, and the server should be asked once.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useBrokerStore } from './brokerStore'

const capabilities = {
  broker_name: 'fixture',
  broker_type: 'IN_stock',
  supported_exchanges: ['NSE'],
  leverage_config: false,
}

afterEach(() => {
  vi.unstubAllGlobals()
  useBrokerStore.getState().clearCapabilities()
})

describe('useBrokerStore.fetchCapabilities', () => {
  it('sends one request for callers that ask while it is in flight', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ status: 'success', data: capabilities }))
    )
    vi.stubGlobal('fetch', fetchMock)

    const { fetchCapabilities } = useBrokerStore.getState()
    await Promise.all([fetchCapabilities(), fetchCapabilities()])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useBrokerStore.getState().capabilities).toEqual(capabilities)
  })

  it('asks again once the earlier request has settled', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ status: 'success', data: capabilities }))
    )
    vi.stubGlobal('fetch', fetchMock)

    await useBrokerStore.getState().fetchCapabilities()
    await useBrokerStore.getState().fetchCapabilities()

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
