import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import type { SymbolSearchResult } from '@/types/chartink'
import { SymbolSearchInput } from './SymbolSearchInput'

const mocks = vi.hoisted(() => ({
  searchSymbols: vi.fn(),
}))

vi.mock('@/api/chartink', () => ({
  chartinkApi: { searchSymbols: mocks.searchSymbols },
}))

const RESULTS: SymbolSearchResult[] = [
  {
    symbol: 'INFY',
    brsymbol: 'INFY',
    name: 'Infosys',
    exchange: 'NSE',
    token: '1594',
    lotsize: 1,
  },
  {
    symbol: 'INOXWIND',
    brsymbol: 'INOXWIND',
    name: 'Inox Wind',
    exchange: 'NSE',
    token: '11162',
    lotsize: 1,
  },
]

function renderInput() {
  const onSelect = vi.fn()
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={queryClient}>
      <SymbolSearchInput value="" exchange="NSE" onSelect={onSelect} />
    </QueryClientProvider>
  )
  return {
    onSelect,
    user,
    input: screen.getByRole('combobox', { name: 'Search symbol' }),
  }
}

describe('SymbolSearchInput accessibility', () => {
  beforeEach(() => {
    mocks.searchSymbols.mockReset()
    mocks.searchSymbols.mockResolvedValue(RESULTS)
  })

  it('exposes combobox semantics that control a listbox of options', async () => {
    const { input, user } = renderInput()

    expect(input).toHaveAccessibleName('Search symbol')
    expect(input).toHaveAttribute('aria-autocomplete', 'list')
    expect(input).toHaveAttribute('aria-haspopup', 'listbox')
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(input).not.toHaveAttribute('aria-controls')

    await user.type(input, 'IN')

    const listbox = await screen.findByRole('listbox')
    const options = await screen.findAllByRole('option')

    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', listbox.id)
    expect(options).toHaveLength(RESULTS.length)
    for (const option of options) {
      expect(option).toHaveAttribute('aria-selected', 'false')
      expect(option).toHaveAttribute('tabindex', '-1')
    }
  })

  it('keeps loading and empty messages outside the listbox', async () => {
    mocks.searchSymbols.mockResolvedValueOnce([])
    const { input, user } = renderInput()

    await user.type(input, 'ZZ')

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Nothing on NSE matching “ZZ”')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).not.toHaveAttribute('aria-controls')
  })

  it('scrolls the active option into view', async () => {
    const scrollIntoView = vi.mocked(HTMLElement.prototype.scrollIntoView)
    scrollIntoView.mockClear()
    const { input, user } = renderInput()

    await user.type(input, 'IN')
    await screen.findAllByRole('option')
    expect(scrollIntoView).not.toHaveBeenCalled()

    await user.keyboard('{ArrowDown}')

    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
  })

  it('queries the instrument master with the typed text and exchange', async () => {
    const { input, user } = renderInput()

    await user.type(input, 'in')

    await waitFor(() => expect(mocks.searchSymbols).toHaveBeenLastCalledWith('IN', 'NSE'))
  })

  it('moves the active option with ArrowDown and ArrowUp', async () => {
    const { input, user } = renderInput()
    await user.type(input, 'IN')
    const options = await screen.findAllByRole('option')

    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[1].id)
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
    expect(options[0]).toHaveAttribute('aria-selected', 'false')

    await user.keyboard('{ArrowUp}')
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('wraps the active option at both ends of the list', async () => {
    const { input, user } = renderInput()
    await user.type(input, 'IN')
    const options = await screen.findAllByRole('option')

    await user.keyboard('{ArrowUp}')
    expect(input).toHaveAttribute('aria-activedescendant', options[1].id)

    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id)

    await user.keyboard('{ArrowDown}')
    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id)
  })

  it('selects the active option with Enter', async () => {
    const { input, onSelect, user } = renderInput()
    await user.type(input, 'IN')
    const options = await screen.findAllByRole('option')

    await user.keyboard('{ArrowDown}{ArrowDown}')
    expect(options[1]).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledWith('INOXWIND')
    expect(input).toHaveValue('INOXWIND')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).not.toHaveAttribute('aria-activedescendant')
  })

  it('submits the typed ticker with Enter when no option is active', async () => {
    const { input, onSelect, user } = renderInput()

    await user.type(input, 'tcs')
    expect(input).toHaveValue('TCS')

    await user.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledWith('TCS')
    expect(input).toHaveValue('TCS')
  })

  it('closes with Escape and leaves focus on the input', async () => {
    const { input, onSelect, user } = renderInput()
    await user.type(input, 'IN')
    await screen.findAllByRole('option')
    await user.keyboard('{ArrowDown}')

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveFocus()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(input).not.toHaveAttribute('aria-activedescendant')
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('closes the list when focus leaves the input', async () => {
    const { input, onSelect, user } = renderInput()
    await user.type(input, 'IN')
    await screen.findAllByRole('option')

    await user.tab()

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(input).not.toHaveAttribute('aria-activedescendant')
    expect(onSelect).toHaveBeenCalledWith('IN')
  })

  it('selects a suggestion with the mouse', async () => {
    const { input, onSelect, user } = renderInput()
    await user.type(input, 'IN')
    const options = await screen.findAllByRole('option')

    await user.click(options[0])

    expect(onSelect).toHaveBeenCalledWith('INFY')
    expect(input).toHaveValue('INFY')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})
