import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'

vi.mock('@/api/flow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/flow')>()
  return {
    ...actual,
    getIndexSymbolsLotSizes: vi.fn(async () => []),
    getWebhookInfo: vi.fn(async () => null),
  }
})

const { ConfigPanel } = await import('./ConfigPanel')

function renderSmartOrder(quantity: number) {
  useFlowWorkflowStore.setState({
    nodes: [
      {
        id: 'smart-order',
        type: 'smartOrder',
        position: { x: 0, y: 0 },
        data: {
          symbol: 'RELIANCE',
          exchange: 'NSE',
          action: 'BUY',
          quantity,
          positionSize: 0,
          product: 'MIS',
          priceType: 'MARKET',
        },
      },
    ],
    selectedNodeId: 'smart-order',
  })

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ConfigPanel />
      </QueryClientProvider>
    </MemoryRouter>
  )

  const field = screen.getByText('Quantity').parentElement?.querySelector('input')
  if (!field) throw new Error('SmartOrder quantity input was not rendered')
  return field
}

describe('SmartOrder quantity contract', () => {
  beforeEach(() => useFlowWorkflowStore.getState().resetWorkflow())

  it('renders and stores an explicit zero quantity', () => {
    const quantity = renderSmartOrder(0)

    expect(quantity).toHaveValue(0)
    expect(quantity).toHaveAttribute('min', '0')

    fireEvent.change(quantity, { target: { value: '2' } })
    fireEvent.change(quantity, { target: { value: '0' } })

    expect(useFlowWorkflowStore.getState().nodes[0].data.quantity).toBe(0)
  })
})
