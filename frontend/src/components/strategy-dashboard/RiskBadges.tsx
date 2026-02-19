import { Badge } from '@/components/ui/badge'
import type { DashboardPosition } from '@/types/strategy-dashboard'

export function RiskBadges({ position }: { position: DashboardPosition }) {
  const badges: { label: string; value: string; color: string }[] = []

  if (position.stoploss_price) {
    badges.push({
      label: 'SL',
      value: position.stoploss_price.toFixed(2),
      color: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800',
    })
  }
  if (position.target_price) {
    badges.push({
      label: 'TGT',
      value: position.target_price.toFixed(2),
      color: 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800',
    })
  }
  if (position.trailstop_price) {
    badges.push({
      label: 'TSL',
      value: position.trailstop_price.toFixed(2),
      color: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
    })
  }
  if (position.breakeven_activated) {
    badges.push({
      label: 'BE',
      value: 'Active',
      color: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-950 dark:text-cyan-300 dark:border-cyan-800',
    })
  }

  if (badges.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1">
      {badges.map((b) => (
        <Badge key={b.label} variant="outline" className={`text-[10px] px-1.5 py-0 ${b.color}`}>
          {b.label}: {b.value}
        </Badge>
      ))}
    </div>
  )
}
