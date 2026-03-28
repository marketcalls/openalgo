import { Badge } from '@/components/ui/badge'
import { Target, ShieldAlert, TrendingUp, TrendingDown, DollarSign } from 'lucide-react'

interface TradeSetup {
  action: string
  entry: number
  stop_loss: number
  target_1: number
  target_2: number
  target_3: number
  sl_distance: number
  sl_percent: number
  risk_reward_1: number
  risk_reward_2: number
  risk_reward_3: number
  suggested_qty: number
  risk_amount: number
  reason: string
}

interface TradeSetupCardProps {
  setup: TradeSetup | null | undefined
}

export function TradeSetupCard({ setup }: TradeSetupCardProps) {
  if (!setup || setup.action === 'NO_TRADE') {
    return (
      <div className="text-center py-4 text-sm text-muted-foreground">
        No trade setup — signal is HOLD
      </div>
    )
  }

  const isBuy = setup.action === 'BUY'
  const actionColor = isBuy ? 'text-green-600' : 'text-red-600'
  const actionBg = isBuy ? 'bg-green-50' : 'bg-red-50'

  return (
    <div className="space-y-3">
      {/* Action + Entry */}
      <div className={`flex items-center justify-between p-2 rounded ${actionBg}`}>
        <div className="flex items-center gap-2">
          {isBuy ? <TrendingUp className="h-4 w-4 text-green-600" /> : <TrendingDown className="h-4 w-4 text-red-600" />}
          <span className={`font-bold ${actionColor}`}>{setup.action}</span>
        </div>
        <span className="font-mono font-bold text-lg">{setup.entry.toFixed(2)}</span>
      </div>

      {/* SL + Targets table */}
      <div className="space-y-1.5 text-sm">
        <div className="flex justify-between items-center px-2 py-1 bg-red-50 rounded">
          <span className="flex items-center gap-1 text-red-600">
            <ShieldAlert className="h-3 w-3" /> Stop Loss
          </span>
          <span className="font-mono font-medium text-red-700">{setup.stop_loss.toFixed(2)}</span>
          <span className="text-xs text-red-500">-{setup.sl_percent.toFixed(1)}%</span>
        </div>

        <div className="flex justify-between items-center px-2 py-1 bg-green-50 rounded">
          <span className="flex items-center gap-1 text-green-600">
            <Target className="h-3 w-3" /> Target 1
          </span>
          <span className="font-mono font-medium text-green-700">{setup.target_1.toFixed(2)}</span>
          <Badge variant="outline" className="text-xs">{setup.risk_reward_1.toFixed(1)}:1</Badge>
        </div>

        <div className="flex justify-between items-center px-2 py-1 bg-green-50/70 rounded">
          <span className="flex items-center gap-1 text-green-600">
            <Target className="h-3 w-3" /> Target 2
          </span>
          <span className="font-mono font-medium text-green-700">{setup.target_2.toFixed(2)}</span>
          <Badge variant="outline" className="text-xs">{setup.risk_reward_2.toFixed(1)}:1</Badge>
        </div>

        <div className="flex justify-between items-center px-2 py-1 bg-green-50/50 rounded">
          <span className="flex items-center gap-1 text-green-600">
            <Target className="h-3 w-3" /> Target 3
          </span>
          <span className="font-mono font-medium text-green-700">{setup.target_3.toFixed(2)}</span>
          <Badge variant="outline" className="text-xs">{setup.risk_reward_3.toFixed(1)}:1</Badge>
        </div>
      </div>

      {/* Quantity + Risk */}
      <div className="flex justify-between items-center text-sm px-2 py-1.5 bg-muted rounded">
        <span className="flex items-center gap-1">
          <DollarSign className="h-3 w-3" /> Qty: <strong>{setup.suggested_qty}</strong>
        </span>
        <span className="text-xs text-muted-foreground">
          Risk: ₹{setup.risk_amount.toFixed(0)} | SL: {setup.sl_distance.toFixed(2)}
        </span>
      </div>

      {/* Reason */}
      <p className="text-xs text-muted-foreground px-1">{setup.reason}</p>
    </div>
  )
}
