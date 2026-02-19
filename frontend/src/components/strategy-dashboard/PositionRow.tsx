import React from 'react'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-react'
import type { DashboardPosition, DistanceMetrics } from '@/types/strategy-dashboard'
import { StatusBadge } from './StatusBadge'

interface PositionRowProps {
  position: DashboardPosition
  onClose: (positionId: number) => void
  closing?: boolean
}

/** Compute distance from LTP to SL/TGT/TSL thresholds. */
export function computeDistanceMetrics(position: DashboardPosition): DistanceMetrics {
  const { ltp, stoploss_price, target_price, trailstop_price, action } = position
  const isLong = action === 'BUY'

  const compute = (ref: number | null, favorable: boolean) => {
    if (!ref || ref === 0 || !ltp || ltp === 0) return null
    const dist = favorable
      ? isLong
        ? ref - ltp
        : ltp - ref
      : isLong
        ? ltp - ref
        : ref - ltp
    return { points: Math.abs(dist), pct: (Math.abs(dist) / ltp) * 100 }
  }

  return {
    sl: compute(stoploss_price, false),
    tgt: compute(target_price, true),
    tsl: compute(trailstop_price, false),
  }
}

/** Get color zone for distance percentage. */
export function getDistanceZone(pct: number | null): 'safe' | 'warning' | 'danger' {
  if (pct === null) return 'safe'
  if (pct > 10) return 'safe'
  if (pct >= 5) return 'warning'
  return 'danger'
}

const ZONE_CLASSES: Record<string, string> = {
  safe: 'text-muted-foreground',
  warning: 'text-amber-500',
  danger: 'text-destructive animate-pulse font-bold',
}

function formatDist(d: { points: number; pct: number } | null) {
  if (!d) return '—'
  return `${d.points.toFixed(1)} (${d.pct.toFixed(1)}%)`
}

export const PositionRow = React.memo(function PositionRow({
  position,
  onClose,
  closing,
}: PositionRowProps) {
  const dist = computeDistanceMetrics(position)
  const pnlColor =
    (position.unrealized_pnl || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'

  return (
    <tr className="border-b text-xs">
      {/* 1. Symbol */}
      <td className="py-2 px-2 font-medium">{position.symbol}</td>
      {/* 2. Qty */}
      <td className={`py-2 px-1 ${position.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>
        {position.action === 'BUY' ? '+' : '-'}
        {position.quantity}
      </td>
      {/* 3. Avg Entry */}
      <td className="py-2 px-1">{position.average_entry_price?.toFixed(2) ?? '—'}</td>
      {/* 4. LTP */}
      <td className="py-2 px-1">{position.ltp?.toFixed(2) ?? '—'}</td>
      {/* 5. P&L */}
      <td className={`py-2 px-1 font-medium ${pnlColor}`}>
        {position.unrealized_pnl?.toFixed(2) ?? '0.00'}
      </td>
      {/* 6. SL */}
      <td className="py-2 px-1">{position.stoploss_price?.toFixed(2) ?? '—'}</td>
      {/* 7. SL Dist */}
      <td className={`py-2 px-1 ${ZONE_CLASSES[getDistanceZone(dist.sl?.pct ?? null)]}`}>
        {formatDist(dist.sl)}
      </td>
      {/* 8. TGT */}
      <td className="py-2 px-1">{position.target_price?.toFixed(2) ?? '—'}</td>
      {/* 9. TGT Dist */}
      <td className={`py-2 px-1 ${ZONE_CLASSES[getDistanceZone(dist.tgt?.pct ?? null)]}`}>
        {formatDist(dist.tgt)}
      </td>
      {/* 10. TSL */}
      <td className="py-2 px-1">{position.trailstop_price?.toFixed(2) ?? '—'}</td>
      {/* 11. TSL Dist */}
      <td className={`py-2 px-1 ${ZONE_CLASSES[getDistanceZone(dist.tsl?.pct ?? null)]}`}>
        {formatDist(dist.tsl)}
      </td>
      {/* 12. BE */}
      <td className="py-2 px-1">
        {position.breakeven_activated && (
          <span className="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 px-1 rounded">
            BE
          </span>
        )}
      </td>
      {/* 13. Status */}
      <td className="py-2 px-1">
        <StatusBadge value={position.position_state} />
      </td>
      {/* 14. Action */}
      <td className="py-2 px-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => onClose(position.id)}
          disabled={closing}
        >
          <X className="h-3 w-3" />
        </Button>
      </td>
    </tr>
  )
})
