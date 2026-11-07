import { ArrowUpRight, HelpCircle, Sparkles } from 'lucide-react'
import { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import { aggregatePositionGreeks, type LegGreeks } from './GreeksTab'
import { Simulators, type SimulatorsProps } from './Simulators'

export interface WhatIfGreeksPanelProps extends SimulatorsProps {
  legs: StrategyLeg[]
  greeksByLeg: Record<string, LegGreeks>
  atmIv: number | null
  onOpenGreeksTab?: () => void
  formatCurrency: (value: number) => string
}

function GreekCard({
  name,
  symbol,
  value,
  description,
  tone = 'neutral',
}: {
  name: string
  symbol: string
  value: string
  description: string
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  return (
    <div className="flex flex-col justify-between rounded-lg border border-border/60 bg-muted/20 p-2.5 transition hover:bg-muted/40">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="font-serif text-xs font-bold text-muted-foreground">{symbol}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {name}
          </span>
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="text-muted-foreground/60 transition hover:text-foreground"
                aria-label={`About ${name}`}
              >
                <HelpCircle className="h-3 w-3" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[200px] text-xs">
              <p>{description}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <div
        className={cn(
          'mt-2 text-base font-bold tabular-nums leading-none',
          tone === 'positive' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'negative' && 'text-rose-600 dark:text-rose-400',
          tone === 'neutral' && 'text-foreground'
        )}
      >
        {value}
      </div>
    </div>
  )
}

export function WhatIfGreeksPanel({
  spotShiftPct,
  ivShiftPct,
  daysElapsed,
  maxDays,
  onSpotShiftChange,
  onIvShiftChange,
  onDaysElapsedChange,
  onReset,
  legs,
  greeksByLeg,
  atmIv,
  onOpenGreeksTab,
  formatCurrency,
}: WhatIfGreeksPanelProps) {
  const positional = useMemo(() => aggregatePositionGreeks(legs, greeksByLeg), [legs, greeksByLeg])

  const activeLegCount = useMemo(() => legs.filter((l) => l.active).length, [legs])

  const deltaFormatted = useMemo(() => {
    if (activeLegCount === 0 || !Number.isFinite(positional.delta)) return '—'
    const prefix = positional.delta > 0 ? '+' : ''
    return `${prefix}${positional.delta.toFixed(2)}`
  }, [positional.delta, activeLegCount])

  const thetaFormatted = useMemo(() => {
    if (activeLegCount === 0 || !Number.isFinite(positional.theta)) return '—'
    return formatCurrency(positional.theta)
  }, [positional.theta, activeLegCount, formatCurrency])

  const gammaFormatted = useMemo(() => {
    if (activeLegCount === 0 || !Number.isFinite(positional.gamma)) return '—'
    return positional.gamma.toFixed(4)
  }, [positional.gamma, activeLegCount])

  const vegaFormatted = useMemo(() => {
    if (activeLegCount === 0 || !Number.isFinite(positional.vega)) return '—'
    return formatCurrency(positional.vega)
  }, [positional.vega, activeLegCount, formatCurrency])

  return (
    <div className="flex flex-col gap-4">
      {/* What-If Simulator with Sliders */}
      <Simulators
        spotShiftPct={spotShiftPct}
        ivShiftPct={ivShiftPct}
        daysElapsed={daysElapsed}
        maxDays={maxDays}
        onSpotShiftChange={onSpotShiftChange}
        onIvShiftChange={onIvShiftChange}
        onDaysElapsedChange={onDaysElapsedChange}
        onReset={onReset}
      />

      {/* Aggregate Positional Greeks Card */}
      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex items-center justify-between border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-violet-500/15 to-indigo-500/15 text-violet-600 dark:text-violet-400">
              <Sparkles className="h-3.5 w-3.5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold leading-none">Positional Greeks</h3>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Portfolio net sensitivities at current market
              </p>
            </div>
          </div>

          {atmIv !== null && (
            <span
              className="rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground"
              title="Current ATM Implied Volatility"
            >
              IV {atmIv.toFixed(1)}%
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2.5 p-3.5">
          <GreekCard
            name="Delta"
            symbol="Δ"
            value={deltaFormatted}
            description="Sensitivity to underlying price. 1.0 = gain 1 point per 1 rupee underlying rise."
            tone={
              positional.delta > 0.05
                ? 'positive'
                : positional.delta < -0.05
                  ? 'negative'
                  : 'neutral'
            }
          />
          <GreekCard
            name="Theta"
            symbol="Θ"
            value={thetaFormatted}
            description="Time decay per day. Positive = earn decay; negative = pay decay."
            tone={positional.theta > 0 ? 'positive' : positional.theta < 0 ? 'negative' : 'neutral'}
          />
          <GreekCard
            name="Gamma"
            symbol="Γ"
            value={gammaFormatted}
            description="Rate of change of Delta per 1-point move in underlying."
            tone="neutral"
          />
          <GreekCard
            name="Vega"
            symbol="ν"
            value={vegaFormatted}
            description="P&L change per 1% change in Implied Volatility."
            tone={positional.vega > 0 ? 'positive' : positional.vega < 0 ? 'negative' : 'neutral'}
          />
        </div>

        {onOpenGreeksTab && (
          <div className="border-t bg-muted/10 px-3.5 py-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={onOpenGreeksTab}
              className="h-7 w-full justify-between text-xs text-muted-foreground hover:text-foreground"
            >
              <span>Open full Greeks table</span>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
