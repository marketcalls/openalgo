import { Button } from '@/components/ui/button'
import { type Direction, STRATEGY_TEMPLATES, type StrategyTemplate } from '@/lib/strategyTemplates'
import { cn } from '@/lib/utils'

export interface TemplateGridProps {
  direction: Direction
  onDirectionChange: (d: Direction) => void
  onPick: (tpl: StrategyTemplate) => void
}

const DIRECTION_FILTERS: Array<{ value: Direction; label: string; color: string }> = [
  { value: 'BULLISH', label: 'Bullish', color: 'bg-emerald-500 text-white' },
  { value: 'BEARISH', label: 'Bearish', color: 'bg-rose-500 text-white' },
  { value: 'NON_DIRECTIONAL', label: 'Non-Directional', color: 'bg-amber-500 text-white' },
]

function MiniPayoffIcon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 100 40"
      className="h-7 w-14"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* zero line */}
      <line
        x1="0"
        y1="20"
        x2="100"
        y2="20"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="1"
        strokeDasharray="2 2"
      />
      <path d={path} />
    </svg>
  )
}

export function TemplateGrid({ direction, onDirectionChange, onPick }: TemplateGridProps) {
  const filtered = STRATEGY_TEMPLATES.filter((t) => t.direction === direction)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {DIRECTION_FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant="outline"
            onClick={() => onDirectionChange(f.value)}
            className={cn(
              'h-8 text-xs',
              direction === f.value && `${f.color} border-transparent hover:opacity-90`
            )}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
        {filtered.map((tpl) => (
          <button
            key={tpl.id}
            onClick={() => onPick(tpl)}
            className={cn(
              'group flex flex-col items-center gap-1.5 rounded-lg border bg-card p-2.5 transition-all',
              'hover:-translate-y-0.5 hover:border-primary hover:shadow-md'
            )}
          >
            <div
              className={cn(
                'flex h-10 w-full items-center justify-center rounded-md',
                tpl.direction === 'BULLISH' &&
                  'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
                tpl.direction === 'BEARISH' && 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
                tpl.direction === 'NON_DIRECTIONAL' &&
                  'bg-amber-500/10 text-amber-600 dark:text-amber-400'
              )}
            >
              <MiniPayoffIcon path={tpl.payoffPath} />
            </div>
            <div className="line-clamp-2 text-center text-[10px] font-medium leading-tight text-muted-foreground group-hover:text-foreground">
              {tpl.name}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
