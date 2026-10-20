/**
 * The SSE client and the hook that folds its frames into a conversation.
 *
 * Two behaviours are asserted here because reading the code cannot establish
 * either one:
 *
 * - **A heartbeat comment is dropped, not parsed.** The server writes
 *   `: heartbeat` when the queue has been idle so a reverse proxy does not
 *   close a stream while the model thinks. A client that fed that to
 *   `JSON.parse` would end the turn on the keepalive that was meant to save it.
 * - **React state is not committed per token.** Deltas are folded into a ref and
 *   flushed on an animation frame, because a markdown parse of the whole
 *   accumulated answer on every token is quadratic in its length. The test
 *   counts renders against tokens; a per-token setter fails it.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AgentFrame, streamAgentFrames } from './stream'

vi.mock('@/api/client', () => ({
  fetchCSRFToken: vi.fn(async () => 'test-csrf-token'),
}))

const cancelRun = vi.fn(async () => ({ status: 'success', message: 'ok', run_id: 'run-1' }))
vi.mock('@/api/agent', () => ({ cancelRun: (id: string) => cancelRun(id) }))

/** A rupee sign, written as an escape so this file stays ASCII on disk. */
const RUPEE = '\u20B9'

/** A Response whose body streams `text` as bytes, cut at the given offsets. */
function sseResponse(text: string, byteSplits: number[] = []): Response {
  const encoded = new TextEncoder().encode(text)
  const bounds = [0, ...byteSplits, encoded.length]
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let index = 0; index < bounds.length - 1; index += 1) {
        controller.enqueue(encoded.slice(bounds[index], bounds[index + 1]))
      }
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function mockFetch(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>
}

async function collect(): Promise<AgentFrame[]> {
  const frames: AgentFrame[] = []
  await streamAgentFrames({
    path: '/chat/stream',
    body: {},
    onFrame: (frame) => frames.push(frame),
  })
  return frames
}

describe('streamAgentFrames', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function respondWith(text: string, byteSplits: number[] = []) {
    mockFetch().mockResolvedValue(sseResponse(text, byteSplits))
  }

  it('ignores a heartbeat comment rather than parsing it', async () => {
    respondWith(
      ': heartbeat\n\n' +
        'data: {"type":"token","delta":"hello"}\n\n' +
        ': heartbeat\n\n' +
        'data: {"type":"done","reason":"stop"}\n\n'
    )
    const frames = await collect()
    expect(frames.map((frame) => frame.type)).toEqual(['token', 'done'])
  })

  it('drops a malformed data line without ending the stream', async () => {
    respondWith(
      'data: {"type":"token","delta":"a"}\n\n' +
        'data: not json at all\n\n' +
        'data: {"type":"token","delta":"b"}\n\n' +
        'data: {"type":"done","reason":"stop"}\n\n'
    )
    const frames = await collect()
    expect(frames.map((frame) => frame.type)).toEqual(['token', 'token', 'done'])
  })

  it('drops an object with no string type', async () => {
    respondWith('data: {"delta":"orphan"}\n\ndata: {"type":"done","reason":"stop"}\n\n')
    const frames = await collect()
    expect(frames.map((frame) => frame.type)).toEqual(['done'])
  })

  it('delivers a final frame that arrived with no trailing newline', async () => {
    respondWith('data: {"type":"done","reason":"stop"}')
    const frames = await collect()
    expect(frames.map((frame) => frame.type)).toEqual(['done'])
  })

  it('reassembles a frame split across two network chunks', async () => {
    respondWith('data: {"type":"token","delta":"split me"}\n\n', [18])
    const frames = await collect()
    expect(frames).toEqual([{ type: 'token', delta: 'split me' }])
  })

  it('keeps a multi-byte character split across two chunks intact', async () => {
    const text = `data: {"type":"token","delta":"${RUPEE}100"}\n\n`
    // The rupee sign is three UTF-8 bytes. Cut the stream inside it.
    const cut = new TextEncoder().encode(text.slice(0, text.indexOf(RUPEE))).length + 1
    respondWith(text, [cut])
    const frames = await collect()
    expect(frames).toEqual([{ type: 'token', delta: `${RUPEE}100` }])
  })

  it('tolerates CRLF line endings', async () => {
    respondWith('data: {"type":"token","delta":"crlf"}\r\n\r\n')
    const frames = await collect()
    expect(frames).toEqual([{ type: 'token', delta: 'crlf' }])
  })

  it('turns a pre-stream HTTP failure into an error frame', async () => {
    mockFetch().mockResolvedValue(
      new Response(JSON.stringify({ status: 'error', message: 'Set up a model first' }), {
        status: 409,
      })
    )
    const frames = await collect()
    expect(frames).toEqual([{ type: 'error', message: 'Set up a model first', kind: 'internal' }])
  })
})

describe('useAgentStream', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('does not commit React state once per token', async () => {
    const TOKENS = 300
    let text = 'data: {"type":"start","run_id":"run-1","session_id":"s-1","conversation_id":7}\n\n'
    for (let index = 0; index < TOKENS; index += 1) {
      text += `data: {"type":"token","delta":"t${index} "}\n\n`
    }
    text += 'data: {"type":"done","reason":"stop"}\n\n'
    mockFetch().mockResolvedValue(sseResponse(text))

    const { useAgentStream } = await import('./useAgentStream')

    let renders = 0
    const { result } = renderHook(() => {
      renders += 1
      return useAgentStream()
    })
    const before = renders

    await act(async () => {
      await result.current.send('count the renders')
    })
    await waitFor(() => expect(result.current.running).toBe(false))

    const assistant = result.current.messages.at(-1)
    expect(assistant?.role).toBe('assistant')
    expect(assistant?.content).toContain('t0 ')
    expect(assistant?.content).toContain(`t${TOKENS - 1} `)
    expect(assistant?.streaming).toBe(false)
    expect(result.current.conversationId).toBe(7)

    // A per-token setter would render at least once per token. The ref and the
    // scheduled flush keep it to a handful.
    expect(renders - before).toBeLessThan(TOKENS / 10)
  })

  it('stops by aborting locally and posting the cancel route', async () => {
    // A stream that never ends on its own, so stop() is what closes it.
    let close: (() => void) | null = null
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"start","run_id":"run-1","session_id":"s-1","conversation_id":7}\n\n'
          )
        )
        close = () => controller.close()
      },
    })
    mockFetch().mockResolvedValue(new Response(body, { status: 200 }))

    const { useAgentStream } = await import('./useAgentStream')
    const { result } = renderHook(() => useAgentStream())

    let pending: Promise<void> | undefined
    await act(async () => {
      pending = result.current.send('hold the line')
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current.messages.at(-1)?.runId).toBe('run-1'))

    await act(async () => {
      await result.current.stop()
      close?.()
      await pending
    })

    expect(cancelRun).toHaveBeenCalledTimes(1)
    expect(cancelRun).toHaveBeenCalledWith('run-1')
    await waitFor(() => expect(result.current.running).toBe(false))
  })
})
