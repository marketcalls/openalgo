import { Badge } from '@/components/ui/badge'

interface RiskBadgesProps {
  stoploss: number | null
  target: number | null
  trailstop: number | null
  breakeven: boolean
}

function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function RiskBadges({ stoploss, target, trailstop, breakeven }: RiskBadgesProps) {
  return (
    <div className="flex items-center gap-2 text-xs font-mono tabular-nums">
      <span className={stoploss ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}>
        {formatPrice(stoploss)}
      </span>
      <span className="text-muted-foreground">/</span>
      <span className={target ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'}>
        {formatPrice(target)}
      </span>
      <span className="text-muted-foreground">/</span>
      <span className={trailstop ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
        {formatPrice(trailstop)}
      </span>
      {breakeven && (
        <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 text-[10px] px-1 py-0">
          BE
        </Badge>
      )}
    </div>
  )
}
