import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { StrategyLeg } from '@/lib/strategyMath'
import { makeFormatCurrency } from '@/lib/utils'
import { GreeksTab, type LegGreeks } from './GreeksTab'

function optionLeg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    id: 'call',
    segment: 'OPTION',
    side: 'BUY',
    lots: 2,
    lotSize: 100,
    expiry: '13AUG26',
    strike: 24_600,
    optionType: 'CE',
    price: 100,
    iv: 20,
    active: true,
    symbol: 'NIFTY13AUG2624600CE',
    ...overrides,
  }
}

function futureLeg(overrides: Partial<StrategyLeg> = {}): StrategyLeg {
  return {
    id: 'future',
    segment: 'FUTURE',
    side: 'BUY',
    lots: 2,
    lotSize: 50,
    expiry: '27AUG26',
    price: 25_000,
    iv: 0,
    active: true,
    symbol: 'NIFTY27AUG26FUT',
    ...overrides,
  }
}

const OPTION_GREEKS: Record<string, LegGreeks> = {
  call: {
    legId: 'call',
    iv: 20,
    delta: 0.5,
    gamma: 0.02,
    theta: -3,
    vega: 5,
  },
}

describe('GreeksTab positional units', () => {
  it('keeps two lots in decimal-mode positional Greeks and applies direction', () => {
    render(
      <GreeksTab
        legs={[optionLeg()]}
        greeksByLeg={OPTION_GREEKS}
        formatCurrency={makeFormatCurrency(null)}
      />
    )

    // Hand-derived: BUY sign (+1) * 2 lots * 100 lot size * 0.5 delta = 100.
    expect(screen.getByTestId('net-delta')).toHaveTextContent('100.00')
    expect(screen.getByTestId('net-delta')).not.toHaveTextContent('₹')

    const optionRow = screen.getByText(/13AUG26 24600CE/).closest('tr')
    expect(optionRow).not.toBeNull()
    expect(within(optionRow as HTMLElement).getAllByRole('cell')[2]).toHaveTextContent('100.00')

    fireEvent.click(screen.getByText('Currency values'))
    expect(screen.getByTestId('net-delta')).toHaveTextContent('100.00')
    expect(screen.getByTestId('net-delta')).not.toHaveTextContent('₹')
    expect(screen.getByTestId('net-theta')).toHaveTextContent('-₹600.00')
    expect(screen.getByTestId('net-vega')).toHaveTextContent('₹1,000.00')
  })

  it('adds signed futures quantity to delta and zero to the other Greeks', () => {
    render(
      <GreeksTab
        legs={[futureLeg(), futureLeg({ id: 'short-future', side: 'SELL', lots: 1, lotSize: 25 })]}
        greeksByLeg={{}}
        formatCurrency={makeFormatCurrency(null)}
      />
    )

    // Hand-derived: +2 * 50 - 1 * 25 = +75 underlying units.
    expect(screen.getByTestId('net-delta')).toHaveTextContent('75.00')
    expect(screen.getByTestId('net-gamma')).toHaveTextContent('0.000000')
    expect(screen.getByTestId('net-theta')).toHaveTextContent('0.00')
    expect(screen.getByTestId('net-vega')).toHaveTextContent('0.00')
  })

  it('labels quantity and currency dimensions without calling delta or gamma rupees', () => {
    render(
      <GreeksTab
        legs={[optionLeg()]}
        greeksByLeg={OPTION_GREEKS}
        formatCurrency={makeFormatCurrency('deltaexchange')}
      />
    )

    expect(screen.getByRole('columnheader', { name: /Delta.*underlying units/i })).toBeVisible()
    expect(screen.getByRole('columnheader', { name: /Gamma.*delta.*price point/i })).toBeVisible()
    expect(
      screen.getByRole('columnheader', { name: /Theta.*position currency.*per day/i })
    ).toBeVisible()
    expect(
      screen.getByRole('columnheader', { name: /Vega.*position currency.*1% IV/i })
    ).toBeVisible()
    expect(screen.getByRole('table')).not.toHaveTextContent('₹')

    fireEvent.click(screen.getByText('Currency values'))
    expect(screen.getByTestId('net-theta')).toHaveTextContent('-$600.00')
    expect(screen.getByTestId('net-vega')).toHaveTextContent('$1,000.00')
    expect(screen.getByTestId('net-delta')).not.toHaveTextContent('$')
    expect(screen.getByTestId('net-gamma')).not.toHaveTextContent('$')
  })
})
