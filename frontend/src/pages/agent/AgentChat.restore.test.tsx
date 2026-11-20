/**
 * A refresh reopens the conversation the operator was in.
 *
 * The open thread used to live only in React state, so reloading the page
 * dropped the operator onto an empty new chat mid-session, with the thread
 * they were trading from reachable only through the sidebar.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@/test/test-utils'
import AgentChat from './AgentChat'

const KEY = 'oa-agent-active-conversation'
const getConversation = vi.fn()
const setConversation = vi.fn()
const stream = { conversationId: null as number | null }

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getConversation: (...args: unknown[]) => getConversation(...args),
  getSettings: async () => ({ data: { trading_enabled: false } }),
  listModels: async () => [],
  listConversations: async () => [],
}))

vi.mock('@/lib/agent/useAgentStream', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/agent/useAgentStream')>()),
  useAgentStream: () => ({
    messages: [],
    running: false,
    error: null,
    conversationId: stream.conversationId,
    send: vi.fn(),
    stop: vi.fn(),
    confirm: vi.fn(),
    reset: vi.fn(),
    setConversation,
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
  window.sessionStorage.clear()
  getConversation.mockReset()
  setConversation.mockReset()
  stream.conversationId = null
})

describe('AgentChat restore on refresh', () => {
  it('reopens the remembered conversation', async () => {
    window.sessionStorage.setItem(KEY, '42')
    getConversation.mockResolvedValue({ messages: [] })

    wrap(<AgentChat />)

    await waitFor(() => expect(setConversation).toHaveBeenCalledWith(42, []))
    expect(getConversation).toHaveBeenCalledWith(42)
    // The empty first render must not have erased what it was restoring.
    expect(window.sessionStorage.getItem(KEY)).toBe('42')
  })

  it('forgets a conversation that no longer opens', async () => {
    window.sessionStorage.setItem(KEY, '42')
    getConversation.mockRejectedValue(new Error('404'))

    wrap(<AgentChat />)

    await waitFor(() => expect(window.sessionStorage.getItem(KEY)).toBeNull())
    expect(setConversation).not.toHaveBeenCalled()
  })

  it('remembers the conversation that is open', async () => {
    stream.conversationId = 7

    wrap(<AgentChat />)

    await waitFor(() => expect(window.sessionStorage.getItem(KEY)).toBe('7'))
    expect(getConversation).not.toHaveBeenCalled()
  })
})
