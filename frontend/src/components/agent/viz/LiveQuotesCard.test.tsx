/**
 * What this pins.
 *
 * The manager is replaced and everything above it is real: the actual
 * `useMarketData` hook, the actual parser, the actual formatters, the actual
 * budget. That choice is the point of the file. Mocking the hook would have
 * been easier and would have tested nothing that matters here, because what
 * matters here is the subscription lifecycle and the lifecycle lives in the
 * hook.
 *
 * Four of these are about honesty rather than about drawing:
 *
 * - **A card that is not streaming says which of the reasons it is.** Not
 *   connected, polling over REST, market closed and queued behind other cards
 *   are four different things for an operator to do about it, and a card
 *   showing a two minute old poll while looking exactly like one taking ticks
 *   is the failure this card exists to prevent.
 * - **A seeded value is labelled as one.** Only a value the WebSocket actually
 *   delivered is called a tick.
 * - **Unmounting releases every subscription.** A thread mounts cards without
 *   limit and never gets a chance to clean up later.
 * - **The number of cards streaming at once is bounded**, and the card that is
 *   held says so instead of quietly showing a frozen price.
 */

import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/MarketDataManager', () => import('@/test/marketDataHarness'))

import { feed } from '@/test/marketDataHarness'
import { LiveQuotesCard } from './LiveQuotesCard'
import { BUDGET, MAX_LIVE_CARDS } from './live'

const HOUR = 3_600_000

/** A session that is open right now, so the card is not simply "closed". */
function openToday() {
  return {
    date: '2026-09-03',
    as_of: '2026-09-03T12:44:12+05:30',
    timezone: 'Asia/Kolkata',
    known: true,
    exchanges: [
      {
        exchange: 'NSE',
        known: true,
        is_open: true,
        opens_at: Date.now() - HOUR,
        closes_at: Date.now() + HOUR,
      },
    ],
    is_open: true,
  }
}

/** The same session, over. `is_open` still says true, and must be ignored. */
function closedToday() {
  return {
    ...openToday(),
    exchanges: [
      {
        exchange: 'NSE',
        known: true,
        // Deliberately stale: this is the verdict the backend reached when it
        // drew the card, and the card is being read hours later.
        is_open: true,
        opens_at: Date.now() - 5 * HOUR,
        closes_at: Date.now() - 2 * HOUR,
      },
    ],
    is_open: true,
  }
}

const RELIANCE = {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  calendar_exchange: 'NSE',
  is_index: false,
  is_derivative: false,
  seed: {
    ltp: 1302.5,
    open: 1314.0,
    high: 1316.8,
    low: 1302.5,
    prev_close: 1313.1,
    volume: 15200000,
    bid: 1302.45,
    ask: 1302.6,
  },
  change: -10.6,
  change_percent: -0.81,
}

const NIFTY = {
  symbol: 'NIFTY',
  exchange: 'NSE_INDEX',
  calendar_exchange: 'NSE',
  is_index: true,
  is_derivative: false,
  seed: { ltp: 23873.45, prev_close: 23914.45 },
  change: -41.0,
  change_percent: -0.17,
}

function spec(mode: string, extra: Record<string, unknown> = {}) {
  return {
    mode,
    currency: 'INR',
    account_mode: 'live',
    as_of: '2026-09-03T12:44:12+05:30',
    timezone: 'Asia/Kolkata',
    instruments: [RELIANCE, NIFTY],
    subscribe: [
      { symbol: 'RELIANCE', exchange: 'NSE' },
      { symbol: 'NIFTY', exchange: 'NSE_INDEX' },
    ],
    market: openToday(),
    ...extra,
  }
}

const DEPTH_SPEC = {
  ...spec('Depth'),
  instruments: [
    {
      ...RELIANCE,
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
    },
  ],
  subscribe: [{ symbol: 'RELIANCE', exchange: 'NSE' }],
}

beforeEach(() => {
  feed.reset()
  BUDGET.reset()
})

describe('LiveQuotesCard modes', () => {
  it('draws a price, a change and a percent per instrument in LTP mode', () => {
    render(<LiveQuotesCard spec={spec('LTP')} source="quotes_service" />)

    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('1,302.50')).toBeInTheDocument()
    expect(screen.getByText('-10.60 (0.81%)')).toBeInTheDocument()
    expect(screen.getByText('NIFTY')).toBeInTheDocument()
    expect(screen.getByText('23,873.45')).toBeInTheDocument()

    // LTP carries no session, so the card draws none rather than drawing
    // labels over blanks.
    expect(screen.queryByText('Open')).toBeNull()
    expect(screen.queryByText('Volume')).toBeNull()
    expect(screen.queryByText('Bids')).toBeNull()
  })

  it('adds the session and the top of book in Quote mode', () => {
    render(<LiveQuotesCard spec={spec('Quote')} source="quotes_service" />)
    // Scoped to the first instrument: every row draws the same labels, which
    // is the point of the grid.
    const row = within(screen.getAllByRole('listitem')[0])

    expect(row.getByText('Open')).toBeInTheDocument()
    expect(row.getByText('1,314.00')).toBeInTheDocument()
    expect(row.getByText('High')).toBeInTheDocument()
    expect(row.getByText('1,316.80')).toBeInTheDocument()
    expect(row.getByText('Low')).toBeInTheDocument()
    expect(row.getByText('Prev close')).toBeInTheDocument()
    expect(row.getByText('1,313.10')).toBeInTheDocument()
    expect(row.getByText('Volume')).toBeInTheDocument()
    expect(row.getByText('1.52 Cr')).toBeInTheDocument()
    expect(row.getByText('Bid')).toBeInTheDocument()
    expect(row.getByText('1,302.45')).toBeInTheDocument()
    expect(row.getByText('Ask')).toBeInTheDocument()
    expect(row.getByText('1,302.60')).toBeInTheDocument()
    expect(screen.queryByText('Bids')).toBeNull()
  })

  it('draws both sides of the ladder with their sizes in Depth mode', () => {
    render(<LiveQuotesCard spec={DEPTH_SPEC} source="depth_service" />)

    const [bids, asks] = screen.getAllByRole('table')
    expect(within(bids).getByText('1,302.45')).toBeInTheDocument()
    expect(within(bids).getByText('430')).toBeInTheDocument()
    expect(within(bids).getByText('1,200')).toBeInTheDocument()
    expect(within(asks).getByText('1,302.60')).toBeInTheDocument()
    expect(within(asks).getByText('275')).toBeInTheDocument()
    // Totals, shortened, because they are read rather than typed.
    expect(screen.getByText('4.12 L')).toBeInTheDocument()
    expect(screen.getByText('3.88 L')).toBeInTheDocument()
  })
})

describe('LiveQuotesCard honesty', () => {
  it('renders the served snapshot before anything ticks, and says it is one', () => {
    render(<LiveQuotesCard spec={spec('LTP')} />)

    // This is the state a card spends most of its life in: a message scrolled
    // back to long after the turn that produced it.
    expect(screen.getByText('1,302.50')).toBeInTheDocument()
    expect(screen.getAllByText('snapshot 2026-09-03 12:44 IST')).toHaveLength(2)
    expect(screen.getByText(/Nothing has arrived yet/)).toBeInTheDocument()
    expect(screen.getByText('Waiting')).toBeInTheDocument()
  })

  it('updates a value on a tick and marks that value as a tick', () => {
    render(<LiveQuotesCard spec={spec('LTP')} />)

    act(() => {
      feed.push('RELIANCE', 'NSE', { ltp: 1310.25 })
    })

    expect(screen.getByText('1,310.25')).toBeInTheDocument()
    expect(screen.queryByText('1,302.50')).toBeNull()
    // Derived from the price on screen against the served previous close, so
    // the price and its move can never disagree in front of the reader.
    expect(screen.getByText('-2.85 (0.22%)')).toBeInTheDocument()
    expect(screen.getByText(/^tick/)).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    // The instrument that has not ticked is still labelled a snapshot.
    expect(screen.getByText('snapshot 2026-09-03 12:44 IST')).toBeInTheDocument()
  })

  it('stops calling a value live once it has stopped arriving', () => {
    render(<LiveQuotesCard spec={spec('LTP')} />)
    act(() => {
      // Connected, subscribed, market open, and the last thing the feed said
      // about this instrument was three minutes ago.
      feed.push('RELIANCE', 'NSE', { ltp: 1310.25 }, 'websocket', Date.now() - 180_000)
    })

    expect(screen.getByText('Delayed')).toBeInTheDocument()
    expect(screen.getByText(/the last update was 3m ago/)).toBeInTheDocument()
    expect(screen.queryByText('Live')).toBeNull()
  })

  it('says it is not connected rather than showing a still price as live', () => {
    render(<LiveQuotesCard spec={spec('LTP')} />)
    act(() => {
      feed.setState({ isConnected: false, isAuthenticated: false })
    })

    expect(screen.getByText('Not connected')).toBeInTheDocument()
    expect(screen.getByText(/nothing here is moving/)).toBeInTheDocument()
  })

  it('calls a REST poll a poll and not a tick', () => {
    render(<LiveQuotesCard spec={spec('LTP')} />)
    act(() => {
      feed.setState({ isFallbackMode: true })
      feed.push('RELIANCE', 'NSE', { ltp: 1310.25 }, 'rest')
    })

    expect(screen.getByText('Polling')).toBeInTheDocument()
    expect(screen.getByText(/REST polls rather than ticks/)).toBeInTheDocument()
    expect(screen.getByText(/^polled/)).toBeInTheDocument()
    expect(screen.queryByText(/^tick/)).toBeNull()
  })

  it('recomputes the session against the clock rather than trusting is_open', () => {
    // The frame says `is_open: true` throughout, because it did when it was
    // drawn. The window says the session ended two hours ago, and the window
    // is what a card read later has to go by.
    render(<LiveQuotesCard spec={spec('LTP', { market: closedToday() })} />)

    expect(screen.getByText('Closed')).toBeInTheDocument()
    expect(screen.getByText(/Market closed/)).toBeInTheDocument()
  })

  it('says nothing about the session when the calendar could not be read', () => {
    render(<LiveQuotesCard spec={spec('LTP', { market: { known: false, exchanges: [] } })} />)

    expect(screen.queryByText(/Market closed/)).toBeNull()
    expect(screen.getByText('Waiting')).toBeInTheDocument()
  })

  it('names an instrument that was refused, so it does not look unasked for', () => {
    render(
      <LiveQuotesCard
        spec={spec('LTP', {
          refused: [
            {
              symbol: 'NOTAREALSYMBOL',
              exchange: 'NSE',
              reason: 'no row in the instrument master, so it would never tick',
            },
          ],
        })}
      />
    )

    expect(
      screen.getByText(/NOTAREALSYMBOL on NSE is not on this card: no row in the instrument master/)
    ).toBeInTheDocument()
  })

  it('says why a row has no opening quote instead of drawing blanks', () => {
    render(
      <LiveQuotesCard
        spec={spec('Quote', {
          instruments: [
            {
              ...RELIANCE,
              seed: undefined,
              unavailable: { seed: 'the broker returned no quote for this instrument' },
            },
          ],
        })}
      />
    )

    expect(
      screen.getByText(/Could not read the opening quote: the broker returned no quote/)
    ).toBeInTheDocument()
    expect(screen.getByText('No price yet')).toBeInTheDocument()
  })
})

describe('LiveQuotesCard subscriptions', () => {
  it('subscribes exactly the frame set, in the frame mode, and releases it on unmount', () => {
    const view = render(<LiveQuotesCard spec={spec('Depth')} />)

    // Through the one shared manager. Nothing here opened a socket of its own.
    expect(feed.live()).toEqual(['NSE:RELIANCE:Depth', 'NSE_INDEX:NIFTY:Depth'])

    view.unmount()

    // Every path, without exception. A conversation mounts cards without limit
    // and never gets a second chance to clean up after one.
    expect(feed.live()).toEqual([])
    expect(feed.closed.sort()).toEqual(['NSE:RELIANCE:Depth', 'NSE_INDEX:NIFTY:Depth'])
  })

  it('bounds how many cards stream at once and says so on the one that is held', async () => {
    const cards = Array.from({ length: MAX_LIVE_CARDS + 1 }, (_, index) => (
      <LiveQuotesCard
        key={index}
        spec={{
          ...spec('LTP'),
          instruments: [{ ...RELIANCE, symbol: `SYM${index}` }],
          subscribe: [{ symbol: `SYM${index}`, exchange: 'NSE' }],
        }}
      />
    ))
    render(<div>{cards}</div>)

    // Four subscribed, the fifth queued behind them rather than adding a fifth
    // instrument's worth of feed to the tab.
    expect(feed.live()).toHaveLength(MAX_LIVE_CARDS)
    expect(feed.live()).not.toContain(`NSE:SYM${MAX_LIVE_CARDS}:LTP`)
    expect(
      screen.getByText(new RegExp(`${MAX_LIVE_CARDS} cards are already live`))
    ).toBeInTheDocument()

    // And the operator can take a slot rather than being stuck behind them.
    await userEvent.click(screen.getByRole('button', { name: 'Stream this one instead' }))
    expect(feed.live()).toHaveLength(MAX_LIVE_CARDS)
    expect(feed.live()).toContain(`NSE:SYM${MAX_LIVE_CARDS}:LTP`)
  })

  it('hands a released slot to the card that was waiting for it', () => {
    function Cards({ first }: { first: boolean }) {
      return (
        <div>
          {first && (
            <LiveQuotesCard
              spec={{
                ...spec('LTP'),
                instruments: [{ ...RELIANCE, symbol: 'FIRST' }],
                subscribe: [{ symbol: 'FIRST', exchange: 'NSE' }],
              }}
            />
          )}
          {Array.from({ length: MAX_LIVE_CARDS }, (_, index) => (
            <LiveQuotesCard
              key={index}
              spec={{
                ...spec('LTP'),
                instruments: [{ ...RELIANCE, symbol: `REST${index}` }],
                subscribe: [{ symbol: `REST${index}`, exchange: 'NSE' }],
              }}
            />
          ))}
        </div>
      )
    }

    const view = render(<Cards first />)
    expect(feed.live()).not.toContain(`NSE:REST${MAX_LIVE_CARDS - 1}:LTP`)

    view.rerender(<Cards first={false} />)
    expect(feed.live()).toContain(`NSE:REST${MAX_LIVE_CARDS - 1}:LTP`)
    expect(feed.live()).toHaveLength(MAX_LIVE_CARDS)
  })
})

describe('LiveQuotesCard malformed frames', () => {
  it.each([
    ['null', null],
    ['a string', 'RELIANCE'],
    ['an empty object', {}],
    ['no instruments', { mode: 'LTP', instruments: [] }],
    ['instruments of the wrong shape', { mode: 'LTP', instruments: [7, 'x', null] }],
    ['sections of the wrong shape', { ...spec('Depth'), market: 5, refused: 'no', notices: 3 }],
    ['a seed that is not an object', { ...spec('Quote'), instruments: [{ ...RELIANCE, seed: 4 }] }],
    ['a mode nobody has', { ...spec('Sonar') }],
  ])('renders rather than throwing for %s', (_name, value) => {
    expect(() => render(<LiveQuotesCard spec={value} title="Live" />)).not.toThrow()
  })

  it('says so when the frame carried no instrument at all', () => {
    render(<LiveQuotesCard spec={{ mode: 'LTP', instruments: [] }} title="Live quotes" />)

    expect(screen.getByText(/could not be drawn/)).toBeInTheDocument()
    expect(feed.live()).toEqual([])
  })

  it('falls back to Quote for a mode the proxy does not have', () => {
    render(<LiveQuotesCard spec={spec('Sonar')} />)

    expect(screen.getByText('Live Quote')).toBeInTheDocument()
    expect(feed.live()).toEqual(['NSE:RELIANCE:Quote', 'NSE_INDEX:NIFTY:Quote'])
  })
})
