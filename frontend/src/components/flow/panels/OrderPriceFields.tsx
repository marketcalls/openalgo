import { useId } from 'react'
import { Input } from '@/components/ui/input'
import type { PriceType } from '@/lib/flow/constants'

import { TemplatableField } from './TemplatableField'

interface OrderPriceFieldsProps {
  /**
   * Which of the two boxes is shown at all. A stop order needs a trigger, a
   * limit order needs a price, and a market order needs neither.
   */
  priceType: PriceType
  /**
   * Both are `unknown` rather than `number` because either may hold a
   * {{reference}}. They are order-critical to the executor, so an unresolved
   * one refuses the order instead of being sent as a zero.
   */
  price: unknown
  triggerPrice: unknown
  onPriceChange: (price: string | number) => void
  onTriggerPriceChange: (triggerPrice: string | number) => void
}

interface OptionsMultiPricingState {
  strategy: string
  priceType: PriceType
}

export function getOptionsMultiStrategyUpdate(
  current: OptionsMultiPricingState,
  strategy: string
): { strategy: string; priceType?: PriceType } {
  const leavesCustomStrategy = current.strategy === 'custom' && strategy !== 'custom'
  const hasStopPriceType = current.priceType === 'SL' || current.priceType === 'SL-M'

  return leavesCustomStrategy && hasStopPriceType ? { strategy, priceType: 'MARKET' } : { strategy }
}

function numericValue(value: string): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export function OrderPriceFields({
  priceType,
  price,
  triggerPrice,
  onPriceChange,
  onTriggerPriceChange,
}: OrderPriceFieldsProps) {
  const priceId = useId()
  const triggerPriceId = useId()

  return (
    <>
      {(priceType === 'LIMIT' || priceType === 'SL') && (
        <TemplatableField
          label="Price"
          htmlFor={priceId}
          value={price}
          onChange={onPriceChange}
          fallback={0}
          placeholder="{{webhook.price}}"
        >
          <Input
            id={priceId}
            type="number"
            step="0.05"
            className="h-8"
            value={price as number}
            onChange={(event) => onPriceChange(numericValue(event.target.value))}
          />
        </TemplatableField>
      )}
      {(priceType === 'SL' || priceType === 'SL-M') && (
        <TemplatableField
          label="Trigger Price"
          htmlFor={triggerPriceId}
          value={triggerPrice}
          onChange={onTriggerPriceChange}
          fallback={0}
          placeholder="{{webhook.triggerPrice}}"
        >
          <Input
            id={triggerPriceId}
            type="number"
            step="0.05"
            className="h-8"
            value={triggerPrice as number}
            onChange={(event) => onTriggerPriceChange(numericValue(event.target.value))}
          />
        </TemplatableField>
      )}
    </>
  )
}
