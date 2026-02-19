import { CopyIcon, LinkIcon, SettingsIcon, CopyPlusIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { dashboardApi } from '@/api/strategy-dashboard'
import { showToast } from '@/utils/toast'
import type { Strategy, StrategySymbolMapping } from '@/types/strategy'
import type { RiskConfig } from '@/types/strategy-dashboard'

interface OverviewTabProps {
  strategy: Strategy
  mappings: StrategySymbolMapping[]
  strategyType: string
  riskConfig: RiskConfig | null
  onOpenRiskConfig: () => void
}

export function OverviewTab({
  strategy,
  mappings,
  strategyType,
  riskConfig,
  onOpenRiskConfig,
}: OverviewTabProps) {
  const webhookUrl = `${window.location.origin}/strategy/webhook/${strategy.webhook_id}`

  const copyWebhook = () => {
    navigator.clipboard.writeText(webhookUrl)
    showToast.success('Webhook URL copied')
  }

  const handleClone = async () => {
    try {
      const result = await dashboardApi.cloneStrategy(strategy.id, strategyType)
      showToast.success(`Strategy cloned (ID: ${result.strategy_id})`)
    } catch {
      showToast.error('Failed to clone strategy')
    }
  }

  return (
    <div className="space-y-4">
      {/* Strategy Details */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Platform</p>
            <p className="text-sm font-medium capitalize">{strategy.platform}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Mode</p>
            <p className="text-sm font-medium">{strategy.trading_mode}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Type</p>
            <p className="text-sm font-medium">{strategy.is_intraday ? 'Intraday' : 'Positional'}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground">Status</p>
            <Badge variant={strategy.is_active ? 'default' : 'secondary'}>
              {strategy.is_active ? 'Active' : 'Inactive'}
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Webhook URL */}
      <Card>
        <CardContent className="p-3">
          <div className="flex items-center gap-2">
            <LinkIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Webhook URL</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <code className="text-xs bg-muted px-2 py-1 rounded flex-1 truncate">{webhookUrl}</code>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={copyWebhook}>
              <CopyIcon className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Symbol Mappings */}
      {mappings.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <p className="text-xs text-muted-foreground mb-2">
              Symbol Mappings ({mappings.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {mappings.map((m) => (
                <Badge key={m.id} variant="outline" className="text-xs">
                  {m.symbol} ({m.exchange}) x{m.quantity} {m.product_type}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Risk Config Summary */}
      {riskConfig && (
        <Card>
          <CardContent className="p-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-muted-foreground">Risk Configuration</p>
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={onOpenRiskConfig}>
                <SettingsIcon className="h-3 w-3 mr-1" />
                Edit
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">SL: </span>
                {riskConfig.default_stoploss_type
                  ? `${riskConfig.default_stoploss_value} ${riskConfig.default_stoploss_type}`
                  : 'Disabled'}
              </div>
              <div>
                <span className="text-muted-foreground">TGT: </span>
                {riskConfig.default_target_type
                  ? `${riskConfig.default_target_value} ${riskConfig.default_target_type}`
                  : 'Disabled'}
              </div>
              <div>
                <span className="text-muted-foreground">TSL: </span>
                {riskConfig.default_trailstop_type
                  ? `${riskConfig.default_trailstop_value} ${riskConfig.default_trailstop_type}`
                  : 'Disabled'}
              </div>
              <div>
                <span className="text-muted-foreground">BE: </span>
                {riskConfig.default_breakeven_type
                  ? `${riskConfig.default_breakeven_threshold} ${riskConfig.default_breakeven_type}`
                  : 'Disabled'}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={handleClone}>
          <CopyPlusIcon className="h-3.5 w-3.5 mr-1" />
          Clone Strategy
        </Button>
      </div>
    </div>
  )
}
