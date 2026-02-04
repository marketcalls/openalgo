// components/trading/QuoteHeader.tsx
// Real-time quote header display for PlaceOrderDialog

import { cn } from '@/lib/utils'

export interface QuoteHeaderProps {
  symbol: string
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

export function QuoteHeader({
  symbol,
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
      {/* Symbol with Exchange and LTP Row */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <span className="text-sm font-medium truncate max-w-[200px]">
            {symbol}
          </span>
          <span className="text-xs text-muted-foreground">
            ({exchange})
          </span>
        </div>
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
          <span className="text-red-500 font-medium font-mono">
            {bidPrice !== undefined && bidPrice > 0 ? bidPrice.toFixed(2) : '-'}
          </span>
          {bidSize !== undefined && bidSize > 0 && (
            <span className="text-muted-foreground text-xs">x {bidSize.toLocaleString()}</span>
          )}
        </div>
        <div className="text-muted-foreground">|</div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Ask:</span>
          <span className="text-green-500 font-medium font-mono">
            {askPrice !== undefined && askPrice > 0 ? askPrice.toFixed(2) : '-'}
          </span>
          {askSize !== undefined && askSize > 0 && (
            <span className="text-muted-foreground text-xs">x {askSize.toLocaleString()}</span>
          )}
        </div>
      </div>
    </div>
  )
}
