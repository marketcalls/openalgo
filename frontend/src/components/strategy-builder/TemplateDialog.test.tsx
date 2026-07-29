import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { STRATEGY_TEMPLATES } from '@/lib/strategyTemplates'
import type { OptionStrike } from '@/types/option-chain'
import { TemplateDialog } from './TemplateDialog'

describe('TemplateDialog payoff topology guard', () => {
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
      ce: null,
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
    expect(screen.getByRole('button', { name: 'Add Strategy' })).toBeDisabled()
  })
})
