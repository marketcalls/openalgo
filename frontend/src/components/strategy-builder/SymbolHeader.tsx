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

function Metric({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: 'profit' | 'loss' | 'warn' | 'info' | 'neutral'
}) {
  return (
    <div
      className={cn(
        'rounded-md px-2.5 py-1.5 text-xs font-medium',
        tone === 'profit' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        tone === 'loss' && 'bg-rose-500/10 text-rose-700 dark:text-rose-300',
        tone === 'warn' && 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
        tone === 'info' && 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
        tone === 'neutral' && 'bg-muted text-foreground'
      )}
    >
      <span className="mr-1 text-muted-foreground">{label}:</span>
      <span className="font-semibold tabular-nums">{value}</span>
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
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* Exchange */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Exchange</label>
          <Select value={selectedExchange} onValueChange={onExchangeChange}>
            <SelectTrigger className="h-9 w-28 text-xs">
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
        </div>

        {/* Underlying (searchable) */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Index / Stock</label>
          <Popover open={underlyingOpen} onOpenChange={onUnderlyingOpenChange}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={underlyingOpen}
                className="h-9 w-48 justify-between text-xs font-semibold"
              >
                {selectedUnderlying || 'Select'}
                <ChevronsUpDown className="ml-2 h-3.5 w-3.5 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 p-0">
              <Command>
                <CommandInput placeholder="Search..." className="h-9 text-xs" />
                <CommandList>
                  <CommandEmpty>None found.</CommandEmpty>
                  <CommandGroup>
                    {underlyings.map((u) => (
                      <CommandItem
                        key={u}
                        value={u}
                        onSelect={() => {
                          onUnderlyingChange(u)
                          onUnderlyingOpenChange(false)
                        }}
                        className="text-xs"
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
        </div>

        {/* Expiry */}
        <div className="flex flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Expiry</label>
          <Select value={selectedExpiry} onValueChange={onExpiryChange}>
            <SelectTrigger className="h-9 w-36 text-xs">
              <SelectValue placeholder="Select" />
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

        <div className="ml-auto">
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="h-9 text-xs"
          >
            <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Metadata strip */}
      <div className="flex flex-wrap gap-2">
        <Metric label="Spot" value={spotPrice !== null ? spotPrice.toFixed(2) : '—'} tone="info" />
        <Metric
          label="Futures"
          value={futuresPrice !== null ? futuresPrice.toFixed(2) : '—'}
          tone="profit"
        />
        <Metric label="Lot Size" value={lotSize !== null ? String(lotSize) : '—'} tone="neutral" />
        <Metric label="ATM IV" value={atmIv !== null ? `${atmIv.toFixed(2)}%` : '—'} tone="warn" />
        <Metric
          label="DTE"
          value={daysToExpiry !== null ? `${daysToExpiry.toFixed(0)}d` : '—'}
          tone="loss"
        />
      </div>
    </div>
  )
}
