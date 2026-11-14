import { Check, ChevronDown, ChevronsUpDown, RefreshCw, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

export interface SymbolHeaderProps {
  exchanges: Array<{ value: string; label: string }>
  selectedExchange: string
  onExchangeChange: (v: string) => void

  underlyings: string[]
  selectedUnderlying: string
  onUnderlyingChange: (u: string) => void
  underlyingOpen: boolean
  onUnderlyingOpenChange: (open: boolean) => void

  expiries: string[]
  selectedExpiry: string
  onExpiryChange: (e: string) => void

  spotPrice: number | null
  futuresPrice: number | null
  lotSize: number | null
  atmIv: number | null
  daysToExpiry: number | null

  onRefresh: () => void
  isRefreshing: boolean
  connectionStatus: 'live' | 'refreshing' | 'stale' | 'idle'

  onToggleLibrary?: () => void
  isLibraryOpen?: boolean
  maxProfit?: number
  maxLoss?: number
  probOfProfit?: number | null
  riskReward?: string
  netCredit?: number
  totalPnl?: number
  marginRequired?: number | null
  isMarginLoading?: boolean
  marginSupported?: boolean | null
  breakevens?: number[]
  formatCurrency?: (value: number) => string
  legsCount?: number
  activeLegsCount?: number
  hideRefresh?: boolean
  hideMetrics?: boolean
}

interface MetricCellProps {
  label: string
  value: string
  sub?: string
  tone?: 'primary' | 'profit' | 'warn' | 'muted'
  accent?: boolean
}

function MetricCell({ label, value, sub, tone = 'muted', accent = false }: MetricCellProps) {
  return (
    <div
      className={cn(
        'relative flex flex-col justify-center gap-0.5 px-3.5 py-1.5 sm:py-2 transition',
        accent && 'bg-gradient-to-b from-background to-muted/20'
      )}
    >
      <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          'font-semibold tabular-nums leading-none',
          accent ? 'text-lg sm:text-xl tracking-tight' : 'text-sm sm:text-base',
          tone === 'primary' && 'text-foreground',
          tone === 'profit' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'warn' && 'text-amber-600 dark:text-amber-400',
          tone === 'muted' && 'text-foreground'
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[9px] font-medium text-muted-foreground">{sub}</span>}
    </div>
  )
}

export function SymbolHeader({
  exchanges,
  selectedExchange,
  onExchangeChange,
  underlyings,
  selectedUnderlying,
  onUnderlyingChange,
  underlyingOpen,
  onUnderlyingOpenChange,
  expiries,
  selectedExpiry,
  onExpiryChange,
  spotPrice,
  futuresPrice,
  lotSize,
  atmIv,
  daysToExpiry,
  onRefresh,
  isRefreshing,
  connectionStatus,
  onToggleLibrary,
  isLibraryOpen,
  maxProfit,
  maxLoss,
  probOfProfit,
  riskReward,
  netCredit,
  totalPnl,
  marginRequired,
  isMarginLoading,
  marginSupported,
  breakevens,
  formatCurrency,
  legsCount,
  activeLegsCount,
  hideRefresh = false,
  hideMetrics = false,
}: SymbolHeaderProps) {
  const statusLabel =
    connectionStatus === 'live'
      ? 'Live'
      : connectionStatus === 'refreshing'
        ? 'Refreshing'
        : connectionStatus === 'stale'
          ? 'Stale'
          : 'Idle'
  const isLive = connectionStatus === 'live'

  return (
    <div
      data-testid="symbol-header"
      className="min-w-0 max-w-full rounded-xl border bg-card shadow-sm"
    >
      {/* Top bar — selectors + strategy templates toggle + payoff ribbon + optional live status */}
      <div
        className={cn(
          'flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-muted/40 via-background to-background px-4 py-2',
          !hideMetrics && 'border-b'
        )}
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Analyzing
          </span>

          <div
            data-testid="symbol-selectors"
            className="grid w-full min-w-0 basis-full grid-cols-1 items-stretch rounded-lg border bg-background divide-y sm:w-auto sm:basis-auto sm:grid-cols-[92px_168px_128px] sm:divide-x sm:divide-y-0"
          >
            {/* Exchange */}
            <Select value={selectedExchange} onValueChange={onExchangeChange}>
              <SelectTrigger
                aria-label="Derivative exchange"
                className="h-8 sm:h-9 w-full min-w-0 rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {exchanges.map((e) => (
                  <SelectItem key={e.value} value={e.value}>
                    {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Underlying */}
            <Popover open={underlyingOpen} onOpenChange={onUnderlyingOpenChange}>
              <PopoverTrigger asChild>
                <Button
                  variant="ghost"
                  role="combobox"
                  aria-label="Underlying"
                  aria-expanded={underlyingOpen}
                  className="h-8 sm:h-9 w-full min-w-0 justify-between rounded-none border-0 bg-transparent px-3 text-xs font-bold tracking-wide hover:bg-muted/40"
                >
                  {selectedUnderlying || 'Select'}
                  <ChevronsUpDown className="ml-2 h-3.5 w-3.5 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-56 p-0">
                <Command>
                  <CommandInput
                    aria-label="Search underlyings"
                    placeholder="Search symbol..."
                    className="h-9 text-xs"
                  />
                  <CommandList>
                    <CommandEmpty>No symbol found.</CommandEmpty>
                    <CommandGroup>
                      {underlyings.map((u) => (
                        <CommandItem
                          key={u}
                          value={u}
                          onSelect={() => {
                            onUnderlyingChange(u)
                            onUnderlyingOpenChange(false)
                          }}
                          className="text-xs font-medium"
                        >
                          <Check
                            className={cn(
                              'mr-2 h-3.5 w-3.5',
                              selectedUnderlying === u ? 'opacity-100' : 'opacity-0'
                            )}
                          />
                          {u}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>

            {/* Expiry */}
            <Select value={selectedExpiry} onValueChange={onExpiryChange}>
              <SelectTrigger
                aria-label="Option expiry"
                className="h-8 sm:h-9 w-full min-w-0 rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0"
              >
                <SelectValue placeholder="Expiry" />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Strategy Templates Button */}
          {onToggleLibrary && (
            <Button
              variant="outline"
              size="sm"
              onClick={onToggleLibrary}
              className={cn(
                'h-8 sm:h-9 gap-1.5 px-3 text-xs font-semibold transition shadow-xs',
                isLibraryOpen
                  ? 'border-violet-500/50 bg-violet-500/15 text-violet-700 dark:text-violet-300 hover:bg-violet-500/20'
                  : 'border-border/80 bg-background text-foreground hover:bg-muted/60'
              )}
              title="Browse strategy templates"
            >
              <Sparkles className="h-3.5 w-3.5 text-violet-500" />
              Strategy Templates
              <ChevronDown
                className={cn(
                  'h-3.5 w-3.5 transition-transform duration-200',
                  isLibraryOpen && 'rotate-180'
                )}
              />
            </Button>
          )}

          {legsCount !== undefined && legsCount > 0 && (
            <span className="hidden items-center gap-1 rounded-full border border-border/50 bg-background/80 px-2 py-0.5 text-[10px] font-medium text-muted-foreground sm:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {activeLegsCount ?? legsCount}/{legsCount} active
            </span>
          )}
        </div>

        {/* Center: Payoff Metrics Ribbon */}
        {formatCurrency && (
          <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs">
            {/* Max Profit */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Max Profit
              </span>
              <span
                className={cn(
                  'font-bold tabular-nums',
                  (maxProfit ?? 0) > 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-foreground'
                )}
              >
                {Number.isFinite(maxProfit ?? 0)
                  ? formatCurrency(maxProfit ?? 0)
                  : Math.abs(maxProfit ?? 0) === Infinity
                    ? 'Unlimited'
                    : '—'}
              </span>
            </div>

            <span className="hidden text-border/60 sm:inline">|</span>

            {/* Max Loss */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Max Loss
              </span>
              <span
                className={cn(
                  'font-bold tabular-nums',
                  (maxLoss ?? 0) < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-foreground'
                )}
              >
                {Number.isFinite(maxLoss ?? 0)
                  ? formatCurrency(maxLoss ?? 0)
                  : Math.abs(maxLoss ?? 0) === Infinity
                    ? 'Unlimited'
                    : '—'}
              </span>
            </div>

            <span className="hidden text-border/60 sm:inline">|</span>

            {/* POP */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                POP
              </span>
              <span className="font-bold tabular-nums text-foreground">
                {probOfProfit !== null &&
                probOfProfit !== undefined &&
                Number.isFinite(probOfProfit)
                  ? `${probOfProfit.toFixed(1)}%`
                  : '—'}
              </span>
            </div>

            <span className="hidden text-border/60 sm:inline">|</span>

            {/* Risk:Reward */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                R : R
              </span>
              <span className="font-bold tabular-nums text-foreground">{riskReward || '—'}</span>
            </div>

            <span className="hidden text-border/60 sm:inline">|</span>

            {/* Net Premium */}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Net Prem.
              </span>
              <span
                className={cn(
                  'font-bold tabular-nums',
                  (netCredit ?? 0) > 0 && 'text-emerald-600 dark:text-emerald-400',
                  (netCredit ?? 0) < 0 && 'text-rose-600 dark:text-rose-400',
                  (netCredit ?? 0) === 0 && 'text-foreground'
                )}
              >
                {formatCurrency(Math.abs(netCredit ?? 0))}
                <span className="ml-1 text-[9px] uppercase text-muted-foreground">
                  {(netCredit ?? 0) > 0 ? 'Cr' : (netCredit ?? 0) < 0 ? 'Db' : ''}
                </span>
              </span>
            </div>

            {/* Net P&L */}
            {legsCount !== undefined && legsCount > 0 && totalPnl !== undefined && (
              <>
                <span className="hidden text-border/60 sm:inline">|</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Net P&amp;L
                  </span>
                  <span
                    className={cn(
                      'font-bold tabular-nums',
                      totalPnl > 0 && 'text-emerald-600 dark:text-emerald-400',
                      totalPnl < 0 && 'text-rose-600 dark:text-rose-400',
                      totalPnl === 0 && 'text-foreground'
                    )}
                  >
                    {formatCurrency(totalPnl)}
                  </span>
                </div>
              </>
            )}

            {/* Margin Required */}
            {marginSupported === true && (
              <>
                <span className="hidden text-border/60 sm:inline">|</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Margin
                  </span>
                  <span className="font-bold tabular-nums text-foreground">
                    {isMarginLoading
                      ? 'Calculating…'
                      : marginRequired !== null && marginRequired !== undefined
                        ? formatCurrency(marginRequired)
                        : '—'}
                  </span>
                </div>
              </>
            )}

            {/* Breakevens */}
            {breakevens && breakevens.length > 0 && (
              <>
                <span className="hidden text-border/60 sm:inline">|</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    B/E
                  </span>
                  <span className="font-bold tabular-nums text-foreground">
                    {breakevens.map((b) => formatCurrency(b)).join(', ')}
                  </span>
                </div>
              </>
            )}
          </div>
        )}

        {/* Right: Live Status & Refresh (rendered here if not placed in outer page header) */}
        {!hideRefresh && (
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden items-center gap-1.5 sm:flex">
              <span className="relative flex h-2 w-2">
                <span
                  className={cn(
                    'absolute inline-flex h-full w-full rounded-full opacity-75',
                    isLive ? 'animate-ping bg-emerald-400' : 'bg-muted-foreground/40'
                  )}
                />
                <span
                  className={cn(
                    'relative inline-flex h-2 w-2 rounded-full',
                    isLive ? 'bg-emerald-500' : 'bg-muted-foreground/60'
                  )}
                />
              </span>
              <span
                aria-live="polite"
                className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground"
              >
                {statusLabel}
              </span>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="h-8 gap-1.5 text-xs"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
              Refresh
            </Button>
          </div>
        )}
      </div>

      {/* Metrics grid — hairline divisions, big primary numbers */}
      {!hideMetrics && (
        <div
          data-testid="symbol-metrics"
          className="grid grid-cols-2 divide-x divide-y overflow-hidden rounded-b-xl sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5"
        >
          <MetricCell
            label="Spot"
            value={spotPrice !== null ? spotPrice.toFixed(2) : '—'}
            tone="primary"
            accent
          />
          <MetricCell
            label="Futures"
            value={futuresPrice !== null ? futuresPrice.toFixed(2) : '—'}
            sub={
              spotPrice !== null && futuresPrice !== null
                ? `${futuresPrice > spotPrice ? '+' : ''}${(futuresPrice - spotPrice).toFixed(2)}`
                : undefined
            }
            tone="profit"
            accent
          />
          <MetricCell
            label="ATM IV"
            value={atmIv !== null ? `${atmIv.toFixed(2)}%` : '—'}
            tone="warn"
          />
          <MetricCell
            label="DTE"
            value={daysToExpiry !== null ? `${daysToExpiry.toFixed(0)}` : '—'}
            sub={daysToExpiry !== null ? 'days to expiry' : undefined}
          />
          <MetricCell label="Lot Size" value={lotSize !== null ? String(lotSize) : '—'} />
        </div>
      )}
    </div>
  )
}
