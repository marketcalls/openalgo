// frontend/src/components/reports/PnlTableFiltersDialog.tsx
/**
 * The Filters button of the merged P&L page (fork-only). It sits above the
 * Report / Curve tabs and narrows both: symbol, strategy, exchange, product.
 */
import { Settings2 } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EMPTY_TABLE_FILTERS, type PnlOptions, type PnlTableFilters } from '@/hooks/usePnlFilters'
import { cn } from '@/lib/utils'

interface Props {
  value: PnlTableFilters
  onChange: (value: PnlTableFilters) => void
  options: PnlOptions
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function Chips({
  options,
  selected,
  onToggle,
}: {
  options: string[]
  selected: string[]
  onToggle: (value: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={selected.includes(option)}
          onClick={() => onToggle(option)}
          className={cn(
            'rounded-full border px-3 py-1 text-sm transition-colors',
            selected.includes(option) ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
          )}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

export function PnlTableFiltersDialog({ value, onChange, options }: Props) {
  const [open, setOpen] = useState(false)
  const active =
    value.symbol.trim() !== '' ||
    value.strategies.length > 0 ||
    value.exchanges.length > 0 ||
    value.products.length > 0

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant={active ? 'default' : 'outline'}
          size="sm"
          className="relative"
          aria-label="Open P&L filters"
        >
          <Settings2 className="h-4 w-4 mr-2" />
          Filters
          {active && (
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-red-500 rounded-full" />
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>P&L Filters</DialogTitle>
          <DialogDescription>
            Narrow the report tables and the curve by symbol, strategy, exchange or product
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-6 py-4">
          <div className="space-y-2">
            <Label htmlFor="pnl-filter-symbol">Symbol</Label>
            <Input
              id="pnl-filter-symbol"
              placeholder="e.g. INFY"
              value={value.symbol}
              onChange={(e) => onChange({ ...value, symbol: e.target.value })}
            />
          </div>
          {options.strategies.length > 0 && (
            <div className="space-y-2">
              <Label>Strategy</Label>
              <Chips
                options={options.strategies}
                selected={value.strategies}
                onToggle={(v) => onChange({ ...value, strategies: toggle(value.strategies, v) })}
              />
            </div>
          )}
          {options.exchanges.length > 0 && (
            <div className="space-y-2">
              <Label>Exchange</Label>
              <Chips
                options={options.exchanges}
                selected={value.exchanges}
                onToggle={(v) => onChange({ ...value, exchanges: toggle(value.exchanges, v) })}
              />
            </div>
          )}
          {options.products.length > 0 && (
            <div className="space-y-2">
              <Label>Product</Label>
              <Chips
                options={options.products}
                selected={value.products}
                onToggle={(v) => onChange({ ...value, products: toggle(value.products, v) })}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onChange(EMPTY_TABLE_FILTERS)}>
            Clear All
          </Button>
          <Button onClick={() => setOpen(false)}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
