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
import { type ReactElement, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LotSizeMap } from '@/api/flow'

const getSymbolLotSizes =
  vi.fn<(refs: { symbol: string; exchange: string }[]) => Promise<LotSizeMap>>()

vi.mock('@/api/flow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/flow')>()
  return { ...actual, getSymbolLotSizes: (...args: never[]) => getSymbolLotSizes(...args) }
})

/**
 * `hasVariableReference` is called once per render and is otherwise pure, which
 * makes it an honest render counter without touching the component.
 */
let renders = 0
vi.mock('@/lib/flow/marginPositions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/flow/marginPositions')>()
  return {
    ...actual,
    hasVariableReference: (raw: string) => {
      renders += 1
      return actual.hasVariableReference(raw)
    },
  }
})

const { MarginPositionsFields } = await import('./MarginPositionsFields')

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
}

function renderEditor(value: string, onChange = vi.fn()) {
  const ui: ReactElement = (
    <QueryClientProvider client={newClient()}>
      <MarginPositionsFields value={value} onChange={onChange} />
    </QueryClientProvider>
  )
  return { onChange, ...render(ui) }
}

/** Feeds onChange back into value, the way ConfigPanel does, so an edit
 * actually re-renders the editor with its new basket. */
function Controlled({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial)
  return <MarginPositionsFields value={value} onChange={setValue} />
}

function renderControlled(initial: string) {
  return render(
    <QueryClientProvider client={newClient()}>
      <Controlled initial={initial} />
    </QueryClientProvider>
  )
}

const settle = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

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
  renders = 0
  getSymbolLotSizes.mockReset()
  getSymbolLotSizes.mockResolvedValue({ 'NFO:NIFTY25AUG26FUT': 65 })
})

describe('lookup cost', () => {
  it('stops rendering once the basket has settled', async () => {
    // The regression: parsing inline produced a new legs array every render,
    // so the debounce rescheduled itself and the panel re-rendered on a 350 ms
    // heartbeat for as long as it stayed open.
    renderEditor(CLEAN_NFO_LEG)
    await screen.findByText(/130 units/)

    const settled = renders
    await settle(1200)

    expect(renders).toBe(settled)
  })

  it('does not re-issue a lookup when a non-symbol field is edited', async () => {
    renderControlled(CLEAN_NFO_LEG)
    const quantity = await screen.findByLabelText('Quantity (Lots)')
    await waitFor(() => expect(getSymbolLotSizes).toHaveBeenCalledTimes(1))

    await userEvent.clear(quantity)
    await userEvent.type(quantity, '3')
    await settle(600)

    // The contract set never changed, so nothing needed re-resolving.
    expect(getSymbolLotSizes).toHaveBeenCalledTimes(1)
  })

  it('asks only for the contract it has not resolved before', async () => {
    getSymbolLotSizes.mockImplementation(async (refs) =>
      Object.fromEntries(refs.map((r) => [`${r.exchange}:${r.symbol}`, 65]))
    )
    const first = JSON.parse(CLEAN_NFO_LEG)[0]
    renderControlled(JSON.stringify([first, { ...first, symbol: '' }]))

    await waitFor(() => expect(getSymbolLotSizes).toHaveBeenCalledTimes(1))
    expect(getSymbolLotSizes.mock.calls[0][0]).toHaveLength(1)

    await userEvent.type(screen.getAllByLabelText('Symbol')[1], 'BANKNIFTY25AUG26FUT')
    await waitFor(() => expect(getSymbolLotSizes).toHaveBeenCalledTimes(2))

    // The first leg was already cached, so only the new contract goes over the
    // wire. Before per-contract caching this refetched the whole basket.
    const second = getSymbolLotSizes.mock.calls[1][0]
    expect(second).toHaveLength(1)
    expect(second[0].symbol).toBe('BANKNIFTY25AUG26FUT')
  })
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

describe('a leg follows its segment', () => {
  /**
   * margin_service requires a product on every leg, so unlike a node this row
   * cannot store "not chosen yet" and let the exchange decide at run time. The
   * default is carried across on an exchange change instead - but only while
   * the leg is still sitting on the one its old exchange implied, so a product
   * the author actually picked survives the move.
   */
  async function moveExchange(user: ReturnType<typeof userEvent.setup>, to: string) {
    await user.click(screen.getByLabelText('Exchange'))
    await user.click(await screen.findByRole('option', { name: to }))
  }

  it('prices an untouched cash leg moved to NFO as a carry position', async () => {
    const user = userEvent.setup()
    renderControlled(NSE_LEG)

    await moveExchange(user, 'NFO')

    await waitFor(() => expect(screen.getByLabelText('Product').textContent).toBe('NRML'))
  })

  it('takes a derivative leg moved to cash back to intraday', async () => {
    const user = userEvent.setup()
    renderControlled(CLEAN_NFO_LEG)

    await moveExchange(user, 'NSE')

    await waitFor(() => expect(screen.getByLabelText('Product').textContent).toBe('MIS'))
  })

  it('leaves a product the author chose alone', async () => {
    const user = userEvent.setup()
    renderControlled(NSE_LEG.replace('"MIS"', '"CNC"'))

    await moveExchange(user, 'NFO')

    await waitFor(() => expect(screen.getByLabelText('Exchange').textContent).toBe('NFO'))
    expect(screen.getByLabelText('Product').textContent).toBe('CNC')
  })
})
