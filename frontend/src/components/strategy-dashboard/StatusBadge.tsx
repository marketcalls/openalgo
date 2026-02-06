import { Badge } from '@/components/ui/badge'
import type { ExitReason, PositionState, RiskMonitoringState } from '@/types/strategy-dashboard'

interface StatusBadgeProps {
  positionState: PositionState
  exitReason: ExitReason | null
  riskMonitoring?: RiskMonitoringState
}

const EXIT_BADGE_MAP: Record<
  string,
  { label: string; className: string; pulse?: boolean }
> = {
  stoploss: {
    label: 'SL',
    className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
  target: {
    label: 'TGT',
    className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
  trailstop: {
    label: 'TSL',
    className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  breakeven_sl: {
    label: 'BE-SL',
    className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  combined_sl: {
    label: 'C-SL',
    className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
  combined_target: {
    label: 'C-TGT',
    className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
  combined_tsl: {
    label: 'C-TSL',
    className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  manual: {
    label: 'Manual',
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
  },
  squareoff: {
    label: 'SQ-OFF',
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
  },
  auto_squareoff: {
    label: 'AUTO-SQ',
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
  },
  rejected: {
    label: 'Failed',
    className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    pulse: true,
  },
}

export function StatusBadge({ positionState, exitReason, riskMonitoring }: StatusBadgeProps) {
  // Active positions
  if (positionState === 'active') {
    if (riskMonitoring === 'active') {
      return (
        <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
          Monitoring
        </Badge>
      )
    }
    if (riskMonitoring === 'paused') {
      return (
        <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
          Paused
        </Badge>
      )
    }
    return (
      <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
        Active
      </Badge>
    )
  }

  // Exiting positions
  if (positionState === 'exiting') {
    return (
      <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 animate-pulse">
        Exiting...
      </Badge>
    )
  }

  // Pending entry
  if (positionState === 'pending_entry') {
    return (
      <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse">
        Pending
      </Badge>
    )
  }

  // Closed positions — show exit reason
  if (positionState === 'closed' && exitReason) {
    const config = EXIT_BADGE_MAP[exitReason]
    if (config) {
      return (
        <Badge className={`${config.className}${config.pulse ? ' animate-pulse' : ''}`}>
          {config.label}
        </Badge>
      )
    }
  }

  return (
    <Badge variant="secondary">
      {positionState || 'Unknown'}
    </Badge>
  )
}
