import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OrderPriceFields } from './OrderPriceFields'

describe('OrderPriceFields', () => {
  it.each([
    ['MARKET', false, false],
    ['LIMIT', true, false],
    ['SL', true, true],
    ['SL-M', false, true],
  ] as const)('renders %s fields', (priceType, hasPrice, hasTrigger) => {
    render(
      <OrderPriceFields
        priceType={priceType}
        price={0}
        triggerPrice={0}
        onPriceChange={vi.fn()}
        onTriggerPriceChange={vi.fn()}
      />
    )

    expect(Boolean(screen.queryByLabelText('Price'))).toBe(hasPrice)
    expect(Boolean(screen.queryByLabelText('Trigger Price'))).toBe(hasTrigger)
  })

  it('reports a numeric limit price', () => {
    const onPriceChange = vi.fn()
    render(
      <OrderPriceFields
        priceType="LIMIT"
        price={0}
        triggerPrice={0}
        onPriceChange={onPriceChange}
        onTriggerPriceChange={vi.fn()}
      />
    )

    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '125.5' } })

    expect(onPriceChange).toHaveBeenLastCalledWith(125.5)
  })

  it('reports a numeric trigger price', () => {
    const onTriggerPriceChange = vi.fn()
    render(
      <OrderPriceFields
        priceType="SL-M"
        price={0}
        triggerPrice={0}
        onPriceChange={vi.fn()}
        onTriggerPriceChange={onTriggerPriceChange}
      />
    )

    fireEvent.change(screen.getByLabelText('Trigger Price'), { target: { value: '124.5' } })

    expect(onTriggerPriceChange).toHaveBeenLastCalledWith(124.5)
  })

  it('persists zero when a numeric field is cleared', () => {
    const onPriceChange = vi.fn()
    render(
      <OrderPriceFields
        priceType="LIMIT"
        price={125.5}
        triggerPrice={0}
        onPriceChange={onPriceChange}
        onTriggerPriceChange={vi.fn()}
      />
    )

    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '' } })

    expect(onPriceChange).toHaveBeenLastCalledWith(0)
  })
})
