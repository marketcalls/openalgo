// components/flow/panels/MarginPositionsFields.tsx
// Basket editor for the Margin Calculator node's `positions`.
//
// The node stores the basket as a JSON string because the backend interpolates
// and parses it before handing the array to services/margin_service
// (flow_executor_service._parse_margin_positions). That storage format is
// unchanged here - only the editing surface is. Parsing, validation,
// serialization and lot arithmetic live in @/lib/flow/marginPositions so they
// can be tested without mounting React; this file owns network state and
// rendering only.

import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { flowQueryKeys, getSymbolLotSizes, type LotSizeMap, type SymbolRef } from '@/api/flow'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  defaultProductForExchange,
  EXCHANGES,
  ORDER_ACTIONS,
  PRICE_TYPES,
  PRODUCT_TYPES,
} from '@/lib/flow/constants'
import {
  EMPTY_LEG,
  hasVariableReference,
  type LegProblems,
  LOT_TRADED_EXCHANGES,
  lotKey,
  MAX_LEGS,
  type MarginLeg,
  NEEDS_PRICE,
  NEEDS_TRIGGER,
  parseLegs,
  roundUpToLot,
  serializeLegs,
  unitsToLots,
  validateBasket,
  validateLeg,
} from '@/lib/flow/marginPositions'
import { cn } from '@/lib/utils'

interface MarginPositionsFieldsProps {
  /** Raw `positionsJson` string as stored on the node. */
  value: string
  onChange: (raw: string) => void
}

/** How long the symbol must stay unchanged before a lookup is issued. Long
 * enough that ordinary typing produces one request, short enough not to feel
 * laggy once the user stops. */
const LOOKUP_DEBOUNCE_MS = 350

function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return settled
}

/** State of one leg's lot-size lookup. `failed` is deliberately distinct from
 * `resolved` with a null size - one is retryable, the other is a fact about the
 * master contract. */
type LotState =
  | { kind: 'not-applicable' }
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'resolved'; lotSize: number | null }

export function MarginPositionsFields({ value, onChange }: MarginPositionsFieldsProps) {
  // Memoized on the raw string, not called inline: an unmemoized parse returns
  // a fresh array every render, which made every downstream useMemo recompute
  // and left the debounce below rescheduling itself forever.
  const { legs, error } = useMemo(() => parseLegs(value), [value])
  const [jsonMode, setJsonMode] = useState(false)

  // Malformed JSON, or a {{variable}} basket, has no field representation -
  // switching to fields would silently discard whatever is in there. A template
  // can still be well-formed JSON, so the variable check is separate from the
  // parse error rather than folded into it.
  const templated = hasVariableReference(value)
  const showJson = jsonMode || error !== null || templated

  // One lookup for the whole basket. Per-leg queries turned a 50-leg import
  // into 50 requests on open.
  const refs = useMemo<SymbolRef[]>(() => {
    const seen = new Set<string>()
    const out: SymbolRef[] = []
    for (const leg of legs) {
      const symbol = leg.symbol.trim().toUpperCase()
      if (!symbol || !LOT_TRADED_EXCHANGES.has(leg.exchange)) continue
      const key = lotKey(symbol, leg.exchange)
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ symbol, exchange: leg.exchange })
    }
    return out.slice(0, MAX_LEGS)
  }, [legs])

  // Debounce a primitive rather than the array. An array restarts the timer on
  // every render because its identity changes; a string only changes when the
  // set of contracts does, so editing a quantity or a price never reschedules
  // a lookup.
  const refKey = refs
    .map((r) => lotKey(r.symbol, r.exchange))
    .sort()
    .join('|')
  const settledKey = useDebounced(refKey, LOOKUP_DEBOUNCE_MS)
  const settledRefs = useMemo<SymbolRef[]>(() => {
    if (!settledKey) return []
    return settledKey.split('|').map((key) => {
      const split = key.indexOf(':')
      return { exchange: key.slice(0, split), symbol: key.slice(split + 1) }
    })
  }, [settledKey])

  // Lot sizes already resolved while this panel has been open. A lot size is a
  // property of the contract, not of the basket that asked for it, so this is
  // keyed per contract rather than per basket. Held in a ref rather than as
  // individual query entries because those have no observer and are evicted on
  // the cache's own schedule - the reuse would then depend on GC timing.
  const resolved = useRef(new Map<string, number | null>())

  const lotQuery = useQuery({
    queryKey: flowQueryKeys.symbolLotSizes(settledKey ? settledKey.split('|') : []),
    queryFn: async () => {
      // Ask only for contracts never resolved before. Adding one leg to a
      // 50-leg basket changes this query's key, so without this the whole
      // basket would go back over the wire to learn a single lot size.
      const missing = settledRefs.filter((r) => !resolved.current.has(lotKey(r.symbol, r.exchange)))
      if (missing.length) {
        const fetched = await getSymbolLotSizes(missing)
        for (const r of missing) {
          const key = lotKey(r.symbol, r.exchange)
          // Absent from the response means the endpoint did not echo the pair,
          // which is the same answer as a contract with no lot size.
          resolved.current.set(key, key in fetched ? fetched[key] : null)
        }
      }
      const merged: LotSizeMap = {}
      for (const r of settledRefs) {
        const key = lotKey(r.symbol, r.exchange)
        merged[key] = resolved.current.get(key) ?? null
      }
      return merged
    },
    enabled: settledRefs.length > 0,
    // Lot sizes change only on a contract revision, not within a session.
    staleTime: 1000 * 60 * 60,
  })

  const lotState = (leg: MarginLeg): LotState => {
    const symbol = leg.symbol.trim().toUpperCase()
    if (!symbol || !LOT_TRADED_EXCHANGES.has(leg.exchange)) return { kind: 'not-applicable' }
    if (lotQuery.isError) return { kind: 'failed' }
    const map: LotSizeMap = lotQuery.data ?? {}
    const key = lotKey(symbol, leg.exchange)
    if (!(key in map)) return { kind: 'loading' }
    return { kind: 'resolved', lotSize: map[key] }
  }

  const update = (index: number, patch: Partial<MarginLeg>) => {
    onChange(serializeLegs(legs.map((leg, i) => (i === index ? { ...leg, ...patch } : leg))))
  }
  const addLeg = () => onChange(serializeLegs([...legs, { ...EMPTY_LEG, extra: {} }]))
  const removeLeg = (index: number) => onChange(serializeLegs(legs.filter((_, i) => i !== index)))

  const basketProblems = showJson ? [] : validateBasket(legs)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs" id="margin-positions-label">
          Positions
        </Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[10px]"
          // Field mode cannot represent either case, so offering the switch
          // would promise an edit that silently discards the basket.
          disabled={templated || error !== null}
          title={
            templated
              ? 'A basket using {{variable}} references can only be edited as JSON'
              : error !== null
                ? 'Fix the JSON before switching to fields'
                : undefined
          }
          onClick={() => setJsonMode((m) => !m)}
        >
          {showJson ? 'Use fields' : 'Edit as JSON'}
        </Button>
      </div>

      {showJson ? (
        <div className="space-y-2">
          <Textarea
            aria-label="Positions JSON"
            aria-invalid={error !== null}
            aria-describedby="margin-json-help"
            className="min-h-[100px] font-mono text-xs"
            placeholder={
              '[{"symbol": "NIFTY25DEC25FUT", "exchange": "NFO", "action": "BUY", "quantity": "75", "product": "NRML", "pricetype": "MARKET", "price": "0"}]'
            }
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          {error ? (
            <p id="margin-json-help" className="text-[10px] text-destructive">
              {error}
            </p>
          ) : templated ? (
            <p id="margin-json-help" className="text-[10px] text-muted-foreground">
              This basket uses {'{{variable}}'} references, which are interpolated before the JSON
              is parsed at run time. Field editing is unavailable so the references are not lost.
            </p>
          ) : (
            <p id="margin-json-help" className="text-[10px] text-muted-foreground">
              Every leg needs symbol, exchange, action, quantity, product and pricetype. Use this
              view for {'{{variable}}'} references, which are interpolated before the JSON is
              parsed.
            </p>
          )}
        </div>
      ) : (
        <>
          {legs.length === 0 ? (
            <p className="text-[10px] text-muted-foreground">
              No positions yet. Margin is estimated for the basket as a whole.
            </p>
          ) : (
            legs.map((leg, index) => (
              <LegRow
                // Legs have no stable id and can be reordered only by delete,
                // so the index is the identity here.
                key={index}
                leg={leg}
                index={index}
                lot={lotState(leg)}
                onRetryLookup={() => lotQuery.refetch()}
                onUpdate={(patch) => update(index, patch)}
                onRemove={() => removeLeg(index)}
              />
            ))
          )}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 w-full text-xs"
            disabled={legs.length >= MAX_LEGS}
            onClick={addLeg}
          >
            <Plus className="mr-1 h-3 w-3" />
            Add Position
          </Button>
          {basketProblems.length > 0 && (
            <ul className="space-y-0.5">
              {basketProblems.map((problem) => (
                <li key={problem} className="text-[10px] text-destructive">
                  {problem}
                </li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-muted-foreground">
            Up to {MAX_LEGS} legs. Margin is estimated for the basket as a whole, so offsetting legs
            get the hedged requirement.
          </p>
        </>
      )}
    </div>
  )
}

interface LegRowProps {
  leg: MarginLeg
  index: number
  lot: LotState
  onRetryLookup: () => void
  onUpdate: (patch: Partial<MarginLeg>) => void
  onRemove: () => void
}

/**
 * The product patch that goes with a leg's new exchange.
 *
 * margin_service requires a product on every leg, so unlike a node this row
 * cannot store "no choice yet" and let the exchange decide at run time. The
 * next best thing: carry the default across when the leg is still sitting on
 * the one its old exchange implied, and leave a product the author actually
 * changed alone. Moving an untouched NSE leg to NFO therefore prices it NRML,
 * while a leg deliberately set to MIS stays intraday wherever it goes.
 */
function productForExchange(leg: MarginLeg, exchange: string): Partial<MarginLeg> {
  if (leg.product !== defaultProductForExchange(leg.exchange)) return {}
  const next = defaultProductForExchange(exchange)
  return next === leg.product ? {} : { product: next }
}

function LegRow({ leg, index, lot, onRetryLookup, onUpdate, onRemove }: LegRowProps) {
  const problems: LegProblems = validateLeg(leg)
  const units = Number.parseInt(leg.quantity, 10) || 0
  const lotSize = lot.kind === 'resolved' ? lot.lotSize : null
  // Lots only when the stored units are a clean multiple. An irregular
  // quantity is shown as-is with an explicit round action rather than being
  // rewritten, so opening a saved workflow can never change what it will
  // execute.
  const lots = lotSize ? unitsToLots(units, lotSize) : null
  const inLots = lots !== null

  // In-progress text for the quantity box. The displayed value is derived from
  // the stored units, so without a draft an intermediate empty string during
  // retyping would immediately re-derive as one lot and fight the user's
  // keystrokes. Tagged with the mode it was typed in so a lookup resolving
  // mid-edit cannot reinterpret lots as units.
  const [draft, setDraft] = useState<{ inLots: boolean; text: string } | null>(null)
  const quantityText =
    draft && draft.inLots === inLots ? draft.text : String(inLots ? lots : leg.quantity)

  const id = (field: string) => `margin-leg-${index}-${field}`
  const describedBy = (field: keyof MarginLeg) =>
    problems[field] ? `${id(String(field))}-error` : undefined

  return (
    <div className="space-y-2 rounded-lg border border-border p-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium text-muted-foreground">Leg {index + 1}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-destructive hover:text-destructive"
          onClick={onRemove}
          aria-label={`Remove leg ${index + 1}`}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>

      <div className="space-y-1">
        <Label htmlFor={id('symbol')} className="text-[10px] text-muted-foreground">
          Symbol
        </Label>
        <Input
          id={id('symbol')}
          className="h-8"
          placeholder="NIFTY25DEC25FUT"
          value={leg.symbol}
          aria-invalid={Boolean(problems.symbol)}
          aria-describedby={describedBy('symbol')}
          onChange={(e) => onUpdate({ symbol: e.target.value.toUpperCase() })}
        />
        {problems.symbol && (
          <p id={`${id('symbol')}-error`} className="text-[10px] text-destructive">
            {problems.symbol}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label htmlFor={id('exchange')} className="text-[10px] text-muted-foreground">
            Exchange
          </Label>
          <Select
            value={leg.exchange}
            onValueChange={(v) => onUpdate({ exchange: v, ...productForExchange(leg, v) })}
          >
            <SelectTrigger id={id('exchange')} className="h-8" aria-label="Exchange">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXCHANGES.map((e) => (
                <SelectItem key={e.value} value={e.value}>
                  {e.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={id('quantity')} className="text-[10px] text-muted-foreground">
            {inLots ? 'Quantity (Lots)' : 'Quantity'}
          </Label>
          <Input
            id={id('quantity')}
            type="number"
            min={1}
            className="h-8"
            value={quantityText}
            aria-invalid={Boolean(problems.quantity)}
            aria-describedby={describedBy('quantity')}
            onChange={(e) => {
              const text = e.target.value
              setDraft({ inLots, text })
              if (!inLots) {
                onUpdate({ quantity: text })
                return
              }
              const entered = Number.parseInt(text, 10)
              // A blank or partial entry keeps the draft but commits nothing,
              // so the stored basket never passes through a bogus quantity.
              if (Number.isFinite(entered) && entered > 0) {
                onUpdate({ quantity: String(entered * (lotSize as number)) })
              }
            }}
            onBlur={() => setDraft(null)}
          />
        </div>
      </div>
      {problems.quantity && (
        <p id={`${id('quantity')}-error`} className="text-[10px] text-destructive">
          {problems.quantity}
        </p>
      )}
      <LotHint
        lot={lot}
        units={units}
        lots={lots}
        onRetryLookup={onRetryLookup}
        onRound={(rounded) => onUpdate({ quantity: String(rounded) })}
      />

      <fieldset className="grid grid-cols-2 gap-2">
        <legend className="sr-only">Action for leg {index + 1}</legend>
        {ORDER_ACTIONS.map((a) => (
          <button
            key={a.value}
            type="button"
            aria-pressed={leg.action === a.value}
            onClick={() => onUpdate({ action: a.value })}
            className={cn(
              'rounded-lg border py-1.5 text-xs font-semibold',
              leg.action === a.value
                ? a.value === 'BUY'
                  ? 'border-green-500 bg-green-500/20 text-green-600'
                  : 'border-red-500 bg-red-500/20 text-red-600'
                : 'border-border bg-muted'
            )}
          >
            {a.label}
          </button>
        ))}
      </fieldset>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label htmlFor={id('product')} className="text-[10px] text-muted-foreground">
            Product
          </Label>
          <Select value={leg.product} onValueChange={(v) => onUpdate({ product: v })}>
            <SelectTrigger id={id('product')} className="h-8" aria-label="Product">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRODUCT_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor={id('pricetype')} className="text-[10px] text-muted-foreground">
            Price Type
          </Label>
          <Select value={leg.pricetype} onValueChange={(v) => onUpdate({ pricetype: v })}>
            <SelectTrigger id={id('pricetype')} className="h-8" aria-label="Price type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRICE_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {NEEDS_PRICE.has(leg.pricetype) && (
        <div className="space-y-1">
          <Label htmlFor={id('price')} className="text-[10px] text-muted-foreground">
            Price
          </Label>
          <Input
            id={id('price')}
            type="number"
            min={0}
            step="any"
            className="h-8"
            value={leg.price}
            aria-invalid={Boolean(problems.price)}
            aria-describedby={describedBy('price')}
            onChange={(e) => onUpdate({ price: e.target.value })}
          />
          {problems.price && (
            <p id={`${id('price')}-error`} className="text-[10px] text-destructive">
              {problems.price}
            </p>
          )}
        </div>
      )}
      {NEEDS_TRIGGER.has(leg.pricetype) && (
        <div className="space-y-1">
          <Label htmlFor={id('trigger_price')} className="text-[10px] text-muted-foreground">
            Trigger Price
          </Label>
          <Input
            id={id('trigger_price')}
            type="number"
            min={0}
            step="any"
            className="h-8"
            value={leg.trigger_price}
            aria-invalid={Boolean(problems.trigger_price)}
            aria-describedby={describedBy('trigger_price')}
            onChange={(e) => onUpdate({ trigger_price: e.target.value })}
          />
          {problems.trigger_price && (
            <p id={`${id('trigger_price')}-error`} className="text-[10px] text-destructive">
              {problems.trigger_price}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

interface LotHintProps {
  lot: LotState
  units: number
  lots: number | null
  onRetryLookup: () => void
  onRound: (units: number) => void
}

/** The four lookup outcomes, kept visibly distinct: a failed request is
 * retryable, while a contract with no lot size is simply priced in units. */
function LotHint({ lot, units, lots, onRetryLookup, onRound }: LotHintProps) {
  if (lot.kind === 'not-applicable') return null

  if (lot.kind === 'loading') {
    return <p className="text-[10px] text-muted-foreground">Looking up lot size...</p>
  }

  if (lot.kind === 'failed') {
    return (
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] text-destructive">
          Lot-size lookup failed. Quantity is in units.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 shrink-0 px-2 text-[10px]"
          onClick={onRetryLookup}
        >
          Retry
        </Button>
      </div>
    )
  }

  if (lot.lotSize === null) {
    return (
      <p className="text-[10px] text-muted-foreground">
        No lot size is available for this contract; quantity is in units.
      </p>
    )
  }

  if (lots !== null) {
    return (
      <p className="text-[10px] text-muted-foreground">
        {lots} lot{lots === 1 ? '' : 's'} x {lot.lotSize} ={' '}
        <span className="font-medium text-foreground">{lots * lot.lotSize} units</span>
      </p>
    )
  }

  // Stored quantity is not a whole number of lots. Offer the correction rather
  // than applying it - rewriting on mount would change a saved workflow.
  const rounded = roundUpToLot(units, lot.lotSize)
  return (
    <div className="flex items-center justify-between gap-2">
      <p className="text-[10px] text-destructive">
        {units} units is not a multiple of the {lot.lotSize}-unit lot.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-6 shrink-0 px-2 text-[10px]"
        onClick={() => onRound(rounded)}
      >
        Round to {rounded / lot.lotSize} lot{rounded / lot.lotSize === 1 ? '' : 's'}
      </Button>
    </div>
  )
}
