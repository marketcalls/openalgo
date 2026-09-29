/**
 * The form a strategy's parameters are set in, before a backtest and before a
 * run: a script's groups and help text have to reach it, because this is the
 * one place a trader reads what a parameter does before money depends on it.
 */

import { describe, expect, it, vi } from 'vitest'
import type { InputDeclaration } from '@/lib/trading/backtestInputs'
import { render, screen } from '@/test/test-utils'
import { StrategyInputs } from './StrategyInputs'

function declared(overrides: Partial<InputDeclaration> & { key: string }): InputDeclaration {
  return {
    kind: 'number',
    label: overrides.key,
    default: ['n', 1],
    min: null,
    max: null,
    step: null,
    options: null,
    group: '',
    tooltip: null,
    ...overrides,
  }
}

const DECLARATIONS = [
  declared({ key: 'fast', label: 'Fast', group: 'Entry' }),
  declared({
    key: 'stop',
    label: 'Stop',
    group: 'Exit',
    tooltip: 'Points below the entry price.',
  }),
  declared({ key: 'slow', label: 'Slow', group: 'Entry' }),
  declared({ key: 'qty', label: 'Quantity' }),
]

describe('a strategy explains its inputs', () => {
  it('draws each group as a heading, once, over the inputs declared into it', () => {
    render(<StrategyInputs declarations={DECLARATIONS} edited={{}} onChange={vi.fn()} />)
    const order = [...document.querySelectorAll('h4, label > span')].map((one) => one.textContent)
    expect(order).toEqual(['Entry', 'Fast', 'Slow', 'Exit', 'Stop', 'Quantity'])
  })

  it('writes a tooltip out as help under its input, tied to the control', () => {
    render(<StrategyInputs declarations={DECLARATIONS} edited={{}} onChange={vi.fn()} />)
    const help = screen.getByText('Points below the entry price.')
    const control = screen.getByRole('spinbutton', { name: 'Stop' })
    expect(control.getAttribute('aria-describedby')).toBe(help.id)
    expect(help.id).not.toBe('')
    // Only the input that declared help points at any.
    expect(
      screen.getByRole('spinbutton', { name: 'Fast' }).getAttribute('aria-describedby')
    ).toBeNull()
  })
})
