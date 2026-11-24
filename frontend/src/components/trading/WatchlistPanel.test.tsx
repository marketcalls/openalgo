import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Watchlist } from '@/api/watchlist'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { WatchlistPanel } from './WatchlistPanel'

/**
 * The API and the price hook are both mocked. What is under test here is the
 * panel's own behaviour: what it renders for a given set of lists and quotes,
 * and which calls a given interaction makes. Neither the network nor the
 * WebSocket belongs in that.
 */
const api = {
  list: vi.fn(),
  create: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  clear: vi.fn(),
  addItem: vi.fn(),
  removeItem: vi.fn(),
  reorderItems: vi.fn(),
}

vi.mock('@/api/watchlist', () => ({
  watchlistApi: {
    list: (...a: unknown[]) => api.list(...a),
    create: (...a: unknown[]) => api.create(...a),
    rename: (...a: unknown[]) => api.rename(...a),
    remove: (...a: unknown[]) => api.remove(...a),
    clear: (...a: unknown[]) => api.clear(...a),
    addItem: (...a: unknown[]) => api.addItem(...a),
    removeItem: (...a: unknown[]) => api.removeItem(...a),
    reorderItems: (...a: unknown[]) => api.reorderItems(...a),
  },
  watchlistError: (_e: unknown, fallback: string) => fallback,
}))

/** Whatever a test wants useLivePrice to be returning this render. */
let liveData: {
  items: Array<{ symbol: string; exchange: string; ltp?: number }>
  quotes: Map<string, { ltp: number; prev_close: number }>
} = {
  items: [],
  quotes: new Map(),
}

vi.mock('@/hooks/useLivePrice', () => ({
  useLivePrice: () => ({
    data: liveData.items,
    multiQuotes: liveData.quotes,
    isLive: true,
    isFallbackMode: false,
    isAnyMarketOpen: true,
  }),
}))

/** Daily history, which is where an unusable prev_close is resolved from. */
const previousClose = vi.fn(async () => null as number | null)
vi.mock('@/lib/trading/previousClose', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  previousClose: (...a: unknown[]) => previousClose(...(a as [])),
}))

const LIST: Watchlist = {
  id: 1,
  name: 'Heavy Weights',
  position: 0,
  items: [
    { id: 10, symbol: 'RELIANCE', exchange: 'NSE', position: 0 },
    { id: 11, symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', position: 1 },
  ],
}

function renderPanel(props: Partial<React.ComponentProps<typeof WatchlistPanel>> = {}) {
  return render(
    <WatchlistPanel
      apiKey="k"
      onPick={props.onPick ?? (() => {})}
      search={props.search ?? (async () => [])}
      activeSymbol={props.activeSymbol}
    />
  )
}

describe('WatchlistPanel', () => {
  beforeEach(() => {
    localStorage.clear()
    for (const fn of Object.values(api)) fn.mockReset()
    api.list.mockResolvedValue([LIST])
    liveData = { items: [], quotes: new Map() }
    previousClose.mockReset()
    previousClose.mockResolvedValue(null)
  })

  it('renders a four-figure price without throwing', async () => {
    // The regression this exists for: minimumFractionDigits was 2 while
    // maximumFractionDigits dropped to 1 above a thousand, and Intl throws
    // RangeError on that. It fires inside render, so the app's root error
    // boundary turned one index price into a blank page.
    liveData = {
      items: [
        { symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287.5 },
        { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', ltp: 57496.3 },
      ],
      quotes: new Map([
        ['NSE:RELIANCE', { ltp: 1287.5, prev_close: 1280 }],
        ['NSE_INDEX:BANKNIFTY', { ltp: 57496.3, prev_close: 57000 }],
      ]),
    }
    renderPanel()

    expect(await screen.findByText('1,287.50')).toBeInTheDocument()
    expect(screen.getByText('57,496.30')).toBeInTheDocument()
  })

  it('opens on symbol, last, change and change percent', async () => {
    // A browser that has never opened the panel. The move in price sits
    // between the last price and the move in percent.
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1351, prev_close: 1377.5 }]]),
    }
    renderPanel()
    await screen.findByText('RELIANCE')

    const header = screen.getByTestId('watchlist-columns')
    expect([...header.children].map((cell) => cell.textContent)).toEqual([
      'Symbol',
      'Last',
      'Chg',
      'Chg%',
      '',
    ])
    expect(screen.getByText('1,351.00')).toBeInTheDocument()
    expect(screen.getByText('-26.50')).toBeInTheDocument()
    expect(screen.getByText('-1.92%')).toBeInTheDocument()
  })

  it('adds the change column once for a browser still on the first default', async () => {
    // The first default was written to storage the moment the panel opened,
    // whether or not anyone touched the menu. A new default alone would have
    // reached nobody who had opened the panel before.
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({ columns: ['last', 'changePercent'], logo: true, exchange: true })
    )
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1351, prev_close: 1377.5 }]]),
    }
    renderPanel()

    expect(await screen.findByText('-26.50')).toBeInTheDocument()
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem('oa-trading-watchlist-display') || '{}')).toEqual({
        version: 2,
        columns: ['last', 'change', 'changePercent'],
        logo: true,
        exchange: true,
      })
    )
  })

  it('leaves the change column off once the user has switched it off', async () => {
    // The same two columns as the first default, but stored by this build, so
    // it is a choice. Without the version the column would come back on
    // every reload.
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({
        version: 2,
        columns: ['last', 'changePercent'],
        logo: true,
        exchange: true,
      })
    )
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1351, prev_close: 1377.5 }]]),
    }
    renderPanel()

    expect(await screen.findByText('-1.92%')).toBeInTheDocument()
    expect(screen.queryByText('-26.50')).not.toBeInTheDocument()
  })

  it('leaves a selection the user made in an older build alone', async () => {
    // Anything other than the exact first default was chosen by somebody.
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({ columns: ['changePercent', 'last'], logo: false, exchange: true })
    )
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1351, prev_close: 1377.5 }]]),
    }
    renderPanel()

    expect(await screen.findByText('-1.92%')).toBeInTheDocument()
    expect(screen.queryByText('-26.50')).not.toBeInTheDocument()
    // The rest of what they chose comes through untouched as well.
    expect(screen.queryByText('R')).not.toBeInTheDocument()
  })

  it('prints the last price and the change to the paisa, so the two add up', async () => {
    // One decimal above a thousand read 62,585.4 and -2,049.8 here: a price
    // that never traded and a move that is not the difference of the two
    // prices. In binary the subtraction is -2049.8499999999985.
    liveData = {
      items: [
        { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', ltp: 62585.35 },
        { symbol: 'RELIANCE', exchange: 'NSE', ltp: 134567.85 },
      ],
      quotes: new Map([
        ['NSE_INDEX:BANKNIFTY', { ltp: 62585.35, prev_close: 64635.2 }],
        ['NSE:RELIANCE', { ltp: 134567.85, prev_close: 133210.4 }],
      ]),
    }
    renderPanel()

    expect(await screen.findByText('62,585.35')).toBeInTheDocument()
    expect(screen.getByText('-2,049.85')).toBeInTheDocument()
    expect(screen.getByText('-3.17%')).toBeInTheDocument()
    expect(screen.getByText('1,34,567.85')).toBeInTheDocument()
    expect(screen.getByText('+1,357.45')).toBeInTheDocument()
    expect(screen.getByText('+1.02%')).toBeInTheDocument()
  })

  it('shows no sign and no direction for an instrument sitting on its close', async () => {
    // Unchanged is not a gain. The quote's own close equals the last price
    // here, so it is resolved from daily history, which agrees: no move.
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1594.3 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1594.3, prev_close: 1594.3 }]]),
    }
    previousClose.mockResolvedValue(1594.3)
    renderPanel()

    const percent = await screen.findByText('0.00%')
    const change = screen.getByText('0.00')
    expect(screen.queryByText('+0.00%')).not.toBeInTheDocument()
    expect(screen.queryByText('+0.00')).not.toBeInTheDocument()
    for (const cell of [change, percent]) {
      expect(cell).toHaveAttribute('data-direction', 'flat')
    }
  })

  it('reads the same price from two feeds as no move', async () => {
    // A live tick and a snapshot can carry one price as two different binary
    // numbers. Their difference is not zero, and was shown as a green +0.00%.
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1594.3000000000002 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1594.3, prev_close: 1594.3 }]]),
    }
    renderPanel()

    expect(await screen.findByText('0.00%')).toHaveAttribute('data-direction', 'flat')
    expect(screen.queryByText('+0.00%')).not.toBeInTheDocument()
  })

  it('marks which way a row moved, on the figures that carry direction', async () => {
    liveData = {
      items: [
        { symbol: 'RELIANCE', exchange: 'NSE', ltp: 1351 },
        { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', ltp: 62585.35 },
      ],
      quotes: new Map([
        ['NSE:RELIANCE', { ltp: 1351, prev_close: 1344.75 }],
        ['NSE_INDEX:BANKNIFTY', { ltp: 62585.35, prev_close: 64635.2 }],
      ]),
    }
    renderPanel()

    expect(await screen.findByText('+6.25')).toHaveAttribute('data-direction', 'up')
    expect(screen.getByText('+0.46%')).toHaveAttribute('data-direction', 'up')
    expect(screen.getByText('-2,049.85')).toHaveAttribute('data-direction', 'down')
    expect(screen.getByText('-3.17%')).toHaveAttribute('data-direction', 'down')
    // The last price carries no direction, so it is never marked.
    expect(screen.getByText('1,351.00')).not.toHaveAttribute('data-direction')
  })

  it('quotes a currency contract to four decimals', async () => {
    // A USDINR future moves a quarter paisa at a time. At two decimals this
    // row read 92.90, +0.00 and +0.00%.
    api.list.mockResolvedValue([
      {
        ...LIST,
        items: [{ id: 12, symbol: 'USDINR26NOV26FUT', exchange: 'CDS', position: 0 }],
      },
    ])
    liveData = {
      items: [{ symbol: 'USDINR26NOV26FUT', exchange: 'CDS', ltp: 92.9025 }],
      quotes: new Map([['CDS:USDINR26NOV26FUT', { ltp: 92.9025, prev_close: 92.9 }]]),
    }
    renderPanel()

    expect(await screen.findByText('92.9025')).toBeInTheDocument()
    expect(screen.getByText('+0.0025')).toHaveAttribute('data-direction', 'up')
    // A percentage is not a price, and stays at two decimals.
    expect(screen.getByText('+0.00%')).toHaveAttribute('data-direction', 'up')
  })

  it('prints no sign on a change too small to show, and keeps its percent', async () => {
    // An instrument quoted finer than the two decimals shown here. The move
    // is real, so the percent and the direction stand, but the price move
    // rounds to nothing and must not read "+0.00".
    api.list.mockResolvedValue([
      { ...LIST, items: [{ id: 13, symbol: 'DOGEUSD', exchange: 'CRYPTO', position: 0 }] },
    ])
    liveData = {
      items: [{ symbol: 'DOGEUSD', exchange: 'CRYPTO', ltp: 0.4321 }],
      quotes: new Map([['CRYPTO:DOGEUSD', { ltp: 0.4321, prev_close: 0.43 }]]),
    }
    renderPanel()

    expect(await screen.findByText('+0.49%')).toHaveAttribute('data-direction', 'up')
    expect(screen.getByText('0.00')).toHaveAttribute('data-direction', 'up')
    expect(screen.queryByText('+0.00')).not.toBeInTheDocument()
  })

  it('offers the whole name and exchange where the pointer is', async () => {
    // A long option symbol is cut short in the row, and its exchange tag
    // gives way first. The row button is what the pointer is over.
    renderPanel()

    expect(await screen.findByLabelText('Chart BANKNIFTY on NSE_INDEX')).toHaveAttribute(
      'title',
      'BANKNIFTY (NSE_INDEX)'
    )
  })

  it('shows two decimals below a thousand', async () => {
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 266.4 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 266.4, prev_close: 269.4 }]]),
    }
    renderPanel()

    expect(await screen.findByText('266.40')).toBeInTheDocument()
  })

  it('keeps the change percent visible rather than swapping it for the delete control', async () => {
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287.5 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1287.5, prev_close: 1280 }]]),
    }
    renderPanel()

    const change = await screen.findByText('+0.59%')
    // Not opacity-0: the most common reason to point at a row is to read it.
    expect(change.className).not.toContain('group-hover:opacity-0')
    expect(screen.getByLabelText('Remove RELIANCE')).toBeInTheDocument()
  })

  it('charts the instrument when its row is clicked', async () => {
    const onPick = vi.fn()
    renderPanel({ onPick })

    await userEvent.click(await screen.findByLabelText('Chart RELIANCE on NSE'))
    expect(onPick).toHaveBeenCalledWith({ symbol: 'RELIANCE', exchange: 'NSE' })
  })

  it('reports a failed load as an error with a retry, not as an empty list', async () => {
    api.list.mockRejectedValueOnce(new Error('network down'))
    renderPanel()

    expect(await screen.findByText('Could not load your watchlists')).toBeInTheDocument()
    expect(screen.queryByText('This list is empty.')).not.toBeInTheDocument()

    api.list.mockResolvedValue([LIST])
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('RELIANCE')).toBeInTheDocument()
  })

  it('creates a starter list when the user has none', async () => {
    api.list.mockResolvedValue([])
    api.create.mockResolvedValue({ id: 2, name: 'Watchlist', position: 0, items: [] })
    renderPanel()

    await waitFor(() => expect(api.create).toHaveBeenCalledWith('Watchlist'))
    expect(await screen.findByText('This list is empty.')).toBeInTheDocument()
  })

  it('removes an instrument optimistically', async () => {
    api.removeItem.mockResolvedValue(undefined)
    api.list.mockResolvedValue([LIST])
    renderPanel()

    await userEvent.click(await screen.findByLabelText('Remove RELIANCE'))
    expect(api.removeItem).toHaveBeenCalledWith(1, 10)
  })

  it('copies a list with its instruments in one call', async () => {
    api.create.mockResolvedValue({ ...LIST, id: 3, name: 'Heavy Weights copy' })
    renderPanel()

    await userEvent.click(await screen.findByText('Heavy Weights'))
    await userEvent.click(await screen.findByText('Make a copy...'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.create).toHaveBeenCalledWith('Heavy Weights copy', LIST.items))
  })

  it('marks the row matching the focused pane, and only that row', async () => {
    renderPanel({ activeSymbol: 'NSE_INDEX:BANKNIFTY' })
    await screen.findByText('BANKNIFTY')

    // aria-current, not a Tailwind class. jsdom has no cascade, so a class
    // assertion passes even when the marker is transparent or zero width,
    // which is exactly how an invalid colour shipped unnoticed once already.
    expect(screen.getByLabelText('Chart BANKNIFTY on NSE_INDEX')).toHaveAttribute(
      'aria-current',
      'true'
    )
    expect(screen.getByLabelText('Chart RELIANCE on NSE')).not.toHaveAttribute('aria-current')
  })

  it('shows a dash rather than a zero for an instrument with no quote', async () => {
    renderPanel()
    await screen.findByText('RELIANCE')

    // Two rows, each with a dash for last and a dash for change.
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(4)
  })

  it('shows a dash, not a green +0.00%, when there is no previous close', async () => {
    // No previous close is not the same as unchanged. Collapsing the two put a
    // confident green +0.00% on every pre-open or thinly quoted instrument.
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287.5 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1287.5, prev_close: 0 }]]),
    }
    renderPanel()

    expect(await screen.findByText('1,287.50')).toBeInTheDocument()
    expect(screen.queryByText('+0.00%')).not.toBeInTheDocument()
    // Nor an unsigned one: no close to measure from is not "no move" either.
    expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })

  it('never marks a row when no pane instrument matches', async () => {
    renderPanel({ activeSymbol: 'NSE:NOTINLIST' })
    await screen.findByText('RELIANCE')

    expect(document.querySelectorAll('[aria-current]')).toHaveLength(0)
  })

  it('resolves the previous close from daily history when the quote cannot', async () => {
    // Some brokers report the CURRENT session's close in prev_close, which
    // equals the last traded price, so every row read +0.00%. The daily bar is
    // the same one the chart legend uses.
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1287, prev_close: 1287 }]]),
    }
    previousClose.mockResolvedValue(1282.2)
    renderPanel()

    expect(await screen.findByText('+0.37%')).toBeInTheDocument()
    // The LTP goes with it: it is what picks the right bar out of the history.
    // The 4th argument is the session state, which picks the right daily bar.
    expect(previousClose).toHaveBeenCalledWith('k', 'RELIANCE', 'NSE', expect.any(Boolean))
  })

  it('does not spend a history call when the quote already carries one', async () => {
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1287, prev_close: 1282.2 }]]),
    }
    renderPanel()

    expect(await screen.findByText('+0.37%')).toBeInTheDocument()
    expect(previousClose).not.toHaveBeenCalled()
  })

  it('shows only the chosen columns, and keeps the header on the same grid', async () => {
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({ columns: ['last', 'change', 'volume'], logo: true, exchange: true })
    )
    liveData = {
      items: [{ symbol: 'RELIANCE', exchange: 'NSE', ltp: 1287 }],
      quotes: new Map([['NSE:RELIANCE', { ltp: 1287, prev_close: 1282.2, volume: 6830228 }]]),
    }
    const { container } = renderPanel()
    await screen.findByText('RELIANCE')

    const grids = container.querySelectorAll('[style*="grid-template-columns"]')
    // Header and row must resolve to the same template, or the labels sit over
    // the wrong numbers.
    const templates = new Set([...grids].map((g) => (g as HTMLElement).style.gridTemplateColumns))
    expect(templates.size).toBe(1)

    expect(screen.getByText('+4.80')).toBeInTheDocument()
    expect(screen.getByText('68.30L')).toBeInTheDocument()
    // Change % was not chosen.
    expect(screen.queryByText('+0.37%')).not.toBeInTheDocument()
  })

  it('hides the symbol letter and the exchange when they are turned off', async () => {
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({ columns: ['last'], logo: false, exchange: false })
    )
    renderPanel()
    await screen.findByText('RELIANCE')

    expect(screen.queryByText('NSE')).not.toBeInTheDocument()
    expect(screen.queryByText('R')).not.toBeInTheDocument()
  })

  it('ignores a stored column id that no longer exists', async () => {
    // A layout saved by an older build must not leave the header and the rows
    // disagreeing about how many cells there are.
    localStorage.setItem(
      'oa-trading-watchlist-display',
      JSON.stringify({ columns: ['last', 'gone', 'alsoGone'], logo: true, exchange: true })
    )
    const { container } = renderPanel()
    await screen.findByText('RELIANCE')

    const grids = container.querySelectorAll('[style*="grid-template-columns"]')
    expect((grids[0] as HTMLElement).style.gridTemplateColumns).toBe('1fr 70px 16px')
  })
})
