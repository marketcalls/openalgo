import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface StrategyListCardProps {
  strategy: DashboardStrategy
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

/** Status bar color at top of card */
function getStatusBarColor(strategy: DashboardStrategy): string {
  if (strategy.risk_monitoring === 'active') return 'bg-green-500'
  if (strategy.risk_monitoring === 'paused') return 'bg-amber-500'
  return 'bg-gray-300 dark:bg-gray-700'
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
      className="relative overflow-hidden flex flex-col cursor-pointer hover:bg-muted/50 transition-colors"
      onClick={() => navigate(`/strategy/${strategy.id}`)}
    >
      {/* Status bar at top — matches Python card pattern */}
      <div className={`absolute top-0 left-0 right-0 h-1 ${getStatusBarColor(strategy)}`} />

      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="space-y-1 min-w-0">
            <CardTitle className="text-lg truncate">{strategy.name}</CardTitle>
            <CardDescription className="text-xs">
              {strategy.platform} · {strategy.trading_mode} · {strategy.is_intraday ? 'Intraday' : 'Positional'}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {!strategy.is_active && (
              <Badge variant="secondary" className="text-xs">
                Inactive
              </Badge>
            )}
            <Badge
              variant={strategy.risk_monitoring === 'active' ? 'default' : 'secondary'}
              className={
                strategy.risk_monitoring === 'active'
                  ? 'bg-green-500 text-white'
                  : strategy.risk_monitoring === 'paused'
                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                    : ''
              }
            >
              {strategy.risk_monitoring === 'active'
                ? 'Active'
                : strategy.risk_monitoring === 'paused'
                  ? 'Paused'
                  : 'Off'}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 flex-1 flex flex-col">
        {/* Live P&L display — prominent like Python schedule section */}
        <div
          className={`text-sm p-3 rounded min-h-[52px] ${
            strategy.total_pnl >= 0
              ? 'bg-green-500/10 border border-green-500/20'
              : 'bg-red-500/10 border border-red-500/20'
          }`}
        >
          <p
            className={`text-xl font-bold font-mono tabular-nums ${
              strategy.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
            }`}
          >
            {strategy.total_pnl >= 0 ? '+' : ''}
            {currencyFormat.format(strategy.total_pnl)}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {strategy.win_rate !== null && `WR: ${strategy.win_rate.toFixed(1)}%`}
            {strategy.profit_factor !== null && strategy.win_rate !== null && ' · '}
            {strategy.profit_factor !== null && `PF: ${strategy.profit_factor.toFixed(2)}`}
            {strategy.win_rate === null && strategy.profit_factor === null && 'Daily P&L'}
          </p>
        </div>

        {/* Stats grid — like Python timestamps section */}
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground mt-auto">
          <div>
            <span className="block">Positions</span>
            <span className="font-medium text-foreground">{activePositions.length} open</span>
          </div>
          <div>
            <span className="block">Trades Today</span>
            <span className="font-medium text-foreground">{strategy.trade_count_today}</span>
          </div>
        </div>

        {/* Webhook URL */}
        {webhookUrl && (
          <div className="flex items-center gap-1.5 pt-2 mt-auto">
            <span className="font-mono text-xs text-muted-foreground truncate">
              {webhookUrl}
            </span>
            <button
              type="button"
              onClick={handleCopyWebhook}
              className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-muted flex-shrink-0"
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
      </CardContent>
    </Card>
  )
}
