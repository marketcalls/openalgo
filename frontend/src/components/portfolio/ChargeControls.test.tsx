import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, userEvent } from '@/test/test-utils'
import {
  DEFAULT_CHARGES,
  type ChargeState,
} from '@/lib/portfolioRequest'
import { ChargeControls } from './ChargeControls'

function Harness() {
  const [value, setValue] = useState<ChargeState>(DEFAULT_CHARGES)
  const [exchange, setExchange] = useState<'NSE' | 'BSE'>('NSE')
  return (
    <ChargeControls
      value={value}
      onChange={setValue}
      exchange={exchange}
      onExchange={setExchange}
    />
  )
}

describe('ChargeControls', () => {
  it('updates the exchange transaction rate with the venue', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    expect(screen.getByDisplayValue('0.00307')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'BSE' }))

    expect(screen.getByDisplayValue('0.00375')).toBeInTheDocument()
  })
})
