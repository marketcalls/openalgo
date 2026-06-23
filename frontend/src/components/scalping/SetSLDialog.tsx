/**
 * SetSLDialog — configure a leg's stop-loss and optional auto-trailing.
 * Configure a leg's stop-loss: initial stop-loss + trailing step + enable toggle + target.
 */
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { SLState } from '@/hooks/useTrailingSL'
import { priceDecimals } from '@/lib/scalpingPrice'
import type { ScalpingAction, ScalpingProduct, SelectedLeg } from '@/types/scalping'

interface SetSLDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  leg: SelectedLeg | null
  product: ScalpingProduct
  side: ScalpingAction
  entryPrice: number
  quantity: number
  ltp?: number
  existing?: SLState
  onSave: (sl: SLState) => void
  onClear?: () => void
}

export function SetSLDialog({
  open,
  onOpenChange,
  leg,
  product,
  side,
  entryPrice,
  quantity,
  ltp,
  existing,
  onSave,
  onClear,
}: SetSLDialogProps) {
  const [stoploss, setStoploss] = useState('')
  const [trailingEnabled, setTrailingEnabled] = useState(false)
  const [trailingStep, setTrailingStep] = useState('')
  const [targetPrice, setTargetPrice] = useState('')

  // Seed fields when the dialog opens.
  useEffect(() => {
    if (!open) return
    if (existing) {
      setStoploss(String(existing.initialSl))
      setTrailingEnabled(existing.trailingEnabled)
      setTrailingStep(existing.trailingStep ? String(existing.trailingStep) : '')
      setTargetPrice(existing.target ? String(existing.target) : '')
    } else {
      setStoploss('')
      setTrailingEnabled(false)
      setTrailingStep('')
      setTargetPrice('')
    }
  }, [open, existing])

  // Currency derivatives (CDS/BCD) display to 4 decimals; everything else to 2.
  const decimals = priceDecimals(leg?.exchange)

  // Reference price for validating stop direction: prefer live LTP, else entry.
  const slNum = Number(stoploss)
  const refPrice = ltp != null && ltp > 0 ? ltp : entryPrice
  let directionError = ''
  if (Number.isFinite(slNum) && slNum > 0 && refPrice > 0) {
    if (side === 'BUY' && slNum >= refPrice) {
      directionError = `Long (BUY): stop-loss must be below ${refPrice.toFixed(decimals)}`
    } else if (side === 'SELL' && slNum <= refPrice) {
      directionError = `Short (SELL): stop-loss must be above ${refPrice.toFixed(decimals)}`
    }
  }

  // Target must be on the PROFIT side, or it would trigger an immediate exit.
  const tgtNum = Number(targetPrice)
  let targetError = ''
  if (Number.isFinite(tgtNum) && tgtNum > 0 && refPrice > 0) {
    if (side === 'BUY' && tgtNum <= refPrice) {
      targetError = `Long (BUY): target must be above ${refPrice.toFixed(decimals)}`
    } else if (side === 'SELL' && tgtNum >= refPrice) {
      targetError = `Short (SELL): target must be below ${refPrice.toFixed(decimals)}`
    }
  }

  // Trailing enabled with a non-positive step would appear active but never move.
  const stepNum = Number(trailingStep)
  const trailingError =
    trailingEnabled && !(Number.isFinite(stepNum) && stepNum > 0)
      ? 'Trailing step must be greater than 0'
      : ''

  const handleSave = () => {
    if (!leg) return
    const sl = Number(stoploss)
    if (!Number.isFinite(sl) || sl <= 0) return
    if (quantity <= 0) return
    // Block wrong-side stop/target (immediate exit) and an inert trailing config.
    if (directionError || targetError || trailingError) return
    const step = Number(trailingStep)
    const tgt = Number(targetPrice)
    const entry = entryPrice > 0 ? entryPrice : (ltp ?? 0)
    onSave({
      symbol: leg.symbol,
      exchange: leg.exchange,
      product,
      side,
      entry,
      quantity,
      initialSl: sl,
      trailingEnabled,
      trailingStep: Number.isFinite(step) && step > 0 ? step : 0,
      highestPrice: entry,
      lowestPrice: entry,
      currentSl: sl,
      target: Number.isFinite(tgt) && tgt > 0 ? tgt : 0,
      active: true,
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>SL · Target · Trailing — {leg?.symbol ?? ''}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Entry</span>
              <div className="font-mono">{entryPrice > 0 ? entryPrice.toFixed(decimals) : '—'}</div>
            </div>
            <div>
              <span className="text-muted-foreground">LTP</span>
              <div className="font-mono">{ltp != null ? ltp.toFixed(decimals) : '—'}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Side</span>
              <div className="font-mono">{side}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Qty</span>
              <div className="font-mono">{quantity}</div>
            </div>
          </div>

          {quantity <= 0 && (
            <p className="text-xs text-red-600">
              No quantity for this leg yet — open a position (or wait for chain data) before setting
              a stop-loss.
            </p>
          )}

          <div className="space-y-1">
            <Label htmlFor="sl-price">Stop-loss price</Label>
            <Input
              id="sl-price"
              type="number"
              inputMode="decimal"
              value={stoploss}
              onChange={(e) => setStoploss(e.target.value)}
              placeholder="e.g. 270"
            />
            {directionError && <p className="text-xs text-red-600">{directionError}</p>}
          </div>

          <label className="flex items-center gap-2">
            <Checkbox
              checked={trailingEnabled}
              onCheckedChange={(v) => setTrailingEnabled(v === true)}
            />
            <span className="text-sm">Enable trailing stop-loss</span>
          </label>

          {trailingEnabled && (
            <div className="space-y-1">
              <Label htmlFor="sl-step">Trailing step</Label>
              <Input
                id="sl-step"
                type="number"
                inputMode="decimal"
                value={trailingStep}
                onChange={(e) => setTrailingStep(e.target.value)}
                placeholder="e.g. 2"
              />
              <p className="text-xs text-muted-foreground">
                Trailing starts only once price is ≥1 in profit; the stop only moves in your favor.
              </p>
              {trailingError && <p className="text-xs text-red-600">{trailingError}</p>}
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="sl-target">Target price (optional)</Label>
            <Input
              id="sl-target"
              type="number"
              inputMode="decimal"
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
              placeholder={side === 'BUY' ? 'above entry' : 'below entry'}
            />
            {targetError && <p className="text-xs text-red-600">{targetError}</p>}
          </div>
        </div>

        <DialogFooter className="gap-2">
          {existing && onClear && (
            <Button
              variant="outline"
              onClick={() => {
                onClear()
                onOpenChange(false)
              }}
            >
              Clear SL
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={
              quantity <= 0 || !stoploss || !!directionError || !!targetError || !!trailingError
            }
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
