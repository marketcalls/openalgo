/**
 * The Margin Calculator's basket editor.
 *
 * Two behaviours here are load-bearing rather than cosmetic. Mounting must
 * never write to the node: the editor derives lots from a stored unit
 * quantity, and an earlier version rounded an irregular quantity on mount,
 * which changed what a saved workflow would execute just by opening its config
 * panel. And a failed lot-size lookup must not read as "this contract has no
 * lot size" - one is retryable, the other is a fact about the master contract.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LotSizeMap } from '@/api/flow'

const getSymbolLotSizes =
  vi.fn<(refs: { symbol: string; exchange: string }[]) => Promise<LotSizeMap>>()

vi.mock('@/api/flow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/flow')>()
  return { ...actual, getSymbolLotSizes: (...args: never[]) => getSymbolLotSizes(...args) }
})

const { MarginPositionsFields } = await import('./MarginPositionsFields')

function renderEditor(value: string, onChange = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const ui: ReactElement = (
    <QueryClientProvider client={client}>
      <MarginPositionsFields value={value} onChange={onChange} />
    </QueryClientProvider>
  )
  return { onChange, ...render(ui) }
}

/** One complete NFO leg of 100 units - deliberately not a multiple of 65. */
const IRREGULAR_NFO_LEG = JSON.stringify([
  {
    symbol: 'NIFTY25AUG26FUT',
    exchange: 'NFO',
    action: 'BUY',
    quantity: '100',
    product: 'NRML',
    pricetype: 'MARKET',
    price: '0',
  },
])

/** The same leg at a clean two lots. */
const CLEAN_NFO_LEG = IRREGULAR_NFO_LEG.replace('"100"', '"130"')

const NSE_LEG = JSON.stringify([
  {
    symbol: 'SBIN',
    exchange: 'NSE',
    action: 'BUY',
    quantity: '10',
    product: 'MIS',
    pricetype: 'MARKET',
    price: '0',
  },
])

beforeEach(() => {
  getSymbolLotSizes.mockReset()
  getSymbolLotSizes.mockResolvedValue({ 'NFO:NIFTY25AUG26FUT': 65 })
})

describe('basket editing', () => {
  it('shows an empty state and can add the first position', async () => {
    const { onChange } = renderEditor('')
    expect(screen.getByText(/no positions yet/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /add position/i }))

    const written = JSON.parse(onChange.mock.calls[0][0])
    expect(written).toHaveLength(1)
    expect(written[0]).toMatchObject({
      exchange: 'NSE',
      action: 'BUY',
      product: 'MIS',
      pricetype: 'MARKET',
      quantity: '1',
      price: '0',
    })
  })

  it('renders a lone object as a one-leg basket', () => {
    renderEditor('{"symbol":"SBIN","exchange":"NSE"}')
    expect(screen.getByText('Leg 1')).toBeInTheDocument()
  })

  it('writes the edited symbol upper-cased', async () => {
    const { onChange } = renderEditor(NSE_LEG)
    await userEvent.type(screen.getByLabelText('Symbol'), 'X')
    expect(JSON.parse(onChange.mock.calls.at(-1)?.[0])[0].symbol).toBe('SBINX')
  })

  it('removes one leg without disturbing the others', async () => {
    const two = JSON.stringify([
      ...JSON.parse(NSE_LEG),
      { ...JSON.parse(NSE_LEG)[0], symbol: 'INFY' },
    ])
    const { onChange } = renderEditor(two)

    await userEvent.click(screen.getByRole('button', { name: /remove leg 1/i }))

    const remaining = JSON.parse(onChange.mock.calls.at(-1)?.[0])
    expect(remaining).toHaveLength(1)
    expect(remaining[0].symbol).toBe('INFY')
  })

  it('keeps unknown properties across an edit', async () => {
    const withExtra = JSON.stringify([{ ...JSON.parse(NSE_LEG)[0], broker_hint: 'keep-me' }])
    const { onChange } = renderEditor(withExtra)

    await userEvent.type(screen.getByLabelText('Symbol'), 'X')

    expect(JSON.parse(onChange.mock.calls.at(-1)?.[0])[0].broker_hint).toBe('keep-me')
  })
})

describe('JSON mode', () => {
  it('stays in JSON mode for malformed input and preserves the text', () => {
    const raw = '[{"symbol":]'
    renderEditor(raw)
    const editor = screen.getByLabelText('Positions JSON') as HTMLTextAreaElement
    expect(editor).toBeInTheDocument()
    expect(editor.value).toBe(raw)
  })

  it('refuses field mode for a basket holding a non-object', () => {
    renderEditor('[{"symbol":"SBIN"}, 42]')
    expect(screen.getByText(/every position must be a json object/i)).toBeInTheDocument()
  })

  it('locks a {{variable}} basket to JSON even when the template parses', async () => {
    // Valid JSON, so nothing but the variable check keeps the field editor
    // shut. In fields this would report {{qty}} as an invalid quantity and
    // drop the reference on the next unrelated edit.
    const templated = JSON.stringify([
      { ...JSON.parse(NSE_LEG)[0], quantity: '{{qty}}', pricetype: '{{pt}}', price: '{{px}}' },
    ])
    const { onChange } = renderEditor(templated)

    const editor = screen.getByLabelText('Positions JSON') as HTMLTextAreaElement
    expect(editor.value).toBe(templated)
    expect(screen.queryByLabelText('Symbol')).not.toBeInTheDocument()
    expect(screen.getByText(/interpolated before the JSON is parsed/i)).toBeInTheDocument()

    // The switch must be refused, not silently ineffective.
    const toggle = screen.getByRole('button', { name: /use fields/i })
    expect(toggle).toBeDisabled()
    await userEvent.click(toggle)
    expect(screen.getByLabelText('Positions JSON')).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('lot-based quantity', () => {
  it('shows NFO quantity in lots and stores units', async () => {
    const { onChange } = renderEditor(CLEAN_NFO_LEG)

    const quantity = await screen.findByLabelText('Quantity (Lots)')
    expect((quantity as HTMLInputElement).value).toBe('2')
    expect(screen.getByText(/130 units/)).toBeInTheDocument()

    await userEvent.clear(quantity)
    await userEvent.type(quantity, '3')

    expect(JSON.parse(onChange.mock.calls.at(-1)?.[0])[0].quantity).toBe('195')
  })

  it('keeps NSE quantity in units and never looks up a lot size', async () => {
    renderEditor(NSE_LEG)
    expect(screen.getByLabelText('Quantity')).toBeInTheDocument()
    await waitFor(() => expect(getSymbolLotSizes).not.toHaveBeenCalled())
  })

  it('falls back to units when the contract has no lot size', async () => {
    getSymbolLotSizes.mockResolvedValue({ 'NFO:NIFTY25AUG26FUT': null })
    renderEditor(CLEAN_NFO_LEG)
    expect(await screen.findByText(/no lot size is available/i)).toBeInTheDocument()
  })

  it('issues one request for a basket, not one per leg', async () => {
    const legs = Array.from({ length: 8 }, (_, i) => ({
      ...JSON.parse(CLEAN_NFO_LEG)[0],
      symbol: `NIFTY25AUG26FUT${i}`,
    }))
    getSymbolLotSizes.mockResolvedValue(
      Object.fromEntries(legs.map((l) => [`NFO:${l.symbol}`, 65]))
    )

    renderEditor(JSON.stringify(legs))

    await waitFor(() => expect(getSymbolLotSizes).toHaveBeenCalledTimes(1))
    expect(getSymbolLotSizes.mock.calls[0][0]).toHaveLength(8)
  })
})

describe('lookup failure is distinct from missing metadata', () => {
  it('offers a retry rather than claiming the contract has no lot size', async () => {
    getSymbolLotSizes.mockRejectedValue(new Error('boom'))
    renderEditor(CLEAN_NFO_LEG)

    expect(await screen.findByText(/lot-size lookup failed/i)).toBeInTheDocument()
    expect(screen.queryByText(/no lot size is available/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })
})

describe('mounting never rewrites stored data', () => {
  it('leaves an irregular saved quantity alone and offers to round it', async () => {
    const { onChange } = renderEditor(IRREGULAR_NFO_LEG)

    const round = await screen.findByRole('button', { name: /round to 2 lots/i })
    expect(screen.getByText(/100 units is not a multiple of the 65-unit lot/i)).toBeInTheDocument()
    // The regression this guards: opening the panel must not touch the node.
    expect(onChange).not.toHaveBeenCalled()

    await userEvent.click(round)
    expect(JSON.parse(onChange.mock.calls.at(-1)?.[0])[0].quantity).toBe('130')
  })

  it('does not write on mount for a clean basket either', async () => {
    const { onChange } = renderEditor(CLEAN_NFO_LEG)
    await screen.findByText(/130 units/)
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('validation feedback', () => {
  it('flags a missing symbol and marks the control invalid', () => {
    const blank = JSON.stringify([{ ...JSON.parse(NSE_LEG)[0], symbol: '' }])
    renderEditor(blank)
    expect(screen.getByText('Symbol is required')).toBeInTheDocument()
    expect(screen.getByLabelText('Symbol')).toHaveAttribute('aria-invalid', 'true')
  })

  it('requires a positive price on a LIMIT leg', () => {
    const limit = JSON.stringify([{ ...JSON.parse(NSE_LEG)[0], pricetype: 'LIMIT', price: '0' }])
    renderEditor(limit)
    expect(screen.getByText(/LIMIT needs a price above 0/)).toBeInTheDocument()
  })

  it('requires a trigger price on an SL-M leg', () => {
    const slm = JSON.stringify([
      { ...JSON.parse(NSE_LEG)[0], pricetype: 'SL-M', trigger_price: '0' },
    ])
    renderEditor(slm)
    expect(screen.getByText(/SL-M needs a trigger price above 0/)).toBeInTheDocument()
  })
})

describe('accessibility', () => {
  it('gives every control an accessible name', async () => {
    renderEditor(CLEAN_NFO_LEG)
    await screen.findByLabelText('Quantity (Lots)')
    for (const name of ['Symbol', 'Exchange', 'Product', 'Price type']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Remove leg 1' })).toBeInTheDocument()
  })

  it('exposes the selected action as a pressed toggle', () => {
    renderEditor(NSE_LEG)
    expect(screen.getByRole('button', { name: 'BUY' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'SELL' })).toHaveAttribute('aria-pressed', 'false')
  })
})
