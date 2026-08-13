import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { ListedOptionChainResponse, ResolvedLegMarket } from '@/lib/strategyContracts'
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

function liveChain(
  overrides: {
    ltp?: number
    iv?: number
    expiryTs?: number
    lotSize?: number
    tickSize?: number
    underlying?: number
    forward?: number
  } = {}
): ListedOptionChainResponse {
  const ltp = overrides.ltp ?? 125
  const underlying = overrides.underlying ?? 24_600
  return {
    status: 'success',
    exchange: 'NFO',
    underlying: 'NIFTY',
    underlying_symbol: 'NIFTY',
    underlying_exchange: 'NSE_INDEX',
    underlying_ltp: underlying,
    underlying_prev_close: 24_500,
    expiry_date: '13AUG26',
    expiry_ts: overrides.expiryTs ?? 1_786_400_000,
    server_ts: 1_786_000_000,
    atm_strike: 24_600,
    forward_price: overrides.forward ?? 24_620,
    greeks_included: true,
    chain: [
      {
        strike: 24_600,
        ce: {
          symbol: 'NIFTY13AUG2624600CE',
          label: 'NIFTY13AUG2624600CE',
          ltp,
          bid: ltp - 0.5,
          ask: ltp + 0.5,
          bid_qty: 75,
          ask_qty: 75,
          open: ltp - 2,
          high: ltp + 5,
          low: ltp - 5,
          prev_close: ltp - 1,
          volume: 1_000,
          oi: 2_000,
          lotsize: overrides.lotSize ?? 75,
          tick_size: overrides.tickSize ?? 0.05,
          implied_volatility: overrides.iv ?? 12,
          delta: 0.6,
          gamma: 0.02,
          theta: -3,
          vega: 5,
        },
        pe: null,
      },
    ],
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
    liveChain: null,
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
  it('refreshes matching same-expiry market metadata without resolving the selection again', async () => {
    const resolveContract = vi.fn(async () => market())
    const onAdd = vi.fn()
    const initialProps = props({ resolveContract, onAdd, liveChain: liveChain() })
    const view = render(<ManualLegBuilder {...initialProps} />)
    await screen.findByText('NIFTY13AUG2624600CE')
    expect(resolveContract).toHaveBeenCalledTimes(1)

    view.rerender(
      <ManualLegBuilder
        {...initialProps}
        liveChain={liveChain({
          ltp: 140,
          iv: 18,
          expiryTs: 1_786_500_000,
          lotSize: 65,
          tickSize: 0.1,
          underlying: 24_610,
          forward: 24_635,
        })}
      />
    )

    expect(await screen.findAllByText('₹140.00')).toHaveLength(2)
    expect(screen.getByText('NIFTY13AUG2624600CE')).toBeVisible()
    expect(resolveContract).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'NIFTY13AUG2624600CE',
        price: 140,
        marketPrice: 140,
        iv: 18,
        expiryTs: 1_786_500_000,
        lotSize: 65,
        tickSize: 0.1,
        referenceUnderlying: 24_610,
        forwardPrice: 24_635,
        greeks: { delta: 0.6, gamma: 0.02, theta: -3, vega: 5 },
      })
    )
  })

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

  it('replaces header-chain strikes with the selected far expiry chain', async () => {
    const farChain = liveChain()
    farChain.expiry_date = '18AUG26'
    farChain.atm_strike = 24_750
    farChain.chain = [
      {
        strike: 24_750,
        ce: {
          ...farChain.chain[0].ce!,
          symbol: 'NIFTY18AUG2624750CE',
        },
        pe: null,
      },
    ]
    const resolveOptionChain = vi.fn(async (expiry: string) =>
      expiry === '18AUG26' ? farChain : liveChain()
    )
    const resolveContract = vi.fn(async (expiry: string, _segment: string, strike?: number) =>
      expiry === '18AUG26' && strike === 24_750
        ? market({ expiry, symbol: 'NIFTY18AUG2624750CE' })
        : market()
    )

    const builderProps = props({
      resolveContract,
      resolveOptionChain,
      liveChain: liveChain(),
      strikeStep: 50,
    })
    const view = render(<ManualLegBuilder {...builderProps} />)
    await screen.findByText('NIFTY13AUG2624600CE')
    await choose('Expiry', '18AUG26')

    expect(await screen.findByText('NIFTY18AUG2624750CE')).toBeVisible()
    expect(screen.getByRole('combobox', { name: 'Strike' })).toHaveTextContent('24750')
    expect(screen.getAllByText('ATM')).toHaveLength(2)

    expect(resolveOptionChain).toHaveBeenCalledTimes(1)
    view.rerender(<ManualLegBuilder {...builderProps} liveChain={liveChain({ ltp: 140 })} />)
    await act(async () => {})
    expect(resolveOptionChain).toHaveBeenCalledTimes(1)
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
            expiryTs: null,
            lotSize: 65,
            tickSize: 0.1,
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
      expect.objectContaining({
        symbol: 'NIFTY27AUG26FUT',
        expiry: '27AUG26',
        expiryTs: null,
        lotSize: 65,
        tickSize: 0.1,
        marketPrice: 25_142,
        price: 25_142,
      })
    )
  })
})
