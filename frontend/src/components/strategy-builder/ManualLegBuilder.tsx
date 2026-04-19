import { Minus, Plus, PlusCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { OptionStrike } from '@/types/option-chain'

export type LegDraftSegment = 'OPTION' | 'FUTURE'
export type LegDraftSide = 'BUY' | 'SELL'
export type LegDraftType = 'CE' | 'PE'

export interface LegDraft {
  segment: LegDraftSegment
  side: LegDraftSide
  expiry: string
  strike?: number
  optionType?: LegDraftType
  lots: number
  price: number
  iv: number
}

export interface ManualLegBuilderProps {
  expiries: string[]
  futureExpiries: string[]
  chain: OptionStrike[] | null
  selectedExpiry: string
  atmStrike: number | null
  onAdd: (draft: LegDraft) => void
}

export function ManualLegBuilder({
  expiries,
  futureExpiries,
  chain,
  selectedExpiry,
  atmStrike,
  onAdd,
}: ManualLegBuilderProps) {
  const [segment, setSegment] = useState<LegDraftSegment>('OPTION')
  const [side, setSide] = useState<LegDraftSide>('BUY')
  const [expiry, setExpiry] = useState<string>(selectedExpiry)
  const [optionType, setOptionType] = useState<LegDraftType>('CE')
  const [strike, setStrike] = useState<number | undefined>(undefined)
  const [lots, setLots] = useState(1)

  // Default the strike to the live ATM whenever the chain loads a new ATM —
  // either on first render, or when the user switches underlying/expiry so the
  // previously-selected strike is no longer in the fresh chain.
  useEffect(() => {
    if (atmStrike === null || !chain) return
    const strikeInChain =
      strike !== undefined && chain.some((s) => s.strike === strike)
    if (!strikeInChain) setStrike(atmStrike)
  }, [atmStrike, chain, strike])

  // Which expiry list to present depends on the selected segment.
  const availableExpiries = segment === 'FUTURE' ? futureExpiries : expiries

  // Keep expiry sane when segment switches.
  useEffect(() => {
    if (availableExpiries.length === 0) {
      setExpiry('')
      return
    }
    if (!availableExpiries.includes(expiry)) {
      setExpiry(availableExpiries[0])
    }
  }, [availableExpiries, expiry])

  // Pull strike list and LTP for the chosen strike from the live chain
  const strikeOptions = useMemo(() => {
    if (!chain) return []
    return chain.map((s) => s.strike)
  }, [chain])

  const liveLeg = useMemo(() => {
    if (segment !== 'OPTION' || !chain || strike === undefined) return null
    const row = chain.find((s) => s.strike === strike)
    if (!row) return null
    const side = optionType === 'CE' ? row.ce : row.pe
    if (!side) return null
    return { price: side.ltp, symbol: side.symbol }
  }, [chain, strike, optionType, segment])

  const canAdd =
    segment === 'FUTURE'
      ? expiry && lots > 0
      : expiry && optionType && strike !== undefined && lots > 0

  const handleAdd = () => {
    if (!canAdd) return
    onAdd({
      segment,
      side,
      expiry,
      strike: segment === 'OPTION' ? strike : undefined,
      optionType: segment === 'OPTION' ? optionType : undefined,
      lots,
      price: liveLeg?.price ?? 0,
      iv: 0,
    })
  }

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Add Position</h3>
        <div className="flex overflow-hidden rounded-md border">
          <button
            onClick={() => setSide('BUY')}
            className={cn(
              'px-3 py-1 text-xs font-semibold transition',
              side === 'BUY'
                ? 'bg-emerald-500 text-white'
                : 'bg-transparent text-muted-foreground hover:bg-muted'
            )}
          >
            Buy
          </button>
          <button
            onClick={() => setSide('SELL')}
            className={cn(
              'px-3 py-1 text-xs font-semibold transition',
              side === 'SELL'
                ? 'bg-rose-500 text-white'
                : 'bg-transparent text-muted-foreground hover:bg-muted'
            )}
          >
            Sell
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-[140px] flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Segment</label>
          <Select value={segment} onValueChange={(v) => setSegment(v as LegDraftSegment)}>
            <SelectTrigger className="h-9 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="OPTION">Options</SelectItem>
              <SelectItem value="FUTURE">Futures</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex min-w-[170px] flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Expiry</label>
          <Select value={expiry} onValueChange={setExpiry}>
            <SelectTrigger className="h-9 text-xs">
              <SelectValue placeholder={availableExpiries.length === 0 ? 'None' : 'Select'} />
            </SelectTrigger>
            <SelectContent>
              {availableExpiries.map((ex) => (
                <SelectItem key={ex} value={ex}>
                  {ex}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {segment === 'OPTION' && (
          <>
            <div className="flex min-w-[140px] flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground">Strike</label>
              <Select
                value={strike !== undefined ? String(strike) : ''}
                onValueChange={(v) => setStrike(Number(v))}
              >
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {strikeOptions.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex min-w-[90px] flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground">Type</label>
              <Select value={optionType} onValueChange={(v) => setOptionType(v as LegDraftType)}>
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="CE">CE</SelectItem>
                  <SelectItem value="PE">PE</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-[11px] font-medium text-muted-foreground">Lot Qty</label>
          <div className="inline-flex h-9 w-[112px] items-center overflow-hidden rounded-md border">
            <button
              type="button"
              onClick={() => setLots(Math.max(1, lots - 1))}
              className="flex h-full w-8 items-center justify-center text-muted-foreground hover:bg-muted"
              aria-label="Decrease lots"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              type="number"
              min={1}
              value={lots}
              onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
              className="h-full w-12 border-x bg-transparent text-center text-xs font-semibold tabular-nums outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <button
              type="button"
              onClick={() => setLots(lots + 1)}
              className="flex h-full w-8 items-center justify-center text-muted-foreground hover:bg-muted"
              aria-label="Increase lots"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          {liveLeg && (
            <>
              <span>
                LTP:{' '}
                <span className="font-semibold text-foreground">₹{liveLeg.price.toFixed(2)}</span>
              </span>
              <span className="font-mono text-[11px]">{liveLeg.symbol}</span>
            </>
          )}
        </div>
        <Button size="sm" onClick={handleAdd} disabled={!canAdd} className="h-8 text-xs">
          <PlusCircle className="mr-1.5 h-3.5 w-3.5" />
          Add Position
        </Button>
      </div>
    </div>
  )
}
