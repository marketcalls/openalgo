import { Minus, Plus } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { StrategyTemplate, TemplateLeg } from '@/lib/strategyTemplates'
import { cn } from '@/lib/utils'
import type { OptionStrike } from '@/types/option-chain'

export interface ResolvedTemplateLeg extends TemplateLeg {
  resolvedStrike: number
  /** Resolved expiry for this specific leg (may differ from header expiry for calendars/diagonals). */
  resolvedExpiry: string
  price: number
  symbol: string | null
}

export interface TemplateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  template: StrategyTemplate | null
  expiry: string
  expiries: string[]
  onExpiryChange: (e: string) => void
  chain: OptionStrike[] | null
  atmStrike: number | null
  /** Common strike increment in the chain (e.g. 50 for NIFTY). */
  strikeStep: number
  onConfirm: (legs: ResolvedTemplateLeg[], totalLots: number) => void
}

function nearestStrike(target: number, strikes: number[]): number | null {
  if (strikes.length === 0) return null
  let best = strikes[0]
  let bestDist = Math.abs(strikes[0] - target)
  for (const s of strikes) {
    const d = Math.abs(s - target)
    if (d < bestDist) {
      bestDist = d
      best = s
    }
  }
  return best
}

export function TemplateDialog({
  open,
  onOpenChange,
  template,
  expiry,
  expiries,
  onExpiryChange,
  chain,
  atmStrike,
  strikeStep,
  onConfirm,
}: TemplateDialogProps) {
  const [lots, setLots] = useState(1)
  const [strikeOverrides, setStrikeOverrides] = useState<Record<number, number>>({})

  // Reset overrides when template changes
  useEffect(() => {
    setStrikeOverrides({})
    setLots(1)
  }, [template?.id])

  const strikes = useMemo(() => chain?.map((s) => s.strike) ?? [], [chain])

  const resolved = useMemo<ResolvedTemplateLeg[]>(() => {
    if (!template || atmStrike === null || chain === null) return []
    // Locate the "near" expiry inside the list so we can index-offset from it.
    const baseIdx = Math.max(0, expiries.indexOf(expiry))
    return template.legs.map((leg, idx) => {
      const target = atmStrike + leg.strikeOffset * strikeStep
      const override = strikeOverrides[idx]
      const resolvedStrike = override ?? nearestStrike(target, strikes) ?? target

      // Calendar / diagonal support: each leg can have its own expiry offset.
      // We clamp to the last available expiry so a template that expects a
      // next-month leg still renders even when only one expiry is available.
      const offset = leg.expiryOffset ?? 0
      const targetIdx = Math.min(baseIdx + offset, expiries.length - 1)
      const resolvedExpiry = expiries[Math.max(0, targetIdx)] ?? expiry

      // Chain symbols are only available for the currently-loaded expiry.
      // For legs on a different expiry the caller rebuilds the symbol from
      // scratch via buildOptionSymbol.
      const canUseChain = resolvedExpiry === expiry
      const row = canUseChain ? chain.find((s) => s.strike === resolvedStrike) : undefined
      const side = leg.optionType === 'CE' ? row?.ce : row?.pe
      return {
        ...leg,
        resolvedStrike,
        resolvedExpiry,
        price: side?.ltp ?? 0,
        symbol: side?.symbol ?? null,
      }
    })
  }, [template, atmStrike, chain, strikes, strikeStep, strikeOverrides, expiry, expiries])

  if (!template) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base">{template.name}</DialogTitle>
          <DialogDescription className="text-xs">{template.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {resolved.map((leg, idx) => {
            const multiExpiry = leg.resolvedExpiry !== expiry
            return (
              <div key={idx} className="flex items-center gap-2 rounded-md border p-2 text-xs">
                <span
                  className={cn(
                    'inline-flex h-6 min-w-[2.25rem] shrink-0 items-center justify-center rounded px-1 font-semibold',
                    leg.side === 'BUY'
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                      : 'bg-rose-500/15 text-rose-700 dark:text-rose-400'
                  )}
                >
                  {leg.side === 'BUY' ? '+' : '-'}
                  {(leg.lots ?? 1) * lots}x
                </span>
                <Select
                  value={String(leg.resolvedStrike)}
                  onValueChange={(v) =>
                    setStrikeOverrides((prev) => ({ ...prev, [idx]: Number(v) }))
                  }
                  disabled={multiExpiry}
                >
                  <SelectTrigger className="h-8 w-[120px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {strikes.map((s) => (
                      <SelectItem key={s} value={String(s)}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-xs font-semibold">{leg.optionType}</span>
                {multiExpiry && (
                  <span
                    className={cn(
                      'rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700 dark:text-violet-400'
                    )}
                    title={`Leg expires ${leg.resolvedExpiry}`}
                  >
                    {leg.resolvedExpiry}
                  </span>
                )}
                <span className="ml-auto text-muted-foreground">
                  {leg.price > 0 ? `₹${leg.price.toFixed(2)}` : '—'}
                </span>
              </div>
            )
          })}

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground">Expiry</label>
              <Select value={expiry} onValueChange={onExpiryChange}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue />
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

            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground">Lot Qty</label>
              <div className="flex h-9 items-center overflow-hidden rounded-md border">
                <button
                  onClick={() => setLots(Math.max(1, lots - 1))}
                  className="h-full px-2 text-muted-foreground hover:bg-muted"
                >
                  <Minus className="h-3 w-3" />
                </button>
                <input
                  type="number"
                  min={1}
                  value={lots}
                  onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
                  className="w-full border-x bg-transparent text-center text-xs outline-none"
                />
                <button
                  onClick={() => setLots(lots + 1)}
                  className="h-full px-2 text-muted-foreground hover:bg-muted"
                >
                  <Plus className="h-3 w-3" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="flex-row justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => onConfirm(resolved, lots)}
            className="bg-emerald-500 hover:bg-emerald-600"
          >
            Add Strategy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
