// frontend/src/components/reports/DateRangePresets.tsx
/**
 * Shared quick date-range chip row (fork-only) for the P&L History and
 * Trade Book filter rows - see lib/dateRangePresets.ts for the actual
 * range math. Renders below the Start/End date inputs; picking a chip
 * fills both dates and fetches immediately (one click), and the active
 * chip stays highlighted until the dates are edited by hand.
 */
import { Button } from '@/components/ui/button'
import { DATE_RANGE_PRESETS } from '@/lib/dateRangePresets'

interface DateRangePresetsProps {
  activeKey: string | null
  onSelect: (start: string, end: string, key: string) => void
}

export function DateRangePresets({ activeKey, onSelect }: DateRangePresetsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {DATE_RANGE_PRESETS.map((preset) => (
        <Button
          key={preset.key}
          type="button"
          variant={activeKey === preset.key ? 'default' : 'outline'}
          size="sm"
          onClick={() => {
            const { start, end } = preset.range()
            onSelect(start, end, preset.key)
          }}
        >
          {preset.label}
        </Button>
      ))}
    </div>
  )
}
