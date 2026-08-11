import { CheckCircle2, Send, XCircle } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { type BasketOrderItem, type BasketOrderResult, tradingApi } from '@/api/trading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { isLegExecutable, type StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

/**
 * Basket execution dialog for the Strategy Builder.
 *
 * Minimal controls by design — per-leg rows show only Include / side /
 * symbol / qty / price. Product (NRML|MIS) and Pricetype (LIMIT|MKT) are
 * single global controls that stamp every leg. Strategy name is
 * read-only and framed by the parent. Exchange is whatever the parent
 * resolves — NFO, BFO, or any crypto code pass through unchanged.
 *
 * Symbol format and order constants follow docs/prompt/symbols.md and
 * docs/prompt/order-constants.md.
 */

type PriceType = 'LIMIT' | 'MARKET'
type ProductType = 'NRML' | 'MIS'

const PRODUCT_TYPES: ProductType[] = ['NRML', 'MIS']

interface RowState {
  legId: string
  contractKey: string
  include: boolean
  symbol: string
  action: 'BUY' | 'SELL'
  segment: 'OPTION' | 'FUTURE'
  optionType?: 'CE' | 'PE'
  /** Lots the user buys/sells. Contract quantity = lots × lotSize. */
  lots: number
  /** Broker lot size (from the symbol / option-chain service). */
  lotSize: number
  price: number | null
  tickSize: number
}

export interface ExecuteBasketDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  legs: StrategyLeg[]
  /** Exchange attached to every leg (NFO / BFO / crypto code). */
  exchange: string
  /** Read-only strategy name — auto-framed by the parent. */
  strategyName: string
  apiKey: string
}

function toScaledInteger(value: number): { coefficient: bigint; exponent: number } {
  const [significand, exponentText] = value.toString().toLowerCase().split('e')
  const decimalPoint = significand.indexOf('.')
  const fractionDigits = decimalPoint === -1 ? 0 : significand.length - decimalPoint - 1
  return {
    coefficient: BigInt(significand.replace('.', '')),
    exponent: (exponentText ? Number(exponentText) : 0) - fractionDigits,
  }
}

function scaledIntegerToNumber(coefficient: bigint, exponent: number): number {
  return Number(`${coefficient}e${exponent}`)
}

/** Snap `value` to the nearest multiple of `tick` with exact decimal half-up rounding. */
function roundToTick(value: number, tick: number): number | null {
  if (!Number.isFinite(value) || value <= 0) return null
  if (!Number.isFinite(tick) || tick <= 0) return null
  const valueParts = toScaledInteger(value)
  const tickParts = toScaledInteger(tick)
  let numerator = valueParts.coefficient
  let denominator = tickParts.coefficient
  if (valueParts.exponent > tickParts.exponent) {
    numerator *= 10n ** BigInt(valueParts.exponent - tickParts.exponent)
  } else if (tickParts.exponent > valueParts.exponent) {
    denominator *= 10n ** BigInt(tickParts.exponent - valueParts.exponent)
  }

  let multiples = numerator / denominator
  if ((numerator % denominator) * 2n >= denominator) multiples += 1n
  const rounded = scaledIntegerToNumber(multiples * tickParts.coefficient, tickParts.exponent)
  return Number.isFinite(rounded) && rounded > 0 ? rounded : null
}

function contractKey(leg: StrategyLeg): string {
  return [
    leg.id,
    leg.exchange ?? '',
    leg.symbol,
    leg.segment,
    leg.expiry,
    leg.strike ?? '',
    leg.optionType ?? '',
    leg.side,
  ].join('|')
}

function rowFromLeg(leg: StrategyLeg): RowState {
  if (!isLegExecutable(leg)) throw new Error('Rows require executable legs')
  return {
    legId: leg.id,
    contractKey: contractKey(leg),
    include: true,
    symbol: leg.symbol,
    action: leg.side,
    segment: leg.segment,
    optionType: leg.optionType,
    lots: leg.lots,
    lotSize: leg.lotSize,
    price: roundToTick(leg.price, leg.tickSize),
    tickSize: leg.tickSize,
  }
}

export function ExecuteBasketDialog({
  open,
  onOpenChange,
  legs,
  exchange,
  strategyName,
  apiKey,
}: ExecuteBasketDialogProps) {
  const executableLegs = useMemo(() => legs.filter(isLegExecutable), [legs])
  const [rows, setRows] = useState<RowState[]>([])
  const [product, setProduct] = useState<ProductType>('NRML')
  const [pricetype, setPricetype] = useState<PriceType>('LIMIT')
  const [submitting, setSubmitting] = useState(false)
  const [results, setResults] = useState<BasketOrderResult[] | null>(null)
  const wasOpenRef = useRef(false)

  // Reset only for a fresh open. While open, market updates reconcile by the
  // exact contract identity so edits and deselections are never silently lost.
  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false
      return
    }
    const isFreshOpen = !wasOpenRef.current
    if (isFreshOpen) {
      setResults(null)
      setProduct('NRML')
      setPricetype('LIMIT')
    }
    setRows((previous) => {
      if (isFreshOpen) return executableLegs.map(rowFromLeg)
      const previousByContract = new Map(previous.map((row) => [row.contractKey, row]))
      return executableLegs.map((leg) => {
        const key = contractKey(leg)
        const existing = previousByContract.get(key)
        if (!existing) return rowFromLeg(leg)
        return {
          ...existing,
          // These are broker-owned metadata, not user choices.
          lotSize: leg.lotSize,
          tickSize: leg.tickSize,
        }
      })
    })
    wasOpenRef.current = true
  }, [open, executableLegs])

  const updateRow = (legId: string, patch: Partial<RowState>) =>
    setRows((prev) => prev.map((r) => (r.legId === legId ? { ...r, ...patch } : r)))

  const includedRows = rows.filter((r) => r.include)
  const hasInvalidLimitPrice =
    pricetype === 'LIMIT' &&
    includedRows.some((r) => r.price === null || !Number.isFinite(r.price) || r.price <= 0)
  const canSubmit =
    !submitting &&
    includedRows.length > 0 &&
    strategyName.trim().length > 0 &&
    !!apiKey &&
    !hasInvalidLimitPrice

  const handleExecute = async () => {
    if (!canSubmit) return

    // Build payload per docs/prompt/services_documentation.md (BasketOrder).
    // Contract quantity = lots × lotSize — the broker API expects contracts.
    // Final tick-snap here in case the user hit Execute before blurring
    // a manually-edited price input.
    const normalizedRows = includedRows.map((row) => ({
      row,
      price: pricetype === 'LIMIT' ? roundToTick(row.price ?? 0, row.tickSize) : 0,
    }))
    if (pricetype === 'LIMIT') {
      const bad = normalizedRows.find(
        ({ price }) => price === null || !Number.isFinite(price) || price <= 0
      )
      if (bad) {
        updateRow(bad.row.legId, { price: null })
        showToast.error(`${bad.row.symbol}: LIMIT needs a valid price`)
        return
      }
    }
    const orders: BasketOrderItem[] = normalizedRows.map(({ row, price }) => ({
      symbol: row.symbol,
      exchange,
      action: row.action,
      quantity: row.lots * row.lotSize,
      pricetype,
      product,
      price: price ?? 0,
      trigger_price: 0,
    }))

    setSubmitting(true)
    try {
      const resp = await tradingApi.placeBasketOrder(apiKey, strategyName.trim(), orders)
      if (resp.status !== 'success') {
        showToast.error(resp.message || 'Basket order failed')
        setSubmitting(false)
        return
      }
      const resultList = resp.results ?? []
      setResults(resultList)
      const successCount = resultList.filter((r) => r.status === 'success').length
      const failCount = resultList.length - successCount
      if (failCount === 0) {
        showToast.success(`Basket placed: ${successCount}/${resultList.length} orders`)
        setTimeout(() => onOpenChange(false), 800)
      } else {
        showToast.error(`Basket partial: ${successCount} ok, ${failCount} failed`)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error'
      showToast.error(`Basket order error: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" /> Execute Basket Order
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Strategy</span>
            <span
              className="rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground"
              title={strategyName}
            >
              {strategyName}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">Exchange</span>
            <span className="rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground">
              {exchange}
            </span>
          </DialogDescription>
        </DialogHeader>

        {/* Global controls — compact inline row */}
        <div className="flex min-w-0 max-w-full items-end gap-4 rounded-lg border bg-muted/20 p-3">
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Product Type
            </Label>
            <fieldset
              aria-label="Product type"
              className="inline-flex h-9 w-full min-w-0 overflow-hidden rounded-md border bg-background"
            >
              {PRODUCT_TYPES.map((p, idx) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={product === p}
                  onClick={() => setProduct(p)}
                  disabled={submitting || !!results}
                  className={cn(
                    'flex-1 text-xs font-semibold transition-colors',
                    idx > 0 && 'border-l',
                    product === p
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted'
                  )}
                >
                  {p}
                </button>
              ))}
            </fieldset>
          </div>
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Price Type
            </Label>
            <fieldset
              aria-label="Price type"
              className="inline-flex h-9 w-full min-w-0 overflow-hidden rounded-md border bg-background"
            >
              <button
                type="button"
                aria-pressed={pricetype === 'LIMIT'}
                onClick={() => setPricetype('LIMIT')}
                disabled={submitting || !!results}
                className={cn(
                  'flex-1 text-xs font-semibold transition-colors',
                  pricetype === 'LIMIT'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted'
                )}
              >
                LIMIT
              </button>
              <button
                type="button"
                aria-pressed={pricetype === 'MARKET'}
                onClick={() => setPricetype('MARKET')}
                disabled={submitting || !!results}
                className={cn(
                  'flex-1 border-l text-xs font-semibold transition-colors',
                  pricetype === 'MARKET'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted'
                )}
              >
                MKT
              </button>
            </fieldset>
          </div>
        </div>

        {/* Leg rows — compact rectangular grid. Symbol + side badges share
            one flex cell so the OpenAlgo symbol has the maximum possible
            width and wraps rather than truncates on narrow viewports. */}
        <div className="overflow-hidden rounded-lg border">
          {/* Header */}
          <div className="grid grid-cols-[32px_1fr_72px_104px] items-center gap-2 border-b bg-muted/30 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <span className="text-center">Use</span>
            <span>Symbol</span>
            <span className="text-right">Lots</span>
            <span className="text-right">Price</span>
          </div>
          {/* Body */}
          <div className="max-h-[40vh] overflow-y-auto">
            {rows.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                No active legs in the strategy.
              </div>
            ) : (
              rows.map((r, idx) => {
                const result = results?.find((x) => x.symbol === r.symbol)
                const priceErrorId = `basket-limit-price-error-${idx}`
                return (
                  <div
                    key={r.legId}
                    className={cn(
                      'grid grid-cols-[32px_1fr_72px_104px] items-start gap-2 px-3 py-2 text-sm',
                      idx !== rows.length - 1 && 'border-b',
                      !r.include && 'opacity-50',
                      result?.status === 'success' && 'bg-emerald-500/5',
                      result?.status === 'error' && 'bg-rose-500/5'
                    )}
                  >
                    {/* Include */}
                    <div className="flex h-8 items-center justify-center">
                      <Checkbox
                        aria-label={`Include ${r.symbol}`}
                        checked={r.include}
                        onCheckedChange={(v) => updateRow(r.legId, { include: v === true })}
                        disabled={submitting || !!results}
                      />
                    </div>

                    {/* Symbol cell — side/type badges inline, full OpenAlgo
                        symbol wraps onto a second line if needed (break-all)
                        instead of truncating. */}
                    <div className="min-w-0 flex-col">
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <span
                          className={cn(
                            'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold text-white',
                            r.action === 'BUY' ? 'bg-emerald-700' : 'bg-rose-700'
                          )}
                        >
                          {r.action === 'BUY' ? 'B' : 'S'}
                        </span>
                        {r.segment === 'OPTION' && r.optionType && (
                          <span
                            className={cn(
                              'shrink-0 rounded px-1 py-0.5 text-[10px] font-bold text-white',
                              r.optionType === 'CE' ? 'bg-emerald-700' : 'bg-rose-700'
                            )}
                          >
                            {r.optionType}
                          </span>
                        )}
                        {r.segment === 'FUTURE' && (
                          <span className="shrink-0 rounded bg-sky-700 px-1 py-0.5 text-[10px] font-bold text-white">
                            FUT
                          </span>
                        )}
                        <span
                          className="break-all font-mono text-xs font-semibold leading-tight"
                          title={r.symbol}
                        >
                          {r.symbol}
                        </span>
                      </div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground">
                        Lot size: {r.lotSize} · Qty: {r.lots * r.lotSize}
                      </div>
                      {result && (
                        <div className="mt-0.5 flex items-center gap-1 text-[10px]">
                          {result.status === 'success' ? (
                            <>
                              <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                              <span className="truncate text-emerald-600 dark:text-emerald-400">
                                #{result.orderid}
                              </span>
                            </>
                          ) : (
                            <>
                              <XCircle className="h-3 w-3 text-rose-500" />
                              <span
                                className="truncate text-rose-600 dark:text-rose-400"
                                title={result.message}
                              >
                                {result.message || 'Failed'}
                              </span>
                            </>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Lots — user edits lots; contract qty = lots × lotSize
                        is computed at payload build time. */}
                    <Input
                      type="number"
                      aria-label={`Lots for ${r.symbol}`}
                      min={1}
                      step={1}
                      value={r.lots}
                      onChange={(e) =>
                        updateRow(r.legId, {
                          lots: Math.max(1, Math.floor(Number(e.target.value) || 1)),
                        })
                      }
                      disabled={submitting || !!results || !r.include}
                      className="h-8 text-right font-mono text-xs"
                    />

                    {/* Price (disabled for MARKET) — snapped to the leg's
                        tick size on blur so users never see floating-point
                        drift like 185.85000000000002. */}
                    <Input
                      type="number"
                      aria-label={`Limit price for ${r.symbol}`}
                      aria-invalid={r.price === null}
                      aria-describedby={r.price === null ? priceErrorId : undefined}
                      min={0}
                      step={r.tickSize}
                      value={r.price ?? ''}
                      onChange={(e) => updateRow(r.legId, { price: Number(e.target.value) || 0 })}
                      onBlur={(e) => {
                        const snapped = roundToTick(Number(e.target.value) || 0, r.tickSize)
                        updateRow(r.legId, { price: snapped })
                      }}
                      disabled={submitting || !!results || pricetype !== 'LIMIT' || !r.include}
                      placeholder={pricetype === 'MARKET' ? 'MKT' : '0.00'}
                      className="h-8 text-right font-mono text-xs"
                    />
                    {r.price === null && (
                      <span
                        id={priceErrorId}
                        role="alert"
                        className="text-[10px] text-rose-700 dark:text-rose-400"
                      >
                        {r.symbol}: price is outside the supported tick range
                      </span>
                    )}
                  </div>
                )
              })
            )}
          </div>
        </div>

        <DialogFooter className="flex-row items-center justify-between sm:justify-between">
          <div className="text-xs text-muted-foreground">
            {includedRows.length} of {rows.length} legs selected
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              {results ? 'Close' : 'Cancel'}
            </Button>
            <Button onClick={handleExecute} disabled={!canSubmit || !!results} className="gap-1.5">
              <Send className="h-3.5 w-3.5" />
              {submitting ? 'Placing…' : `Execute (${includedRows.length})`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
