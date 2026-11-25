import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithQuery } from '@/test/queryRender'
import { breakdown, chargeSettings, costReport, cryptoSettings } from '@/test/sandboxChargesFixture'
import { fireEvent, screen, userEvent, waitFor, within } from '@/test/test-utils'
import SandboxCommissions from './SandboxCommissions'

// The /sandbox/commissions page: the brokerage plan and the transaction cost
// report. The server works every charge out; the page sends a plan and shows
// what comes back.

const api = vi.hoisted(() => ({
  settings: vi.fn(),
  save: vi.fn(),
  reset: vi.fn(),
  estimate: vi.fn(),
  report: vi.fn(),
}))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))

vi.mock('@/api/sandbox-charges', async (original) => ({
  ...(await original<typeof import('@/api/sandbox-charges')>()),
  sandboxChargesApi: api,
}))
vi.mock('@/utils/toast', () => ({ showToast: toast }))

function open(path = '/sandbox/commissions') {
  window.history.pushState({}, '', path)
  return renderWithQuery(<SandboxCommissions />)
}

/** The plan has loaded. A segment's name is in two tables, so wait on its row. */
const loaded = () => screen.findByTestId('plan-equity_delivery')
const flat = (label: string) =>
  screen.getByRole('spinbutton', { name: `${label} amount per executed order` })
const percent = (label: string) =>
  screen.getByRole('spinbutton', { name: `${label} percentage of trade value` })

describe('SandboxCommissions', () => {
  beforeEach(() => {
    api.settings.mockResolvedValue(chargeSettings())
    api.report.mockResolvedValue(costReport())
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('opens on the saved plan, one sentence per segment', async () => {
    open()

    expect(await loaded()).toBeInTheDocument()
    expect(flat('Equity Delivery')).toHaveValue(20)
    expect(percent('Equity Delivery')).toHaveValue(2.5)
    expect(screen.getByTestId('plan-equity_delivery')).toHaveTextContent(
      /20\.00 per executed order or 2\.5% of the trade value, whichever is lower$/
    )
    expect(screen.getByTestId('plan-equity_intraday')).toHaveTextContent(
      /20\.00 per executed order or 0\.1% of the trade value, whichever is lower$/
    )
    expect(screen.getByTestId('plan-fno_options')).toHaveTextContent(/20\.00 per executed order$/)
    // An Indian broker's plan has no crypto rows in it.
    expect(screen.queryByTestId('plan-crypto_futures')).not.toBeInTheDocument()
    expect(screen.queryByText(/crypto/i)).not.toBeInTheDocument()
    // Nothing to save until something changes.
    expect(screen.getByRole('button', { name: /Save charges/ })).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Charge sandbox trades' })).toBeChecked()
  })

  it('shows the statutory schedule it adds, and that it cannot be changed here', async () => {
    open()

    await screen.findByText('Statutory charges')
    expect(screen.getByText('0.1% on buy and sell')).toBeInTheDocument()
    expect(screen.getByText('0.025% on sell')).toBeInTheDocument()
    expect(screen.getByText('NFO 0.03553%, BFO 0.0325%')).toBeInTheDocument()
    expect(screen.getByText(/Rates as of 2026-11-23/)).toBeInTheDocument()
    // Main exchange first, though the rates arrive with BSE before NSE.
    expect(screen.getAllByText('NSE 0.00307%, BSE 0.00375%')).toHaveLength(2)
    expect(screen.getAllByText('MCX 0.0021%, NCDEX 0.0021%, NCO 0.0001%')).toHaveLength(1)
    expect(
      screen.getByText(/STT and stamp duty are rounded to the nearest rupee, as on a contract note/)
    ).toBeInTheDocument()
  })

  it('shows a trader on a crypto venue the venue fee and nothing of the Indian plan', async () => {
    api.settings.mockResolvedValue(cryptoSettings())
    open()

    expect(await screen.findByTestId('plan-crypto_futures')).toHaveTextContent('No fee')
    expect(screen.getByTestId('plan-crypto_options')).toHaveTextContent('No fee')
    for (const key of ['equity_delivery', 'equity_intraday', 'fno_options', 'commodity_futures']) {
      expect(screen.queryByTestId(`plan-${key}`)).not.toBeInTheDocument()
    }
    // Its own words: a fee, not a brokerage plan.
    expect(screen.getByRole('tab', { name: /Venue Fee/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Fee Calculator/ })).toHaveAttribute(
      'href',
      '/sandbox/calculator'
    )
    expect(screen.getByText(/pays the venue fee entered below/)).toBeInTheDocument()
    expect(screen.getByText('Nothing is added to the fee')).toBeInTheDocument()
    // None of the Indian schedule, and none of its caveats.
    for (const text of [
      'Statutory charges',
      'STT / CTT',
      'Stamp duty',
      'SEBI charges',
      /Depository/,
      /Brokerage/,
    ]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument()
    }
    expect(screen.getByText(/One fee applies to every executed order/)).toBeInTheDocument()
  })

  it('rewords the plan as it is typed and marks it as not saved', async () => {
    open()
    await loaded()

    fireEvent.change(flat('Equity Delivery'), { target: { value: '0' } })
    fireEvent.change(percent('Equity Delivery'), { target: { value: '0.5' } })

    const plan = screen.getByTestId('plan-equity_delivery')
    expect(plan).toHaveTextContent('0.5% of the trade value')
    expect(within(plan.parentElement as HTMLElement).getByText('Not saved')).toBeInTheDocument()
    expect(screen.getByText('You have changes that are not saved.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save charges/ })).toBeEnabled()
  })

  it('saves the switch and the whole plan together and shows what the server said', async () => {
    const savedPlan = chargeSettings()
    savedPlan.segments[0] = { ...savedPlan.segments[0], flat: '0', percent: '0.5' }
    api.save.mockResolvedValue({
      settings: savedPlan,
      message: 'Charges saved. They apply from the next trade.',
    })
    open()
    await loaded()

    fireEvent.change(flat('Equity Delivery'), { target: { value: '0' } })
    fireEvent.change(percent('Equity Delivery'), { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: /Save charges/ }))

    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1))
    const sent = api.save.mock.calls[0][0]
    expect(sent.enabled).toBe(true)
    // The eight segments this browser is shown. The crypto plan is not sent,
    // so saving here cannot change a plan the trader never saw.
    expect(Object.keys(sent.segments)).toHaveLength(8)
    expect(Object.keys(sent.segments).filter((key) => key.startsWith('crypto'))).toEqual([])
    expect(sent.segments.equity_delivery).toEqual({ flat: '0', percent: '0.5' })
    expect(sent.segments.fno_options).toEqual({ flat: '20', percent: '0' })
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Charges saved. They apply from the next trade.',
        'analyzer'
      )
    )
    await waitFor(() => expect(screen.getByRole('button', { name: /Save charges/ })).toBeDisabled())
    expect(screen.getByText('Saved. Applies to the next trade.')).toBeInTheDocument()
  })

  it("shows the server's own sentence when a value is refused, and keeps what was typed", async () => {
    api.save.mockRejectedValue({
      isAxiosError: true,
      response: {
        data: {
          status: 'error',
          message:
            'F&O Futures: the percentage cannot be more than 5. Enter 0.03 for 0.03%, not 3.',
        },
      },
    })
    open()
    await loaded()

    fireEvent.change(percent('F&O Futures'), { target: { value: '30' } })
    fireEvent.click(screen.getByRole('button', { name: /Save charges/ }))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        'F&O Futures: the percentage cannot be more than 5. Enter 0.03 for 0.03%, not 3.',
        'analyzer'
      )
    )
    expect(percent('F&O Futures')).toHaveValue(30)
    expect(screen.getByRole('button', { name: /Save charges/ })).toBeEnabled()
  })

  it('will not save a field that is empty or below zero', async () => {
    open()
    await loaded()

    fireEvent.change(flat('Equity Intraday'), { target: { value: '-5' } })

    expect(screen.getByTestId('plan-equity_intraday')).toHaveTextContent(
      'Enter a number, 0 or above'
    )
    expect(flat('Equity Intraday')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: /Save charges/ })).toBeDisabled()

    fireEvent.change(flat('Equity Intraday'), { target: { value: '' } })
    expect(screen.getByRole('button', { name: /Save charges/ })).toBeDisabled()
  })

  it('says what switching charges off means before it is saved', async () => {
    api.save.mockResolvedValue({
      settings: chargeSettings({ enabled: false }),
      message: 'Charges saved. They apply from the next trade.',
    })
    open()
    await loaded()
    expect(screen.getByText(/pays brokerage and statutory charges/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('switch', { name: 'Charge sandbox trades' }))

    expect(screen.getByText(/Sandbox trades cost nothing/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Save charges/ }))
    await waitFor(() => expect(api.save.mock.calls[0][0].enabled).toBe(false))
  })

  it('asks before resetting, and says the trades and funds are not touched', async () => {
    api.reset.mockResolvedValue({
      settings: chargeSettings(),
      message: 'Charges are back to the defaults. They apply from the next trade.',
    })
    open()
    await loaded()
    fireEvent.change(flat('Equity Delivery'), { target: { value: '5' } })

    fireEvent.click(screen.getByRole('button', { name: /Reset to defaults/ }))

    expect(api.reset).not.toHaveBeenCalled()
    expect(
      screen.getByText(/Your trades, positions, funds and the charges already paid are not changed/)
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reset charges' }))

    await waitFor(() => expect(api.reset).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(flat('Equity Delivery')).toHaveValue(20))
  })

  it('links to the calculator, the sandbox settings and the P&L page', async () => {
    open()
    await loaded()

    expect(screen.getByRole('link', { name: /Brokerage Calculator/ })).toHaveAttribute(
      'href',
      '/sandbox/calculator'
    )
    expect(screen.getByRole('link', { name: /Sandbox Config/ })).toHaveAttribute('href', '/sandbox')
    expect(screen.getByRole('link', { name: /My P&L/ })).toHaveAttribute('href', '/sandbox/mypnl')
  })

  it('says so when the plan cannot be loaded', async () => {
    api.settings.mockRejectedValue(new Error('offline'))
    open()

    expect(await screen.findByText('The sandbox charges could not be loaded.')).toBeInTheDocument()
  })

  describe('transaction costs', () => {
    it('opens straight on the report from its link and totals what was paid', async () => {
      open('/sandbox/commissions?tab=report')

      expect(await screen.findByText('Total charges')).toBeInTheDocument()
      expect(api.report).toHaveBeenCalledTimes(1)
      const [from, to] = api.report.mock.calls[0]
      expect(from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(to).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(from < to).toBe(true)

      const total = screen.getByText('Total charges').parentElement as HTMLElement
      expect(total).toHaveTextContent('330.74')
      expect(total).toHaveTextContent('0.130% of turnover')
      // Statutory is everything that is not brokerage.
      expect(screen.getByText('Statutory charges').parentElement).toHaveTextContent('290.74')
      expect(screen.getByText('All 2 trades in this range, latest first.')).toBeInTheDocument()
      // Each trade carries its own breakdown.
      const rows = screen.getAllByText('RELIANCE').map((cell) => cell.closest('tr') as HTMLElement)
      expect(rows[0]).toHaveTextContent('SELL')
      expect(rows[0]).toHaveTextContent('158.46')
      expect(rows[1]).toHaveTextContent('BUY')
      expect(rows[1]).toHaveTextContent('172.28')
      expect(screen.getByRole('button', { name: /Export CSV/ })).toBeEnabled()
    })

    it('shows a crypto venue its fees alone, with no columns from the Indian schedule', async () => {
      api.settings.mockResolvedValue(cryptoSettings())
      const fee = breakdown({ brokerage: 30.25, total_charges: 30.25 })
      const totals = { trades: 1, turnover: 60500, ...fee }
      api.report.mockResolvedValue(
        costReport({
          totals,
          by_segment: [{ ...totals, segment: 'crypto_futures', label: 'Crypto Futures and Spot' }],
          by_day: [{ ...totals, date: '2026-11-23' }],
          trades: [
            {
              ...fee,
              tradeid: 'TRADE-9',
              orderid: '9',
              timestamp: '2026-11-23 10:05:00',
              symbol: 'CHGTESTUSDFUT',
              exchange: 'CRYPTO',
              product: 'NRML',
              action: 'SELL',
              quantity: 1,
              price: 60500,
              turnover: 60500,
              segment: 'crypto_futures',
              segment_label: 'Crypto Futures and Spot',
              strategy: '',
            },
          ],
          trades_listed: 1,
          trades_total: 1,
        })
      )
      open('/sandbox/commissions?tab=report')

      const total = (await screen.findByText('Total fees')).parentElement as HTMLElement
      expect(total).toHaveTextContent('30.25')
      expect(screen.getAllByRole('columnheader', { name: 'Fee' })).toHaveLength(3)
      for (const header of ['STT / CTT', 'Exchange', 'SEBI', 'Stamp duty', 'GST', 'Brokerage']) {
        expect(screen.queryByRole('columnheader', { name: header })).not.toBeInTheDocument()
      }
      expect(screen.queryByText('Statutory charges')).not.toBeInTheDocument()
      expect(screen.getByText('CHGTESTUSDFUT').closest('tr')).toHaveTextContent('30.25')
    })

    it('reads the report again for the dates chosen', async () => {
      const user = userEvent.setup()
      open('/sandbox/commissions?tab=report')
      await screen.findByText('Total charges')

      fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-11-01' } })
      fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-11-10' } })
      expect(api.report).toHaveBeenCalledTimes(1)
      await user.click(screen.getByRole('button', { name: 'Show' }))

      await waitFor(() => expect(api.report).toHaveBeenLastCalledWith('2026-11-01', '2026-11-10'))
    })

    it('says when the list is cut short and that the totals are not', async () => {
      api.report.mockResolvedValue(costReport({ trades_listed: 2, trades_total: 950 }))
      open('/sandbox/commissions?tab=report')

      expect(
        await screen.findByText(
          'The latest 2 of 950 trades. The totals above cover all of them, and the CSV lists every one.'
        )
      ).toBeInTheDocument()
    })

    it('has nothing to export when there are no trades', async () => {
      const empty = { trades: 0, turnover: 0, ...breakdown() }
      api.report.mockResolvedValue(
        costReport({
          totals: empty,
          by_segment: [],
          by_day: [],
          trades: [],
          trades_listed: 0,
          trades_total: 0,
        })
      )
      open('/sandbox/commissions?tab=report')

      expect(await screen.findByText('No sandbox trades between these dates.')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Export CSV/ })).toBeDisabled()
    })

    it('moves between the plan and the report by tab', async () => {
      const user = userEvent.setup()
      open()
      await loaded()

      await user.click(screen.getByRole('tab', { name: /Transaction Costs/ }))

      expect(await screen.findByText('Total charges')).toBeInTheDocument()
      expect(window.location.search).toBe('?tab=report')
      await user.click(screen.getByRole('tab', { name: /Brokerage Plan/ }))
      expect(window.location.search).toBe('')
    })
  })
})
