// types/strategy_module.ts
// Strategy module vocabulary, wire types and pure helpers.
//
// The types mirror the `*_to_dict` functions in `database/strategy_module_db.py`
// and the enum tuples that file exports; the leg shape mirrors `LEG_FIELDS` and
// `_validate_leg` in `blueprints/strategy_module.py`, which is the only place a
// payload is refused. Where the two disagree the validator wins, because it is
// what a request actually has to satisfy.
//
// Pure helpers live here too rather than in a fourth file: they are functions of
// these types alone (no React, no network), and keeping them beside the
// vocabulary they read is what stops a second copy of "which products are legal"
// from appearing next to the form that asks the question.

// ---------------------------------------------------------------------------
// Enumerations - each one is the store's tuple of the same name
// ---------------------------------------------------------------------------

export type StrategyKind = 'batch' | 'signal'
export type StrategyDirection = 'both' | 'long_only' | 'short_only'
export type StrategyType = 'intraday' | 'positional'
export type StrategyStatus = 'stopped' | 'running' | 'paused' | 'errored'
export type RunMode = 'live' | 'sandbox'
export type TriggerSource = 'manual' | 'webhook' | 'scheduler'

export type Product = 'CNC' | 'NRML' | 'MIS'
export type PriceType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'

export type Segment = 'options' | 'futures' | 'cash'
export type LegPosition = 'B' | 'S'
export type OptionType = 'CE' | 'PE'
export type StrikeMode = 'atm' | 'strike'

/**
 * Which signals a leg accepts, on a signal-mode strategy.
 *
 * Not the side the leg is currently held. That is decided by whichever signal
 * opened it and lives in run state, so a leg declared "both" may be short right
 * now. Mirrors `LEG_SIDES` in the validator.
 */
export type LegSide = 'long' | 'short' | 'both'

/**
 * How a signal leg's quantity is counted.
 *
 * In `lots` the stored number is a lot count and the engine multiplies by the
 * contract's lot size when it enters. In `units` the number is the quantity
 * itself. Mirrors `QTY_MODES` in the validator.
 */
export type QtyMode = 'lots' | 'units'

/**
 * Expiry ranks the validator accepts (`LEG_EXPIRIES`).
 *
 * `weekly` and `monthly` are the nearest weekly and nearest monthly contract;
 * `current` and `next` are the older spellings of the monthly pair and are still
 * accepted, so a strategy saved before the rename keeps working.
 */
export type ExpiryRank = 'weekly' | 'next_week' | 'monthly' | 'next_month' | 'current' | 'next'

export type Weekday = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT' | 'SUN'
export type LockProfitMode = 'lock' | 'lock_and_trail'

/** Per-leg risk numbers are either absolute points or a percentage of entry. */
export type RiskUnit = 'points' | 'percent'

export type OrderStatus = 'pending' | 'open' | 'complete' | 'cancelled' | 'rejected'
export type EventSeverity = 'info' | 'warn' | 'critical'

export type StopReason =
  | 'manual'
  | 'scheduler'
  | 'overall_sl'
  | 'overall_target'
  | 'lock_profit'
  | 'eod'
  | 'expiry'
  | 'daily_loss_limit'
  | 'tick_stale'
  | 'recovery_failed'
  | 'error'

export type WebhookResult =
  | 'ok'
  | 'rejected_token'
  | 'rejected_ip'
  | 'rate_limited'
  | 'rejected_dedupe'
  | 'rejected_cooling_off'
  | 'rejected_invalid_action'
  | 'rejected_live_disabled'
  | 'rejected_locked'
  | 'rejected_payload'
  | 'rejected_engine_error'

/**
 * Which universe the wizard was pointed at. The column is free text on the
 * server (30 chars), so this union is the set the UI offers rather than a
 * constraint the API enforces.
 */
export type UniverseTab = 'weekly_monthly' | 'monthly_only' | 'stocks_fno' | 'mcx'

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface TrailConfig {
  x: number
  y: number
}

/**
 * One leg of a strategy.
 *
 * The optional fields are conditionally *forbidden*, not merely optional: the
 * validator rejects `option_type` on a futures leg, `expiry` on a cash leg,
 * `strike` while `strike_mode` is `atm`, and `atm_offset` while it is `strike`.
 * `legToPayload` below is the one place that pruning happens.
 */
export interface Leg {
  id: number
  segment: Segment

  // --- Batch-mode fields. Absent on a signal leg, which the validator
  // rejects outright rather than ignoring. ---
  position?: LegPosition | null
  lots?: number | null
  option_type?: OptionType | null
  strike_mode?: StrikeMode | null
  atm_offset?: string | null
  strike?: number | null

  // --- Signal-mode fields. A signal leg names its own instrument and its own
  // absolute quantity; it is a different shape, not a superset. ---
  symbol?: string | null
  exchange?: string | null
  side?: LegSide | null
  /** Counted in lots or in units, per `qty_mode`. */
  qty?: number | null
  qty_mode?: QtyMode | null

  // --- Shared by both kinds. ---
  expiry?: ExpiryRank | null
  sl_pts?: number | null
  target_pts?: number | null
  trail?: TrailConfig | null
  /**
   * How sl_pts, target_pts and trail are expressed for this leg.
   *
   * Absent means points: every leg written before this field existed is a
   * points leg, and the field names keep saying "pts" so the wire format did
   * not change.
   */
  risk_unit?: RiskUnit | null
}

export interface LockProfitConfig {
  mode: LockProfitMode
  if_profit_reaches: number
  lock_profit: number
  trail_step?: number | null
}

export interface SchedulerConfig {
  enabled: boolean
  days: Weekday[]
  start_time: string | null
  auto_stop_time: string | null
  default_mode: RunMode
}

/** The durable P&L authority for a strategy whose latest run has ended. */
export interface FinalizedRunSummary {
  id: number
  pnl_realized: number
  stopped_at: string
}

/** A strategy as the list endpoint returns it: everything but the legs. */
export interface StrategySummary {
  id: number
  name: string
  strategy_kind: StrategyKind
  direction: StrategyDirection
  universe_tab: string
  underlying: string
  underlying_exchange: string
  strategy_type: StrategyType
  entry_time: string | null
  exit_time: string | null
  product: Product
  pricetype: PriceType
  overall_sl_mtm: number | null
  overall_target_mtm: number | null
  lock_profit: LockProfitConfig | null
  trail_sl_to_entry: boolean
  scheduler: SchedulerConfig | null
  live_enabled: boolean
  webhook_locked: boolean
  webhook_ip_allowlist: string[] | null
  daily_loss_limit_inr: number | null
  status: StrategyStatus
  current_run_id: number | null
  created_at: string
  updated_at: string
  /** Present on list rows; never use a checkpoint after this run has ended. */
  last_finalized_run?: FinalizedRunSummary | null
}

/** A strategy as the detail endpoint returns it. */
export interface Strategy extends StrategySummary {
  legs: Leg[]
}

/**
 * The create body, and (as a Partial) the update body.
 *
 * A PATCH is merged onto the stored configuration and re-validated whole, so a
 * partial update still has to leave the strategy in a valid state.
 */
export interface StrategyConfigPayload {
  name: string
  strategy_kind?: StrategyKind
  direction?: StrategyDirection
  universe_tab?: string
  underlying: string
  underlying_exchange: string
  strategy_type?: StrategyType
  entry_time?: string | null
  exit_time?: string | null
  product?: Product
  pricetype?: PriceType
  legs: Leg[]
  overall_sl_mtm?: number | null
  overall_target_mtm?: number | null
  lock_profit?: LockProfitConfig | null
  trail_sl_to_entry?: boolean
  scheduler?: SchedulerConfig | null
  daily_loss_limit_inr?: number | null
  webhook_ip_allowlist?: string[] | null
}

export type StrategyUpdatePayload = Partial<StrategyConfigPayload>

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export interface Run {
  id: number
  strategy_id: number
  mode: RunMode
  broker: string | null
  started_at: string | null
  stopped_at: string | null
  stop_reason: StopReason | null
  pnl_realized: number
  pnl_peak: number
  pnl_trough: number
  trigger_source: TriggerSource
  webhook_event_id: number | null
  resolved_expiries: Record<string, string> | null
}

export interface Order {
  id: number
  run_id: number
  leg_id: number
  kind: string
  broker_order_id: string | null
  position_ref: string | null
  symbol: string
  exchange: string
  action: string
  qty: number
  pricetype: string
  price: number
  trigger_price: number
  status: OrderStatus
  placed_at: string | null
  filled_at: string | null
  avg_fill_price: number | null
  filled_qty: number | null
  reject_reason: string | null
}

// ---------------------------------------------------------------------------
// Broker-backed books
// ---------------------------------------------------------------------------

/** A normalized row from the broker's order book. */
export interface BrokerOrder {
  orderid: string
  symbol: string
  exchange: string
  action: string
  quantity: number | null
  price: number | null
  trigger_price: number | null
  pricetype: string
  product: string
  order_status: string
  timestamp: string | null
  [field: string]: unknown
}

/** A normalized fill row from the broker's trade book. */
export interface BrokerTrade {
  orderid: string
  symbol: string
  exchange: string
  product: string
  action: string
  quantity: number | null
  average_price: number | null
  trade_value: number | null
  timestamp: string | null
  [field: string]: unknown
}

/** A normalized contract row from the broker's position book. */
export type PositionTruthSource = 'broker' | 'broker/shared' | 'local/unreconciled'

export interface BrokerPosition {
  symbol: string
  exchange: string
  product: string
  quantity: number | null
  average_price: number | null
  ltp: number | null
  pnl: number | null
  source?: PositionTruthSource
  position_ref?: string | null
  run_id?: number | null
  leg_id?: number | null
  [field: string]: unknown
}

export type BrokerReconciliation = 'matched' | 'disagrees' | 'unmatched' | 'ambiguous'

/** Strategy-only context attached only when one exact local identifier matches. */
export interface BrokerStrategyContext {
  run_id: number | null
  leg_id: number | null
  kind: string | null
  local_status: OrderStatus | null
  position_ref: string | null
  reject_reason: string | null
  reconciliation: BrokerReconciliation
  disagreements: string[]
}

export interface ReconciledBrokerOrder extends BrokerOrder, BrokerStrategyContext {}

export interface ReconciledBrokerTrade extends BrokerTrade, BrokerStrategyContext {}

export interface StrategyEvent {
  id: number
  run_id: number | null
  strategy_id: number
  ts: string
  kind: string
  severity: EventSeverity
  leg_id: number | null
  message: string
  payload: Record<string, unknown> | null
}

export interface WebhookEvent {
  id: number
  strategy_id: number
  action: string | null
  mode: string | null
  payload: Record<string, unknown> | null
  ip: string | null
  user_agent: string | null
  received_at: string | null
  result: WebhookResult
  error: string | null
}

/**
 * One leg's runtime state, as the engine stores it in a checkpoint's
 * `leg_state` map. Mirrors `_new_leg_state` in `services/strategy_module/state.py`.
 */
export interface LegState {
  leg_id: number
  position: LegPosition
  symbol: string
  exchange: string
  lots: number
  qty: number
  entry_order_id: number | null
  entry_status: string
  entry_avg: number
  exit_order_id: number | null
  exit_kind: string | null
  exit_avg: number | null
  ltp: number | null
  mtm: number
  realized_pnl: number
  status: string
  tick_source: string
  sl_pts: number | null
  target_pts: number | null
  trail_x: number
  trail_y: number
  effective_sl: number | null
  effective_target: number | null
  trail_active: boolean
  highest_price: number | null
  lowest_price: number | null
  /**
   * The favourable excursion in points, when the source measured it already.
   *
   * The socket sends this instead of the price ratchet it came from; a
   * checkpoint row sends the ratchet and leaves this undefined.
   */
  favorable_points?: number | null
}

/** A runtime snapshot of a run: one point on its P&L curve. */
export interface Checkpoint {
  id: number
  run_id: number
  ts: string
  pnl_realized: number
  pnl_unrealized: number
  pnl_total: number
  pnl_peak: number
  pnl_trough: number
  lock_floor: number | null
  trail_to_entry_active: boolean
  leg_state: Record<string, LegState>
}

// ---------------------------------------------------------------------------
// Wizard vocabulary
// ---------------------------------------------------------------------------

export const UNIVERSE_TABS: UniverseTab[] = ['weekly_monthly', 'monthly_only', 'stocks_fno', 'mcx']

export const UNIVERSE_TAB_LABELS: Record<UniverseTab, string> = {
  weekly_monthly: 'Weekly & Monthly Expiries',
  monthly_only: 'Monthly Only Expiry',
  stocks_fno: 'Stocks – Cash / F&O',
  mcx: 'Commodities (MCX)',
}

export const UNIVERSE_TAB_HINT: Record<UniverseTab, string> = {
  weekly_monthly: 'NIFTY, SENSEX',
  monthly_only: 'MIDCPNIFTY, BANKNIFTY, FINNIFTY, BANKEX',
  stocks_fno: 'Any NSE or BSE stock',
  mcx: 'CRUDEOIL, NATURALGAS, GOLD, SILVER, …',
}

/** Universe tab label, tolerant of a value the UI does not know. */
export function universeTabLabel(tab: string): string {
  return UNIVERSE_TAB_LABELS[tab as UniverseTab] ?? tab
}

export const EXPIRY_RANK_LABELS: Record<ExpiryRank, string> = {
  weekly: 'Current Week',
  next_week: 'Next Week',
  monthly: 'Current Month',
  next_month: 'Next Month',
  // Older spellings of the monthly pair, still accepted by the validator so an
  // existing strategy keeps rendering sensibly until it is next saved.
  current: 'Current Month (legacy)',
  next: 'Next Month (legacy)',
}

/**
 * What expiry ranks a tab offers. Weekly contracts exist on the index options
 * side only; stock F&O and MCX are monthly.
 */
export const TAB_EXPIRIES: Record<UniverseTab, ExpiryRank[]> = {
  weekly_monthly: ['weekly', 'next_week', 'monthly', 'next_month'],
  monthly_only: ['monthly', 'next_month'],
  stocks_fno: ['monthly', 'next_month'],
  mcx: ['monthly', 'next_month'],
}

export const TAB_SEGMENTS: Record<UniverseTab, Segment[]> = {
  weekly_monthly: ['futures', 'options'],
  monthly_only: ['futures', 'options'],
  stocks_fno: ['cash', 'futures', 'options'],
  mcx: ['futures', 'options'],
}

export interface UnderlyingChoice {
  symbol: string
  name: string
  exchange: string
}

/**
 * The underlying seed per tab.
 *
 * The index tabs are the whole universe, so the wizard offers them as a closed
 * list. The stock and commodity tabs are open universes and the seed is only a
 * starting point, so those tabs let the user type as well.
 */
export const TAB_DEFAULT_UNDERLYINGS: Record<UniverseTab, UnderlyingChoice[]> = {
  weekly_monthly: [
    { symbol: 'NIFTY', name: 'Nifty 50', exchange: 'NSE_INDEX' },
    { symbol: 'SENSEX', name: 'BSE SENSEX', exchange: 'BSE_INDEX' },
  ],
  monthly_only: [
    { symbol: 'BANKNIFTY', name: 'Nifty Bank', exchange: 'NSE_INDEX' },
    { symbol: 'FINNIFTY', name: 'Nifty Fin Service', exchange: 'NSE_INDEX' },
    { symbol: 'MIDCPNIFTY', name: 'Nifty Midcap Select', exchange: 'NSE_INDEX' },
    { symbol: 'BANKEX', name: 'BSE Bankex', exchange: 'BSE_INDEX' },
  ],
  stocks_fno: [
    { symbol: 'RELIANCE', name: 'Reliance Industries', exchange: 'NSE' },
    { symbol: 'TCS', name: 'Tata Consultancy Services', exchange: 'NSE' },
    { symbol: 'HDFCBANK', name: 'HDFC Bank', exchange: 'NSE' },
    { symbol: 'INFY', name: 'Infosys', exchange: 'NSE' },
  ],
  mcx: [
    { symbol: 'CRUDEOIL', name: 'Crude Oil', exchange: 'MCX' },
    { symbol: 'NATURALGAS', name: 'Natural Gas', exchange: 'MCX' },
    { symbol: 'GOLD', name: 'Gold', exchange: 'MCX' },
    { symbol: 'SILVER', name: 'Silver', exchange: 'MCX' },
  ],
}

/** Whether the tab's universe is closed (a dropdown) or open (type-ahead). */
export const TAB_UNDERLYING_IS_CLOSED_SET: Record<UniverseTab, boolean> = {
  weekly_monthly: true,
  monthly_only: true,
  stocks_fno: false,
  mcx: false,
}

/**
 * Exchanges a tab's underlying may be quoted on.
 *
 * Only the stocks tab has a choice to offer. An index tab's exchange follows
 * the index the user picked, and MCX lists on one venue. Cash resolves against
 * whichever of these the strategy carries, and a derivative leg on the same
 * underlying maps from it (NSE to NFO, BSE to BFO), so this is the strategy's
 * exchange rather than the cash leg's.
 */
export const TAB_UNDERLYING_EXCHANGES: Record<UniverseTab, string[]> = {
  weekly_monthly: ['NSE_INDEX', 'BSE_INDEX'],
  monthly_only: ['NSE_INDEX', 'BSE_INDEX'],
  stocks_fno: ['NSE', 'BSE'],
  mcx: ['MCX'],
}

/** The exchange a typed underlying defaults to on an open-universe tab. */
export const TAB_DEFAULT_EXCHANGE: Record<UniverseTab, string> = {
  weekly_monthly: 'NSE_INDEX',
  monthly_only: 'NSE_INDEX',
  stocks_fno: 'NSE',
  mcx: 'MCX',
}

/** A strike named relative to the money - the validator's `ATM_OFFSETS`. */
export const ATM_OFFSETS: string[] = [
  'ATM',
  'ITM1',
  'ITM2',
  'ITM3',
  'ITM4',
  'ITM5',
  'OTM1',
  'OTM2',
  'OTM3',
  'OTM4',
  'OTM5',
]

export const STRATEGY_KIND_LABELS: Record<StrategyKind, string> = {
  batch: 'Multi-leg (batch)',
  signal: 'Signal-driven (TradingView)',
}

export const STRATEGY_KIND_HINT: Record<StrategyKind, string> = {
  batch: 'All legs entered together on start; exited together on stop. Best for option spreads.',
  signal: 'Each leg reacts to long_entry / long_exit / short_entry / short_exit signals.',
}

export const STRATEGY_DIRECTION_LABELS: Record<StrategyDirection, string> = {
  long_only: 'Long only',
  short_only: 'Short only',
  both: 'Both',
}

export const LEG_SIDE_LABELS: Record<LegSide, string> = {
  long: 'Long',
  short: 'Short',
  both: 'Both',
}

/**
 * Universe tabs a signal strategy can use.
 *
 * Signal mode does not do option spreads - a signal leg carries no option
 * fields at all - so the two index-options tabs have nothing to offer it.
 */
export const SIGNAL_MODE_TABS: UniverseTab[] = ['stocks_fno', 'mcx']

/** Segments a signal leg may take. Narrower than a batch leg's: no options. */
export const SIGNAL_LEG_SEGMENTS: Segment[] = ['cash', 'futures']

/**
 * Segments a signal leg may take on a given tab.
 *
 * The flat list above offered cash on the commodity tab, where there is no
 * spot to trade: the leg validated, the segment was then ignored downstream,
 * and the order went to MCX as whatever the symbol happened to be. Intersecting
 * with the tab keeps the offer honest.
 */
export function signalSegmentsForTab(tab: UniverseTab): Segment[] {
  const allowed = new Set(TAB_SEGMENTS[tab])
  const offered = SIGNAL_LEG_SEGMENTS.filter((segment) => allowed.has(segment))
  return offered.length > 0 ? offered : ['futures']
}

/**
 * Where a signal leg may trade. Mirrors `SIGNAL_LEG_EXCHANGES` in
 * `blueprints/strategy_module.py`. The exchange box takes typed text, so
 * without this the only thing that caught "NSEE" was a 400 on save.
 */
export const SIGNAL_LEG_EXCHANGES = [
  'NSE',
  'BSE',
  'NFO',
  'BFO',
  'MCX',
  'CDS',
  'BCD',
  'NCDEX',
  'NCO',
]

/**
 * Which leg sides a strategy-level direction can ever act on. Mirrors
 * `_DIRECTION_ACCEPTS` in `blueprints/strategy_module.py`.
 *
 * A long_only strategy discards every short signal before it reaches a leg, so
 * a leg declared short is configuration that looks complete and can never
 * trade. The server refuses it; without this the operator found out on save.
 */
export const DIRECTION_ACCEPTS: Record<StrategyDirection, LegSide[]> = {
  both: ['long', 'short', 'both'],
  long_only: ['long', 'both'],
  short_only: ['short', 'both'],
}

/** Whether a signal leg's segment and exchange describe the same instrument. */
export function segmentSuitsExchange(segment: Segment, exchange: string | null | undefined) {
  const venue = (exchange ?? '').trim().toUpperCase()
  if (!venue) return true
  if (segment === 'cash') return !isDerivativeExchange(venue)
  if (segment === 'futures') return isDerivativeExchange(venue)
  return true
}

/**
 * Intraday window per tab. NSE and BSE trade 09:15-15:30, so 09:35-15:15 skips
 * the opening auction and exits before a broker's MIS square-off. MCX runs to
 * 23:30 in winter, so its window closes at 23:25.
 */
export const TAB_INTRADAY_DEFAULTS: Record<UniverseTab, { entry: string; exit: string }> = {
  weekly_monthly: { entry: '09:35', exit: '15:15' },
  monthly_only: { entry: '09:35', exit: '15:15' },
  stocks_fno: { entry: '09:35', exit: '15:15' },
  mcx: { entry: '09:00', exit: '23:25' },
}

export const MAX_LEGS = 10
export const MAX_LOTS = 50
/**
 * Cap on a batch cash leg's quantity.
 *
 * A cash contract's lot size is 1, so a batch cash leg's "lots" is a share
 * count. Capping it at the derivative's 50 made fifty shares the largest cash
 * order a batch strategy could place, while signal mode counted the same
 * instrument in units up to a million. Mirrors MAX_CASH_QUANTITY in
 * blueprints/strategy_module.py.
 */
export const MAX_CASH_QUANTITY = 1_000_000
export const MAX_NAME_LENGTH = 200
/** Cap on a signal leg's quantity when it is counted in units. */
export const MAX_SIGNAL_QTY = 1_000_000
/** Cap on a signal leg's quantity when it is counted in lots. */
export const MAX_SIGNAL_LOTS = 10_000

/** The cap on a batch leg's count: shares on cash, lots on a derivative. */
export function maxBatchQuantityFor(segment: Segment): number {
  return segment === 'cash' ? MAX_CASH_QUANTITY : MAX_LOTS
}

/** What a batch leg's count is measured in, for a label the operator reads. */
export function batchQuantityLabelFor(segment: Segment): string {
  return segment === 'cash' ? 'Quantity (shares)' : 'Lots'
}

/**
 * Exchanges that trade in lots. Mirrors `DERIVATIVE_EXCHANGES` in
 * `services/strategy_module/symbol_resolver.py`, which is what the validator
 * checks the leg's exchange against.
 */
export const DERIVATIVE_EXCHANGES = new Set([
  'NFO',
  'BFO',
  'MCX',
  'CDS',
  'NCO',
  'BCD',
  'NCDEX',
  'CRYPTO',
])

/** Whether an exchange has a lot size to multiply by. */
export function isDerivativeExchange(exchange: string | null | undefined): boolean {
  return DERIVATIVE_EXCHANGES.has((exchange ?? '').trim().toUpperCase())
}

/**
 * The mode a venue implies.
 *
 * A derivative is naturally counted in lots and cash in units, so the leg picks
 * that up from its exchange rather than making the user state it. An explicit
 * choice always wins - except on cash, where lots is refused outright because
 * there is no lot size to multiply by.
 */
export function defaultQtyMode(exchange: string | null | undefined): QtyMode {
  return isDerivativeExchange(exchange) ? 'lots' : 'units'
}

/** The cap that applies to a quantity in the given mode. */
export function maxQtyFor(mode: QtyMode): number {
  return mode === 'lots' ? MAX_SIGNAL_LOTS : MAX_SIGNAL_QTY
}

/**
 * What a leg's stored quantity actually sends, once the lot size is known.
 *
 * Null when it cannot be worked out - an unknown lot size, or a units-mode
 * quantity, which is already the number that goes to the broker.
 */
export function resolvedQuantity(
  qty: number | null | undefined,
  mode: QtyMode,
  lotSize: number | null | undefined
): number | null {
  if (qty == null || !Number.isFinite(qty)) return null
  if (mode === 'units') return qty
  if (!lotSize || lotSize <= 0) return null
  return qty * lotSize
}

/**
 * The leg that results from switching to another quantity mode.
 *
 * The number is converted when the lot size is known, because the same digit
 * means two different trades either side of the toggle. One lot of RELIANCE is
 * 500 shares, so leaving "1" on screen after a switch to units offers a
 * quantity that cannot be traded at all, and reads as though the toggle did
 * nothing. Switching back divides, floored to whole lots and never below one,
 * so a part-lot number resolves to the lots it covers rather than to nonsense.
 *
 * With no lot size the number is kept and reinterpreted, which is the older
 * behaviour: there is nothing to convert by, and inventing a factor would be
 * worse than leaving a figure the card already flags. A units quantity off a
 * lot boundary is still called out by `isWholeLots`, and the server refuses a
 * part lot by name.
 *
 * Lots on a cash venue is refused outright by the validator, so the switch is
 * a no-op there rather than something to be undone on save.
 */
export function withQtyMode(leg: Leg, mode: QtyMode, lotSize?: number | null): Leg {
  if (mode === 'lots' && !isDerivativeExchange(leg.exchange)) return leg

  const current = leg.qty ?? 1
  const size = lotSize && lotSize > 0 ? lotSize : null
  let converted = current
  if (size && mode !== (leg.qty_mode ?? defaultQtyMode(leg.exchange))) {
    converted = mode === 'units' ? current * size : Math.max(1, Math.floor(current / size))
  }

  return {
    ...leg,
    qty_mode: mode,
    // The cap changes with the mode too: 10,000 lots against 1,000,000 units.
    qty: Math.min(maxQtyFor(mode), Math.max(1, converted)),
  }
}

/**
 * Whether a units-mode quantity lands on a lot boundary.
 *
 * True when there is nothing to check against: an unknown lot size is not a
 * failure the user can act on from this form, and the engine checks again at
 * entry where the real contract is known. Mirrors `quantity_is_whole_lots`.
 */
export function isWholeLots(qty: number | null | undefined, lotSize: number | null): boolean {
  if (!lotSize || lotSize <= 0) return true
  if (qty == null || !Number.isFinite(qty)) return true
  return qty > 0 && qty % lotSize === 0
}

// ---------------------------------------------------------------------------
// Pure configuration helpers
// ---------------------------------------------------------------------------

/**
 * Products valid for a mix of segments.
 *
 * The product is a strategy-level field applied to every leg, and the engine
 * reads it as the intent rather than as a literal: MIS is intraday everywhere,
 * and anything else means carry, which `product_for_exchange` sends as NRML on
 * a derivative venue and CNC on cash. A mixed basket can therefore be carried,
 * with each leg receiving a product its own venue accepts.
 *
 * This used to offer MIS alone for a mixed basket, which was stricter than the
 * engine and removed carry from a basket that supports it. NRML is offered as
 * the carry intent because that is the spelling a derivative leg keeps; the
 * hint beside the control says what the cash leg is sent as.
 */
export function allowedProductsForLegs(legs: Leg[]): Product[] {
  const segments = new Set(legs.map((leg) => leg.segment))
  const hasCash = segments.has('cash')
  const hasDerivative = segments.has('futures') || segments.has('options')
  if (hasCash && hasDerivative) return ['MIS', 'NRML']
  if (hasCash) return ['MIS', 'CNC']
  return ['NRML', 'MIS']
}

/** What the chosen product is actually sent as, per venue, for a leg mix. */
export function productHintForLegs(legs: Leg[], product: Product): string {
  const segments = new Set(legs.map((leg) => leg.segment))
  const hasCash = segments.has('cash')
  const hasDerivative = segments.has('futures') || segments.has('options')
  if (product === 'MIS') return 'Intraday on every leg, squared off the same day.'
  if (hasCash && hasDerivative) {
    return 'Carried: the derivative legs are sent as NRML and the cash legs as CNC.'
  }
  if (hasCash) return 'Cash equity: CNC takes delivery, MIS is intraday.'
  return 'Derivatives: NRML carries the position, MIS is intraday.'
}

/** Default product for a leg composition: cash-only is MIS, derivatives NRML. */
export function defaultProductForLegs(legs: Leg[]): Product {
  return allowedProductsForLegs(legs)[0]
}

/** Expiry choices for a leg, given its tab and segment. */
export function expiriesFor(tab: UniverseTab, segment: Segment): ExpiryRank[] {
  // Futures are monthly on every Indian exchange, index included: the weekly
  // contracts exist on the options side only.
  if (segment === 'cash') return []
  if (segment === 'futures') return ['monthly', 'next_month']
  return TAB_EXPIRIES[tab]
}

// ---------------------------------------------------------------------------
// Leg shapes
//
// A batch leg and a signal leg are different shapes, not one shape with
// optional halves. The validator enforces that in both directions: it refuses
// `position` and `lots` on a signal leg, and refuses `symbol`, `exchange`,
// `side` and `qty` on a batch one, rather than ignoring what does not apply.
//
// That makes the conversion below load bearing. A form that let an option leg
// keep its `strike_mode` while the strategy was switched to signal mode would
// produce a payload the server rejects outright, naming a field the user
// cannot see any more.
// ---------------------------------------------------------------------------

/** A new batch leg: one short ATM call, the usual starting point. */
export function freshBatchLeg(id: number, tab: UniverseTab): Leg {
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
 * A new signal leg.
 *
 * Cash on the stocks tab, futures on MCX, which is what each of those
 * universes actually trades. The symbol is left empty on purpose: it is the
 * one field with no sensible default, and pre-filling it with a seed symbol
 * invites a strategy that trades something nobody chose.
 */
export function freshSignalLeg(id: number, tab: UniverseTab): Leg {
  const segment: Segment = tab === 'mcx' ? 'futures' : 'cash'
  const exchange =
    segment === 'futures'
      ? derivativeExchangeFor(TAB_DEFAULT_EXCHANGE[tab])
      : TAB_DEFAULT_EXCHANGE[tab]
  return {
    id,
    segment,
    symbol: '',
    exchange,
    side: 'both',
    qty: 1,
    qty_mode: defaultQtyMode(exchange),
    expiry: segment === 'futures' ? 'monthly' : null,
    sl_pts: null,
    target_pts: null,
    trail: { x: 0, y: 0 },
  }
}

/**
 * The same leg, reshaped for the other kind.
 *
 * Per-leg risk carries across because it means the same thing under both
 * kinds; everything else is rebuilt from the target shape's defaults. An
 * options leg becomes a cash leg, because signal mode has no options at all.
 */
export function convertLegKind(leg: Leg, kind: StrategyKind, tab: UniverseTab): Leg {
  const risk = {
    sl_pts: leg.sl_pts ?? null,
    target_pts: leg.target_pts ?? null,
    trail: leg.trail ?? { x: 0, y: 0 },
  }

  if (kind === 'signal') {
    const segment: Segment = leg.segment === 'futures' ? 'futures' : 'cash'
    const exchange =
      leg.exchange ||
      (segment === 'futures'
        ? derivativeExchangeFor(TAB_DEFAULT_EXCHANGE[tab])
        : TAB_DEFAULT_EXCHANGE[tab])
    return {
      id: leg.id,
      segment,
      symbol: leg.symbol ?? '',
      exchange,
      side: leg.side ?? 'both',
      qty: leg.qty ?? 1,
      qty_mode: leg.qty_mode ?? defaultQtyMode(exchange),
      expiry: segment === 'futures' ? (leg.expiry ?? 'monthly') : null,
      ...risk,
    }
  }

  const allowed = TAB_SEGMENTS[tab]
  const segment: Segment = allowed.includes(leg.segment) ? leg.segment : allowed[0]
  const isOption = segment === 'options'
  return {
    id: leg.id,
    segment,
    position: leg.position ?? 'S',
    lots: leg.lots ?? 1,
    option_type: isOption ? (leg.option_type ?? 'CE') : null,
    // Always ATM-relative coming back from signal mode: there is no strike to
    // carry over, and an empty direct strike would fail validation on save.
    strike_mode: isOption ? 'atm' : null,
    atm_offset: isOption ? (leg.atm_offset ?? 'ATM') : null,
    strike: null,
    expiry: segment === 'cash' ? null : (leg.expiry ?? expiriesFor(tab, segment)[0] ?? 'monthly'),
    ...risk,
  }
}

/**
 * A leg reduced to exactly the keys its kind accepts.
 *
 * The optional fields are conditionally forbidden rather than merely optional.
 * Pruning in one place, at submit time, lets the form keep a field's last value
 * while the user toggles a mode back and forth without that value reaching the
 * request.
 */
export function legToPayload(leg: Leg, kind: StrategyKind = 'batch'): Leg {
  const clean: Leg = { id: leg.id, segment: leg.segment }

  if (kind === 'signal') {
    clean.symbol = (leg.symbol ?? '').trim().toUpperCase()
    clean.exchange = (leg.exchange ?? '').trim().toUpperCase()
    clean.side = leg.side ?? 'both'
    // The mode decides what the number means, so it is sent explicitly rather
    // than left to the server's venue default: a leg whose exchange the user
    // has typed by hand should still send the mode the form was showing.
    const mode: QtyMode = leg.qty_mode ?? defaultQtyMode(clean.exchange)
    // Lots is refused outright on cash - there is no lot size to multiply by.
    clean.qty_mode = isDerivativeExchange(clean.exchange) ? mode : 'units'
    clean.qty = Math.min(maxQtyFor(clean.qty_mode), Math.max(1, Math.trunc(leg.qty ?? 1)))
    // Refused outright on a cash leg, so it is omitted rather than nulled.
    if (leg.segment === 'futures') clean.expiry = leg.expiry ?? 'monthly'
  } else {
    clean.position = leg.position ?? 'S'
    clean.lots = leg.lots ?? 1
    if (leg.segment !== 'cash') clean.expiry = leg.expiry
    if (leg.segment === 'options') {
      clean.option_type = leg.option_type ?? 'CE'
      clean.strike_mode = leg.strike_mode ?? 'atm'
      if (clean.strike_mode === 'atm') clean.atm_offset = leg.atm_offset ?? 'ATM'
      else clean.strike = leg.strike ?? null
    }
  }

  if (leg.sl_pts != null) clean.sl_pts = leg.sl_pts
  if (leg.target_pts != null) clean.target_pts = leg.target_pts
  if (leg.trail && (leg.trail.x > 0 || leg.trail.y > 0)) clean.trail = leg.trail
  // Sent with the numbers it governs, and always. Leaving it out let the
  // server apply its own default of points, so a leg configured as a
  // percentage of entry saved as points: the toggle moved, the form redrew,
  // and the stop was a rupee distance on a 2500 stock instead of a percentage
  // of it. Editing such a strategy then converted it back again. Points is
  // still the default when nothing is set, so this changes no stored leg.
  clean.risk_unit = leg.risk_unit ?? 'points'
  return clean
}

// ---------------------------------------------------------------------------
// Expiry ranks against the listed contracts
//
// A leg stores a rank, not a date, because that is what makes it survive a
// roll: "the current week" still means something next Thursday, and a stored
// date does not. But a rank is not something an operator can check, so the
// wizard resolves it against the real expiry list and shows the date it lands
// on. The rank stays the stored value; the date is display, and the strike
// query needs it too.
// ---------------------------------------------------------------------------

const MONTH_CODES = [
  'JAN',
  'FEB',
  'MAR',
  'APR',
  'MAY',
  'JUN',
  'JUL',
  'AUG',
  'SEP',
  'OCT',
  'NOV',
  'DEC',
]

/**
 * A `DD-MMM-YY` expiry as a UTC date, or null when it is not one.
 *
 * UTC throughout: these are calendar dates, and building them in local time
 * moves an Indian expiry across a day boundary for anyone west of London.
 */
export function parseExpiryDate(text: string): Date | null {
  const match = /^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$/.exec((text ?? '').trim())
  if (!match) return null
  const day = Number(match[1])
  const month = MONTH_CODES.indexOf(match[2].toUpperCase())
  if (month < 0) return null
  const rawYear = Number(match[3])
  const year = rawYear < 100 ? 2000 + rawYear : rawYear
  const date = new Date(Date.UTC(year, month, day))
  // Rejects 31-FEB-25 and friends, which JS would otherwise roll forward.
  if (date.getUTCMonth() !== month || date.getUTCDate() !== day) return null
  return date
}

/** The parseable expiries, oldest first. */
export function sortExpiries(expiries: string[]): string[] {
  return expiries
    .map((text) => ({ text, date: parseExpiryDate(text) }))
    .filter((entry): entry is { text: string; date: Date } => entry.date !== null)
    .sort((a, b) => a.date.getTime() - b.date.getTime())
    .map((entry) => entry.text)
}

/**
 * The monthly expiries in a list: the last contract of each calendar month.
 *
 * Derived rather than assumed. An index has weeklies and monthlies in one
 * list and only the last of a month is the monthly; a stock or a commodity has
 * one expiry per month, which this rule also gets right without a special case.
 */
export function monthlyExpiries(expiries: string[]): string[] {
  const lastOfMonth = new Map<string, { text: string; date: Date }>()
  for (const text of expiries) {
    const date = parseExpiryDate(text)
    if (!date) continue
    const key = `${date.getUTCFullYear()}-${date.getUTCMonth()}`
    const existing = lastOfMonth.get(key)
    if (!existing || date.getTime() > existing.date.getTime()) lastOfMonth.set(key, { text, date })
  }
  return Array.from(lastOfMonth.values())
    .sort((a, b) => a.date.getTime() - b.date.getTime())
    .map((entry) => entry.text)
}

/**
 * The contract a rank names, given the exchange's list of expiries.
 *
 * Returns null when the list cannot answer: an empty list, or a rank asking
 * for a contract further out than the exchange has listed. Null is rendered as
 * "unresolved" rather than silently as the nearest expiry, because quietly
 * substituting a different contract is how a leg ends up on an expiry nobody
 * chose.
 */
export function resolveExpiryRank(rank: ExpiryRank, expiries: string[]): string | null {
  const sorted = sortExpiries(expiries)
  if (sorted.length === 0) return null
  switch (rank) {
    case 'weekly':
      return sorted[0] ?? null
    case 'next_week':
      return sorted[1] ?? null
    case 'monthly':
    case 'current':
      return monthlyExpiries(sorted)[0] ?? null
    case 'next_month':
    case 'next':
      return monthlyExpiries(sorted)[1] ?? null
    default:
      return null
  }
}

/**
 * Strikes matching what was typed into the picker's filter box.
 *
 * Substring, not prefix. On a chain running 18000 to 30000 an operator hunting
 * 24000 is as likely to type "400" as "24", and a prefix match would hide every
 * strike that contains what they typed.
 */
export function filterStrikes(strikes: number[], filter: string): number[] {
  const needle = filter.trim()
  if (!needle) return strikes
  return strikes.filter((strike) => String(strike).includes(needle))
}

/**
 * Where a given underlying's derivatives are listed.
 *
 * The expiry lookup is keyed on the derivative exchange (NIFTY's options are
 * in NFO, not NSE_INDEX), while the option chain is keyed on the underlying's
 * own exchange. Two different answers for the same instrument, so both live
 * here rather than being guessed at each call site.
 */
export function derivativeExchangeFor(underlyingExchange: string): string {
  switch (underlyingExchange) {
    case 'NSE':
    case 'NSE_INDEX':
    case 'NFO':
      return 'NFO'
    case 'BSE':
    case 'BSE_INDEX':
    case 'BFO':
      return 'BFO'
    default:
      return underlyingExchange
  }
}

/**
 * How far a leg has moved in its favour, in points.
 *
 * Derived from the price ratchet the trailing stop itself uses rather than read
 * from a stored points value, so the two cannot disagree. Mirrors
 * `favorable_peak_points` in `services/strategy_module/state.py`.
 */
export function favorablePeakPoints(
  leg: Pick<
    LegState,
    'position' | 'entry_avg' | 'highest_price' | 'lowest_price' | 'favorable_points'
  >
): number {
  // Already measured by the sender, which is the socket's shape. Preferred
  // over re-deriving it so the two transports cannot disagree by a tick.
  if (leg.favorable_points != null && Number.isFinite(leg.favorable_points)) {
    return Math.max(0, leg.favorable_points)
  }
  const entry = leg.entry_avg || 0
  if (!entry) return 0
  if (leg.position === 'B') {
    const peak = leg.highest_price
    return peak ? Math.max(0, peak - entry) : 0
  }
  const trough = leg.lowest_price
  return trough ? Math.max(0, entry - trough) : 0
}

// ---------------------------------------------------------------------------
// Display formatting
//
// Three rules, deliberately different, because they answer different questions.
// The list is scanned, so a strategy that has not traded should read as blank
// rather than as a real zero. A detail page is read, so there a zero is a
// measurement and prints as one.
// ---------------------------------------------------------------------------

const EM_DASH = '—'

/**
 * A timestamp in IST.
 *
 * The API sends UTC with an explicit `+00:00` offset. Rendering in the
 * browser's zone would put an Indian trading session in whatever zone the
 * laptop is set to, so the zone is pinned and the suffix says which one it is.
 */
export function formatIst(iso: string | null | undefined, withSeconds = true): string {
  if (!iso) return EM_DASH
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: withSeconds ? 'numeric' : '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' as const } : {}),
    hour12: false,
    timeZone: 'Asia/Kolkata',
  })} IST`
}

/** P&L for the list: an untraded strategy reads as blank, not as 0.00. */
export function formatListPnl(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return EM_DASH
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

/** P&L for the detail page: zero is a measurement and prints as one. */
export function formatPnl(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return EM_DASH
  if (value === 0) return '0.00'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

/** P&L for a live tile, where an absent figure is not yet a zero. */
export function formatLivePnl(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return EM_DASH
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`
}

/** A price, or an em dash when there is not one yet. */
export function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return EM_DASH
  return Number(value).toFixed(2)
}

/** A duration in minutes, in the largest unit that keeps it readable. */
export function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return EM_DASH
  if (minutes < 60) return `${minutes.toFixed(1)}m`
  if (minutes < 24 * 60) return `${(minutes / 60).toFixed(1)}h`
  return `${(minutes / (24 * 60)).toFixed(1)}d`
}

/** Colour class for a signed number: green up, red down, inherited at zero. */
export function pnlToneClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return ''
  if (value > 0) return 'text-green-600'
  if (value < 0) return 'text-red-600'
  return ''
}
