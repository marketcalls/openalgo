import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import type { OptionChainResponse } from '@/types/option-chain'
import { OptionChainPanel } from './OptionChainPanel'

const useOptionChainLive = vi.fn()
const getAllUnderlyings = vi.fn()
const getExpiry = vi.fn()
const refetch = vi.fn()

// The panel streams through this hook rather than polling the REST endpoint,
// so the hook is the seam these tests drive. Fetching, request identity and
// the websocket merge are the hook's own concern and are covered by
// hooks/useOptionChainPolling.test.tsx and hooks/useOptionChainLive.test.tsx.
vi.mock('@/hooks/useOptionChainLive', () => ({
  useOptionChainLive: (...a: unknown[]) => useOptionChainLive(...a),
}))

/** The hook's return shape, with only the fields this panel reads. */
function live(over: Record<string, unknown> = {}) {
  return {
    data: chain(),
    isLoading: false,
    isStreaming: true,
    error: null,
    lastUpdate: new Date(),
    refetch,
    ...over,
  }
}

vi.mock('@/api/scalping', () => ({
  scalpingApi: {
    getAllUnderlyings: (...a: unknown[]) => getAllUnderlyings(...a),
    getExpiry: (...a: unknown[]) => getExpiry(...a),
  },
}))

function chain(overrides: Partial<OptionChainResponse> = {}): OptionChainResponse {
  return {
    status: 'success',
    underlying: 'NIFTY',
    underlying_symbol: 'NIFTY',
    underlying_exchange: 'NSE_INDEX',
    underlying_ltp: 24175.65,
    underlying_prev_close: 24100,
    expiry_date: '01SEP26',
    atm_strike: 24200,
    greeks_included: true,
    chain: [
      {
        strike: 24150,
        ce: {
          symbol: 'NIFTY01SEP2624150CE',
          label: 'ITM1',
          ltp: 127.5,
          bid: 0,
          ask: 0,
          bid_qty: 0,
          ask_qty: 0,
          open: 0,
          high: 0,
          low: 0,
          prev_close: 0,
          volume: 0,
          oi: 4694000,
          lotsize: 65,
          tick_size: 0.05,
          implied_volatility: 12.4,
          delta: 0.55,
        },
        pe: {
          symbol: 'NIFTY01SEP2624150PE',
          label: 'OTM1',
          ltp: 50.55,
          bid: 0,
          ask: 0,
          bid_qty: 0,
          ask_qty: 0,
          open: 0,
          high: 0,
          low: 0,
          prev_close: 0,
          volume: 0,
          oi: 6184000,
          lotsize: 65,
          tick_size: 0.05,
          implied_volatility: 11.8,
          delta: -0.45,
        },
      },
      {
        strike: 24200,
        ce: {
          symbol: 'NIFTY01SEP2624200CE',
          label: 'ATM',
          ltp: 97.2,
          bid: 0,
          ask: 0,
          bid_qty: 0,
          ask_qty: 0,
          open: 0,
          high: 0,
          low: 0,
          prev_close: 0,
          volume: 0,
          oi: 9405000,
          lotsize: 65,
          tick_size: 0.05,
          implied_volatility: 12.1,
          delta: 0.5,
          gamma: 0.001902,
          theta: -15.7635,
          vega: 8.0937,
        },
        pe: null,
      },
    ],
    ...overrides,
  }
}

function renderPanel(onPick = vi.fn()) {
  render(<OptionChainPanel apiKey="k" onPick={onPick} />)
  return onPick
}

describe('OptionChainPanel', () => {
  beforeEach(() => {
    localStorage.clear()
    useOptionChainLive.mockReset()
    getAllUnderlyings.mockReset()
    getExpiry.mockReset()
    refetch.mockReset()
    getAllUnderlyings.mockResolvedValue({ status: 'success', data: ['NIFTY', 'BANKNIFTY'] })
    getExpiry.mockResolvedValue({ status: 'success', data: ['01SEP26', '08SEP26'] })
    useOptionChainLive.mockReturnValue(live())
  })

  it('streams the chain rather than polling it, and asks for the shared cadence', async () => {
    renderPanel()
    await waitFor(() => expect(useOptionChainLive).toHaveBeenCalled())

    // Greeks are no longer a flag on a REST call: the hook recomputes them
    // client-side on every tick batch, so they cost no broker call at all.
    //
    // The LAST call, not the first: the underlying and expiry arrive async, so
    // the first render asks with enabled false and nothing loaded.
    await waitFor(() => {
      const args = useOptionChainLive.mock.calls.at(-1) as unknown[]
      expect(args[6]).toMatchObject({ enabled: true, pauseWhenHidden: true })
    })
    const args = useOptionChainLive.mock.calls.at(-1) as unknown[]
    expect(args[1]).toBe('NIFTY')
    expect(args[2]).toBe('NFO')
    // Underlying and options are quoted on the same segment here.
    expect(args[3]).toBe('NFO')
  })

  it('charts the leg that was clicked', async () => {
    const onPick = renderPanel()
    await userEvent.click(await screen.findByTitle('Chart NIFTY01SEP2624200CE'))

    expect(onPick).toHaveBeenCalledWith({ symbol: 'NIFTY01SEP2624200CE', exchange: 'NFO' })
  })

  it('disables a leg the chain does not carry rather than charting nothing', async () => {
    renderPanel()
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    // The 24200 put is absent from this chain.
    expect(screen.queryByTitle('Chart NIFTY01SEP2624200PE')).not.toBeInTheDocument()
  })

  it('names the metric in the column header', async () => {
    const { container } = render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    // The notation sits in its own span (it must escape the container's
    // text-transform), so match on the header's rendered text rather than a
    // single node.
    const header = Array.from(container.querySelectorAll('div')).find((el) =>
      /^Calls .*Strike.*Puts /.test(el.textContent ?? '')
    )
    expect(header?.textContent).toBe('Calls LTPStrikePuts LTP')
  })

  it('shows a dash for a leg with no implied volatility rather than a zero', async () => {
    useOptionChainLive.mockReturnValue(
      live({ data: chain({
        chain: [
          {
            strike: 24200,
            ce: {
              symbol: 'NIFTY01SEP2624200CE',
              label: 'ATM',
              ltp: 0,
              bid: 0,
              ask: 0,
              bid_qty: 0,
              ask_qty: 0,
              open: 0,
              high: 0,
              low: 0,
              prev_close: 0,
              volume: 0,
              oi: 0,
              lotsize: 65,
              tick_size: 0.05,
            },
            pe: null,
          },
        ],
      }) })
    )
    renderPanel()
    // A zero would read as a real measurement of zero volatility.
    // '24200' is both the ATM readout and the strike cell, hence getAllByText.
    await waitFor(() => expect(screen.getAllByText('24200').length).toBeGreaterThan(0))
    expect(screen.getAllByText('-').length).toBeGreaterThan(0)
  })

  it('re-requests the chain when the contract changes', async () => {
    // Dropping a response from a contract the user has already left is the
    // hook's job now, and is covered in hooks/useOptionChainPolling.test.tsx
    // under 'request identity'. What the panel still owns is asking for the
    // right contract in the first place.
    renderPanel()
    await waitFor(() => expect(useOptionChainLive).toHaveBeenCalled())

    const expiry = screen.getAllByRole('combobox').find((el) => el.textContent === '01SEP26')
    await userEvent.click(expiry as HTMLElement)
    await userEvent.click(await screen.findByRole('option', { name: '08SEP26' }))

    await waitFor(() =>
      expect(useOptionChainLive.mock.calls.some((c) => c[4] === '08SEP26')).toBe(true)
    )
  })

  it('does not paint the spot red when there is no previous close', async () => {
    useOptionChainLive.mockReturnValue(live({ data: chain({ underlying_prev_close: 0 }) }))
    renderPanel()

    const spot = await screen.findByText('24175.65')
    // Flat, not "down": no previous close means no direction to report.
    expect(spot.className).not.toContain('rose')
    expect(spot.className).toContain('text-foreground')
  })

  it('colours a rising spot with the theme-aware pair, not a bare green', async () => {
    renderPanel()
    const spot = await screen.findByText('24175.65')

    expect(spot.className).toContain('text-emerald-600')
    expect(spot.className).toContain('dark:text-emerald-400')
  })

  it('gives every leg button an accessible name, not just a title', async () => {
    // title does not become the accessible name on a button that already has
    // text, so without aria-label a screen reader announced a button called
    // "97.20".
    renderPanel()
    // The name carries the value too, so the number is not lost to the label.
    expect(await screen.findByLabelText('Chart NIFTY01SEP2624200CE, LTP 97.20')).toBeInTheDocument()
  })

  it('colours calls green and puts red, matching the platform option chain', async () => {
    // pages/OptionChain.tsx paints CE green and PE red. The same chain with the
    // colours swapped in another tab is a way to read resistance as support.
    const { container } = render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    const metric = screen.getAllByRole('combobox').find((el) => el.textContent === 'LTP')
    await userEvent.click(metric as HTMLElement)
    await userEvent.click(await screen.findByRole('option', { name: 'OI' }))

    await waitFor(() => {
      expect(container.querySelector('[class*="from-emerald-500"]')).not.toBeNull()
      expect(container.querySelector('[class*="from-rose-500"]')).not.toBeNull()
    })
  })

  it('reports a failed load as an error with a retry, not as a missing contract', async () => {
    useOptionChainLive.mockReturnValue(live({ data: null, error: 'network down' }))
    renderPanel()

    expect(await screen.findByText('network down')).toBeInTheDocument()
    // Never blame the user's expiry or master contracts for a network failure.
    expect(screen.queryByText(/master contracts are downloaded/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('does not paint the ATM strike as a solid slab', async () => {
    // --primary is near-black in light and near-white in dark, so bg-primary
    // would put the loudest element on the page inside a 21-row table.
    const { container } = render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    const atm = Array.from(container.querySelectorAll('span')).find(
      (el) => el.textContent === '24200' && el.className.includes('ring-inset')
    )
    expect(atm).toBeDefined()
    expect(atm?.className).toContain('bg-primary/10')
  })

  it.each([
    ['LTP', '97.20'],
    ['OI', '94.05L'],
    ['Volume', '-'],
    ['IV', '12.1%'],
    ['Delta', '0.50'],
    // Four decimals, not two. Gamma on an index option is about 0.0019, so at
    // delta's precision every strike on the board would read 0.00.
    ['Gamma', '0.0019'],
    ['Theta', '-15.76'],
    ['Vega', '8.09'],
  ])('renders %s at a precision that shows the number', async (name, expected) => {
    const { container } = render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    const trigger = screen.getAllByRole('combobox').find((el) => el.textContent === 'LTP')
    await userEvent.click(trigger as HTMLElement)
    await userEvent.click(await screen.findByRole('option', { name: new RegExp(name) }))

    await waitFor(() => {
      const atm = Array.from(container.querySelectorAll('[class*="grid-cols"]')).find((row) =>
        row.textContent?.includes('24200')
      )
      expect(atm?.textContent).toContain(expected)
    })
  })

  it('offers every Greek, grouped away from the price metrics', async () => {
    renderPanel()
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    const trigger = screen.getAllByRole('combobox').find((el) => el.textContent === 'LTP')
    await userEvent.click(trigger as HTMLElement)

    for (const name of ['LTP', 'OI', 'Volume', 'IV', 'Delta', 'Gamma', 'Theta', 'Vega']) {
      expect(await screen.findByRole('option', { name: new RegExp(name) })).toBeInTheDocument()
    }
    expect(screen.getByText('Greeks')).toBeInTheDocument()
    expect(screen.getByText('Price')).toBeInTheDocument()
  })

  it('marks the charted leg without erasing its moneyness', async () => {
    // The active state used to override the background with !important, which
    // beat the amber out-of-the-money tint as well, so the charted leg read as
    // at-the-money. It is a ring now, and the fact is stated in aria-current
    // rather than left to a class jsdom cannot evaluate.
    render(<OptionChainPanel apiKey="k" onPick={vi.fn()} activeSymbol="NFO:NIFTY01SEP2624200CE" />)
    const leg = await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    expect(leg).toHaveAttribute('aria-current', 'true')
    expect(leg.className).not.toContain('!bg-accent')
    expect(screen.getByTitle('Chart NIFTY01SEP2624150CE')).not.toHaveAttribute('aria-current')
  })

  it('offers buy and sell on every leg without nesting a button in a button', async () => {
    const { container } = render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    expect(screen.getByLabelText('Buy NIFTY01SEP2624200CE')).toBeInTheDocument()
    expect(screen.getByLabelText('Sell NIFTY01SEP2624200CE')).toBeInTheDocument()

    // A button inside a button is invalid HTML and behaves like it, which is
    // why the pills are siblings of the chart button rather than children.
    expect(container.querySelector('button button')).toBeNull()
  })

  it('opens the shared order dialog rather than placing anything itself', async () => {
    render(<OptionChainPanel apiKey="k" onPick={vi.fn()} />)
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    await userEvent.click(screen.getByLabelText('Sell NIFTY01SEP2624200CE'))

    // Quantity, product and price type are confirmed in the dialog, so a pill
    // starts an order and never places one.
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('NIFTY01SEP2624200CE')
    expect(dialog.textContent).toContain('SELL')
  })

  it('does not offer an order on a leg the chain does not carry', async () => {
    renderPanel()
    await screen.findByTitle('Chart NIFTY01SEP2624200CE')

    // The 24200 put is absent from this fixture.
    expect(screen.queryByLabelText('Buy NIFTY01SEP2624200PE')).not.toBeInTheDocument()
  })
})
