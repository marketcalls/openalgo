/**
 * What a reloaded conversation must still show.
 *
 * The first test is the defect itself: usage is written into the message's
 * notices sidecar by `_TurnRecorder.sidecar()` in `blueprints/agent.py` and
 * nowhere else, so a hydration that copies `content` and `tools` and leaves the
 * sidecar packed produces a thread whose turns show no tokens and no cost, and
 * a header total that counts only what streamed since the page loaded. Without
 * this test that failure looks identical to a conversation that genuinely cost
 * nothing.
 */

import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '@/api/agent'
import { sumUsage } from '@/components/agent/UsageBadge'
import { hydrateMessages } from './hydrate'
import { OPENUI_VIZ } from './viz'

function storedMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 1,
    conversation_id: 7,
    role: 'assistant',
    content: 'Answered.',
    tools: [],
    notices: [],
    created_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  }
}

const USAGE = {
  type: 'usage' as const,
  input_tokens: 1200,
  output_tokens: 300,
  total_tokens: 1500,
  cached_tokens: 100,
  reasoning_tokens: 40,
  cost_usd: 0.0123,
  model: 'gpt-4o-mini',
  ttft_ms: 480,
}

describe('hydrateMessages', () => {
  it('carries a stored turn usage onto the message and into the total', () => {
    const [message] = hydrateMessages([storedMessage({ notices: [USAGE] })])

    expect(message.usage).toEqual({
      input_tokens: 1200,
      output_tokens: 300,
      total_tokens: 1500,
      cached_tokens: 100,
      reasoning_tokens: 40,
      cost_usd: 0.0123,
      model: 'gpt-4o-mini',
      ttft_ms: 480,
    })

    const totals = sumUsage([message.usage])
    expect(totals.turns).toBe(1)
    expect(totals.totalTokens).toBe(1500)
    expect(totals.costUsd).toBeCloseTo(0.0123)
    expect(totals.hasUnpricedTurn).toBe(false)
  })

  it('keeps an unpriced turn unknown rather than free', () => {
    const [message] = hydrateMessages([storedMessage({ notices: [{ ...USAGE, cost_usd: null }] })])

    expect(message.usage?.cost_usd).toBeNull()
    expect(sumUsage([message.usage]).hasUnpricedTurn).toBe(true)
  })

  it('splits the sidecar into notices, visualizations and prose', () => {
    const [message] = hydrateMessages([
      storedMessage({
        content: 'Here is the position book.',
        tools: [{ id: 'call-1', name: 'get_positions', args: { exchange: 'NSE' }, ok: true }],
        notices: [
          { type: 'notice', level: 'warning', message: 'Trading is disabled.' },
          { type: 'error', message: 'The provider timed out.', kind: 'provider' },
          { type: 'ui', content: 'root = Card([])' },
        ],
      }),
    ])

    expect(message.role).toBe('assistant')
    expect(message.content).toBe('Here is the position book.')
    expect(message.tools).toHaveLength(1)
    expect(message.tools[0].ok).toBe(true)
    expect(message.viz).toEqual([
      {
        kind: OPENUI_VIZ,
        spec: { markup: 'root = Card([])' },
        title: '',
        source: '',
        at: 'Here is the position book.'.length,
      },
    ])
    expect(message.notices).toEqual([
      { level: 'warning', message: 'Trading is disabled.' },
      { level: 'error', message: 'The provider timed out.' },
    ])
    expect(message.streaming).toBe(false)
  })

  it('restores a stored chart as the same item the live frame produced', () => {
    // `_TurnRecorder` stores the frame dict verbatim, which is what lets one
    // renderer branch serve a chart that is streaming and the same chart after
    // a reload. Without this a conversation loses every chart it drew.
    const spec = { engine: '2d', data: [{ type: 'bar' }] }
    const [message] = hydrateMessages([
      storedMessage({
        content: 'Open interest peaks at 24000.',
        notices: [
          {
            type: 'viz',
            kind: 'plotly',
            spec,
            title: 'NIFTY 08SEP26 open interest by strike',
            source: 'option_chain_service',
          },
          { type: 'ui', content: 'root = Card([])' },
        ],
      }),
    ])

    expect(message.viz.map((entry) => entry.kind)).toEqual(['plotly', OPENUI_VIZ])
    expect(message.viz[0].spec).toEqual(spec)
    expect(message.viz[0].title).toBe('NIFTY 08SEP26 open interest by strike')
    expect(message.viz[0].source).toBe('option_chain_service')
    // A stored turn has no record of how much prose had been written when the
    // frame arrived, so every chart is anchored at the end of the answer.
    expect(message.viz[0].at).toBe(message.content.length)
  })

  it('drops a stored viz entry whose spec is not an object', () => {
    const [message] = hydrateMessages([
      storedMessage({
        notices: [
          {
            type: 'viz',
            kind: 'candles',
            spec: null,
            title: null,
            source: null,
          } as unknown as ChatMessage['notices'][number],
        ],
      }),
    ])

    expect(message.viz).toHaveLength(1)
    expect(message.viz[0].spec).toEqual({})
    expect(message.viz[0].title).toBe('')
  })

  it('re-offers a confirmation only on the newest message', () => {
    const confirm = {
      type: 'confirm' as const,
      run_id: 'run-1',
      session_id: 'session-1',
      requirements: [
        {
          id: 'req-1',
          tool_call_id: 'call-1',
          tool_name: 'place_order',
          args: { symbol: 'INFY' },
          kind: 'confirmation' as const,
        },
      ],
    }

    // Decided: the resumed run was persisted as the message after it.
    const decided = hydrateMessages([
      storedMessage({ id: 1, notices: [confirm] }),
      storedMessage({ id: 2, content: 'Order placed.' }),
    ])
    expect(decided[0].pending).toBeNull()

    // Still parked: nothing follows it, and agno's own store still holds the
    // requirement, so the operator can still answer it after a reload.
    const parked = hydrateMessages([storedMessage({ id: 1, notices: [confirm] })])
    expect(parked[0].pending).toEqual({
      runId: 'run-1',
      sessionId: 'session-1',
      requirements: confirm.requirements,
    })
  })

  it('survives a row whose sidecar is missing fields', () => {
    const [message] = hydrateMessages([
      storedMessage({
        content: null as unknown as string,
        tools: null as unknown as ChatMessage['tools'],
        notices: [
          { type: 'notice', level: 'nonsense' as never, message: null as unknown as string },
          { type: 'usage', cost_usd: 'free' } as unknown as ChatMessage['notices'][number],
        ],
      }),
    ])

    expect(message.content).toBe('')
    expect(message.tools).toEqual([])
    expect(message.notices).toEqual([{ level: 'info', message: '' }])
    expect(message.usage?.total_tokens).toBe(0)
    expect(message.usage?.cost_usd).toBeNull()
  })

  it('gives a user turn the user role and a stable id', () => {
    const messages = hydrateMessages([
      storedMessage({ id: 4, role: 'user', content: 'What are my positions?' }),
      storedMessage({ id: 5 }),
    ])

    expect(messages[0].role).toBe('user')
    expect(messages[0].id).toBe('stored-4')
    expect(messages[1].id).toBe('stored-5')
    // Re-opening the same conversation must produce the same keys.
    expect(hydrateMessages([storedMessage({ id: 4 })])[0].id).toBe('stored-4')
  })
})
