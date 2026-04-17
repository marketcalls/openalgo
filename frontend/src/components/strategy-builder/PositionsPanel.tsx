import { Pencil, RotateCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'

export interface PositionsPanelProps {
  legs: StrategyLeg[]
  onToggleLeg: (id: string) => void
  onToggleSide: (id: string) => void
  onEditLeg: (id: string) => void
  onRemoveLeg: (id: string) => void
  onToggleAll: (active: boolean) => void
  onReset: () => void

  probOfProfit: number
  maxProfit: number
  maxLoss: number
  breakevens: number[]
  totalPnl: number
  netCredit: number
  estPremium: number
  /** Broker-computed margin requirement. undefined while loading / unavailable. */
  marginRequired?: number | null
  isMarginLoading?: boolean
  /**
   * Whether the broker supports the /margin endpoint. `false` hides the row
   * entirely so we don't show a dash for a feature the broker can't provide.
   */
  marginSupported?: boolean | null
}

function formatCurrency(v: number): string {
  if (!isFinite(v)) return '-'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : v > 0 ? '+' : ''
  return `${sign}₹${abs.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function formatPct(v: number): string {
  if (!isFinite(v)) return '-'
  return `${v.toFixed(2)}%`
}

export function PositionsPanel({
  legs,
  onToggleLeg,
  onToggleSide,
  onEditLeg,
  onRemoveLeg,
  onToggleAll,
  onReset,
  probOfProfit,
  maxProfit,
  maxLoss,
  breakevens,
  totalPnl,
  netCredit,
  estPremium,
  marginRequired,
  isMarginLoading,
  marginSupported,
}: PositionsPanelProps) {
  const allSelected = legs.length > 0 && legs.every((l) => l.active)
  const activeCount = legs.filter((l) => l.active).length

  const metrics: Array<{ label: string; value: string; tone?: 'profit' | 'loss' | 'neutral' }> = [
    {
      label: 'Prob. of Profit',
      value: probOfProfit > 0 ? formatPct(probOfProfit * 100) : '-',
      tone: 'neutral',
    },
    {
      label: 'Max. Profit',
      value: formatCurrency(maxProfit),
      tone: 'profit',
    },
    {
      label: 'Max. Loss',
      value: formatCurrency(maxLoss),
      tone: 'loss',
    },
    {
      label: 'Risk:Reward',
      value:
        maxProfit > 0 && maxLoss < 0
          ? `1 : ${(Math.abs(maxProfit) / Math.abs(maxLoss)).toFixed(2)}`
          : '-',
    },
    {
      label: 'Breakevens',
      value: breakevens.length === 0 ? '-' : breakevens.map((b) => b.toFixed(0)).join(', '),
    },
    {
      label: 'Total P&L',
      value: formatCurrency(totalPnl),
      tone: totalPnl > 0 ? 'profit' : totalPnl < 0 ? 'loss' : 'neutral',
    },
    {
      label: 'Net Credit',
      value: formatCurrency(netCredit),
      tone: netCredit > 0 ? 'profit' : netCredit < 0 ? 'loss' : 'neutral',
    },
    {
      label: 'Est. Premium',
      value: `₹${Math.abs(estPremium).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`,
    },
  ]

  // Only show the Margin metric when the broker supports /margin.
  // Probing state (null) suppresses the row until we know — otherwise a
  // dash flashes briefly for unsupported brokers.
  if (marginSupported === true) {
    metrics.push({
      label: 'Margin Required',
      value: isMarginLoading
        ? 'Calculating…'
        : marginRequired !== null && marginRequired !== undefined
          ? `₹${marginRequired.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
          : '—',
    })
  }

  return (
    <div className="flex h-full flex-col rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-sm font-semibold">Strategy Positions</h3>
        <Button variant="outline" size="sm" onClick={onReset} className="h-7 text-xs">
          <RotateCw className="mr-1.5 h-3 w-3" />
          Reset
        </Button>
      </div>

      <div className="flex items-center gap-3 border-b px-4 py-2">
        <Checkbox
          checked={allSelected}
          onCheckedChange={(v) => onToggleAll(Boolean(v))}
          disabled={legs.length === 0}
        />
        <label className="text-xs font-medium text-muted-foreground">
          Select All {legs.length > 0 ? `(${activeCount}/${legs.length})` : ''}
        </label>
      </div>

      <div className="max-h-[260px] flex-1 overflow-y-auto">
        {legs.length === 0 ? (
          <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
            No legs yet. Pick a template or add a leg manually.
          </div>
        ) : (
          <ul className="divide-y">
            {legs.map((leg) => {
              const isClosed = leg.exitPrice !== undefined && leg.exitPrice > 0
              const sign = leg.side === 'BUY' ? 1 : -1
              const qty = leg.lots * leg.lotSize
              const realisedPnl = isClosed
                ? sign * ((leg.exitPrice ?? 0) - leg.price) * qty
                : 0
              const descriptor =
                leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType
                  ? `${leg.strike}${leg.optionType}`
                  : 'FUT'
              return (
                <li
                  key={leg.id}
                  className={cn(
                    'flex items-center gap-2 px-4 py-2.5 text-xs',
                    isClosed && 'bg-rose-500/5'
                  )}
                >
                  <Checkbox
                    checked={leg.active}
                    onCheckedChange={() => onToggleLeg(leg.id)}
                    disabled={isClosed}
                  />
                  <button
                    type="button"
                    onClick={() => !isClosed && onToggleSide(leg.id)}
                    disabled={isClosed}
                    title={isClosed ? 'Closed position' : `Click to flip to ${leg.side === 'BUY' ? 'SELL' : 'BUY'}`}
                    className={cn(
                      'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold transition',
                      isClosed
                        ? 'cursor-not-allowed bg-rose-500/20 text-rose-700 dark:text-rose-400'
                        : leg.side === 'BUY'
                          ? 'cursor-pointer bg-emerald-500/15 text-emerald-700 hover:bg-emerald-500/25 dark:text-emerald-400'
                          : 'cursor-pointer bg-rose-500/15 text-rose-700 hover:bg-rose-500/25 dark:text-rose-400'
                    )}
                  >
                    {leg.side === 'BUY' ? 'B' : 'S'}
                  </button>

                  {/* Compact, single-line descriptor so narrow columns don't wrap. */}
                  <span
                    className={cn(
                      'min-w-0 flex-1 truncate whitespace-nowrap font-medium',
                      isClosed && 'text-rose-700/80 line-through dark:text-rose-400/80'
                    )}
                    title={`${leg.lots}× ${leg.expiry} ${descriptor}`}
                  >
                    <span className="tabular-nums">{leg.lots}×</span>{' '}
                    <span>{leg.expiry}</span>{' '}
                    <span className="font-semibold">{descriptor}</span>
                  </span>

                  {/* Price block: realised P&L for closed; entry price otherwise. */}
                  {isClosed ? (
                    <span
                      className={cn(
                        'shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular-nums',
                        realisedPnl >= 0
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                          : 'bg-rose-500/10 text-rose-700 dark:text-rose-400'
                      )}
                      title={`Entry ₹${leg.price.toFixed(2)} → Exit ₹${(leg.exitPrice ?? 0).toFixed(2)}`}
                    >
                      {realisedPnl >= 0 ? '+' : '-'}₹
                      {Math.abs(realisedPnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                  ) : (
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      ₹{leg.price.toFixed(2)}
                    </span>
                  )}

                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    onClick={() => onEditLeg(leg.id)}
                    aria-label="Edit position"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    onClick={() => onRemoveLeg(leg.id)}
                    aria-label="Remove position"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="border-t">
        <dl className="grid grid-cols-1 divide-y text-xs">
          {metrics.map((m) => (
            <div key={m.label} className="flex items-center justify-between px-4 py-2">
              <dt className="font-medium text-muted-foreground">{m.label}</dt>
              <dd
                className={cn(
                  'font-semibold tabular-nums',
                  m.tone === 'profit' && 'text-emerald-600 dark:text-emerald-400',
                  m.tone === 'loss' && 'text-rose-600 dark:text-rose-400'
                )}
              >
                {m.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
