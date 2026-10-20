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

/** Whether this instance has a usable model, for the setup gate. */
let configured = true

/** The operator's trading switch, as the config page stores it. */
let tradingOn = false

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getStatus: async () => ({ configured, default_model_id: 1, model_count: 1 }),
  // The composer asks which model the turn will run on so it knows whether a
  // file may be attached, and the picker lists them. Most tests configure
  // none, and no model means the question cannot be answered, which is not a
  // reason to refuse a file.
  listModels: async () => models,
  getSettings: async () => ({
    data: { trading_enabled: tradingOn },
    defaults: { trading_enabled: false },
  }),
}))

/** The registered models the picker offers; empty unless a test sets them. */
let models: Array<Record<string, unknown>> = []

function model(id: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    provider_kind: 'openai',
    model_name: name,
    display_name: name,
    base_url: null,
    enabled: true,
    is_default: false,
    supports_reasoning: false,
    default_reasoning_effort: 'off',
    supports_vision: false,
    tools_unreliable: false,
    last_tested_at: null,
    last_test_ok: true,
    last_test_error: null,
    has_api_key: true,
    api_key_fingerprint: null,
    ...extra,
  }
}

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
  configured = true
  tradingOn = false
  models = []
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

  it('runs on the chart surface and asks for no order tools while trading is off', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await userEvent.type(box(), 'read this chart{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.surface).toBe('chart')
    // The operator's switch is off, so the panel does not even ask: the backend
    // then builds no order tool into the run's schema at all.
    expect(streams[0].body.trading_enabled).toBe(false)
  })

  it('asks for order tools when the operator has trading on', async () => {
    tradingOn = true
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await screen.findByText(/wait for your approval/)
    await userEvent.type(box(), 'buy 1 share of RELIANCE{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.surface).toBe('chart')
    expect(streams[0].body.trading_enabled).toBe(true)
  })

  it('shows the approval card when an order pauses the run', async () => {
    tradingOn = true
    replies = [
      {
        type: 'confirm',
        run_id: 'run-1',
        session_id: 'session-1',
        requirements: [
          {
            id: 'req-1',
            tool_call_id: 'call-1',
            tool_name: 'place_order',
            args: { symbol: 'RELIANCE', exchange: 'NSE', action: 'BUY', quantity: 1 },
            kind: 'confirmation',
          },
        ],
      },
    ]
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await screen.findByText(/wait for your approval/)
    await userEvent.type(box(), 'buy 1 share of RELIANCE{Enter}')

    expect(await screen.findByText('This turn is waiting for your approval.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled()
  })

  it('refuses to approve an order whose details never arrived', async () => {
    tradingOn = true
    replies = [
      {
        type: 'confirm',
        run_id: 'run-1',
        session_id: 'session-1',
        requirements: [
          {
            id: 'req-1',
            tool_call_id: 'call-1',
            tool_name: 'place_order',
            args: {},
            missing: ['exchange', 'symbol'],
          },
        ],
      },
    ]
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await screen.findByText(/wait for your approval/)
    await userEvent.type(box(), 'buy RELIANCE{Enter}')

    expect(
      await screen.findByText(/details did not arrive \(exchange, symbol\)/)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled()
  })

  it('still approves a tool that takes no arguments at all', async () => {
    // cancel_all_orders and close_all_positions have no arguments, so empty
    // arguments are complete, not lost.
    tradingOn = true
    replies = [
      {
        type: 'confirm',
        run_id: 'run-1',
        session_id: 'session-1',
        requirements: [
          {
            id: 'req-1',
            tool_call_id: 'call-1',
            tool_name: 'cancel_all_orders',
            args: {},
            missing: [],
          },
        ],
      },
    ]
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await screen.findByText(/wait for your approval/)
    await userEvent.type(box(), 'cancel all my orders{Enter}')

    expect(await screen.findByText('This turn is waiting for your approval.')).toBeInTheDocument()
    expect(screen.queryByText(/details did not arrive/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
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

/**
 * The composer's own controls, tested here rather than against `onSend`
 * because what matters is the request the server receives. The panel is the
 * cheapest place to see one: it already mounts the whole stream path.
 */
describe('AgentPanel composer controls', () => {
  it('withholds web search from the turn when the switch is off', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Add to this message' }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Web search' }))
    await userEvent.type(box(), 'what is the news on this{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    // Only the off case is transmitted. Absent means on, which is the default
    // the backend had before the switch existed.
    expect(streams[0].body.web_search).toBe(false)
  })

  it('leaves web search alone when the switch is untouched', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)
    await userEvent.type(box(), 'read this chart{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.web_search).toBeUndefined()
  })

  it('sends an attached file in the body the backend parses', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await userEvent.upload(
      screen.getByLabelText('Choose files to attach'),
      new File(['symbol,qty\nRELIANCE,10\n'], 'book.csv', { type: 'text/csv' })
    )
    await screen.findByText('book.csv')
    await userEvent.type(box(), 'what is in this{Enter}')

    await waitFor(() => expect(streams).toHaveLength(1))
    const files = streams[0].body.attachments as { name: string; mime: string; data: string }[]
    expect(files).toHaveLength(1)
    expect(files[0].name).toBe('book.csv')
    expect(files[0].mime).toBe('text/csv')
    // A data URL, which is what the server's decoder accepts alongside bare
    // base64, and what FileReader produces without a re-encoding step.
    expect(files[0].data.startsWith('data:')).toBe(true)
    // The message still carries the question. A file is not one.
    expect(streams[0].body.message).toBe('what is in this')
  })

  it('offers the chart screenshot, because this surface has a chart', async () => {
    const capture = vi.fn().mockResolvedValue(null)
    wrap(
      <AgentPanel
        getChartContext={() => context()}
        onChartCommand={vi.fn()}
        onCaptureChart={capture}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: 'Add to this message' }))
    expect(
      await screen.findByRole('menuitem', { name: 'Attach chart screenshot' })
    ).toBeInTheDocument()
  })
})

/**
 * The setup gate, which this panel shares with `/agent` rather than
 * reimplementing. A composer that takes a question an unconfigured instance
 * cannot answer is worse than one that explains itself.
 */
describe('AgentPanel setup gate', () => {
  it('asks for a model instead of a question when none is configured', async () => {
    configured = false
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    expect(await screen.findByText('Set up your agent')).toBeInTheDocument()
    expect(screen.queryByLabelText('Message the agent')).not.toBeInTheDocument()
    expect(streams).toHaveLength(0)
  })

  it('shows the composer once one is', async () => {
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await waitFor(() => expect(screen.getByLabelText('Message the agent')).toBeInTheDocument())
    expect(screen.queryByText('Set up your agent')).not.toBeInTheDocument()
  })
})

describe('AgentPanel model choice', () => {
  const both = () => [
    model(1, 'gpt-4.1', { is_default: true }),
    model(2, 'claude-sonnet-5-5', { provider_kind: 'anthropic' }),
  ]

  it('runs on the model chosen on /agent, remembered in this browser', async () => {
    models = both()
    localStorage.setItem('oa-agent-model', '2')
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    expect(await screen.findByRole('button', { name: /claude-sonnet-5-5/ })).toBeInTheDocument()
    await userEvent.type(box(), 'read this chart{Enter}')
    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body.model_id).toBe(2)
  })

  it('sends no model when none was chosen, so the configured default runs', async () => {
    models = both()
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    expect(await screen.findByRole('button', { name: /gpt-4\.1/ })).toBeInTheDocument()
    await userEvent.type(box(), 'read this chart{Enter}')
    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body).not.toHaveProperty('model_id')
  })

  it('forgets a remembered model that is no longer enabled and runs the default', async () => {
    models = [model(1, 'gpt-4.1', { is_default: true }), model(2, 'old-model', { enabled: false })]
    localStorage.setItem('oa-agent-model', '2')
    wrap(<AgentPanel getChartContext={() => context()} onChartCommand={vi.fn()} />)

    await waitFor(() => expect(localStorage.getItem('oa-agent-model')).toBeNull())
    await userEvent.type(box(), 'read this chart{Enter}')
    await waitFor(() => expect(streams).toHaveLength(1))
    expect(streams[0].body).not.toHaveProperty('model_id')
  })
})
