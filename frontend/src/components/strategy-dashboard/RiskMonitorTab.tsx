import type { DashboardPosition } from '@/types/strategy-dashboard'
import { RiskProgressBar } from './RiskProgressBar'
import { RiskEventsLog } from './RiskEventsLog'

interface RiskMonitorTabProps {
  strategyId: number
  strategyType: string
  positions: DashboardPosition[]
}

export function RiskMonitorTab({ strategyId, strategyType, positions }: RiskMonitorTabProps) {
  const activePositions = positions.filter((p) => p.position_state === 'active' && p.ltp)

  return (
    <div className="space-y-6">
      {/* Risk distance bars for active positions */}
      {activePositions.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-sm font-medium">Active Position Risk Distances</h4>
          {activePositions.map((pos) => (
            <div key={pos.id} className="p-3 border rounded-lg space-y-3">
              <div className="text-xs font-medium">
                {pos.symbol}{' '}
                <span className={pos.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                  {pos.action}
                </span>{' '}
                @ {pos.average_entry_price.toFixed(2)} | LTP: {pos.ltp?.toFixed(2)}
              </div>
              {pos.stoploss_price && pos.ltp && (
                <RiskProgressBar
                  label="Stop Loss"
                  currentPrice={pos.ltp}
                  entryPrice={pos.average_entry_price}
                  triggerPrice={pos.stoploss_price}
                  action={pos.action}
                  type="sl"
                />
              )}
              {pos.target_price && pos.ltp && (
                <RiskProgressBar
                  label="Target"
                  currentPrice={pos.ltp}
                  entryPrice={pos.average_entry_price}
                  triggerPrice={pos.target_price}
                  action={pos.action}
                  type="tgt"
                />
              )}
              {pos.trailstop_price && pos.ltp && (
                <RiskProgressBar
                  label="Trailing Stop"
                  currentPrice={pos.ltp}
                  entryPrice={pos.average_entry_price}
                  triggerPrice={pos.trailstop_price}
                  action={pos.action}
                  type="tsl"
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Risk events log */}
      <div>
        <h4 className="text-sm font-medium mb-2">Risk Events</h4>
        <RiskEventsLog strategyId={strategyId} strategyType={strategyType} />
      </div>
    </div>
  )
}
