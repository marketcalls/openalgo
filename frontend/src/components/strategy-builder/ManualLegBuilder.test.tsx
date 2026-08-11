import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { ResolvedLegMarket } from '@/lib/strategyContracts'
import { ManualLegBuilder, type ManualLegBuilderProps } from './ManualLegBuilder'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function market(overrides: Partial<ResolvedLegMarket> = {}): ResolvedLegMarket {
  return {
    exchange: 'NFO',
    symbol: 'NIFTY13AUG2624600CE',
    expiry: '13AUG26',
    expiryTs: 1_786_400_000,
    lotSize: 75,
    tickSize: 0.05,
    marketPrice: 125,
    iv: 12,
    forwardPrice: 24_620,
    referenceUnderlying: 24_600,
    greeks: { delta: 0.5, gamma: 0.01, theta: -2, vega: 4 },
    ...overrides,
  }
}

function props(overrides: Partial<ManualLegBuilderProps> = {}): ManualLegBuilderProps {
  return {
    expiries: ['13AUG26', '18AUG26'],
    futureExpiries: ['27AUG26'],
    chain: [
      {
        strike: 24_600,
        ce: null,
        pe: null,
      },
    ],
    selectedExpiry: '13AUG26',
    atmStrike: 24_600,
    resolveContract: vi.fn(async (expiry) => market({ expiry })),
    onAdd: vi.fn(),
    ...overrides,
  }
}

async function choose(selectName: string, optionName: string) {
  fireEvent.keyDown(screen.getByRole('combobox', { name: selectName }), { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: optionName }))
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

describe('ManualLegBuilder listed contracts', () => {
  it('renders and adds the canonical option returned for a far expiry', async () => {
    const onAdd = vi.fn()
    const resolveContract = vi.fn(async (expiry: string) =>
      expiry === '18AUG26'
        ? market({ symbol: 'NIFTY18AUG2624600CE', expiry, marketPrice: 225, iv: 18 })
        : market()
    )
    render(<ManualLegBuilder {...props({ resolveContract, onAdd })} />)

    await screen.findByText('NIFTY13AUG2624600CE')
    await choose('Expiry', '18AUG26')

    expect(await screen.findByText('NIFTY18AUG2624600CE')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        expiry: '18AUG26',
        symbol: 'NIFTY18AUG2624600CE',
        price: 225,
        marketPrice: 225,
      })
    )
  })

  it('keeps only the latest async contract and clears a missing selection', async () => {
    const first = deferred<ResolvedLegMarket | null>()
    const second = deferred<ResolvedLegMarket | null>()
    const resolveContract = vi
      .fn()
      .mockResolvedValueOnce(market())
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    render(<ManualLegBuilder {...props({ resolveContract })} />)
    await screen.findByText('NIFTY13AUG2624600CE')

    fireEvent.click(screen.getByRole('button', { name: 'PE' }))
    fireEvent.click(screen.getByRole('button', { name: 'CE' }))
    expect(screen.queryByText('NIFTY13AUG2624600CE')).not.toBeInTheDocument()

    await act(async () => second.resolve(null))
    expect(await screen.findByText('Contract is not listed for this selection')).toBeVisible()
    expect(screen.getByRole('button', { name: /Add Buy/ })).toBeDisabled()

    await act(async () => first.resolve(market({ symbol: 'STALE-PE', marketPrice: 91, iv: 14 })))
    await waitFor(() => expect(screen.queryByText('STALE-PE')).not.toBeInTheDocument())
    expect(screen.queryByText('NIFTY13AUG2624600CE')).not.toBeInTheDocument()
  })

  it('adds the exact listed and quoted future rather than an option-chain forward', async () => {
    const onAdd = vi.fn()
    const resolveContract = vi.fn(async (_expiry, segment) =>
      segment === 'FUTURE'
        ? market({
            symbol: 'NIFTY27AUG26FUT',
            expiry: '27AUG26',
            marketPrice: 25_142,
            iv: 0,
            forwardPrice: null,
            greeks: { delta: null, gamma: null, theta: null, vega: null },
          })
        : market()
    )
    render(<ManualLegBuilder {...props({ resolveContract, onAdd })} />)
    await screen.findByText('NIFTY13AUG2624600CE')

    await choose('Segment', 'Futures')
    expect(await screen.findByText('NIFTY27AUG26FUT')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: 'NIFTY27AUG26FUT', marketPrice: 25_142, price: 25_142 })
    )
  })
})
