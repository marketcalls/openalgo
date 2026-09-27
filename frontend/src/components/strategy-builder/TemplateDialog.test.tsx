import { render, screen, within } from '@testing-library/react'
import { axe, toHaveNoViolations } from 'jest-axe'
import { describe, expect, it, vi } from 'vitest'
import { STRATEGY_TEMPLATES } from '@/lib/strategyTemplates'
import type { OptionStrike } from '@/types/option-chain'
import { TemplateDialog } from './TemplateDialog'

expect.extend(toHaveNoViolations)

describe('TemplateDialog payoff topology guard', () => {
  it('SB-18 labels strike, expiry, lot, and icon controls without accessibility violations', async () => {
    const template = STRATEGY_TEMPLATES.find((item) => item.id === 'long_call')
    const chain: OptionStrike[] = [
      { strike: 100, ce: { symbol: 'CALL100', ltp: 5 } as OptionStrike['ce'], pe: null },
    ]

    const view = render(
      <TemplateDialog
        open
        onOpenChange={vi.fn()}
        template={template ?? null}
        expiry="04AUG26"
        expiries={['04AUG26']}
        onExpiryChange={vi.fn()}
        chain={chain}
        atmStrike={100}
        strikeStep={10}
        onConfirm={vi.fn()}
      />
    )

    const dialog = screen.getByRole('dialog', { name: 'Long Call' })
    expect(within(dialog).getByRole('combobox', { name: /strike for buy call leg 1/i })).toBeVisible()
    expect(within(dialog).getByRole('combobox', { name: /strategy expiry/i })).toBeVisible()
    expect(within(dialog).getByRole('spinbutton', { name: /strategy lot quantity/i })).toBeVisible()
    expect(within(dialog).getByRole('button', { name: /decrease strategy lots/i })).toBeVisible()
    expect(within(dialog).getByRole('button', { name: /increase strategy lots/i })).toBeVisible()
    expect(await axe(view.container)).toHaveNoViolations()
  })

  it('PG-22 disables Add Strategy when an offset is outside the loaded chain', () => {
    const template = STRATEGY_TEMPLATES.find((item) => item.id === 'batman_strategy')
    const chain: OptionStrike[] = [90, 100, 110].map((strike) => ({
      strike,
      ce: null,
      pe: null,
    }))

    render(
      <TemplateDialog
        open
        onOpenChange={vi.fn()}
        template={template ?? null}
        expiry="04-AUG-2026"
        expiries={['04-AUG-2026']}
        onExpiryChange={vi.fn()}
        chain={chain}
        atmStrike={100}
        strikeStep={10}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/outside the loaded option chain/i)
    expect(screen.getByRole('button', { name: 'Add Strategy' })).toBeDisabled()
  })

  it('PG-21 disables a calendar instead of collapsing both legs into one expiry', () => {
    const template = STRATEGY_TEMPLATES.find((item) => item.id === 'call_calendar')
    const chain: OptionStrike[] = [90, 100, 110].map((strike) => ({
      strike,
      ce: { symbol: `CALL${strike}`, ltp: 5 } as OptionStrike['ce'],
      pe: null,
    }))

    render(
      <TemplateDialog
        open
        onOpenChange={vi.fn()}
        template={template ?? null}
        expiry="04AUG26"
        expiries={['04AUG26']}
        onExpiryChange={vi.fn()}
        chain={chain}
        atmStrike={100}
        strikeStep={10}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/later expiry is required/i)
    expect(screen.getByRole('combobox', { name: /strategy expiry/i })).toHaveAttribute(
      'aria-invalid',
      'true'
    )
    for (const strike of screen.getAllByRole('combobox', { name: /strike for/i })) {
      expect(strike).toHaveAttribute('aria-invalid', 'false')
    }
    expect(screen.getByRole('button', { name: 'Add Strategy' })).toBeDisabled()
  })

  it('PG-22 disables a template when its required CE or PE contract is missing', () => {
    const template = STRATEGY_TEMPLATES.find((item) => item.id === 'long_call')
    const chain: OptionStrike[] = [{ strike: 100, ce: null, pe: null }]

    render(
      <TemplateDialog
        open
        onOpenChange={vi.fn()}
        template={template ?? null}
        expiry="04AUG26"
        expiries={['04AUG26']}
        onExpiryChange={vi.fn()}
        chain={chain}
        atmStrike={100}
        strikeStep={10}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.getByRole('alert')).toHaveTextContent(/required CE contract/i)
    expect(screen.getByRole('combobox', { name: /strike for buy call leg 1/i })).toHaveAttribute(
      'aria-invalid',
      'true'
    )
    expect(screen.getByRole('combobox', { name: /strategy expiry/i })).toHaveAttribute(
      'aria-invalid',
      'false'
    )
    expect(screen.getByRole('button', { name: 'Add Strategy' })).toBeDisabled()
  })
})
