import { Card, CardContent } from '@/components/ui/card'
import type { BuilderLeg, PresetDefinition } from '@/types/strategy-builder'

const PRESETS: PresetDefinition[] = [
  {
    id: 'short_straddle',
    name: 'Short Straddle',
    description: 'Sell ATM CE + ATM PE',
    category: 'neutral',
    legs: [
      { leg_type: 'option', action: 'SELL', option_type: 'CE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'SELL', option_type: 'PE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
  {
    id: 'short_strangle',
    name: 'Short Strangle',
    description: 'Sell OTM3 CE + OTM3 PE',
    category: 'neutral',
    legs: [
      { leg_type: 'option', action: 'SELL', option_type: 'CE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'SELL', option_type: 'PE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
  {
    id: 'iron_condor',
    name: 'Iron Condor',
    description: 'Short strangle with protective wings',
    category: 'neutral',
    legs: [
      { leg_type: 'option', action: 'SELL', option_type: 'CE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'BUY', option_type: 'CE', offset: 'OTM6', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'SELL', option_type: 'PE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'BUY', option_type: 'PE', offset: 'OTM6', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
  {
    id: 'bull_call_spread',
    name: 'Bull Call Spread',
    description: 'Buy ATM CE + Sell OTM3 CE',
    category: 'bullish',
    legs: [
      { leg_type: 'option', action: 'BUY', option_type: 'CE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'SELL', option_type: 'CE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
  {
    id: 'bear_put_spread',
    name: 'Bear Put Spread',
    description: 'Buy ATM PE + Sell OTM3 PE',
    category: 'bearish',
    legs: [
      { leg_type: 'option', action: 'BUY', option_type: 'PE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'SELL', option_type: 'PE', offset: 'OTM3', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
  {
    id: 'long_straddle',
    name: 'Long Straddle',
    description: 'Buy ATM CE + ATM PE',
    category: 'neutral',
    legs: [
      { leg_type: 'option', action: 'BUY', option_type: 'CE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
      { leg_type: 'option', action: 'BUY', option_type: 'PE', offset: 'ATM', expiry_type: 'current_week', product_type: 'MIS', quantity_lots: 1, order_type: 'MARKET' },
    ],
  },
]

interface PresetSelectorProps {
  onSelect: (legs: Omit<BuilderLeg, 'id'>[], presetId: string) => void
}

export function PresetSelector({ onSelect }: PresetSelectorProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {PRESETS.map((preset) => (
        <Card
          key={preset.id}
          className="cursor-pointer hover:border-primary transition-colors"
          onClick={() => onSelect(preset.legs, preset.id)}
        >
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-medium">{preset.name}</span>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  preset.category === 'neutral'
                    ? 'bg-gray-100 text-gray-600'
                    : preset.category === 'bullish'
                      ? 'bg-green-100 text-green-700'
                      : 'bg-red-100 text-red-700'
                }`}
              >
                {preset.category}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{preset.description}</p>
            <p className="text-[10px] text-muted-foreground mt-1">{preset.legs.length} legs</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

export { PRESETS }
