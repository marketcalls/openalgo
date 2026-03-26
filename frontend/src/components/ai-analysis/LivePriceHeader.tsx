// frontend/src/components/ai-analysis/LivePriceHeader.tsx
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { TrendingUp, TrendingDown, Minus, Wifi, WifiOff } from 'lucide-react'

interface LivePriceHeaderProps {
  symbol: string
  exchange: string
}

export function LivePriceHeader({ symbol, exchange }: LivePriceHeaderProps) {
  const { data, isLive, isLoading } = useLiveQuote(symbol, exchange)

  if (isLoading || !data) {
    return <div className="animate-pulse h-8 w-48 bg-muted rounded" />
  }

  const change = data.change ?? 0
  const changePct = data.changePercent ?? 0
  const isUp = change > 0
  const isDown = change < 0

  return (
    <div className="flex items-center gap-3">
      <span className="text-2xl font-bold font-mono">{data.ltp?.toFixed(2) ?? '—'}</span>
      <span className={`text-sm font-medium flex items-center gap-1 ${isUp ? 'text-green-600' : isDown ? 'text-red-600' : 'text-muted-foreground'}`}>
        {isUp ? <TrendingUp className="h-4 w-4" /> : isDown ? <TrendingDown className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
        {change > 0 ? '+' : ''}{change.toFixed(2)} ({changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%)
      </span>
      <span className="text-xs text-muted-foreground">
        Bid: {data.bidPrice?.toFixed(2) ?? '—'} | Ask: {data.askPrice?.toFixed(2) ?? '—'}
      </span>
      {isLive ? <Wifi className="h-3 w-3 text-green-500" /> : <WifiOff className="h-3 w-3 text-muted-foreground" />}
    </div>
  )
}
