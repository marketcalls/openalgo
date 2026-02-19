import { AlertTriangle } from 'lucide-react'

interface CircuitBreakerBannerProps {
  reason?: string
}

export function CircuitBreakerBanner({ reason }: CircuitBreakerBannerProps) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-destructive/10 border-l-4 border-destructive text-destructive text-xs">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="font-medium">Circuit Breaker Tripped</span>
      {reason && <span className="text-muted-foreground">— {reason}</span>}
    </div>
  )
}
