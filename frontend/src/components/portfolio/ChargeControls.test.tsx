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
  it('associates every visible charge label with a uniquely identified control', () => {
    render(<Harness />)

    expect(screen.getByRole('group', { name: 'Exchange' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Brokerage' })).toBeInTheDocument()

    const labelledControls = [
      ['Per order (₹)', 'portfolio-charge-brokerage-flat'],
      ['STT (%)', 'portfolio-charge-stt'],
      ['Exchange txn (%)', 'portfolio-charge-exchangeTxn'],
      ['Stamp duty (%)', 'portfolio-charge-stampDuty'],
      ['GST (%)', 'portfolio-charge-gst'],
      ['SEBI (₹/crore)', 'portfolio-charge-sebiPerCrore'],
      ['Slippage (%)', 'portfolio-charge-slippage'],
    ]

    const ids = labelledControls.map(([label, id]) => {
      const control = screen.getByLabelText(label)
      expect(control).toHaveAttribute('id', id)
      return control.id
    })

    expect(new Set(ids)).toHaveLength(ids.length)
  })

  it('updates the exchange transaction rate with the venue', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    expect(screen.getByDisplayValue('0.00307')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'BSE' }))

    expect(screen.getByDisplayValue('0.00375')).toBeInTheDocument()
  })

  it('associates the percent brokerage controls with their visible labels', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.click(screen.getByRole('button', { name: '% of order' }))

    expect(screen.getByLabelText('Rate (%)')).toHaveAttribute(
      'id',
      'portfolio-charge-brokerage-pct'
    )
    expect(screen.getByLabelText('Cap / order (₹)')).toHaveAttribute(
      'id',
      'portfolio-charge-brokerage-cap'
    )
  })

  it('updates a charge control found by its visible label', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const stt = screen.getByLabelText('STT (%)')
    await user.clear(stt)
    await user.type(stt, '0.2')

    expect(stt).toHaveValue(0.2)
  })
})
