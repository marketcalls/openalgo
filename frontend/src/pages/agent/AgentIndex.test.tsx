/**
 * The /agent gate.
 *
 * This page and the chart panel now render the same component from the same
 * status query, and the reason to pin it here as well as there is that they
 * used to be two copies of the same paragraph. A regression would look like
 * one surface asking for a model and the other quietly offering a box to type
 * in, which is the failure worth catching: a composer that accepts a question
 * an unconfigured instance cannot answer.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@/test/test-utils'
import AgentIndex from './AgentIndex'

/** Whether this instance has a usable model. */
let configured = false
/** Whether the status route answers at all. */
let reachable = true

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getStatus: async () => {
    if (!reachable) throw new Error('network')
    return { configured, default_model_id: configured ? 1 : null, model_count: configured ? 1 : 0 }
  },
  listModels: async () => [],
  listConversations: async () => [],
}))

// The page renders the app navbar, which is not what any of this is about.
vi.mock('@/components/layout/Navbar', () => ({
  Navbar: () => <nav aria-label="Main" />,
}))

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  configured = false
  reachable = true
})

describe('AgentIndex setup gate', () => {
  it('asks for a model instead of a conversation when none is configured', async () => {
    wrap(<AgentIndex />)

    expect(await screen.findByText('Set up your agent')).toBeInTheDocument()
    // The gate has to lead somewhere: a fresh install lands here.
    expect(screen.getByRole('link', { name: /Configure the agent/ })).toHaveAttribute(
      'href',
      '/agent/config'
    )
    expect(screen.queryByLabelText('Message the agent')).not.toBeInTheDocument()
  })

  it('reads an unreachable status as unconfigured, never as a working agent', async () => {
    reachable = false
    wrap(<AgentIndex />)

    expect(await screen.findByText('Set up your agent')).toBeInTheDocument()
  })

  it('opens the conversation once a model is configured', async () => {
    configured = true
    wrap(<AgentIndex />)

    expect(await screen.findByLabelText('Message the agent')).toBeInTheDocument()
    expect(screen.queryByText('Set up your agent')).not.toBeInTheDocument()
  })
})
