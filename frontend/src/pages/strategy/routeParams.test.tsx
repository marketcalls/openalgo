/**
 * The strategy pages, mounted at the URLs they are actually reached by.
 *
 * These exist because /strategy/1 rendered "Invalid strategy id" for every
 * strategy that has ever existed, and nothing caught it:
 *
 *   - App.tsx declares `path="/strategy/:strategyId"`.
 *   - Detail.tsx and Edit.tsx read `useParams<{ id: string }>()`.
 *
 * `id` was therefore always undefined, `Number(undefined)` is NaN, and each
 * page failed its own validity check. TypeScript could not see it: the generic
 * on useParams is asserted by the caller, not derived from the route, so
 * `{ id: string }` type-checks against a route that has no `id`. Biome cannot
 * see it either. Every other frontend test renders a component with props
 * supplied directly, so none of them went through a router at all.
 *
 * The fix is not "read the right name once" - it is having a test that reaches
 * these pages the way a browser does. Both pages are asserted here, because
 * both carried the same defect and a fix applied to one would have left the
 * other broken.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

const getStrategy = vi.fn()

vi.mock('@/api/strategy_module', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/strategy_module')>('@/api/strategy_module')
  return {
    ...actual,
    getStrategy: (id: number) => getStrategy(id),
    // The detail page opens several reads and a live subscription on mount.
    // None of them is what these tests are about; the id reaching the fetcher
    // is.
    listRuns: () => Promise.resolve([]),
    listOrders: () => Promise.resolve([]),
    listEvents: () => Promise.resolve([]),
    listWebhookEvents: () => Promise.resolve([]),
    listCheckpoints: () => Promise.resolve({ data: [], run_id: null }),
    useStrategyLive: () => ({
      status: 'idle' as const,
      runId: null,
      checkpoint: null,
      legs: {},
      updatedAt: null,
      curve: [],
      isFetching: false,
      error: null,
      refresh: vi.fn(),
    }),
  }
})

function wrap(ui: ReactNode, path: string, url: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('the strategy pages read the id the route actually supplies', () => {
  it('the detail page asks for the strategy in the URL', async () => {
    getStrategy.mockResolvedValue({
      id: 7,
      name: 'Iron condor',
      status: 'stopped',
      strategy_kind: 'batch',
      legs: [],
    })
    const { default: Detail } = await import('./Detail')

    wrap(<Detail />, '/strategy/:strategyId', '/strategy/7')

    await waitFor(() => expect(getStrategy).toHaveBeenCalledWith(7))
    expect(screen.queryByText(/invalid strategy id/i)).toBeNull()
  })

  it('the edit page asks for the strategy in the URL', async () => {
    getStrategy.mockResolvedValue({
      id: 42,
      name: 'Short straddle',
      status: 'stopped',
      strategy_kind: 'batch',
      legs: [],
    })
    const { default: Edit } = await import('./Edit')

    wrap(<Edit />, '/strategy/:strategyId/edit', '/strategy/42/edit')

    await waitFor(() => expect(getStrategy).toHaveBeenCalledWith(42))
    expect(screen.queryByText(/invalid strategy id/i)).toBeNull()
  })

  it('a url with no usable id is still refused', async () => {
    getStrategy.mockClear()
    const { default: Detail } = await import('./Detail')

    wrap(<Detail />, '/strategy/:strategyId', '/strategy/not-a-number')

    expect(await screen.findByText(/invalid strategy id/i)).toBeTruthy()
    expect(getStrategy).not.toHaveBeenCalled()
  })
})
