import { Check, ChevronsUpDown, RefreshCw } from 'lucide-react'
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
        'relative flex flex-col justify-center gap-1 px-4 py-3 transition',
        accent && 'bg-gradient-to-b from-background to-muted/20'
      )}
    >
      <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          'font-semibold tabular-nums leading-none',
          accent ? 'text-2xl tracking-tight' : 'text-base',
          tone === 'primary' && 'text-foreground',
          tone === 'profit' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'warn' && 'text-amber-600 dark:text-amber-400',
          tone === 'muted' && 'text-foreground'
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[10px] font-medium text-muted-foreground">{sub}</span>}
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
}: SymbolHeaderProps) {
  const hasData = spotPrice !== null

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* Top bar — breadcrumb-style selectors + live status */}
      <div className="flex flex-wrap items-center gap-3 border-b bg-gradient-to-r from-muted/40 via-background to-background px-4 py-2.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Analyzing
        </span>

        <div className="inline-flex items-stretch overflow-hidden rounded-lg border bg-background divide-x">
          {/* Exchange */}
          <Select value={selectedExchange} onValueChange={onExchangeChange}>
            <SelectTrigger className="h-9 w-[92px] rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0">
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
                aria-expanded={underlyingOpen}
                className="h-9 w-[168px] justify-between rounded-none border-0 bg-transparent px-3 text-xs font-bold tracking-wide hover:bg-muted/40"
              >
                {selectedUnderlying || 'Select'}
                <ChevronsUpDown className="ml-2 h-3.5 w-3.5 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-0">
              <Command>
                <CommandInput placeholder="Search symbol..." className="h-9 text-xs" />
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
            <SelectTrigger className="h-9 w-[128px] rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0">
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

        <div className="ml-auto flex items-center gap-3">
          {/* Live indicator */}
          <div className="hidden items-center gap-1.5 sm:flex">
            <span className="relative flex h-2 w-2">
              <span
                className={cn(
                  'absolute inline-flex h-full w-full rounded-full opacity-75',
                  hasData ? 'animate-ping bg-emerald-400' : 'bg-muted-foreground/40'
                )}
              />
              <span
                className={cn(
                  'relative inline-flex h-2 w-2 rounded-full',
                  hasData ? 'bg-emerald-500' : 'bg-muted-foreground/60'
                )}
              />
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              {hasData ? 'Live' : 'Idle'}
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
      </div>

      {/* Metrics grid — hairline divisions, big primary numbers */}
      <div className="grid grid-cols-2 divide-x divide-y sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5">
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
    </div>
  )
}
