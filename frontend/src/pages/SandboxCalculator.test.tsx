import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EstimateRequest } from '@/api/sandbox-charges'
import { renderWithQuery } from '@/test/queryRender'
import { chargeSettings, cryptoSettings, estimateFor } from '@/test/sandboxChargesFixture'
import { fireEvent, screen, userEvent, waitFor, within } from '@/test/test-utils'
import SandboxCalculator from './SandboxCalculator'

// The /sandbox/calculator page: a card per segment, priced by the server as
// the trade is typed. The server sends the segments of the logged-in broker's
// market alone, so a trader on an Indian broker sees the Indian calculator
// (with its statutory lines) and a trader on a crypto venue sees the crypto
// one (a venue fee and nothing else). The two are never on one page.

const api = vi.hoisted(() => ({
  settings: vi.fn(),
  save: vi.fn(),
  reset: vi.fn(),
  estimate: vi.fn(),
  report: vi.fn(),
}))

vi.mock('@/api/sandbox-charges', async (original) => ({
  ...(await original<typeof import('@/api/sandbox-charges')>()),
  sandboxChargesApi: api,
}))

const card = (key: string) => screen.getByTestId(`calc-${key}`)
const requestsFor = (segment: string): EstimateRequest[] =>
  api.estimate.mock.calls.map(([request]) => request).filter((r) => r.segment === segment)

describe('SandboxCalculator', () => {
  beforeEach(() => {
    api.settings.mockResolvedValue(chargeSettings())
    api.estimate.mockImplementation(async (request: EstimateRequest) => estimateFor(request))
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('opens on a priced trade for each equity and F&O segment', async () => {
    renderWithQuery(<SandboxCalculator />)

    expect(await screen.findByTestId('calc-equity_intraday')).toBeInTheDocument()
    for (const key of ['equity_delivery', 'equity_intraday', 'fno_futures', 'fno_options']) {
      expect(card(key)).toBeInTheDocument()
    }
    await waitFor(() =>
      expect(screen.getByTestId('calc-equity_intraday-total')).toHaveTextContent('200.62')
    )
    expect(requestsFor('equity_intraday')[0]).toEqual({
      segment: 'equity_intraday',
      exchange: 'NSE',
      buy_price: '1000',
      sell_price: '1100',
      quantity: '400',
    })
    // Options open on a premium, not a share price.
    expect(requestsFor('fno_options')[0]).toMatchObject({ buy_price: '100', exchange: 'NFO' })

    const intraday = within(card('equity_intraday'))
    expect(intraday.getByText('Turnover').nextSibling).toHaveTextContent('8,40,000.00')
    expect(intraday.getByText('STT total').nextSibling).toHaveTextContent('110.00')
    expect(intraday.getByText('Exchange txn charge').nextSibling).toHaveTextContent('25.79')
    expect(intraday.getByText('GST').nextSibling).toHaveTextContent('11.99')
    expect(intraday.getByText('SEBI charges').nextSibling).toHaveTextContent('0.84')
    expect(intraday.getByText('Stamp duty').nextSibling).toHaveTextContent('12.00')
    expect(intraday.getByText('Points to breakeven').nextSibling).toHaveTextContent('0.5')
    expect(screen.getByTestId('calc-equity_intraday-net')).toHaveTextContent('39,799.38')
    expect(screen.getByTestId('calc-equity_intraday-net')).toHaveClass('text-green-500')
  })

  it('prices under the saved plan and says which plan that is', async () => {
    renderWithQuery(<SandboxCalculator />)
    await screen.findByTestId('calc-equity_delivery')

    expect(
      within(card('equity_delivery')).getByText(
        /20\.00 per executed order or 2\.5% of the trade value, whichever is lower$/
      )
    ).toBeInTheDocument()
    // The request carries no plan of its own, so the server uses the saved one.
    await waitFor(() => expect(requestsFor('equity_delivery')).not.toHaveLength(0))
    expect(requestsFor('equity_delivery')[0]).not.toHaveProperty('flat')
    expect(requestsFor('equity_delivery')[0]).not.toHaveProperty('percent')
    expect(screen.getByRole('link', { name: /Brokerage Plan/ })).toHaveAttribute(
      'href',
      '/sandbox/commissions'
    )
  })

  it('prices the trade again once typing settles', async () => {
    renderWithQuery(<SandboxCalculator />)
    await waitFor(() => expect(requestsFor('equity_intraday')).toHaveLength(1))

    const quantity = within(card('equity_intraday')).getByLabelText('Quantity')
    fireEvent.change(quantity, { target: { value: '4' } })
    fireEvent.change(quantity, { target: { value: '45' } })
    fireEvent.change(quantity, { target: { value: '450' } })

    await waitFor(() => expect(requestsFor('equity_intraday')).toHaveLength(2))
    // One request for where the typing ended, none for the digits on the way.
    expect(requestsFor('equity_intraday')[1].quantity).toBe('450')
  })

  it('prices on the exchange chosen', async () => {
    renderWithQuery(<SandboxCalculator />)
    await waitFor(() => expect(requestsFor('fno_futures')).toHaveLength(1))

    const futures = within(card('fno_futures'))
    expect(futures.getByRole('button', { name: 'NFO' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(futures.getByRole('button', { name: 'BFO' }))

    await waitFor(() => expect(requestsFor('fno_futures').at(-1)?.exchange).toBe('BFO'))
    expect(futures.getByRole('button', { name: 'BFO' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('waits for a complete trade instead of pricing half of one', async () => {
    renderWithQuery(<SandboxCalculator />)
    await waitFor(() =>
      expect(screen.getByTestId('calc-equity_delivery-total')).toHaveTextContent('200.62')
    )
    const before = requestsFor('equity_delivery').length

    const sell = within(card('equity_delivery')).getByLabelText('Sell')
    fireEvent.change(sell, { target: { value: '' } })

    await waitFor(() =>
      expect(screen.getByTestId('calc-equity_delivery-total')).toHaveTextContent('-')
    )
    expect(sell).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByTestId('calc-equity_delivery-net')).toHaveTextContent('-')
    expect(requestsFor('equity_delivery')).toHaveLength(before)
  })

  it('shows a loss in red', async () => {
    api.estimate.mockImplementation(async (request: EstimateRequest) =>
      estimateFor({ ...request, sell_price: '990' })
    )
    renderWithQuery(<SandboxCalculator />)

    await waitFor(() =>
      expect(screen.getByTestId('calc-equity_intraday-net')).toHaveClass('text-red-500')
    )
  })

  it('names the commodity levy CTT', async () => {
    const user = userEvent.setup()
    renderWithQuery(<SandboxCalculator />)
    await screen.findByTestId('calc-equity_intraday')

    await user.click(screen.getByRole('tab', { name: 'Commodities' }))

    const futures = within(await screen.findByTestId('calc-commodity_futures'))
    expect(await futures.findByText('CTT total')).toBeInTheDocument()
    expect(futures.getByRole('button', { name: 'MCX' })).toHaveAttribute('aria-pressed', 'true')
    expect(futures.getByRole('button', { name: 'NCO' })).toBeInTheDocument()
  })

  it('opens each card on the main exchange, though the rates arrive sorted', async () => {
    // What the server sends: the rates as an object with its keys sorted, so
    // BSE and BFO come first there, and the order to show as a list.
    const intraday = chargeSettings().segments.find((s) => s.key === 'equity_intraday')
    expect(Object.keys(intraday?.statutory.exchange_txn ?? {})).toEqual(['BSE', 'NSE'])
    expect(intraday?.exchanges).toEqual(['NSE', 'BSE'])

    const user = userEvent.setup()
    renderWithQuery(<SandboxCalculator />)
    await waitFor(() => expect(requestsFor('fno_options')).toHaveLength(1))

    for (const [key, main, other] of [
      ['equity_delivery', 'NSE', 'BSE'],
      ['equity_intraday', 'NSE', 'BSE'],
      ['fno_futures', 'NFO', 'BFO'],
      ['fno_options', 'NFO', 'BFO'],
    ]) {
      const buttons = within(card(key)).getAllByRole('button')
      expect(buttons.map((button) => button.textContent)).toEqual([main, other])
      expect(buttons[0]).toHaveAttribute('aria-pressed', 'true')
      expect(requestsFor(key)[0].exchange).toBe(main)
    }

    await user.click(screen.getByRole('tab', { name: 'Currency' }))
    const currency = within(await screen.findByTestId('calc-currency_futures'))
    expect(currency.getByRole('button', { name: 'CDS' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(requestsFor('currency_futures')[0]?.exchange).toBe('CDS'))
  })

  it('never offers crypto to a trader on an Indian broker', async () => {
    renderWithQuery(<SandboxCalculator />)
    await screen.findByTestId('calc-equity_intraday')

    expect(screen.getByRole('heading', { name: 'Brokerage Calculator' })).toBeInTheDocument()
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Equities and F&O',
      'Currency',
      'Commodities',
    ])
    expect(screen.queryByRole('tab', { name: /Crypto/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('calc-crypto_futures')).not.toBeInTheDocument()
    expect(screen.queryByText(/venue fee/i)).not.toBeInTheDocument()
    expect(api.estimate.mock.calls.every(([request]) => request.exchange !== 'CRYPTO')).toBe(true)
  })

  it('shows a trader on a crypto venue the crypto calculator and nothing Indian', async () => {
    api.settings.mockResolvedValue(cryptoSettings())
    api.estimate.mockImplementation(async (request: EstimateRequest) => estimateFor(request, 0))
    renderWithQuery(<SandboxCalculator />)

    const perpetual = within(await screen.findByTestId('calc-crypto_futures'))
    expect(screen.getByTestId('calc-crypto_options')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Fee Calculator' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Venue Fee/ })).toHaveAttribute(
      'href',
      '/sandbox/commissions'
    )
    // One market, so there is nothing to switch between.
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    for (const key of ['equity_delivery', 'equity_intraday', 'fno_futures', 'currency_futures']) {
      expect(screen.queryByTestId(`calc-${key}`)).not.toBeInTheDocument()
    }
    expect(screen.queryByText(/Brokerage/)).not.toBeInTheDocument()

    expect(perpetual.getByText('Venue fee')).toBeInTheDocument()
    expect(perpetual.getByText('Fee')).toBeInTheDocument()
    expect(perpetual.getByText('No fee')).toBeInTheDocument()
    expect(perpetual.getByText('Total charges')).toBeInTheDocument()
    for (const line of [
      'Statutory charges',
      'STT total',
      'Exchange txn charge',
      'GST',
      'SEBI charges',
      'Stamp duty',
    ]) {
      expect(perpetual.queryByText(line)).not.toBeInTheDocument()
    }
    // One venue, so there is no exchange to choose.
    expect(perpetual.queryByRole('button', { name: 'CRYPTO' })).not.toBeInTheDocument()
    await waitFor(() => expect(requestsFor('crypto_futures')[0]?.exchange).toBe('CRYPTO'))
    expect(screen.getByText(/Until you enter one, trades cost nothing here/)).toBeVisible()
    expect(api.estimate.mock.calls.every(([request]) => request.exchange === 'CRYPTO')).toBe(true)
  })

  it('says a round trip is priced as one contract note and a fill on its own', async () => {
    renderWithQuery(<SandboxCalculator />)
    await screen.findByTestId('calc-equity_intraday')

    expect(
      screen.getByText(/STT and stamp duty to the nearest rupee, the other lines to the paisa/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/the two fills can come to a paisa more or less than the figure here/)
    ).toBeInTheDocument()
  })

  it('says when charges are switched off that the figures are still what a trade costs', async () => {
    api.settings.mockResolvedValue(chargeSettings({ enabled: false }))
    renderWithQuery(<SandboxCalculator />)

    expect(
      await screen.findByText(/Charges are switched off, so sandbox trades are not charged/)
    ).toBeInTheDocument()
  })

  it("shows the server's sentence when a trade cannot be priced", async () => {
    api.estimate.mockRejectedValue({
      isAxiosError: true,
      response: { data: { status: 'error', message: 'Enter a quantity above zero.' } },
    })
    renderWithQuery(<SandboxCalculator />)

    expect(
      await within(await screen.findByTestId('calc-equity_intraday')).findByText(
        'Enter a quantity above zero.'
      )
    ).toBeInTheDocument()
  })

  it('says so when the calculator cannot be loaded', async () => {
    api.settings.mockRejectedValue(new Error('offline'))
    renderWithQuery(<SandboxCalculator />)

    expect(await screen.findByText('The calculator could not be loaded.')).toBeInTheDocument()
  })
})
