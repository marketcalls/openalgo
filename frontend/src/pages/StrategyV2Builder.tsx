/**
 * Strategy v2 — builder/detail page.
 *
 * Mirrors images 1, 3, 4, 5 from the plan: segment-aware leg builder
 * (Cash / Futures / Options) with per-leg risk controls (Target / Stop Loss /
 * Trail SL X-Y / Simple Momentum), each in pts or %. Image 2's overall
 * settings (Overall SL / Overall Target / Lock Profit / Trail-to-entry) are
 * abs ₹ only at the strategy level — strategy capital is not tracked.
 *
 * URLs:
 *   /strategy/v2/new            → blank create form
 *   /strategy/v2/<id>           → edit existing strategy
 *
 * Webhook security UI is in a sibling dialog (StrategyV2WebhookDialog) so
 * the one-time secret display + rotate flow + test button stays contained.
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { strategyV2Api } from '@/api/strategy_v2'
import type {
  ExpiryType,
  LegPayload,
  OptionType,
  Position,
  ProductType,
  RiskUnit,
  Segment,
  StrategyLeg,
  StrategyRiskConfig,
  StrategyV2,
  StrategyV2CreatePayload,
} from '@/types/strategy_v2'

import StrategyV2WebhookDialog from './StrategyV2WebhookDialog'

// ---------------------------------------------------------------------------
// Local form-state types — aligned with LegPayload but with all fields
// always present so controlled inputs stay simple.
// ---------------------------------------------------------------------------

interface LegFormState {
  segment: Segment
  position: Position
  product: ProductType

  symbol_cash: string
  qty: number

  expiry_type: ExpiryType
  lots: number

  option_type: OptionType
  strike_criteria: 'ATM' | 'STRIKE_OFFSET'
  strike_value: number

  target_enabled: boolean
  target_value: number
  target_unit: RiskUnit

  sl_enabled: boolean
  sl_value: number
  sl_unit: RiskUnit

  trail_enabled: boolean
  trail_x: number
  trail_y: number
  trail_unit: RiskUnit

  momentum_enabled: boolean
  momentum_value: number
  momentum_unit: RiskUnit
}

const blankLeg = (segment: Segment): LegFormState => ({
  segment,
  position: 'B',
  product: segment === 'CASH' ? 'MIS' : 'NRML',
  symbol_cash: '',
  qty: 1,
  expiry_type: 'CURRENT_WEEK',
  lots: 1,
  option_type: 'CE',
  strike_criteria: 'ATM',
  strike_value: 0,
  target_enabled: false,
  target_value: 0,
  target_unit: 'pts',
  sl_enabled: false,
  sl_value: 0,
  sl_unit: 'pts',
  trail_enabled: false,
  trail_x: 1,
  trail_y: 1,
  trail_unit: 'pts',
  momentum_enabled: false,
  momentum_value: 0,
  momentum_unit: 'pts',
})

const legFormToPayload = (lf: LegFormState, leg_index: number): LegPayload => ({
  leg_index,
  segment: lf.segment,
  position: lf.position,
  product: lf.product,
  // Conditional fields
  ...(lf.segment === 'CASH'
    ? { symbol_cash: lf.symbol_cash.trim(), qty: lf.qty }
    : {}),
  ...(lf.segment !== 'CASH'
    ? { expiry_type: lf.expiry_type, lots: lf.lots }
    : {}),
  ...(lf.segment === 'OPT'
    ? {
        option_type: lf.option_type,
        strike_criteria: lf.strike_criteria,
        strike_value: lf.strike_value,
      }
    : {}),
  // Risk
  target_enabled: lf.target_enabled,
  target_value: lf.target_enabled ? lf.target_value : null,
  target_unit: lf.target_enabled ? lf.target_unit : null,
  sl_enabled: lf.sl_enabled,
  sl_value: lf.sl_enabled ? lf.sl_value : null,
  sl_unit: lf.sl_enabled ? lf.sl_unit : null,
  trail_enabled: lf.trail_enabled,
  trail_x: lf.trail_enabled ? lf.trail_x : null,
  trail_y: lf.trail_enabled ? lf.trail_y : null,
  trail_unit: lf.trail_enabled ? lf.trail_unit : null,
  momentum_enabled: lf.momentum_enabled,
  momentum_value: lf.momentum_enabled ? lf.momentum_value : null,
  momentum_unit: lf.momentum_enabled ? lf.momentum_unit : null,
})

// ---------------------------------------------------------------------------
// Strategy-header form state
// ---------------------------------------------------------------------------

interface StrategyForm {
  name: string
  underlying: string
  underlying_exchange: string
  is_intraday: boolean
  start_time: string
  end_time: string
  squareoff_time: string
  mode: 'live' | 'sandbox'
}

const blankStrategy = (): StrategyForm => ({
  name: '',
  underlying: 'NIFTY',
  underlying_exchange: 'NSE_INDEX',
  is_intraday: true,
  start_time: '09:35',
  end_time: '15:15',
  squareoff_time: '15:20',
  mode: 'live',
})

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function StrategyV2Builder() {
  const { id } = useParams<{ id?: string }>()
  const navigate = useNavigate()
  const isNew = id === 'new' || !id
  const numericId = !isNew && id ? Number(id) : null

  const [strategy, setStrategy] = useState<StrategyV2 | null>(null)
  const [form, setForm] = useState<StrategyForm>(blankStrategy())
  const [legs, setLegs] = useState<StrategyLeg[]>([])
  const [draftLeg, setDraftLeg] = useState<LegFormState>(blankLeg('CASH'))
  const [loading, setLoading] = useState(false)
  const [savingHeader, setSavingHeader] = useState(false)
  const [showWebhook, setShowWebhook] = useState(false)
  const [oneTimeSecret, setOneTimeSecret] = useState<{
    webhook_secret?: string
    webhook_hmac_key?: string
  } | null>(null)
  const [riskConfig, setRiskConfig] = useState<StrategyRiskConfig | null>(null)
  const [savingRisk, setSavingRisk] = useState(false)

  // -------- Load existing strategy ----------------------------------------
  useEffect(() => {
    if (isNew || !numericId) return
    setLoading(true)
    Promise.all([
      strategyV2Api.get(numericId),
      strategyV2Api.getRiskConfig(numericId).catch(() => null),
    ])
      .then(([data, rc]) => {
        setStrategy(data.strategy)
        setLegs(data.legs)
        setForm({
          name: data.strategy.name,
          underlying: data.strategy.underlying ?? 'NIFTY',
          underlying_exchange: data.strategy.underlying_exchange ?? 'NSE_INDEX',
          is_intraday: data.strategy.is_intraday,
          start_time: data.strategy.start_time,
          end_time: data.strategy.end_time,
          squareoff_time: data.strategy.squareoff_time ?? '',
          mode: data.strategy.mode,
        })
        if (rc) setRiskConfig(rc)
      })
      .catch((err) => {
        toast.error('Failed to load strategy')
        console.error(err)
      })
      .finally(() => setLoading(false))
  }, [isNew, numericId])

  const onSaveRiskConfig = async () => {
    if (!numericId || !riskConfig) return
    setSavingRisk(true)
    try {
      const updated = await strategyV2Api.updateRiskConfig(numericId, riskConfig)
      setRiskConfig(updated)
      toast.success('Risk config saved')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e?.response?.data?.message ?? 'Failed to save risk config')
    } finally {
      setSavingRisk(false)
    }
  }

  // -------- Header save ---------------------------------------------------
  const onSaveHeader = async () => {
    setSavingHeader(true)
    try {
      const payload: StrategyV2CreatePayload = {
        name: form.name.trim(),
        underlying: form.underlying || null,
        underlying_exchange: form.underlying_exchange || null,
        is_intraday: form.is_intraday,
        start_time: form.start_time,
        end_time: form.end_time,
        squareoff_time: form.is_intraday ? form.squareoff_time || null : null,
        mode: form.mode,
        webhook_signing_method: 'NONE',
      }
      if (isNew) {
        const r = await strategyV2Api.create(payload)
        // Capture one-time secrets if backend issued any (NONE method → none).
        if (r.strategy.webhook_secret || r.strategy.webhook_hmac_key) {
          setOneTimeSecret({
            webhook_secret: r.strategy.webhook_secret,
            webhook_hmac_key: r.strategy.webhook_hmac_key,
          })
        }
        toast.success('Strategy created')
        navigate(`/strategy/v2/${r.strategy.id}`, { replace: true })
      } else if (numericId) {
        const r = await strategyV2Api.update(numericId, payload)
        setStrategy(r.strategy)
        toast.success('Saved')
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string; errors?: unknown } } }
      toast.error(e?.response?.data?.message ?? 'Save failed')
      console.error(err)
    } finally {
      setSavingHeader(false)
    }
  }

  // -------- Add a leg -----------------------------------------------------
  const onAddLeg = async () => {
    if (!numericId) {
      toast.error('Save the strategy first to start adding legs')
      return
    }
    if (draftLeg.segment === 'CASH' && !draftLeg.symbol_cash.trim()) {
      toast.error('Cash leg needs a symbol')
      return
    }
    try {
      const payload = legFormToPayload(draftLeg, legs.length + 1)
      const newLeg = await strategyV2Api.addLeg(numericId, payload)
      setLegs((prev) => [...prev, newLeg])
      setDraftLeg(blankLeg(draftLeg.segment))
      toast.success(`Leg ${legs.length + 1} added`)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e?.response?.data?.message ?? 'Failed to add leg')
      console.error(err)
    }
  }

  const onRemoveLeg = async (legId: number) => {
    if (!numericId) return
    try {
      await strategyV2Api.removeLeg(numericId, legId)
      setLegs((prev) => prev.filter((l) => l.id !== legId))
      toast.success('Leg removed')
    } catch (err) {
      toast.error('Failed to remove leg')
      console.error(err)
    }
  }

  // ----------------------------------------------------------------------
  if (loading) {
    return <div className="container mx-auto p-8">Loading…</div>
  }

  return (
    <div className="container mx-auto p-6 max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <button
            type="button"
            onClick={() => navigate('/strategy/v2')}
            className="text-sm text-muted-foreground hover:underline"
          >
            ← All strategies
          </button>
          <h1 className="text-2xl font-semibold mt-1">
            {isNew ? 'New Strategy' : strategy?.name || 'Strategy'}
          </h1>
        </div>
        {!isNew && strategy && (
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={
                strategy.mode === 'sandbox'
                  ? 'bg-amber-500/15 text-amber-700 border-amber-500/30'
                  : 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30'
              }
            >
              {strategy.mode === 'sandbox' ? 'SANDBOX' : 'LIVE'}
            </Badge>
            <Badge variant="outline">{strategy.state}</Badge>
            <Button
              variant="outline"
              onClick={() => navigate(`/strategy/v2/${strategy.id}/runs`)}
            >
              Runs
            </Button>
            <Button variant="outline" onClick={() => setShowWebhook(true)}>
              Webhook & Security
            </Button>
          </div>
        )}
      </div>

      {/* ---------- Sandbox banner (Phase 6) ----------
          Surfaces the routing guarantee when this strategy is set to
          sandbox: regardless of the global analyzer toggle, every order
          this strategy places is rerouted to the sandbox engine via the
          per-call mode contextvar. */}
      {form.mode === 'sandbox' && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-100">
          <div className="font-medium">Sandbox mode</div>
          <p className="text-xs mt-1 text-amber-800 dark:text-amber-200">
            Orders from this strategy always route to the sandbox engine
            (paper fills at live LTP, zero slippage), independent of the
            global Analyzer toggle. Live strategies on the same account
            keep routing to the broker normally.
          </p>
        </div>
      )}

      {/* ---------- Index & Timings ---------- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Index and Timings</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="space-y-1">
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm((s) => ({ ...s, name: e.target.value }))}
              placeholder="My iron condor"
              maxLength={80}
            />
          </div>
          <div className="space-y-1">
            <Label>Underlying</Label>
            <Select
              value={form.underlying}
              onValueChange={(v) => setForm((s) => ({ ...s, underlying: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NIFTY">NIFTY</SelectItem>
                <SelectItem value="BANKNIFTY">BANKNIFTY</SelectItem>
                <SelectItem value="FINNIFTY">FINNIFTY</SelectItem>
                <SelectItem value="MIDCPNIFTY">MIDCPNIFTY</SelectItem>
                <SelectItem value="SENSEX">SENSEX</SelectItem>
                <SelectItem value="BANKEX">BANKEX</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Strategy Type</Label>
            <div className="flex border rounded-md overflow-hidden">
              <button
                type="button"
                className={`flex-1 py-2 text-sm ${form.is_intraday ? 'bg-primary text-primary-foreground' : ''}`}
                onClick={() => setForm((s) => ({ ...s, is_intraday: true }))}
              >
                Intraday
              </button>
              <button
                type="button"
                className={`flex-1 py-2 text-sm ${!form.is_intraday ? 'bg-primary text-primary-foreground' : ''}`}
                onClick={() => setForm((s) => ({ ...s, is_intraday: false }))}
              >
                Positional
              </button>
            </div>
          </div>
          <div className="space-y-1">
            <Label>Mode</Label>
            <Select
              value={form.mode}
              onValueChange={(v: 'live' | 'sandbox') => setForm((s) => ({ ...s, mode: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="live">LIVE</SelectItem>
                <SelectItem value="sandbox">SANDBOX</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Entry Time (IST)</Label>
            <Input
              type="time"
              value={form.start_time}
              onChange={(e) => setForm((s) => ({ ...s, start_time: e.target.value }))}
            />
          </div>
          <div className="space-y-1">
            <Label>Exit Time (IST)</Label>
            <Input
              type="time"
              value={form.end_time}
              onChange={(e) => setForm((s) => ({ ...s, end_time: e.target.value }))}
            />
          </div>
          {form.is_intraday && (
            <div className="space-y-1">
              <Label>Squareoff Time</Label>
              <Input
                type="time"
                value={form.squareoff_time}
                onChange={(e) => setForm((s) => ({ ...s, squareoff_time: e.target.value }))}
              />
            </div>
          )}
        </CardContent>
        <CardContent className="flex justify-end gap-2 pt-0">
          <Button onClick={onSaveHeader} disabled={savingHeader || !form.name.trim()}>
            {savingHeader ? 'Saving…' : isNew ? 'Create Strategy' : 'Save'}
          </Button>
        </CardContent>
      </Card>

      {/* ---------- Leg Builder ---------- */}
      {!isNew && numericId && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Leg Builder</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs value={draftLeg.segment} onValueChange={(v) => setDraftLeg(blankLeg(v as Segment))}>
              <TabsList>
                <TabsTrigger value="CASH">Cash</TabsTrigger>
                <TabsTrigger value="FUT">Futures</TabsTrigger>
                <TabsTrigger value="OPT">Options</TabsTrigger>
              </TabsList>
            </Tabs>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {draftLeg.segment === 'CASH' && (
                <>
                  <div className="space-y-1">
                    <Label>Symbol</Label>
                    <Input
                      value={draftLeg.symbol_cash}
                      onChange={(e) =>
                        setDraftLeg((s) => ({ ...s, symbol_cash: e.target.value.toUpperCase() }))
                      }
                      placeholder="INFY"
                    />
                  </div>
                  <NumberField
                    label="Qty"
                    value={draftLeg.qty}
                    onChange={(v) => setDraftLeg((s) => ({ ...s, qty: v }))}
                    min={1}
                  />
                </>
              )}

              {draftLeg.segment !== 'CASH' && (
                <>
                  <div className="space-y-1">
                    <Label>Expiry</Label>
                    <Select
                      value={draftLeg.expiry_type}
                      onValueChange={(v) =>
                        setDraftLeg((s) => ({ ...s, expiry_type: v as ExpiryType }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="CURRENT_WEEK">Current Week</SelectItem>
                        <SelectItem value="NEXT_WEEK">Next Week</SelectItem>
                        <SelectItem value="CURRENT_MONTH">Current Month</SelectItem>
                        <SelectItem value="NEXT_MONTH">Next Month</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <NumberField
                    label="Lots"
                    value={draftLeg.lots}
                    onChange={(v) => setDraftLeg((s) => ({ ...s, lots: v }))}
                    min={1}
                  />
                </>
              )}

              <div className="space-y-1">
                <Label>Position</Label>
                <div className="flex border rounded-md overflow-hidden">
                  <button
                    type="button"
                    className={`flex-1 py-2 text-sm ${draftLeg.position === 'B' ? 'bg-primary text-primary-foreground' : ''}`}
                    onClick={() => setDraftLeg((s) => ({ ...s, position: 'B' }))}
                  >
                    B
                  </button>
                  <button
                    type="button"
                    className={`flex-1 py-2 text-sm ${draftLeg.position === 'S' ? 'bg-primary text-primary-foreground' : ''}`}
                    onClick={() => setDraftLeg((s) => ({ ...s, position: 'S' }))}
                  >
                    S
                  </button>
                </div>
              </div>

              <div className="space-y-1">
                <Label>Product</Label>
                <Select
                  value={draftLeg.product}
                  onValueChange={(v: ProductType) => setDraftLeg((s) => ({ ...s, product: v }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MIS">MIS</SelectItem>
                    <SelectItem value="CNC">CNC</SelectItem>
                    <SelectItem value="NRML">NRML</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {draftLeg.segment === 'OPT' && (
                <>
                  <div className="space-y-1">
                    <Label>Option Type</Label>
                    <div className="flex border rounded-md overflow-hidden">
                      <button
                        type="button"
                        className={`flex-1 py-2 text-sm ${draftLeg.option_type === 'CE' ? 'bg-primary text-primary-foreground' : ''}`}
                        onClick={() => setDraftLeg((s) => ({ ...s, option_type: 'CE' }))}
                      >
                        Call
                      </button>
                      <button
                        type="button"
                        className={`flex-1 py-2 text-sm ${draftLeg.option_type === 'PE' ? 'bg-primary text-primary-foreground' : ''}`}
                        onClick={() => setDraftLeg((s) => ({ ...s, option_type: 'PE' }))}
                      >
                        Put
                      </button>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label>Strike Criteria</Label>
                    <Select
                      value={draftLeg.strike_criteria}
                      onValueChange={(v) =>
                        setDraftLeg((s) => ({ ...s, strike_criteria: v as 'ATM' | 'STRIKE_OFFSET' }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="ATM">ATM</SelectItem>
                        <SelectItem value="STRIKE_OFFSET">ITM/OTM Offset</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {draftLeg.strike_criteria === 'STRIKE_OFFSET' && (
                    <NumberField
                      label="Offset (negative=ITM, positive=OTM)"
                      value={draftLeg.strike_value}
                      onChange={(v) => setDraftLeg((s) => ({ ...s, strike_value: v }))}
                    />
                  )}
                </>
              )}
            </div>

            {/* Per-leg risk */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-2">
              <RiskBlock
                label="Target Profit"
                enabled={draftLeg.target_enabled}
                onToggle={(b) => setDraftLeg((s) => ({ ...s, target_enabled: b }))}
                value={draftLeg.target_value}
                unit={draftLeg.target_unit}
                onValue={(v) => setDraftLeg((s) => ({ ...s, target_value: v }))}
                onUnit={(u) => setDraftLeg((s) => ({ ...s, target_unit: u }))}
              />
              <RiskBlock
                label="Stop Loss"
                enabled={draftLeg.sl_enabled}
                onToggle={(b) => setDraftLeg((s) => ({ ...s, sl_enabled: b }))}
                value={draftLeg.sl_value}
                unit={draftLeg.sl_unit}
                onValue={(v) => setDraftLeg((s) => ({ ...s, sl_value: v }))}
                onUnit={(u) => setDraftLeg((s) => ({ ...s, sl_unit: u }))}
              />
              <TrailBlock
                enabled={draftLeg.trail_enabled}
                onToggle={(b) => setDraftLeg((s) => ({ ...s, trail_enabled: b }))}
                x={draftLeg.trail_x}
                y={draftLeg.trail_y}
                unit={draftLeg.trail_unit}
                onX={(v) => setDraftLeg((s) => ({ ...s, trail_x: v }))}
                onY={(v) => setDraftLeg((s) => ({ ...s, trail_y: v }))}
                onUnit={(u) => setDraftLeg((s) => ({ ...s, trail_unit: u }))}
              />
              <RiskBlock
                label="Simple Momentum"
                enabled={draftLeg.momentum_enabled}
                onToggle={(b) => setDraftLeg((s) => ({ ...s, momentum_enabled: b }))}
                value={draftLeg.momentum_value}
                unit={draftLeg.momentum_unit}
                onValue={(v) => setDraftLeg((s) => ({ ...s, momentum_value: v }))}
                onUnit={(u) => setDraftLeg((s) => ({ ...s, momentum_unit: u }))}
              />
            </div>

            <div className="flex justify-end">
              <Button onClick={onAddLeg}>+ Add Leg</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---------- Strategy Legs (read-only display) ---------- */}
      {!isNew && legs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Strategy Legs</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">#</th>
                  <th className="px-4 py-2">Segment</th>
                  <th className="px-4 py-2">B/S</th>
                  <th className="px-4 py-2">Symbol / Underlying</th>
                  <th className="px-4 py-2">Qty / Lots</th>
                  <th className="px-4 py-2">Risk</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {legs.map((l) => (
                  <tr key={l.id} className="border-b last:border-b-0">
                    <td className="px-4 py-2">{l.leg_index}</td>
                    <td className="px-4 py-2">
                      <Badge variant="outline">{l.segment}</Badge>
                    </td>
                    <td className="px-4 py-2">{l.position}</td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {l.segment === 'CASH'
                        ? l.symbol_cash
                        : `${strategy?.underlying ?? ''} ${l.expiry_type ?? ''} ${l.option_type ?? ''} ${l.strike_criteria ?? ''}${l.strike_value ? ` ${l.strike_value > 0 ? `OTM${l.strike_value}` : `ITM${Math.abs(l.strike_value)}`}` : ''}`}
                    </td>
                    <td className="px-4 py-2">
                      {l.segment === 'CASH' ? `${l.qty} qty` : `${l.lots} lots`}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {[
                        l.target_enabled && `T:${l.target_value}${l.target_unit}`,
                        l.sl_enabled && `SL:${l.sl_value}${l.sl_unit}`,
                        l.trail_enabled && `Trail:${l.trail_x}/${l.trail_y}${l.trail_unit}`,
                      ]
                        .filter(Boolean)
                        .join(' · ') || '—'}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Button variant="ghost" size="sm" onClick={() => onRemoveLeg(l.id)}>
                        Remove
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* ---------- Strategy Risk Config (Phase 4) ---------- */}
      {!isNew && numericId && riskConfig && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Overall Strategy Risk</CardTitle>
            <p className="text-xs text-muted-foreground">
              Strategy-level rules in absolute ₹. Aggregate MTM across all legs
              decides when these fire — not single-symbol points.
            </p>
          </CardHeader>
          <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Overall SL */}
            <div className="border rounded-md p-3 space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Overall SL (₹)</Label>
                <Switch
                  checked={riskConfig.overall_sl_enabled}
                  onCheckedChange={(b) =>
                    setRiskConfig({ ...riskConfig, overall_sl_enabled: b })
                  }
                />
              </div>
              {riskConfig.overall_sl_enabled && (
                <Input
                  type="number"
                  min={0}
                  value={riskConfig.overall_sl_abs ?? 0}
                  onChange={(e) =>
                    setRiskConfig({
                      ...riskConfig,
                      overall_sl_abs: Number(e.target.value) || 0,
                    })
                  }
                  placeholder="e.g. 5000"
                />
              )}
              <p className="text-xs text-muted-foreground">
                Strategy exits all legs when aggregate MTM ≤ -₹{riskConfig.overall_sl_abs ?? 0}.
              </p>
            </div>

            {/* Overall Target */}
            <div className="border rounded-md p-3 space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Overall Target (₹)</Label>
                <Switch
                  checked={riskConfig.overall_target_enabled}
                  onCheckedChange={(b) =>
                    setRiskConfig({ ...riskConfig, overall_target_enabled: b })
                  }
                />
              </div>
              {riskConfig.overall_target_enabled && (
                <Input
                  type="number"
                  min={0}
                  value={riskConfig.overall_target_abs ?? 0}
                  onChange={(e) =>
                    setRiskConfig({
                      ...riskConfig,
                      overall_target_abs: Number(e.target.value) || 0,
                    })
                  }
                  placeholder="e.g. 10000"
                />
              )}
              <p className="text-xs text-muted-foreground">
                Strategy exits all legs when aggregate MTM ≥ +₹{riskConfig.overall_target_abs ?? 0}.
              </p>
            </div>

            {/* Profit Lock */}
            <div className="border rounded-md p-3 space-y-2 lg:col-span-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Profit Lock (₹)</Label>
                <Switch
                  checked={riskConfig.lock_profit_enabled}
                  onCheckedChange={(b) =>
                    setRiskConfig({ ...riskConfig, lock_profit_enabled: b })
                  }
                />
              </div>
              {riskConfig.lock_profit_enabled && (
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <span className="text-xs text-muted-foreground">Lock at (peak ₹)</span>
                    <Input
                      type="number"
                      min={0}
                      value={riskConfig.lock_at_abs ?? 0}
                      onChange={(e) =>
                        setRiskConfig({
                          ...riskConfig,
                          lock_at_abs: Number(e.target.value) || 0,
                        })
                      }
                    />
                  </div>
                  <div className="space-y-1">
                    <span className="text-xs text-muted-foreground">Floor (min ₹)</span>
                    <Input
                      type="number"
                      min={0}
                      value={riskConfig.lock_min_abs ?? 0}
                      onChange={(e) =>
                        setRiskConfig({
                          ...riskConfig,
                          lock_min_abs: Number(e.target.value) || 0,
                        })
                      }
                    />
                  </div>
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Once peak MTM hits ₹{riskConfig.lock_at_abs ?? 0}, strategy exits if MTM
                drops back to ₹{riskConfig.lock_min_abs ?? 0}. One-way latch.
              </p>
            </div>

            {/* Trail-to-entry */}
            <div className="border rounded-md p-3 space-y-2 lg:col-span-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Trail SL to Entry</Label>
                <Switch
                  checked={riskConfig.trail_to_entry_enabled}
                  onCheckedChange={(b) =>
                    setRiskConfig({ ...riskConfig, trail_to_entry_enabled: b })
                  }
                />
              </div>
              {riskConfig.trail_to_entry_enabled && (
                <div className="flex gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={riskConfig.trail_to_entry_threshold}
                    onChange={(e) =>
                      setRiskConfig({
                        ...riskConfig,
                        trail_to_entry_threshold: Number(e.target.value) || 0,
                      })
                    }
                    className="flex-1"
                  />
                  <UnitToggle
                    unit={riskConfig.trail_to_entry_unit}
                    onChange={(u) =>
                      setRiskConfig({ ...riskConfig, trail_to_entry_unit: u })
                    }
                  />
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Once each leg moves favorably by{' '}
                {riskConfig.trail_to_entry_threshold}
                {riskConfig.trail_to_entry_unit}, its SL is pinned to entry price
                (no-loss trade). One-way ratchet per leg.
              </p>
            </div>
          </CardContent>
          <CardContent className="flex justify-end pt-0">
            <Button onClick={onSaveRiskConfig} disabled={savingRisk}>
              {savingRisk ? 'Saving…' : 'Save Risk Config'}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ---------- Webhook & Security dialog ---------- */}
      {showWebhook && strategy && (
        <StrategyV2WebhookDialog
          strategy={strategy}
          oneTimeSecret={oneTimeSecret}
          onClose={() => {
            setShowWebhook(false)
            setOneTimeSecret(null)
          }}
          onUpdated={(s) => setStrategy(s)}
          onRotated={(secrets) => setOneTimeSecret(secrets)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Small reusable form blocks
// ---------------------------------------------------------------------------

function NumberField({
  label,
  value,
  onChange,
  min,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input
        type="number"
        value={value}
        min={min}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
      />
    </div>
  )
}

function RiskBlock({
  label,
  enabled,
  onToggle,
  value,
  unit,
  onValue,
  onUnit,
}: {
  label: string
  enabled: boolean
  onToggle: (b: boolean) => void
  value: number
  unit: RiskUnit
  onValue: (v: number) => void
  onUnit: (u: RiskUnit) => void
}) {
  return (
    <div className="border rounded-md p-3 space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">{label}</Label>
        <Switch checked={enabled} onCheckedChange={onToggle} />
      </div>
      {enabled && (
        <div className="flex gap-2">
          <Input
            type="number"
            value={value}
            onChange={(e) => onValue(Number(e.target.value) || 0)}
            className="flex-1"
          />
          <UnitToggle unit={unit} onChange={onUnit} />
        </div>
      )}
    </div>
  )
}

function TrailBlock({
  enabled,
  onToggle,
  x,
  y,
  unit,
  onX,
  onY,
  onUnit,
}: {
  enabled: boolean
  onToggle: (b: boolean) => void
  x: number
  y: number
  unit: RiskUnit
  onX: (v: number) => void
  onY: (v: number) => void
  onUnit: (u: RiskUnit) => void
}) {
  return (
    <div className="border rounded-md p-3 space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm">Trail SL (X / Y)</Label>
        <Switch checked={enabled} onCheckedChange={onToggle} />
      </div>
      {enabled && (
        <>
          <div className="flex gap-2">
            <div className="flex-1 space-y-1">
              <span className="text-xs text-muted-foreground">X (move trigger)</span>
              <Input
                type="number"
                value={x}
                onChange={(e) => onX(Number(e.target.value) || 0)}
              />
            </div>
            <div className="flex-1 space-y-1">
              <span className="text-xs text-muted-foreground">Y (advance by)</span>
              <Input
                type="number"
                value={y}
                onChange={(e) => onY(Number(e.target.value) || 0)}
              />
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Unit</span>
              <UnitToggle unit={unit} onChange={onUnit} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Every {x}{unit} favorable move advances the SL by {y}{unit}.
          </p>
        </>
      )}
    </div>
  )
}

function UnitToggle({ unit, onChange }: { unit: RiskUnit; onChange: (u: RiskUnit) => void }) {
  return (
    <div className="flex border rounded-md overflow-hidden">
      <button
        type="button"
        className={`px-3 text-xs ${unit === 'pts' ? 'bg-primary text-primary-foreground' : ''}`}
        onClick={() => onChange('pts')}
      >
        pts
      </button>
      <button
        type="button"
        className={`px-3 text-xs ${unit === 'pct' ? 'bg-primary text-primary-foreground' : ''}`}
        onClick={() => onChange('pct')}
      >
        %
      </button>
    </div>
  )
}
