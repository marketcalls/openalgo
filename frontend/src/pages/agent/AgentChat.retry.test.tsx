/**
 * Retry replaces the last answer; it does not ask the question a second time.
 *
 * This is pinned because the difference is invisible in the browser for about
 * one second. Retry used to call `send` with the last question's text and
 * nothing else, which reads correctly and is not: the server appends a user row
 * and an assistant row for every send, so one retry left the conversation
 * holding the same question twice and both answers, and agno went on carrying
 * the answer the operator had just rejected into every later turn.
 *
 * The assertion is therefore about the truncate call, not about the text sent.
 * A retry that sends the right text and truncates nothing is the defect.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentMessage } from '@/lib/agent/useAgentStream'
import { render, screen, userEvent } from '@/test/test-utils'
import AgentChat from './AgentChat'

const truncate = vi.fn(async () => ({}) as never)
const send = vi.fn()

/** A stored two-turn thread, ids shaped the way the server hands them back. */
function row(id: string, role: 'user' | 'assistant', content: string): AgentMessage {
  return {
    id,
    role,
    content,
    reasoning: '',
    viz: [],
    tools: [],
    attachments: [],
    notices: [],
  } as unknown as AgentMessage
}

const messages: AgentMessage[] = [
  row('stored-182', 'user', 'write a python script to fetch TCS history'),
  row('stored-183', 'assistant', 'here you go'),
]

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  truncateConversation: (...args: unknown[]) => truncate(...(args as [])),
  getSettings: async () => ({ data: { trading_enabled: false } }),
  listModels: async () => [],
  listConversations: async () => [],
}))

vi.mock('@/lib/agent/useAgentStream', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/agent/useAgentStream')>()),
  useAgentStream: () => ({
    messages,
    running: false,
    error: null,
    conversationId: 66,
    send,
    stop: vi.fn(),
    confirm: vi.fn(),
    reset: vi.fn(),
    setConversation: vi.fn(),
  }),
}))

vi.mock('@/components/agent/ConversationSidebar', () => ({
  ConversationSidebar: () => <aside />,
}))
vi.mock('@/components/agent/ModelPicker', () => ({ ModelPicker: () => <div /> }))

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  truncate.mockClear()
  send.mockClear()
})

describe('AgentChat retry', () => {
  it('truncates back to the question before answering it again', async () => {
    const user = userEvent.setup()
    wrap(<AgentChat />)

    await user.hover(await screen.findByText('here you go'))
    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    // The row named is the USER message, so the old answer goes with it.
    expect(truncate).toHaveBeenCalledWith(66, 182)
  })

  it('re-sends the question it truncated, so the turn actually happens', async () => {
    const user = userEvent.setup()
    wrap(<AgentChat />)

    await user.hover(await screen.findByText('here you go'))
    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(send).toHaveBeenCalledWith(
      'write a python script to fetch TCS history',
      expect.anything()
    )
  })
})
