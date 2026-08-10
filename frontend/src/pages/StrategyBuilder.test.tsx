import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PortfolioEntry } from '@/api/strategy-portfolio'
import type { OptionChainResponse, OptionData } from '@/types/option-chain'
import StrategyBuilder from './StrategyBuilder'

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
  getExpiries: vi.fn(),
  getOptionChain: vi.fn(),
  getPortfolioEntry: vi.fn(),
  getUnderlyings: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: { post: mocks.apiPost },
}))

vi.mock('@/api/oi-profile', () => ({
  oiProfileApi: { getUnderlyings: mocks.getUnderlyings },
}))

vi.mock('@/api/option-chain', () => ({
  optionChainApi: {
    getExpiries: mocks.getExpiries,
    getOptionChain: mocks.getOptionChain,
  },
}))

vi.mock('@/api/strategy-portfolio', () => ({
  strategyPortfolioApi: {
    get: mocks.getPortfolioEntry,
    create: vi.fn(),
    update: vi.fn(),
  },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key' }),
}))

vi.mock('@/components/strategy-builder/PayoffChart', () => ({ PayoffChart: () => null }))
vi.mock('@/components/strategy-builder/PnLTab', () => ({ PnLTab: () => null }))
vi.mock('@/components/strategy-builder/StrategyChartTab', () => ({ default: () => null }))
vi.mock('@/components/strategy-builder/MultiStrikeOITab', () => ({ default: () => null }))
vi.mock('@/components/trading/ExecuteBasketDialog', () => ({ ExecuteBasketDialog: () => null }))
vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn() },
}))

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

function option(symbol: string, ltp: number): OptionData {
  return {
    symbol,
    label: symbol,
    ltp,
    bid: ltp - 0.5,
    ask: ltp + 0.5,
    bid_qty: 75,
    ask_qty: 75,
    open: ltp,
    high: ltp + 5,
    low: ltp - 5,
    prev_close: ltp - 1,
    volume: 1_000,
    oi: 2_000,
    lotsize: 75,
    tick_size: 0.05,
    implied_volatility: 12,
  }
}

function chainFixture(
  underlying: string,
  expiry: string,
  strike = underlying === 'RELIANCE' ? 2_500 : 24_600
): OptionChainResponse {
  return {
    status: 'success',
    underlying,
    underlying_symbol: underlying,
    underlying_exchange: underlying === 'SENSEX' ? 'BSE_INDEX' : 'NSE_INDEX',
    underlying_ltp: strike,
    underlying_prev_close: strike - 10,
    expiry_date: expiry,
    expiry_ts: 1_786_400_000,
    server_ts: 1_786_000_000,
    atm_strike: strike,
    forward_price: strike + 20,
    greeks_included: true,
    chain: [
      {
        strike,
        ce: option(`${underlying}${expiry}${strike}CE`, 125),
        pe: option(`${underlying}${expiry}${strike}PE`, 105),
      },
    ],
  }
}

function savedRelianceStrategy(): PortfolioEntry {
  return {
    id: 17,
    watchlist: 'simulation',
    name: 'Saved Reliance Call',
    exchange: 'NFO',
    underlying: 'RELIANCE',
    expiry: '18AUG26',
    notes: null,
    created_at: null,
    updated_at: null,
    legs: [
      {
        id: 'saved-leg',
        segment: 'OPTION',
        side: 'BUY',
        lots: 1,
        lotSize: 75,
        expiry: '18AUG26',
        strike: 2_500,
        optionType: 'CE',
        price: 125,
        iv: 12,
        active: true,
        symbol: 'RELIANCE18AUG262500CE',
      },
    ],
  }
}

function renderBuilder(route = '/strategybuilder') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <StrategyBuilder />
    </MemoryRouter>
  )
}

async function chooseExpiry(expiry: string) {
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Option expiry' }), {
    key: 'ArrowDown',
  })
  fireEvent.click(await screen.findByRole('option', { name: expiry }))
}

async function chooseUnderlying(underlying: string) {
  fireEvent.click(screen.getByRole('combobox', { name: 'Underlying' }))
  fireEvent.click(await screen.findByRole('option', { name: underlying }))
}

async function addOneLeg() {
  const add = await screen.findByRole('button', { name: /Add Buy/ })
  await waitFor(() => expect(add).toBeEnabled())
  fireEvent.click(add)
  await screen.findByRole('button', { name: 'Remove position' })
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  window.IntersectionObserver = class {
    readonly root = null
    readonly rootMargin = ''
    readonly thresholds = []
    disconnect() {}
    observe() {}
    takeRecords(): IntersectionObserverEntry[] {
      return []
    }
    unobserve() {}
  }
  window.ResizeObserver = class {
    disconnect() {}
    observe() {}
    unobserve() {}
  }
})

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getUnderlyings.mockResolvedValue({
    status: 'success',
    underlyings: ['NIFTY', 'BANKNIFTY', 'RELIANCE'],
  })
  mocks.getExpiries.mockImplementation(
    async (_apiKey: string, _symbol: string, _exchange: string, instrument: string) => ({
      status: 'success',
      data: instrument === 'futures' ? ['27AUG26'] : ['13AUG26', '18AUG26'],
    })
  )
  mocks.getOptionChain.mockImplementation(
    async (_apiKey: string, underlying: string, _exchange: string, expiry: string) =>
      chainFixture(underlying, expiry)
  )
  mocks.apiPost.mockImplementation(async (url: string) => {
    if (url === '/optiongreeks') {
      return { status: 200, data: { status: 'success', implied_volatility: 12 } }
    }
    if (url === '/syntheticfuture') {
      return { status: 200, data: { status: 'success', synthetic_future_price: 24_620 } }
    }
    if (url === '/margin') {
      return {
        status: 200,
        data: { status: 'success', data: { total_margin_required: 10_000 } },
      }
    }
    return { status: 200, data: { status: 'success' } }
  })
})

describe('StrategyBuilder identity orchestration', () => {
  it('disables Add immediately when expiry changes until the matching chain arrives', async () => {
    const nextChain = deferred<OptionChainResponse>()
    mocks.getOptionChain.mockImplementation(
      async (_apiKey: string, underlying: string, _exchange: string, expiry: string) =>
        expiry === '18AUG26' ? nextChain.promise : chainFixture(underlying, expiry)
    )

    renderBuilder()
    const add = await screen.findByRole('button', { name: /Add Buy/ })
    await waitFor(() => expect(add).toBeEnabled())
    fireEvent.click(add)
    await screen.findByRole('button', { name: 'Remove position' })

    await chooseExpiry('18AUG26')

    expect(screen.getByRole('button', { name: /Add Buy/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove position' })).toBeInTheDocument()

    await act(async () => {
      nextChain.resolve(chainFixture('NIFTY', '18AUG26'))
      await nextChain.promise
    })
    await waitFor(() => expect(screen.getByRole('button', { name: /Add Buy/ })).toBeEnabled())
  })

  it('keeps a controlled identity and legs on cancel, then clears legs and scenarios on acceptance', async () => {
    renderBuilder()
    await addOneLeg()
    const spotShift = screen.getAllByRole('slider')[0]
    fireEvent.change(spotShift, { target: { value: '5' } })
    expect(spotShift).toHaveValue('5')

    await chooseUnderlying('BANKNIFTY')
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Clear the current strategy')
    expect(
      screen.getByRole('combobox', { name: 'Underlying', hidden: true })
    ).toHaveTextContent('NIFTY')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('combobox', { name: 'Underlying' })).toHaveTextContent('NIFTY')
    expect(screen.getByRole('button', { name: 'Remove position' })).toBeInTheDocument()
    expect(screen.getAllByRole('slider')[0]).toHaveValue('5')

    await chooseUnderlying('BANKNIFTY')
    fireEvent.click(screen.getByRole('button', { name: 'Clear strategy' }))

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Underlying' })).toHaveTextContent('BANKNIFTY')
    )
    expect(screen.queryByRole('button', { name: 'Remove position' })).not.toBeInTheDocument()

    await addOneLeg()
    expect(screen.getAllByRole('slider')[0]).toHaveValue('0')
  })

  it('hydrates a saved non-default identity and legs before defaulting or fetch effects run', async () => {
    const portfolio = deferred<PortfolioEntry>()
    const underlyings = deferred<{ status: 'success'; underlyings: string[] }>()
    const optionExpiries = deferred<{ status: 'success'; data: string[] }>()
    const savedChain = deferred<OptionChainResponse>()
    mocks.getPortfolioEntry.mockReturnValue(portfolio.promise)
    mocks.getUnderlyings.mockReturnValue(underlyings.promise)
    mocks.getExpiries.mockImplementation(
      async (_apiKey: string, _symbol: string, _exchange: string, instrument: string) =>
        instrument === 'options'
          ? optionExpiries.promise
          : { status: 'success', data: ['27AUG26'] }
    )
    mocks.getOptionChain.mockReturnValue(savedChain.promise)

    renderBuilder('/strategybuilder?load=17')

    expect(mocks.getUnderlyings).not.toHaveBeenCalled()
    expect(mocks.getExpiries).not.toHaveBeenCalled()
    expect(mocks.getOptionChain).not.toHaveBeenCalled()

    await act(async () => {
      portfolio.resolve(savedRelianceStrategy())
      await portfolio.promise
    })
    await waitFor(() => expect(mocks.getUnderlyings).toHaveBeenCalledWith('NFO'))
    await waitFor(() => expect(mocks.getExpiries).toHaveBeenCalled())

    await act(async () => {
      underlyings.resolve({
        status: 'success',
        underlyings: ['NIFTY', 'BANKNIFTY', 'RELIANCE'],
      })
      optionExpiries.resolve({ status: 'success', data: ['13AUG26', '18AUG26'] })
      await Promise.all([underlyings.promise, optionExpiries.promise])
    })
    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalled())

    await act(async () => {
      savedChain.resolve(chainFixture('RELIANCE', '18AUG26'))
      await savedChain.promise
    })

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Underlying' })).toHaveTextContent('RELIANCE')
    )
    expect(screen.getByRole('combobox', { name: 'Option expiry' })).toHaveTextContent('18AUG26')
    expect(screen.getByRole('button', { name: 'Remove position' })).toBeInTheDocument()
    expect(screen.getByText('2500CE')).toBeInTheDocument()
  })
})
