// components/trading/QuoteHeader.tsx
// Real-time quote header display for PlaceOrderDialog

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export interface QuoteHeaderProps {
  exchange: string
  ltp?: number
  prevClose?: number
  change?: number
  changePercent?: number
  bidPrice?: number
  askPrice?: number
  bidSize?: number
  askSize?: number
  isLoading?: boolean
}

// Exchange badge colors
function getExchangeBadgeClass(exchange: string): string {
  switch (exchange) {
    case 'NFO':
      return 'bg-purple-500/20 text-purple-400 border-purple-500/30'
    case 'BFO':
      return 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    case 'NSE':
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    case 'BSE':
      return 'bg-pink-500/20 text-pink-400 border-pink-500/30'
    case 'MCX':
      return 'bg-orange-500/20 text-orange-400 border-orange-500/30'
    case 'CDS':
      return 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
    case 'BCD':
      return 'bg-rose-500/20 text-rose-400 border-rose-500/30'
    default:
      return 'bg-gray-500/20 text-gray-400 border-gray-500/30'
  }
}

export function QuoteHeader({
  exchange,
  ltp,
  prevClose,
  change,
  changePercent,
  bidPrice,
  askPrice,
  bidSize,
  askSize,
  isLoading,
}: QuoteHeaderProps) {
  // Calculate change from prevClose if not provided
  const displayChange = change ?? (ltp && prevClose ? ltp - prevClose : undefined)
  const displayChangePercent = changePercent ?? (displayChange && prevClose ? (displayChange / prevClose) * 100 : undefined)

  const isPositive = displayChange !== undefined && displayChange >= 0

  if (isLoading) {
    return (
      <div className="p-3 bg-muted/30 rounded-lg animate-pulse">
        <div className="h-4 bg-muted rounded w-24 mb-2" />
        <div className="h-6 bg-muted rounded w-32" />
      </div>
    )
  }

  return (
    <div className="p-3 bg-muted/30 rounded-lg space-y-2">
      {/* Exchange Badge and LTP Row */}
      <div className="flex items-center justify-between">
        <Badge className={cn('text-[10px] px-1.5 py-0', getExchangeBadgeClass(exchange))}>
          {exchange}
        </Badge>
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold">
            {ltp !== undefined ? ltp.toFixed(2) : '-'}
          </span>
          {displayChange !== undefined && (
            <span className={cn(
              'text-sm font-medium',
              isPositive ? 'text-green-500' : 'text-red-500'
            )}>
              {isPositive ? '+' : ''}{displayChange.toFixed(2)}
              {displayChangePercent !== undefined && (
                <span className="ml-1">
                  ({isPositive ? '+' : ''}{displayChangePercent.toFixed(2)}%)
                </span>
              )}
            </span>
          )}
        </div>
      </div>

      {/* Bid/Ask Row */}
      <div className="flex items-center justify-between text-sm border-t border-border/50 pt-2">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Bid:</span>
          <span className="text-emerald-400 font-medium font-mono">
            {bidPrice !== undefined && bidPrice > 0 ? bidPrice.toFixed(2) : '-'}
          </span>
          {bidSize !== undefined && bidSize > 0 && (
            <span className="text-muted-foreground text-xs">x{bidSize.toLocaleString()}</span>
          )}
        </div>
        <div className="text-muted-foreground">|</div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Ask:</span>
          <span className="text-rose-400 font-medium font-mono">
            {askPrice !== undefined && askPrice > 0 ? askPrice.toFixed(2) : '-'}
          </span>
          {askSize !== undefined && askSize > 0 && (
            <span className="text-muted-foreground text-xs">x{askSize.toLocaleString()}</span>
          )}
        </div>
      </div>
    </div>
  )
}
