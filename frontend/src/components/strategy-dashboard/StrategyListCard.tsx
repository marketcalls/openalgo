import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface StrategyListCardProps {
  strategy: DashboardStrategy
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

function getTopBarColor(strategy: DashboardStrategy): string {
  if (strategy.risk_monitoring === 'active') return 'border-t-green-500'
  if (strategy.risk_monitoring === 'paused') return 'border-t-amber-500'
  return 'border-t-gray-300 dark:border-t-gray-700'
}

export function StrategyListCard({ strategy }: StrategyListCardProps) {
  const navigate = useNavigate()
  const [webhookCopied, setWebhookCopied] = useState(false)

  const activePositions = strategy.positions.filter(
    (p) => p.position_state === 'active' || p.position_state === 'exiting'
  )

  const webhookUrl = strategy.webhook_id
    ? `${window.location.origin}/strategy/webhook/${strategy.webhook_id}`
    : ''

  const handleCopyWebhook = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!webhookUrl) return
    navigator.clipboard
      .writeText(webhookUrl)
      .then(() => {
        setWebhookCopied(true)
        showToast.success('Webhook URL copied', 'clipboard')
        setTimeout(() => setWebhookCopied(false), 2000)
      })
      .catch(() => {
        showToast.error('Failed to copy', 'clipboard')
      })
  }

  return (
    <Card
      className={`border-t-2 ${getTopBarColor(strategy)} cursor-pointer hover:bg-muted/50 transition-colors`}
      onClick={() => navigate(`/strategy/${strategy.id}`)}
    >
      <div className="flex items-center justify-between p-4">
        <div className="flex items-center gap-3 min-w-0">
          {/* Status dot */}
          <div className="relative flex-shrink-0">
            <div
              className={`h-2.5 w-2.5 rounded-full ${
                strategy.risk_monitoring === 'active'
                  ? 'bg-green-500'
                  : strategy.risk_monitoring === 'paused'
                    ? 'bg-amber-500'
                    : 'bg-gray-400'
              }`}
            />
            {strategy.risk_monitoring === 'active' && (
              <div className="absolute inset-0 h-2.5 w-2.5 rounded-full bg-green-500 animate-ping opacity-75" />
            )}
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-lg truncate">{strategy.name}</h3>
              {!strategy.is_active && (
                <Badge variant="secondary" className="text-xs">
                  Inactive
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>{strategy.platform}</span>
              <span>·</span>
              <span>{strategy.trading_mode}</span>
              <span>·</span>
              <span>{strategy.is_intraday ? 'Intraday' : 'Positional'}</span>
              <span>·</span>
              <span>{activePositions.length} positions</span>
              <span>·</span>
              <span>{strategy.trade_count_today} trades today</span>
            </div>
            {webhookUrl && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-0.5">
                <span className="font-mono truncate max-w-[300px]">{webhookUrl}</span>
                <button
                  type="button"
                  onClick={handleCopyWebhook}
                  className="inline-flex items-center justify-center h-5 w-5 rounded hover:bg-muted flex-shrink-0"
                  title="Copy webhook URL"
                >
                  {webhookCopied ? (
                    <Check className="h-3 w-3 text-green-500" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          {/* Live P&L */}
          <div className="text-right">
            <p
              className={`text-lg font-bold font-mono tabular-nums ${
                strategy.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {strategy.total_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(strategy.total_pnl)}
            </p>
            {strategy.win_rate !== null && (
              <p className="text-xs text-muted-foreground">
                WR: {strategy.win_rate.toFixed(1)}%
                {strategy.profit_factor !== null && ` · PF: ${strategy.profit_factor.toFixed(2)}`}
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
