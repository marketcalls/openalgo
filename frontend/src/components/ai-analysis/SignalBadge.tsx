// frontend/src/components/ai-analysis/SignalBadge.tsx
import { Badge } from '@/components/ui/badge'
import { SIGNAL_CONFIG } from '@/types/ai-analysis'
import type { SignalType } from '@/types/ai-analysis'

interface SignalBadgeProps {
  signal: SignalType
  size?: 'sm' | 'md' | 'lg'
}

export function SignalBadge({ signal, size = 'md' }: SignalBadgeProps) {
  const config = SIGNAL_CONFIG[signal]
  const sizeClass = size === 'lg' ? 'text-lg px-4 py-2' : size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1'

  return (
    <Badge className={`${config.bgColor} ${config.color} ${sizeClass} font-semibold`}>
      {config.label}
    </Badge>
  )
}
