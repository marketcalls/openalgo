// components/flow/panels/MarginPositionsFields.tsx
// Basket editor for the Margin Calculator node's `positions`.
//
// The node stores the basket as a JSON string because the backend interpolates
// and parses it before handing the array to services/margin_service
// (flow_executor_service._parse_margin_positions). That storage format is
// unchanged here - only the editing surface is.
//
// Hand-writing the JSON was easy to get wrong in a way nothing caught until the
// run: margin_service.validate_position requires exchange, symbol, action,
// quantity, product AND pricetype on every leg, and restx_api's
// MarginPositionSchema additionally requires quantity/price to be strings. The
// panel's own placeholder satisfied neither, so copying it produced
// "Position 1: Missing mandatory field(s): product, pricetype".

import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { flowQueryKeys, getSymbolLotSize } from '@/api/flow'
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
import { EXCHANGES, ORDER_ACTIONS, PRICE_TYPES, PRODUCT_TYPES } from '@/lib/flow/constants'
import { cn } from '@/lib/utils'

interface MarginPositionsFieldsProps {
  /** Raw `positionsJson` string as stored on the node. */
  value: string
  onChange: (raw: string) => void
}

interface Leg {
  symbol: string
  exchange: string
  action: string
  quantity: string
  product: string
  pricetype: string
  price: string
  trigger_price: string
}

const EMPTY_LEG: Leg = {
  symbol: '',
  exchange: 'NSE',
  action: 'BUY',
  quantity: '1',
  product: 'MIS',
  pricetype: 'MARKET',
  price: '0',
  trigger_price: '0',
}

/** Price types whose leg needs a limit price / a stop trigger. */
const NEEDS_PRICE = new Set(['LIMIT', 'SL'])
const NEEDS_TRIGGER = new Set(['SL', 'SL-M'])

/** Exchanges whose quantity is entered in lots, matching the options tools. */
const LOT_TRADED_EXCHANGES = new Set(['NFO', 'BFO'])

function toLeg(entry: Record<string, unknown>): Leg {
  const str = (key: string, fallback: string) => {
    const raw = entry[key]
    return raw === undefined || raw === null || raw === '' ? fallback : String(raw)
  }
  return {
    symbol: str('symbol', ''),
    exchange: str('exchange', 'NSE'),
    action: str('action', 'BUY').toUpperCase(),
    quantity: str('quantity', '1'),
    product: str('product', 'MIS'),
    pricetype: str('pricetype', 'MARKET'),
    price: str('price', '0'),
    trigger_price: str('trigger_price', '0'),
  }
}

function parseLegs(raw: string): { legs: Leg[]; error: string | null } {
  const text = (raw || '').trim()
  if (!text) return { legs: [], error: null }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { legs: [], error: e instanceof Error ? e.message : 'Invalid JSON' }
  }
  // The executor accepts a lone object as a one-leg basket, so the editor does
  // too rather than pushing the user into JSON mode over it.
  const list = Array.isArray(parsed) ? parsed : [parsed]
  if (list.some((e) => e === null || typeof e !== 'object' || Array.isArray(e))) {
    return { legs: [], error: 'Positions must be a JSON array of objects' }
  }
  return { legs: list.map((e) => toLeg(e as Record<string, unknown>)), error: null }
}

/** Serialize to the exact shape both validators accept.
 *
 * quantity/price go out as strings: margin_service coerces either, but
 * MarginPositionSchema declares them fields.Str and rejects a number outright,
 * so the string form is the one that works on every path. trigger_price is
 * only emitted for the price types that use it. */
function serialize(legs: Leg[]): string {
  if (!legs.length) return ''
  return JSON.stringify(
    legs.map((leg) => ({
      symbol: leg.symbol,
      exchange: leg.exchange,
      action: leg.action,
      quantity: String(leg.quantity || '0'),
      product: leg.product,
      pricetype: leg.pricetype,
      price: String(NEEDS_PRICE.has(leg.pricetype) ? leg.price || '0' : '0'),
      ...(NEEDS_TRIGGER.has(leg.pricetype)
        ? { trigger_price: String(leg.trigger_price || '0') }
        : {}),
    }))
  )
}

interface LegRowProps {
  leg: Leg
  index: number
  onUpdate: (patch: Partial<Leg>) => void
  onRemove: () => void
}

function LegRow({ leg, index, onUpdate, onRemove }: LegRowProps) {
  const symbol = leg.symbol.trim()
  // NFO/BFO contracts trade in lots, and the options tools (Option Chain,
  // Option Greeks) take the quantity that way, so this does too. The API still
  // wants units, so the lot count is multiplied out on the way into the JSON
  // and divided back out for display.
  const isLotTraded = LOT_TRADED_EXCHANGES.has(leg.exchange)
  const lotSizeQuery = useQuery({
    queryKey: flowQueryKeys.symbolLotSize(symbol, leg.exchange),
    queryFn: () => getSymbolLotSize(symbol, leg.exchange),
    enabled: isLotTraded && symbol.length > 0,
    // Lot sizes change only on a contract revision, not within a session.
    staleTime: 1000 * 60 * 60,
  })
  const lotSize = isLotTraded ? (lotSizeQuery.data ?? null) : null

  const units = Number.parseInt(leg.quantity, 10) || 0
  // Until the lookup resolves - or when the master contract has no lot size for
  // this symbol - stay in units. Guessing a lot count against an unknown lot
  // size would silently multiply the basket by the wrong factor.
  const inLots = lotSize !== null && lotSize > 0
  const lots = inLots ? Math.max(1, Math.round(units / lotSize)) : 0

  // Snap the stored units onto a whole number of lots once the lot size is
  // known. A leg added as NSE and then switched to NFO still carries its
  // 1-unit default, and showing "1 lot x 75 = 75 units" over a stored 1 would
  // price the basket at a quantity the panel never displayed. Converges in one
  // pass and stays quiet for a leg that is already a clean multiple, so a saved
  // workflow is not marked dirty just by opening it.
  useEffect(() => {
    if (!inLots) return
    const normalized = lots * lotSize
    if (normalized !== units) onUpdate({ quantity: String(normalized) })
  }, [inLots, lots, lotSize, units, onUpdate])

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

      <Input
        className="h-8"
        placeholder="NIFTY25DEC25FUT"
        value={leg.symbol}
        onChange={(e) => onUpdate({ symbol: e.target.value.toUpperCase() })}
      />

      <div className="grid grid-cols-2 gap-2">
        <Select value={leg.exchange} onValueChange={(v) => onUpdate({ exchange: v })}>
          <SelectTrigger className="h-8">
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
        <Input
          type="number"
          min={1}
          className="h-8"
          placeholder={inLots ? 'Lots' : 'Qty'}
          value={inLots ? lots : leg.quantity}
          onChange={(e) => {
            const entered = Number.parseInt(e.target.value, 10)
            if (!inLots) {
              onUpdate({ quantity: e.target.value })
              return
            }
            onUpdate({ quantity: String(Math.max(1, entered || 1) * lotSize) })
          }}
        />
      </div>
      {inLots ? (
        <p className="text-[10px] text-muted-foreground">
          {lots} lot{lots === 1 ? '' : 's'} x {lotSize} ={' '}
          <span className="font-medium text-foreground">{lots * lotSize} units</span>
        </p>
      ) : isLotTraded && symbol && lotSizeQuery.isFetching ? (
        <p className="text-[10px] text-muted-foreground">Looking up lot size...</p>
      ) : isLotTraded && symbol ? (
        <p className="text-[10px] text-muted-foreground">
          No lot size in the master contract for this symbol - quantity is in units.
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-2">
        {ORDER_ACTIONS.map((a) => (
          <button
            key={a.value}
            type="button"
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
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Select value={leg.product} onValueChange={(v) => onUpdate({ product: v })}>
          <SelectTrigger className="h-8">
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
        <Select value={leg.pricetype} onValueChange={(v) => onUpdate({ pricetype: v })}>
          <SelectTrigger className="h-8">
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

      {NEEDS_PRICE.has(leg.pricetype) && (
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">Price</Label>
          <Input
            type="number"
            min={0}
            step="any"
            className="h-8"
            value={leg.price}
            onChange={(e) => onUpdate({ price: e.target.value })}
          />
        </div>
      )}
      {NEEDS_TRIGGER.has(leg.pricetype) && (
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">Trigger Price</Label>
          <Input
            type="number"
            min={0}
            step="any"
            className="h-8"
            value={leg.trigger_price}
            onChange={(e) => onUpdate({ trigger_price: e.target.value })}
          />
        </div>
      )}
    </div>
  )
}

export function MarginPositionsFields({ value, onChange }: MarginPositionsFieldsProps) {
  const { legs, error } = parseLegs(value)
  const [jsonMode, setJsonMode] = useState(false)

  // Malformed JSON, or a {{variable}} basket, has no field representation -
  // switching to fields would silently discard whatever is in there.
  const showJson = jsonMode || error !== null

  const update = (index: number, patch: Partial<Leg>) => {
    onChange(serialize(legs.map((leg, i) => (i === index ? { ...leg, ...patch } : leg))))
  }
  const addLeg = () => onChange(serialize([...legs, { ...EMPTY_LEG }]))
  const removeLeg = (index: number) => onChange(serialize(legs.filter((_, i) => i !== index)))

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs">Positions</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[10px]"
          onClick={() => setJsonMode((m) => !m)}
        >
          {showJson ? 'Use fields' : 'Edit as JSON'}
        </Button>
      </div>

      {showJson ? (
        <div className="space-y-2">
          <Textarea
            className="min-h-[100px] font-mono text-xs"
            placeholder={
              '[{"symbol": "NIFTY25DEC25FUT", "exchange": "NFO", "action": "BUY", "quantity": "75", "product": "NRML", "pricetype": "MARKET", "price": "0"}]'
            }
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          {error ? (
            <p className="text-[10px] text-destructive">{error}</p>
          ) : (
            <p className="text-[10px] text-muted-foreground">
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
            onClick={addLeg}
          >
            <Plus className="mr-1 h-3 w-3" />
            Add Position
          </Button>
          <p className="text-[10px] text-muted-foreground">
            Up to 50 legs. Margin is estimated for the basket as a whole, so offsetting legs get the
            hedged requirement.
          </p>
        </>
      )}
    </div>
  )
}
