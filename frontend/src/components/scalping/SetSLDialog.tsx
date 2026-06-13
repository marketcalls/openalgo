/**
 * SetSLDialog — configure a leg's stop-loss and optional auto-trailing.
 * Mirrors the 1cliq "Set SL" dialog: initial stop-loss + trailing step + enable toggle.
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

  // Seed fields when the dialog opens.
  useEffect(() => {
    if (!open) return
    if (existing) {
      setStoploss(String(existing.initialSl))
      setTrailingEnabled(existing.trailingEnabled)
      setTrailingStep(existing.trailingStep ? String(existing.trailingStep) : '')
    } else {
      setStoploss('')
      setTrailingEnabled(false)
      setTrailingStep('')
    }
  }, [open, existing])

  const handleSave = () => {
    if (!leg) return
    const sl = Number(stoploss)
    if (!Number.isFinite(sl) || sl <= 0) return
    if (quantity <= 0) return
    const step = Number(trailingStep)
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
      active: true,
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Set Stop-Loss — {leg?.symbol ?? ''}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Entry</span>
              <div className="font-mono">{entryPrice > 0 ? entryPrice.toFixed(2) : '—'}</div>
            </div>
            <div>
              <span className="text-muted-foreground">LTP</span>
              <div className="font-mono">{ltp != null ? ltp.toFixed(2) : '—'}</div>
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
            </div>
          )}
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
          <Button onClick={handleSave} disabled={quantity <= 0 || !stoploss}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
