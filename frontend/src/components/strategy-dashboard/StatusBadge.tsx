import { Badge } from '@/components/ui/badge'

const STATE_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  pending_entry: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  exiting: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  closed: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  // Exit reasons
  stoploss: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  target: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  trailstop: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  manual: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  squareoff: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  group_close: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  breakeven: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
  // Order statuses
  complete: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  open: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  rejected: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  cancelled: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
}

const LABELS: Record<string, string> = {
  pending_entry: 'Pending',
  stoploss: 'SL Hit',
  target: 'TGT Hit',
  trailstop: 'TSL Hit',
  squareoff: 'Squared Off',
  group_close: 'Group Close',
  breakeven: 'Breakeven',
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null
  const key = value.toLowerCase()
  const style = STATE_STYLES[key] || 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
  const label = LABELS[key] || value.charAt(0).toUpperCase() + value.slice(1)

  return (
    <Badge variant="outline" className={`text-xs font-medium ${style}`}>
      {label}
    </Badge>
  )
}
