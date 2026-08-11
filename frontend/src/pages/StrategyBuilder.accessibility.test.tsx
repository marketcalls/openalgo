import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe, toHaveNoViolations } from 'jest-axe'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OptionChainResponse, OptionData } from '@/types/option-chain'
import StrategyBuilder from './StrategyBuilder'

expect.extend(toHaveNoViolations)

const mocks = vi.hoisted(() => ({
  getExpiries: vi.fn(),
  getUnderlyings: vi.fn(),
  liveData: null as OptionChainResponse | null,
  refetch: vi.fn(),
  dataIdentity: { exchange: 'NFO', underlying: 'NIFTY', expiry: '04AUG26' },
  disabledLiveResult: {
    data: null,
    forwardPrice: null,
    clockOffsetMs: 0,
    isLoading: false,
    isStreaming: false,
    isPaused: false,
    lastStreamUpdate: null,
    dataIdentity: null,
  },
  enabledLiveResult: {
    data: null as OptionChainResponse | null,
    forwardPrice: 101,
    clockOffsetMs: 0,
    isLoading: false,
    isStreaming: false,
    isPaused: false,
    lastStreamUpdate: null,
    dataIdentity: { exchange: 'NFO', underlying: 'NIFTY', expiry: '04AUG26' },
  },
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    post: vi.fn(async () => ({
      status: 200,
      data: { status: 'success', data: { total_margin_required: 10_000 } },
    })),
  },
}))

vi.mock('@/api/oi-profile', () => ({
  oiProfileApi: { getUnderlyings: mocks.getUnderlyings },
}))

vi.mock('@/api/option-chain', () => ({
  optionChainApi: {
    getExpiries: mocks.getExpiries,
    getOptionChain: vi.fn(async () => mocks.liveData),
  },
}))

vi.mock('@/api/scalping', () => ({
  scalpingApi: { futures: vi.fn(async () => ({ status: 'success', data: [] })) },
}))

vi.mock('@/api/strategy-portfolio', () => ({
  strategyPortfolioApi: {
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
}))

vi.mock('@/api/trading', () => ({
  tradingApi: {
    getQuotes: vi.fn(),
    placeBasketOrder: vi.fn(),
  },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key', user: { broker: null } }),
}))

vi.mock('@/hooks/useOptionChainLive', () => ({
  currentWebSocketMarketData: (data: Map<string, unknown>) => data,
  useOptionChainLive: (
    _apiKey: string,
    _underlying: string,
    _underlyingExchange: string,
    _exchange: string,
    expiry: string
  ) => ({
    ...(expiry ? mocks.enabledLiveResult : mocks.disabledLiveResult),
    refetch: mocks.refetch,
  }),
}))

vi.mock('@/lib/Plot2D', () => ({
  default: () => <div aria-hidden="true" data-testid="payoff-plot" />,
}))

vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn() },
}))

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
    implied_volatility: 20,
  }
}

function chainFixture(): OptionChainResponse {
  return {
    status: 'success',
    underlying: 'NIFTY',
    underlying_symbol: 'NIFTY',
    underlying_exchange: 'NSE_INDEX',
    underlying_ltp: 100,
    underlying_prev_close: 99,
    expiry_date: '04AUG26',
    expiry_ts: Math.floor(Date.now() / 1_000) + 7 * 86_400,
    server_ts: Math.floor(Date.now() / 1_000),
    atm_strike: 100,
    forward_price: 101,
    greeks_included: true,
    chain: [
      { strike: 90, ce: option('NIFTY04AUG2690CE', 12), pe: option('NIFTY04AUG2690PE', 2) },
      { strike: 100, ce: option('NIFTY04AUG26100CE', 6), pe: option('NIFTY04AUG26100PE', 5) },
      { strike: 110, ce: option('NIFTY04AUG26110CE', 2), pe: option('NIFTY04AUG26110PE', 12) },
    ],
  }
}

async function renderPopulatedBuilder() {
  const user = userEvent.setup()
  const view = render(
    <MemoryRouter initialEntries={['/strategybuilder']}>
      <StrategyBuilder />
    </MemoryRouter>
  )
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: 'Option expiry' })).toHaveTextContent('04AUG26')
  )
  await screen.findByText('NIFTY04AUG26100CE')
  const add = await screen.findByRole('button', { name: /add buy/i })
  await waitFor(() => expect(add).toBeEnabled())
  await user.click(add)
  await screen.findByRole('button', { name: 'Remove position' })
  return { user, view }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.liveData = chainFixture()
  mocks.enabledLiveResult.data = mocks.liveData
  mocks.getUnderlyings.mockResolvedValue({ status: 'success', underlyings: ['NIFTY'] })
  mocks.getExpiries.mockImplementation(
    async (_apiKey: string, _symbol: string, _exchange: string, instrument: string) => ({
      status: 'success',
      data: instrument === 'options' ? ['04AUG26', '11AUG26'] : ['28AUG26'],
    })
  )
  Element.prototype.scrollIntoView = vi.fn()
})

describe('StrategyBuilder accessibility and mobile containment', () => {
  it(
    'SB-17/SB-18 contains tabs and exposes controls/payoff semantics without Axe violations',
    async () => {
      const { view } = await renderPopulatedBuilder()

      const page = screen.getByTestId('strategy-builder-page')
      expect(page).toHaveClass('min-w-0', 'max-w-full')
      expect(screen.getByTestId('strategy-tabs-scroller')).toHaveClass(
        'min-w-0',
        'max-w-full',
        'overflow-x-auto'
      )

      expect(screen.getByRole('textbox', { name: 'Search strategy templates' })).toBeVisible()
      expect(screen.getByRole('combobox', { name: 'Segment' })).toBeVisible()
      expect(screen.getByRole('combobox', { name: 'Expiry' })).toBeVisible()
      expect(screen.getByRole('combobox', { name: 'Strike' })).toBeVisible()
      expect(screen.getByRole('group', { name: 'Option type' })).toBeVisible()
      expect(screen.getByRole('group', { name: 'Trade side' })).toBeVisible()
      expect(screen.getByRole('spinbutton', { name: 'Position lot quantity' })).toBeVisible()
      expect(screen.getByRole('slider', { name: 'Spot price shift' })).toBeVisible()
      expect(screen.getByRole('slider', { name: 'Implied volatility shift' })).toBeVisible()
      expect(screen.getByRole('slider', { name: 'Time forward' })).toBeVisible()

      const payoff = screen.getByRole('region', { name: /payoff analysis/i })
      expect(
        within(payoff).getByRole('table', { name: /representative payoff values/i })
      ).toBeVisible()

      const headingLevels = screen
        .getAllByRole('heading')
        .map((heading) => Number(heading.tagName.slice(1)))
      for (let index = 1; index < headingLevels.length; index += 1) {
        expect(headingLevels[index]).toBeLessThanOrEqual(headingLevels[index - 1] + 1)
      }
      expect(await axe(view.container)).toHaveNoViolations()
    },
    15_000
  )

  it('labels template dialog controls in the integrated builder', async () => {
    const { user } = await renderPopulatedBuilder()

    await user.click(screen.getByRole('button', { name: /long call/i }))
    const dialog = await screen.findByRole('dialog', { name: 'Long Call' })
    expect(
      within(dialog).getByRole('combobox', { name: /strike for buy call leg 1/i })
    ).toBeVisible()
    expect(within(dialog).getByRole('combobox', { name: 'Strategy expiry' })).toBeVisible()
    expect(within(dialog).getByRole('spinbutton', { name: 'Strategy lot quantity' })).toBeVisible()
    expect(await axe(document.body)).toHaveNoViolations()
  })

  it('labels order controls and associates an invalid limit price with its error', async () => {
    const { user } = await renderPopulatedBuilder()

    await user.click(screen.getByRole('button', { name: 'Execute' }))
    const dialog = await screen.findByRole('dialog', { name: /execute basket order/i })
    expect(within(dialog).getByRole('group', { name: 'Product type' })).toBeVisible()
    expect(within(dialog).getByRole('group', { name: 'Price type' })).toBeVisible()
    expect(
      within(dialog).getByRole('checkbox', { name: /include nifty04aug26100ce/i })
    ).toBeVisible()
    expect(
      within(dialog).getByRole('spinbutton', { name: /lots for nifty04aug26100ce/i })
    ).toBeVisible()

    const price = within(dialog).getByRole('spinbutton', {
      name: /limit price for nifty04aug26100ce/i,
    })
    fireEvent.change(price, { target: { value: '' } })
    fireEvent.blur(price)

    expect(price).toHaveAttribute('aria-invalid', 'true')
    const errorId = price.getAttribute('aria-describedby')
    expect(errorId).toBeTruthy()
    expect(document.getElementById(errorId as string)).toHaveTextContent(/supported tick range/i)
    expect(await axe(document.body)).toHaveNoViolations()
  })
})
