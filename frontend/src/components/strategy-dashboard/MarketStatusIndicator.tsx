import { Badge } from '@/components/ui/badge'
import { useDashboardMarketStatus } from '@/hooks/useMarketStatus'
import type { MarketPhase } from '@/types/strategy-dashboard'

const PHASE_CONFIG: Record<MarketPhase, { label: string; dot: string; bg: string }> = {
  market_open: {
    label: 'Market Open',
    dot: 'bg-green-500 animate-pulse',
    bg: 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800',
  },
  pre_market: {
    label: 'Pre-Market',
    dot: 'bg-yellow-500',
    bg: 'bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950 dark:text-yellow-300 dark:border-yellow-800',
  },
  post_market: {
    label: 'Post-Market',
    dot: 'bg-amber-500',
    bg: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800',
  },
  market_closed: {
    label: 'Market Closed',
    dot: 'bg-gray-400',
    bg: 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700',
  },
  weekend: {
    label: 'Weekend',
    dot: 'bg-gray-400',
    bg: 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:border-gray-700',
  },
  holiday: {
    label: 'Holiday',
    dot: 'bg-purple-400',
    bg: 'bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-950 dark:text-purple-400 dark:border-purple-800',
  },
}

export function MarketStatusIndicator() {
  const { data, isLoading } = useDashboardMarketStatus()

  if (isLoading || !data) {
    return (
      <Badge variant="outline" className="text-xs bg-gray-50 text-gray-500">
        Loading...
      </Badge>
    )
  }

  const config = PHASE_CONFIG[data.phase] || PHASE_CONFIG.market_closed

  return (
    <Badge variant="outline" className={`text-xs gap-1.5 ${config.bg}`}>
      <span className={`inline-block w-2 h-2 rounded-full ${config.dot}`} />
      {config.label}
    </Badge>
  )
}
