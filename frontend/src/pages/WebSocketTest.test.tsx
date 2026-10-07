import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@/test/test-utils'

vi.mock('@/hooks/useSupportedExchanges', () => ({
  useSupportedExchanges: () => ({ tradingExchanges: ['NSE'] }),
}))

import WebSocketTest from './WebSocketTest'

class FakeWebSocket {
  static readonly OPEN = 1
  static readonly instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.OPEN
  close = vi.fn(() => {
    this.readyState = 3
  })
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: (() => void) | null = null

  constructor(_url: string) {
    FakeWebSocket.instances.push(this)
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeWebSocket.instances.length = 0
})

describe('WebSocket tester lifetime', () => {
  it('closes every page-owned socket after 101 visits', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => ({
        json: async () =>
          url.includes('csrf-token')
            ? { csrf_token: 'test' }
            : { status: 'success', websocket_url: 'ws://test' },
      }))
    )

    for (let visit = 0; visit < 101; visit++) {
      const page = render(<WebSocketTest />)
      fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
      await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(visit + 1))
      page.unmount()
    }

    expect(
      FakeWebSocket.instances.filter((socket) => socket.close.mock.calls.length === 0)
    ).toHaveLength(0)
  }, 60_000)

  it('does not open a socket when connection setup finishes after leaving the page', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    let finishConfig: ((value: object) => void) | undefined
    const config = new Promise<object>((resolve) => {
      finishConfig = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url.includes('csrf-token')
          ? Promise.resolve({ json: async () => ({ csrf_token: 'test' }) })
          : config
      )
    )

    const page = render(<WebSocketTest />)
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBe(2))
    page.unmount()
    finishConfig?.({ json: async () => ({ status: 'success', websocket_url: 'ws://test' }) })
    await Promise.resolve()
    await Promise.resolve()

    expect(FakeWebSocket.instances).toHaveLength(0)
  })
})
