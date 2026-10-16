/**
 * Order engine (ARCHITECTURE.md §9.5): the chart-trading write path. Drives the
 * order state machine with: client-token idempotency, an arm/confirm gate,
 * pre-trade validation, rate-limited drag-modify, OCO linking, and analyzer
 * (sandbox) mode. Network-agnostic: it talks to an injected OrderFeed (the
 * FakeBroker simulates it in tests/demos).
 *
 * Three lifecycles are tracked per order and they are deliberately not merged:
 *
 *   state         the historical `ClientOrderState`. Existing consumers read it
 *                 and its meaning is unchanged, including the parts that are
 *                 optimistic (a resolved place() reads `working`).
 *   intent        what THIS client actually knows: submitted, ambiguous,
 *                 acknowledged, settled. A transport result never reaches past
 *                 SUBMITTED.
 *   brokerStatus  what the BROKER said. Undefined until an authoritative event
 *                 arrives (a stream or book update, or the broker's own explicit
 *                 refusal of the request), and written by nothing else.
 *
 * A resolved promise is not an order: it says the request left and an answer
 * came back, not that the exchange has anything. The v2 broker contract replaces
 * `state` outright with the two-field `OrderRow`; removing it here would break
 * every consumer of `ClientOrderState`, so the honest fields are added alongside
 * and the merge is deferred to v2.
 *
 * Closing, partly closing and reversing a position, and brackets whose legs the
 * provider links itself, are commands of their own with their own tokens. They
 * go only to a feed that declares and implements them. An opposite order is
 * never sent in place of a close: it can open a position the other way when
 * the one being closed has already gone, which is exactly the order nobody
 * asked for.
 */
import { transition, isTerminal, type ClientOrderState, type OrderEvent } from './order-state-machine';
import { validateOrder, validatePrice, validateQuantity, type OrderConstraints, type ValidationResult } from './validation';
import type { OrderSide, OrderStatus, OrderType } from './types';
import { checkTradingCapability, type TradingCapabilities, type TradingCapabilityRequest, type TradingCapabilityResult, type TradingCapabilitySource } from 'openalgo-charts';
import { checkTradingFeature, ORDER_DURATIONS, type OrderDuration, type TradingFeature, type TradingFeatureRequest, type TradingFeatureSource } from './features';
import { errorText, nonEmpty } from './text';
import {
  isBrokerRejection, isPreflightFailure,
  type BracketOrderRequest, type BracketReceipt, type BrokerOrderUpdate, type ClosePositionRequest, type CommandReceipt, type CommandResult,
  type GateFn, type IntentState, type MarketOrderOptions, type ModifyOptions, type ModifyPatch, type OrderEngineOptions, type OrderFeed,
  type OrderKind, type OrderPreview, type PlaceRequest, type PlaceResult, type PositionCommandRequest, type PreviewResult,
  type ReversePositionRequest, type TradeMode, type TradingCommand,
} from './order-types';

export * from './order-types';

/** What the engine remembers of a request. Position commands have no side or type of their own. */
interface TrackedRequest {
  symbol: string;
  exchange?: string | undefined;
  side?: OrderSide;
  type?: OrderType;
  qty?: number | undefined;
  price?: number | undefined;
  triggerPrice?: number | undefined;
  account?: string | undefined;
}

interface Tracked {
  clientId: string;
  kind: OrderKind;
  state: ClientOrderState;
  intent: IntentState;
  /** Last state the BROKER reported. Undefined until it reports one. */
  brokerStatus?: OrderStatus;
  brokerId?: string;
  req: TrackedRequest;
  /** New writes and broker reconciliation supersede older transport completions. */
  writeRevision: number;
  ocoPeer?: string;
  legs?: { stopLoss?: string; takeProfit?: string };
  /** A provider bracket's leg orders, kept so a leg first seen on the order stream can be adopted. */
  legReqs?: Record<LegSuffix, TrackedRequest>;
  /** Counted once into the settled ring, so a repeated terminal event cannot double-count. */
  pruned?: boolean;
}

type LegSuffix = 'stop' | 'target';
const LEG_SUFFIXES: readonly LegSuffix[] = ['stop', 'target'];
const LEG_KEY = { stop: 'stopLoss', target: 'takeProfit' } as const;

/** A position command whose outcome is not yet known holds the position against another. */
const UNRESOLVED: ReadonlySet<IntentState> = new Set<IntentState>(['SUBMITTING', 'SUBMITTED', 'AMBIGUOUS', 'RECONCILING']);

const PREVIEW_NUMBERS = ['estimatedPrice', 'estimatedValue', 'marginRequired', 'marginAvailableAfter', 'fees', 'asOf'] as const;

/** A readable preview, or the name of the first field that is not. */
function readPreview(raw: unknown): OrderPreview | string {
  if (typeof raw !== 'object' || raw === null) return 'preview';
  const r = raw as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of PREVIEW_NUMBERS) {
    if (r[key] === undefined) continue;
    if (typeof r[key] !== 'number' || !Number.isFinite(r[key])) return key;
    out[key] = r[key];
  }
  for (const key of ['accountId', 'currency', 'rejectReason'] as const) {
    if (r[key] === undefined) continue;
    if (typeof r[key] !== 'string') return key;
    out[key] = r[key];
  }
  if (r.warnings !== undefined) {
    if (!Array.isArray(r.warnings) || !r.warnings.every(w => typeof w === 'string')) return 'warnings';
    out.warnings = [...r.warnings];
  }
  return out as OrderPreview;
}

/**
 * The place flag and accepted modes still govern a close or reverse, so a host
 * lock stops them too. The order-type list does not: it describes new orders,
 * and a native close has no type the host chose.
 */
function withoutOrderTypes(source: TradingCapabilitySource | undefined): TradingCapabilitySource | undefined {
  if (source === undefined) return undefined;
  const strip = (c: TradingCapabilities | undefined): TradingCapabilities | undefined => {
    if (!c || typeof c !== 'object' || Array.isArray(c) || 'then' in c) return c;
    const { orderTypes: _types, ...rest } = c;
    return rest;
  };
  return typeof source === 'function' ? (request) => strip(source(request)) : strip(source);
}

type PatchResult = { ok: true; patch: ModifyPatch } | { ok: false; reason: string };

/** How a broker-reported status drives the client machine. `pending` adds nothing. */
const BROKER_EVENT: Readonly<Record<OrderStatus, OrderEvent | undefined>> = {
  pending: undefined,
  working: 'ack',
  partial: 'partialFill',
  filled: 'fill',
  cancelled: 'cancelled',
  rejected: 'reject',
};

const BROKER_FINAL: ReadonlySet<OrderStatus> = new Set<OrderStatus>(['filled', 'cancelled', 'rejected']);

const DEFAULT_MAX_SETTLED = 500;
/** How many unbound entries may have leg rows held for them at once. See `_hold`. */
const MAX_HELD_ENTRIES = 64;

export class OrderEngine {
  private readonly _feed: OrderFeed;
  private readonly _capabilities?: TradingCapabilitySource | undefined;
  private readonly _features?: TradingFeatureSource | undefined;
  private readonly _selectedAccount?: OrderEngineOptions['selectedAccount'];
  private readonly _confirmCommand?: ((command: TradingCommand) => boolean | Promise<boolean>) | undefined;
  private readonly _clock: () => number;
  private readonly _constraints: OrderConstraints;
  private readonly _mode: TradeMode;
  private readonly _armed: boolean;
  private readonly _gate?: GateFn | undefined;
  private readonly _minModifyMs: number;
  private readonly _now: () => number;
  private readonly _idGen: () => string;
  private readonly _onValidationError?: ((reason: string) => void) | undefined;
  private readonly _maxSettled: number;

  private readonly _orders = new Map<string, Tracked>();
  private readonly _byBroker = new Map<string, string>();
  private readonly _sentTokens = new Set<string>();
  private readonly _lastModifyAt = new Map<string, number>();
  private readonly _pendingModify = new Map<string, ModifyPatch>();
  /** Settled client ids, oldest first: the eviction order for the maps above. */
  private readonly _settledIds: string[] = [];
  /** Leg rows that named an entry before it was bound, by entry broker id, then leg broker id. */
  private readonly _heldLegs = new Map<string, Map<string, BrokerOrderUpdate>>();
  private _counter = 0;

  public constructor(opts: OrderEngineOptions) {
    this._feed = opts.feed;
    this._capabilities = opts.capabilities;
    this._features = opts.features;
    this._selectedAccount = opts.selectedAccount;
    this._confirmCommand = opts.confirmCommand;
    this._clock = opts.clock ?? (() => Date.now() / 1000);
    this._constraints = opts.constraints;
    this._mode = opts.mode ?? 'live';
    this._armed = opts.armed ?? false;
    this._gate = opts.gate;
    this._minModifyMs = opts.minModifyIntervalMs ?? 150;
    this._now = opts.now ?? (() => (typeof performance !== 'undefined' ? performance.now() : 0));
    this._idGen = opts.idGen ?? (() => `c${++this._counter}`);
    this._onValidationError = opts.onValidationError;
    this._maxSettled = Math.max(0, opts.maxSettledOrders ?? DEFAULT_MAX_SETTLED);
  }

  public get mode(): TradeMode { return this._mode; }
  public state(clientId: string): ClientOrderState | undefined { return this._orders.get(clientId)?.state; }

  /** Client-owned intent: what we did, as opposed to what the broker confirmed. */
  public intentState(clientId: string): IntentState | undefined { return this._orders.get(clientId)?.intent; }

  /**
   * The broker's own last word. Undefined means the broker has said nothing
   * about this order yet, however far `state` has advanced on transport results.
   */
  public brokerStatus(clientId: string): OrderStatus | undefined { return this._orders.get(clientId)?.brokerStatus; }

  /** Whether a row is a plain order, a position command, or a leg of a provider bracket. */
  public orderKind(clientId: string): OrderKind | undefined { return this._orders.get(clientId)?.kind; }

  /** The account an order or command was sent for, fixed when it was sent. */
  public orderAccount(clientId: string): string | undefined { return this._orders.get(clientId)?.req.account; }

  /** Client ids of a provider bracket's legs. */
  public bracketLegs(clientId: string): { stopLoss?: string; takeProfit?: string } | undefined {
    const legs = this._orders.get(clientId)?.legs;
    return legs === undefined ? undefined : { ...legs };
  }

  private _capability(request: TradingCapabilityRequest): TradingCapabilityResult {
    const feed = checkTradingCapability(this._feed.capabilities, request);
    return feed.supported ? checkTradingCapability(this._capabilities, request) : feed;
  }

  private _orderCapability(operation: 'modify' | 'cancel', order: Tracked): TradingCapabilityResult {
    return this._capability({ operation, symbol: order.req.symbol, exchange: order.req.exchange,
      type: order.req.type, mode: this._mode, orderId: order.brokerId });
  }

  /** The feed must declare a feature; host features, when given, may refuse it as well. */
  private _feature(request: TradingFeatureRequest): TradingCapabilityResult {
    const feed = checkTradingFeature(this._feed.features, request);
    return feed.supported && this._features !== undefined ? checkTradingFeature(this._features, request) : feed;
  }

  private _featureRequest(feature: TradingFeature, req: TrackedRequest & { duration?: OrderDuration }): TradingFeatureRequest {
    return { feature, symbol: req.symbol, exchange: req.exchange, account: req.account, mode: this._mode,
      type: req.type, duration: req.duration };
  }

  /**
   * Resolve the account an order goes to, writing it onto `req`. With a
   * selection configured the account is the one on screen; a request that
   * names a different one is refused rather than silently redirected.
   */
  private _account(req: { account?: string }): string | null {
    if (this._selectedAccount === undefined && req.account === undefined) return null;
    // A provider without accounts is the first thing to say: no selection
    // could make an account-bound order deliverable through it.
    const support = this._feature({ feature: 'accounts', account: req.account, mode: this._mode });
    if (!support.supported) return support.reason;
    if (this._selectedAccount !== undefined) {
      const selected = this._selection();
      if (!selected.ok) return selected.reason;
      if (req.account !== undefined && req.account !== selected.id) return `The order names account ${req.account} but ${selected.id} is selected`;
      req.account = selected.id;
    }
    return nonEmpty(req.account) ? null : 'The account id must be a non-empty string';
  }

  /** The selected account, or why there is none this engine may stamp on an order. */
  private _selection(): { ok: true; id: string } | { ok: false; reason: string } {
    const source = this._selectedAccount!;
    if (typeof source === 'function') {
      const id = source();
      return nonEmpty(id) ? { ok: true, id } : { ok: false, reason: 'No account is selected' };
    }
    const state = source.getState();
    const id = state.selectedId;
    if (!nonEmpty(id)) return { ok: false, reason: 'No account is selected' };
    const mode = state.mode !== this._mode ? state.mode : state.accounts.find(account => account.id === id)?.mode ?? state.mode;
    return mode === this._mode ? { ok: true, id } : { ok: false, reason: `The selected account ${id} is in ${mode} mode, not ${this._mode}` };
  }

  /** After an await: the account the user confirmed must still be the one selected. */
  private _accountStill(req: { account?: string }): string | null {
    if (this._selectedAccount === undefined) return null;
    const selected = this._selection();
    return selected.ok && selected.id === req.account ? null : 'The account changed before the order was sent; nothing was sent';
  }

  /** Duration, expiry and leverage: each is either carried by the provider or refused here. */
  private _schema(req: PlaceRequest): string | null {
    const duration = req.duration;
    if (duration !== undefined) {
      if (!ORDER_DURATIONS.includes(duration)) return `Unknown duration ${String(duration)}`;
      const support = this._feature(this._featureRequest('duration', req));
      if (!support.supported) return support.reason;
    }
    if (duration === 'GTD' && req.expiresAt === undefined) return 'A GTD order needs an expiry';
    if (req.expiresAt !== undefined) {
      if (duration !== 'GTD') return 'An expiry needs the GTD duration';
      if (!Number.isFinite(req.expiresAt) || req.expiresAt <= this._clock()) return 'The expiry is not in the future';
    }
    if (req.leverage !== undefined) {
      if (!Number.isFinite(req.leverage) || req.leverage <= 0) return 'Leverage must be a positive number';
      const support = this._feature(this._featureRequest('leverage', req));
      if (!support.supported) return support.reason;
    }
    return null;
  }

  /** Place capability, then the newer request fields. Null when the order may go. */
  private _permitOrder(req: PlaceRequest): string | null {
    const capability = this._capability({
      operation: 'place', symbol: req.symbol, exchange: req.exchange, type: req.type, mode: this._mode,
    });
    return capability.supported ? this._schema(req) : capability.reason;
  }

  /** Price, trigger and quantity checks, with both prices snapped. */
  private _validate(req: PlaceRequest): { ok: true; price: number | undefined; triggerPrice: number | undefined } | { ok: false; reason: string } {
    // Quantity constraints (freeze, lot grid) bind on EVERY order type; only the
    // price checks are conditional, because a market order has no price. Gating
    // the whole validate call on `price !== undefined` left the market order, the
    // one that cannot be taken back, as the single unchecked path.
    const v: ValidationResult = validateOrder(req.price, req.qty, this._constraints);
    if (!v.ok) return { ok: false, reason: v.reason ?? 'invalid order' };
    const price = req.price === undefined ? undefined : v.price;

    // A stop trigger is a price and earns the same tick snap and band check.
    let triggerPrice = req.triggerPrice;
    if (req.triggerPrice !== undefined) {
      const t = validateOrder(req.triggerPrice, req.qty, this._constraints);
      if (!t.ok) return { ok: false, reason: `trigger: ${t.reason}` };
      triggerPrice = t.price;
    }
    return { ok: true, price, triggerPrice };
  }

  /** The refusal for a token this engine has already put on the wire, if it has. */
  private _duplicate(token: string): PlaceResult | null {
    if (!this._sentTokens.has(token)) return null;
    const held = this._orders.get(token);
    return {
      ok: false,
      reason: held?.intent === 'AMBIGUOUS'
        ? 'duplicate clientToken: the first attempt was never confirmed and may be live'
        : 'duplicate clientToken (idempotent skip)',
      clientId: token,
      state: held?.state,
      intent: held?.intent,
    };
  }

  /**
   * A command's confirmation, the same contract as the order gate: it runs
   * before any network call, so declining or throwing frees the token and the
   * same one may be offered again. Callers skip it when armed, so an armed
   * command reaches the feed in the same tick, as an armed order does.
   */
  private async _confirmed(tokens: readonly string[], ask: (() => boolean | Promise<boolean>) | undefined): Promise<boolean> {
    let approved = false;
    try {
      approved = await (ask ? ask() : Promise.resolve(false));
    } catch (err) {
      this._release(tokens);
      throw err;
    }
    if (!approved) this._release(tokens);
    return approved;
  }

  private _release(tokens: readonly string[]): void {
    for (const token of tokens) this._sentTokens.delete(token);
  }

  /**
   * The transport answered with an id. `state` keeps its historical optimism
   * for existing consumers; `intent` stops at SUBMITTED and `brokerStatus`
   * stays undefined, because the transport answering is not the exchange
   * answering. An order stream can describe the order before the transport
   * returns, and its word outranks the transport's, so a row the broker has
   * already described is left as the broker left it.
   */
  private _submitted(o: Tracked, brokerId: string): void {
    if (o.brokerId === undefined) this._bind(o, brokerId);
    if (o.brokerStatus !== undefined) return;
    o.state = transition(o.state, 'ack');
    o.intent = 'SUBMITTED';
  }

  /** A write threw. Returns the reason to report. */
  private _failed(o: Tracked, err: unknown): string {
    const message = errorText(err);
    const preflight = isPreflightFailure(err);
    // The stream already described the order, so the lost answer changes nothing.
    if (!preflight && o.brokerStatus !== undefined) return message;
    if (!preflight && isBrokerRejection(err)) {
      // The broker answered and refused. That is its word, not a guess, so the
      // row settles as rejected; the token stays claimed because it was sent.
      o.brokerStatus = 'rejected';
      o.state = transition(o.state, 'reject');
      o.intent = 'SETTLED';
      this._settle(o);
      return `rejected by the broker: ${message}`;
    }
    o.state = transition(o.state, 'reject');
    o.intent = preflight ? 'BLOCKED' : 'AMBIGUOUS';
    // A transport failure says the RESPONSE did not arrive. It says nothing
    // about whether the REQUEST did: a 504, a socket reset after the body was
    // flushed, a tab suspended mid-flight all leave the order possibly live.
    // Releasing the token would make the retry indistinguishable from a first
    // attempt to every layer that dedupes on it, and double a live position on
    // a chart that draws Buy and Sell buttons. So the token is kept unless the
    // feed proves the request never left. Pessimistic is the safe default.
    if (preflight) this._sentTokens.delete(o.clientId);
    this._settle(o);
    return preflight ? message : `${message} (may have reached the broker; check the order book before retrying)`;
  }

  /**
   * A modify or cancel threw. It may still have been applied: only a
   * pre-flight failure rules that out, and leaves the order where it was last
   * known to be, unless it has moved on from `pending` since.
   */
  private _writeFailed(o: Tracked, err: unknown, pending: IntentState, previousState: ClientOrderState, previousIntent: IntentState): void {
    if (isPreflightFailure(err)) {
      if (o.intent === pending) { o.state = previousState; o.intent = previousIntent; }
      this._onValidationError?.(errorText(err));
    } else {
      o.state = transition(o.state, 'reject');
      o.intent = 'AMBIGUOUS';
    }
  }

  /** `ok` after a failure only when the broker's own stream already reports the write as accepted. */
  private _outcome(o: Tracked, reason?: string): PlaceResult {
    const ok = reason === undefined || (o.brokerStatus !== undefined && o.brokerStatus !== 'rejected');
    return { ok, clientId: o.clientId, state: o.state, intent: o.intent, ...(reason === undefined ? {} : { reason }) };
  }

  public async placeOrder(request: PlaceRequest): Promise<PlaceResult> {
    const req = { ...request };
    const v = this._validate(req);
    if (!v.ok) return { ok: false, reason: v.reason, intent: 'BLOCKED' };

    const token = req.clientToken ?? this._idGen();
    // Claim the token BEFORE the first await. The confirm gate below is
    // asynchronous, and claiming after it let two clicks sail through the
    // duplicate check together and place the order twice.
    const duplicate = this._duplicate(token);
    if (duplicate !== null) return duplicate;
    const refusal = this._permitOrder(req) ?? this._account(req);
    if (refusal !== null) return { ok: false, reason: refusal, intent: 'BLOCKED' };
    this._sentTokens.add(token);

    // The gate runs before any network call, so a gate that throws or declines
    // frees the token (see `_confirmed`): the request provably never left.
    const gate = this._gate;
    if (!this._armed && !(await this._confirmed([token], gate ? () => gate({ ...req }) : undefined))) {
      return { ok: false, reason: 'not confirmed', intent: 'BLOCKED' };
    }

    // Capabilities, features and the account can all change while the user
    // reads the confirmation, so every one of them is asked again.
    const current = this._permitOrder(req) ?? this._accountStill(req);
    if (current !== null) {
      this._sentTokens.delete(token);
      return { ok: false, reason: current, intent: 'BLOCKED' };
    }

    const finalReq: PlaceRequest = { ...req, price: v.price, triggerPrice: v.triggerPrice, clientToken: token };
    const tracked: Tracked = { clientId: token, kind: 'order', state: 'pending_place', intent: 'SUBMITTING', req: finalReq, writeRevision: 0 };
    this._orders.set(token, tracked);

    try {
      const { orderId } = await this._feed.place({ ...finalReq, mode: this._mode });
      this._submitted(tracked, orderId);
      return this._outcome(tracked);
    } catch (err) {
      return this._outcome(tracked, this._failed(tracked, err));
    }
  }

  /**
   * Ask the provider what an order would cost. Read-only: it claims no token,
   * runs no confirmation and never calls `place`. The same checks as placing
   * apply, so a preview is never shown for an order that would be refused here.
   */
  public async previewOrder(request: PlaceRequest): Promise<PreviewResult> {
    const req = { ...request };
    const support = this._feature(this._featureRequest('preview', req));
    if (!support.supported) return { ok: false, unsupported: true, reason: support.reason };
    const preview = this._feed.previewOrder;
    if (preview === undefined) return { ok: false, unsupported: true, reason: 'Order preview is not implemented by this feed' };
    const v = this._validate(req);
    if (!v.ok) return { ok: false, reason: v.reason };
    const refusal = this._permitOrder(req) ?? this._account(req);
    if (refusal !== null) return { ok: false, reason: refusal };
    const sent: PlaceRequest = { ...req, price: v.price, triggerPrice: v.triggerPrice };
    const stale = { ok: false, stale: true, reason: 'The account changed during the preview; preview again' } as const;
    let raw: unknown;
    try {
      raw = await preview.call(this._feed, { ...sent, mode: this._mode });
    } catch (err) {
      return this._accountStill(sent) === null ? { ok: false, reason: errorText(err) } : stale;
    }
    if (this._accountStill(sent) !== null) return stale;
    const read = readPreview(raw);
    if (typeof read === 'string') return { ok: false, reason: `The preview could not be read: ${read}` };
    if (read.accountId !== undefined && sent.account !== undefined && read.accountId !== sent.account) {
      return { ok: false, stale: true, reason: `The preview answered for account ${read.accountId}, not ${sent.account}` };
    }
    return { ok: true, preview: read, request: sent };
  }

  /** Close a whole position, or part of it when `qty` is given, through the provider's own close. */
  public closePosition(request: ClosePositionRequest): Promise<CommandResult> {
    const close = this._feed.closePosition;
    return this._positionCommand('close', { ...request }, request.qty === undefined ? 'close' : 'partialClose',
      close === undefined ? undefined : req => close.call(this._feed, { ...req, mode: this._mode }));
  }

  /** Reverse a position through the provider's own reverse. */
  public reversePosition(request: ReversePositionRequest): Promise<CommandResult> {
    const reverse = this._feed.reversePosition;
    return this._positionCommand('reverse', { ...request }, 'reverse',
      reverse === undefined ? undefined : req => reverse.call(this._feed, { ...req, mode: this._mode }));
  }

  /**
   * Whether a tracked command acts on the position a new one names. An
   * omitted exchange is whatever default the provider applies, so it matches
   * any exchange: keyed on the literal field, one position asked for with and
   * without its exchange let a second close out while the first was unresolved.
   */
  private static _samePosition(a: TrackedRequest, b: PositionCommandRequest): boolean {
    return a.symbol === b.symbol && (a.account ?? '') === (b.account ?? '')
      && (a.exchange === undefined || b.exchange === undefined || a.exchange === b.exchange);
  }

  /**
   * Everything a close or reverse must pass, asked before confirmation and
   * again after it. The position lock is here: while an earlier close or
   * reverse on the same position has no known outcome, a second one could
   * reduce it twice or flip it back, so it waits for the broker's word.
   */
  private _permitCommand(kind: 'close' | 'reverse', req: ClosePositionRequest, feature: TradingFeature, implemented: boolean): string | null {
    const request: TradingCapabilityRequest = { operation: 'place', symbol: req.symbol, exchange: req.exchange, mode: this._mode };
    for (const source of [this._feed.capabilities, this._capabilities]) {
      const write = checkTradingCapability(withoutOrderTypes(source), request);
      if (!write.supported) return write.reason;
    }
    const support = this._feature(this._featureRequest(feature, req));
    if (!support.supported) return support.reason;
    if (!implemented) return `${kind === 'close' ? 'Closing a position' : 'Reversing a position'} is not implemented by this feed`;
    for (const row of this._orders.values()) {
      if ((row.kind === 'close' || row.kind === 'reverse') && UNRESOLVED.has(row.intent) && OrderEngine._samePosition(row.req, req)) {
        return `A previous close or reverse for ${req.symbol} is unresolved; reconcile it with the broker first`;
      }
    }
    return null;
  }

  private async _positionCommand(
    kind: 'close' | 'reverse',
    req: ClosePositionRequest,
    feature: TradingFeature,
    send: ((req: ClosePositionRequest) => Promise<CommandReceipt>) | undefined,
  ): Promise<CommandResult> {
    const blocked = (reason: string): CommandResult => ({ ok: false, kind, reason, intent: 'BLOCKED' });
    if (!nonEmpty(req.symbol)) return blocked(`A ${kind} needs a symbol`);
    if (req.qty !== undefined) {
      const q = validateQuantity(req.qty, this._constraints);
      if (!q.ok) return blocked(q.reason ?? 'invalid quantity');
    }
    const token = req.clientToken ?? this._idGen();
    const duplicate = this._duplicate(token);
    if (duplicate !== null) return { ...duplicate, kind };
    const refusal = this._account(req) ?? this._permitCommand(kind, req, feature, send !== undefined);
    if (refusal !== null) return blocked(refusal);
    this._sentTokens.add(token);
    const finalReq: ClosePositionRequest = { ...req, clientToken: token };
    const ask = this._confirmCommand;
    if (!this._armed && !await this._confirmed([token], ask ? () => ask({ kind, request: { ...finalReq } }) : undefined)) return blocked('not confirmed');
    const current = this._accountStill(finalReq) ?? this._permitCommand(kind, finalReq, feature, send !== undefined);
    if (current !== null) {
      this._sentTokens.delete(token);
      return blocked(current);
    }
    const tracked: Tracked = {
      clientId: token, kind, state: 'pending_place', intent: 'SUBMITTING', writeRevision: 0,
      req: { symbol: finalReq.symbol, exchange: finalReq.exchange, qty: finalReq.qty, account: finalReq.account },
    };
    this._orders.set(token, tracked);
    try {
      const receipt = await send!(finalReq);
      // The request left, and an answer naming nothing the stream could report
      // on is the same as not knowing whether it happened.
      if (!nonEmpty(receipt?.commandId)) return { ...this._outcome(tracked, this._failed(tracked, new Error('the broker returned no command id'))), kind };
      this._submitted(tracked, receipt.commandId);
      return { ...this._outcome(tracked), kind };
    } catch (err) {
      return { ...this._outcome(tracked, this._failed(tracked, err)), kind };
    }
  }

  /**
   * Place an entry whose stop and target legs the provider places and links
   * itself. The legs are never linked client-side: one-cancels-other is the
   * provider's job here, and a second, client-side link would race it.
   */
  public async placeBracket(request: BracketOrderRequest): Promise<CommandResult> {
    const req = { ...request };
    const blocked = (reason: string): CommandResult => ({ ok: false, kind: 'bracket', reason, intent: 'BLOCKED' });
    const v = this._validate(req);
    if (!v.ok) return blocked(v.reason);
    const stop = validatePrice(req.stopLoss, this._constraints);
    if (!stop.ok) return blocked(`stop: ${stop.reason}`);
    const target = validatePrice(req.takeProfit, this._constraints);
    if (!target.ok) return blocked(`target: ${target.reason}`);
    const stopLoss = stop.price ?? req.stopLoss;
    const takeProfit = target.price ?? req.takeProfit;
    // A market entry has no price of its own, so only the legs' order is checked.
    const entry = req.type === 'SL-M' ? v.triggerPrice : v.price;
    const buy = req.side === 'BUY';
    const [low, high] = buy ? [stopLoss, takeProfit] : [takeProfit, stopLoss];
    if (!(low < high) || (entry !== undefined && !(low < entry && entry < high))) {
      return blocked('The stop and target are on the wrong side of the entry');
    }

    const token = req.clientToken ?? this._idGen();
    const legClientTokens = { stopLoss: `${token}:stop`, takeProfit: `${token}:target` };
    // The legs' tokens go on the wire with the entry's, so any of the three
    // already sent makes this a repeat.
    const tokens = [token, legClientTokens.stopLoss, legClientTokens.takeProfit];
    for (const claimed of tokens) {
      const duplicate = this._duplicate(claimed);
      if (duplicate !== null) return { ...duplicate, kind: 'bracket' };
    }
    const place = this._feed.placeBracket;
    const permit = (): string | null => {
      const support = this._feature(this._featureRequest('brackets', req));
      if (!support.supported) return support.reason;
      if (place === undefined) return 'Bracket placement is not implemented by this feed';
      return this._permitOrder(req);
    };
    const refusal = this._account(req) ?? permit();
    if (refusal !== null) return blocked(refusal);
    for (const claimed of tokens) this._sentTokens.add(claimed);
    const finalReq: BracketOrderRequest = { ...req, price: v.price, triggerPrice: v.triggerPrice, stopLoss, takeProfit, clientToken: token };
    const ask = this._confirmCommand;
    if (!this._armed && !await this._confirmed(tokens, ask ? () => ask({ kind: 'bracket', request: { ...finalReq } }) : undefined)) return blocked('not confirmed');
    const current = this._accountStill(finalReq) ?? permit();
    if (current !== null) {
      this._release(tokens);
      return blocked(current);
    }
    const exit: OrderSide = buy ? 'SELL' : 'BUY';
    const leg = { symbol: req.symbol, exchange: req.exchange, side: exit, qty: req.qty, account: req.account };
    const tracked: Tracked = {
      clientId: token, kind: 'bracket', state: 'pending_place', intent: 'SUBMITTING', req: finalReq, writeRevision: 0,
      legReqs: { stop: { ...leg, type: 'SL-M', triggerPrice: stopLoss }, target: { ...leg, type: 'LIMIT', price: takeProfit } },
    };
    this._orders.set(token, tracked);
    // The legs may already be known from the order stream, whatever the transport says.
    const result = (reason?: string): CommandResult => ({
      ...this._outcome(tracked, reason), kind: 'bracket', ...(tracked.legs === undefined ? {} : { legs: { ...tracked.legs } }),
    });
    let receipt: BracketReceipt;
    try {
      receipt = await place!.call(this._feed, { ...finalReq, mode: this._mode, legClientTokens });
    } catch (err) {
      const reason = this._failed(tracked, err);
      if (isPreflightFailure(err)) this._release(tokens);
      return result(reason);
    }
    if (!nonEmpty(receipt?.orderId)) return result(this._failed(tracked, new Error('the broker returned no order id')));
    this._submitted(tracked, receipt.orderId);
    for (const [suffix, brokerId] of [['stop', receipt.stopLossId], ['target', receipt.takeProfitId]] as const) {
      if (nonEmpty(brokerId)) this._submitted(this._leg(tracked, suffix), brokerId);
    }
    return result();
  }

  /**
   * The row for one leg of a provider bracket, made on first sight. The
   * receipt names the legs when it arrives; the order stream or a read of the
   * book can name them first, or instead, when the receipt was lost.
   */
  private _leg(parent: Tracked, suffix: LegSuffix): Tracked {
    const clientId = `${parent.clientId}:${suffix}`;
    let row = this._orders.get(clientId);
    if (row === undefined) {
      row = { clientId, kind: suffix === 'stop' ? 'bracket-stop' : 'bracket-target', state: 'pending_place', intent: 'SUBMITTING',
        writeRevision: 0, req: { ...parent.legReqs![suffix] } };
      this._orders.set(clientId, row);
    }
    parent.legs = { ...parent.legs, [LEG_KEY[suffix]]: clientId };
    return row;
  }

  /** One-click market order. Omitting `opts` is exactly the previous behaviour. */
  public placeMarket(symbol: string, side: OrderSide, qty: number, opts?: MarketOrderOptions): Promise<PlaceResult> {
    return this.placeOrder({
      symbol,
      side,
      type: 'MARKET',
      qty,
      exchange: opts?.exchange,
      product: opts?.product,
      clientToken: opts?.clientToken,
    });
  }

  /** Link two orders as OCO: when one fills/cancels, the other is cancelled. */
  public linkOco(clientIdA: string, clientIdB: string): void {
    const a = this._orders.get(clientIdA);
    const b = this._orders.get(clientIdB);
    if (a && b) { a.ocoPeer = clientIdB; b.ocoPeer = clientIdA; }
  }

  /**
   * Rate-limited modify (drag): coalesces to the latest, sends at most every
   * minModifyMs. An invalid price (tick/band/freeze) is NOT enqueued or sent:
   * it surfaces via `onValidationError` so the UI can snap the line back.
   */
  public requestModify(clientId: string, price: number, opts?: ModifyOptions): void {
    const triggerPrice = opts?.triggerPrice;
    const o = this._orders.get(clientId);
    if (o === undefined || isTerminal(o.state)) return;
    if (this._isPositionCommand(o)) return;
    const capability = this._orderCapability('modify', o);
    if (!capability.supported) {
      this._pendingModify.delete(clientId);
      this._onValidationError?.(capability.reason);
      return;
    }
    const built = this._buildModifyPatch(o, price, triggerPrice);
    if (!built.ok) {
      this._onValidationError?.(built.reason);
      return; // do NOT send an out-of-band modify to the broker
    }
    this._pendingModify.set(clientId, built.patch);
    const last = this._lastModifyAt.get(clientId) ?? -Infinity;
    if (this._now() - last >= this._minModifyMs) void this._flushModify(clientId);
  }

  /** Force-send any pending modify (e.g. on drag end). */
  public commitModify(clientId: string): Promise<void> {
    return this._flushModify(clientId);
  }

  /**
   * Turn a dragged level into a patch the broker can apply without losing a
   * field it already holds.
   */
  private _buildModifyPatch(o: Tracked, price: number, explicitTrigger?: number): PatchResult {
    const v = validateOrder(price, o.req.qty ?? Number.NaN, this._constraints);
    if (!v.ok) return { ok: false, reason: v.reason ?? 'invalid modify price' };
    const level = v.price ?? price;

    if (o.req.type === 'SL-M') {
      // Stop-market has a trigger and no limit price at all. The dragged level
      // IS the trigger; writing it to `price` dropped the stop and handed the
      // broker a limit the order never had.
      const trigger = explicitTrigger ?? level;
      const t = this._validateTrigger(trigger, o.req.qty);
      return t.ok ? { ok: true, patch: { triggerPrice: t.price } } : t;
    }

    if (o.req.type === 'SL') {
      // Stop-limit moves as a pair. The gap between limit and trigger is the
      // user's decision, so carry it rather than collapsing the two onto one
      // level or, as before, leaving the trigger behind at the old price.
      const offset = o.req.triggerPrice !== undefined && o.req.price !== undefined
        ? o.req.triggerPrice - o.req.price
        : 0;
      const trigger = explicitTrigger ?? level + offset;
      const t = this._validateTrigger(trigger, o.req.qty);
      return t.ok ? { ok: true, patch: { price: level, triggerPrice: t.price } } : t;
    }

    if (explicitTrigger !== undefined) {
      const t = this._validateTrigger(explicitTrigger, o.req.qty);
      return t.ok ? { ok: true, patch: { price: level, triggerPrice: t.price } } : t;
    }
    return { ok: true, patch: { price: level } };
  }

  private _validateTrigger(trigger: number, qty: number | undefined): { ok: true; price: number } | { ok: false; reason: string } {
    const t = validateOrder(trigger, qty ?? Number.NaN, this._constraints);
    if (!t.ok) return { ok: false, reason: `trigger: ${t.reason ?? 'invalid'}` };
    return { ok: true, price: t.price ?? trigger };
  }

  private async _flushModify(clientId: string): Promise<void> {
    const patch = this._pendingModify.get(clientId);
    const o = this._orders.get(clientId);
    if (patch === undefined || o === undefined || o.brokerId === undefined) return;
    this._pendingModify.delete(clientId);
    const capability = this._orderCapability('modify', o);
    if (!capability.supported) {
      this._onValidationError?.(capability.reason);
      return;
    }
    this._lastModifyAt.set(clientId, this._now());
    const previousState = o.state;
    const previousIntent = o.intent;
    const revision = ++o.writeRevision;
    o.state = transition(o.state, 'submitModify');
    o.intent = 'MODIFY_SUBMITTING';
    try {
      await this._feed.modify(o.brokerId, { ...patch });
      if (revision !== o.writeRevision) return;
      o.state = transition(o.state, 'ack');
      o.intent = 'ACKNOWLEDGED';
      // Track what we asked for, so the next drag derives its stop offset from
      // the level the order is now resting at.
      if (patch.price !== undefined) o.req = { ...o.req, price: patch.price };
      if (patch.triggerPrice !== undefined) o.req = { ...o.req, triggerPrice: patch.triggerPrice };
    } catch (err) {
      if (revision === o.writeRevision) this._writeFailed(o, err, 'MODIFY_SUBMITTING', previousState, previousIntent);
    }
  }

  public async cancelOrder(clientId: string): Promise<void> {
    const o = this._orders.get(clientId);
    if (o === undefined || o.brokerId === undefined || isTerminal(o.state)) return;
    if (this._isPositionCommand(o)) return;
    const capability = this._orderCapability('cancel', o);
    if (!capability.supported) {
      this._onValidationError?.(capability.reason);
      return;
    }
    const previousState = o.state;
    const previousIntent = o.intent;
    const revision = ++o.writeRevision;
    o.state = transition(o.state, 'submitCancel');
    o.intent = 'CANCEL_SUBMITTING';
    try {
      await this._feed.cancel(o.brokerId);
      if (revision !== o.writeRevision) return;
      o.state = transition(o.state, 'cancelled');
      // Transport-level only. The order line may stop drawing, but the broker
      // has not said the order is gone, so `brokerStatus` stays untouched.
      o.intent = 'ACKNOWLEDGED';
      this._cancelOcoPeer(o);
      this._settle(o);
    } catch (err) {
      if (revision === o.writeRevision) this._writeFailed(o, err, 'CANCEL_SUBMITTING', previousState, previousIntent);
    }
  }

  /** Broker fill event (by broker id). Advances state and triggers OCO. */
  public onFill(brokerId: string, full: boolean): void {
    this.onBrokerUpdate(brokerId, full ? 'filled' : 'partial');
  }

  /**
   * Authoritative state from the broker: an order-stream push or a poll of the
   * book. This is the ONLY input that writes `brokerStatus`; place, modify and
   * cancel resolving never do.
   */
  public onBrokerUpdate(brokerId: string, status: OrderStatus): void {
    const clientId = this._byBroker.get(brokerId);
    if (clientId === undefined) return;
    const o = this._orders.get(clientId);
    if (o === undefined) return;
    o.writeRevision++;
    o.brokerStatus = status;
    // A terminal state on an AMBIGUOUS row is the client's own guess: a lost
    // answer reads `rejected`, a row a snapshot missed reads `stale`. The
    // broker describing the row is the first real word on it, so the machine
    // starts again from the place. Left on the guess, a live order could be
    // neither cancelled nor modified, and would be pruned as if it had settled.
    if (o.intent === 'AMBIGUOUS' && isTerminal(o.state)) o.state = 'pending_place';
    // Being reported at all, even as pending or already cancelled (an IOC that
    // found nothing), means the broker accepted the order. That is the step
    // the machine needs before a cancel or a modify can be asked of it.
    if (o.state === 'pending_place' && status !== 'rejected') o.state = transition(o.state, 'ack');
    const event = BROKER_EVENT[status];
    if (event !== undefined) o.state = transition(o.state, event);
    o.intent = BROKER_FINAL.has(status) ? 'SETTLED' : 'ACKNOWLEDGED';
    if (status === 'filled') this._cancelOcoPeer(o);
    this._settle(o);
  }

  /**
   * An order row from the broker's stream or book, matched by broker id or,
   * failing that, by the client token the broker echoes. The token is the only
   * handle on a write whose answer was lost: it is how an AMBIGUOUS row learns
   * its broker id and its outcome from the broker rather than from a guess.
   * Rows may come in any order: a bracket leg that names an entry not yet
   * bound is held, and applied when the entry binds.
   */
  public onBrokerOrder(update: BrokerOrderUpdate): void {
    if (!this._byBroker.has(update.id)) {
      const row = this._unbound(update);
      if (row === undefined) this._hold(update);
      else if (row.brokerId === undefined) this._bind(row, update.id);
    }
    this.onBrokerUpdate(update.id, update.status);
  }

  /**
   * Give a row its broker id. A bracket entry then takes the leg rows that
   * named it before it was bound, ahead of its own status: a filled entry
   * can settle and leave the ring at once, and its legs would have no entry
   * left to find.
   */
  private _bind(o: Tracked, brokerId: string): void {
    o.brokerId = brokerId;
    this._byBroker.set(brokerId, o.clientId);
    const held = this._heldLegs.get(brokerId);
    if (held === undefined) return;
    this._heldLegs.delete(brokerId);
    if (o.legReqs === undefined) return;
    for (const update of held.values()) this.onBrokerOrder(update);
    if (!this._awaitingEntry()) this._heldLegs.clear();
  }

  /**
   * Keep a leg row whose entry has no broker id here yet, until `_bind`
   * gives it one. A provider that echoes no leg token names a leg only by
   * its entry, and may well report the leg first: its history lists the
   * newest rows first, and its stream can describe the legs before the
   * transport returns the entry's id. Rows are held only while a bracket
   * this engine sent is still waiting for that id, since no other could
   * ever claim them, and for a bounded number of entries, since other
   * sessions' brackets arrive alongside and are never claimed. The latest
   * row for a leg is the one kept.
   */
  private _hold(update: BrokerOrderUpdate): void {
    if (update.parentId === undefined || (update.role !== 'sl' && update.role !== 'tp')) return;
    if (!this._awaitingEntry()) {
      this._heldLegs.clear();
      return;
    }
    let held = this._heldLegs.get(update.parentId);
    if (held === undefined) {
      held = new Map();
      this._heldLegs.set(update.parentId, held);
      if (this._heldLegs.size > MAX_HELD_ENTRIES) this._heldLegs.delete(this._heldLegs.keys().next().value!);
    }
    held.set(update.id, { ...update });
  }

  /** Whether a bracket this engine sent could still be bound to an entry the broker reports. */
  private _awaitingEntry(): boolean {
    for (const o of this._orders.values()) {
      if (o.legReqs !== undefined && o.brokerId === undefined && UNRESOLVED.has(o.intent)) return true;
    }
    return false;
  }

  /**
   * The row a broker id not seen before belongs to: the one its echoed token
   * names, or a leg of a bracket this engine sent, found by the leg's own
   * token or by its entry and role. Adopting a leg on first sight is how a
   * bracket whose answer was lost still gets legs that can be cancelled,
   * modified and filled. A leg found only by an entry not yet bound is held
   * until the entry binds, so the order the broker reports rows in does not
   * matter.
   */
  private _unbound(update: BrokerOrderUpdate): Tracked | undefined {
    const token = update.clientToken;
    if (token !== undefined) {
      const row = this._orders.get(token);
      if (row !== undefined) return row;
      for (const suffix of LEG_SUFFIXES) {
        const parent = token.endsWith(`:${suffix}`) && this._sentTokens.has(token) ? this._orders.get(token.slice(0, -suffix.length - 1)) : undefined;
        if (parent?.legReqs !== undefined) return this._leg(parent, suffix);
      }
    }
    const suffix = update.role === 'sl' ? 'stop' : update.role === 'tp' ? 'target' : undefined;
    const parentId = update.parentId === undefined ? undefined : this._byBroker.get(update.parentId);
    const parent = parentId === undefined ? undefined : this._orders.get(parentId);
    return suffix !== undefined && parent?.legReqs !== undefined ? this._leg(parent, suffix) : undefined;
  }

  /**
   * Drop an AMBIGUOUS row and free its token, after the host has established
   * from the broker's complete book that the request never arrived. Nothing
   * here can decide that on its own, which is why it is a separate call. Any
   * other row is left alone and the call returns false.
   */
  public releaseAmbiguous(clientId: string): boolean {
    const o = this._orders.get(clientId);
    if (o === undefined || o.intent !== 'AMBIGUOUS') return false;
    this._orders.delete(clientId);
    this._sentTokens.delete(clientId);
    // A bracket that never arrived took its legs' tokens nowhere either.
    if (o.legReqs !== undefined) {
      for (const suffix of LEG_SUFFIXES) if (!this._orders.has(`${clientId}:${suffix}`)) this._sentTokens.delete(`${clientId}:${suffix}`);
      if (!this._awaitingEntry()) this._heldLegs.clear();
    }
    if (o.brokerId !== undefined) this._byBroker.delete(o.brokerId);
    this._lastModifyAt.delete(clientId);
    this._pendingModify.delete(clientId);
    return true;
  }

  /** A close or reverse is not an order the user can drag or cancel from here. */
  private _isPositionCommand(o: Tracked): boolean {
    if (o.kind !== 'close' && o.kind !== 'reverse') return false;
    this._onValidationError?.(`A ${o.kind} command cannot be modified or cancelled`);
    return true;
  }

  private _cancelOcoPeer(o: Tracked): void {
    if (o.ocoPeer === undefined) return;
    const peer = this._orders.get(o.ocoPeer);
    if (peer && !isTerminal(peer.state)) void this.cancelOrder(peer.clientId);
  }

  /**
   * Enter reconciliation: the connection dropped or a gap was seen, so our
   * picture may be behind. Nothing is concluded here; call `onReconnect` with
   * the fresh book to conclude anything. An AMBIGUOUS row is left alone, since
   * only the broker can take it out of that state.
   */
  public beginReconcile(): void {
    for (const o of this._orders.values()) {
      if (isTerminal(o.state) || o.intent === 'AMBIGUOUS') continue;
      o.writeRevision++;
      o.intent = 'RECONCILING';
    }
  }

  /**
   * Apply a fresh order-book snapshot. Absence is not death: `state` still goes
   * to `stale` for existing consumers, but the intent becomes AMBIGUOUS, because
   * an order missing from one snapshot means our picture is incomplete, not that
   * the broker cancelled it. Such a row is never pruned. (v2 drops `stale`
   * entirely; that removal has to wait for the contract bump.)
   */
  public onReconnect(presentBrokerIds: ReadonlySet<string>): void {
    for (const o of this._orders.values()) {
      if (isTerminal(o.state)) continue;
      o.writeRevision++;
      if (o.brokerId !== undefined && presentBrokerIds.has(o.brokerId)) {
        o.intent = 'ACKNOWLEDGED';
        continue;
      }
      o.state = transition(o.state, 'reconnectAbsent');
      o.intent = 'AMBIGUOUS';
    }
  }

  /**
   * Terminal bookkeeping. Per-order scratch (throttle stamps, coalesced patches)
   * goes at once; the row itself survives so a host can still read the final
   * state, and only the oldest are evicted once `maxSettledOrders` is passed.
   *
   * Idempotency tokens are never pruned. They are the record of what this client
   * has put on the wire, and dropping one so a map stays small is the same
   * mistake as releasing it on a transport error.
   */
  private _settle(o: Tracked): void {
    if (o.pruned === true || !isTerminal(o.state)) return;
    // An ambiguous or reconciling row is not over, whatever `state` says.
    if (o.intent === 'AMBIGUOUS' || o.intent === 'RECONCILING') return;
    o.pruned = true;
    this._lastModifyAt.delete(o.clientId);
    this._pendingModify.delete(o.clientId);
    this._settledIds.push(o.clientId);
    while (this._settledIds.length > this._maxSettled) {
      const id = this._settledIds.shift();
      if (id === undefined) break;
      const row = this._orders.get(id);
      // A token released by a pre-flight failure can be offered again, so the id
      // may now hold a LIVE row. Evicting that would drop a working order from
      // the book and with it the broker-id lookup that routes its fills.
      if (row === undefined || row.pruned !== true) continue;
      this._orders.delete(id);
      if (row.brokerId !== undefined) this._byBroker.delete(row.brokerId);
      this._lastModifyAt.delete(id);
      this._pendingModify.delete(id);
    }
  }
}
