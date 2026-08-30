// pages/strategy/Wizard.tsx
// Create or edit a strategy. One page, not a stepped wizard: every section is
// visible at once so the shape of the whole strategy is readable while any part
// of it is being changed.

import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { createStrategy, updateStrategy } from '@/api/strategy_module'
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
  defaultProductForLegs,
  EXPIRY_RANK_LABELS,
  type ExpiryRank,
  expiriesFor,
  type Leg,
  type LegPosition,
  type LockProfitMode,
  MAX_LEGS,
  MAX_LOTS,
  MAX_NAME_LENGTH,
  type OptionType,
  type Product,
  type Segment,
  STRATEGY_DIRECTION_LABELS,
  STRATEGY_KIND_HINT,
  STRATEGY_KIND_LABELS,
  type Strategy,
  type StrategyConfigPayload,
  type StrategyDirection,
  type StrategyKind,
  type StrategyType,
  type StrategyUpdatePayload,
  TAB_DEFAULT_EXCHANGE,
  TAB_DEFAULT_UNDERLYINGS,
  TAB_INTRADAY_DEFAULTS,
  TAB_SEGMENTS,
  TAB_UNDERLYING_IS_CLOSED_SET,
  UNIVERSE_TAB_HINT,
  UNIVERSE_TAB_LABELS,
  UNIVERSE_TABS,
  type UniverseTab,
} from '@/types/strategy_module'
import { showToast } from '@/utils/toast'

const SELECT_CLASS_SM = 'flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm'
const SELECT_CLASS_MD = 'flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm'

/** A tab the wizard knows, or the default when a stored value is unfamiliar. */
function asTab(value: string | undefined): UniverseTab {
  return UNIVERSE_TABS.includes(value as UniverseTab) ? (value as UniverseTab) : 'weekly_monthly'
}

function freshLeg(id: number, tab: UniverseTab): Leg {
  return {
    id,
    segment: 'options',
    position: 'S',
    lots: 1,
    option_type: 'CE',
    strike_mode: 'atm',
    atm_offset: 'ATM',
    strike: null,
    expiry: expiriesFor(tab, 'options')[0],
    sl_pts: null,
    target_pts: null,
    trail: { x: 0, y: 0 },
  }
}

/**
 * A leg reduced to what the validator accepts.
 *
 * The optional fields are conditionally forbidden rather than merely optional:
 * an `atm_offset` sent alongside `strike_mode: "strike"` is refused outright,
 * as is any options field on a futures leg. Pruning here rather than at each
 * form control means the form can keep a field's last value while the user
 * toggles a mode back and forth without that value leaking into the request.
 */
function legToPayload(leg: Leg): Leg {
  const clean: Leg = {
    id: leg.id,
    segment: leg.segment,
    position: leg.position,
    lots: leg.lots,
  }
  if (leg.segment !== 'cash') clean.expiry = leg.expiry
  if (leg.segment === 'options') {
    clean.option_type = leg.option_type ?? 'CE'
    clean.strike_mode = leg.strike_mode ?? 'atm'
    if (clean.strike_mode === 'atm') clean.atm_offset = leg.atm_offset ?? 'ATM'
    else clean.strike = leg.strike ?? null
  }
  if (leg.sl_pts != null) clean.sl_pts = leg.sl_pts
  if (leg.target_pts != null) clean.target_pts = leg.target_pts
  if (leg.trail && (leg.trail.x > 0 || leg.trail.y > 0)) clean.trail = leg.trail
  return clean
}

// ---------------------------------------------------------------------------
// Leg card
// ---------------------------------------------------------------------------

interface LegCardProps {
  leg: Leg
  tab: UniverseTab
  index: number
  onChange: (next: Leg) => void
  onRemove: () => void
  removable: boolean
}

function LegCard({ leg, tab, index, onChange, onRemove, removable }: LegCardProps) {
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
                {expiries.map((expiry) => (
                  <option key={expiry} value={expiry}>
                    {EXPIRY_RANK_LABELS[expiry]}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Lots</Label>
            <Input
              type="number"
              min={1}
              max={MAX_LOTS}
              value={leg.lots}
              onChange={(event) =>
                update('lots', Math.max(1, Number.parseInt(event.target.value || '1', 10)))
              }
              className="h-9"
            />
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
                <Input
                  type="number"
                  step={0.01}
                  value={leg.strike ?? ''}
                  placeholder="e.g. 25000"
                  onChange={(event) =>
                    update('strike', event.target.value === '' ? null : Number(event.target.value))
                  }
                  className="h-9 font-mono"
                />
                <p className="text-xs text-muted-foreground">
                  Resolved against the underlying and the leg's expiry rank ({leg.expiry}) when the
                  run starts.
                </p>
              </div>
            )}
          </div>
        )}

        <Separator />

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Stop Loss (pts)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={leg.sl_pts ?? ''}
              placeholder="0 = off"
              onChange={(event) =>
                update('sl_pts', event.target.value === '' ? null : Number(event.target.value))
              }
              className="h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase">Target (pts)</Label>
            <Input
              type="number"
              step={0.01}
              min={0}
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
// Wizard
// ---------------------------------------------------------------------------

interface StrategyWizardProps {
  /** When present the form pre-fills from this strategy and saves with PATCH. */
  editing?: Strategy
}

export default function StrategyWizard({ editing }: StrategyWizardProps = {}) {
  const navigate = useNavigate()
  const isEdit = editing != null

  const initialTab = asTab(editing?.universe_tab)

  const [kind, setKind] = useState<StrategyKind>(editing?.strategy_kind ?? 'batch')
  const [direction, setDirection] = useState<StrategyDirection>(editing?.direction ?? 'both')
  const isSignal = kind === 'signal'

  const [tab, setTab] = useState<UniverseTab>(initialTab)
  const [name, setName] = useState(editing?.name ?? '')
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
    editing && editing.legs.length > 0 ? editing.legs : [freshLeg(1, initialTab)]
  )

  const [product, setProduct] = useState<Product>(
    editing?.product ?? defaultProductForLegs(editing?.legs ?? [freshLeg(1, initialTab)])
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

  const underlyings = TAB_DEFAULT_UNDERLYINGS[tab]
  const underlyingExchange = useMemo(
    () =>
      underlyings.find((choice) => choice.symbol === underlying)?.exchange ??
      TAB_DEFAULT_EXCHANGE[tab],
    [underlying, underlyings, tab]
  )

  const allowedProducts = useMemo(() => allowedProductsForLegs(legs), [legs])
  useEffect(() => {
    // Snap the product back into range when the leg composition changes: a
    // basket that gains a cash leg can no longer carry NRML.
    if (!allowedProducts.includes(product)) setProduct(allowedProducts[0])
  }, [allowedProducts, product])

  const onTabChange = (next: UniverseTab) => {
    setTab(next)
    setUnderlying(TAB_DEFAULT_UNDERLYINGS[next][0].symbol)
    const seeded = [freshLeg(1, next)]
    setLegs(seeded)
    setEntryTime(TAB_INTRADAY_DEFAULTS[next].entry)
    setExitTime(TAB_INTRADAY_DEFAULTS[next].exit)
    setProduct(defaultProductForLegs(seeded))
  }

  const addLeg = () => {
    if (legs.length >= MAX_LEGS) {
      showToast.error(`Up to ${MAX_LEGS} legs per strategy`)
      return
    }
    setLegs([...legs, freshLeg((legs.at(-1)?.id ?? 0) + 1, tab)])
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
    if (!underlying.trim()) return 'Underlying is required'
    if (strategyType === 'intraday') {
      if (!entryTime) return 'Entry time is required for an intraday strategy'
      if (!exitTime) return 'Exit time is required for an intraday strategy'
      if (entryTime >= exitTime) return 'Entry time must be earlier than exit time'
    }
    for (const leg of legs) {
      if (leg.segment === 'options' && leg.strike_mode === 'strike') {
        if (leg.strike == null || leg.strike <= 0) {
          return `Leg ${leg.id}: a direct strike is required`
        }
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

    const payload: StrategyConfigPayload = {
      name: name.trim(),
      strategy_kind: kind,
      direction,
      universe_tab: tab,
      underlying: underlying.trim().toUpperCase(),
      underlying_exchange: underlyingExchange,
      strategy_type: strategyType,
      entry_time: strategyType === 'intraday' ? entryTime : null,
      exit_time: strategyType === 'intraday' ? exitTime : null,
      product,
      pricetype: 'MARKET',
      legs: legs.map(legToPayload),
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
      webhook_ip_allowlist: null,
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
  const closedUniverse = TAB_UNDERLYING_IS_CLOSED_SET[tab]

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
                onClick={() => !isEdit && setKind(option)}
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
            {UNIVERSE_TABS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onTabChange(option)}
                className={cn(
                  'rounded-md border p-3 text-left transition-colors',
                  tab === option
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:bg-muted/50'
                )}
              >
                <div className="text-sm font-medium">{UNIVERSE_TAB_LABELS[option]}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {UNIVERSE_TAB_HINT[option]}
                </div>
              </button>
            ))}
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

            <div className="space-y-1.5">
              <Label htmlFor="underlying">Underlying</Label>
              {closedUniverse ? (
                <select
                  id="underlying"
                  value={underlying}
                  onChange={(event) => setUnderlying(event.target.value)}
                  className={SELECT_CLASS_MD}
                >
                  {underlyings.map((choice) => (
                    <option key={choice.symbol} value={choice.symbol}>
                      {choice.symbol} — {choice.name}
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <Input
                    id="underlying"
                    list="strategy-underlyings"
                    value={underlying}
                    onChange={(event) => setUnderlying(event.target.value.toUpperCase())}
                    placeholder={underlyings[0]?.symbol}
                    className="font-mono"
                  />
                  <datalist id="strategy-underlyings">
                    {underlyings.map((choice) => (
                      <option key={choice.symbol} value={choice.symbol}>
                        {choice.name}
                      </option>
                    ))}
                  </datalist>
                </>
              )}
              <p className="text-xs text-muted-foreground">
                Exchange: <span className="font-mono">{underlyingExchange}</span>
              </p>
            </div>
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
              <p className="text-xs text-muted-foreground">
                {allowedProducts.length === 1
                  ? 'Mixed cash + derivatives legs: only MIS works for both.'
                  : allowedProducts.includes('CNC')
                    ? 'Cash equity: CNC (delivery) or MIS (intraday).'
                    : 'Derivatives: NRML (carry) or MIS (intraday).'}
              </p>
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
              Signal mode drives these same legs from long_entry / long_exit / short_entry /
              short_exit webhooks instead of entering them all at start. Each leg keeps the contract
              configured here; the direction filter above decides which signals are accepted.
            </p>
          )}
          {legs.map((leg, index) => (
            <LegCard
              key={leg.id}
              leg={leg}
              tab={tab}
              index={index}
              onChange={(next) => updateLeg(index, next)}
              onRemove={() => removeLeg(index)}
              removable={legs.length > 1}
            />
          ))}
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
