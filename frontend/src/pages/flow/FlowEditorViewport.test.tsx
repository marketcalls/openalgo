import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  getViewportForBounds,
  type ReactFlowProps,
  type FitViewOptions,
} from '@xyflow/react'
import type { PropsWithChildren, ReactNode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FlowEditor from './FlowEditor'

const capturedCanvas = vi.hoisted(() => ({
  props: undefined as { fitView?: boolean; fitViewOptions?: FitViewOptions } | undefined,
}))

const getWorkflowMock = vi.hoisted(() => vi.fn())

vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react')

  return {
    ...actual,
    ReactFlow: ({ children, ...props }: ReactFlowProps) => {
      capturedCanvas.props = props
      return <div data-testid="flow-canvas">{children}</div>
    },
    ReactFlowProvider: ({ children }: PropsWithChildren) => <>{children}</>,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Panel: ({ children }: { children: ReactNode }) => <>{children}</>,
    useReactFlow: () => ({
      screenToFlowPosition: (position: { x: number; y: number }) => position,
    }),
  }
})

vi.mock('@/api/flow', async () => {
  const actual = await vi.importActual<typeof import('@/api/flow')>('@/api/flow')
  return { ...actual, getWorkflow: getWorkflowMock }
})

vi.mock('@/hooks/useProfileMenuItems', () => ({
  useProfileMenuItems: () => [],
}))

describe('FlowEditor initial viewport', () => {
  beforeEach(() => {
    capturedCanvas.props = undefined
    getWorkflowMock.mockReset()
    getWorkflowMock.mockResolvedValue({
      id: 7,
      name: 'Compact workflow',
      description: null,
      nodes: [],
      edges: [],
      is_active: true,
      schedule_job_id: null,
      webhook_token: null,
      webhook_secret: null,
      webhook_enabled: false,
      webhook_auth_type: 'payload',
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
    })
  })

  it('opens a small workflow centered at its natural size', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <MemoryRouter initialEntries={['/flow/7']}>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route path="/flow/:id" element={<FlowEditor />} />
          </Routes>
        </QueryClientProvider>
      </MemoryRouter>
    )

    await waitFor(() => expect(capturedCanvas.props).toBeDefined())

    const viewport = getViewportForBounds(
      { x: 100, y: 80, width: 300, height: 200 },
      1200,
      800,
      0.1,
      capturedCanvas.props?.fitViewOptions?.maxZoom ?? 2,
      0.1
    )

    expect(capturedCanvas.props?.fitView).toBe(true)
    expect(viewport.zoom).toBe(1)
  })
})
