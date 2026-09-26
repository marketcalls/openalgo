/**
 * useKeepReconnecting: the Action Center's connection never stopped retrying,
 * and the shared one it now uses gives up after five attempts. While the page
 * is open the hook starts another cycle whenever one gives up, and it never
 * reopens a connection its owner closed on purpose.
 *
 * The first block drives the hook with a fake socket and fake timers. The
 * second checks, against the real socket.io-client, the two facts the hook
 * rests on: a socket whose reconnection gave up is still `active` and
 * `connect()` starts a fresh cycle, while a socket closed with `disconnect()`
 * is not `active`.
 */

import { renderHook } from '@testing-library/react'
import { io, type Socket } from 'socket.io-client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RECONNECT_CYCLE_PAUSE_MS, useKeepReconnecting } from './useKeepReconnecting'

class Emitter {
  handlers = new Map<string, Set<() => void>>()

  on(event: string, handler: () => void) {
    const set = this.handlers.get(event) ?? new Set()
    set.add(handler)
    this.handlers.set(event, set)
    return this
  }

  off(event: string, handler: () => void) {
    this.handlers.get(event)?.delete(handler)
    return this
  }

  fire(event: string) {
    for (const handler of [...(this.handlers.get(event) ?? [])]) handler()
  }

  count(event: string) {
    return this.handlers.get(event)?.size ?? 0
  }
}

class FakeSocket {
  connected = false
  active = true
  io = new Emitter()
  connect = vi.fn(() => this)
}

function asSocket(fake: FakeSocket) {
  return fake as unknown as Socket
}

describe('useKeepReconnecting', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts another reconnection cycle after the pause when one gives up', () => {
    const socket = new FakeSocket()
    renderHook(() => useKeepReconnecting(asSocket(socket)))

    socket.io.fire('reconnect_failed')
    vi.advanceTimersByTime(RECONNECT_CYCLE_PAUSE_MS - 1)
    expect(socket.connect).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(socket.connect).toHaveBeenCalledTimes(1)
  })

  it('keeps doing so for as long as the page is open', () => {
    const socket = new FakeSocket()
    renderHook(() => useKeepReconnecting(asSocket(socket)))

    for (let cycle = 1; cycle <= 3; cycle++) {
      socket.io.fire('reconnect_failed')
      vi.advanceTimersByTime(RECONNECT_CYCLE_PAUSE_MS)
      expect(socket.connect).toHaveBeenCalledTimes(cycle)
    }
  })

  it('never reopens a connection its owner closed on purpose', () => {
    const socket = new FakeSocket()
    renderHook(() => useKeepReconnecting(asSocket(socket)))

    socket.io.fire('reconnect_failed')
    // Logout, leaving the layout, or the server ending the session.
    socket.active = false
    vi.advanceTimersByTime(RECONNECT_CYCLE_PAUSE_MS)

    expect(socket.connect).not.toHaveBeenCalled()
  })

  it('does nothing when the connection came back by itself meanwhile', () => {
    const socket = new FakeSocket()
    renderHook(() => useKeepReconnecting(asSocket(socket)))

    socket.io.fire('reconnect_failed')
    socket.connected = true
    vi.advanceTimersByTime(RECONNECT_CYCLE_PAUSE_MS)

    expect(socket.connect).not.toHaveBeenCalled()
  })

  it('stops, and cancels a pending restart, when the page closes', () => {
    const socket = new FakeSocket()
    const { unmount } = renderHook(() => useKeepReconnecting(asSocket(socket)))
    expect(socket.io.count('reconnect_failed')).toBe(1)

    socket.io.fire('reconnect_failed')
    unmount()
    vi.advanceTimersByTime(RECONNECT_CYCLE_PAUSE_MS)

    expect(socket.connect).not.toHaveBeenCalled()
    expect(socket.io.count('reconnect_failed')).toBe(0)
  })

  it('registers nothing without a connection or when switched off', () => {
    const socket = new FakeSocket()
    renderHook(() => useKeepReconnecting(null))
    renderHook(() => useKeepReconnecting(asSocket(socket), false))

    expect(socket.io.count('reconnect_failed')).toBe(0)
  })
})

describe('what the hook relies on in socket.io-client', () => {
  // Nothing listens on port 1, so every attempt is refused at once.
  const DEAD_URL = 'http://127.0.0.1:1'
  const FAST = {
    transports: ['polling'],
    upgrade: false,
    forceNew: true,
    reconnectionAttempts: 2,
    reconnectionDelay: 10,
    reconnectionDelayMax: 10,
    randomizationFactor: 0,
    timeout: 2000,
  }

  it('a socket whose reconnection gave up is still active, and connect() starts a new cycle', async () => {
    const socket = io(DEAD_URL, FAST)
    try {
      await new Promise<void>((resolve) => socket.io.once('reconnect_failed', () => resolve()))
      expect(socket.connected).toBe(false)
      expect(socket.active).toBe(true)

      const attempts: number[] = []
      socket.io.on('reconnect_attempt', (attempt) => attempts.push(attempt))
      const gaveUpAgain = new Promise<void>((resolve) =>
        socket.io.once('reconnect_failed', () => resolve())
      )
      socket.connect()
      await gaveUpAgain

      expect(attempts).toEqual([1, 2])
    } finally {
      socket.disconnect()
    }
  }, 15000)

  it('a socket closed with disconnect() is not active', () => {
    const socket = io(DEAD_URL, FAST)
    socket.disconnect()
    expect(socket.active).toBe(false)
  })
})
