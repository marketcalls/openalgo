import { ListPlus, Minus, Plus, PlusCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { strikeMoneyness } from '@/lib/strategyMath'
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
  /** Common strike increment (e.g. 50 for NIFTY) — drives moneyness step labels. */
  strikeStep?: number
  onAdd: (draft: LegDraft) => void
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </span>
  )
}

export function ManualLegBuilder({
  expiries,
  futureExpiries,
  chain,
  selectedExpiry,
  atmStrike,
  strikeStep = 0,
  onAdd,
}: ManualLegBuilderProps) {
  const [segment, setSegment] = useState<LegDraftSegment>('OPTION')
  const [side, setSide] = useState<LegDraftSide>('BUY')
  const [expiry, setExpiry] = useState<string>(selectedExpiry)
  const [optionType, setOptionType] = useState<LegDraftType>('CE')
  const [strike, setStrike] = useState<number | undefined>(undefined)
  const [lots, setLots] = useState(1)

  useEffect(() => {
    if (atmStrike === null || !chain) return
    const strikeInChain =
      strike !== undefined && chain.some((s) => s.strike === strike)
    if (!strikeInChain) setStrike(atmStrike)
  }, [atmStrike, chain, strike])

  const availableExpiries = segment === 'FUTURE' ? futureExpiries : expiries

  useEffect(() => {
    if (availableExpiries.length === 0) {
      setExpiry('')
      return
    }
    if (!availableExpiries.includes(expiry)) {
      setExpiry(availableExpiries[0])
    }
  }, [availableExpiries, expiry])

  const strikeOptions = useMemo(() => {
    if (!chain) return []
    return chain.map((s) => s.strike)
  }, [chain])

  const liveLeg = useMemo(() => {
    if (segment !== 'OPTION' || !chain || strike === undefined) return null
    const row = chain.find((s) => s.strike === strike)
    if (!row) return null
    const rowSide = optionType === 'CE' ? row.ce : row.pe
    if (!rowSide) return null
    return { price: rowSide.ltp, symbol: rowSide.symbol }
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

  const currentMoneyness = strikeMoneyness(strike, atmStrike, strikeStep, optionType)

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* Header — icon + title only. Buy/Sell moved down next to Add. */}
      <div className="flex items-center justify-between border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-emerald-500/15 to-blue-500/15 text-emerald-600 dark:text-emerald-400">
            <ListPlus className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">Add a Position</h3>
            <p className="mt-1 text-[10px] text-muted-foreground">
              Build legs manually with custom strike, expiry and side
            </p>
          </div>
        </div>
        {liveLeg && (
          <div className="hidden items-center gap-2 text-[11px] sm:flex">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              LTP
              <span className="font-bold tabular-nums text-foreground">
                ₹{liveLeg.price.toFixed(2)}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Action row — everything inline so mouse travel is minimal. */}
      <div className="flex flex-wrap items-end gap-3 px-4 py-4">
        {/* Segment */}
        <div className="flex min-w-[120px] flex-col gap-1.5">
          <FieldLabel>Segment</FieldLabel>
          <Select value={segment} onValueChange={(v) => setSegment(v as LegDraftSegment)}>
            <SelectTrigger className="h-9 text-xs font-medium">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="OPTION">Options</SelectItem>
              <SelectItem value="FUTURE">Futures</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Expiry */}
        <div className="flex min-w-[140px] flex-col gap-1.5">
          <FieldLabel>Expiry</FieldLabel>
          <Select value={expiry} onValueChange={setExpiry}>
            <SelectTrigger className="h-9 text-xs font-medium">
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
            {/* Strike + inline moneyness */}
            <div className="flex min-w-[140px] flex-col gap-1.5">
              <FieldLabel>
                <span className="inline-flex items-center gap-1.5">
                  Strike
                  {currentMoneyness && (
                    <span
                      className={cn(
                        'rounded px-1 py-px text-[9px] font-bold uppercase tracking-wider normal-case',
                        currentMoneyness.kind === 'ATM' &&
                          'bg-amber-500/15 text-amber-700 dark:text-amber-400',
                        currentMoneyness.kind === 'ITM' &&
                          'bg-sky-500/15 text-sky-700 dark:text-sky-400',
                        currentMoneyness.kind === 'OTM' &&
                          'bg-muted text-muted-foreground'
                      )}
                    >
                      {currentMoneyness.label}
                    </span>
                  )}
                </span>
              </FieldLabel>
              <Select
                value={strike !== undefined ? String(strike) : ''}
                onValueChange={(v) => setStrike(Number(v))}
              >
                <SelectTrigger className="h-9 text-xs font-medium tabular-nums">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {strikeOptions.map((s) => {
                    const m = strikeMoneyness(s, atmStrike, strikeStep, optionType)
                    return (
                      <SelectItem key={s} value={String(s)}>
                        <span className="tabular-nums">{s}</span>
                        {m && (
                          <span
                            className={cn(
                              'ml-2 text-[9px] font-semibold uppercase tracking-wider',
                              m.kind === 'ATM' && 'text-amber-600 dark:text-amber-400',
                              m.kind === 'ITM' && 'text-sky-600 dark:text-sky-400',
                              m.kind === 'OTM' && 'text-muted-foreground'
                            )}
                          >
                            {m.label}
                          </span>
                        )}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            </div>

            {/* CE / PE */}
            <div className="flex flex-col gap-1.5">
              <FieldLabel>Type</FieldLabel>
              <div className="inline-flex h-9 overflow-hidden rounded-md border bg-background p-0.5">
                <button
                  type="button"
                  onClick={() => setOptionType('CE')}
                  className={cn(
                    'rounded-sm px-3 text-[11px] font-bold transition',
                    optionType === 'CE'
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  CE
                </button>
                <button
                  type="button"
                  onClick={() => setOptionType('PE')}
                  className={cn(
                    'rounded-sm px-3 text-[11px] font-bold transition',
                    optionType === 'PE'
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  PE
                </button>
              </div>
            </div>
          </>
        )}

        {/* Buy / Sell — now inline, right where mouse already is. */}
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Side</FieldLabel>
          <div className="inline-flex h-9 overflow-hidden rounded-md border bg-background p-0.5">
            <button
              type="button"
              onClick={() => setSide('BUY')}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'BUY'
                  ? 'bg-emerald-500 text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide('SELL')}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'SELL'
                  ? 'bg-rose-500 text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Sell
            </button>
          </div>
        </div>

        {/* Lot Qty */}
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Lot Qty</FieldLabel>
          <div className="inline-flex h-9 w-[120px] items-center overflow-hidden rounded-md border bg-background">
            <button
              type="button"
              onClick={() => setLots(Math.max(1, lots - 1))}
              className="flex h-full w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Decrease lots"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              type="number"
              min={1}
              value={lots}
              onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
              className="h-full w-full border-x bg-transparent text-center text-xs font-bold tabular-nums outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <button
              type="button"
              onClick={() => setLots(lots + 1)}
              className="flex h-full w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Increase lots"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Context-aware Add button — color + label mirror the selected side,
            so the visual intent matches what will be added. */}
        <div className="ml-auto flex flex-col gap-1.5">
          <FieldLabel>&nbsp;</FieldLabel>
          <Button
            size="sm"
            onClick={handleAdd}
            disabled={!canAdd}
            className={cn(
              'h-9 gap-1.5 px-4 text-xs font-bold uppercase tracking-wider transition',
              side === 'BUY'
                ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                : 'bg-rose-500 text-white hover:bg-rose-600'
            )}
          >
            <PlusCircle className="h-3.5 w-3.5" />
            {side === 'BUY' ? 'Add Buy' : 'Add Sell'}{' '}
            <span className="rounded bg-white/20 px-1.5 py-px text-[10px] font-bold tabular-nums">
              {side === 'BUY' ? '+' : '-'}
              {lots}x
            </span>
          </Button>
        </div>
      </div>

      {/* Live symbol footer (LTP was moved to header; keep symbol here). */}
      {liveLeg && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-2">
          <span className="text-[10px] text-muted-foreground sm:hidden">
            LTP
            <span className="ml-1 font-bold tabular-nums text-foreground">
              ₹{liveLeg.price.toFixed(2)}
            </span>
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">{liveLeg.symbol}</span>
        </div>
      )}
    </div>
  )
}
