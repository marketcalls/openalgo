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
import { strikeMoneyness } from '@/lib/strategyMath'
import type { StrategyTemplate, TemplateLeg } from '@/lib/strategyTemplates'
import {
  resolveExpiryOffset,
  resolveListedContract,
  resolveStrikeOffset,
  validateTemplateStrikeTopology,
} from '@/lib/templateResolution'
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
  onConfirm: (legs: ResolvedTemplateLeg[], totalLots: number) => void | Promise<void>
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
  const [isConfirming, setIsConfirming] = useState(false)

  // Reset overrides when template changes
  // biome-ignore lint/correctness/useExhaustiveDependencies: template?.id is an intentional reset trigger — the body only calls setters, but it MUST re-fire when the selected template changes to clear stale overrides
  useEffect(() => {
    setStrikeOverrides({})
    setLots(1)
    setIsConfirming(false)
  }, [template?.id])

  const strikes = useMemo(
    () =>
      Array.from(new Set(chain?.map((strike) => strike.strike) ?? [])).sort(
        (left, right) => left - right
      ),
    [chain]
  )

  const resolution = useMemo<{
    legs: ResolvedTemplateLeg[]
    errors: string[]
    strikeErrorIndexes: Set<number>
    expiryInvalid: boolean
  }>(() => {
    if (!template || atmStrike === null || chain === null) {
      return { legs: [], errors: [], strikeErrorIndexes: new Set(), expiryInvalid: false }
    }

    const unresolvedTopology: Array<{
      strikeOffset: number
      resolvedStrike: number | null
    }> = []
    const errors: string[] = []
    const strikeErrorIndexes = new Set<number>()
    let expiryInvalid = false
    const legs = template.legs.map((leg, idx) => {
      const override = strikeOverrides[idx]
      const listedStrike = resolveStrikeOffset(strikes, atmStrike, leg.strikeOffset)
      const resolvedStrike = override ?? listedStrike
      unresolvedTopology.push({ strikeOffset: leg.strikeOffset, resolvedStrike })

      const offset = leg.expiryOffset ?? 0
      const listedExpiry = resolveExpiryOffset(expiries, expiry, offset)
      if (listedExpiry === null) {
        expiryInvalid = true
        errors.push(
          offset > 0
            ? `A later expiry is required for ${template.name}.`
            : `The selected expiry cannot resolve every leg in ${template.name}.`
        )
      }
      const resolvedExpiry = listedExpiry ?? expiry
      const displayStrike = resolvedStrike ?? atmStrike
      if (resolvedStrike === null) strikeErrorIndexes.add(idx)

      // Chain symbols are only available for the currently-loaded expiry.
      // For legs on a different expiry the caller rebuilds the symbol from
      // scratch via buildOptionSymbol.
      const canUseChain = resolvedExpiry === expiry
      const side = canUseChain ? resolveListedContract(chain, displayStrike, leg.optionType) : null
      if (canUseChain && resolvedStrike !== null && side === null) {
        strikeErrorIndexes.add(idx)
        errors.push(
          `The required ${leg.optionType} contract at ${displayStrike} is not available in the loaded option chain.`
        )
      }
      return {
        ...leg,
        resolvedStrike: displayStrike,
        resolvedExpiry,
        price: side?.ltp ?? 0,
        symbol: side?.symbol ?? null,
      }
    })

    const topologyErrors = validateTemplateStrikeTopology(unresolvedTopology)
    if (topologyErrors.length > 0) {
      for (let index = 0; index < template.legs.length; index += 1) {
        strikeErrorIndexes.add(index)
      }
    }
    errors.push(...topologyErrors)
    return {
      legs,
      errors: Array.from(new Set(errors)),
      strikeErrorIndexes,
      expiryInvalid,
    }
  }, [template, atmStrike, chain, strikes, strikeOverrides, expiry, expiries])

  const resolved = resolution.legs
  const validationErrors = resolution.errors
  const expiryInvalid = resolution.expiryInvalid
  const validationErrorId = 'template-validation-error'

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
            const strikeInvalid = resolution.strikeErrorIndexes.has(idx)
            const moneyness = strikeMoneyness(
              leg.resolvedStrike,
              atmStrike,
              strikeStep,
              leg.optionType
            )
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
                  <SelectTrigger
                    aria-label={`Strike for ${leg.side.toLowerCase()} ${leg.optionType === 'CE' ? 'call' : 'put'} leg ${idx + 1}`}
                    aria-invalid={strikeInvalid}
                    aria-describedby={strikeInvalid ? validationErrorId : undefined}
                    className="h-8 w-[120px] text-xs"
                  >
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
                {moneyness && (
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
                      moneyness.kind === 'ATM' &&
                        'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                      moneyness.kind === 'ITM' && 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
                      moneyness.kind === 'OTM' && 'bg-muted text-muted-foreground'
                    )}
                    title={
                      moneyness.kind === 'ATM'
                        ? 'At the Money'
                        : moneyness.kind === 'ITM'
                          ? `In the Money · ${Math.abs(moneyness.steps)} ${Math.abs(moneyness.steps) === 1 ? 'strike' : 'strikes'} from ATM`
                          : `Out of the Money · ${Math.abs(moneyness.steps)} ${Math.abs(moneyness.steps) === 1 ? 'strike' : 'strikes'} from ATM`
                    }
                  >
                    {moneyness.label}
                  </span>
                )}
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

          {validationErrors.length > 0 && (
            <div
              id={validationErrorId}
              role="alert"
              className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive"
            >
              {validationErrors.map((error) => (
                <p key={error}>{error}</p>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground">Expiry</label>
              <Select value={expiry} onValueChange={onExpiryChange}>
                <SelectTrigger
                  aria-label="Strategy expiry"
                  aria-invalid={expiryInvalid}
                  aria-describedby={expiryInvalid ? validationErrorId : undefined}
                  className="h-9 text-xs"
                >
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
                  type="button"
                  aria-label="Decrease strategy lots"
                  onClick={() => setLots(Math.max(1, lots - 1))}
                  className="h-full px-2 text-muted-foreground hover:bg-muted"
                >
                  <Minus className="h-3 w-3" />
                </button>
                <input
                  type="number"
                  aria-label="Strategy lot quantity"
                  min={1}
                  value={lots}
                  onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
                  className="w-full border-x bg-transparent text-center text-xs outline-none"
                />
                <button
                  type="button"
                  aria-label="Increase strategy lots"
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
            disabled={
              isConfirming ||
              validationErrors.length > 0 ||
              resolved.length !== template.legs.length
            }
            onClick={async () => {
              if (validationErrors.length > 0) return
              setIsConfirming(true)
              try {
                await onConfirm(resolved, lots)
              } finally {
                setIsConfirming(false)
              }
            }}
            className="bg-emerald-700 text-white hover:bg-emerald-800 dark:bg-emerald-600 dark:hover:bg-emerald-700"
          >
            {isConfirming ? 'Validating...' : 'Add Strategy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
