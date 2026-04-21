import { Layers, Pencil, RotateCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { strikeMoneyness, type StrategyLeg } from '@/lib/strategyMath'
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
  /** ATM strike from the live chain — used to compute per-leg moneyness. */
  atmStrike?: number | null
  /** Common strike increment (e.g. 50 for NIFTY) — drives moneyness step count. */
  strikeStep?: number
}

function formatCurrency(v: number): string {
  // Unlimited-profit / unlimited-loss strategies report ±Infinity from
  // computePayoff. Surface that clearly instead of a generic dash.
  if (v === Infinity) return 'Unlimited'
  if (v === -Infinity) return 'Unlimited'
  if (!isFinite(v)) return '—'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : v > 0 ? '+' : ''
  return `${sign}₹${abs.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function formatPct(v: number): string {
  if (!isFinite(v)) return '—'
  return `${v.toFixed(2)}%`
}

interface MetricTileProps {
  label: string
  value: string
  tone?: 'profit' | 'loss' | 'neutral'
  span?: 1 | 2
  emphasize?: boolean
}

function MetricTile({ label, value, tone = 'neutral', span = 1, emphasize = false }: MetricTileProps) {
  return (
    <div
      className={cn(
        'flex flex-col justify-center gap-1 px-3.5 py-2.5',
        span === 2 && 'col-span-2',
        emphasize && 'bg-gradient-to-br from-muted/40 to-transparent'
      )}
    >
      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={cn(
          'font-semibold tabular-nums leading-tight',
          emphasize ? 'text-base' : 'text-sm',
          tone === 'profit' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'loss' && 'text-rose-600 dark:text-rose-400'
        )}
      >
        {value}
      </dd>
    </div>
  )
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
  atmStrike = null,
  strikeStep = 0,
}: PositionsPanelProps) {
  const allSelected = legs.length > 0 && legs.every((l) => l.active)
  const activeCount = legs.filter((l) => l.active).length

  // Risk / Reward — meaningful only when both ends are finite and on opposite
  // sides of zero. Unlimited strategies have no defined ratio.
  const riskReward =
    isFinite(maxProfit) && isFinite(maxLoss) && maxProfit > 0 && maxLoss < 0
      ? `1 : ${(Math.abs(maxProfit) / Math.abs(maxLoss)).toFixed(2)}`
      : 'NA'

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* Header — title + action cluster. flex-wrap lets the actions drop
          to a second row when the panel column is narrow (360px on lg),
          while staying inline on wider screens. */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-blue-500/15 to-violet-500/15 text-blue-600 dark:text-blue-400">
            <Layers className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold leading-none">Positions</h3>
            <p className="mt-1 truncate text-[10px] text-muted-foreground">
              {legs.length > 0
                ? `${activeCount}/${legs.length} active`
                : 'No legs added yet'}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          className="h-7 text-[11px] text-muted-foreground hover:text-foreground"
          disabled={legs.length === 0}
        >
          <RotateCw className="mr-1 h-3 w-3" />
          Reset
        </Button>
      </div>

      {/* Select-all row — checked legs are included in payoff/greeks/pnl,
          unchecked legs are excluded from all analysis outputs. Using the
          shadcn Checkbox (Radix-backed) so the indeterminate state and a11y
          are handled correctly. */}
      {legs.length > 0 && (
        <div className="flex items-center gap-2.5 border-b px-4 py-2">
          <Checkbox
            checked={allSelected ? true : activeCount > 0 ? 'indeterminate' : false}
            onCheckedChange={() => onToggleAll(!allSelected)}
            title={allSelected ? 'Exclude all legs' : 'Include all legs'}
            className={cn(
              'h-4 w-4 border-border',
              'data-[state=checked]:border-emerald-500 data-[state=checked]:bg-emerald-500 data-[state=checked]:text-white',
              'data-[state=indeterminate]:border-emerald-500 data-[state=indeterminate]:bg-emerald-500 data-[state=indeterminate]:text-white'
            )}
          />
          <label className="text-[11px] font-medium text-muted-foreground">Select all</label>
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
            {activeCount}/{legs.length}
          </span>
        </div>
      )}

      {/* Legs list */}
      <div className="max-h-[280px] flex-1 overflow-y-auto">
        {legs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 p-8 text-center">
            <p className="text-xs font-medium text-muted-foreground">No legs yet</p>
            <p className="text-[11px] text-muted-foreground/80">
              Pick a template or add manually
            </p>
          </div>
        ) : (
          <ul>
            {legs.map((leg, idx) => {
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
                    'group flex items-center gap-2 border-b border-border/60 px-3 py-2.5 transition last:border-b-0',
                    'hover:bg-muted/40',
                    isClosed && 'bg-rose-500/5',
                    !leg.active && !isClosed && 'bg-muted/30'
                  )}
                >
                  <span className="w-4 shrink-0 text-center text-[10px] font-semibold tabular-nums text-muted-foreground">
                    {idx + 1}
                  </span>
                  <Checkbox
                    checked={leg.active}
                    onCheckedChange={() => !isClosed && onToggleLeg(leg.id)}
                    disabled={isClosed}
                    title={
                      isClosed
                        ? 'Closed position'
                        : leg.active
                          ? 'Included in analysis — click to exclude'
                          : 'Excluded from analysis — click to include'
                    }
                    aria-label={leg.active ? 'Exclude leg' : 'Include leg'}
                    className={cn(
                      'h-4 w-4 border-border',
                      'data-[state=checked]:border-emerald-500 data-[state=checked]:bg-emerald-500 data-[state=checked]:text-white',
                      'hover:border-foreground/40 data-[state=checked]:hover:bg-emerald-600'
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => !isClosed && onToggleSide(leg.id)}
                    disabled={isClosed}
                    title={
                      isClosed
                        ? 'Closed position'
                        : `${leg.side === 'BUY' ? 'Buy' : 'Sell'} — click to flip to ${leg.side === 'BUY' ? 'Sell' : 'Buy'}`
                    }
                    aria-label={leg.side === 'BUY' ? 'Buy' : 'Sell'}
                    className={cn(
                      'inline-flex h-5 w-6 shrink-0 items-center justify-center rounded-md text-[10px] font-bold uppercase tracking-wider transition',
                      isClosed
                        ? 'cursor-not-allowed bg-rose-500/15 text-rose-700 dark:text-rose-400'
                        : leg.side === 'BUY'
                          ? 'cursor-pointer bg-emerald-500/15 text-emerald-700 ring-1 ring-inset ring-emerald-500/20 hover:bg-emerald-500/25 dark:text-emerald-400'
                          : 'cursor-pointer bg-rose-500/15 text-rose-700 ring-1 ring-inset ring-rose-500/20 hover:bg-rose-500/25 dark:text-rose-400'
                    )}
                  >
                    {leg.side === 'BUY' ? 'B' : 'S'}
                  </button>

                  <div
                    className={cn(
                      'min-w-0 flex-1',
                      isClosed && 'text-rose-700/80 line-through dark:text-rose-400/80',
                      !leg.active && !isClosed && 'text-muted-foreground line-through'
                    )}
                  >
                    <div className="flex items-center gap-1.5 truncate text-xs">
                      <span className="font-semibold tabular-nums">{leg.lots}×</span>
                      <span className="font-semibold">{descriptor}</span>
                      {(() => {
                        const m = strikeMoneyness(
                          leg.strike,
                          atmStrike,
                          strikeStep,
                          leg.optionType
                        )
                        if (!m) return null
                        return (
                          <span
                            className={cn(
                              'shrink-0 rounded px-1 py-px text-[9px] font-semibold uppercase tracking-wider',
                              m.kind === 'ATM' &&
                                'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                              m.kind === 'ITM' &&
                                'bg-sky-500/15 text-sky-700 dark:text-sky-400',
                              m.kind === 'OTM' && 'bg-muted text-muted-foreground'
                            )}
                            title={
                              m.kind === 'ATM'
                                ? 'At the Money'
                                : m.kind === 'ITM'
                                  ? `In the Money · ${Math.abs(m.steps)} ${Math.abs(m.steps) === 1 ? 'strike' : 'strikes'} from ATM`
                                  : `Out of the Money · ${Math.abs(m.steps)} ${Math.abs(m.steps) === 1 ? 'strike' : 'strikes'} from ATM`
                            }
                          >
                            {m.label}
                          </span>
                        )
                      })()}
                    </div>
                    <div className="truncate text-[10px] text-muted-foreground tabular-nums">
                      {leg.expiry}
                    </div>
                  </div>

                  {/* Price / realised P&L */}
                  {isClosed ? (
                    <span
                      className={cn(
                        'shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                        realisedPnl >= 0
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                          : 'bg-rose-500/10 text-rose-700 dark:text-rose-400'
                      )}
                      title={`Entry ₹${leg.price.toFixed(2)} → Exit ₹${(leg.exitPrice ?? 0).toFixed(2)}`}
                    >
                      {realisedPnl >= 0 ? '+' : '-'}₹
                      {Math.abs(realisedPnl).toLocaleString('en-IN', {
                        maximumFractionDigits: 0,
                      })}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                      ₹{leg.price.toFixed(2)}
                    </span>
                  )}

                  <div className="flex shrink-0 items-center opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => onEditLeg(leg.id)}
                      aria-label="Edit position"
                    >
                      <Pencil className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 hover:text-rose-600"
                      onClick={() => onRemoveLeg(leg.id)}
                      aria-label="Remove position"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {/* Metrics — 2-col grid with hairline dividers */}
      <div className="border-t">
        <dl className="grid grid-cols-2 divide-x divide-y">
          <MetricTile
            label="Max Profit"
            value={formatCurrency(maxProfit)}
            tone="profit"
            emphasize
          />
          <MetricTile
            label="Max Loss"
            value={formatCurrency(maxLoss)}
            tone="loss"
            emphasize
          />
          <MetricTile
            label="Prob. of Profit"
            value={probOfProfit > 0 ? formatPct(probOfProfit * 100) : '—'}
          />
          <MetricTile label="Risk : Reward" value={riskReward} />
          <MetricTile
            label="Total P&L"
            value={formatCurrency(totalPnl)}
            tone={totalPnl > 0 ? 'profit' : totalPnl < 0 ? 'loss' : 'neutral'}
          />
          <MetricTile
            label="Net Credit"
            value={formatCurrency(netCredit)}
            tone={netCredit > 0 ? 'profit' : netCredit < 0 ? 'loss' : 'neutral'}
          />
          <MetricTile
            label="Est. Premium"
            value={`₹${Math.abs(estPremium).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          />
          {marginSupported === true && (
            <MetricTile
              label="Margin Req."
              value={
                isMarginLoading
                  ? 'Calculating…'
                  : marginRequired !== null && marginRequired !== undefined
                    ? `₹${marginRequired.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                    : '—'
              }
            />
          )}
        </dl>

        {/* Breakevens — full width chip row */}
        {breakevens.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-t bg-muted/20 px-3.5 py-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Breakevens
            </span>
            {breakevens.map((b, i) => (
              <span
                key={i}
                className="rounded-md border bg-background px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-foreground"
              >
                {b.toFixed(0)}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
