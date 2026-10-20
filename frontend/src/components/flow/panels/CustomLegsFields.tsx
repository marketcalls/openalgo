// components/flow/panels/CustomLegsFields.tsx
// Manual leg builder for the Multi-Leg Options node's "custom" strategy.
//
// The readymade strategies cover the shapes whose legs all share one expiry and
// are positioned by offset. Everything else - a calendar or diagonal spread, a
// ratio, a basket pinned to strikes the trader already chose - has to name its
// own strike, expiry and side per leg. The executor has accepted all of that
// for a while; until now the panel said "Configure custom legs via API", so the
// only way to reach it was to hand-write the workflow JSON.
//
// Parsing, defaults, validation, template seeding and serialization live in
// @/lib/flow/customLegs so they can be tested without mounting React. This file
// owns rendering only.

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Copy, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { flowQueryKeys, getOptionStrikes } from '@/api/flow'
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
import { PRICE_TYPES, PRODUCT_TYPES, strikeOffsetOptions } from '@/lib/flow/constants'
import {
  type CustomLeg,
  describeLeg,
  EMPTY_CUSTOM_LEG,
  hasVariableReference,
  type LegProblems,
  MAX_CUSTOM_LEGS,
  NEEDS_PRICE,
  NEEDS_TRIGGER,
  parseCustomLegs,
  type StrikeMode,
  seedLegsFromStrategy,
  serializeCustomLegs,
  validateCustomLeg,
  validateCustomLegs,
} from '@/lib/flow/customLegs'
import { cn } from '@/lib/utils'

interface CustomLegsFieldsProps {
  /** Raw `legs` array as stored on the node. */
  value: unknown
  onChange: (legs: ReturnType<typeof serializeCustomLegs>) => void
  /** The node's common price type, which a leg inherits when it names none. */
  commonPriceType: string
  /** The node's common product, shown as the inherit placeholder. */
  commonProduct: string
  /** The node's common expiry type, shown as the inherit placeholder. */
  commonExpiryType: string
  /** Common action / quantity / width, used when seeding from a template. */
  commonAction: string
  commonQuantity: number
  strangleWidth: string
  /** The node's underlying, used to look up the contracts a leg can name. */
  underlying: string
}

const STRIKE_MODES: Array<{ value: StrikeMode; label: string; hint: string }> = [
  { value: 'OFFSET', label: 'Offset', hint: 'Re-resolved against the underlying on every run' },
  { value: 'STRIKE', label: 'Strike', hint: 'One named contract, used exactly as entered' },
]

const TEMPLATES: Array<{ value: string; label: string }> = [
  { value: 'straddle', label: 'Straddle' },
  { value: 'strangle', label: 'Strangle' },
  { value: 'iron_condor', label: 'Iron Condor' },
  { value: 'bull_call_spread', label: 'Bull Call Spread' },
  { value: 'bear_put_spread', label: 'Bear Put Spread' },
]

export function CustomLegsFields({
  value,
  onChange,
  commonPriceType,
  commonProduct,
  commonExpiryType,
  commonAction,
  commonQuantity,
  strangleWidth,
  underlying,
}: CustomLegsFieldsProps) {
  const legs = parseCustomLegs(value)
  // Which rows are expanded. A freshly added leg opens itself; everything else
  // stays collapsed so a four-leg condor still fits the sidebar.
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set([0]))

  const commit = (next: CustomLeg[]) => onChange(serializeCustomLegs(next))

  const update = (index: number, patch: Partial<CustomLeg>) =>
    commit(legs.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)))

  const addLeg = () => {
    setExpanded(new Set([legs.length]))
    commit([...legs, { ...EMPTY_CUSTOM_LEG, quantity: String(commonQuantity || 1) }])
  }

  const duplicateLeg = (index: number) => {
    setExpanded(new Set([index + 1]))
    const next = [...legs]
    next.splice(index + 1, 0, { ...legs[index] })
    commit(next)
  }

  const removeLeg = (index: number) => {
    setExpanded(new Set())
    commit(legs.filter((_, i) => i !== index))
  }

  const loadTemplate = (strategy: string) => {
    const seeded = seedLegsFromStrategy(strategy, {
      action: commonAction === 'SELL' ? 'SELL' : 'BUY',
      quantity: String(commonQuantity || 1),
      strangleWidth,
    })
    if (!seeded.length) return
    setExpanded(new Set())
    commit(seeded)
  }

  const basketProblem = validateCustomLegs(legs, commonPriceType)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs">Legs</Label>
        <span className="text-[10px] text-muted-foreground">
          {legs.length}/{MAX_CUSTOM_LEGS}
        </span>
      </div>

      <div className="space-y-1">
        <Select value="" onValueChange={loadTemplate}>
          <SelectTrigger className="h-8" aria-label="Load legs from a readymade strategy">
            <SelectValue placeholder="Start from a readymade strategy" />
          </SelectTrigger>
          <SelectContent>
            {TEMPLATES.map((template) => (
              <SelectItem key={template.value} value={template.value}>
                {template.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground">
          Loads that strategy&apos;s legs here so you can change strikes, expiries and sides.
          Replaces the legs below.
        </p>
      </div>

      {legs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-3 text-center text-[10px] text-muted-foreground">
          No legs yet. Add one, or load a readymade strategy above and edit it.
        </p>
      ) : (
        legs.map((leg, index) => (
          <LegRow
            // Legs carry no id and are reordered only by add or delete, so the
            // index is the identity here.
            key={index}
            leg={leg}
            index={index}
            open={expanded.has(index)}
            onToggle={() =>
              setExpanded((current) => {
                const next = new Set(current)
                if (!next.delete(index)) next.add(index)
                return next
              })
            }
            commonPriceType={commonPriceType}
            commonProduct={commonProduct}
            commonExpiryType={commonExpiryType}
            underlying={underlying}
            onUpdate={(patch) => update(index, patch)}
            onDuplicate={() => duplicateLeg(index)}
            onRemove={() => removeLeg(index)}
          />
        ))
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8 w-full text-xs"
        disabled={legs.length >= MAX_CUSTOM_LEGS}
        onClick={addLeg}
      >
        <Plus className="mr-1 h-3 w-3" />
        Add Leg
      </Button>

      {basketProblem && <p className="text-[10px] text-destructive">{basketProblem}</p>}

      <p className="text-[10px] text-muted-foreground">
        Every leg is placed against the node&apos;s underlying. A leg that names its own expiry is
        how a calendar or diagonal spread is built; leave it on Same as node otherwise.
      </p>
    </div>
  )
}

interface LegRowProps {
  leg: CustomLeg
  index: number
  open: boolean
  onToggle: () => void
  commonPriceType: string
  commonProduct: string
  commonExpiryType: string
  underlying: string
  onUpdate: (patch: Partial<CustomLeg>) => void
  onDuplicate: () => void
  onRemove: () => void
}

function LegRow({
  leg,
  index,
  open,
  onToggle,
  commonPriceType,
  commonProduct,
  commonExpiryType,
  underlying,
  onUpdate,
  onDuplicate,
  onRemove,
}: LegRowProps) {
  const problems: LegProblems = validateCustomLeg(leg, commonPriceType)
  const hasProblem = Object.keys(problems).length > 0
  const effectivePriceType = leg.priceType || commonPriceType

  // Which expiry this leg will actually trade. An exact date asks for itself; a
  // relative type - the leg's own or, when it inherits, the node's - is
  // resolved server-side with the executor's selector so the panel names the
  // same contract the run will place.
  const expiryParams =
    leg.expiryMode === 'DATE' && leg.expiry && !hasVariableReference(leg.expiry)
      ? { expiry: leg.expiry }
      : { expiryType: leg.expiryMode === 'TYPE' ? leg.expiryType : commonExpiryType }
  const expiryKey = 'expiry' in expiryParams ? expiryParams.expiry : `@${expiryParams.expiryType}`

  // Only while the row is open: a collapsed condor would otherwise issue four
  // chain lookups for contracts nobody is editing. Legs sharing an expiry and
  // side share one request through the query key.
  const listing = useQuery({
    queryKey: flowQueryKeys.optionStrikes(underlying, expiryKey ?? '', leg.optionType),
    queryFn: () => getOptionStrikes({ underlying, ...expiryParams, optionType: leg.optionType }),
    enabled: open && Boolean(underlying),
    // The master contract changes on a contract revision, not within a session.
    staleTime: 1000 * 60 * 30,
    retry: false,
  })

  const listedStrikes = listing.data?.strikes ?? []
  const listedExpiries = listing.data?.expiries ?? []
  const selectedStrike = listedStrikes.find((row) => String(row.strike) === leg.strike)

  // The chain comes back as a window around ATM (OPTION_STRIKE_WINDOW), so a
  // leg deliberately pinned far out of the money has no row to select and the
  // control comes up empty - after which the next strike picked silently
  // replaces one the author chose. Keep it selectable, for the same reason the
  // expiry below keeps a date the contract no longer lists.
  const strikeOptions =
    leg.strike && !selectedStrike
      ? [{ strike: Number(leg.strike), symbol: null, label: '' }, ...listedStrikes]
      : listedStrikes

  // A typed value stays typed. The picker is an aid, not a cage: a strike or
  // expiry carrying a {{variable}} is resolved at run time and has no listing to
  // choose from, and the editor has to stay usable when the lookup fails - no
  // API key, no broker session, an underlying the master contract does not
  // carry - or a workflow could not be edited at all.
  const [typeStrike, setTypeStrike] = useState(false)
  const [typeExpiry, setTypeExpiry] = useState(false)
  const pickStrike = !typeStrike && listedStrikes.length > 0 && !hasVariableReference(leg.strike)

  // Expiry is a plain list of the dates the exchange lists, the way the
  // Strategy Builder's leg row reads. No mode step and no "same as node" entry:
  // the control shows the date this leg will actually trade, whether that date
  // came from the leg or from the node.
  //
  // Underneath, a leg that has not been given its own expiry keeps inheriting
  // the node's. That matters because a Flow workflow runs on a schedule, over
  // and over: a basket whose every leg was pinned to a date would keep trying
  // to trade that contract after it expired, whereas an untouched leg rolls
  // forward with the node. Choosing a date here pins that leg deliberately,
  // which is exactly what a calendar or diagonal spread needs.
  const inheritedExpiry = listing.data?.resolved?.[commonExpiryType] ?? ''
  const pinnedExpiry = leg.expiryMode === 'DATE' && leg.expiry ? leg.expiry : ''
  const relativeExpiry =
    leg.expiryMode === 'TYPE' ? (listing.data?.resolved?.[leg.expiryType] ?? '') : ''
  const effectiveExpiry = pinnedExpiry || relativeExpiry || inheritedExpiry

  // A date the contract no longer lists still has to be selectable, or opening
  // an older workflow would silently move that leg onto another expiry.
  const expiryOptions =
    effectiveExpiry && !listedExpiries.includes(effectiveExpiry)
      ? [effectiveExpiry, ...listedExpiries]
      : listedExpiries

  // Product and price type read the same way as expiry: the control shows what
  // this leg will actually use, and a leg that has not been given its own keeps
  // following the node. Naming the inheritance instead ("Same as node (MIS)")
  // said the same thing in more words and truncated to "Same (MARK".
  const effectiveProduct = leg.product || commonProduct
  // An options node should never be CNC, but a value the list does not carry
  // would render the trigger blank, which reads as "no product" rather than as
  // the bad data it is.
  const productOptions = PRODUCT_TYPES.filter(
    (product) => product.value !== 'CNC' || effectiveProduct === 'CNC'
  )

  const id = (field: string) => `custom-leg-${index}-${field}`
  const describedBy = (field: keyof CustomLeg) =>
    problems[field] ? `${id(String(field))}-error` : undefined

  const Problem = ({ field }: { field: keyof CustomLeg }) =>
    problems[field] ? (
      <p id={`${id(String(field))}-error`} className="text-[10px] text-destructive">
        {problems[field]}
      </p>
    ) : null

  return (
    <div
      className={cn(
        'rounded-lg border p-2',
        hasProblem ? 'border-destructive/50' : 'border-border'
      )}
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1 text-left"
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          <span className="shrink-0 text-[10px] font-medium text-muted-foreground">
            {index + 1}
          </span>
          <span
            className={cn(
              'truncate font-mono text-[10px]',
              leg.action === 'BUY' ? 'text-green-600' : 'text-red-600'
            )}
          >
            {describeLeg(leg)}
          </span>
        </button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={onDuplicate}
          aria-label={`Duplicate leg ${index + 1}`}
        >
          <Copy className="h-3 w-3" />
        </Button>
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

      {!open && hasProblem && (
        <p className="mt-1 pl-5 text-[10px] text-destructive">{Object.values(problems)[0]}</p>
      )}

      {open && (
        <div className="mt-2 space-y-2">
          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="sr-only">Side for leg {index + 1}</legend>
            {(['BUY', 'SELL'] as const).map((side) => (
              <button
                key={side}
                type="button"
                onClick={() => onUpdate({ action: side })}
                aria-pressed={leg.action === side}
                className={cn(
                  'rounded-lg border py-1.5 text-xs font-semibold',
                  leg.action === side
                    ? side === 'BUY'
                      ? 'border-green-500 bg-green-500/20 text-green-600'
                      : 'border-red-500 bg-red-500/20 text-red-600'
                    : 'border-border bg-muted'
                )}
              >
                {side}
              </button>
            ))}
          </fieldset>

          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="sr-only">Option type for leg {index + 1}</legend>
            {(['CE', 'PE'] as const).map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => onUpdate({ optionType: type })}
                aria-pressed={leg.optionType === type}
                className={cn(
                  'rounded-lg border py-1.5 text-xs font-semibold',
                  leg.optionType === type
                    ? 'border-primary bg-primary/20 text-primary'
                    : 'border-border bg-muted'
                )}
              >
                {type}
              </button>
            ))}
          </fieldset>

          <div className="space-y-1">
            <Label htmlFor={id('strikeMode')} className="text-[10px] text-muted-foreground">
              Strike
            </Label>
            <Select
              value={leg.strikeMode}
              onValueChange={(mode) =>
                onUpdate(
                  // Seeded with ATM rather than left blank: an empty strike is
                  // not a contract, and it serializes to 0, which then reads
                  // back as a leg deliberately pinned to strike zero.
                  mode === 'STRIKE' && !leg.strike && listing.data?.atm
                    ? { strikeMode: 'STRIKE', strike: String(listing.data.atm) }
                    : { strikeMode: mode as StrikeMode }
                )
              }
            >
              <SelectTrigger id={id('strikeMode')} className="h-8" aria-label="Strike mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STRIKE_MODES.map((mode) => (
                  <SelectItem key={mode.value} value={mode.value}>
                    {mode.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {leg.strikeMode === 'OFFSET' ? (
              <Select value={leg.offset} onValueChange={(v) => onUpdate({ offset: v })}>
                <SelectTrigger className="h-8" aria-label="Strike offset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {strikeOffsetOptions(leg.offset).map((offset) => (
                    <SelectItem key={offset.value} value={offset.value}>
                      {offset.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : pickStrike ? (
              <Select value={leg.strike} onValueChange={(v) => onUpdate({ strike: v })}>
                <SelectTrigger id={id('strike')} className="h-8" aria-label="Strike price">
                  <SelectValue placeholder="Pick a listed strike" />
                </SelectTrigger>
                <SelectContent>
                  {strikeOptions.map((row) => (
                    <SelectItem key={row.strike} value={String(row.strike)}>
                      <span className="flex w-full items-center justify-between gap-3">
                        <span className="font-mono">{row.strike}</span>
                        <span
                          className={cn(
                            'text-[10px]',
                            row.label === 'ATM' ? 'text-amber-500' : 'text-muted-foreground'
                          )}
                        >
                          {row.label}
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={id('strike')}
                className="h-8"
                placeholder="24500"
                value={leg.strike}
                aria-label="Strike price"
                aria-invalid={Boolean(problems.strike)}
                aria-describedby={describedBy('strike')}
                onChange={(e) => onUpdate({ strike: e.target.value })}
              />
            )}
            <Problem field={leg.strikeMode === 'STRIKE' ? 'strike' : 'offset'} />
            {leg.strikeMode === 'STRIKE' && listedStrikes.length > 0 && (
              <button
                type="button"
                className="text-[10px] text-muted-foreground underline"
                onClick={() => setTypeStrike((current) => !current)}
              >
                {pickStrike ? 'Type a strike or {{variable}}' : 'Pick a listed strike'}
              </button>
            )}
            <p className="text-[10px] text-muted-foreground">
              {STRIKE_MODES.find((m) => m.value === leg.strikeMode)?.hint}
            </p>
          </div>

          <div className="space-y-1">
            <Label htmlFor={id('expiry')} className="text-[10px] text-muted-foreground">
              Expiry
            </Label>
            {typeExpiry || hasVariableReference(leg.expiry) ? (
              <Input
                id={id('expiry')}
                className="h-8 font-mono"
                placeholder="28OCT25"
                value={leg.expiry}
                aria-label="Expiry date"
                aria-invalid={Boolean(problems.expiry)}
                aria-describedby={describedBy('expiry')}
                onChange={(e) =>
                  onUpdate({ expiryMode: 'DATE', expiry: e.target.value.toUpperCase() })
                }
              />
            ) : (
              <Select
                value={effectiveExpiry}
                onValueChange={(value) => onUpdate({ expiryMode: 'DATE', expiry: value })}
              >
                <SelectTrigger id={id('expiry')} className="h-8" aria-label="Expiry">
                  <SelectValue placeholder="Pick an expiry" />
                </SelectTrigger>
                <SelectContent>
                  {expiryOptions.map((value) => (
                    <SelectItem key={value} value={value}>
                      <span className="font-mono">{value}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Problem field="expiry" />
            {!pinnedExpiry && effectiveExpiry && (
              // Only shown while the leg is still following the node, because
              // that is the state whose behaviour is not visible from the date.
              <p className="text-[10px] text-muted-foreground">
                Follows the node, so it rolls to the next expiry.
              </p>
            )}
            <button
              type="button"
              className="text-[10px] text-muted-foreground underline"
              onClick={() => setTypeExpiry((current) => !current)}
            >
              {typeExpiry ? 'Pick a listed expiry' : 'Type a date or {{variable}}'}
            </button>
          </div>

          <div className="space-y-1">
            <Label htmlFor={id('quantity')} className="text-[10px] text-muted-foreground">
              Quantity (Lots)
            </Label>
            <Input
              id={id('quantity')}
              className="h-8"
              value={leg.quantity}
              aria-invalid={Boolean(problems.quantity)}
              aria-describedby={describedBy('quantity')}
              onChange={(e) => onUpdate({ quantity: e.target.value })}
            />
            <Problem field="quantity" />
          </div>

          <div className="space-y-1">
            <Label htmlFor={id('product')} className="text-[10px] text-muted-foreground">
              Product
            </Label>
            <Select
              value={effectiveProduct}
              onValueChange={(value) => onUpdate({ product: value })}
            >
              <SelectTrigger id={id('product')} className="h-8" aria-label="Product">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {productOptions.map((product) => (
                  <SelectItem key={product.value} value={product.value}>
                    {product.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label htmlFor={id('priceType')} className="text-[10px] text-muted-foreground">
              Price Type
            </Label>
            <Select
              value={effectivePriceType}
              onValueChange={(value) => onUpdate({ priceType: value })}
            >
              <SelectTrigger id={id('priceType')} className="h-8" aria-label="Price type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRICE_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {NEEDS_PRICE.has(effectivePriceType) && (
            <div className="space-y-1">
              <Label htmlFor={id('price')} className="text-[10px] text-muted-foreground">
                Price
              </Label>
              <Input
                id={id('price')}
                className="h-8"
                value={leg.price}
                aria-invalid={Boolean(problems.price)}
                aria-describedby={describedBy('price')}
                onChange={(e) => onUpdate({ price: e.target.value })}
              />
              <Problem field="price" />
            </div>
          )}

          {NEEDS_TRIGGER.has(effectivePriceType) && (
            <div className="space-y-1">
              <Label htmlFor={id('triggerPrice')} className="text-[10px] text-muted-foreground">
                Trigger Price
              </Label>
              <Input
                id={id('triggerPrice')}
                className="h-8"
                value={leg.triggerPrice}
                aria-invalid={Boolean(problems.triggerPrice)}
                aria-describedby={describedBy('triggerPrice')}
                onChange={(e) => onUpdate({ triggerPrice: e.target.value })}
              />
              <Problem field="triggerPrice" />
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor={id('splitSize')} className="text-[10px] text-muted-foreground">
              Split Size
            </Label>
            <Input
              id={id('splitSize')}
              className="h-8"
              placeholder="0 (no split)"
              value={leg.splitSize}
              aria-invalid={Boolean(problems.splitSize)}
              aria-describedby={describedBy('splitSize')}
              onChange={(e) => onUpdate({ splitSize: e.target.value })}
            />
            <Problem field="splitSize" />
          </div>

          <ContractHint
            leg={leg}
            loading={listing.isLoading}
            failed={listing.isError}
            symbol={selectedStrike?.symbol ?? null}
            atm={listing.data?.atm ?? null}
            underlyingLtp={listing.data?.underlyingLtp ?? null}
            underlyingSymbol={listing.data?.underlyingSymbol ?? null}
          />
        </div>
      )}
    </div>
  )
}

interface ContractHintProps {
  leg: CustomLeg
  loading: boolean
  failed: boolean
  symbol: string | null
  atm: number | null
  underlyingLtp: number | null
  underlyingSymbol: string | null
}

/**
 * What this leg currently resolves to.
 *
 * An offset leg deliberately shows no symbol: it re-resolves against the
 * underlying on every run, so naming today's contract would be a promise the
 * next run does not keep. Only a leg pinned to a strike names one.
 */
function ContractHint({
  leg,
  loading,
  failed,
  symbol,
  atm,
  underlyingLtp,
  underlyingSymbol,
}: ContractHintProps) {
  if (loading) {
    return <p className="text-[10px] text-muted-foreground">Loading listed contracts...</p>
  }
  if (failed) {
    // Not an error state for the leg: the workflow is still editable by hand,
    // and this is the ordinary case when no broker session is live.
    return (
      <p className="text-[10px] text-muted-foreground">
        Listed contracts unavailable, so strike and expiry are typed here. They are checked when the
        workflow is saved.
      </p>
    )
  }

  return (
    <div className="space-y-0.5 border-t border-border pt-1.5">
      {symbol && leg.strikeMode === 'STRIKE' && (
        <p className="font-mono text-[10px] text-foreground">{symbol}</p>
      )}
      {underlyingLtp !== null && (
        <p className="text-[10px] text-muted-foreground">
          {underlyingSymbol ?? 'Underlying'} {underlyingLtp}
          {atm !== null ? ` - ATM ${atm}` : ''}
        </p>
      )}
    </div>
  )
}
