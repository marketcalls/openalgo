import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface SliderRowProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  unit?: string
  formatter?: (v: number) => string
  onChange: (v: number) => void
  accent?: 'pink' | 'violet' | 'blue'
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  unit,
  formatter,
  onChange,
  accent = 'violet',
}: SliderRowProps) {
  const accentClass = {
    pink: '[&::-webkit-slider-thumb]:bg-pink-500 accent-pink-500',
    violet: '[&::-webkit-slider-thumb]:bg-violet-500 accent-violet-500',
    blue: '[&::-webkit-slider-thumb]:bg-blue-500 accent-blue-500',
  }[accent]

  return (
    <div className="grid grid-cols-[100px_1fr_80px] items-center gap-3">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={cn(
          'h-1.5 cursor-pointer appearance-none rounded-full bg-muted outline-none',
          '[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow',
          '[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0',
          accentClass
        )}
      />
      <span className="text-right text-xs font-semibold tabular-nums">
        {formatter ? formatter(value) : `${value}${unit ?? ''}`}
      </span>
    </div>
  )
}

export interface SimulatorsProps {
  spotShiftPct: number
  ivShiftPct: number
  daysElapsed: number
  maxDays: number
  onSpotShiftChange: (v: number) => void
  onIvShiftChange: (v: number) => void
  onDaysElapsedChange: (v: number) => void
  onReset: () => void
}

export function Simulators({
  spotShiftPct,
  ivShiftPct,
  daysElapsed,
  maxDays,
  onSpotShiftChange,
  onIvShiftChange,
  onDaysElapsedChange,
  onReset,
}: SimulatorsProps) {
  const maxShiftedDays = Math.max(1, Math.floor(maxDays))
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Simulators</h3>
        <Button variant="ghost" size="sm" onClick={onReset} className="h-7 text-xs">
          <RotateCcw className="mr-1.5 h-3 w-3" />
          Reset
        </Button>
      </div>
      <div className="space-y-2.5">
        <SliderRow
          label="Spot (%)"
          value={spotShiftPct}
          min={-10}
          max={10}
          step={0.1}
          accent="pink"
          formatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
          onChange={onSpotShiftChange}
        />
        <SliderRow
          label="IV (%)"
          value={ivShiftPct}
          min={-50}
          max={50}
          step={1}
          accent="violet"
          formatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`}
          onChange={onIvShiftChange}
        />
        <SliderRow
          label="Days forward"
          value={daysElapsed}
          min={0}
          max={maxShiftedDays}
          step={1}
          accent="blue"
          formatter={(v) => `+${v}d`}
          onChange={onDaysElapsedChange}
        />
      </div>
    </div>
  )
}
