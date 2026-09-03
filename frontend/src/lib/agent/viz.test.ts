/**
 * How a turn's visualizations reach the thread.
 *
 * Four behaviours are asserted here because none of them can be established by
 * reading the renderer:
 *
 * - **A chart lands where the model drew it.** Each item records the length of
 *   the prose at the moment its frame arrived, and later tokens must not move
 *   it. Without that anchor every chart in a turn stacks after the answer, and
 *   the third one's commentary ends up above it.
 * - **`ui` deltas accumulate.** The renderer wants the whole string on every
 *   frame; handing it a delta renders one fragment and loses the rest.
 * - **A chart closes an open OpenUI block.** A turn that renders markup, draws,
 *   then renders more markup is two blocks with a chart between them, not one
 *   block with a chart wedged inside it.
 * - **An unknown kind survives the hook untouched.** The decision to draw
 *   nothing belongs to `VizBlock`, so a newer backend can add a kind without a
 *   client release. A hook that dropped it would make that impossible to fix
 *   in the renderer alone.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OPENUI_VIZ, openUiMarkup, openUiSpec, vizItemFromFrame } from './viz'

vi.mock('@/api/client', () => ({
  fetchCSRFToken: vi.fn(async () => 'test-csrf-token'),
}))

vi.mock('@/api/agent', () => ({
  cancelRun: vi.fn(async () => ({ status: 'success', message: 'ok', run_id: 'run-1' })),
}))

const START = 'data: {"type":"start","run_id":"run-1","session_id":"s-1","conversation_id":7}\n\n'
const DONE = 'data: {"type":"done","reason":"stop"}\n\n'

function token(delta: string): string {
  return `data: ${JSON.stringify({ type: 'token', delta })}\n\n`
}

function ui(delta: string): string {
  return `data: ${JSON.stringify({ type: 'ui', delta })}\n\n`
}

function viz(kind: string, spec: Record<string, unknown> = {}): string {
  return `data: ${JSON.stringify({ type: 'viz', kind, spec, title: 't', source: 's' })}\n\n`
}

function sseResponse(text: string): Response {
  const encoded = new TextEncoder().encode(text)
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoded)
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function mockFetch(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>
}

/** Stream one scripted turn and hand back the assistant message it produced. */
async function runTurn(text: string) {
  mockFetch().mockResolvedValue(sseResponse(text))
  const { useAgentStream } = await import('./useAgentStream')
  const { result } = renderHook(() => useAgentStream())
  await act(async () => {
    await result.current.send('draw something')
  })
  await waitFor(() => expect(result.current.running).toBe(false))
  const assistant = result.current.messages.at(-1)
  if (!assistant) throw new Error('the turn produced no assistant message')
  return assistant
}

describe('viz item helpers', () => {
  it('reads markup back out of an openui spec, and nothing else', () => {
    expect(openUiMarkup(openUiSpec('root = Card([])'))).toBe('root = Card([])')
    expect(openUiMarkup({})).toBe('')
    expect(openUiMarkup({ markup: 42 })).toBe('')
  })

  it('builds a fresh spec object per markup value', () => {
    // A renderer memoized on spec identity has to see growing markup as a
    // change, while a chart's spec must keep its identity for the life of the
    // turn. This is the half that has to change.
    expect(openUiSpec('a')).not.toBe(openUiSpec('a'))
  })

  it('passes a frame spec through by reference', () => {
    // CandleViz keys its whole chart lifecycle on this object's identity, so
    // cloning it here would rebuild the chart on every streamed token.
    const spec = { bars: [] }
    const item = vizItemFromFrame(
      { type: 'viz', kind: 'candles', spec, title: 'INFY', source: 'history_service' },
      12
    )
    expect(item.spec).toBe(spec)
    expect(item.at).toBe(12)
  })

  it('defends against a frame whose fields are the wrong shape', () => {
    const item = vizItemFromFrame(
      {
        type: 'viz',
        kind: 'candles',
        spec: null as unknown as Record<string, unknown>,
        title: 7 as unknown as string,
        source: undefined as unknown as string,
      },
      0
    )
    expect(item.spec).toEqual({})
    expect(item.title).toBe('')
    expect(item.source).toBe('')
  })
})

describe('useAgentStream visualizations', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('anchors a chart at the prose written when its frame arrived', async () => {
    const assistant = await runTurn(
      START +
        token('Here is the chart.') +
        viz('candles', { bars: [{ time: 1, close: 2 }] }) +
        token(' It fell all week.') +
        DONE
    )

    expect(assistant.content).toBe('Here is the chart. It fell all week.')
    expect(assistant.viz).toHaveLength(1)
    // The prose written before the frame, not the whole answer: a later token
    // must not drag the chart to the end.
    expect(assistant.viz[0].at).toBe('Here is the chart.'.length)
    expect(assistant.viz[0].kind).toBe('candles')
    expect(assistant.viz[0].title).toBe('t')
    expect(assistant.viz[0].source).toBe('s')
  })

  it('accumulates ui deltas into one block and hands over the whole string', async () => {
    const assistant = await runTurn(
      START + ui('root = Card([a])\n') + ui('a = TextContent(') + ui('"hello")') + DONE
    )

    expect(assistant.viz).toHaveLength(1)
    expect(assistant.viz[0].kind).toBe(OPENUI_VIZ)
    expect(openUiMarkup(assistant.viz[0].spec)).toBe('root = Card([a])\na = TextContent("hello")')
  })

  it('closes an open markup block when a chart is drawn between two of them', async () => {
    const assistant = await runTurn(
      START +
        ui('root = Card([a])') +
        viz('plotly', { engine: '2d' }) +
        ui('root = Card([b])') +
        DONE
    )

    expect(assistant.viz.map((item) => item.kind)).toEqual([OPENUI_VIZ, 'plotly', OPENUI_VIZ])
    expect(openUiMarkup(assistant.viz[0].spec)).toBe('root = Card([a])')
    expect(openUiMarkup(assistant.viz[2].spec)).toBe('root = Card([b])')
  })

  it('carries a kind it cannot draw through to the renderer', async () => {
    const assistant = await runTurn(START + viz('sankey', { nodes: [] }) + DONE)

    expect(assistant.viz).toHaveLength(1)
    expect(assistant.viz[0].kind).toBe('sankey')
    expect(assistant.viz[0].spec).toEqual({ nodes: [] })
  })

  it('does not commit React state once per ui frame', async () => {
    const FRAMES = 300
    let text = START
    for (let index = 0; index < FRAMES; index += 1) text += ui(`x${index} `)
    text += DONE
    mockFetch().mockResolvedValue(sseResponse(text))

    const { useAgentStream } = await import('./useAgentStream')
    let renders = 0
    const { result } = renderHook(() => {
      renders += 1
      return useAgentStream()
    })
    const before = renders

    await act(async () => {
      await result.current.send('render a lot of markup')
    })
    await waitFor(() => expect(result.current.running).toBe(false))

    const assistant = result.current.messages.at(-1)
    expect(assistant?.viz).toHaveLength(1)
    expect(openUiMarkup(assistant?.viz[0].spec ?? {})).toContain(`x${FRAMES - 1} `)
    // The ref-and-flush path is what holds this down. A setter per frame would
    // render at least once per frame.
    expect(renders - before).toBeLessThan(FRAMES / 10)
  })
})
