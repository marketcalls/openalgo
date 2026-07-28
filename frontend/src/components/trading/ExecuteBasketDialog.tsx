import { CheckCircle2, Send, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
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
import type { StrategyLeg } from '@/lib/strategyMath'
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
  include: boolean
  symbol: string
  action: 'BUY' | 'SELL'
  segment: 'OPTION' | 'FUTURE'
  optionType?: 'CE' | 'PE'
  /** Lots the user buys/sells. Contract quantity = lots × lotSize. */
  lots: number
  /** Broker lot size (from the symbol / option-chain service). */
  lotSize: number
  price: number
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
  /**
   * Per-leg tick size, keyed by the leg's OpenAlgo symbol. Sourced from
   * the option-chain response (SymToken.tick_size in the DB). Missing
   * symbols fall back to 0.05, which is the NSE F&O default.
   */
  tickSizeBySymbol?: Record<string, number>
  apiKey: string
}

/** Decimal places implied by a tick (0.05 → 2, 0.0001 → 4, 0.5 → 1, 1 → 0). */
function tickDecimals(tick: number): number {
  if (!Number.isFinite(tick) || tick <= 0) return 2
  if (tick >= 1) return 0
  const s = tick.toString()
  const dot = s.indexOf('.')
  return dot === -1 ? 0 : s.length - dot - 1
}

/** Snap `value` to the nearest multiple of `tick` and strip binary drift. */
function roundToTick(value: number, tick = 0.05): number {
  if (!Number.isFinite(value) || value <= 0) return 0
  if (!Number.isFinite(tick) || tick <= 0) return value
  const decimals = tickDecimals(tick)
  return Number((Math.round(value / tick) * tick).toFixed(decimals))
}

export function ExecuteBasketDialog({
  open,
  onOpenChange,
  legs,
  exchange,
  strategyName,
  tickSizeBySymbol,
  apiKey,
}: ExecuteBasketDialogProps) {
  const activeLegs = useMemo(() => legs.filter((l) => l.active), [legs])
  const [rows, setRows] = useState<RowState[]>([])
  const [product, setProduct] = useState<ProductType>('NRML')
  const [pricetype, setPricetype] = useState<PriceType>('LIMIT')
  const [submitting, setSubmitting] = useState(false)
  const [results, setResults] = useState<BasketOrderResult[] | null>(null)

  // Seed rows whenever dialog opens or legs change.
  useEffect(() => {
    if (!open) return
    setResults(null)
    setProduct('NRML')
    setPricetype('LIMIT')
    setRows(
      activeLegs.map((leg) => {
        const tick = tickSizeBySymbol?.[leg.symbol] ?? 0.05
        return {
          legId: leg.id,
          include: true,
          symbol: leg.symbol,
          action: leg.side,
          segment: leg.segment,
          optionType: leg.optionType,
          lots: Math.max(1, Math.floor(leg.lots || 1)),
          lotSize: Math.max(1, Math.floor(leg.lotSize || 1)),
          price: roundToTick(leg.price || 0, tick),
          tickSize: tick,
        }
      })
    )
  }, [open, activeLegs, tickSizeBySymbol])

  const updateRow = (legId: string, patch: Partial<RowState>) =>
    setRows((prev) => prev.map((r) => (r.legId === legId ? { ...r, ...patch } : r)))

  const includedRows = rows.filter((r) => r.include)
  const canSubmit =
    !submitting && includedRows.length > 0 && strategyName.trim().length > 0 && !!apiKey

  const handleExecute = async () => {
    if (!canSubmit) return

    // Build payload per docs/prompt/services_documentation.md (BasketOrder).
    // Contract quantity = lots × lotSize — the broker API expects contracts.
    // Final tick-snap here in case the user hit Execute before blurring
    // a manually-edited price input.
    const orders: BasketOrderItem[] = includedRows.map((r) => ({
      symbol: r.symbol,
      exchange,
      action: r.action,
      quantity: Math.max(1, Math.floor(r.lots) * Math.max(1, r.lotSize)),
      pricetype,
      product,
      price: pricetype === 'LIMIT' ? roundToTick(r.price, r.tickSize) : 0,
      trigger_price: 0,
    }))

    if (pricetype === 'LIMIT') {
      const bad = orders.find((o) => !o.price || (o.price ?? 0) <= 0)
      if (bad) {
        showToast.error(`${bad.symbol}: LIMIT needs a valid price`)
        return
      }
    }

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
        <div className="flex items-end gap-4 rounded-lg border bg-muted/20 p-3">
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Product Type
            </Label>
            <div className="inline-flex h-9 w-full overflow-hidden rounded-md border bg-background">
              {PRODUCT_TYPES.map((p, idx) => (
                <button
                  key={p}
                  type="button"
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
            </div>
          </div>
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Price Type
            </Label>
            <div className="inline-flex h-9 w-full overflow-hidden rounded-md border bg-background">
              <button
                type="button"
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
            </div>
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
                            r.action === 'BUY' ? 'bg-emerald-500' : 'bg-rose-500'
                          )}
                        >
                          {r.action === 'BUY' ? 'B' : 'S'}
                        </span>
                        {r.segment === 'OPTION' && r.optionType && (
                          <span
                            className={cn(
                              'shrink-0 rounded px-1 py-0.5 text-[10px] font-bold text-white',
                              r.optionType === 'CE' ? 'bg-emerald-600' : 'bg-rose-600'
                            )}
                          >
                            {r.optionType}
                          </span>
                        )}
                        {r.segment === 'FUTURE' && (
                          <span className="shrink-0 rounded bg-sky-600 px-1 py-0.5 text-[10px] font-bold text-white">
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
                      min={0}
                      step={r.tickSize}
                      value={r.price}
                      onChange={(e) => updateRow(r.legId, { price: Number(e.target.value) || 0 })}
                      onBlur={(e) => {
                        const snapped = roundToTick(Number(e.target.value) || 0, r.tickSize)
                        updateRow(r.legId, { price: snapped })
                      }}
                      disabled={submitting || !!results || pricetype !== 'LIMIT' || !r.include}
                      placeholder={pricetype === 'MARKET' ? 'MKT' : '0.00'}
                      className="h-8 text-right font-mono text-xs"
                    />
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
