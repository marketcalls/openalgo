import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export type RiskType = 'percentage' | 'points' | null

export interface RiskField {
  type: RiskType
  value: string
}

interface RiskFieldGroupProps {
  label: string
  field: RiskField
  onChange: (field: RiskField) => void
  pointsOnly?: boolean
}

export function RiskFieldGroup({
  label,
  field,
  onChange,
  pointsOnly = false,
}: RiskFieldGroupProps) {
  const typeValue = field.type ?? 'none'

  return (
    <div className="space-y-2">
      <Label className="text-sm">{label}</Label>
      <Tabs
        value={typeValue}
        onValueChange={(v) =>
          onChange({ ...field, type: v === 'none' ? null : (v as RiskType) })
        }
      >
        {pointsOnly ? (
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="points">Points (₹)</TabsTrigger>
            <TabsTrigger value="none">None</TabsTrigger>
          </TabsList>
        ) : (
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="percentage">Percentage</TabsTrigger>
            <TabsTrigger value="points">Points</TabsTrigger>
            <TabsTrigger value="none">None</TabsTrigger>
          </TabsList>
        )}
      </Tabs>
      {field.type && (
        <Input
          type="number"
          step="0.01"
          min="0"
          value={field.value}
          onChange={(e) => onChange({ ...field, value: e.target.value })}
          placeholder={pointsOnly ? '5000' : field.type === 'percentage' ? '2.0' : '50'}
          className="font-mono"
        />
      )}
    </div>
  )
}
