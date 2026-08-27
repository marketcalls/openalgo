import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, within } from '@/test/test-utils'
import { type CatalogEntry, IndicatorPickerDialog } from './IndicatorPickerDialog'

/** Shaped like `indicatorCatalog()`: the engine's four real categories. */
const CATALOG: CatalogEntry[] = [
  { id: 'sma', name: 'Simple Moving Average', category: 'Trend' },
  { id: 'ema', name: 'Exponential Moving Average', category: 'Trend' },
  { id: 'adx', name: 'Average Directional Index', category: 'Trend' },
  { id: 'rsi', name: 'Relative Strength Index', category: 'Momentum' },
  { id: 'macd', name: 'MACD', category: 'Momentum' },
  { id: 'atr', name: 'Average True Range', category: 'Volatility' },
  { id: 'obv', name: 'On Balance Volume', category: 'Volume' },
]

const ACTIVE = [
  { id: 'inst-1', name: 'RSI 14' },
  { id: 'inst-2', name: 'SMA 20' },
]

function renderPicker(over: Partial<Parameters<typeof IndicatorPickerDialog>[0]> = {}) {
  const props = {
    open: true,
    catalog: CATALOG,
    active: ACTIVE,
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    onSettings: vi.fn(),
    onClose: vi.fn(),
    ...over,
  }
  render(<IndicatorPickerDialog {...props} />)
  return props
}

/** The scrollable list, so a rail button named 'Trend' is not mistaken for a row. */
const list = () => screen.getByLabelText('Search indicators').closest('div')?.parentElement
  ?.parentElement?.querySelector('.min-w-0') as HTMLElement

beforeEach(() => localStorage.clear())

describe('IndicatorPickerDialog', () => {
  it('builds the rail from the categories the registry actually uses', () => {
    renderPicker()
    // Counted, not guessed: three Trend, two Momentum, one each of the others.
    expect(screen.getByRole('button', { name: 'Trend, 3 indicators' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Momentum, 2 indicators' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Volatility, 1 indicators' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Volume, 1 indicators' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All, 7 indicators' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Active, 2 indicators' })).toBeInTheDocument()
  })

  it('invents no section the data cannot fill', () => {
    renderPicker()
    // No author, no popularity, no community: this is a local registry.
    for (const absent of ['Editors', 'Trending', 'Store', 'Purchased', 'Author', 'Boosts']) {
      expect(screen.queryByText(new RegExp(absent, 'i'))).not.toBeInTheDocument()
    }
  })

  it('filters to one category and sorts it alphabetically', async () => {
    const user = userEvent.setup()
    renderPicker()
    await user.click(screen.getByRole('button', { name: 'Trend, 3 indicators' }))
    const names = within(list())
      .getAllByTitle(/^Add /)
      .map((b) => b.textContent)
    expect(names).toEqual([
      'Average Directional Index',
      'Exponential Moving Average',
      'Simple Moving Average',
    ])
    expect(within(list()).queryByTitle('Add MACD')).not.toBeInTheDocument()
  })

  it('searches by name and by registry id', async () => {
    const user = userEvent.setup()
    renderPicker()
    const box = screen.getByLabelText('Search indicators')
    await user.type(box, 'obv') // the id, not the name
    expect(within(list()).getByTitle('Add On Balance Volume')).toBeInTheDocument()
    expect(within(list()).queryByTitle('Add MACD')).not.toBeInTheDocument()
  })

  it('adds on click and remembers it as recent', async () => {
    const user = userEvent.setup()
    const props = renderPicker()
    await user.click(within(list()).getByTitle('Add MACD'))
    expect(props.onAdd).toHaveBeenCalledWith('macd')
    expect(JSON.parse(localStorage.getItem('oa-trading-recent-indicators') ?? '[]')).toEqual(['macd'])
    await user.click(screen.getByRole('button', { name: 'Recent, 1 indicators' }))
    expect(within(list()).getByTitle('Add MACD')).toBeInTheDocument()
  })

  it('keeps favourites across a close and reopen', async () => {
    const user = userEvent.setup()
    const { unmount } = render(
      <IndicatorPickerDialog
        open
        catalog={CATALOG}
        active={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onSettings={vi.fn()}
        onClose={vi.fn()}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Star MACD' }))
    expect(JSON.parse(localStorage.getItem('oa-trading-fav-indicators') ?? '[]')).toEqual(['macd'])
    unmount()

    renderPicker()
    await user.click(screen.getByRole('button', { name: 'Favourites, 1 indicators' }))
    expect(within(list()).getByTitle('Add MACD')).toBeInTheDocument()
  })

  it('offers settings and remove on active instances, never add', async () => {
    const user = userEvent.setup()
    const props = renderPicker()
    await user.click(screen.getByRole('button', { name: 'Active, 2 indicators' }))
    // Instances, not descriptors: two SMAs would differ only by instance id.
    await user.click(within(list()).getAllByRole('button', { name: 'Settings' })[0])
    expect(props.onSettings).toHaveBeenCalledWith('inst-1')
    await user.click(within(list()).getAllByRole('button', { name: 'Remove' })[1])
    expect(props.onRemove).toHaveBeenCalledWith('inst-2')
    expect(within(list()).queryByTitle(/^Add /)).not.toBeInTheDocument()
  })

  it('says the library is loading rather than showing an empty shelf', () => {
    renderPicker({ catalog: [] })
    expect(screen.getByText('Loading the indicator library…')).toBeInTheDocument()
  })

  it('renders nothing when closed', () => {
    renderPicker({ open: false })
    expect(screen.queryByText('Indicators')).not.toBeInTheDocument()
  })
})
