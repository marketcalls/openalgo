import { Clock, RotateCcw, Sliders, TrendingUp, Waves } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface SliderRowProps {
  icon: ReactNode
  label: string
  sublabel: string
  value: number
  min: number
  max: number
  step: number
  formatter: (v: number) => string
  onChange: (v: number) => void
  accent?: 'pink' | 'violet' | 'blue'
  centered?: boolean
}

function SliderRow({
  icon,
  label,
  sublabel,
  value,
  min,
  max,
  step,
  formatter,
  onChange,
  accent = 'violet',
  centered = false,
}: SliderRowProps) {
  // Note: keep the native range appearance so the browser paints the thumb
  // — we tint only the track (accent-*) and rely on the user agent for thumb
  // rendering, which gives us a visible, high-contrast circle in every
  // theme (light, dark, and our analyzer theme). A fully custom thumb via
  // ::webkit-slider-thumb { appearance:none } was invisible on light mode
  // because Tailwind utilities inside pseudo-selectors aren't composed the
  // way the `accent` utility is.
  const accentTrack = {
    pink: 'accent-pink-500',
    violet: 'accent-violet-500',
    blue: 'accent-blue-500',
  }[accent]

  const accentBg = {
    pink: 'from-pink-500/15 to-pink-500/0 text-pink-600 dark:text-pink-400',
    violet: 'from-violet-500/15 to-violet-500/0 text-violet-600 dark:text-violet-400',
    blue: 'from-blue-500/15 to-blue-500/0 text-blue-600 dark:text-blue-400',
  }[accent]

  const accentValue = {
    pink: 'text-pink-600 dark:text-pink-400',
    violet: 'text-violet-600 dark:text-violet-400',
    blue: 'text-blue-600 dark:text-blue-400',
  }[accent]

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            'inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br',
            accentBg
          )}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold leading-none">{label}</div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">{sublabel}</div>
        </div>
        <span className={cn('text-sm font-semibold tabular-nums', accentValue)}>
          {formatter(value)}
        </span>
      </div>
      <div className="relative px-1">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className={cn(
            'h-2 w-full cursor-pointer rounded-full bg-muted outline-none',
            accentTrack
          )}
        />
        {/* Center tick for bipolar sliders */}
        {centered && (
          <span
            className="pointer-events-none absolute top-1/2 h-2 w-[2px] -translate-y-1/2 rounded-full bg-border"
            style={{ left: `${((0 - min) / (max - min)) * 100}%` }}
          />
        )}
        <div className="mt-1 flex justify-between text-[9px] font-medium tabular-nums text-muted-foreground/70">
          <span>{formatter(min)}</span>
          {centered && <span className="opacity-60">0</span>}
          <span>{formatter(max)}</span>
        </div>
      </div>
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
  const isDirty = spotShiftPct !== 0 || ivShiftPct !== 0 || daysElapsed !== 0

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-amber-500/15 to-pink-500/15 text-amber-600 dark:text-amber-400">
            <Sliders className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">What-If Simulator</h3>
            <p className="mt-1 text-[10px] text-muted-foreground">
              Stress-test the strategy across spot, IV and time
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          disabled={!isDirty}
          className="h-7 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40"
        >
          <RotateCcw className="mr-1 h-3 w-3" />
          Reset
        </Button>
      </div>
      <div className="space-y-5 px-4 py-4">
        <SliderRow
          icon={<TrendingUp className="h-3.5 w-3.5" />}
          label="Spot Price"
          sublabel="Move underlying up or down"
          value={spotShiftPct}
          min={-10}
          max={10}
          step={0.1}
          accent="pink"
          centered
          formatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
          onChange={onSpotShiftChange}
        />
        <SliderRow
          icon={<Waves className="h-3.5 w-3.5" />}
          label="Implied Volatility"
          sublabel="Vol expansion or crush"
          value={ivShiftPct}
          min={-50}
          max={50}
          step={1}
          accent="violet"
          centered
          formatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`}
          onChange={onIvShiftChange}
        />
        <SliderRow
          icon={<Clock className="h-3.5 w-3.5" />}
          label="Days Forward"
          sublabel="Advance time toward expiry"
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
