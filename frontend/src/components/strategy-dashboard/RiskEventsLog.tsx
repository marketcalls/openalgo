import { useEffect, useState } from 'react'
import { AlertTriangleIcon, ShieldAlertIcon, TargetIcon, TrendingDownIcon } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { dashboardApi } from '@/api/strategy-dashboard'
import type { RiskEvent } from '@/types/strategy-dashboard'
import { EmptyState } from './EmptyState'

interface RiskEventsLogProps {
  strategyId: number
  strategyType: string
}

const ALERT_ICONS: Record<string, React.ReactNode> = {
  stoploss_triggered: <TrendingDownIcon className="h-3.5 w-3.5 text-red-500" />,
  target_triggered: <TargetIcon className="h-3.5 w-3.5 text-green-500" />,
  trailstop_triggered: <AlertTriangleIcon className="h-3.5 w-3.5 text-amber-500" />,
  circuit_breaker: <ShieldAlertIcon className="h-3.5 w-3.5 text-red-600" />,
}

export function RiskEventsLog({ strategyId, strategyType }: RiskEventsLogProps) {
  const [events, setEvents] = useState<RiskEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    dashboardApi
      .getRiskEvents(strategyId, strategyType, { limit: 50 })
      .then((data) => {
        if (!cancelled) setEvents(data)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [strategyId, strategyType])

  if (loading) {
    return <div className="py-4 text-center text-sm text-muted-foreground">Loading events...</div>
  }

  if (events.length === 0) {
    return <EmptyState title="No risk events" description="No risk alerts have been triggered." />
  }

  return (
    <ScrollArea className="h-[300px]">
      <div className="space-y-2 pr-4">
        {events.map((event) => (
          <div
            key={event.id}
            className="flex items-start gap-2 p-2 rounded-md border text-xs"
          >
            <div className="mt-0.5">
              {ALERT_ICONS[event.alert_type] || (
                <AlertTriangleIcon className="h-3.5 w-3.5 text-muted-foreground" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                {event.symbol && (
                  <span className="font-medium">{event.symbol}</span>
                )}
                <span className="text-muted-foreground">
                  {event.trigger_reason || event.alert_type}
                </span>
              </div>
              {event.message && (
                <p className="text-muted-foreground mt-0.5 truncate">{event.message}</p>
              )}
            </div>
            <div className="text-[10px] text-muted-foreground whitespace-nowrap">
              {event.created_at
                ? new Date(event.created_at).toLocaleTimeString('en-IN', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : ''}
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
