import { Minus, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
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
import type { ResolveLegContract } from '@/components/strategy-builder/ManualLegBuilder'
import { parseFinitePrice, type ResolvedLegMarket } from '@/lib/strategyContracts'
import type { StrategyLeg } from '@/lib/strategyMath'
import { strikeMoneyness } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import type { OptionStrike } from '@/types/option-chain'

export interface EditLegDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  leg: StrategyLeg | null
  optionExpiries: string[]
  futureExpiries: string[]
  chain: OptionStrike[] | null
  /** ATM strike from the live chain — used to show moneyness next to the Strike field. */
  atmStrike?: number | null
  /** Common strike increment (e.g. 50 for NIFTY) — drives the moneyness step count. */
  strikeStep?: number
  resolveContract: ResolveLegContract
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
  atmStrike = null,
  strikeStep = 0,
  resolveContract,
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
  const [entryPriceError, setEntryPriceError] = useState<string | null>(null)
  const [exitPriceError, setExitPriceError] = useState<string | null>(null)
  const [resolvedContract, setResolvedContract] = useState<ResolvedLegMarket | null>(null)
  const [contractError, setContractError] = useState<string | null>(null)
  const [isPriceLoading, setIsPriceLoading] = useState(false)
  const resolveGenerationRef = useRef(0)
  const legRef = useRef(leg)
  legRef.current = leg
  const openLegSelectionKey = leg
    ? [leg.id, leg.segment, leg.expiry, leg.strike ?? '', leg.optionType ?? ''].join(':')
    : ''

  // Hydrate the editable values, but never trust the persisted symbol or
  // market metadata as proof that the contract is still listed. Resolve the
  // exact stored selection on every open/leg identity change and keep Modify
  // disabled until that validation completes.
  useEffect(() => {
    const currentLeg = legRef.current
    const generation = ++resolveGenerationRef.current
    if (!open || !currentLeg || openLegSelectionKey === '') {
      setResolvedContract(null)
      setIsPriceLoading(false)
      return
    }
    const currentType = currentLeg.optionType ?? 'CE'
    setSide(currentLeg.side)
    setExpiry(currentLeg.expiry)
    setStrike(currentLeg.strike)
    setOptionType(currentType)
    setLots(currentLeg.lots)
    setEntryPrice(currentLeg.price.toString())
    setExitPrice(currentLeg.exitPrice !== undefined ? currentLeg.exitPrice.toString() : '')
    setEntryPriceError(null)
    setExitPriceError(null)
    setContractError(null)
    setResolvedContract(null)
    setIsPriceLoading(true)
    void resolveContract(
      currentLeg.expiry,
      currentLeg.segment,
      currentLeg.strike,
      currentLeg.segment === 'OPTION' ? currentType : undefined
    )
      .then((contract) => {
        if (generation !== resolveGenerationRef.current) return
        if (contract === null) {
          setContractError('Contract is not listed for this selection')
          return
        }
        setResolvedContract(contract)
      })
      .catch(() => {
        if (generation === resolveGenerationRef.current) {
          setContractError('Unable to resolve this contract')
        }
      })
      .finally(() => {
        if (generation === resolveGenerationRef.current) setIsPriceLoading(false)
      })
  }, [open, openLegSelectionKey, resolveContract])

  const isClosed = exitPrice.trim() !== '' && parseFinitePrice(exitPrice).value !== null

  /** Resolve the exact listed selection; only the latest request may update the form. */
  const resolveSelection = (
    nextStrike: number | undefined,
    nextType: 'CE' | 'PE',
    nextExpiry: string
  ) => {
    const generation = ++resolveGenerationRef.current
    setResolvedContract(null)
    setEntryPrice('')
    setEntryPriceError(null)
    setContractError(null)
    const currentLeg = legRef.current
    if (
      !currentLeg ||
      !nextExpiry ||
      (currentLeg.segment === 'OPTION' && nextStrike === undefined)
    ) {
      setIsPriceLoading(false)
      return
    }

    setIsPriceLoading(true)
    void resolveContract(nextExpiry, currentLeg.segment, nextStrike, nextType)
      .then((contract) => {
        if (generation !== resolveGenerationRef.current) return
        if (contract === null) {
          setContractError('Contract is not listed for this selection')
          return
        }
        setResolvedContract(contract)
        setEntryPrice(String(contract.marketPrice))
      })
      .catch(() => {
        if (generation === resolveGenerationRef.current) {
          setContractError('Unable to resolve this contract')
        }
      })
      .finally(() => {
        if (generation === resolveGenerationRef.current) setIsPriceLoading(false)
      })
  }

  const availableExpiries = useMemo(
    () => (leg?.segment === 'FUTURE' ? futureExpiries : optionExpiries),
    [leg, optionExpiries, futureExpiries]
  )

  const strikes = useMemo(() => chain?.map((s) => s.strike) ?? [], [chain])

  if (!leg) return null

  const handleSave = () => {
    const parsedEntry = parseFinitePrice(entryPrice)
    const parsedExit =
      exitPrice.trim() === '' ? { value: null, error: null } : parseFinitePrice(exitPrice)
    setEntryPriceError(parsedEntry.error)
    setExitPriceError(parsedExit.error)
    if (parsedEntry.error || parsedEntry.value === null || parsedExit.error || !resolvedContract) {
      return
    }

    const updated: StrategyLeg = {
      ...leg,
      side,
      expiry,
      lots: Math.max(1, lots),
      price: parsedEntry.value,
      exitPrice: parsedExit.value ?? undefined,
      symbol: resolvedContract.symbol,
      exchange: resolvedContract.exchange,
      expiryTs: resolvedContract.expiryTs,
      lotSize: resolvedContract.lotSize,
      tickSize: resolvedContract.tickSize,
      contractValid: resolvedContract.contractValid,
      marketPrice: resolvedContract.marketPrice,
      iv: resolvedContract.iv,
      referenceUnderlying: resolvedContract.referenceUnderlying,
      forwardPrice: resolvedContract.forwardPrice ?? undefined,
      marketGreeks: resolvedContract.greeks,
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
            Update expiry, strike, side, quantity, entry price, or mark the leg closed with an exit
            price.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Expiry */}
          <div className="space-y-1">
            <Select
              value={expiry}
              onValueChange={(v) => {
                setExpiry(v)
                resolveSelection(strike, optionType, v)
              }}
            >
              <SelectTrigger aria-label="Expiry" className="h-10 text-sm font-semibold">
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
                    resolveSelection(nextStrike, optionType, expiry)
                  }}
                >
                  <SelectTrigger aria-label="Strike" className="h-10 text-sm font-semibold">
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
                {(() => {
                  const m = strikeMoneyness(strike, atmStrike, strikeStep, optionType)
                  if (!m) {
                    return <p className="text-[11px] text-muted-foreground">Strike</p>
                  }
                  return (
                    <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      Strike
                      <span
                        className={cn(
                          'rounded px-1 py-px text-[9px] font-semibold uppercase tracking-wider',
                          m.kind === 'ATM' && 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                          m.kind === 'ITM' && 'bg-sky-500/15 text-sky-700 dark:text-sky-400',
                          m.kind === 'OTM' && 'bg-muted text-muted-foreground'
                        )}
                      >
                        {m.label}
                      </span>
                    </p>
                  )
                })()}
              </div>
              <div className="space-y-1">
                <Select
                  value={optionType}
                  onValueChange={(v) => {
                    const nextType = v as 'CE' | 'PE'
                    setOptionType(nextType)
                    resolveSelection(strike, nextType, expiry)
                  }}
                >
                  <SelectTrigger aria-label="Option type" className="h-10 text-sm font-semibold">
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
            <label className="text-sm font-medium">Lot Qty</label>
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
              aria-label="Entry price"
              aria-invalid={entryPriceError !== null}
              aria-describedby={entryPriceError ? 'entry-price-error' : undefined}
              type="text"
              inputMode="decimal"
              value={entryPrice}
              onChange={(e) => {
                setEntryPrice(e.target.value)
                setEntryPriceError(null)
              }}
              disabled={isPriceLoading}
              className="h-10 text-base font-semibold"
            />
            {entryPriceError ? (
              <p id="entry-price-error" role="alert" className="text-[11px] text-destructive">
                {entryPriceError}
              </p>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                {isPriceLoading
                  ? 'Resolving listed contract…'
                  : `Modify ${leg.segment === 'FUTURE' ? 'Futures' : 'Option'} Entry Price`}
              </p>
            )}
          </div>

          {/* Exit Price */}
          <div className="space-y-1">
            <Input
              aria-label="Exit price"
              aria-invalid={exitPriceError !== null}
              aria-describedby={exitPriceError ? 'exit-price-error' : undefined}
              type="text"
              inputMode="decimal"
              value={exitPrice}
              onChange={(e) => {
                setExitPrice(e.target.value)
                setExitPriceError(null)
              }}
              placeholder="0"
              className={cn(
                'h-10 text-base font-semibold',
                isClosed && 'border-rose-400 text-rose-600 dark:text-rose-400'
              )}
            />
            {exitPriceError ? (
              <p id="exit-price-error" role="alert" className="text-[11px] text-destructive">
                {exitPriceError}
              </p>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Enter Exit Price {isClosed && '— leg will be marked as closed'}
              </p>
            )}
          </div>

          {(resolvedContract || contractError) && (
            <p
              className={cn(
                'font-mono text-[11px]',
                contractError ? 'text-destructive' : 'text-muted-foreground'
              )}
              role={contractError ? 'alert' : undefined}
            >
              {contractError ?? resolvedContract?.symbol}
            </p>
          )}
        </div>

        <DialogFooter className="flex-row items-center justify-between gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <Button
              size="sm"
              onClick={handleSave}
              disabled={isPriceLoading || resolvedContract === null}
            >
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
