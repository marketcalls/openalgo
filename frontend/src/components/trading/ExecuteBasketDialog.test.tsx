import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import type { StrategyLeg } from '@/lib/strategyMath'
import { ExecuteBasketDialog } from './ExecuteBasketDialog'

function leg(id: string, exitPrice?: number): StrategyLeg {
  return {
    id,
    segment: 'OPTION',
    side: 'BUY',
    lots: 1,
    lotSize: 25,
    expiry: '13AUG26',
    strike: id === 'open' ? 24_700 : 24_600,
    optionType: 'CE',
    price: 100,
    iv: 12,
    active: true,
    symbol: id === 'open' ? 'NIFTY13AUG2624700CE' : 'NIFTY13AUG2624600CE',
    exitPrice,
  }
}

beforeAll(() => {
  Element.prototype.scrollIntoView = () => undefined
})

describe('ExecuteBasketDialog closed-leg boundary', () => {
  it('omits an explicitly zero-exit leg while retaining open active legs', () => {
    render(
      <ExecuteBasketDialog
        open
        onOpenChange={() => undefined}
        legs={[leg('closed', 0), leg('open')]}
        exchange="NFO"
        strategyName="Zero exit"
        apiKey="key"
      />
    )

    expect(screen.queryByText('NIFTY13AUG2624600CE')).not.toBeInTheDocument()
    expect(screen.getByText('NIFTY13AUG2624700CE')).toBeVisible()
    expect(screen.getByText('1 of 1 legs selected')).toBeVisible()
  })
})
