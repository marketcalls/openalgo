// components/trading/MarketDepthPanel.tsx
// Collapsible market depth display for PlaceOrderDialog

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

export interface DepthLevel {
  price: number
  quantity: number
  orders?: number
}

export interface MarketDepthPanelProps {
  depth?: {
    buy: DepthLevel[]
    sell: DepthLevel[]
  }
  isExpanded: boolean
  onToggle: () => void
  maxLevels?: number
}

// Individual depth level row with gradient bar
function DepthRow({
  price,
  quantity,
  maxQty,
  side,
}: {
  price: number
  quantity: number
  maxQty: number
  side: 'buy' | 'sell'
}) {
  const pct = maxQty > 0 ? Math.min((quantity / maxQty) * 100, 100) : 0

  return (
    <div className="relative flex items-center gap-2 py-1 px-2">
      <div className="absolute inset-0 overflow-hidden">
        <div
          className={cn(
            'absolute top-0 bottom-0 transition-all duration-300',
            side === 'buy'
              ? 'left-0 bg-gradient-to-r from-emerald-500/20 to-transparent'
              : 'right-0 bg-gradient-to-l from-rose-500/20 to-transparent'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn(
        'relative z-10 flex-1 font-mono text-xs',
        side === 'buy' ? 'text-emerald-400' : 'text-rose-400'
      )}>
        {price.toFixed(2)}
      </span>
      <span className="relative z-10 font-mono text-xs text-muted-foreground">
        {quantity.toLocaleString()}
      </span>
    </div>
  )
}

export function MarketDepthPanel({
  depth,
  isExpanded,
  onToggle,
  maxLevels = 5,
}: MarketDepthPanelProps) {
  const buyLevels = depth?.buy?.slice(0, maxLevels) ?? []
  const sellLevels = depth?.sell?.slice(0, maxLevels) ?? []

  // Calculate max quantity for gradient scaling
  const maxBuyQty = Math.max(...buyLevels.map(l => l.quantity), 1)
  const maxSellQty = Math.max(...sellLevels.map(l => l.quantity), 1)
  const maxQty = Math.max(maxBuyQty, maxSellQty)

  const hasDepth = buyLevels.length > 0 || sellLevels.length > 0

  return (
    <Collapsible open={isExpanded} onOpenChange={onToggle}>
      <CollapsibleTrigger className="flex items-center justify-between w-full py-2 px-3 bg-muted/20 rounded hover:bg-muted/30 transition-colors">
        <span className="text-sm text-muted-foreground">
          {isExpanded ? 'Hide' : 'Show'} Market Depth
        </span>
        <span className="text-xs text-muted-foreground">
          {isExpanded ? '[-]' : '[+]'}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent>
        {!hasDepth ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            No depth data available
          </div>
        ) : (
          <div className="mt-2 border rounded-lg overflow-hidden">
            {/* Header */}
            <div className="grid grid-cols-2 bg-muted/30">
              <div className="px-2 py-1.5 text-xs font-medium text-emerald-500 border-r">
                Bids
              </div>
              <div className="px-2 py-1.5 text-xs font-medium text-rose-500">
                Asks
              </div>
            </div>

            {/* Depth rows */}
            <div className="grid grid-cols-2 divide-x">
              {/* Buy side (bids) */}
              <div className="divide-y divide-border/50">
                {buyLevels.length > 0 ? (
                  buyLevels.map((level, idx) => (
                    <DepthRow
                      key={`buy-${idx}`}
                      price={level.price}
                      quantity={level.quantity}
                      maxQty={maxQty}
                      side="buy"
                    />
                  ))
                ) : (
                  <div className="py-2 text-center text-xs text-muted-foreground">-</div>
                )}
              </div>

              {/* Sell side (asks) */}
              <div className="divide-y divide-border/50">
                {sellLevels.length > 0 ? (
                  sellLevels.map((level, idx) => (
                    <DepthRow
                      key={`sell-${idx}`}
                      price={level.price}
                      quantity={level.quantity}
                      maxQty={maxQty}
                      side="sell"
                    />
                  ))
                ) : (
                  <div className="py-2 text-center text-xs text-muted-foreground">-</div>
                )}
              </div>
            </div>

            {/* Total row */}
            <div className="grid grid-cols-2 bg-muted/30 border-t divide-x">
              <div className="px-2 py-1.5 text-xs text-muted-foreground flex justify-between">
                <span>Total</span>
                <span className="font-mono text-emerald-400">
                  {buyLevels.reduce((sum, l) => sum + l.quantity, 0).toLocaleString()}
                </span>
              </div>
              <div className="px-2 py-1.5 text-xs text-muted-foreground flex justify-between">
                <span className="font-mono text-rose-400">
                  {sellLevels.reduce((sum, l) => sum + l.quantity, 0).toLocaleString()}
                </span>
                <span>Total</span>
              </div>
            </div>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
