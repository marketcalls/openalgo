import { CandlestickChart } from 'lucide-react'
import { Link } from 'react-router'
import { chartHref } from '@/lib/trading/chartLink'
import { cn } from '@/lib/utils'

interface Props {
  symbol: string
  exchange: string
  className?: string
}

/**
 * A symbol in the order book, trade book or positions table that opens its
 * chart. A plain link, so a middle click or Ctrl+click opens the chart in a
 * new tab and leaves the book where it was.
 */
export function ChartSymbolLink({ symbol, exchange, className }: Props) {
  return (
    <Link
      to={chartHref(symbol, exchange)}
      title="Open chart"
      aria-label={`Open chart for ${symbol} on ${exchange}`}
      className={cn(
        'group inline-flex items-center gap-1.5 rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className
      )}
    >
      <span className="underline-offset-4 group-hover:underline">{symbol}</span>
      <CandlestickChart
        aria-hidden="true"
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-primary"
      />
    </Link>
  )
}
