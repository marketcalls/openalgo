import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { ResolvedLegMarket } from '@/lib/strategyContracts'
import type { StrategyLeg } from '@/lib/strategyMath'
import { EditLegDialog, invalidateIvWhenContractChanges } from './EditLegDialog'

const original: StrategyLeg = {
  id: 'leg-1',
  segment: 'OPTION',
  side: 'BUY',
  lots: 1,
  lotSize: 25,
  expiry: '04AUG26',
  strike: 24000,
  optionType: 'CE',
  price: 100,
  iv: 14.2,
  active: true,
  symbol: 'NIFTY04AUG2624000CE',
  marketGreeks: { delta: 0.5, gamma: 0.01, theta: -2, vega: 4 },
}

describe('EditLegDialog payoff market-data invalidation', () => {
  it.each([
    ['strike', { strike: 24500 }],
    ['option type', { optionType: 'PE' as const }],
    ['expiry', { expiry: '11AUG26' }],
  ])('PG-13 clears stale IV when %s changes', (_label, change) => {
    const result = invalidateIvWhenContractChanges(original, { ...original, ...change })
    expect(result.iv).toBe(0)
    expect(result.marketGreeks).toBeUndefined()
  })

  it('clears the Greek snapshot when the canonical symbol changes', () => {
    const result = invalidateIvWhenContractChanges(original, {
      ...original,
      symbol: 'NIFTY04AUG2624000CE-CANONICAL',
    })

    expect(result.iv).toBe(0)
    expect(result.marketGreeks).toBeUndefined()
  })

  it('keeps IV for quantity, side, and entry-price-only edits', () => {
    expect(
      invalidateIvWhenContractChanges(original, {
        ...original,
        side: 'SELL',
        lots: 2,
        price: 101,
      })
    ).toMatchObject({ iv: 14.2, marketGreeks: original.marketGreeks })
  })
})

function market(overrides: Partial<ResolvedLegMarket> = {}): ResolvedLegMarket {
  return {
    exchange: 'NFO',
    symbol: 'NIFTY04AUG2624000CE',
    expiry: '04AUG26',
    expiryTs: 1_786_400_000,
    lotSize: 25,
    tickSize: 0.05,
    marketPrice: 100,
    iv: 14.2,
    forwardPrice: 24_620,
    referenceUnderlying: 24_600,
    greeks: { delta: 0.5, gamma: 0.01, theta: -2, vega: 4 },
    ...overrides,
  }
}

function renderDialog(resolveContract = vi.fn(async () => market()), onSave = vi.fn()) {
  render(
    <EditLegDialog
      open
      onOpenChange={vi.fn()}
      leg={original}
      optionExpiries={['04AUG26', '18AUG26']}
      futureExpiries={['27AUG26']}
      chain={null}
      resolveContract={resolveContract}
      onSave={onSave}
      onDelete={vi.fn()}
    />
  )
  return { resolveContract, onSave }
}

async function chooseInDialog(index: number, optionName: string) {
  const dialog = screen.getByRole('dialog', { name: 'Edit Position' })
  fireEvent.keyDown(within(dialog).getAllByRole('combobox')[index], { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: optionName }))
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

describe('EditLegDialog listed contracts and price validation', () => {
  it('clears the old price and saves the canonical far-expiry contract', async () => {
    const pending: { resolve?: (value: ResolvedLegMarket | null) => void } = {}
    const resolveContract = vi.fn(
      () =>
        new Promise<ResolvedLegMarket | null>((resolve) => {
          pending.resolve = resolve
        })
    )
    const { onSave } = renderDialog(resolveContract)

    await chooseInDialog(0, '18AUG26')
    expect(screen.getByLabelText('Entry price')).toHaveValue('')
    expect(screen.queryByText(original.symbol)).not.toBeInTheDocument()

    await act(async () =>
      pending.resolve?.(
        market({
          symbol: 'NIFTY18AUG2624600CE',
          expiry: '18AUG26',
          marketPrice: 225,
          iv: 22,
        })
      )
    )
    expect(await screen.findByText('NIFTY18AUG2624600CE')).toBeVisible()
    expect(screen.getByLabelText('Entry price')).toHaveValue('225')

    fireEvent.click(screen.getByRole('button', { name: 'Modify' }))
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: 'NIFTY18AUG2624600CE',
        price: 225,
        marketPrice: 225,
        expiry: '18AUG26',
      })
    )
  })

  it('does not restore a stale contract after the latest selection is missing', async () => {
    let resolvePe!: (value: ResolvedLegMarket | null) => void
    let resolveCe!: (value: ResolvedLegMarket | null) => void
    const resolveContract = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<ResolvedLegMarket | null>((resolve) => {
            resolvePe = resolve
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise<ResolvedLegMarket | null>((resolve) => {
            resolveCe = resolve
          })
      )
    renderDialog(resolveContract)

    await chooseInDialog(2, 'PE')
    await chooseInDialog(2, 'CE')
    await act(async () => resolveCe(null))
    expect(await screen.findByText('Contract is not listed for this selection')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Modify' })).toBeDisabled()

    await act(async () => resolvePe(market({ symbol: 'STALE-PE' })))
    await waitFor(() => expect(screen.queryByText('STALE-PE')).not.toBeInTheDocument())
    expect(screen.getByLabelText('Entry price')).toHaveValue('')
  })

  it.each([
    ['Infinity', 'Enter a finite price'],
    ['-1', 'Price must be zero or greater'],
    ['', 'Enter a price'],
  ])('rejects entry price %p with an associated inline error', async (raw, message) => {
    const user = userEvent.setup()
    renderDialog()
    const input = screen.getByLabelText('Entry price')
    await user.clear(input)
    if (raw) fireEvent.change(input, { target: { value: raw } })
    fireEvent.click(screen.getByRole('button', { name: 'Modify' }))

    expect(await screen.findByText(message)).toBeVisible()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-describedby', 'entry-price-error')
  })

  it('accepts a zero entry price without falling back to the stale leg price', async () => {
    const user = userEvent.setup()
    const { onSave } = renderDialog()
    const input = screen.getByLabelText('Entry price')
    await user.clear(input)
    await user.type(input, '0')
    fireEvent.click(screen.getByRole('button', { name: 'Modify' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ price: 0 }))
  })

  it('rejects a non-finite exit price with an associated inline error', async () => {
    const { onSave } = renderDialog()
    const input = screen.getByLabelText('Exit price')
    fireEvent.change(input, { target: { value: 'Infinity' } })
    fireEvent.click(screen.getByRole('button', { name: 'Modify' }))

    expect(await screen.findByText('Enter a finite price')).toBeVisible()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-describedby', 'exit-price-error')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('preserves a zero exit price as a valid explicit value', async () => {
    const { onSave } = renderDialog()
    fireEvent.change(screen.getByLabelText('Exit price'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Modify' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ exitPrice: 0 }))
  })
})
