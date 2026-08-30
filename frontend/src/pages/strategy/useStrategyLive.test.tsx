import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The shared socket, swapped per test. Hoisted so the module factory below can
// reach it without being evaluated too early.
const shared = vi.hoisted(() => ({ socket: null as FakeSocket | null }))

vi.mock('@/components/socket/SocketProvider', () => ({
  useSocketContext: () => ({ playAlertSound: () => {}, socket: shared.socket }),
}))

const rest = vi.hoisted(() => ({
  get: vi.fn(async () => ({ data: { status: 'success', data: [], run_id: null } })),
}))

vi.mock('@/api/client', () => ({
  webClient: { get: rest.get, post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiClient: { post: vi.fn(), get: vi.fn() },
  authClient: { post: vi.fn() },
  fetchCSRFToken: vi.fn(),
  default: { post: vi.fn(), get: vi.fn() },
}))

import {
  foldStrategyFrame,
  LIVE_POLL_MS,
  SOCKET_STALE_MS,
  type StrategyStateFrame,
  type StrategyWireLeg,
  useStrategyLive,
} from '@/api/strategy_module'

type Handler = (payload: unknown) => void

/**
 * Stands in for the one app-wide Socket.IO connection.
 *
 * Records what was emitted so the tests can assert the room is left, and lets
 * them deliver frames by hand.
 */
class FakeSocket {
  connected = true
  ackStatus: 'success' | 'error' = 'success'
  ackMessage: string | undefined
  emitted: Array<{ event: string; payload: unknown }> = []
  private handlers = new Map<string, Set<Handler>>()

  on(event: string, handler: Handler) {
    const set = this.handlers.get(event) ?? new Set<Handler>()
    set.add(handler)
    this.handlers.set(event, set)
  }

  off(event: string, handler: Handler) {
    this.handlers.get(event)?.delete(handler)
  }

  emit(event: string, payload: unknown, ack?: (response: unknown) => void) {
    this.emitted.push({ event, payload })
    ack?.({ status: this.ackStatus, message: this.ackMessage })
  }

  deliver(event: string, payload: unknown) {
    for (const handler of [...(this.handlers.get(event) ?? [])]) handler(payload)
  }

  listenerCount(event: string) {
    return this.handlers.get(event)?.size ?? 0
  }

  emittedFor(event: string) {
    return this.emitted.filter((entry) => entry.event === event).map((entry) => entry.payload)
  }
}

function wireLeg(over: Partial<StrategyWireLeg> & { leg_id: number }): StrategyWireLeg {
  return {
    symbol: 'NIFTY28MAR2420800CE',
    exchange: 'NFO',
    position: 'S',
    lots: 1,
    qty: 65,
    status: 'open',
    entry_status: 'complete',
    exit_kind: null,
    ltp: 100,
    entry_avg: 120,
    mtm: 1300,
    realized_pnl: 0,
    effective_sl: 150,
    effective_target: 60,
    trail_active: false,
    favorable_points: 20,
    tick_source: 'ws',
    ...over,
  }
}

function stateFrame(
  type: 'snapshot' | 'delta',
  legs: StrategyWireLeg[],
  over: Partial<StrategyStateFrame> = {}
): StrategyStateFrame {
  return {
    type,
    strategy_id: 7,
    run_id: 42,
    ts: '2026-04-12T14:45:00+05:30',
    ts_ms: 1_776_000_000_000,
    mtm_realized: 100,
    mtm_unrealized: 50,
    mtm_total: 150,
    peak: 200,
    trough: -20,
    lock_armed: false,
    lock_floor: null,
    trail_to_entry_active: false,
    tick_source_degraded: false,
    legs,
    ...over,
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  shared.socket = null
  rest.get.mockClear()
})

// ---------------------------------------------------------------------------

describe('foldStrategyFrame', () => {
  const openLeg = wireLeg({ leg_id: 1, status: 'open', mtm: 500 })
  const closedLeg = wireLeg({ leg_id: 2, status: 'closed', mtm: 900, exit_kind: 'exit_target' })

  it('takes every leg from a snapshot', () => {
    const folded = foldStrategyFrame(null, stateFrame('snapshot', [openLeg, closedLeg]))
    expect(Object.keys(folded.leg_state).sort()).toEqual(['1', '2'])
    expect(folded.leg_state['2'].status).toBe('closed')
    expect(folded.pnl_total).toBe(150)
    expect(folded.run_id).toBe(42)
  })

  // The one structural difference between the two frames, and the bug it
  // would otherwise cause: a closed leg's final numbers blanking on the next
  // tick because the delta that arrived did not mention it.
  it('keeps a closed leg that a delta does not mention', () => {
    const snapshot = foldStrategyFrame(null, stateFrame('snapshot', [openLeg, closedLeg]))
    const delta = foldStrategyFrame(
      snapshot,
      stateFrame('delta', [wireLeg({ leg_id: 1, status: 'open', mtm: 750 })])
    )

    expect(Object.keys(delta.leg_state).sort()).toEqual(['1', '2'])
    expect(delta.leg_state['1'].mtm).toBe(750)
    // Untouched, and still carrying what the snapshot said.
    expect(delta.leg_state['2'].mtm).toBe(900)
    expect(delta.leg_state['2'].exit_kind).toBe('exit_target')
  })

  it('lets a later snapshot drop a leg the strategy no longer has', () => {
    const first = foldStrategyFrame(null, stateFrame('snapshot', [openLeg, closedLeg]))
    const second = foldStrategyFrame(first, stateFrame('snapshot', [openLeg]))
    expect(Object.keys(second.leg_state)).toEqual(['1'])
  })

  it('handles a delta arriving before any snapshot', () => {
    const folded = foldStrategyFrame(null, stateFrame('delta', [openLeg]))
    expect(Object.keys(folded.leg_state)).toEqual(['1'])
  })

  it('maps the wire leg onto the shape the pages already read', () => {
    const folded = foldStrategyFrame(null, stateFrame('snapshot', [openLeg]))
    const leg = folded.leg_state['1']
    expect(leg.entry_avg).toBe(120)
    expect(leg.ltp).toBe(100)
    expect(leg.effective_sl).toBe(150)
    expect(leg.favorable_points).toBe(20)
    // The socket does not send the price ratchet the points came from.
    expect(leg.highest_price).toBeNull()
  })

  it('carries the run forward when a frame omits it', () => {
    const snapshot = foldStrategyFrame(null, stateFrame('snapshot', [openLeg]))
    const delta = foldStrategyFrame(snapshot, stateFrame('delta', [openLeg], { run_id: null }))
    expect(delta.run_id).toBe(42)
  })
})

describe('useStrategyLive transport', () => {
  it('falls back to polling when there is no socket at all', async () => {
    shared.socket = null
    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('polling'))
    expect(rest.get).toHaveBeenCalled()
  })

  it('falls back to polling when the socket is present but disconnected', async () => {
    const socket = new FakeSocket()
    socket.connected = false
    shared.socket = socket

    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('polling'))
    // Nothing is emitted down a socket that is not connected.
    expect(socket.emittedFor('strategy_subscribe')).toHaveLength(0)
  })

  it('reports connecting once joined but before the first frame', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('connecting'))
    expect(socket.emittedFor('strategy_subscribe')).toEqual([{ strategy_id: 7 }])
  })

  it('goes live once a snapshot arrives, and reads the figures off it', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('connecting'))

    act(() => {
      socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
    })

    await waitFor(() => expect(result.current.status).toBe('live'))
    expect(result.current.checkpoint?.pnl_total).toBe(150)
    expect(result.current.legs).toHaveLength(1)
    expect(result.current.runId).toBe(42)
  })

  it('resumes polling when a joined socket falls silent after its first frame', async () => {
    // The failure this guards: liveness used to be "a frame arrived once",
    // which is sticky. A socket that connected, delivered one snapshot and
    // then stopped left the poll disabled for the life of the page, so the
    // operator watched indefinitely stale P&L, legs and run state while the
    // badge said live. Nothing about a silent socket announces itself, which
    // is exactly why the fallback has to notice on its own.
    vi.useFakeTimers()
    try {
      const socket = new FakeSocket()
      shared.socket = socket

      const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })

      act(() => {
        socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(result.current.status).toBe('live')

      // Silence, past the staleness bound.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(SOCKET_STALE_MS + LIVE_POLL_MS)
      })

      expect(result.current.status).toBe('polling')
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows the REST answer once the socket has gone stale, not the old frame', async () => {
    // Resuming the poll changes nothing an operator can see if the page still
    // renders the frame it received before the silence. The socket frame wins
    // only while the socket is live.
    vi.useFakeTimers()
    try {
      const socket = new FakeSocket()
      shared.socket = socket
      rest.get.mockResolvedValue({
        data: {
          status: 'success',
          run_id: 42,
          data: [{ ts: '2026-04-12T15:00:00+05:30', pnl_total: 999, leg_state: {} }],
        },
      })

      const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      act(() => {
        socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(result.current.checkpoint?.pnl_total).toBe(150)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SOCKET_STALE_MS + LIVE_POLL_MS * 2)
      })

      expect(result.current.status).toBe('polling')
      expect(result.current.checkpoint?.pnl_total).toBe(999)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not label freshly polled state with a stale run id', async () => {
    // A run ends and the next one starts. The socket's last frame still names
    // the old run, and preferring it unconditionally attributed one run's
    // numbers to another on the page.
    vi.useFakeTimers()
    try {
      const socket = new FakeSocket()
      shared.socket = socket
      rest.get.mockResolvedValue({
        data: {
          status: 'success',
          run_id: 99,
          data: [{ ts: '2026-04-12T15:00:00+05:30', pnl_total: 12, leg_state: {} }],
        },
      })

      const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      act(() => {
        socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(result.current.runId).toBe(42)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SOCKET_STALE_MS + LIVE_POLL_MS * 2)
      })

      expect(result.current.runId).toBe(99)
    } finally {
      vi.useRealTimers()
    }
  })

  it('goes live again when frames resume after a silence', async () => {
    vi.useFakeTimers()
    try {
      const socket = new FakeSocket()
      shared.socket = socket

      const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      act(() => {
        socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(SOCKET_STALE_MS + LIVE_POLL_MS)
      })
      expect(result.current.status).toBe('polling')

      act(() => {
        socket.deliver(
          'strategy_delta',
          stateFrame('delta', [wireLeg({ leg_id: 1 })], { ts_ms: 1_776_000_000_001 })
        )
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })

      expect(result.current.status).toBe('live')
    } finally {
      vi.useRealTimers()
    }
  })

  it('reports an error when the join is refused', async () => {
    const socket = new FakeSocket()
    socket.ackStatus = 'error'
    socket.ackMessage = 'Strategy not found'
    shared.socket = socket

    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.message).toBe('Strategy not found')
  })

  it('drops a frame that arrives out of order', async () => {
    const socket = new FakeSocket()
    shared.socket = socket
    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('connecting'))

    act(() => {
      socket.deliver(
        'strategy_snapshot',
        stateFrame('snapshot', [wireLeg({ leg_id: 1 })], { ts_ms: 2000, mtm_total: 150 })
      )
    })
    await waitFor(() => expect(result.current.checkpoint?.pnl_total).toBe(150))

    act(() => {
      socket.deliver(
        'strategy_delta',
        stateFrame('delta', [wireLeg({ leg_id: 1 })], { ts_ms: 1000, mtm_total: 999 })
      )
    })
    expect(result.current.checkpoint?.pnl_total).toBe(150)
  })

  it('ignores a frame belonging to another strategy', async () => {
    const socket = new FakeSocket()
    shared.socket = socket
    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('connecting'))

    act(() => {
      socket.deliver(
        'strategy_snapshot',
        stateFrame('snapshot', [wireLeg({ leg_id: 1 })], { strategy_id: 99 })
      )
    })
    expect(result.current.status).toBe('connecting')
    expect(result.current.checkpoint).toBeNull()
  })

  it('stops presenting the run as live on a terminal frame', async () => {
    const socket = new FakeSocket()
    shared.socket = socket
    const { result } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('connecting'))

    act(() => {
      socket.deliver('strategy_snapshot', stateFrame('snapshot', [wireLeg({ leg_id: 1 })]))
    })
    await waitFor(() => expect(result.current.status).toBe('live'))

    act(() => {
      socket.deliver('strategy_terminal', {
        type: 'terminal',
        strategy_id: 7,
        run_id: 42,
        ts: '2026-04-12T15:15:00+05:30',
        ts_ms: 1_776_000_100_000,
        stop_reason: 'eod',
        pnl_realized: 150,
      })
    })

    await waitFor(() => expect(result.current.status).not.toBe('live'))
  })

  it('does not join at all while the strategy is stopped', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { result } = renderHook(() => useStrategyLive(7, false), { wrapper })

    await waitFor(() => expect(rest.get).toHaveBeenCalled())
    expect(socket.emittedFor('strategy_subscribe')).toHaveLength(0)
    expect(result.current.status).toBe('idle')
  })
})

describe('useStrategyLive room membership', () => {
  it('leaves the room on unmount', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { unmount } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(socket.emittedFor('strategy_subscribe')).toHaveLength(1))

    unmount()

    expect(socket.emittedFor('strategy_unsubscribe')).toEqual([{ strategy_id: 7 }])
  })

  it('leaves the old room and joins the new one when the id changes', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { rerender } = renderHook(({ id }: { id: number }) => useStrategyLive(id, true), {
      wrapper,
      initialProps: { id: 7 },
    })
    await waitFor(() => expect(socket.emittedFor('strategy_subscribe')).toHaveLength(1))

    rerender({ id: 8 })

    await waitFor(() => expect(socket.emittedFor('strategy_subscribe')).toHaveLength(2))
    expect(socket.emittedFor('strategy_unsubscribe')).toEqual([{ strategy_id: 7 }])
    expect(socket.emittedFor('strategy_subscribe')).toEqual([
      { strategy_id: 7 },
      { strategy_id: 8 },
    ])
  })

  it('removes its own listeners rather than leaving them on the shared socket', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { unmount } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(socket.listenerCount('strategy_snapshot')).toBe(1))

    unmount()

    for (const event of [
      'strategy_snapshot',
      'strategy_delta',
      'strategy_event',
      'strategy_order_update',
      'strategy_run_update',
      'strategy_terminal',
      'connect',
      'disconnect',
    ]) {
      expect(socket.listenerCount(event)).toBe(0)
    }
  })

  it('never disconnects the shared connection', async () => {
    const socket = new FakeSocket()
    shared.socket = socket

    const { unmount } = renderHook(() => useStrategyLive(7, true), { wrapper })
    await waitFor(() => expect(socket.emittedFor('strategy_subscribe')).toHaveLength(1))
    unmount()

    expect(socket.connected).toBe(true)
    expect(socket.emitted.map((entry) => entry.event)).not.toContain('disconnect')
  })
})
