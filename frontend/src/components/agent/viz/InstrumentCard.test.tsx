/**
 * What this pins.
 *
 * The live layer is stubbed, not the wiring around it: the real parser, the
 * real formatters and the real composer channel all run, so a field that
 * stopped being read or a number that stopped being grouped would fail here.
 * Only `useLiveQuote`, `useMarketStatus` and the chart engine are stubs,
 * because none of them can be reached from jsdom and none of them is what this
 * card is.
 *
 * Four of these tests are about **absence**, which is unusual and deliberate:
 *
 * - A card with only a quote must draw only a quote. Every other section is
 *   optional and the frame very often carries none of them.
 * - Nothing held draws nothing. Not a zero, not the word flat, and in
 *   particular nothing that would read the same whether the position book
 *   answered "you hold none" or never answered at all.
 * - Open interest is a number on a contract that has one, and meaningless on
 *   equity.
 * - **There is no fundamentals tile, and there is no placeholder for one.**
 *   OpenAlgo has no fundamentals source. A dash or an empty tile is an
 *   invitation to fill it, and a number a model remembered would be
 *   indistinguishable to a reader from one the broker returned.
 *
 * And one is about safety: the Buy control writes a sentence into the composer
 * and does nothing else. If that ever becomes a call to an order tool it
 * bypasses the human approval gate every order in this product stops at, and
 * this test is what fails first.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { subscribeComposerPrefill } from '@/lib/agent/composer'
import { InstrumentCard } from './InstrumentCard'

const harness = vi.hoisted(() => ({
  live: { data: {} as Record<string, unknown>, isLive: false },
  marketOpen: false,
  charts: [] as Array<Record<string, unknown>>,
}))

vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: () => ({
    data: harness.live.data,
    isLive: harness.live.isLive,
    isConnected: false,
    isLoading: false,
    isPaused: false,
    isFallbackMode: false,
    dataSource: 'none',
    refresh: async () => {},
  }),
}))

vi.mock('@/hooks/useMarketStatus', () => ({
  useMarketStatus: () => ({
    isMarketOpen: () => harness.marketOpen,
    isAnyMarketOpen: () => harness.marketOpen,
    isHolidayForExchange: () => false,
    getMarketStatus: () => null,
    timings: [],
    holidays: [],
    isLoading: false,
    error: null,
  }),
}))

// The chart is CandleViz, and CandleViz has its own tests. What matters here is
// that this card mounts it inline and hands it the bars it was given, rather
// than growing a second driver of the engine.
vi.mock('./CandleViz', () => ({
  CandleViz: (props: Record<string, unknown>) => {
    harness.charts.push(props)
    return <div data-testid="chart" />
  },
}))

function bar(time: number, close: number, volume = 1000) {
  return { time, open: close, high: close, low: close, close, volume }
}

/** A quote and nothing else, which is the minimum a card is ever built from. */
const QUOTE_ONLY = {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  currency: 'INR',
  mode: 'live',
  as_of: '2026-09-03T17:50:50+05:30',
  timezone: 'Asia/Kolkata',
  is_derivative: false,
  is_index: false,
  quote: { ltp: 1302.5, prev_close: 1313.1 },
  change: -10.6,
  change_percent: -0.81,
}

const FULL = {
  ...QUOTE_ONLY,
  quote: {
    ltp: 1302.5,
    open: 1314.0,
    high: 1316.8,
    low: 1302.5,
    prev_close: 1313.1,
    volume: 15200000,
    bid: 1302.45,
    ask: 1302.6,
  },
  instrument: {
    name: 'RELIANCE INDUSTRIES',
    instrument_type: 'EQ',
    lot_size: 1,
    tick_size: 0.05,
  },
  intraday: {
    interval: '5m',
    sessions: ['2026-09-03'],
    bar_count: 3,
    has_volume: true,
    bars: [bar(1780444800, 1314), bar(1780445100, 1310), bar(1780445400, 1302.5)],
  },
  week_52: {
    high: 1608.8,
    low: 1114.85,
    start_date: '2025-08-27',
    end_date: '2026-09-03',
    bar_count: 248,
    full_year: true,
    first_date: '2025-08-27',
    from_high_percent: -19.04,
  },
  depth: {
    bids: [
      { price: 1302.45, quantity: 430 },
      { price: 1302.4, quantity: 1200 },
    ],
    asks: [
      { price: 1302.6, quantity: 275 },
      { price: 1302.65, quantity: 980 },
    ],
    total_buy_quantity: 412000,
    total_sell_quantity: 388500,
  },
  notices: ['Depth is the broker snapshot at the time of the answer.'],
}

const FUTURE = {
  ...QUOTE_ONLY,
  symbol: 'NIFTY29SEP26FUT',
  exchange: 'NFO',
  is_derivative: true,
  quote: { ltp: 24180.5, prev_close: 24100.0, oi: 4500000, volume: 812000 },
  instrument: {
    name: 'NIFTY',
    instrument_type: 'FUT',
    expiry: '29-SEP-26',
    lot_size: 75,
    tick_size: 0.05,
  },
}

beforeEach(() => {
  harness.live.data = {}
  harness.live.isLive = false
  harness.marketOpen = false
  harness.charts.length = 0
})

describe('InstrumentCard', () => {
  it('renders a card from the quote alone', () => {
    render(<InstrumentCard spec={QUOTE_ONLY} title="RELIANCE NSE" source="quotes_service" />)

    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('NSE')).toBeInTheDocument()
    expect(screen.getByText('1,302.50')).toBeInTheDocument()
    expect(screen.getByText('-10.60 (0.81%)')).toBeInTheDocument()
    expect(screen.getByText('1,313.10')).toBeInTheDocument()

    // Every optional section, absent.
    expect(screen.queryByTestId('chart')).toBeNull()
    expect(screen.queryByText('Day range')).toBeNull()
    expect(screen.queryByText('52 week range')).toBeNull()
    expect(screen.queryByText('Bids')).toBeNull()
    expect(screen.queryByText('Your position')).toBeNull()
    expect(screen.queryByText('Open interest')).toBeNull()
  })

  it('carries no fundamentals, and no placeholder where one would go', () => {
    render(<InstrumentCard spec={FULL} source="quotes_service" />)
    const card = screen.getByRole('figure')

    for (const absent of [
      /p\/e/i,
      /market cap/i,
      /eps/i,
      /dividend/i,
      /book value/i,
      /beta/i,
      /target/i,
      /not available/i,
      /^-$/,
    ]) {
      expect(within(card).queryByText(absent)).toBeNull()
    }
  })

  it('paints the served values first and lets the live quote take over', () => {
    const view = render(<InstrumentCard spec={FULL} source="quotes_service" />)
    // Nothing has ticked yet, and the card is already complete. A message can
    // be scrolled to an hour after its turn, so this is the state it spends
    // most of its life in. Read off the figure's own label, because the served
    // last price is also the session low and appears more than once.
    expect(screen.getByRole('figure').getAttribute('aria-label')).toContain('last 1,302.50')
    expect(screen.getByText('Closed')).toBeInTheDocument()
    expect(screen.getByText(/Market closed\. Last read 2026-09-03 17:50 IST/)).toBeInTheDocument()

    harness.live.data = { ltp: 1310.25, close: 1313.1, high: 1316.8, low: 1302.5 }
    harness.live.isLive = true
    harness.marketOpen = true
    view.rerender(<InstrumentCard spec={FULL} source="quotes_service" />)

    expect(screen.getByText('1,310.25')).toBeInTheDocument()
    // Derived from the price on screen, so the two can never disagree.
    expect(screen.getByText('-2.85 (0.22%)')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.queryByText(/Last read/)).toBeNull()
  })

  it('draws the intraday session through the shared chart, inline', () => {
    render(<InstrumentCard spec={FULL} source="quotes_service" />)

    expect(screen.getByTestId('chart')).toBeInTheDocument()
    expect(harness.charts).toHaveLength(1)
    expect(harness.charts[0].variant).toBe('inline')
    const spec = harness.charts[0].spec as { bars: unknown[]; interval: string }
    expect(spec.bars).toHaveLength(3)
    expect(spec.interval).toBe('5m')
    expect(screen.getByText('5m bars, 3 shown')).toBeInTheDocument()
  })

  it('shows where the last price sits in the day and the year', () => {
    render(<InstrumentCard spec={FULL} />)

    expect(
      screen.getByLabelText('Day range: 1,302.50 to 1,316.80, last 1,302.50')
    ).toBeInTheDocument()
    expect(
      screen.getByLabelText('52 week range: 1,114.85 to 1,608.80, last 1,302.50')
    ).toBeInTheDocument()
    expect(screen.getByText('19.0% from high')).toBeInTheDocument()
  })

  it('names the window rather than calling a short one a year', () => {
    const short = {
      ...QUOTE_ONLY,
      week_52: { high: 1400, low: 1200, full_year: false, first_date: '2026-07-01' },
    }
    render(<InstrumentCard spec={short} />)

    expect(screen.getByText('Range since 2026-07-01')).toBeInTheDocument()
    expect(screen.queryByText('52 week range')).toBeNull()
  })

  it('renders both sides of the order book', () => {
    render(<InstrumentCard spec={FULL} />)

    expect(screen.getByText('Bids')).toBeInTheDocument()
    expect(screen.getByText('Asks')).toBeInTheDocument()

    const [bids, asks] = screen.getAllByRole('table')
    expect(within(bids).getByText('1,302.45')).toBeInTheDocument()
    expect(within(bids).getByText('430')).toBeInTheDocument()
    expect(within(asks).getByText('1,302.60')).toBeInTheDocument()
    expect(within(asks).getByText('275')).toBeInTheDocument()
    expect(screen.getByText('4.12 L')).toBeInTheDocument()
    expect(screen.getByText('3.88 L')).toBeInTheDocument()
  })

  it('shows open interest on a contract that has one', () => {
    render(<InstrumentCard spec={FUTURE} />)

    expect(screen.getByText('Open interest')).toBeInTheDocument()
    expect(screen.getByText('45.00 L')).toBeInTheDocument()
    expect(screen.getByText('FUT')).toBeInTheDocument()
    expect(screen.getByText('NIFTY, Expiry 29-SEP-26, Lot 75')).toBeInTheDocument()
  })

  it('shows no open interest on equity, where it means nothing', () => {
    // The same field, present in the payload, and deliberately not drawn: it is
    // the instrument that decides whether the number exists, not the feed.
    render(<InstrumentCard spec={{ ...FULL, quote: { ...FULL.quote, oi: 4500000 } }} />)

    expect(screen.queryByText('Open interest')).toBeNull()
  })

  it('makes a loss on a held position unmistakable', () => {
    const held = {
      ...FULL,
      position: {
        held: true,
        quantity: 250,
        side: 'long',
        average_price: 1322.3,
        pnl: -4950.75,
        pnl_percent: -1.5,
        legs: [{ product: 'CNC', quantity: 250, average_price: 1322.3, pnl: -4950.75 }],
      },
    }
    render(<InstrumentCard spec={held} />)

    expect(screen.getByText('Your position')).toBeInTheDocument()
    expect(screen.getByText('long')).toBeInTheDocument()
    expect(screen.getByText('250')).toBeInTheDocument()
    expect(screen.getByText('1,322.30')).toBeInTheDocument()
    // The word, not only the colour: a red number is not readable to everyone
    // and is not readable at all to a screen reader.
    const pnl = screen.getByText('Unrealised loss')
    expect(pnl).toBeInTheDocument()
    expect(screen.getByText('-4,950.75 (1.50%)')).toBeInTheDocument()
  })

  it('lists the legs when a position is held across two products', () => {
    const held = {
      ...FULL,
      position: {
        held: true,
        quantity: 300,
        side: 'long',
        pnl: 1200,
        legs: [
          { product: 'CNC', quantity: 250, average_price: 1290, pnl: 3125 },
          { product: 'MIS', quantity: 50, average_price: 1341, pnl: -1925 },
        ],
      },
    }
    render(<InstrumentCard spec={held} />)

    expect(screen.getByText('CNC')).toBeInTheDocument()
    expect(screen.getByText('MIS')).toBeInTheDocument()
    expect(screen.getByText('Unrealised gain')).toBeInTheDocument()
    // No average price across two products: an average of two averages is not
    // a price anybody paid, so the backend omits it and so does the card.
    expect(screen.queryByText('Average')).toBeNull()
  })

  it.each([
    ['no position section at all', undefined],
    ['a book that answered nothing is held', { held: false }],
  ])('draws nothing for %s', (_name, position) => {
    render(<InstrumentCard spec={{ ...FULL, position }} />)

    expect(screen.queryByText('Your position')).toBeNull()
    expect(screen.queryByText(/Unrealised/)).toBeNull()
    expect(screen.queryByText('Quantity')).toBeNull()
  })

  it('names a section that could not be read rather than drawing it as empty', () => {
    // The position is the case that matters. A book that answered "you hold
    // none" and a book that never answered draw the same empty space, so the
    // only thing keeping them apart on screen is this line.
    const failed = {
      ...FULL,
      position: undefined,
      unavailable: { position: 'RetryAgentRun: the broker rejected the position book request' },
    }
    render(<InstrumentCard spec={failed} />)

    expect(screen.queryByText('Your position')).toBeNull()
    expect(
      screen.getByText(
        /Could not read your position: RetryAgentRun: the broker rejected the position book/
      )
    ).toBeInTheDocument()
  })

  it('says nothing about an order book an index never had', () => {
    const index = {
      ...QUOTE_ONLY,
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      is_index: true,
      quote: { ltp: 23873.45, prev_close: 23914.45 },
      unavailable: { depth: 'there are no resting orders on either side' },
    }
    render(<InstrumentCard spec={index} />)

    expect(screen.queryByText(/Could not read/)).toBeNull()
  })

  it.each([
    ['null', null],
    ['a string', 'RELIANCE'],
    ['an empty object', {}],
    ['a symbol with no quote', { symbol: 'RELIANCE', exchange: 'NSE' }],
    ['a quote with no last price', { symbol: 'X', exchange: 'NSE', quote: {} }],
    ['a last price of zero', { symbol: 'X', exchange: 'NSE', quote: { ltp: 0 } }],
    ['sections of the wrong shape', { ...QUOTE_ONLY, depth: 7, position: 'yes', intraday: [] }],
  ])('renders rather than throwing for %s', (_name, spec) => {
    expect(() => render(<InstrumentCard spec={spec} title="RELIANCE NSE" />)).not.toThrow()
  })

  it('says so when the quote could not be read', () => {
    render(<InstrumentCard spec={{ symbol: 'X', exchange: 'NSE', quote: {} }} title="X NSE" />)

    expect(screen.getByText(/could not be drawn/)).toBeInTheDocument()
  })
})

describe('InstrumentCard order controls', () => {
  const sent: string[] = []
  let release: (() => void) | null = null

  beforeEach(() => {
    sent.length = 0
    release = subscribeComposerPrefill((text) => sent.push(text))
  })

  afterEach(() => {
    release?.()
    release = null
  })

  it('writes a request into the composer and places nothing', async () => {
    render(<InstrumentCard spec={FULL} />)

    await userEvent.click(screen.getByRole('button', { name: 'Buy' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sell' }))

    // A sentence, for a human to read and send. Not an order, not a tool call,
    // and nothing that could reach a broker without passing the approval gate.
    expect(sent).toEqual([
      'Buy 1 share of RELIANCE on NSE at market.',
      'Sell 1 share of RELIANCE on NSE at market.',
    ])
  })

  it('asks for a lot, not a share, on a derivative', async () => {
    render(<InstrumentCard spec={FUTURE} />)

    await userEvent.click(screen.getByRole('button', { name: 'Buy' }))
    expect(sent).toEqual(['Buy 1 lot (75 quantity) of NIFTY29SEP26FUT on NFO at market.'])
  })

  it('offers nothing on an index, which cannot be traded', () => {
    const index = {
      ...QUOTE_ONLY,
      symbol: 'NIFTY',
      exchange: 'NSE_INDEX',
      is_index: true,
      quote: { ltp: 24180.5, prev_close: 24100 },
    }
    render(<InstrumentCard spec={index} />)

    expect(screen.queryByRole('button', { name: 'Buy' })).toBeNull()
    expect(screen.queryByText('Bids')).toBeNull()
  })
})

describe('InstrumentCard without a composer', () => {
  it('leaves the controls out rather than rendering two that do nothing', () => {
    // No composer has registered, which is every surface that mounts the thread
    // read-only. A control that quietly did nothing would be worse than none.
    render(<InstrumentCard spec={FULL} />)

    expect(screen.queryByRole('button', { name: 'Buy' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sell' })).toBeNull()
  })
})
