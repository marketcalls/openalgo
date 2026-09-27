// pages/strategy/Wizard.tsx
// Create or edit a strategy. One page, not a stepped wizard: every section is
// visible at once so the shape of the whole strategy is readable while any part
// of it is being changed.

import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  createStrategy,
  type ExpiryResolution,
  updateStrategy,
  useExpiryResolution,
  useLotSize,
  useOptionStrikes,
  useUnderlyingSearch,
} from '@/api/strategy_module'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'
import {
  ATM_OFFSETS,
  allowedProductsForLegs,
  batchQuantityLabelFor,
  convertLegKind,
  DIRECTION_ACCEPTS,
  defaultProductForLegs,
  defaultQtyMode,
  derivativeExchangeFor,
  EXPIRY_RANK_LABELS,
  type ExpiryRank,
  expiriesFor,
  filterStrikes,
  freshBatchLeg,
  freshSignalLeg,
  isDerivativeExchange,
  isWholeLots,
  LEG_SIDE_LABELS,
  type Leg,
  type LegPosition,
  type LegSide,
  type LockProfitMode,
  legToPayload,
  MAX_LEGS,
  MAX_NAME_LENGTH,
  MAX_SIGNAL_LOTS,
  MAX_SIGNAL_QTY,
  maxBatchQuantityFor,
  maxQtyFor,
  type OptionType,
  type Product,
  productHintForLegs,
  type QtyMode,
  resolvedQuantity,
  type Segment,
  SIGNAL_LEG_EXCHANGES,
  SIGNAL_MODE_TABS,
  STRATEGY_DIRECTION_LABELS,
  STRATEGY_KIND_HINT,
  STRATEGY_KIND_LABELS,
  type Strategy,
  type StrategyConfigPayload,
  type StrategyDirection,
  type StrategyKind,
  type StrategyType,
  type StrategyUpdatePayload,
  segmentSuitsExchange,
  signalSegmentsForTab,
  TAB_DEFAULT_EXCHANGE,
  TAB_DEFAULT_UNDERLYINGS,
  TAB_INTRADAY_DEFAULTS,
  TAB_SEGMENTS,
  TAB_UNDERLYING_EXCHANGES,
  TAB_UNDERLYING_IS_CLOSED_SET,
  UNIVERSE_TAB_HINT,
  UNIVERSE_TAB_LABELS,
  UNIVERSE_TABS,
  type UniverseTab,
  withQtyMode,
} from '@/types/strategy_module'
import { showToast } from '@/utils/toast'

const SELECT_CLASS_SM = 'flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm'
const SELECT_CLASS_MD = 'flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm'

/** A tab the wizard knows, or the default when a stored value is unfamiliar. */
function asTab(value: string | undefined): UniverseTab {
  return UNIVERSE_TABS.includes(value as UniverseTab) ? (value as UniverseTab) : 'weekly_monthly'
}

/** A value that settles before it is used, so typing does not fan out a request per keystroke. */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const handle = setTimeout(() => setSettled(value), delayMs)
    return () => clearTimeout(handle)
  }, [value, delayMs])
  return settled
}

// ---------------------------------------------------------------------------
// Strike picker
// ---------------------------------------------------------------------------

interface StrikePickerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  underlying: string
  underlyingExchange: string
  expiryRank: ExpiryRank
  /** The date the rank resolved to, or null when it could not be resolved. */
  resolvedExpiry: string | null
  optionType: OptionType
  selectedStrike: number | null
  onPick: (strike: number) => void
}

/**
 * Pick a strike from what is actually listed.
 *
 * A typed strike is a strike that may not exist: the leg saves, and the failure
 * surfaces at start when the engine cannot resolve a contract. Choosing from
 * the chain means the number in the field is one the exchange lists for that
 * expiry, and the header says which expiry that is.
 */
function StrikePickerDialog({
  open,
  onOpenChange,
  underlying,
  underlyingExchange,
  expiryRank,
  resolvedExpiry,
  optionType,
  selectedStrike,
  onPick,
}: StrikePickerProps) {
  const [filter, setFilter] = useState('')
  const {
    strikes,
    resolvedExpiry: chainExpiry,
    exchange,
    isLoading,
    error,
  } = useOptionStrikes(underlying, underlyingExchange, resolvedExpiry, open)

  const filtered = filterStrikes(strikes, filter)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            Pick strike — {underlying} {expiryRank} {optionType}
          </DialogTitle>
          {strikes.length > 0 ? (
            <DialogDescription className="text-xs">
              {strikes.length} strikes available · resolved expiry:{' '}
              <span className="font-mono">{chainExpiry ?? resolvedExpiry}</span> on {exchange}
            </DialogDescription>
          ) : (
            <DialogDescription className="text-xs">
              {underlying} {optionType} options for the {expiryRank} contract.
            </DialogDescription>
          )}
        </DialogHeader>
        <div className="space-y-3">
          <Input
            placeholder="Filter (e.g. 24000)…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            autoFocus
          />
          <div className="max-h-72 overflow-y-auto rounded-md border">
            {resolvedExpiry === null ? (
              <p className="p-3 text-center text-sm text-destructive">
                Could not resolve the {expiryRank} expiry for {underlying}. The master contract may
                not be downloaded.
              </p>
            ) : isLoading ? (
              <p className="p-3 text-center text-sm text-muted-foreground">Loading…</p>
            ) : error ? (
              <p className="p-3 text-center text-sm text-destructive">{error}</p>
            ) : filtered.length === 0 ? (
              <p className="p-3 text-center text-sm text-muted-foreground">No matches</p>
            ) : (
              <ul className="divide-y">
                {filtered.map((strike) => (
                  <li key={strike}>
                    <button
                      type="button"
                      onClick={() => {
                        onPick(strike)
                        onOpenChange(false)
                      }}
                      className={cn(
                        'flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-muted',
                        selectedStrike === strike && 'bg-primary/10 font-semibold'
                      )}
                    >
                      <span className="font-mono">{strike}</span>
                      {selectedStrike === strike && (
                        <Badge variant="secondary" className="text-[10px]">
                          selected
                        </Badge>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Leg card
// ---------------------------------------------------------------------------

/** What a leg's expiry rank resolved to, for the line under the rank picker. */
interface LegExpiryState {
  date: string | null
  isLoading: boolean
  error: string | null
}

interface LegCardProps {
  leg: Leg
  tab: UniverseTab
  index: number
  expiry: LegExpiryState
  onChange: (next: Leg) => void
  onRemove: () => void
  onOpenStrikePicker: () => void
  removable: boolean
}

function LegCard({
  leg,
  tab,
  index,
  expiry,
  onChange,
  onRemove,
  onOpenStrikePicker,
  removable,
}: LegCardProps) {
  const segments = TAB_SEGMENTS[tab]
  const expiries = expiriesFor(tab, leg.segment)

  const update = <K extends keyof Leg>(key: K, value: Leg[K]) => {
    onChange({ ...leg, [key]: value })
  }

  return (
    <Card className="border-dashed bg-muted/30">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Leg {index + 1}</CardTitle>
        {removable && (
          <Button size="sm" variant="ghost" onClick={onRemove}>
            Remove
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Segment</Label>
            <select
              value={leg.segment}
              onChange={(event) => {
                const segment = event.target.value as Segment
                // Resolve the new strike mode first: the offset and strike
                // defaults have to be evaluated against it, not against the
                // value the leg is leaving, or a round trip through a futures
                // segment comes back with a mode and no value to go with it.
                const strikeMode = segment === 'options' ? (leg.strike_mode ?? 'atm') : null
                onChange({
                  ...leg,
                  segment,
                  expiry: segment === 'cash' ? null : (expiriesFor(tab, segment)[0] ?? 'monthly'),
                  option_type: segment === 'options' ? (leg.option_type ?? 'CE') : null,
                  strike_mode: strikeMode,
                  atm_offset: strikeMode === 'atm' ? (leg.atm_offset ?? 'ATM') : null,
                  strike: strikeMode === 'strike' ? (leg.strike ?? null) : null,
                })
              }}
              className={SELECT_CLASS_SM}
            >
              {segments.map((segment) => (
                <option key={segment} value={segment}>
                  {segment}
                </option>
              ))}
            </select>
          </div>

          {leg.segment !== 'cash' && (
            <div className="space-y-1.5">
              <Label className="text-xs uppercase">Expiry</Label>
              <select
                value={leg.expiry ?? expiries[0]}
                onChange={(event) => update('expiry', event.target.value as ExpiryRank)}
                className={SELECT_CLASS_SM}
              >
                {expiries.map((rank) => (
                  <option key={rank} value={rank}>
                    {EXPIRY_RANK_LABELS[rank]}
                  </option>
                ))}
              </select>
              {/* The rank is what is stored, because that is what survives a
                  roll. The date is what the operator can check. */}
              {expiry.isLoading ? (
                <p className="text-[10px] text-muted-foreground">resolving…</p>
              ) : expiry.error ? (
                <p className="text-[10px] text-destructive" title={expiry.error}>
                  could not resolve
                </p>
              ) : expiry.date ? (
                <p className="font-mono text-[10px] text-muted-foreground">{expiry.date}</p>
              ) : (
                <p className="text-[10px] text-amber-600">not listed</p>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <Label className="text-xs uppercase">{batchQuantityLabelFor(leg.segment)}</Label>
            <Input
              type="number"
              min={1}
              max={maxBatchQuantityFor(leg.segment)}
              value={leg.lots ?? 1}
              onChange={(event) =>
                update(
                  'lots',
                  Math.min(
                    maxBatchQuantityFor(leg.segment),
                    Math.max(1, Number.parseInt(event.target.value || '1', 10))
                  )
                )
              }
              className="h-9"
            />
            {leg.segment === 'cash' && (
              <p className="text-[10px] text-muted-foreground">Shares, sent as-is.</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Position</Label>
            <div className="flex h-9 overflow-hidden rounded-md border border-input">
              {(['B', 'S'] as LegPosition[]).map((position) => (
                <button
                  key={position}
                  type="button"
                  onClick={() => update('position', position)}
                  className={cn(
                    'flex-1 text-sm font-medium transition-colors',
                    leg.position === position
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background hover:bg-muted'
                  )}
                >
                  {position}
                </button>
              ))}
            </div>
          </div>
        </div>

        {leg.segment === 'options' && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="space-y-1.5">
              <Label className="text-xs uppercase">Option Type</Label>
              <div className="flex h-9 overflow-hidden rounded-md border border-input">
                {(['CE', 'PE'] as OptionType[]).map((optionType) => (
                  <button
                    key={optionType}
                    type="button"
                    onClick={() => update('option_type', optionType)}
                    className={cn(
                      'flex-1 text-sm font-medium transition-colors',
                      leg.option_type === optionType
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background hover:bg-muted'
                    )}
                  >
                    {optionType}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs uppercase">Strike mode</Label>
              <div className="flex h-9 overflow-hidden rounded-md border border-input">
                {(['atm', 'strike'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() =>
                      onChange({
                        ...leg,
                        strike_mode: mode,
                        atm_offset: mode === 'atm' ? (leg.atm_offset ?? 'ATM') : null,
                        strike: mode === 'strike' ? (leg.strike ?? null) : null,
                      })
                    }
                    className={cn(
                      'flex-1 text-sm font-medium transition-colors',
                      leg.strike_mode === mode
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background hover:bg-muted'
                    )}
                  >
                    {mode === 'atm' ? 'ATM-relative' : 'Direct strike'}
                  </button>
                ))}
              </div>
            </div>

            {leg.strike_mode === 'atm' ? (
              <div className="space-y-1.5 sm:col-span-2">
                <Label className="text-xs uppercase">Strike offset</Label>
                <select
                  value={leg.atm_offset ?? 'ATM'}
                  onChange={(event) => update('atm_offset', event.target.value)}
                  className={SELECT_CLASS_SM}
                >
                  {ATM_OFFSETS.map((offset) => (
                    <option key={offset} value={offset}>
                      {offset}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="space-y-1.5 sm:col-span-2">
                <Label className="text-xs uppercase">Strike value</Label>
                <div className="flex gap-2">
                  <Input
                    type="number"
                    step={0.01}
                    value={leg.strike ?? ''}
                    placeholder="Pick from list →"
                    readOnly
                    className="h-9 font-mono"
                  />
                  <Button type="button" variant="outline" size="sm" onClick={onOpenStrikePicker}>
                    Pick strike
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Filtered by underlying + resolved expiry rank ({leg.expiry}).
                </p>
              </div>
            )}
          </div>
        )}

        <Separator />

        <div className="mb-3 flex items-center gap-2">
          <Label className="text-xs uppercase text-muted-foreground">Risk measured in</Label>
          <div className="inline-flex overflow-hidden rounded-md border">
            {(['points', 'percent'] as const).map((unit) => (
              <button
                key={unit}
                type="button"
                onClick={() => update('risk_unit', unit)}
                className={cn(
                  'px-3 py-1 text-xs transition-colors',
                  (leg.risk_unit ?? 'points') === unit
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background hover:bg-muted'
                )}
              >
                {unit === 'points' ? 'Points' : '% of entry'}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {(leg.risk_unit ?? 'points') === 'percent'
              ? 'Stop, target and trail are a percentage of the entry price.'
              : 'Stop, target and trail are absolute point distances.'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">
              Stop Loss ({(leg.risk_unit ?? 'points') === 'percent' ? '%' : 'pts'})
            </Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              max={(leg.risk_unit ?? 'points') === 'percent' ? 100 : undefined}
              value={leg.sl_pts ?? ''}
              placeholder="0 = off"
              onChange={(event) =>
                update('sl_pts', event.target.value === '' ? null : Number(event.target.value))
              }
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">
              Target ({(leg.risk_unit ?? 'points') === 'percent' ? '%' : 'pts'})
            </Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              max={(leg.risk_unit ?? 'points') === 'percent' ? 100 : undefined}
              value={leg.target_pts ?? ''}
              placeholder="0 = off"
              onChange={(event) =>
                update('target_pts', event.target.value === '' ? null : Number(event.target.value))
              }
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Trail SL — X (pts)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={leg.trail?.x ?? 0}
              onChange={(event) =>
                update('trail', { x: Number(event.target.value || 0), y: leg.trail?.y ?? 0 })
              }
              className="h-9"
            />
            <p className="text-[10px] text-muted-foreground">
              Advance the stop by Y points for every X points the leg moves in your favour. Both
              halves are required together.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Trail SL — Y (step)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={leg.trail?.y ?? 0}
              onChange={(event) =>
                update('trail', { x: leg.trail?.x ?? 0, y: Number(event.target.value || 0) })
              }
              className="h-9"
            />
            <p className="text-[10px] text-muted-foreground">
              Leave both at 0 for a leg with no trailing stop.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Signal leg card
// ---------------------------------------------------------------------------

interface SignalLegCardProps {
  leg: Leg
  tab: UniverseTab
  index: number
  onChange: (next: Leg) => void
  onRemove: () => void
  removable: boolean
}

/**
 * One signal-mode leg.
 *
 * A different shape from a batch leg, not a superset: it names its own
 * instrument and its own absolute quantity, and carries no option fields at
 * all. The validator refuses the batch fields here and the signal fields
 * there, so the two cards stay separate rather than one form hiding half of
 * itself.
 */
function SignalLegCard({ leg, tab, index, onChange, onRemove, removable }: SignalLegCardProps) {
  const cashVenue = TAB_DEFAULT_EXCHANGE[tab]
  const derivativeVenue = derivativeExchangeFor(cashVenue)
  const venueFor = (segment: Segment) => (segment === 'futures' ? derivativeVenue : cashVenue)

  // A futures leg still names its contract by rank, so the same resolution the
  // batch card does applies - keyed on this leg's own symbol, because in
  // signal mode there is no single strategy-level underlying to key on.
  const expiry = useExpiryResolution(
    leg.symbol ?? '',
    leg.exchange || venueFor(leg.segment),
    'futures',
    leg.segment === 'futures' && Boolean(leg.symbol?.trim())
  )
  const resolvedExpiry = leg.expiry ? expiry.resolve(leg.expiry) : null

  const update = <K extends keyof Leg>(key: K, value: Leg[K]) => {
    onChange({ ...leg, [key]: value })
  }

  // The leg's own exchange decides whether it is counted in lots, because that
  // is what the validator checks - not the segment, and not the tab.
  const venue = leg.exchange || venueFor(leg.segment)
  const derivative = isDerivativeExchange(venue)
  const qtyMode: QtyMode = derivative ? (leg.qty_mode ?? defaultQtyMode(venue)) : 'units'
  const qty = leg.qty ?? 1

  const lot = useLotSize(leg.symbol, venue, derivative && Boolean(leg.symbol?.trim()))
  const sent = resolvedQuantity(qty, qtyMode, lot.lotSize)
  const partLot = qtyMode === 'units' && derivative && !isWholeLots(qty, lot.lotSize)

  const quantityLabel =
    qtyMode === 'lots' ? 'Lots' : derivative ? 'Quantity (units)' : 'Quantity (shares)'

  // The spinner should move by a tradeable amount. In units mode on a
  // derivative that is one lot, so 500 goes to 1000 rather than to 501, which
  // is not a quantity the exchange accepts. Typing is untouched: an arbitrary
  // number is still allowed, and a part lot is still flagged below and refused
  // by the server. Shares and lot counts both step by one.
  const qtyStep = qtyMode === 'units' && derivative && lot.lotSize ? lot.lotSize : 1

  const setQtyMode = (mode: QtyMode) => {
    // The lot size the card has already resolved, so the toggle converts
    // rather than reinterpreting: one lot of RELIANCE becomes 500 shares.
    if (mode !== qtyMode) onChange(withQtyMode(leg, mode, lot.lotSize))
  }

  return (
    <Card className="border-dashed bg-muted/30">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Leg {index + 1}</CardTitle>
        {removable && (
          <Button size="sm" variant="ghost" onClick={onRemove}>
            Remove
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Symbol</Label>
            <UnderlyingSearchField
              value={leg.symbol ?? ''}
              onChange={(symbol) => {
                // Picking a symbol fills the venue in, but never overwrites
                // one the user has already set by hand.
                const nextVenue = leg.exchange || venueFor(leg.segment)
                onChange({
                  ...leg,
                  symbol,
                  exchange: nextVenue,
                  qty_mode: leg.qty_mode ?? defaultQtyMode(nextVenue),
                })
              }}
              searchExchange={leg.segment === 'futures' ? derivativeVenue : cashVenue}
              placeholder={leg.segment === 'cash' ? 'e.g. RELIANCE' : 'e.g. CRUDEOIL'}
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Exchange</Label>
            <select
              value={leg.exchange || venueFor(leg.segment)}
              onChange={(event) => {
                const nextVenue = event.target.value.toUpperCase()
                // The segment follows the venue rather than being left to
                // contradict it. A leg marked cash on NFO validated and the
                // segment was then ignored, so the leg traded whatever the
                // symbol happened to be.
                const nextSegment: Segment = isDerivativeExchange(nextVenue) ? 'futures' : 'cash'
                onChange({
                  ...leg,
                  exchange: nextVenue,
                  segment: nextSegment,
                  expiry: nextSegment === 'futures' ? (leg.expiry ?? 'monthly') : null,
                  // Lots on a cash venue is refused outright, so moving to one
                  // moves the leg to units rather than leaving it unsavable.
                  qty_mode: defaultQtyMode(nextVenue),
                })
              }}
              className={`${SELECT_CLASS_SM} font-mono`}
            >
              {SIGNAL_LEG_EXCHANGES.map((venue) => (
                <option key={venue} value={venue}>
                  {venue}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Segment</Label>
            <select
              value={leg.segment}
              onChange={(event) => {
                const segment = event.target.value as Segment
                const wasDefaultVenue = !leg.exchange || leg.exchange === venueFor(leg.segment)
                const nextVenue = wasDefaultVenue ? venueFor(segment) : (leg.exchange as string)
                onChange({
                  ...leg,
                  segment,
                  // Refused outright on a cash leg, so it is cleared here
                  // rather than left for the payload to strip.
                  expiry: segment === 'futures' ? (leg.expiry ?? 'monthly') : null,
                  exchange: nextVenue,
                  qty_mode: defaultQtyMode(nextVenue),
                })
              }}
              className={SELECT_CLASS_SM}
            >
              {signalSegmentsForTab(tab).map((segment) => (
                <option key={segment} value={segment}>
                  {segment}
                </option>
              ))}
            </select>
          </div>

          {leg.segment === 'futures' && (
            <div className="space-y-1.5">
              <Label className="text-xs uppercase">Expiry</Label>
              <select
                value={leg.expiry ?? 'monthly'}
                onChange={(event) => update('expiry', event.target.value as ExpiryRank)}
                className={SELECT_CLASS_SM}
              >
                {expiriesFor(tab, 'futures').map((rank) => (
                  <option key={rank} value={rank}>
                    {EXPIRY_RANK_LABELS[rank]}
                  </option>
                ))}
              </select>
              {!leg.symbol?.trim() ? (
                <p className="text-[10px] text-muted-foreground">pick a symbol first</p>
              ) : expiry.isLoading ? (
                <p className="text-[10px] text-muted-foreground">resolving…</p>
              ) : expiry.error ? (
                <p className="text-[10px] text-destructive" title={expiry.error}>
                  could not resolve
                </p>
              ) : resolvedExpiry ? (
                <p className="font-mono text-[10px] text-muted-foreground">{resolvedExpiry}</p>
              ) : (
                <p className="text-[10px] text-amber-600">not listed</p>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Side</Label>
            <select
              value={leg.side ?? 'both'}
              onChange={(event) => update('side', event.target.value as LegSide)}
              className={SELECT_CLASS_SM}
            >
              {(['long', 'short', 'both'] as LegSide[]).map((side) => (
                <option key={side} value={side}>
                  {LEG_SIDE_LABELS[side]}
                </option>
              ))}
            </select>
            {/* The single most confusable thing in this feature. */}
            <p className="text-[10px] text-muted-foreground">
              Which signals this leg accepts, not the side it is held. Both takes all four actions;
              whichever signal opens the leg decides whether it is long or short.
            </p>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-xs uppercase">{quantityLabel}</Label>
              <div className="flex h-5 overflow-hidden rounded border border-input">
                {(['lots', 'units'] as QtyMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    disabled={mode === 'lots' && !derivative}
                    onClick={() => setQtyMode(mode)}
                    title={
                      mode === 'lots' && !derivative
                        ? `${venue} has no lot size to multiply by, so cash is counted in shares.`
                        : undefined
                    }
                    className={cn(
                      'px-1.5 text-[10px] font-medium uppercase transition-colors',
                      qtyMode === mode
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background hover:bg-muted',
                      mode === 'lots' && !derivative && 'cursor-not-allowed opacity-40'
                    )}
                  >
                    {/* On a derivative "units" is contracts. On cash it is
                        shares, which is the word the instrument actually uses. */}
                    {mode === 'units' && !derivative ? 'shares' : mode}
                  </button>
                ))}
              </div>
            </div>
            <Input
              type="number"
              min={qtyStep}
              max={qtyMode === 'lots' ? MAX_SIGNAL_LOTS : MAX_SIGNAL_QTY}
              step={qtyStep}
              value={qty}
              onChange={(event) =>
                update(
                  'qty',
                  Math.min(
                    maxQtyFor(qtyMode),
                    Math.max(1, Number.parseInt(event.target.value || '1', 10) || 1)
                  )
                )
              }
              className={cn('h-9', partLot && 'border-amber-500')}
            />
            {qtyMode === 'lots' ? (
              lot.isLoading ? (
                <p className="text-[10px] text-muted-foreground">reading lot size…</p>
              ) : sent != null ? (
                <p className="text-[10px] text-muted-foreground">
                  <span className="font-mono">
                    {qty} {qty === 1 ? 'lot' : 'lots'} = {sent}
                  </span>{' '}
                  (lot size {lot.lotSize}). The lot count is what is stored - lot sizes get revised,
                  and a saved quantity would silently become a different number of lots.
                </p>
              ) : (
                <p className="text-[10px] text-amber-600">
                  {leg.symbol?.trim()
                    ? 'Lot size unknown, so the quantity cannot be shown. The master contract may not be downloaded; the engine resolves it at entry.'
                    : 'Pick a symbol to see what this sends.'}
                </p>
              )
            ) : partLot ? (
              <p className="text-[10px] text-amber-600">
                <span className="font-mono">{qty}</span> is not a whole number of lots
                {lot.lotSize ? ` (lot size ${lot.lotSize})` : ''}. The broker refuses a part lot.
              </p>
            ) : derivative && sent != null && lot.lotSize ? (
              <p className="text-[10px] text-muted-foreground">
                <span className="font-mono">
                  {sent} = {sent / lot.lotSize} {sent / lot.lotSize === 1 ? 'lot' : 'lots'}
                </span>{' '}
                (lot size {lot.lotSize}), sent as-is.
              </p>
            ) : (
              <p className="text-[10px] text-muted-foreground">
                {derivative ? 'Units, sent as-is.' : 'Shares, sent as-is.'}
              </p>
            )}
          </div>
        </div>

        <Separator />

        <div className="mb-3 flex items-center gap-2">
          <Label className="text-xs uppercase text-muted-foreground">Risk measured in</Label>
          <div className="inline-flex overflow-hidden rounded-md border">
            {(['points', 'percent'] as const).map((unit) => (
              <button
                key={unit}
                type="button"
                onClick={() => update('risk_unit', unit)}
                className={cn(
                  'px-3 py-1 text-xs transition-colors',
                  (leg.risk_unit ?? 'points') === unit
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background hover:bg-muted'
                )}
              >
                {unit === 'points' ? 'Points' : '% of entry'}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {(leg.risk_unit ?? 'points') === 'percent'
              ? 'Stop, target and trail are a percentage of the entry price.'
              : 'Stop, target and trail are absolute point distances.'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">
              Stop Loss ({(leg.risk_unit ?? 'points') === 'percent' ? '%' : 'pts'})
            </Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              max={(leg.risk_unit ?? 'points') === 'percent' ? 100 : undefined}
              value={leg.sl_pts ?? ''}
              placeholder="0 = off"
              onChange={(event) =>
                update('sl_pts', event.target.value === '' ? null : Number(event.target.value))
              }
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">
              Target ({(leg.risk_unit ?? 'points') === 'percent' ? '%' : 'pts'})
            </Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              max={(leg.risk_unit ?? 'points') === 'percent' ? 100 : undefined}
              value={leg.target_pts ?? ''}
              placeholder="0 = off"
              onChange={(event) =>
                update('target_pts', event.target.value === '' ? null : Number(event.target.value))
              }
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Trail SL — X (pts)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={leg.trail?.x ?? 0}
              onChange={(event) =>
                update('trail', { x: Number(event.target.value || 0), y: leg.trail?.y ?? 0 })
              }
              className="h-9"
            />
            <p className="text-[10px] text-muted-foreground">
              Advance the stop by Y points for every X points the leg moves in your favour. Both
              halves are required together.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Trail SL — Y (step)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={leg.trail?.y ?? 0}
              onChange={(event) =>
                update('trail', { x: leg.trail?.x ?? 0, y: Number(event.target.value || 0) })
              }
              className="h-9"
            />
            <p className="text-[10px] text-muted-foreground">
              Leave both at 0 for a leg with no trailing stop.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Underlying picker for the open-universe tabs
// ---------------------------------------------------------------------------

/**
 * Search for an underlying instead of choosing from a seeded handful.
 *
 * Stock F&O and MCX are open universes: a fixed list can only ever be wrong.
 * The lookup runs against the derivative exchange, so what comes back is
 * underlyings that actually have contracts listed.
 */
function UnderlyingSearchField({
  id,
  value,
  onChange,
  searchExchange,
  placeholder,
}: {
  /** Only set where a <Label htmlFor> points at it; omitted inside leg cards,
   *  where the field is rendered once per leg and an id would repeat. */
  id?: string
  value: string
  onChange: (symbol: string) => void
  searchExchange: string
  placeholder: string
}) {
  const [open, setOpen] = useState(false)
  const debounced = useDebouncedValue(value, 300)
  const { results, isLoading, error } = useUnderlyingSearch(debounced, searchExchange, open)

  return (
    <div className="relative">
      <Input
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value.toUpperCase())
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false)
        }}
        placeholder={placeholder}
        className="font-mono"
        autoComplete="off"
      />
      {open && value.trim().length >= 2 && (
        <div className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border bg-popover shadow-md">
          {isLoading ? (
            <p className="p-3 text-center text-xs text-muted-foreground">Searching…</p>
          ) : error ? (
            <p className="p-3 text-center text-xs text-destructive">{error}</p>
          ) : results.length === 0 ? (
            <p className="p-3 text-center text-xs text-muted-foreground">
              No underlying matches “{value}” on {searchExchange}.
            </p>
          ) : (
            <ul className="divide-y">
              {results.map((result) => (
                <li key={result.symbol}>
                  <button
                    type="button"
                    // mousedown, not click: the input's blur would close the
                    // list before a click ever landed on it.
                    onMouseDown={(event) => {
                      event.preventDefault()
                      onChange(result.symbol)
                      setOpen(false)
                    }}
                    className={cn(
                      'flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-muted',
                      result.symbol === value.toUpperCase() && 'bg-primary/10 font-semibold'
                    )}
                  >
                    <span className="font-mono">{result.symbol}</span>
                    <span className="text-[10px] text-muted-foreground">{result.instruments}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

interface StrategyWizardProps {
  /** When present the form pre-fills from this strategy and saves with PATCH. */
  editing?: Strategy
}

export default function StrategyWizard({ editing }: StrategyWizardProps = {}) {
  const navigate = useNavigate()
  const isEdit = editing != null

  const initialKind: StrategyKind = editing?.strategy_kind ?? 'batch'
  const storedTab = asTab(editing?.universe_tab)
  // A signal strategy cannot sit on an index-options tab, so a new one starts
  // on the first tab its kind allows.
  const initialTab: UniverseTab =
    initialKind === 'signal' && !SIGNAL_MODE_TABS.includes(storedTab)
      ? SIGNAL_MODE_TABS[0]
      : storedTab

  const [kind, setKind] = useState<StrategyKind>(initialKind)
  const [direction, setDirection] = useState<StrategyDirection>(editing?.direction ?? 'both')
  const isSignal = kind === 'signal'

  const [tab, setTab] = useState<UniverseTab>(initialTab)
  const [name, setName] = useState(editing?.name ?? '')
  const [chosenExchange, setChosenExchange] = useState<string | null>(
    editing?.underlying_exchange ?? null
  )
  const [underlying, setUnderlying] = useState(
    editing?.underlying ?? TAB_DEFAULT_UNDERLYINGS[initialTab][0].symbol
  )
  const [strategyType, setStrategyType] = useState<StrategyType>(
    editing?.strategy_type ?? 'intraday'
  )
  const [entryTime, setEntryTime] = useState(
    editing?.entry_time ?? TAB_INTRADAY_DEFAULTS[initialTab].entry
  )
  const [exitTime, setExitTime] = useState(
    editing?.exit_time ?? TAB_INTRADAY_DEFAULTS[initialTab].exit
  )

  const [legs, setLegs] = useState<Leg[]>(() =>
    editing && editing.legs.length > 0
      ? editing.legs
      : [initialKind === 'signal' ? freshSignalLeg(1, initialTab) : freshBatchLeg(1, initialTab)]
  )

  const [product, setProduct] = useState<Product>(
    editing?.product ??
      defaultProductForLegs(
        editing?.legs ?? [
          initialKind === 'signal' ? freshSignalLeg(1, initialTab) : freshBatchLeg(1, initialTab),
        ]
      )
  )

  const [overallSl, setOverallSl] = useState(
    editing?.overall_sl_mtm != null ? String(editing.overall_sl_mtm) : ''
  )
  const [overallTarget, setOverallTarget] = useState(
    editing?.overall_target_mtm != null ? String(editing.overall_target_mtm) : ''
  )
  const [trailToEntry, setTrailToEntry] = useState(editing?.trail_sl_to_entry ?? false)
  const [lockEnabled, setLockEnabled] = useState(editing?.lock_profit != null)
  const [lockMode, setLockMode] = useState<LockProfitMode>(editing?.lock_profit?.mode ?? 'lock')
  const [lockProfitReaches, setLockProfitReaches] = useState(
    editing?.lock_profit?.if_profit_reaches != null
      ? String(editing.lock_profit.if_profit_reaches)
      : ''
  )
  const [lockProfitFloor, setLockProfitFloor] = useState(
    editing?.lock_profit?.lock_profit != null ? String(editing.lock_profit.lock_profit) : ''
  )
  const [lockTrailStep, setLockTrailStep] = useState(
    editing?.lock_profit?.trail_step != null ? String(editing.lock_profit.trail_step) : ''
  )
  const [dailyLossLimit, setDailyLossLimit] = useState(
    editing?.daily_loss_limit_inr != null ? String(editing.daily_loss_limit_inr) : ''
  )

  const [schedulerEnabled, setSchedulerEnabled] = useState(editing?.scheduler?.enabled ?? false)
  const [schedulerStart, setSchedulerStart] = useState(editing?.scheduler?.start_time ?? '09:15')
  const [schedulerStop, setSchedulerStop] = useState(editing?.scheduler?.auto_stop_time ?? '15:20')

  const [strikePickerLegIndex, setStrikePickerLegIndex] = useState<number | null>(null)

  const closedUniverse = TAB_UNDERLYING_IS_CLOSED_SET[tab]
  const seededUnderlyings = TAB_DEFAULT_UNDERLYINGS[tab]

  // On a closed-universe tab the exchange comes from the seed entry; on an open
  // one every underlying on the tab is listed on the same exchange.
  // On a closed-universe tab the exchange follows the index that was picked:
  // NIFTY is quoted on NSE_INDEX and SENSEX on BSE_INDEX, and there is nothing
  // to choose. On an open one the operator chooses, because the same typed
  // symbol is listed on both venues: RELIANCE trades on NSE and on BSE.
  //
  // The explicit choice wins over the seed. Preferring the seed meant a stock
  // that happens to be in the tab's seed list, which is most of them, silently
  // went back to NSE the moment it was named, so BSE could be selected and
  // never submitted.
  const underlyingExchange = useMemo(() => {
    const seeded = seededUnderlyings.find((choice) => choice.symbol === underlying)?.exchange
    if (closedUniverse) return seeded ?? TAB_DEFAULT_EXCHANGE[tab]
    return chosenExchange ?? seeded ?? TAB_DEFAULT_EXCHANGE[tab]
  }, [underlying, seededUnderlyings, tab, chosenExchange, closedUniverse])

  const exchangeChoices = TAB_UNDERLYING_EXCHANGES[tab]

  // Expiry lists are per (underlying, instrument), not per leg: ten legs on one
  // underlying ask the platform once. Only fetched for the instrument types the
  // legs actually use.
  // Signal legs resolve their own expiries per card, against their own symbol,
  // so the strategy-level lookup is batch-only.
  const hasOptionsLeg = useMemo(
    () => !isSignal && legs.some((leg) => leg.segment === 'options'),
    [legs, isSignal]
  )
  const hasFuturesLeg = useMemo(
    () => !isSignal && legs.some((leg) => leg.segment === 'futures'),
    [legs, isSignal]
  )
  const optionExpiries = useExpiryResolution(
    underlying,
    underlyingExchange,
    'options',
    hasOptionsLeg
  )
  const futureExpiries = useExpiryResolution(
    underlying,
    underlyingExchange,
    'futures',
    hasFuturesLeg
  )

  const expiryStateFor = (leg: Leg): LegExpiryState => {
    if (leg.segment === 'cash' || !leg.expiry) {
      return { date: null, isLoading: false, error: null }
    }
    const source: ExpiryResolution = leg.segment === 'futures' ? futureExpiries : optionExpiries
    return {
      date: source.resolve(leg.expiry),
      isLoading: source.isLoading,
      error: source.error,
    }
  }

  const allowedProducts = useMemo(() => allowedProductsForLegs(legs), [legs])
  useEffect(() => {
    // Snap the product back into range when the leg composition changes: a
    // basket that gains a cash leg can no longer carry NRML.
    if (!allowedProducts.includes(product)) setProduct(allowedProducts[0])
  }, [allowedProducts, product])

  const freshLegFor = (id: number, forTab: UniverseTab, forKind: StrategyKind): Leg =>
    forKind === 'signal' ? freshSignalLeg(id, forTab) : freshBatchLeg(id, forTab)

  const onTabChange = (next: UniverseTab) => {
    setTab(next)
    setUnderlying(TAB_DEFAULT_UNDERLYINGS[next][0].symbol)
    setChosenExchange(TAB_DEFAULT_EXCHANGE[next])
    const seeded = [freshLegFor(1, next, kind)]
    setLegs(seeded)
    setEntryTime(TAB_INTRADAY_DEFAULTS[next].entry)
    setExitTime(TAB_INTRADAY_DEFAULTS[next].exit)
    setProduct(defaultProductForLegs(seeded))
  }

  /**
   * Switch the strategy between kinds.
   *
   * The legs are reshaped rather than thrown away: the per-leg risk the user
   * has already typed means the same thing under both kinds. What cannot
   * survive is the shape - a leg keeping `strike_mode` into signal mode would
   * produce a payload the server refuses, naming a field no longer on screen.
   */
  const onKindChange = (next: StrategyKind) => {
    if (isEdit || next === kind) return
    const nextTab: UniverseTab =
      next === 'signal' && !SIGNAL_MODE_TABS.includes(tab) ? SIGNAL_MODE_TABS[0] : tab
    const reshaped = legs.map((leg) => convertLegKind(leg, next, nextTab))
    setKind(next)
    setTab(nextTab)
    setLegs(reshaped)
    if (nextTab !== tab) {
      setUnderlying(TAB_DEFAULT_UNDERLYINGS[nextTab][0].symbol)
      setEntryTime(TAB_INTRADAY_DEFAULTS[nextTab].entry)
      setExitTime(TAB_INTRADAY_DEFAULTS[nextTab].exit)
    }
    setProduct(defaultProductForLegs(reshaped))
  }

  const addLeg = () => {
    if (legs.length >= MAX_LEGS) {
      showToast.error(`Up to ${MAX_LEGS} legs per strategy`)
      return
    }
    setLegs([...legs, freshLegFor((legs.at(-1)?.id ?? 0) + 1, tab, kind)])
  }

  const updateLeg = (index: number, next: Leg) => {
    const copy = legs.slice()
    copy[index] = next
    setLegs(copy)
  }

  const removeLeg = (index: number) => {
    if (legs.length <= 1) return
    setLegs(legs.filter((_, i) => i !== index))
  }

  const [revealedToken, setRevealedToken] = useState<{
    token: string
    strategyId: number
  } | null>(null)

  const createMutation = useMutation({
    mutationFn: (payload: StrategyConfigPayload) => createStrategy(payload),
    onSuccess: (created) => {
      setRevealedToken({ token: created.webhook_token, strategyId: created.strategy.id })
    },
    onError: (err: Error) => showToast.error(err.message || 'Failed to create strategy'),
  })

  const updateMutation = useMutation({
    mutationFn: (payload: StrategyUpdatePayload) => updateStrategy(editing?.id ?? 0, payload),
    onSuccess: (updated) => {
      showToast.success('Strategy updated')
      navigate(`/strategy/${updated.id}`)
    },
    onError: (err: Error) => showToast.error(err.message || 'Failed to update strategy'),
  })

  /** Everything the server would refuse, refused here with a clearer message. */
  const validate = (): string | null => {
    if (!name.trim()) return 'Name is required'
    if (!isSignal && !underlying.trim()) return 'Underlying is required'
    if (strategyType === 'intraday') {
      if (!entryTime) return 'Entry time is required for an intraday strategy'
      if (!exitTime) return 'Exit time is required for an intraday strategy'
      if (entryTime >= exitTime) return 'Entry time must be earlier than exit time'
    }
    // A short cash leg the product cannot carry. Indian cash equity is sold
    // short intraday and never carried short, and the product is read as
    // intent: anything that is not MIS reaches a cash venue as CNC, which
    // makes the order a naked short delivery the broker refuses.
    if (product !== 'MIS') {
      for (const leg of legs) {
        if (leg.segment !== 'cash') continue
        if (leg.position === 'S' || leg.side === 'short') {
          return `Leg ${leg.id}: cash cannot be held short overnight. Use MIS for an intraday short, or make the leg long.`
        }
      }
    }
    for (const leg of legs) {
      if (isSignal) {
        if (!leg.symbol?.trim()) return `Leg ${leg.id}: symbol is required`
        if (!leg.exchange?.trim()) return `Leg ${leg.id}: exchange is required`
        if (!SIGNAL_LEG_EXCHANGES.includes(leg.exchange.trim().toUpperCase())) {
          return `Leg ${leg.id}: ${leg.exchange.trim().toUpperCase()} is not a venue this module trades. Use one of ${SIGNAL_LEG_EXCHANGES.join(', ')}.`
        }
        if (!segmentSuitsExchange(leg.segment, leg.exchange)) {
          return `Leg ${leg.id}: a ${leg.segment} leg cannot trade on ${leg.exchange.trim().toUpperCase()}.`
        }
        if (!DIRECTION_ACCEPTS[direction].includes(leg.side ?? 'both')) {
          return `Leg ${leg.id}: side ${leg.side} is one a ${direction} strategy never acts on. Change the side, or the strategy direction.`
        }
        const qty = Number(leg.qty)
        if (!Number.isInteger(qty) || qty < 1) {
          return `Leg ${leg.id}: quantity must be a whole number of at least 1`
        }
        // Lots and units have different caps, because a lot count is a much
        // smaller number than the quantity it stands for.
        const mode = isDerivativeExchange(leg.exchange)
          ? (leg.qty_mode ?? defaultQtyMode(leg.exchange))
          : 'units'
        const cap = maxQtyFor(mode)
        if (qty > cap) {
          return `Leg ${leg.id}: ${mode === 'lots' ? 'lots' : 'quantity'} cannot be more than ${cap.toLocaleString('en-IN')}`
        }
        continue
      }
      if (leg.segment === 'options' && leg.strike_mode === 'strike') {
        if (leg.strike == null || leg.strike <= 0) {
          return `Leg ${leg.id}: pick a strike, or switch the leg to ATM-relative`
        }
      }
      // Shares on cash, lots on a derivative. They are not the same number.
      const cap = maxBatchQuantityFor(leg.segment)
      if ((leg.lots ?? 1) > cap) {
        const counted = leg.segment === 'cash' ? 'quantity' : 'lots'
        return `Leg ${leg.id}: ${counted} cannot be more than ${cap.toLocaleString('en-IN')}`
      }
      if (!TAB_SEGMENTS[tab].includes(leg.segment)) {
        return `Leg ${leg.id}: the ${UNIVERSE_TAB_LABELS[tab]} universe does not trade ${leg.segment}.`
      }
    }
    if (lockEnabled) {
      const reaches = Number(lockProfitReaches)
      const floor = Number(lockProfitFloor)
      if (!lockProfitReaches || reaches <= 0) return 'Lock-profit: enter the profit that arms it'
      if (!lockProfitFloor || floor < 0) return 'Lock-profit: enter the floor to lock'
      if (floor > reaches) {
        return 'Lock-profit: the floor cannot be above the profit that arms it'
      }
      if (lockMode === 'lock_and_trail' && (!lockTrailStep || Number(lockTrailStep) <= 0)) {
        return 'Lock-profit: a trail step is required for Lock + Trail'
      }
    }
    if (schedulerEnabled) {
      if (!schedulerStart) return 'Scheduler: a start time is required'
      if (!schedulerStop) return 'Scheduler: an auto-stop time is required'
      if (schedulerStart >= schedulerStop) {
        return 'Scheduler: the start time must be earlier than the auto-stop time'
      }
    }
    return null
  }

  const submit = () => {
    const problem = validate()
    if (problem) {
      showToast.error(problem)
      return
    }

    // The strategy row still carries one underlying, but a signal strategy's
    // legs each name their own instrument. The first leg stands in, so the
    // list and the detail header have something meaningful to show.
    const firstLeg = legs[0]
    const submittedUnderlying = isSignal
      ? firstLeg?.symbol?.trim().toUpperCase() || 'MULTI'
      : underlying.trim().toUpperCase()
    const submittedExchange = isSignal
      ? firstLeg?.exchange?.trim().toUpperCase() || TAB_DEFAULT_EXCHANGE[tab]
      : underlyingExchange

    const payload: StrategyConfigPayload = {
      name: name.trim(),
      strategy_kind: kind,
      direction,
      universe_tab: tab,
      underlying: submittedUnderlying,
      underlying_exchange: submittedExchange,
      strategy_type: strategyType,
      entry_time: strategyType === 'intraday' ? entryTime : null,
      exit_time: strategyType === 'intraday' ? exitTime : null,
      product,
      pricetype: 'MARKET',
      legs: legs.map((leg) => legToPayload(leg, kind)),
      overall_sl_mtm: overallSl ? Number(overallSl) : null,
      overall_target_mtm: overallTarget ? Number(overallTarget) : null,
      trail_sl_to_entry: trailToEntry,
      daily_loss_limit_inr: dailyLossLimit ? Number(dailyLossLimit) : null,
      lock_profit: lockEnabled
        ? {
            mode: lockMode,
            if_profit_reaches: Number(lockProfitReaches),
            lock_profit: Number(lockProfitFloor),
            trail_step: lockMode === 'lock_and_trail' ? Number(lockTrailStep) : null,
          }
        : null,
      scheduler: schedulerEnabled
        ? {
            enabled: true,
            days: ['MON', 'TUE', 'WED', 'THU', 'FRI'],
            start_time: schedulerStart,
            auto_stop_time: schedulerStop,
            default_mode: 'sandbox',
          }
        : null,
    }

    if (isEdit) {
      // The kind is fixed once a strategy exists: its legs mean different
      // things to the engine under each one.
      const { strategy_kind: _kind, ...update } = payload
      void _kind
      updateMutation.mutate(update)
    } else {
      createMutation.mutate(payload)
    }
  }

  const submitting = isEdit ? updateMutation.isPending : createMutation.isPending
  const pickerLeg = strikePickerLegIndex !== null ? legs[strikePickerLegIndex] : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {isEdit ? `Edit "${editing?.name}"` : 'New strategy'}
        </h1>
        <p className="text-sm text-muted-foreground">
          {isEdit
            ? 'Edits are committed immediately. The webhook token is preserved - rotate it from the Webhook tab if needed.'
            : 'Configure legs and risk. Sandbox-only until you explicitly enable live mode on the detail page.'}
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Strategy kind</CardTitle>
          <CardDescription>
            {isEdit
              ? 'Kind is locked after the strategy is created.'
              : 'Pick how the strategy is driven. This cannot be changed later.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(['batch', 'signal'] as StrategyKind[]).map((option) => (
              <button
                key={option}
                type="button"
                disabled={isEdit && option !== kind}
                onClick={() => onKindChange(option)}
                className={cn(
                  'rounded-md border p-3 text-left transition-colors',
                  kind === option
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:bg-muted/50',
                  isEdit && option !== kind && 'cursor-not-allowed opacity-40'
                )}
              >
                <div className="text-sm font-medium">{STRATEGY_KIND_LABELS[option]}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {STRATEGY_KIND_HINT[option]}
                </div>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {UNIVERSE_TABS.map((option) => {
              const unavailable = isSignal && !SIGNAL_MODE_TABS.includes(option)
              return (
                <button
                  key={option}
                  type="button"
                  disabled={unavailable}
                  onClick={() => !unavailable && onTabChange(option)}
                  className={cn(
                    'rounded-md border p-3 text-left transition-colors',
                    tab === option
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:bg-muted/50',
                    unavailable && 'cursor-not-allowed opacity-40'
                  )}
                >
                  <div className="text-sm font-medium">{UNIVERSE_TAB_LABELS[option]}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {UNIVERSE_TAB_HINT[option]}
                  </div>
                  {unavailable && (
                    <div className="mt-1 text-[10px] uppercase text-muted-foreground">
                      not available in signal mode
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {isSignal && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Direction filter</CardTitle>
            <CardDescription>
              Restricts which signals the engine accepts. Long-only ignores short_entry / short_exit
              signals; short-only ignores the long ones. Both accepts all four.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <div className="flex overflow-hidden rounded-md border border-input">
              {(['both', 'long_only', 'short_only'] as StrategyDirection[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setDirection(option)}
                  className={cn(
                    'flex-1 px-3 py-2 text-sm font-medium transition-colors',
                    direction === option
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background hover:bg-muted'
                  )}
                >
                  {STRATEGY_DIRECTION_LABELS[option]}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Index and Timings</CardTitle>
          <CardDescription>
            Pick the underlying and (for intraday) entry/exit windows.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="strategy-name">Strategy name</Label>
              <Input
                id="strategy-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Iron condor weekly"
                maxLength={MAX_NAME_LENGTH}
              />
            </div>

            {isSignal ? (
              <div className="space-y-1.5 rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                Signal mode: each leg picks its own symbol below. The strategy row shows the first
                leg's symbol as its label.
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="underlying">Underlying</Label>
                {closedUniverse ? (
                  <select
                    id="underlying"
                    value={underlying}
                    onChange={(event) => setUnderlying(event.target.value)}
                    className={SELECT_CLASS_MD}
                  >
                    {seededUnderlyings.map((choice) => (
                      <option key={choice.symbol} value={choice.symbol}>
                        {choice.symbol} — {choice.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <UnderlyingSearchField
                    id="underlying"
                    value={underlying}
                    onChange={setUnderlying}
                    searchExchange={underlyingExchange}
                    placeholder={`Search ${seededUnderlyings[0]?.symbol ?? 'symbol'}…`}
                  />
                )}
                {exchangeChoices.length > 1 && !closedUniverse ? (
                  <div className="flex items-center gap-2 pt-0.5">
                    <Label htmlFor="underlying-exchange" className="text-xs text-muted-foreground">
                      Exchange
                    </Label>
                    <select
                      id="underlying-exchange"
                      value={underlyingExchange}
                      onChange={(event) => setChosenExchange(event.target.value)}
                      className={`${SELECT_CLASS_SM} w-28 font-mono`}
                    >
                      {exchangeChoices.map((venue) => (
                        <option key={venue} value={venue}>
                          {venue}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Exchange: <span className="font-mono">{underlyingExchange}</span>
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label>Strategy type</Label>
              <div className="flex h-10 overflow-hidden rounded-md border border-input">
                {(['intraday', 'positional'] as StrategyType[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setStrategyType(option)}
                    className={cn(
                      'flex-1 text-sm font-medium transition-colors',
                      strategyType === option
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background hover:bg-muted'
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>

            {strategyType === 'intraday' && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="entry-time">Entry time (IST)</Label>
                  <Input
                    id="entry-time"
                    type="time"
                    value={entryTime}
                    onChange={(event) => setEntryTime(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="exit-time">Exit time (IST)</Label>
                  <Input
                    id="exit-time"
                    type="time"
                    value={exitTime}
                    onChange={(event) => setExitTime(event.target.value)}
                  />
                </div>
              </>
            )}
          </div>

          {strategyType === 'intraday' ? (
            <p className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
              Intraday signals only execute after your entry time and auto-exit at exit time.
            </p>
          ) : (
            <p className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
              Positional strategies activate on signal and exit automatically at contract expiry.
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="product">Product</Label>
              <select
                id="product"
                value={product}
                onChange={(event) => setProduct(event.target.value as Product)}
                className={SELECT_CLASS_MD}
              >
                {allowedProducts.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{productHintForLegs(legs, product)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Leg Builder</CardTitle>
            <CardDescription>
              Up to {MAX_LEGS} legs. Add as many as you need; remove the rest.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={addLeg}>
            + Add leg
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {isSignal && (
            <p className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
              Each leg reacts to long_entry / long_exit / short_entry / short_exit webhooks instead
              of being entered with the rest at start. The direction filter above decides which of
              the four the strategy accepts at all; each leg's Side narrows that further.
            </p>
          )}
          {legs.map((leg, index) =>
            isSignal ? (
              <SignalLegCard
                key={leg.id}
                leg={leg}
                tab={tab}
                index={index}
                onChange={(next) => updateLeg(index, next)}
                onRemove={() => removeLeg(index)}
                removable={legs.length > 1}
              />
            ) : (
              <LegCard
                key={leg.id}
                leg={leg}
                tab={tab}
                index={index}
                expiry={expiryStateFor(leg)}
                onChange={(next) => updateLeg(index, next)}
                onRemove={() => removeLeg(index)}
                onOpenStrikePicker={() => setStrikePickerLegIndex(index)}
                removable={legs.length > 1}
              />
            )
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Overall Strategy Settings</CardTitle>
          <CardDescription>
            Strategy-level risk applied across all legs. Evaluated against total MTM (realized +
            unrealized).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="overall-sl">Overall SL (₹ MTM)</Label>
              <Input
                id="overall-sl"
                type="number"
                min={0}
                step={1}
                value={overallSl}
                onChange={(event) => setOverallSl(event.target.value)}
                placeholder="empty = off"
              />
              <p className="text-xs text-muted-foreground">
                Enter as positive — applied as a negative threshold.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="overall-target">Overall Target (₹ MTM)</Label>
              <Input
                id="overall-target"
                type="number"
                min={0}
                step={1}
                value={overallTarget}
                onChange={(event) => setOverallTarget(event.target.value)}
                placeholder="empty = off"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="daily-loss-limit">Daily loss limit (₹)</Label>
              <Input
                id="daily-loss-limit"
                type="number"
                min={0}
                step={1}
                value={dailyLossLimit}
                onChange={(event) => setDailyLossLimit(event.target.value)}
                placeholder="empty = off"
              />
              <p className="text-xs text-muted-foreground">Also entered as a positive amount.</p>
            </div>
          </div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={lockEnabled}
                onChange={(event) => setLockEnabled(event.target.checked)}
              />
              Enable Lock-Profit
            </label>
            {lockEnabled && (
              <div className="space-y-3 rounded-md border border-dashed p-3">
                <div className="flex h-10 overflow-hidden rounded-md border border-input">
                  {(['lock', 'lock_and_trail'] as LockProfitMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setLockMode(mode)}
                      className={cn(
                        'flex-1 text-sm font-medium transition-colors',
                        lockMode === mode
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-background hover:bg-muted'
                      )}
                    >
                      {mode === 'lock' ? 'Lock (static floor)' : 'Lock + Trail (rising floor)'}
                    </button>
                  ))}
                </div>
                <div
                  className={cn(
                    'grid gap-3 sm:grid-cols-2',
                    lockMode === 'lock_and_trail' && 'sm:grid-cols-3'
                  )}
                >
                  <div className="space-y-1.5">
                    <Label className="text-xs uppercase">If profit reaches (₹)</Label>
                    <Input
                      type="number"
                      min={0}
                      value={lockProfitReaches}
                      onChange={(event) => setLockProfitReaches(event.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs uppercase">Lock floor (₹)</Label>
                    <Input
                      type="number"
                      min={0}
                      value={lockProfitFloor}
                      onChange={(event) => setLockProfitFloor(event.target.value)}
                    />
                  </div>
                  {lockMode === 'lock_and_trail' && (
                    <div className="space-y-1.5">
                      <Label className="text-xs uppercase">Trail step (₹)</Label>
                      <Input
                        type="number"
                        min={0}
                        value={lockTrailStep}
                        onChange={(event) => setLockTrailStep(event.target.value)}
                      />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={trailToEntry}
              onChange={(event) => setTrailToEntry(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Trail SL to entry price</span>
              <span className="ml-2 text-xs text-muted-foreground">
                When ANY leg's SL fires, every other open leg's SL moves to its entry.
              </span>
            </span>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduler</CardTitle>
          <CardDescription>
            Optional cron-based start. Mon–Fri default. Times are interpreted in IST (Asia/Kolkata).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={schedulerEnabled}
              onChange={(event) => setSchedulerEnabled(event.target.checked)}
            />
            Enable scheduled start (Mon–Fri)
          </label>
          {schedulerEnabled && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>Start time (IST)</Label>
                <Input
                  type="time"
                  value={schedulerStart}
                  onChange={(event) => setSchedulerStart(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Auto-stop time (IST)</Label>
                <Input
                  type="time"
                  value={schedulerStop}
                  onChange={(event) => setSchedulerStop(event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Required: a scheduled start with nothing to stop it runs until the session ends.
                </p>
              </div>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            The webhook token is generated automatically on save and shown to you once. Copy it into
            TradingView.
          </p>
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-3">
        <Button
          variant="outline"
          onClick={() => navigate(isEdit ? `/strategy/${editing?.id}` : '/strategy')}
        >
          Cancel
        </Button>
        <Button onClick={submit} disabled={submitting}>
          {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Save and Continue'}
        </Button>
      </div>

      {pickerLeg && strikePickerLegIndex !== null && (
        <StrikePickerDialog
          open
          onOpenChange={(open) => {
            if (!open) setStrikePickerLegIndex(null)
          }}
          underlying={underlying}
          underlyingExchange={underlyingExchange}
          expiryRank={pickerLeg.expiry ?? 'monthly'}
          resolvedExpiry={expiryStateFor(pickerLeg).date}
          optionType={pickerLeg.option_type ?? 'CE'}
          selectedStrike={pickerLeg.strike ?? null}
          onPick={(strike) => {
            updateLeg(strikePickerLegIndex, { ...pickerLeg, strike })
          }}
        />
      )}

      <Dialog
        open={revealedToken !== null}
        onOpenChange={(open) => {
          if (!open && revealedToken) navigate(`/strategy/${revealedToken.strategyId}`)
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Strategy created — copy your webhook token</DialogTitle>
            <DialogDescription>
              This token is stored as a hash and cannot be shown again. If you lose it, rotate the
              token from the Webhook tab.
            </DialogDescription>
          </DialogHeader>

          {revealedToken && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Webhook URL</Label>
                <div className="flex items-center gap-2">
                  <Input
                    readOnly
                    value={`${window.location.origin}/strategy/webhook/${revealedToken.token}`}
                    className="font-mono text-xs"
                  />
                  <Button
                    size="sm"
                    onClick={() => {
                      navigator.clipboard.writeText(
                        `${window.location.origin}/strategy/webhook/${revealedToken.token}`
                      )
                      showToast.success('Copied URL')
                    }}
                  >
                    Copy
                  </Button>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>TradingView alert message body</Label>
                <pre className="rounded-md bg-muted p-3 text-xs">
                  {'{"action":"start","mode":"sandbox"}'}
                </pre>
              </div>
              <p className="text-xs text-muted-foreground">
                Token:{' '}
                <Badge variant="outline" className="font-mono">
                  {revealedToken.token}
                </Badge>
              </p>
            </div>
          )}

          <DialogFooter>
            <Button
              onClick={() => {
                if (revealedToken) navigate(`/strategy/${revealedToken.strategyId}`)
              }}
            >
              I've copied it — continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
