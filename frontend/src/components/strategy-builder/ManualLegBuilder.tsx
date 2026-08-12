import { ListPlus, Minus, Plus, PlusCircle } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  type ListedOptionChainResponse,
  normalizeExpiryCode,
  type ResolvedLegMarket,
  resolveOptionContract,
} from '@/lib/strategyContracts'
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
  symbol: string
  exchange: string
  expiryTs: number | null
  lotSize: number
  tickSize: number
  contractValid: true
  marketPrice: number
  referenceUnderlying: number
  forwardPrice: number | null
  greeks: ResolvedLegMarket['greeks']
}

export type ResolveLegContract = (
  expiry: string,
  segment: LegDraftSegment,
  strike?: number,
  optionType?: LegDraftType
) => Promise<ResolvedLegMarket | null>

export type ResolveOptionChain = (expiry: string) => Promise<ListedOptionChainResponse | null>

export interface ManualLegBuilderProps {
  expiries: string[]
  futureExpiries: string[]
  chain: OptionStrike[] | null
  /** Current live chain, used only to refresh an already-resolved matching option in place. */
  liveChain: ListedOptionChainResponse | null
  selectedExpiry: string
  atmStrike: number | null
  /** Common strike increment (e.g. 50 for NIFTY) — drives moneyness step labels. */
  strikeStep?: number
  resolveContract: ResolveLegContract
  resolveOptionChain?: ResolveOptionChain
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
  liveChain,
  selectedExpiry,
  atmStrike,
  strikeStep = 0,
  resolveContract,
  resolveOptionChain,
  onAdd,
}: ManualLegBuilderProps) {
  const [segment, setSegment] = useState<LegDraftSegment>('OPTION')
  const [side, setSide] = useState<LegDraftSide>('BUY')
  const [expiry, setExpiry] = useState<string>(selectedExpiry)
  const [optionType, setOptionType] = useState<LegDraftType>('CE')
  const [strike, setStrike] = useState<number | undefined>(undefined)
  const [lots, setLots] = useState(1)
  const [resolvedContract, setResolvedContract] = useState<ResolvedLegMarket | null>(null)
  const [contractError, setContractError] = useState<string | null>(null)
  const [isResolving, setIsResolving] = useState(false)
  const [resolvedOptionChain, setResolvedOptionChain] = useState<ListedOptionChainResponse | null>(
    null
  )
  const [isChainResolving, setIsChainResolving] = useState(false)
  const [chainError, setChainError] = useState<string | null>(null)
  const resolveGenerationRef = useRef(0)
  const chainGenerationRef = useRef(0)
  const liveChainRef = useRef(liveChain)
  liveChainRef.current = liveChain
  const liveChainIdentity = liveChain
    ? `${liveChain.status}:${normalizeExpiryCode(liveChain.expiry_date)}`
    : ''

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

  useEffect(() => {
    const generation = ++chainGenerationRef.current
    setChainError(null)
    if (segment !== 'OPTION' || !expiry || !resolveOptionChain) {
      setResolvedOptionChain(null)
      setIsChainResolving(false)
      return
    }
    const currentLiveChain = liveChainRef.current
    if (
      liveChainIdentity === `success:${normalizeExpiryCode(expiry)}` &&
      currentLiveChain?.status === 'success' &&
      normalizeExpiryCode(currentLiveChain.expiry_date) === normalizeExpiryCode(expiry)
    ) {
      setResolvedOptionChain(currentLiveChain)
      setIsChainResolving(false)
      return
    }

    setResolvedOptionChain(null)
    setIsChainResolving(true)
    void resolveOptionChain(expiry)
      .then((response) => {
        if (generation !== chainGenerationRef.current) return
        if (
          response === null ||
          normalizeExpiryCode(response.expiry_date) !== normalizeExpiryCode(expiry)
        ) {
          setChainError('Option chain is not available for this expiry')
          return
        }
        setResolvedOptionChain(response)
      })
      .catch(() => {
        if (generation === chainGenerationRef.current) {
          setChainError('Unable to load strikes for this expiry')
        }
      })
      .finally(() => {
        if (generation === chainGenerationRef.current) setIsChainResolving(false)
      })
  }, [expiry, liveChainIdentity, resolveOptionChain, segment])

  const matchingResolvedChain =
    resolvedOptionChain &&
    normalizeExpiryCode(resolvedOptionChain.expiry_date) === normalizeExpiryCode(expiry)
      ? resolvedOptionChain
      : null
  const matchingLiveChain =
    liveChain && normalizeExpiryCode(liveChain.expiry_date) === normalizeExpiryCode(expiry)
      ? liveChain
      : null
  const selectedChain = matchingLiveChain ?? matchingResolvedChain
  const selectionStrikes =
    selectedChain?.chain ??
    (!resolveOptionChain || normalizeExpiryCode(expiry) === normalizeExpiryCode(selectedExpiry)
      ? chain
      : null)
  const selectionAtmStrike = selectedChain?.atm_strike ?? atmStrike
  const hasListedSelection =
    strike !== undefined && Boolean(selectionStrikes?.some((item) => item.strike === strike))

  useEffect(() => {
    if (selectionAtmStrike === null || !selectionStrikes) return
    const strikeInChain =
      strike !== undefined && selectionStrikes.some((item) => item.strike === strike)
    if (!strikeInChain) setStrike(selectionAtmStrike)
  }, [selectionAtmStrike, selectionStrikes, strike])

  const strikeOptions = useMemo(() => {
    if (!selectionStrikes) return []
    return selectionStrikes.map((item) => item.strike)
  }, [selectionStrikes])

  useEffect(() => {
    const generation = ++resolveGenerationRef.current
    setResolvedContract(null)
    setContractError(null)

    const hasSelection =
      Boolean(expiry) &&
      availableExpiries.includes(expiry) &&
      (segment === 'FUTURE' || hasListedSelection)
    if (!hasSelection) {
      setIsResolving(false)
      return
    }

    setIsResolving(true)
    void resolveContract(expiry, segment, strike, segment === 'OPTION' ? optionType : undefined)
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
        if (generation === resolveGenerationRef.current) setIsResolving(false)
      })
  }, [availableExpiries, expiry, hasListedSelection, optionType, resolveContract, segment, strike])

  // Selection changes belong to the async resolver above. Live ticks are a
  // different state transition: refresh only an already-resolved option whose
  // canonical identity still matches, without clearing it, incrementing the
  // resolver generation, or issuing another request. Far expiries and futures
  // deliberately ignore active-chain ticks.
  useEffect(() => {
    if (
      segment !== 'OPTION' ||
      strike === undefined ||
      liveChain?.status !== 'success' ||
      normalizeExpiryCode(liveChain.expiry_date) !== normalizeExpiryCode(expiry)
    ) {
      return
    }
    const refreshed = resolveOptionContract(liveChain, optionType, strike)
    if (refreshed === null) return
    setResolvedContract((current) => {
      if (
        current === null ||
        current.symbol !== refreshed.symbol ||
        current.exchange !== refreshed.exchange ||
        normalizeExpiryCode(current.expiry) !== normalizeExpiryCode(refreshed.expiry)
      ) {
        return current
      }
      return refreshed
    })
  }, [expiry, liveChain, optionType, segment, strike])

  const canAdd = Boolean(
    resolvedContract && !isResolving && !isChainResolving && !chainError && lots > 0
  )
  const contractErrorId = 'manual-leg-contract-error'

  const handleAdd = () => {
    if (!canAdd) return
    if (!resolvedContract) return
    onAdd({
      segment,
      side,
      expiry,
      strike: segment === 'OPTION' ? strike : undefined,
      optionType: segment === 'OPTION' ? optionType : undefined,
      lots,
      price: resolvedContract.marketPrice,
      iv: resolvedContract.iv,
      symbol: resolvedContract.symbol,
      exchange: resolvedContract.exchange,
      expiryTs: resolvedContract.expiryTs,
      lotSize: resolvedContract.lotSize,
      tickSize: resolvedContract.tickSize,
      contractValid: resolvedContract.contractValid,
      marketPrice: resolvedContract.marketPrice,
      referenceUnderlying: resolvedContract.referenceUnderlying,
      forwardPrice: resolvedContract.forwardPrice,
      greeks: resolvedContract.greeks,
    })
  }

  const currentMoneyness = strikeMoneyness(strike, selectionAtmStrike, strikeStep, optionType)

  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-xl border bg-card shadow-sm">
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
        {resolvedContract && (
          <div className="hidden items-center gap-2 text-[11px] sm:flex">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              LTP
              <span className="font-bold tabular-nums text-foreground">
                ₹{resolvedContract.marketPrice.toFixed(2)}
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
            <SelectTrigger
              aria-label="Segment"
              aria-invalid={contractError !== null}
              aria-describedby={contractError ? contractErrorId : undefined}
              className="h-9 text-xs font-medium"
            >
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
            <SelectTrigger
              aria-label="Expiry"
              aria-invalid={contractError !== null}
              aria-describedby={contractError ? contractErrorId : undefined}
              className="h-9 text-xs font-medium"
            >
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
                        currentMoneyness.kind === 'OTM' && 'bg-muted text-muted-foreground'
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
                <SelectTrigger
                  aria-label="Strike"
                  aria-invalid={contractError !== null}
                  aria-describedby={contractError ? contractErrorId : undefined}
                  className="h-9 text-xs font-medium tabular-nums"
                >
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {strikeOptions.map((s) => {
                    const m = strikeMoneyness(s, selectionAtmStrike, strikeStep, optionType)
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
              <fieldset
                aria-label="Option type"
                aria-describedby={contractError ? contractErrorId : undefined}
                className="inline-flex h-9 min-w-0 overflow-hidden rounded-md border bg-background p-0.5"
              >
                <button
                  type="button"
                  onClick={() => setOptionType('CE')}
                  aria-pressed={optionType === 'CE'}
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
                  aria-pressed={optionType === 'PE'}
                  className={cn(
                    'rounded-sm px-3 text-[11px] font-bold transition',
                    optionType === 'PE'
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  PE
                </button>
              </fieldset>
            </div>
          </>
        )}

        {/* Buy / Sell — now inline, right where mouse already is. */}
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Side</FieldLabel>
          <fieldset
            aria-label="Trade side"
            className="inline-flex h-9 min-w-0 overflow-hidden rounded-md border bg-background p-0.5"
          >
            <button
              type="button"
              onClick={() => setSide('BUY')}
              aria-pressed={side === 'BUY'}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'BUY'
                  ? 'bg-emerald-700 text-white shadow-sm dark:bg-emerald-600'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide('SELL')}
              aria-pressed={side === 'SELL'}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'SELL'
                  ? 'bg-rose-700 text-white shadow-sm dark:bg-rose-600'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Sell
            </button>
          </fieldset>
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
              aria-label="Position lot quantity"
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
                ? 'bg-emerald-700 text-white hover:bg-emerald-800 dark:bg-emerald-600 dark:hover:bg-emerald-700'
                : 'bg-rose-700 text-white hover:bg-rose-800 dark:bg-rose-600 dark:hover:bg-rose-700'
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

      {(isResolving || isChainResolving || contractError || chainError) && (
        <div
          id={contractError || chainError ? contractErrorId : undefined}
          className={cn(
            'border-t px-4 py-2 text-[11px]',
            contractError || chainError ? 'text-destructive' : 'text-muted-foreground'
          )}
          role={contractError || chainError ? 'alert' : 'status'}
        >
          {contractError ??
            chainError ??
            (isChainResolving ? 'Loading expiry strikes…' : 'Resolving listed contract…')}
        </div>
      )}

      {/* Live symbol footer (LTP was moved to header; keep symbol here). */}
      {resolvedContract && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-2">
          <span className="text-[10px] text-muted-foreground sm:hidden">
            LTP
            <span className="ml-1 font-bold tabular-nums text-foreground">
              ₹{resolvedContract.marketPrice.toFixed(2)}
            </span>
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {resolvedContract.symbol}
          </span>
        </div>
      )}
    </div>
  )
}
