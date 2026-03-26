// frontend/src/components/ai-analysis/TradeActionPanel.tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { PlaceOrderDialog } from '@/components/trading/PlaceOrderDialog'
import { showToast } from '@/utils/toast'
import type { SignalType } from '@/types/ai-analysis'
import { ShoppingCart, AlertCircle } from 'lucide-react'

interface TradeActionPanelProps {
  symbol: string
  exchange: string
  signal: SignalType
  confidence: number
}

export function TradeActionPanel({ symbol, exchange, signal, confidence }: TradeActionPanelProps) {
  const [orderDialogOpen, setOrderDialogOpen] = useState(false)

  const suggestedAction = signal === 'STRONG_BUY' || signal === 'BUY' ? 'BUY' as const
    : signal === 'STRONG_SELL' || signal === 'SELL' ? 'SELL' as const
    : undefined

  const isHold = signal === 'HOLD'
  const isStrong = signal === 'STRONG_BUY' || signal === 'STRONG_SELL'

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button
          className="flex-1 bg-green-600 hover:bg-green-700 text-white"
          onClick={() => { setOrderDialogOpen(true) }}
          disabled={isHold}
        >
          <ShoppingCart className="h-4 w-4 mr-1" />
          {suggestedAction === 'BUY' ? (isStrong ? 'Strong Buy' : 'Buy') : 'Buy'}
        </Button>
        <Button
          className="flex-1 bg-red-600 hover:bg-red-700 text-white"
          onClick={() => { setOrderDialogOpen(true) }}
          disabled={isHold}
        >
          {suggestedAction === 'SELL' ? (isStrong ? 'Strong Sell' : 'Sell') : 'Sell'}
        </Button>
      </div>

      {isHold && (
        <div className="flex items-center gap-2 text-xs text-yellow-600 bg-yellow-50 p-2 rounded">
          <AlertCircle className="h-3 w-3" />
          Signal is HOLD — no trade recommended (confidence: {confidence.toFixed(1)}%)
        </div>
      )}

      {confidence < 50 && !isHold && (
        <p className="text-xs text-muted-foreground">
          Low confidence ({confidence.toFixed(1)}%) — consider smaller position size
        </p>
      )}

      <PlaceOrderDialog
        open={orderDialogOpen}
        onOpenChange={setOrderDialogOpen}
        symbol={symbol}
        exchange={exchange}
        action={suggestedAction}
        strategy="AIAnalyzer"
        onSuccess={(orderId) => {
          showToast.success(`Order placed: ${orderId}`)
          setOrderDialogOpen(false)
        }}
        onError={(err) => showToast.error(err)}
      />
    </div>
  )
}
