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

    expect(await screen.findByText('1,287.5')).toBeInTheDocument()
    expect(screen.getByText('57,496.3')).toBeInTheDocument()
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

    expect(await screen.findByText('1,287.5')).toBeInTheDocument()
    expect(screen.queryByText('+0.00%')).not.toBeInTheDocument()
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
    expect((grids[0] as HTMLElement).style.gridTemplateColumns).toBe('1fr 64px 16px')
  })
})
