import { useEffect, useMemo, useState } from 'react'
import { Minus, Plus, Trash2 } from 'lucide-react'
import { apiClient } from '@/api/client'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { buildFutureSymbol, buildOptionSymbol } from '@/lib/strategyMath'
import type { StrategyLeg } from '@/lib/strategyMath'
import type { OptionStrike } from '@/types/option-chain'

export interface EditLegDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  leg: StrategyLeg | null
  optionExpiries: string[]
  futureExpiries: string[]
  chain: OptionStrike[] | null
  /**
   * Expiry the `chain` corresponds to. If the user picks a different expiry
   * in this dialog we fall back to a live /quotes fetch for the freshly-
   * constructed option symbol.
   */
  chainExpiry: string
  /** Underlying base symbol (e.g. "NIFTY"), used to rebuild option symbols. */
  underlying: string
  /** F&O exchange (NFO / BFO / MCX / CDS) for the /quotes call. */
  optionExchange: string
  /** OpenAlgo API key for /quotes. */
  apiKey: string
  onSave: (updated: StrategyLeg) => void
  onDelete: (id: string) => void
}

export function EditLegDialog({
  open,
  onOpenChange,
  leg,
  optionExpiries,
  futureExpiries,
  chain,
  chainExpiry,
  underlying,
  optionExchange,
  apiKey,
  onSave,
  onDelete,
}: EditLegDialogProps) {
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [expiry, setExpiry] = useState('')
  const [strike, setStrike] = useState<number | undefined>(undefined)
  const [optionType, setOptionType] = useState<'CE' | 'PE'>('CE')
  const [lots, setLots] = useState(1)
  const [entryPrice, setEntryPrice] = useState('')
  const [exitPrice, setExitPrice] = useState('')

  // When the dialog opens for a leg, hydrate local state from it.
  useEffect(() => {
    if (!leg) return
    setSide(leg.side)
    setExpiry(leg.expiry)
    setStrike(leg.strike)
    setOptionType(leg.optionType ?? 'CE')
    setLots(leg.lots)
    setEntryPrice(leg.price.toString())
    setExitPrice(
      leg.exitPrice !== undefined && leg.exitPrice > 0 ? leg.exitPrice.toString() : ''
    )
  }, [leg])

  const isClosed = exitPrice.trim() !== '' && Number(exitPrice) > 0

  const [isPriceLoading, setIsPriceLoading] = useState(false)

  /**
   * Look up live LTP for the leg's current (strike, optionType, expiry) —
   * or for futures, just (expiry) — and write it into the Entry Price field.
   * Called explicitly from the Strike / Type / Expiry onChange handlers.
   *
   * Fast path: for option legs on the same expiry as the loaded chain, read
   * LTP from chain (synchronous, no network).
   * Slow path: for cross-expiry option legs OR any futures leg, build the
   * symbol and fetch /quotes for it.
   */
  const syncEntryPriceFromChain = async (
    nextStrike: number | undefined,
    nextType: 'CE' | 'PE',
    nextExpiry: string
  ) => {
    if (!leg || isClosed || !nextExpiry) return

    // ── Options: try the chain first, fall back to /quotes ──
    if (leg.segment === 'OPTION') {
      if (nextStrike === undefined) return

      if (chain && nextExpiry === chainExpiry) {
        const row = chain.find((s) => s.strike === nextStrike)
        const sideRow = nextType === 'CE' ? row?.ce : row?.pe
        if (sideRow && sideRow.ltp > 0) {
          setEntryPrice(sideRow.ltp.toString())
        }
        return
      }

      if (!apiKey || !underlying || !optionExchange) return
      const symbol = buildOptionSymbol(underlying, nextExpiry, nextStrike, nextType)
      await fetchAndSetLtp(symbol, optionExchange)
      return
    }

    // ── Futures: only expiry matters ──
    if (leg.segment === 'FUTURE') {
      if (!apiKey || !underlying || !optionExchange) return
      const symbol = buildFutureSymbol(underlying, nextExpiry)
      await fetchAndSetLtp(symbol, optionExchange)
    }
  }

  const fetchAndSetLtp = async (symbol: string, exchange: string) => {
    setIsPriceLoading(true)
    try {
      const res = await apiClient.post<{
        status: string
        data?: { ltp?: number }
      }>(
        '/quotes',
        { apikey: apiKey, symbol, exchange },
        { validateStatus: () => true }
      )
      if (res.data.status === 'success' && res.data.data?.ltp) {
        setEntryPrice(String(res.data.data.ltp))
      }
    } catch {
      /* non-fatal — user can enter the price manually */
    } finally {
      setIsPriceLoading(false)
    }
  }

  const availableExpiries = useMemo(
    () => (leg?.segment === 'FUTURE' ? futureExpiries : optionExpiries),
    [leg, optionExpiries, futureExpiries]
  )

  const strikes = useMemo(() => chain?.map((s) => s.strike) ?? [], [chain])

  if (!leg) return null

  const handleSave = () => {
    const updated: StrategyLeg = {
      ...leg,
      side,
      expiry,
      lots: Math.max(1, lots),
      price: Number(entryPrice) || leg.price,
      exitPrice: exitPrice.trim() === '' ? undefined : Number(exitPrice) || undefined,
    }
    if (leg.segment === 'OPTION') {
      updated.strike = strike ?? leg.strike
      updated.optionType = optionType
    }
    onSave(updated)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Position</DialogTitle>
          <DialogDescription>
            Update expiry, strike, side, quantity, entry price, or mark the leg closed with an
            exit price.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Expiry */}
          <div className="space-y-1">
            <Select
              value={expiry}
              onValueChange={(v) => {
                setExpiry(v)
                syncEntryPriceFromChain(strike, optionType, v)
              }}
            >
              <SelectTrigger className="h-10 text-sm font-semibold">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableExpiries.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">Select Expiry</p>
          </div>

          {/* Strike + Type (options only) */}
          {leg.segment === 'OPTION' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Select
                  value={strike !== undefined ? String(strike) : ''}
                  onValueChange={(v) => {
                    const nextStrike = Number(v)
                    setStrike(nextStrike)
                    syncEntryPriceFromChain(nextStrike, optionType, expiry)
                  }}
                >
                  <SelectTrigger className="h-10 text-sm font-semibold">
                    <SelectValue placeholder="Strike" />
                  </SelectTrigger>
                  <SelectContent>
                    {strikes.map((s) => (
                      <SelectItem key={s} value={String(s)}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">Strike</p>
              </div>
              <div className="space-y-1">
                <Select
                  value={optionType}
                  onValueChange={(v) => {
                    const nextType = v as 'CE' | 'PE'
                    setOptionType(nextType)
                    syncEntryPriceFromChain(strike, nextType, expiry)
                  }}
                >
                  <SelectTrigger className="h-10 text-sm font-semibold">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="CE">CE</SelectItem>
                    <SelectItem value="PE">PE</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">Option Type</p>
              </div>
            </div>
          )}

          {/* Buy/Sell */}
          <div className="flex items-center gap-6">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="side"
                checked={side === 'BUY'}
                onChange={() => setSide('BUY')}
                className="h-4 w-4 accent-emerald-500"
              />
              <span className={cn(side === 'BUY' && 'font-semibold text-emerald-600')}>Buy</span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="side"
                checked={side === 'SELL'}
                onChange={() => setSide('SELL')}
                className="h-4 w-4 accent-rose-500"
              />
              <span className={cn(side === 'SELL' && 'font-semibold text-rose-600')}>Sell</span>
            </label>
          </div>

          {/* Lot Qty */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Lot Qty: {lots}</label>
            <div className="inline-flex h-10 w-[160px] items-center overflow-hidden rounded-md border">
              <button
                type="button"
                onClick={() => setLots(Math.max(1, lots - 1))}
                className="flex h-full w-10 items-center justify-center text-muted-foreground hover:bg-muted"
                aria-label="Decrease lots"
              >
                <Minus className="h-4 w-4" />
              </button>
              <input
                type="number"
                min={1}
                value={lots}
                onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
                className="h-full w-full border-x bg-transparent text-center text-sm font-semibold tabular-nums outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <button
                type="button"
                onClick={() => setLots(lots + 1)}
                className="flex h-full w-10 items-center justify-center text-muted-foreground hover:bg-muted"
                aria-label="Increase lots"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Entry Price */}
          <div className="space-y-1">
            <Input
              type="number"
              step="0.05"
              value={entryPrice}
              onChange={(e) => setEntryPrice(e.target.value)}
              disabled={isPriceLoading}
              className="h-10 text-base font-semibold"
            />
            <p className="text-[11px] text-muted-foreground">
              {isPriceLoading
                ? 'Fetching live LTP…'
                : `Modify ${leg.segment === 'FUTURE' ? 'Futures' : 'Option'} Entry Price`}
            </p>
          </div>

          {/* Exit Price */}
          <div className="space-y-1">
            <Input
              type="number"
              step="0.05"
              value={exitPrice}
              onChange={(e) => setExitPrice(e.target.value)}
              placeholder="0"
              className={cn(
                'h-10 text-base font-semibold',
                isClosed && 'border-rose-400 text-rose-600 dark:text-rose-400'
              )}
            />
            <p className="text-[11px] text-muted-foreground">
              Enter Exit Price {isClosed && '— leg will be marked as closed'}
            </p>
          </div>
        </div>

        <DialogFooter className="flex-row items-center justify-between gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" onClick={handleSave}>
              Modify
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 text-rose-500 hover:bg-rose-500/10 hover:text-rose-600"
              onClick={() => {
                onDelete(leg.id)
                onOpenChange(false)
              }}
              aria-label="Delete position"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
