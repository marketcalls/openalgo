import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowUpCircle, ArrowDownCircle, MinusCircle, AlertTriangle } from 'lucide-react'
import type { TradingDecision } from '@/types/ai-analysis'

interface DecisionCardProps {
  decision: TradingDecision
  symbol: string
  exchange: string
  onPlaceOrder?: () => void
}

const ACTION_CONFIG: Record<string, { color: string; bg: string; icon: typeof ArrowUpCircle }> = {
  'BUY NOW': { color: 'text-green-700', bg: 'bg-green-50 border-green-200', icon: ArrowUpCircle },
  'SELL NOW': { color: 'text-red-700', bg: 'bg-red-50 border-red-200', icon: ArrowDownCircle },
  'WAIT': { color: 'text-yellow-700', bg: 'bg-yellow-50 border-yellow-200', icon: MinusCircle },
  'AVOID': { color: 'text-gray-700', bg: 'bg-gray-50 border-gray-200', icon: AlertTriangle },
}

function formatINR(value: number): string {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 }).format(value)
}

function pctChange(entry: number, price: number): string {
  if (!entry || entry === 0) return ''
  const pct = ((price - entry) / entry * 100).toFixed(1)
  return `(${Number(pct) >= 0 ? '+' : ''}${pct}%)`
}

export function DecisionCard({ decision, symbol: _symbol, exchange: _exchange, onPlaceOrder }: DecisionCardProps) {
  const config = ACTION_CONFIG[decision.action] ?? ACTION_CONFIG['WAIT']
  const Icon = config.icon

  return (
    <Card className={`border-2 ${config.bg}`}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">WHAT TO DO</CardTitle>
        <div className="flex items-center gap-2">
          <Icon className={`h-6 w-6 ${config.color}`} />
          <span className={`text-xl font-bold ${config.color}`}>{decision.action}</span>
          <Badge variant="outline" className="ml-auto">{decision.confidence_label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Entry / SL / Target */}
        {decision.entry > 0 && (
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <div className="text-muted-foreground text-xs">Entry</div>
              <div className="font-semibold text-blue-600">{formatINR(decision.entry)}</div>
            </div>
            <div>
              <div className="text-muted-foreground text-xs">Stop Loss</div>
              <div className="font-semibold text-red-600">
                {formatINR(decision.stop_loss)} <span className="text-xs">{pctChange(decision.entry, decision.stop_loss)}</span>
              </div>
            </div>
            <div>
              <div className="text-muted-foreground text-xs">Target</div>
              <div className="font-semibold text-green-600">
                {formatINR(decision.target)} <span className="text-xs">{pctChange(decision.entry, decision.target)}</span>
              </div>
            </div>
          </div>
        )}

        {/* Qty / Risk / R:R */}
        {decision.quantity > 0 && (
          <div className="flex items-center gap-4 text-sm">
            <span>Qty: <strong>{decision.quantity}</strong> shares</span>
            <span>Risk: <strong>{formatINR(decision.risk_amount)}</strong></span>
            <span>R:R = <strong>1:{decision.risk_reward.toFixed(1)}</strong></span>
          </div>
        )}

        {/* Supporting / Opposing Signals */}
        <div className="flex flex-wrap gap-1">
          {decision.supporting_signals.map((s) => (
            <Badge key={s} variant="outline" className="text-xs bg-green-50 text-green-700 border-green-200">
              ✓ {s}
            </Badge>
          ))}
          {decision.opposing_signals.map((s) => (
            <Badge key={s} variant="outline" className="text-xs bg-red-50 text-red-700 border-red-200">
              ✗ {s}
            </Badge>
          ))}
        </div>

        {/* Risk Warning */}
        <p className="text-xs text-muted-foreground">{decision.risk_warning}</p>

        {/* Reason */}
        <p className="text-xs italic">{decision.reason}</p>

        {/* Score + Place Order */}
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Score: {decision.score}/100</span>
          {decision.action !== 'WAIT' && decision.action !== 'AVOID' && onPlaceOrder && (
            <Button size="sm" onClick={onPlaceOrder}>
              Place Order
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
