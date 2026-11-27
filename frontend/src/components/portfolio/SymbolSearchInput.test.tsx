import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent } from '@/test/test-utils'
import { SymbolSearchInput } from './SymbolSearchInput'

vi.mock('@/api/chartink', () => ({
  chartinkApi: {
    searchSymbols: vi.fn(async () => [
      { symbol: 'INFY', name: 'Infosys', exchange: 'NSE' },
      { symbol: 'INFIBEAM', name: 'Infibeam Avenues', exchange: 'NSE' },
      { symbol: 'INFOBEAN', name: 'InfoBeans Technologies', exchange: 'NSE' },
    ]),
  },
}))

function setup() {
  const onSelect = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SymbolSearchInput value="" exchange="NSE" onSelect={onSelect} />
    </QueryClientProvider>
  )
  return { onSelect, user: userEvent.setup(), input: screen.getByRole('combobox') }
}

describe('SymbolSearchInput', () => {
  beforeEach(() => vi.clearAllMocks())

  it('exposes the combobox and listbox roles', async () => {
    const { user, input } = setup()
    expect(input).toHaveAttribute('aria-expanded', 'false')

    await user.type(input, 'inf')
    const listbox = await screen.findByRole('listbox')
    expect(await screen.findAllByRole('option')).toHaveLength(3)
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', listbox.id)
    expect(input).not.toHaveAttribute('aria-activedescendant')
  })

  it('moves a single active option with the arrow keys and selects it with Enter', async () => {
    const { user, input, onSelect } = setup()
    await user.type(input, 'inf')
    const options = await screen.findAllByRole('option')

    await user.keyboard('{ArrowDown}{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[1].id)
    expect(screen.getAllByRole('option', { selected: true })).toEqual([options[1]])

    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(input).toHaveAttribute('aria-activedescendant', options[2].id)

    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('INFOBEAN')
    expect(input).toHaveValue('INFOBEAN')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveFocus()
  })

  it('keeps Enter on the typed ticker when nothing is highlighted', async () => {
    const { user, input, onSelect } = setup()
    await user.type(input, 'infy')
    await screen.findAllByRole('option')

    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('INFY')
  })

  it('closes on Escape and selects with the mouse', async () => {
    const { user, input, onSelect } = setup()
    await user.type(input, 'inf')
    await screen.findAllByRole('option')

    await user.keyboard('{ArrowDown}{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).not.toHaveAttribute('aria-activedescendant')

    await user.type(input, 'o')
    await user.click(await screen.findByRole('option', { name: /INFIBEAM/ }))
    expect(onSelect).toHaveBeenCalledWith('INFIBEAM')
  })
})
