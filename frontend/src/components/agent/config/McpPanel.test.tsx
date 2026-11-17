/**
 * The external data panel renders whatever the registry serves.
 *
 * Adding an MCP server is one registry entry on the backend. This pins the
 * frontend half of that promise: the panel names each server from the
 * `/agent/api/mcp` response and carries no server-specific text of its own.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { McpServersResponse } from '@/api/agent'
import { render, screen, waitFor } from '@/test/test-utils'
import { McpPanel } from './McpPanel'

const oneServer: McpServersResponse = {
  enabled: true,
  servers: [
    {
      key: 'bse_eod',
      title: 'BSE end-of-day data',
      description: 'Daily BSE prices and corporate filings.',
      url: 'https://example.invalid/bse/mcp',
    },
  ],
}

/** What the next render's `/agent/api/mcp` returns. */
let registry: McpServersResponse = oneServer

vi.mock('@/api/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/agent')>()),
  getSettings: async () => ({ data: { mcp_enabled: true } }),
  getMcpServers: async () => registry,
}))

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <McpPanel />
    </QueryClientProvider>
  )
}

describe('McpPanel', () => {
  beforeEach(() => {
    registry = oneServer
  })

  it('names each server from the registry response', async () => {
    renderPanel()

    expect(await screen.findByText('BSE end-of-day data')).toBeInTheDocument()
    expect(screen.getByText('Daily BSE prices and corporate filings.')).toBeInTheDocument()
  })

  it('carries no text about a particular server of its own', async () => {
    const { container } = renderPanel()

    await screen.findByText('BSE end-of-day data')
    expect(container.textContent).not.toMatch(/NSE/)
  })

  it('renders nothing while no server is registered', async () => {
    registry = { enabled: true, servers: [] }
    const { container } = renderPanel()

    await waitFor(() => expect(container.textContent).toBe(''))
    expect(screen.queryByText('External data (MCP)')).not.toBeInTheDocument()
  })
})
