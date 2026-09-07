/**
 * A small modify ticket for a working order: quantity, and whichever of
 * price and trigger the order type carries. The rest of the order (symbol,
 * side, product, type) is shown and not editable, because the modify route
 * takes the whole order and those are the parts that make it the same one.
 */

import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { DockOrder } from './blotter'

export interface ModifyValues {
  quantity: number
  price: number
  trigger_price: number
}

interface Props {
  /** The order being modified; null closes the dialog. */
  order: DockOrder | null
  onOpenChange(open: boolean): void
  /** Resolves true once the modification was accepted, which closes the dialog. */
  onSubmit(order: DockOrder, values: ModifyValues): Promise<boolean>
}

export function sendsPrice(pricetype: string): boolean {
  return pricetype === 'LIMIT' || pricetype === 'SL'
}

export function sendsTrigger(pricetype: string): boolean {
  return pricetype === 'SL' || pricetype === 'SL-M'
}

export function ModifyOrderDialog({ order, onOpenChange, onSubmit }: Props) {
  const [values, setValues] = useState<ModifyValues>({ quantity: 0, price: 0, trigger_price: 0 })
  const [busy, setBusy] = useState(false)

  // Prefilled from the row each time a different order is opened.
  useEffect(() => {
    if (!order) return
    setValues({
      quantity: order.quantity,
      price: order.price,
      trigger_price: order.trigger_price,
    })
    setBusy(false)
  }, [order])

  const withPrice = order ? sendsPrice(order.pricetype) : false
  const withTrigger = order ? sendsTrigger(order.pricetype) : false
  const valid =
    values.quantity > 0 &&
    (!withPrice || values.price > 0) &&
    (!withTrigger || values.trigger_price > 0)

  const submit = async () => {
    if (!order || !valid || busy) return
    setBusy(true)
    try {
      const ok = await onSubmit(order, values)
      if (ok) onOpenChange(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={order !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[380px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Modify order
            {order && (
              <Badge variant={order.action === 'BUY' ? 'default' : 'destructive'}>
                {order.action}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {order?.symbol} on {order?.exchange}, {order?.pricetype} {order?.product}, id{' '}
            <span className="font-mono">{order?.orderid}</span>
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <div className="grid grid-cols-[96px_1fr] items-center gap-2">
            <Label htmlFor="dock-modify-qty">Quantity</Label>
            <Input
              id="dock-modify-qty"
              type="number"
              min={1}
              step={1}
              value={values.quantity}
              onChange={(e) => setValues((v) => ({ ...v, quantity: Number(e.target.value) }))}
              className="h-8 text-right tabular-nums"
            />
          </div>
          {withPrice && (
            <div className="grid grid-cols-[96px_1fr] items-center gap-2">
              <Label htmlFor="dock-modify-price">Price</Label>
              <Input
                id="dock-modify-price"
                type="number"
                min={0}
                step="any"
                value={values.price}
                onChange={(e) => setValues((v) => ({ ...v, price: Number(e.target.value) }))}
                className="h-8 text-right tabular-nums"
              />
            </div>
          )}
          {withTrigger && (
            <div className="grid grid-cols-[96px_1fr] items-center gap-2">
              <Label htmlFor="dock-modify-trigger">Trigger</Label>
              <Input
                id="dock-modify-trigger"
                type="number"
                min={0}
                step="any"
                value={values.trigger_price}
                onChange={(e) =>
                  setValues((v) => ({ ...v, trigger_price: Number(e.target.value) }))
                }
                className="h-8 text-right tabular-nums"
              />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Keep as is
            </Button>
            <Button type="submit" disabled={!valid || busy}>
              {busy ? 'Modifying' : 'Modify'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
