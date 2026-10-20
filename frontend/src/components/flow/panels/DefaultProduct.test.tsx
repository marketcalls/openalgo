/**
 * What the config panel's Product control shows, and when it writes.
 *
 * The control read `nodeData.product || 'MIS'` on every node, so a node placed
 * on NFO or MCX said MIS - and, because the node also shipped a stored MIS,
 * meant it. The segment was invisible: the author had to notice and fix each
 * node by hand, and the ones they missed auto-squared-off at the close.
 *
 * The control now shows what the run will send: the node's own product if it
 * has one, otherwise the default its exchange implies. It still writes nothing
 * until the author actually picks, which is what lets changing the exchange
 * move the default with it - and what stops a shown value from being mistaken
 * for a chosen one.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'

vi.mock('@/api/flow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/flow')>()
  return {
    ...actual,
    getIndexSymbolsLotSizes: vi.fn(async () => []),
    getWebhookInfo: vi.fn(async () => null),
    getOptionStrikes: vi.fn(async () => {
      throw new Error('not needed here')
    }),
  }
})

const { ConfigPanel } = await import('./ConfigPanel')

function mount(type: string, data: Record<string, unknown>) {
  useFlowWorkflowStore.setState({
    nodes: [{ id: 'n1', type, position: { x: 0, y: 0 }, data }],
    selectedNodeId: 'n1',
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ConfigPanel />
      </QueryClientProvider>
    </MemoryRouter>
  )
}

/** The Product select's trigger, read the way a user reads it. */
function productControl(): HTMLElement {
  const label = screen.getByText('Product')
  const trigger = label.parentElement?.querySelector('button')
  if (!trigger) throw new Error('Product control was not rendered')
  return trigger
}

const storedProduct = () => useFlowWorkflowStore.getState().nodes[0].data.product

/** Change the node's exchange the way the panel offers it. */
function chooseExchange(value: string) {
  const trigger = screen.getByText('Exchange').parentElement?.querySelector('button')
  if (!trigger) throw new Error('Exchange control was not rendered')
  fireEvent.click(trigger)
  fireEvent.click(within(screen.getByRole('listbox')).getByText(value))
}

beforeEach(() => useFlowWorkflowStore.getState().resetWorkflow())

describe('a node that names a symbol', () => {
  it.each([
    ['NSE', 'MIS'],
    ['BSE', 'MIS'],
    ['NFO', 'NRML'],
    ['BFO', 'NRML'],
    ['MCX', 'NRML'],
    ['CDS', 'NRML'],
  ])('shows %s orders as %s', (exchange, expected) => {
    mount('placeOrder', { symbol: 'X', exchange, quantity: 1 })

    expect(productControl().textContent).toBe(expected)
  })

  it('shows the product the author chose, whatever the segment implies', () => {
    /** Intraday on a derivative is a legitimate thing to ask for. */
    mount('placeOrder', { symbol: 'X', exchange: 'NFO', quantity: 1, product: 'MIS' })

    expect(productControl().textContent).toBe('MIS')
  })

  it('leaves an untouched node storing nothing, so its exchange still decides', () => {
    mount('placeOrder', { symbol: 'X', exchange: 'NSE', quantity: 1 })

    expect(storedProduct()).toBeUndefined()
  })

  it('follows the exchange when the author changes the exchange', () => {
    /** The point of storing nothing: moving a half-built node to NFO moves its
     * product too, rather than leaving intraday behind to be noticed later. */
    mount('placeOrder', { symbol: 'X', exchange: 'NSE', quantity: 1 })
    expect(productControl().textContent).toBe('MIS')

    chooseExchange('NFO')

    expect(productControl().textContent).toBe('NRML')
    expect(storedProduct()).toBeUndefined()
  })

  it('stops following once the author picks', () => {
    mount('placeOrder', { symbol: 'X', exchange: 'NSE', quantity: 1, product: 'CNC' })

    chooseExchange('NFO')

    expect(productControl().textContent).toBe('CNC')
  })
})

describe('an options node', () => {
  it.each(['optionsOrder', 'optionsMultiOrder'])('carries, whatever %s quotes on', (type) => {
    /** `exchange` on these names where the *underlying* is quoted - NSE_INDEX -
     * so following it would default every index option to intraday. */
    mount(type, { underlying: 'NIFTY', exchange: 'NSE_INDEX', quantity: 1, strategy: 'straddle' })

    expect(productControl().textContent).toBe('NRML')
  })
})

describe('a basket', () => {
  it('decides per row rather than blanket', () => {
    /** One basket can hold an NSE row and an MCX row; a single product would be
     * wrong for at least one of them. */
    mount('basketOrder', { orders: 'SBIN,NSE,BUY,1\nGOLDM,MCX,BUY,1' })

    expect(productControl().textContent).toBe('By row exchange')
    expect(storedProduct()).toBeUndefined()
  })

  it('shows a blanket product once one is chosen', () => {
    mount('basketOrder', { orders: 'SBIN,NSE,BUY,1', product: 'NRML' })

    expect(productControl().textContent).toBe('NRML')
  })

  it('clears the node product when the author goes back to per row', () => {
    /** Writing an empty string instead would reach the executor as a product
     * that failed to resolve, which it refuses rather than guesses. */
    mount('basketOrder', { orders: 'SBIN,NSE,BUY,1', product: 'NRML' })

    fireEvent.click(productControl())
    fireEvent.click(screen.getByText('By row exchange'))

    expect(storedProduct()).toBeUndefined()
    expect(JSON.parse(JSON.stringify({ data: { product: storedProduct() } }))).toEqual({ data: {} })
  })
})
