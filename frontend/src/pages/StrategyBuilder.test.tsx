import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PortfolioEntry } from '@/api/strategy-portfolio'
import { useBrokerStore } from '@/stores/brokerStore'
import type { OptionChainResponse, OptionData } from '@/types/option-chain'
import StrategyBuilder from './StrategyBuilder'

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
  fetchRequests: [] as Array<{ url: string; body: Record<string, unknown> }>,
  marketData: new Map(),
  marketConnected: false,
  marketAuthenticated: false,
  marketPaused: false,
  marketConnectionEpoch: 0,
  marketSubscriptions: [] as Array<Array<{ symbol: string; exchange: string }>>,
  getExpiries: vi.fn(),
  getOptionChain: vi.fn(),
  getFutures: vi.fn(),
  getPortfolioEntry: vi.fn(),
  getUnderlyings: vi.fn(),
  strategyChartProps: [] as Array<Record<string, unknown>>,
  multiStrikeOIProps: [] as Array<Record<string, unknown>>,
  broker: null as string | null,
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

vi.mock('@/api/scalping', () => ({
  scalpingApi: { futures: mocks.getFutures },
}))

vi.mock('@/api/strategy-portfolio', () => ({
  strategyPortfolioApi: {
    get: mocks.getPortfolioEntry,
    create: vi.fn(),
    update: vi.fn(),
  },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({
    apiKey: 'test-api-key',
    user: { broker: mocks.broker },
  }),
}))

vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: ({ symbols }: { symbols: Array<{ symbol: string; exchange: string }> }) => {
    mocks.marketSubscriptions.push(symbols)
    return {
      data: mocks.marketData,
      isConnected: mocks.marketConnected,
      isAuthenticated: mocks.marketAuthenticated,
      isPaused: mocks.marketPaused,
      connectionEpoch: mocks.marketConnectionEpoch,
    }
  },
}))

vi.mock('@/components/strategy-builder/PayoffChart', () => ({ PayoffChart: () => null }))
vi.mock('@/components/strategy-builder/PnLTab', () => ({ PnLTab: () => null }))
vi.mock('@/components/strategy-builder/StrategyChartTab', () => ({
  default: (props: Record<string, unknown>) => {
    mocks.strategyChartProps.push(props)
    return null
  },
}))
vi.mock('@/components/strategy-builder/MultiStrikeOITab', () => ({
  default: (props: Record<string, unknown>) => {
    mocks.multiStrikeOIProps.push(props)
    return null
  },
}))
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

async function chooseExchange(exchange: string) {
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Derivative exchange' }), {
    key: 'ArrowDown',
  })
  fireEvent.click(await screen.findByRole('option', { name: exchange }))
}

const ASYNC_READY_TIMEOUT = 5_000
const SLOW_INTEGRATION_TEST_TIMEOUT = 15_000

async function waitForAddButton() {
  const add = await screen.findByRole('button', { name: /Add Buy/ })
  await waitFor(() => expect(add).toBeEnabled(), { timeout: ASYNC_READY_TIMEOUT })
  return add
}

async function waitForExecuteButton() {
  const execute = await screen.findByRole('button', { name: 'Execute' })
  await waitFor(() => expect(execute).toBeEnabled(), { timeout: ASYNC_READY_TIMEOUT })
  return execute
}

async function addOneLeg() {
  const add = await waitForAddButton()
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
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  mocks.fetchRequests.length = 0
  mocks.marketData = new Map()
  mocks.marketConnected = false
  mocks.marketAuthenticated = false
  mocks.marketPaused = false
  mocks.marketConnectionEpoch = 0
  mocks.marketSubscriptions.length = 0
  mocks.strategyChartProps.length = 0
  mocks.multiStrikeOIProps.length = 0
  mocks.broker = null
  useBrokerStore.setState({ capabilities: null, isLoaded: false })
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
  mocks.getFutures.mockResolvedValue({
    status: 'success',
    data: [
      {
        symbol: 'NIFTY27AUG26FUT',
        expiry: '27-AUG-26',
        lotsize: 65,
        tick_size: 0.05,
      },
    ],
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = init?.body ? JSON.parse(String(init.body)) : {}
      mocks.fetchRequests.push({ url, body })
      return new Response(
        JSON.stringify(chainFixture(String(body.underlying), String(body.expiry_date))),
        { status: 200 }
      )
    })
  )
  mocks.apiPost.mockImplementation(async (url: string) => {
    if (url === '/quotes') {
      return { status: 200, data: { status: 'success', data: { ltp: 25_142 } } }
    }
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

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function requests(path: string): unknown[] {
  const fetchCalls = mocks.fetchRequests.filter(({ url }) => url === path)
  const clientCalls = mocks.apiPost.mock.calls.filter(([url]) => `/api/v1${url}` === path)
  return [...fetchCalls, ...clientCalls]
}

describe('StrategyBuilder live request orchestration', () => {
  it('uses broker-reported NCDEX through the real hook and expiry request path', async () => {
    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'IN_stock',
        supported_exchanges: ['NCDEX'],
        leverage_config: false,
      },
      isLoaded: true,
    })
    mocks.getUnderlyings.mockResolvedValue({
      status: 'success',
      underlyings: ['GUARSEED'],
    })

    renderBuilder()

    await waitFor(() => expect(mocks.getUnderlyings).toHaveBeenCalledWith('NCDEX'))
    await waitFor(() =>
      expect(mocks.getExpiries).toHaveBeenCalledWith(
        'test-api-key',
        'GUARSEED',
        'NCDEX',
        'options'
      )
    )
    expect(screen.getByRole('combobox', { name: 'Derivative exchange' })).toHaveTextContent(
      'NCDEX'
    )
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Option expiry' })).toHaveTextContent(
        '13AUG26'
      )
    )
  })

  it('does not mount crypto auxiliary requests without a canonical chain reference', async () => {
    const user = userEvent.setup()
    const slowChain = deferred<Response>()
    let slowRequestStarted = false
    const cryptoChain = (expiry: string) => {
      const chain = chainFixture('BTC', expiry)
      chain.underlying_symbol = 'BTCUSDFUT'
      chain.underlying_exchange = 'CRYPTO'
      return chain
    }

    useBrokerStore.setState({
      capabilities: {
        broker_name: 'test',
        broker_type: 'crypto',
        supported_exchanges: ['CRYPTO'],
        leverage_config: false,
      },
      isLoaded: true,
    })
    mocks.getUnderlyings.mockResolvedValue({ status: 'success', underlyings: ['BTC'] })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body))
        if (body.expiry_date === '18AUG26') {
          slowRequestStarted = true
          return slowChain.promise
        }
        return new Response(JSON.stringify(cryptoChain(String(body.expiry_date))), { status: 200 })
      })
    )

    renderBuilder()
    await addOneLeg()
    await user.click(screen.getByRole('tab', { name: 'Strategy Chart' }))
    await waitFor(() => expect(mocks.strategyChartProps).not.toHaveLength(0))
    mocks.strategyChartProps.length = 0
    mocks.multiStrikeOIProps.length = 0

    await chooseExpiry('18AUG26')
    await waitFor(() => expect(slowRequestStarted).toBe(true))
    await user.click(screen.getByRole('tab', { name: 'Multi Strike OI' }))

    expect(
      mocks.strategyChartProps.some(
        (props) => !props.underlyingSymbol || !props.underlyingExchange
      )
    ).toBe(false)
    expect(
      mocks.multiStrikeOIProps.some(
        (props) => !props.underlyingSymbol || !props.underlyingExchange
      )
    ).toBe(false)

    await act(async () => {
      slowChain.resolve(
        new Response(JSON.stringify(cryptoChain('18AUG26')), {
          status: 200,
        })
      )
    })
    await waitFor(() =>
      expect(mocks.multiStrikeOIProps.at(-1)).toEqual(
        expect.objectContaining({
          underlyingSymbol: 'BTCUSDFUT',
          underlyingExchange: 'CRYPTO',
        })
      )
    )

    await user.click(screen.getByRole('tab', { name: 'Strategy Chart' }))
    await waitFor(() =>
      expect(mocks.strategyChartProps.at(-1)).toEqual(
        expect.objectContaining({
          underlyingSymbol: 'BTCUSDFUT',
          underlyingExchange: 'CRYPTO',
        })
      )
    )
  })

  it('passes the option-chain canonical reference to both auxiliary chart tabs', async () => {
    const user = userEvent.setup()
    const canonical = chainFixture('NIFTY', '13AUG26')
    canonical.underlying_symbol = 'NIFTY27AUG26FUT'
    canonical.underlying_exchange = 'NFO'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(canonical), { status: 200 }))
    )
    renderBuilder()
    await addOneLeg()

    await user.click(screen.getByRole('tab', { name: 'Strategy Chart' }))
    await waitFor(() => expect(mocks.strategyChartProps).not.toHaveLength(0))
    expect(mocks.strategyChartProps.at(-1)).toEqual(
      expect.objectContaining({
        underlyingSymbol: 'NIFTY27AUG26FUT',
        underlyingExchange: 'NFO',
      })
    )

    await user.click(screen.getByRole('tab', { name: 'Multi Strike OI' }))
    await waitFor(() => expect(mocks.multiStrikeOIProps).not.toHaveLength(0))
    expect(mocks.multiStrikeOIProps.at(-1)).toEqual(
      expect.objectContaining({
        underlyingSymbol: 'NIFTY27AUG26FUT',
        underlyingExchange: 'NFO',
      })
    )
  })

  it('formats currency output for the authenticated Delta Exchange broker', async () => {
    mocks.broker = 'deltaexchange'
    renderBuilder()
    await addOneLeg()

    expect(screen.getAllByText('$125.00').length).toBeGreaterThan(0)
  })

  it('adds a manual far-expiry option only from that expiry response', async () => {
    const farChain = chainFixture('NIFTY', '18AUG26')
    if (farChain.chain[0].ce) {
      farChain.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
      farChain.chain[0].ce.ltp = 225
    }
    mocks.getOptionChain.mockResolvedValue(farChain)
    renderBuilder()
    await screen.findByText('NIFTY13AUG2624600CE')

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Expiry' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '18AUG26' }))

    expect(await screen.findByText('NIFTY18AUG2624600CE')).toBeVisible()
    expect(mocks.getOptionChain).toHaveBeenCalledWith(
      'test-api-key',
      'NIFTY',
      'NSE_INDEX',
      '18AUG26',
      20,
      { withGreeks: true }
    )
    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))
    await screen.findByRole('button', { name: 'Remove position' })
    expect(screen.getAllByText('₹225.00').length).toBeGreaterThan(0)
  })

  it('does not let a delayed manual response override a newer active expiry chain', async () => {
    const user = userEvent.setup()
    const staleManualChain = deferred<OptionChainResponse>()
    mocks.getOptionChain.mockImplementation(async (_apiKey, underlying, _exchange, expiry) => {
      if (expiry === '18AUG26') return staleManualChain.promise
      return chainFixture(underlying, expiry)
    })
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      mocks.fetchRequests.push({ url, body })
      const response = chainFixture(body.underlying, body.expiry_date)
      if (body.expiry_date === '18AUG26') response.underlying_ltp = 24_650
      return new Response(JSON.stringify(response), { status: 200 })
    })

    renderBuilder()
    await screen.findByText('NIFTY13AUG2624600CE')

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Expiry' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '18AUG26' }))
    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalledTimes(1))

    await chooseExpiry('18AUG26')
    await screen.findByText('24650.00')

    const staleResponse = chainFixture('NIFTY', '18AUG26')
    if (staleResponse.chain[0].ce) {
      staleResponse.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
      staleResponse.chain[0].ce.ltp = 225
      staleResponse.chain[0].ce.implied_volatility = 99
      staleResponse.chain[0].ce.delta = 0.01
    }
    await act(async () => {
      staleManualChain.resolve(staleResponse)
      await staleManualChain.promise
    })

    const add = await waitForAddButton()
    fireEvent.click(add)
    await screen.findByRole('button', { name: 'Remove position' })
    expect(screen.getAllByText('₹125.00').length).toBeGreaterThan(0)
    expect(screen.queryByText('₹225.00')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    const rows = await screen.findAllByRole('row')
    const row = rows.find((item) => item.textContent?.includes('24600CE'))
    expect(row).toBeDefined()
    expect(row).not.toHaveTextContent('99.00')
  })

  it('adds the exact listed futures contract at its own quote', async () => {
    renderBuilder()
    await waitForAddButton()

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Segment' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Futures' }))

    expect(await screen.findByText('NIFTY27AUG26FUT')).toBeVisible()
    expect(mocks.getFutures).toHaveBeenCalledWith('NIFTY', 'NFO')
    expect(mocks.apiPost).toHaveBeenCalledWith('/quotes', {
      apikey: 'test-api-key',
      symbol: 'NIFTY27AUG26FUT',
      exchange: 'NFO',
    })

    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))
    await screen.findByRole('button', { name: 'Remove position' })
    expect(screen.getAllByText('₹25142.00').length).toBeGreaterThan(0)
  })

  it('does not re-fetch a selected far-expiry option when the active chain streams a tick', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    const view = renderBuilder()
    await screen.findByText('NIFTY13AUG2624600CE')

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Expiry' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '18AUG26' }))
    expect(await screen.findByText('NIFTY18AUG2624600CE')).toBeVisible()
    expect(mocks.getOptionChain).toHaveBeenCalledTimes(1)

    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_610 },
          lastUpdate: Date.now(),
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )

    await screen.findByText('Live')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('NIFTY18AUG2624600CE')).toBeVisible()
    expect(mocks.getOptionChain).toHaveBeenCalledTimes(1)
  })

  it('refreshes the selected same-expiry manual quote without another contract request', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    const view = renderBuilder()
    await screen.findByText('NIFTY13AUG2624600CE')
    expect(mocks.getOptionChain).not.toHaveBeenCalled()

    mocks.marketData = new Map([
      [
        'NFO:NIFTY13AUG2624600CE',
        {
          data: { ltp: 140, bid_price: 139.5, ask_price: 140.5 },
          lastUpdate: Date.now(),
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_610 },
          lastUpdate: Date.now(),
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )

    await screen.findByText('Live')
    await waitFor(() => expect(screen.getAllByText('₹140.00').length).toBeGreaterThan(0))
    expect(screen.getByText('NIFTY13AUG2624600CE')).toBeVisible()
    expect(mocks.getOptionChain).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /Add Buy/ }))
    const remove = await screen.findByRole('button', { name: 'Remove position' })
    const position = remove.closest('li')
    expect(position).not.toBeNull()
    expect(within(position as HTMLElement).getByText('₹140.00')).toBeVisible()
  })

  it('does not re-fetch a selected future when the active option chain streams a tick', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    const view = renderBuilder()
    await waitForAddButton()

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Segment' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Futures' }))
    expect(await screen.findByText('NIFTY27AUG26FUT')).toBeVisible()
    expect(mocks.getFutures).toHaveBeenCalledTimes(1)

    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_611 },
          lastUpdate: Date.now(),
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )

    await screen.findByText('Live')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('NIFTY27AUG26FUT')).toBeVisible()
    expect(mocks.getFutures).toHaveBeenCalledTimes(1)
  })

  it('loads market state through one option-chain request without redundant snapshot calls', async () => {
    renderBuilder()

    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))
    await waitForAddButton()

    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.queryByText('Live')).not.toBeInTheDocument()
    expect(requests('/api/v1/syntheticfuture')).toHaveLength(0)
    expect(requests('/api/v1/optiongreeks')).toHaveLength(0)
    expect(requests('/api/v1/multioptiongreeks')).toHaveLength(0)
  })

  it('does not label an authenticated socket Live before its first stream tick', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1

    renderBuilder()
    await waitForAddButton()

    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.queryByText('Live')).not.toBeInTheDocument()
  })

  it('keeps recent REST-cached data Stale until an authenticated WebSocket tick arrives', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_605 },
          lastUpdate: Date.now(),
          updateSource: 'rest' as const,
        },
      ],
    ])

    const view = renderBuilder()
    await waitForAddButton()

    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.queryByText('Live')).not.toBeInTheDocument()

    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_606 },
          lastUpdate: Date.now() + 1,
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Live')).toBeInTheDocument())
    expect(screen.queryByText('Stale')).not.toBeInTheDocument()
  })

  it('requires a post-reconnect WebSocket tick before returning to Live', async () => {
    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_610 },
          lastUpdate: Date.now(),
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
        },
      ],
    ])

    const view = renderBuilder()
    await waitFor(() => expect(screen.getByText('Live')).toBeInTheDocument())

    mocks.marketConnected = false
    mocks.marketAuthenticated = false
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Stale')).toBeInTheDocument())

    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 2
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.queryByText('Live')).not.toBeInTheDocument()

    mocks.marketData = new Map([
      [
        'NSE_INDEX:NIFTY',
        {
          data: { ltp: 24_611 },
          lastUpdate: Date.now() + 1,
          updateSource: 'websocket' as const,
          connectionEpoch: 2,
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Live')).toBeInTheDocument())
  })

  it('does not repeat an unchanged margin request when support is confirmed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const firstMargin = deferred<{
      status: number
      data: { status: string; data: { total_margin_required: number } }
    }>()
    mocks.apiPost.mockImplementation(async (url: string) => {
      if (url === '/margin') return firstMargin.promise
      return { status: 200, data: { status: 'success' } }
    })

    renderBuilder()
    await addOneLeg()
    await waitFor(() => expect(requests('/api/v1/margin')).toHaveLength(1), { timeout: 2_000 })

    await act(async () => {
      firstMargin.resolve({
        status: 200,
        data: { status: 'success', data: { total_margin_required: 10_000 } },
      })
      await firstMargin.promise
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(550)
    })
    expect(requests('/api/v1/margin')).toHaveLength(1)
  })

  it('does not request margin for a hydrated zero-exit leg', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const saved = savedRelianceStrategy()
    saved.legs[0].exitPrice = 0
    mocks.getPortfolioEntry.mockResolvedValue(saved)

    renderBuilder('/strategybuilder?load=17')
    await screen.findByRole('button', { name: 'Remove position' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })

    expect(mocks.apiPost.mock.calls.filter(([url]) => url === '/margin')).toHaveLength(0)
  })

  it('immediately refetches the live chain when the page becomes visible again', async () => {
    renderBuilder()
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))

    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(2))
  })

  it('refreshes live market state without overwriting the leg entry price', async () => {
    const user = userEvent.setup()
    let ltp = 125
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      mocks.fetchRequests.push({ url, body })
      const response = chainFixture(body.underlying, body.expiry_date)
      response.underlying_ltp = ltp === 125 ? 24_600 : 24_700
      response.forward_price = ltp === 125 ? 24_620 : 24_670
      if (response.chain[0].ce) {
        response.chain[0].ce.ltp = ltp
        response.chain[0].ce.implied_volatility = ltp === 125 ? 12 : 20
        response.chain[0].ce.delta = ltp === 125 ? 0.5 : 0.6
        response.chain[0].ce.gamma = ltp === 125 ? 0.01 : 0.02
        response.chain[0].ce.theta = ltp === 125 ? -2 : -3
        response.chain[0].ce.vega = ltp === 125 ? 4 : 5
      }
      response.expiry_ts = null
      return new Response(JSON.stringify(response), { status: 200 })
    })

    renderBuilder()
    await addOneLeg()
    expect(screen.getAllByText('₹125.00').length).toBeGreaterThan(0)

    ltp = 175
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(2))
    await screen.findByText('24700.00')
    await screen.findByTitle('Current mark ₹175.00')

    expect(screen.getAllByText('₹125.00').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    const greekRows = await screen.findAllByRole('row')
    const positionRow = greekRows.find((row) => row.textContent?.includes('13AUG26 24600CE'))
    expect(positionRow).toBeDefined()
    expect(positionRow).toHaveTextContent('20.00')
    expect(positionRow).toHaveTextContent('45.00')
    expect(positionRow).toHaveTextContent('-225.00')
    expect(positionRow).toHaveTextContent('1.500000')
    expect(positionRow).toHaveTextContent('375.00')
  })

  it('keeps a newer derivative-exchange chain when the prior request resolves late', async () => {
    const oldExchangeChain = deferred<OptionChainResponse>()
    let requestCount = 0
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      mocks.fetchRequests.push({ url, body })
      requestCount += 1
      const response =
        requestCount === 1
          ? await oldExchangeChain.promise
          : chainFixture(body.underlying, body.expiry_date)
      return new Response(JSON.stringify(response), { status: 200 })
    })

    renderBuilder()
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))
    await chooseExchange('BFO')
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(2))
    await screen.findByText('24600.00')

    await act(async () => {
      oldExchangeChain.resolve(chainFixture('NIFTY', '13AUG26', 11_111))
      await oldExchangeChain.promise
    })

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('24600.00')).toBeInTheDocument()
    expect(screen.queryByText('11111.00')).not.toBeInTheDocument()
  })

  it('hydrates calendar legs from each expiry response with Greeks requested', async () => {
    const user = userEvent.setup()
    const farChain = chainFixture('NIFTY', '18AUG26')
    farChain.expiry_ts = 1_797_000_000
    farChain.server_ts = 1_786_000_100
    farChain.forward_price = 24_880
    farChain.underlying_ltp = 24_850
    if (farChain.chain[0].ce) {
      farChain.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
      farChain.chain[0].ce.ltp = 225
      farChain.chain[0].ce.implied_volatility = 33
      farChain.chain[0].ce.delta = 0.44
      farChain.chain[0].ce.gamma = 0.0012
      farChain.chain[0].ce.theta = -8
      farChain.chain[0].ce.vega = 9
      farChain.chain[0].ce.lotsize = 50
      farChain.chain[0].ce.tick_size = 0.1
    }
    mocks.getOptionChain.mockResolvedValue(farChain)

    renderBuilder()
    await waitForAddButton()
    fireEvent.click(screen.getByRole('button', { name: /Neutral/ }))
    fireEvent.click(screen.getByRole('button', { name: /Call Calendar/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add Strategy' }))

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Remove position' })).toHaveLength(2)
    )
    expect(mocks.getOptionChain).toHaveBeenCalledWith(
      'test-api-key',
      'NIFTY',
      'NSE_INDEX',
      '18AUG26',
      20,
      { withGreeks: true }
    )
    expect(screen.getAllByText('18AUG26').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹225.00').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    const greekRows = await screen.findAllByRole('row')
    const farGreekRow = greekRows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    expect(farGreekRow).toBeDefined()
    expect(farGreekRow).toHaveTextContent('33.00')
    expect(farGreekRow).toHaveTextContent('22.00')
    expect(farGreekRow).toHaveTextContent('-400.00')
    expect(farGreekRow).toHaveTextContent('0.060000')
    expect(farGreekRow).toHaveTextContent('450.00')
  })

  it('refreshes each calendar expiry from its own option-chain Greeks response', async () => {
    const user = userEvent.setup()
    const intervalSpy = vi.spyOn(window, 'setInterval')
    let farIv = 33
    let farDelta = 0.44
    mocks.getOptionChain.mockImplementation(
      async (_apiKey: string, underlying: string, _exchange: string, expiry: string) => {
        const response = chainFixture(underlying, expiry)
        if (expiry === '18AUG26' && response.chain[0].ce) {
          response.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
          response.chain[0].ce.ltp = farIv === 33 ? 225 : 245
          response.chain[0].ce.implied_volatility = farIv
          response.chain[0].ce.delta = farDelta
          response.chain[0].ce.gamma = farIv === 33 ? 0.0012 : 0.0015
          response.chain[0].ce.theta = farIv === 33 ? -8 : -9
          response.chain[0].ce.vega = farIv === 33 ? 9 : 10
        }
        return response
      }
    )

    renderBuilder()
    await waitForAddButton()
    fireEvent.click(screen.getByRole('button', { name: /Neutral/ }))
    fireEvent.click(screen.getByRole('button', { name: /Call Calendar/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add Strategy' }))

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Remove position' })).toHaveLength(2)
    )
    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalledTimes(1))
    expect(mocks.getOptionChain).toHaveBeenLastCalledWith(
      'test-api-key',
      'NIFTY',
      'NSE_INDEX',
      '18AUG26',
      20,
      { withGreeks: true }
    )

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    let rows = await screen.findAllByRole('row')
    let farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    const nearRow = rows.find((row) => row.textContent?.includes('13AUG26 24600CE'))
    expect(farRow).toHaveTextContent('33.00')
    expect(nearRow).not.toHaveTextContent('33.00')
    const initialFarGreeks = within(farRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
      .map((cell) => cell.textContent)
    const initialNearGreeks = within(nearRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
      .map((cell) => cell.textContent)
    expect(initialFarGreeks).not.toEqual(initialNearGreeks)

    farIv = 41
    farDelta = 0.52
    const supplementalTimer = intervalSpy.mock.calls
      .filter(([, delay]) => delay === 30_000)
      .at(-1)?.[0]
    expect(typeof supplementalTimer).toBe('function')
    act(() => {
      if (typeof supplementalTimer === 'function') supplementalTimer()
    })

    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalledTimes(2))
    rows = await screen.findAllByRole('row')
    farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    expect(farRow).toHaveTextContent('41.00')
    expect(farRow).not.toHaveTextContent('12.00')
    const refreshedFarGreeks = within(farRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
      .map((cell) => cell.textContent)
    expect(refreshedFarGreeks).toHaveLength(initialFarGreeks.length)
    refreshedFarGreeks.forEach((value, index) => {
      expect(value).not.toBe(initialFarGreeks[index])
    })

    farIv = 47
    farDelta = 0.57
    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalledTimes(3))
    rows = await screen.findAllByRole('row')
    farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    expect(farRow).toHaveTextContent('47.00')

    farIv = 53
    farDelta = 0.61
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))

    await waitFor(() => expect(mocks.getOptionChain).toHaveBeenCalledTimes(4))
    rows = await screen.findAllByRole('row')
    farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    expect(farRow).toHaveTextContent('53.00')
  }, SLOW_INTEGRATION_TEST_TIMEOUT)

  it('recalculates a supplemental-expiry leg from its exact WebSocket contract and parity ticks', async () => {
    const user = userEvent.setup()
    const farChain = chainFixture('NIFTY', '18AUG26')
    farChain.expiry_ts = 1_786_900_000
    farChain.server_ts = 1_786_000_000
    farChain.forward_price = 24_620
    farChain.atm_strike = 24_500
    if (farChain.chain[0].ce) {
      farChain.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
      farChain.chain[0].ce.ltp = 225
      farChain.chain[0].ce.implied_volatility = 33
      farChain.chain[0].ce.delta = 0.44
      farChain.chain[0].ce.gamma = 0.0012
      farChain.chain[0].ce.theta = -8
      farChain.chain[0].ce.vega = 9
    }
    if (farChain.chain[0].pe) {
      farChain.chain[0].pe.symbol = 'NIFTY18AUG2624600PE'
      farChain.chain[0].pe.ltp = 105
    }
    farChain.chain.push({
      strike: 24_500,
      ce: option('NIFTY18AUG2624500CE', 260),
      pe: option('NIFTY18AUG2624500PE', 140),
    })
    mocks.getOptionChain.mockResolvedValue(farChain)

    const view = renderBuilder()
    await waitForAddButton()
    fireEvent.click(screen.getByRole('button', { name: /Neutral/ }))
    fireEvent.click(screen.getByRole('button', { name: /Call Calendar/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add Strategy' }))
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Remove position' })).toHaveLength(2)
    )

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    let rows = await screen.findAllByRole('row')
    let farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    const initialGreeks = within(farRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
      .map((cell) => cell.textContent)

    mocks.marketConnected = true
    mocks.marketAuthenticated = true
    mocks.marketConnectionEpoch = 1
    mocks.marketData = new Map([
      [
        'NFO:NIFTY18AUG2624600CE',
        {
          exchange: 'NFO',
          symbol: 'NIFTY18AUG2624600CE',
          lastUpdate: 1_786_000_099_000,
          updateSource: 'rest' as const,
          data: { ltp: 999 },
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )
    rows = await screen.findAllByRole('row')
    farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    expect(
      within(farRow as HTMLElement)
        .getAllByRole('cell')
        .slice(1)
        .map((cell) => cell.textContent)
    ).toEqual(initialGreeks)

    mocks.marketData = new Map([
      [
        'NFO:NIFTY18AUG2624600CE',
        {
          exchange: 'NFO',
          symbol: 'NIFTY18AUG2624600CE',
          lastUpdate: 1_786_000_100_000,
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
          data: {
            ltp: 250,
            depth: {
              buy: [{ price: 249, quantity: 75 }],
              sell: [{ price: 251, quantity: 75 }],
            },
          },
        },
      ],
      [
        'NFO:NIFTY18AUG2624500CE',
        {
          exchange: 'NFO',
          symbol: 'NIFTY18AUG2624500CE',
          lastUpdate: 1_786_000_100_000,
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
          data: {
            ltp: 280,
            depth: {
              buy: [{ price: 279, quantity: 75 }],
              sell: [{ price: 281, quantity: 75 }],
            },
          },
        },
      ],
      [
        'NFO:NIFTY18AUG2624500PE',
        {
          exchange: 'NFO',
          symbol: 'NIFTY18AUG2624500PE',
          lastUpdate: 1_786_000_100_000,
          updateSource: 'websocket' as const,
          connectionEpoch: 1,
          data: {
            ltp: 130,
            depth: {
              buy: [{ price: 129, quantity: 75 }],
              sell: [{ price: 131, quantity: 75 }],
            },
          },
        },
      ],
    ])
    view.rerender(
      <MemoryRouter initialEntries={['/strategybuilder']}>
        <StrategyBuilder />
      </MemoryRouter>
    )

    await waitFor(() =>
      expect(
        mocks.marketSubscriptions.some(
          (symbols) =>
            symbols.some(
              (item) => item.exchange === 'NFO' && item.symbol === 'NIFTY18AUG2624600CE'
            ) &&
            symbols.some(
              (item) => item.exchange === 'NFO' && item.symbol === 'NIFTY18AUG2624500CE'
            ) &&
            symbols.some(
              (item) => item.exchange === 'NFO' && item.symbol === 'NIFTY18AUG2624500PE'
            )
        )
      ).toBe(true)
    )
    rows = await screen.findAllByRole('row')
    farRow = rows.find((row) => row.textContent?.includes('18AUG26 24600CE'))
    const liveGreeks = within(farRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
      .map((cell) => cell.textContent)
    expect(liveGreeks).toHaveLength(initialGreeks.length)
    liveGreeks.forEach((value, index) => {
      expect(value).not.toBe(initialGreeks[index])
    })
  }, SLOW_INTEGRATION_TEST_TIMEOUT)

  it('does not show a prior contract Greek snapshot after editing a calendar leg', async () => {
    const user = userEvent.setup()
    const farChain = chainFixture('NIFTY', '18AUG26')
    if (farChain.chain[0].ce) {
      farChain.chain[0].ce.symbol = 'NIFTY18AUG2624600CE'
      farChain.chain[0].ce.implied_volatility = 33
      farChain.chain[0].ce.delta = 0.44
      farChain.chain[0].ce.gamma = 0.0012
      farChain.chain[0].ce.theta = -8
      farChain.chain[0].ce.vega = 9
    }
    mocks.getOptionChain.mockResolvedValue(farChain)

    renderBuilder()
    await waitForAddButton()
    fireEvent.click(screen.getByRole('button', { name: /Neutral/ }))
    fireEvent.click(screen.getByRole('button', { name: /Call Calendar/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add Strategy' }))
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Edit position' })).toHaveLength(2)
    )

    await user.click(screen.getAllByRole('button', { name: 'Edit position' })[1])
    const dialog = await screen.findByRole('dialog', { name: 'Edit Position' })
    const optionType = within(dialog).getAllByRole('combobox')[2]
    fireEvent.keyDown(optionType, { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'PE' }))
    await user.click(within(dialog).getByRole('button', { name: 'Modify' }))

    await user.click(screen.getByRole('tab', { name: 'Greeks' }))
    const rows = await screen.findAllByRole('row')
    const editedRow = rows.find((row) => row.textContent?.includes('18AUG26 24600PE'))
    expect(editedRow).toBeDefined()
    const greekCells = within(editedRow as HTMLElement)
      .getAllByRole('cell')
      .slice(1)
    expect(greekCells[0]).toHaveTextContent('12.00')
    for (const cell of greekCells.slice(1)) expect(cell).toHaveTextContent('-')
    expect(editedRow).not.toHaveTextContent('0.4400')
  }, SLOW_INTEGRATION_TEST_TIMEOUT)
})

describe('StrategyBuilder identity orchestration', () => {
  it('persists a contracted time horizon after the maximum remaining time shrinks', async () => {
    const timedChain = (underlying: string, expiry: string) => {
      const chain = chainFixture(underlying, expiry)
      chain.server_ts = 1_786_000_000
      chain.expiry_ts = /18.*AUG.*26/i.test(expiry)
        ? chain.server_ts + 5 * 86_400
        : chain.server_ts + 0.25 * 86_400
      return chain
    }
    mocks.getOptionChain.mockImplementation(
      async (_apiKey: string, underlying: string, _exchange: string, expiry: string) =>
        timedChain(underlying, expiry)
    )
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      mocks.fetchRequests.push({ url, body })
      return new Response(JSON.stringify(timedChain(body.underlying, body.expiry_date)), {
        status: 200,
      })
    })

    renderBuilder()
    const add = await waitForAddButton()
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Expiry' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '18AUG26' }))
    await addOneLeg()

    const timeSlider = screen.getAllByRole('slider')[2]
    fireEvent.change(timeSlider, { target: { value: '4' } })
    expect(timeSlider).toHaveValue('4')

    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Expiry' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: '13AUG26' }))
    await waitFor(() => expect(add).toBeEnabled(), { timeout: ASYNC_READY_TIMEOUT })
    fireEvent.click(add)
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Remove position' })).toHaveLength(2)
    )
    await waitFor(() => {
      const contractedSlider = screen.getAllByRole('slider')[2] as HTMLInputElement
      expect(contractedSlider).toHaveValue(contractedSlider.max)
      expect(Number(contractedSlider.max)).toBeLessThanOrEqual(7)
    })

    const removeButtons = screen.getAllByRole('button', { name: 'Remove position' })
    const removeNearLeg = removeButtons.find((button) =>
      button.closest('li')?.textContent?.includes('13AUG26')
    )
    expect(removeNearLeg).toBeDefined()
    fireEvent.click(removeNearLeg as HTMLButtonElement)
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Remove position' })).toHaveLength(1)
    )
    expect(Number(screen.getAllByRole('slider')[2].getAttribute('max'))).toBeGreaterThan(4)
    await waitFor(() => {
      const persistedDays = Number((screen.getAllByRole('slider')[2] as HTMLInputElement).value)
      expect(persistedDays).toBeGreaterThan(0.24)
      expect(persistedDays).toBeLessThan(0.26)
    })
  })

  it('disables Add immediately when expiry changes until the matching chain arrives', async () => {
    const nextChain = deferred<OptionChainResponse>()
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, string>
      mocks.fetchRequests.push({ url, body })
      const chain =
        body.expiry_date === '18AUG26'
          ? await nextChain.promise
          : chainFixture(body.underlying, body.expiry_date)
      return new Response(JSON.stringify(chain), { status: 200 })
    })

    renderBuilder()
    const add = await waitForAddButton()
    fireEvent.click(add)
    await screen.findByRole('button', { name: 'Remove position' })

    await chooseExpiry('18AUG26')

    expect(screen.getByRole('button', { name: /Add Buy/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove position' })).toBeInTheDocument()

    await act(async () => {
      nextChain.resolve(chainFixture('NIFTY', '18AUG26'))
      await nextChain.promise
    })
    await waitForAddButton()
  })

  it('keeps a controlled identity and legs on cancel, then clears legs and scenarios on acceptance', async () => {
    renderBuilder()
    await addOneLeg()
    const spotShift = screen.getAllByRole('slider')[0]
    fireEvent.change(spotShift, { target: { value: '5' } })
    expect(spotShift).toHaveValue('5')

    await chooseUnderlying('BANKNIFTY')
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Clear the current strategy')
    expect(screen.getByRole('combobox', { name: 'Underlying', hidden: true })).toHaveTextContent(
      'NIFTY'
    )

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
    // Slow for the same reason as its neighbours: it drives the full builder
    // through two identity changes and rebuilds the legs each time. It fits in
    // the default 5s on a plain run and does not under `vitest --coverage`,
    // where v8 instrumentation pushed this file to 65s in CI. The work is real,
    // so the timeout is what is wrong, not the test.
  }, SLOW_INTEGRATION_TEST_TIMEOUT)

  it('does not let an in-flight margin response repopulate state after an identity reset', async () => {
    const staleMargin = deferred<{
      status: number
      data: { status: string; data: { total_margin_required: number } }
    }>()
    // The post-reset request is deferred too, so the assertion below is not
    // racing it. Returning an immediate 20,000 here made the tile appear on its
    // own once the margin effect's 400ms debounce fired, which is what the
    // slower `vitest --coverage` run was losing to.
    const freshMargin = deferred<{
      status: number
      data: { status: string; data: { total_margin_required: number } }
    }>()
    let marginRequestCount = 0
    mocks.apiPost.mockImplementation(async (url: string) => {
      if (url === '/margin') {
        marginRequestCount += 1
        if (marginRequestCount === 1) return staleMargin.promise
        return freshMargin.promise
      }
      if (url === '/optiongreeks') {
        return { status: 200, data: { status: 'success', implied_volatility: 12 } }
      }
      if (url === '/syntheticfuture') {
        return { status: 200, data: { status: 'success', synthetic_future_price: 24_620 } }
      }
      return { status: 200, data: { status: 'success' } }
    })

    renderBuilder()
    await addOneLeg()
    await waitFor(
      () => expect(mocks.apiPost.mock.calls.some(([url]) => url === '/margin')).toBe(true),
      { timeout: 2_000 }
    )

    await chooseUnderlying('BANKNIFTY')
    fireEvent.click(screen.getByRole('button', { name: 'Clear strategy' }))
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Underlying' })).toHaveTextContent('BANKNIFTY')
    )

    await act(async () => {
      staleMargin.resolve({
        status: 200,
        data: { status: 'success', data: { total_margin_required: 10_000 } },
      })
      await staleMargin.promise
    })

    await addOneLeg()

    // With the post-reset request still in flight, nothing legitimate can
    // populate this tile: its presence could only mean the stale in-flight
    // response repopulated state after the identity reset.
    expect(screen.queryByText('Margin Req.')).not.toBeInTheDocument()

    // Non-vacuity: the tile is absent because the stale response was discarded,
    // not because nothing is able to render it. Let the fresh request land and
    // the fresh figure appears - never the stale 10,000.
    await act(async () => {
      freshMargin.resolve({
        status: 200,
        data: { status: 'success', data: { total_margin_required: 20_000 } },
      })
      await freshMargin.promise
    })
    const marginTile = (await screen.findByText('Margin Req.')).closest('div')
    await waitFor(() => expect(marginTile).toHaveTextContent('₹20,000.00'))
    expect(marginTile).not.toHaveTextContent('₹10,000.00')
  }, SLOW_INTEGRATION_TEST_TIMEOUT)

  it('hydrates a saved non-default identity and legs before defaulting or fetch effects run', async () => {
    const portfolio = deferred<PortfolioEntry>()
    const underlyings = deferred<{ status: 'success'; underlyings: string[] }>()
    const optionExpiries = deferred<{ status: 'success'; data: string[] }>()
    const savedChain = deferred<OptionChainResponse>()
    mocks.getPortfolioEntry.mockReturnValue(portfolio.promise)
    mocks.getUnderlyings.mockReturnValue(underlyings.promise)
    mocks.getExpiries.mockImplementation(
      async (_apiKey: string, _symbol: string, _exchange: string, instrument: string) =>
        instrument === 'options' ? optionExpiries.promise : { status: 'success', data: ['27AUG26'] }
    )
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      mocks.fetchRequests.push({ url, body })
      return new Response(JSON.stringify(await savedChain.promise), { status: 200 })
    })

    renderBuilder('/strategybuilder?load=17')

    expect(mocks.getUnderlyings).not.toHaveBeenCalled()
    expect(mocks.getExpiries).not.toHaveBeenCalled()
    expect(requests('/api/v1/optionchain')).toHaveLength(0)

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
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))

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

  it('blocks a saved leg while canonical rehydration is pending, then enables execution without changing entry price', async () => {
    const saved = savedRelianceStrategy()
    saved.legs[0].price = 100
    const restoredChain = deferred<OptionChainResponse>()
    mocks.getPortfolioEntry.mockResolvedValue(saved)
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      mocks.fetchRequests.push({ url, body })
      return new Response(JSON.stringify(await restoredChain.promise), { status: 200 })
    })

    renderBuilder('/strategybuilder?load=17')

    await screen.findByRole('button', { name: 'Remove position' })
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled()

    await act(async () => {
      restoredChain.resolve(chainFixture('RELIANCE', '18AUG26'))
      await restoredChain.promise
    })

    await waitForExecuteButton()
    expect(screen.getAllByText('₹100.00').length).toBeGreaterThan(0)
  })

  it('retries a saved futures leg after its expiry list arrives', async () => {
    const saved = savedRelianceStrategy()
    saved.legs = [
      {
        id: 'saved-future',
        segment: 'FUTURE',
        side: 'BUY',
        lots: 1,
        lotSize: 1,
        expiry: '27AUG26',
        price: 25_100,
        iv: 0,
        active: true,
        symbol: 'STALE_FUTURE',
      },
    ]
    const futuresExpiries = deferred<{ status: 'success'; data: string[] }>()
    mocks.getPortfolioEntry.mockResolvedValue(saved)
    mocks.getExpiries.mockImplementation(
      async (_apiKey: string, _symbol: string, _exchange: string, instrument: string) =>
        instrument === 'futures'
          ? futuresExpiries.promise
          : { status: 'success' as const, data: ['18AUG26'] }
    )
    mocks.getFutures.mockResolvedValue({
      status: 'success',
      data: [
        {
          symbol: 'RELIANCE27AUG26FUT',
          expiry: '27-AUG-26',
          lotsize: 75,
          tick_size: 0.05,
        },
      ],
    })

    renderBuilder('/strategybuilder?load=17')
    await screen.findByRole('button', { name: 'Remove position' })
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled()
    expect(mocks.getFutures).not.toHaveBeenCalled()

    await act(async () => {
      futuresExpiries.resolve({ status: 'success', data: ['27AUG26'] })
      await futuresExpiries.promise
    })

    await waitFor(() => expect(mocks.getFutures).toHaveBeenCalledWith('RELIANCE', 'NFO'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Execute' })).toBeEnabled())
  })

  it('keeps a saved leg blocked when the restored chain cannot resolve its contract', async () => {
    const saved = savedRelianceStrategy()
    mocks.getPortfolioEntry.mockResolvedValue(saved)
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      mocks.fetchRequests.push({ url, body })
      const chain = chainFixture('RELIANCE', '18AUG26')
      chain.chain = []
      return new Response(JSON.stringify(chain), { status: 200 })
    })

    renderBuilder('/strategybuilder?load=17')

    await screen.findByRole('button', { name: 'Remove position' })
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled()
  })

  it('rehydrates each saved leg independently when another resolver rejects', async () => {
    const saved = savedRelianceStrategy()
    saved.legs.push({
      ...saved.legs[0],
      id: 'rejected-far-leg',
      expiry: '13AUG26',
      symbol: 'RELIANCE13AUG262500CE',
    })
    mocks.getPortfolioEntry.mockResolvedValue(saved)
    mocks.getOptionChain.mockImplementation(async (_apiKey, underlying, _exchange, expiry) => {
      if (expiry === '13AUG26') throw new Error('far chain unavailable')
      return chainFixture(underlying, expiry)
    })

    renderBuilder('/strategybuilder?load=17')

    await waitForExecuteButton()
    expect(
      mocks.getOptionChain.mock.calls.filter(([, , , expiry]) => expiry === '13AUG26')
    ).not.toHaveLength(0)
  })

  it('does not retry an unchanged failed far contract on live chain refreshes', async () => {
    const saved = savedRelianceStrategy()
    saved.legs.push({
      ...saved.legs[0],
      id: 'missing-far-leg',
      expiry: '13AUG26',
      symbol: 'RELIANCE13AUG262500CE',
    })
    mocks.getPortfolioEntry.mockResolvedValue(saved)
    mocks.getOptionChain.mockImplementation(async (_apiKey, underlying, _exchange, expiry) => {
      const chain = chainFixture(underlying, expiry)
      if (expiry === '13AUG26') chain.chain = []
      return chain
    })

    renderBuilder('/strategybuilder?load=17')

    await waitFor(() =>
      expect(
        mocks.getOptionChain.mock.calls.filter(([, , , expiry]) => expiry === '13AUG26').length
      ).toBeGreaterThan(0)
    )
    const farCallsBeforeRefresh = mocks.getOptionChain.mock.calls.filter(
      ([, , , expiry]) => expiry === '13AUG26'
    ).length
    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(1))

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))

    await waitFor(() => expect(requests('/api/v1/optionchain')).toHaveLength(2))
    expect(
      mocks.getOptionChain.mock.calls.filter(([, , , expiry]) => expiry === '13AUG26')
    ).toHaveLength(farCallsBeforeRefresh)
  })
})
