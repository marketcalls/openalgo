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

describe('custom options common pricing contract', () => {
  beforeEach(() => useFlowWorkflowStore.getState().resetWorkflow())

  it('explains inheritance and persists the common price fields', () => {
    useFlowWorkflowStore.setState({
      nodes: [
        {
          id: 'custom-options',
          type: 'optionsMultiOrder',
          position: { x: 0, y: 0 },
          data: {
            strategy: 'custom',
            underlying: 'NIFTY',
            exchange: 'NSE_INDEX',
            expiryType: 'current_week',
            legs: [],
            action: 'SELL',
            quantity: 1,
            product: 'MIS',
            priceType: 'SL',
            price: 100,
            triggerPrice: 99,
          },
        },
      ],
      selectedNodeId: 'custom-options',
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

    expect(
      screen.getByText(/custom legs inherit these common product and price fields/i)
    ).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '101.5' } })
    fireEvent.change(screen.getByLabelText('Trigger Price'), { target: { value: '100.5' } })

    expect(useFlowWorkflowStore.getState().nodes[0].data.price).toBe(101.5)
    expect(useFlowWorkflowStore.getState().nodes[0].data.triggerPrice).toBe(100.5)
  })
})

describe('imported basket editing contract', () => {
  beforeEach(() => useFlowWorkflowStore.getState().resetWorkflow())

  it('preserves an imported list until the user explicitly converts it to CSV', () => {
    const importedOrders = [
      {
        symbol: 'SBIN',
        exchange: 'NSE',
        action: 'BUY',
        quantity: 2,
        product: 'CNC',
        pricetype: 'LIMIT',
        price: 100,
      },
      { symbol: 'INFY', exchange: 'NSE', action: 'SELL', quantity: 1 },
    ]
    useFlowWorkflowStore.setState({
      nodes: [
        {
          id: 'basket',
          type: 'basketOrder',
          position: { x: 0, y: 0 },
          data: {
            basketName: 'Imported',
            orders: importedOrders,
            product: 'MIS',
            priceType: 'MARKET',
          },
        },
      ],
      selectedNodeId: 'basket',
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

    const textarea = screen
      .getByText('Orders (SYMBOL,EXCHANGE,ACTION,QTY)')
      .parentElement?.querySelector('textarea')
    if (!textarea) throw new Error('Basket orders textarea was not rendered')

    expect(textarea).toHaveValue(JSON.stringify(importedOrders, null, 2))
    expect(textarea).toHaveAttribute('readonly')
    expect(useFlowWorkflowStore.getState().nodes[0].data.orders).toEqual(importedOrders)

    fireEvent.click(screen.getByRole('button', { name: /convert imported orders to csv/i }))

    expect(useFlowWorkflowStore.getState().nodes[0].data.orders).toBe(
      'SBIN,NSE,BUY,2\nINFY,NSE,SELL,1'
    )
    expect(textarea).not.toHaveAttribute('readonly')
  })
})

describe('the options node strike offset', () => {
  beforeEach(() => useFlowWorkflowStore.getState().resetWorkflow())

  function renderOptionsOrder(offset: string) {
    useFlowWorkflowStore.setState({
      nodes: [
        {
          id: 'options-order',
          type: 'optionsOrder',
          position: { x: 0, y: 0 },
          data: {
            underlying: 'NIFTY',
            exchange: 'NSE_INDEX',
            expiryType: 'current_week',
            offset,
            optionType: 'PE',
            action: 'SELL',
            quantity: 1,
            priceType: 'MARKET',
          },
        },
      ],
      selectedNodeId: 'options-order',
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

    const trigger = screen.getByText('Strike Offset').parentElement?.querySelector('button')
    if (!trigger) throw new Error('Strike Offset control was not rendered')
    return trigger
  }

  it('shows a far offset the node already stores', () => {
    /** This control listed six offsets - ATM, ITM1, ITM2, OTM1, OTM2, OTM3 -
     * directly beneath its own hint promising ITM1-ITM50 and OTM1-OTM50. An
     * imported OTM12 leg had nothing to render and the trigger came up empty. */
    expect(renderOptionsOrder('OTM12').textContent).toContain('OTM12')
  })

  it('offers out to the same window the strike picker uses', () => {
    /** Not the executor's full ITM50/OTM50: an offset further out than the
     * chain endpoint returns names a contract the panel cannot show. A leg
     * already storing one is kept by the test above. */
    fireEvent.click(renderOptionsOrder('ATM'))
    const offered = screen.getAllByRole('option').map((option) => option.textContent)

    expect(offered).toContain('OTM12')
    expect(offered).toContain('OTM25')
    expect(offered).toContain('ITM25')
    expect(offered).not.toContain('OTM26')
  })
})
