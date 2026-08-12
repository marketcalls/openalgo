import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TemplateGrid } from './TemplateGrid'

describe('TemplateGrid preview disclosure', () => {
  it('SB-20 visibly marks a calendar payoff preview as illustrative', () => {
    render(
      <TemplateGrid direction="NON_DIRECTIONAL" onDirectionChange={vi.fn()} onPick={vi.fn()} />
    )

    const calendar = screen.getByRole('button', { name: /call calendar/i })
    expect(within(calendar).getByText('Illustrative')).toBeVisible()

    const sameExpiryStrategy = screen.getByRole('button', { name: /long straddle/i })
    expect(within(sameExpiryStrategy).queryByText('Illustrative')).not.toBeInTheDocument()
  })
})
