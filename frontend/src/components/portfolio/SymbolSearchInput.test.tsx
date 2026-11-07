import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/vitest'
import { beforeEach, expect, it, vi } from 'vitest'

import { SymbolSearchInput } from './SymbolSearchInput'

const mockSearchSymbols = vi.hoisted(() => vi.fn())

vi.mock('@/api/chartink', () => ({
  chartinkApi: {
    searchSymbols: mockSearchSymbols,
  },
}))

function renderComponent() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  const onSelect = vi.fn()

  render(
    <QueryClientProvider client={queryClient}>
      <SymbolSearchInput value="" exchange="NSE" onSelect={onSelect} />
    </QueryClientProvider>
  )

  return { onSelect }
}

beforeEach(() => {
  vi.clearAllMocks()

  mockSearchSymbols.mockResolvedValue([
    { symbol: 'RELIANCE', name: 'Reliance Industries', exchange: 'NSE' },
    { symbol: 'TCS', name: 'Tata Consultancy Services', exchange: 'NSE' },
    { symbol: 'INFY', name: 'Infosys', exchange: 'NSE' },
  ])
})

it('highlights the next suggestion when ArrowDown is pressed', async () => {
  const user = userEvent.setup()
  renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(screen.getByRole('option', { name: /RELIANCE/ })).toBeInTheDocument()
  })

  await user.keyboard('{ArrowDown}')

  expect(input).toHaveAttribute('aria-activedescendant', expect.stringContaining('option-0'))

  expect(screen.getByRole('option', { name: /RELIANCE/ })).toHaveAttribute('aria-selected', 'true')
})

it('highlights the previous suggestion when ArrowUp is pressed', async () => {
  const user = userEvent.setup()
  renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(screen.getByRole('option', { name: /RELIANCE/ })).toBeInTheDocument()
  })

  await user.keyboard('{ArrowDown}')
  await user.keyboard('{ArrowDown}')
  await user.keyboard('{ArrowUp}')

  expect(input).toHaveAttribute('aria-activedescendant', expect.stringContaining('option-0'))

  expect(screen.getByRole('option', { name: /RELIANCE/ })).toHaveAttribute('aria-selected', 'true')
})

it('selects the highlighted suggestion when Enter is pressed', async () => {
  const user = userEvent.setup()
  const { onSelect } = renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(screen.getByRole('option', { name: /RELIANCE/ })).toBeInTheDocument()
  })

  await user.keyboard('{ArrowDown}')
  await user.keyboard('{Enter}')

  expect(onSelect).toHaveBeenCalledWith('RELIANCE')
})

it('closes suggestions when Escape is pressed', async () => {
  const user = userEvent.setup()
  renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  await user.keyboard('{ArrowDown}')
  await user.keyboard('{Escape}')

  expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  expect(input).toHaveFocus()
  expect(input).not.toHaveAttribute('aria-activedescendant')
})

it('selects the manually typed symbol when Enter is pressed without highlighting a suggestion', async () => {
  const user = userEvent.setup()
  const { onSelect } = renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'INFY')
  await user.keyboard('{Enter}')

  expect(onSelect).toHaveBeenCalledWith('INFY')
})

it('selects a suggestion when clicked with the mouse', async () => {
  const user = userEvent.setup()
  const { onSelect } = renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  const suggestion = await screen.findByRole('option', {
    name: /RELIANCE/,
  })

  await user.click(suggestion)

  expect(onSelect).toHaveBeenCalledWith('RELIANCE')
})

it('moves to the first suggestion after the last suggestion when ArrowDown is pressed', async () => {
  const user = userEvent.setup()
  renderComponent()

  const input = screen.getByRole('combobox')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(screen.getByRole('option', { name: /RELIANCE/ })).toBeInTheDocument()
  })

  await user.keyboard('{ArrowDown}')
  await user.keyboard('{ArrowDown}')
  await user.keyboard('{ArrowDown}')
  await user.keyboard('{ArrowDown}')

  expect(screen.getByRole('option', { name: /RELIANCE/ })).toHaveAttribute('aria-selected', 'true')
})

it('exposes the correct accessibility attributes', async () => {
  const user = userEvent.setup()
  renderComponent()

  const input = screen.getByRole('combobox')

  expect(input).toHaveAttribute('aria-autocomplete', 'list')
  expect(input).toHaveAttribute('aria-haspopup', 'listbox')
  expect(input).toHaveAttribute('aria-expanded', 'false')

  await user.type(input, 'RE')

  await waitFor(() => {
    expect(input).toHaveAttribute('aria-expanded', 'true')
  })

  expect(screen.getByRole('listbox')).toBeInTheDocument()
})
