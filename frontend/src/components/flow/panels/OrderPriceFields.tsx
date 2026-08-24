import { useId } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { PriceType } from '@/lib/flow/constants'

interface OrderPriceFieldsProps {
  priceType: PriceType
  price: number
  triggerPrice: number
  onPriceChange: (price: number) => void
  onTriggerPriceChange: (triggerPrice: number) => void
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

  return leavesCustomStrategy && hasStopPriceType
    ? { strategy, priceType: 'MARKET' }
    : { strategy }
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
        <div className="space-y-2">
          <Label htmlFor={priceId} className="text-xs">
            Price
          </Label>
          <Input
            id={priceId}
            type="number"
            step="0.05"
            className="h-8"
            value={price}
            onChange={(event) => onPriceChange(numericValue(event.target.value))}
          />
        </div>
      )}
      {(priceType === 'SL' || priceType === 'SL-M') && (
        <div className="space-y-2">
          <Label htmlFor={triggerPriceId} className="text-xs">
            Trigger Price
          </Label>
          <Input
            id={triggerPriceId}
            type="number"
            step="0.05"
            className="h-8"
            value={triggerPrice}
            onChange={(event) => onTriggerPriceChange(numericValue(event.target.value))}
          />
        </div>
      )}
    </>
  )
}
