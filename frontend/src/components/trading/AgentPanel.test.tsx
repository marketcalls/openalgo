/**
 * The two things this panel adds on top of the chat surface it reuses.
 *
 * Everything else here (the thread, the markdown, the tool timeline, the
 * composer) is the `/agent` page's own machinery and is tested where it lives.
 * What is only true on the chart is that the context is read when the message
 * is sent rather than when the panel opened, and that a suggestion chip fills
 * the box without sending. Both have an obvious wrong version that looks
 * identical on screen, which is why they are pinned here.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChartContext } from '@/lib/trading/chartContract'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { AgentPanel } from './AgentPanel'

/** Every stream the panel opens, so the request body can be inspected. */
const streams: { path: string; body: Record<string, unknown> }[] = []

/** Frames the next turn will deliver, ahead of its done frame. */
let replies: unknown[] = []

vi.mock('@/lib/agent/stream', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/agent/stream')>()),
  streamAgentFrames: async (request: {
    path: string
    body: Record<string, unknown>
    onFrame: (frame: unknown) => void
  }) => {
    streams.push({ path: request.path, body: request.body })
    for (const frame of replies) request.onFrame(frame)
    request.onFrame({ type: 'done', reason: 'stop' })
  },
}))

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getStatus: async () => ({ configured: true, default_model_id: 1, model_count: 1 }),
}))

function context(overrides: Partial<ChartContext> = {}): ChartContext {
  return {
    symbol: 'RELIANCE',
    exchange: 'NSE',
    interval: 'D',
    chart_type: 'candlestick',
    bars_loaded: 400,
    visible_bars: 180,
    visible_from: 1772916803,
    visible_to: 1788468803,
    last_price: 1302.5,
    indicators: [],
    drawings: [],
    agent_groups: [],
    ...overrides,
  }
}

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function box(): HTMLTextAreaElement {
  return screen.getByLabelText('Message the agent') as HTMLTextAreaElement
}

beforeEach(() => {
  streams.length = 0
  replies = []
  localStorage.clear()
})

describe('AgentPanel chart commands', () => {
  it('hands a draw command straight to the terminal', async () => {
    const commands = [
      {
        op: 'draw',
        group: 'levels',
        shapes: [{ kind: 'level', price: 1271, tone: 'bullish', id: 'ai:levels:0' }],
      },
    ]
    replies = [{ type: 'chart_command', commands }]
    const onChartCommand = vi.fn()
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={onChartCommand} />)

    await userEvent.type(box(), 'draw the levels{Enter}')

    // Delivered as it came off the wire. What each op means is the terminal's
    // business, and chartContract.test.ts is where that is pinned.
    await waitFor(() => expect(onChartCommand).toHaveBeenCalledWith(commands))
  })
})

describe('AgentPanel chart context', () => {
  it('reads the chart at send time, not at mount', async () => {
    // The operator opens the panel on one instrument and then loads another
    // before asking anything. A context captured at mount would have the agent
    // analysing the chart they used to be looking at.
    let current = context({ symbol: 'RELIANCE', interval: 'D' })
    const getChartContext = vi.fn(() => current)
    wrap(<AgentPanel getChartContext={getChartContext} onChartCommand={vi.fn()} />)

    expect(getChartContext).not.toHaveBeenCalled()

    current = context({ symbol: 'INFY', interval: '15m' })
    await userEvent.type(box(), 'what is the trend{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].path).toBe('/chat/stream')
    expect(streams[0].body.chart_context).toMatchObject({ symbol: 'INFY', interval: '15m' })
  })

  it('runs on the chart surface and asks for no order tools', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await userEvent.type(box(), 'read this chart{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.surface).toBe('chart')
    // Asking is not the same as getting, but this surface does not even ask:
    // the backend then builds no order tool into the run's schema at all.
    expect(streams[0].body.trading_enabled).toBe(false)
  })

  it('sends no context when nothing is charted', async () => {
    wrap(<AgentPanel getChartContext={() => null} onChartCommand={vi.fn()} />)
    await userEvent.type(box(), 'hello{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.chart_context).toBeUndefined()
  })
})

describe('AgentPanel suggestion chips', () => {
  it('fills the composer and sends nothing', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Analyse this chart' }))

    // The instrument comes from the live context, so the chip is about the
    // chart in front of the operator rather than a generic prompt.
    expect(box().value).toBe('Analyse the RELIANCE D chart: trend, structure and momentum.')
    expect(streams).toHaveLength(0)
    // Sending stays the operator's action, and theirs alone.
    expect(screen.getByRole('button', { name: 'Send the message' })).toBeEnabled()
  })

  it('keeps what the operator was already writing', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await userEvent.type(box(), 'ignore the gap')
    await userEvent.click(screen.getByRole('button', { name: 'Candlestick patterns' }))

    expect(box().value).toBe(
      'ignore the gap\nIdentify the candlestick patterns on this chart and mark them.'
    )
    expect(streams).toHaveLength(0)
  })

  it('offers a chart-shaped starting point rather than a menu', () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    for (const label of [
      'Analyse this chart',
      'Draw demand and supply',
      'Candlestick patterns',
      'Read my drawings',
    ]) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })
})
