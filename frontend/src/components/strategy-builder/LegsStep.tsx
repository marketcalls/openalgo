import { PlusIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { BuilderLeg } from '@/types/strategy-builder'
import { LegCard } from './LegCard'
import { PresetSelector } from './PresetSelector'

interface LegsStepProps {
  legs: BuilderLeg[]
  onChange: (legs: BuilderLeg[]) => void
  onPresetSelect: (presetId: string) => void
  onBack: () => void
  onNext: () => void
}

function generateId() {
  return Math.random().toString(36).substring(2, 10)
}

const DEFAULT_LEG: Omit<BuilderLeg, 'id'> = {
  leg_type: 'option',
  action: 'SELL',
  option_type: 'CE',
  offset: 'ATM',
  expiry_type: 'current_week',
  product_type: 'MIS',
  quantity_lots: 1,
  order_type: 'MARKET',
}

export function LegsStep({ legs, onChange, onPresetSelect, onBack, onNext }: LegsStepProps) {
  const addLeg = () => {
    onChange([...legs, { ...DEFAULT_LEG, id: generateId() }])
  }

  const updateLeg = (index: number, leg: BuilderLeg) => {
    const updated = [...legs]
    updated[index] = leg
    onChange(updated)
  }

  const removeLeg = (index: number) => {
    onChange(legs.filter((_, i) => i !== index))
  }

  const handlePresetSelect = (presetLegs: Omit<BuilderLeg, 'id'>[], presetId: string) => {
    const withIds = presetLegs.map((leg) => ({ ...leg, id: generateId() }))
    onChange(withIds)
    onPresetSelect(presetId)
  }

  return (
    <div className="space-y-6">
      {/* Presets */}
      <div>
        <h3 className="text-sm font-medium mb-3">Quick Start with Presets</h3>
        <PresetSelector onSelect={handlePresetSelect} />
      </div>

      {/* Custom Legs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">
            Legs {legs.length > 0 && `(${legs.length})`}
          </h3>
          <Button variant="outline" size="sm" onClick={addLeg}>
            <PlusIcon className="h-3.5 w-3.5 mr-1" />
            Add Leg
          </Button>
        </div>

        {legs.length === 0 ? (
          <div className="text-center py-8 text-sm text-muted-foreground border border-dashed rounded-lg">
            Select a preset above or add legs manually
          </div>
        ) : (
          <div className="space-y-2">
            {legs.map((leg, idx) => (
              <LegCard
                key={leg.id}
                leg={leg}
                index={idx}
                onChange={(l) => updateLeg(idx, l)}
                onRemove={() => removeLeg(idx)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-between pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={onNext} disabled={legs.length === 0}>
          Next: Risk Config
        </Button>
      </div>
    </div>
  )
}
