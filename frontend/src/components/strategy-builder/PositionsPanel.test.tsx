import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PositionsPanel } from './PositionsPanel'

function renderPanel(probOfProfit: number | null) {
  const noop = vi.fn()
  render(
    <PositionsPanel
      legs={[]}
      onToggleLeg={noop}
      onToggleSide={noop}
      onEditLeg={noop}
      onRemoveLeg={noop}
      onToggleAll={noop}
      onReset={noop}
      probOfProfit={probOfProfit}
      maxProfit={0}
      maxLoss={0}
      breakevens={[]}
      totalPnl={0}
      netCredit={0}
      estPremium={0}
    />
  )
}

describe('PositionsPanel probability of profit', () => {
  it('renders a finite zero probability as 0.00%', () => {
    renderPanel(0)

    expect(screen.getByText('0.00%')).toBeVisible()
  })

  it('renders unavailable probability as a dash', () => {
    renderPanel(null)

    expect(screen.getByText('Prob. of Profit').nextElementSibling).toHaveTextContent('—')
  })
})
