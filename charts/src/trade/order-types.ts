/**
 * The order engine's public contract (order-engine.ts): the requests a host
 * sends, the receipts and results it gets back, the feed the engine drives,
 * the intents an order moves through, the engine's options, and the two
 * checks that tell what kind of failure a write met. Its own module so the
 * engine stays under the line limit; order-engine.ts re-exports all of it.
 */
import type { TradingCapabilitySource } from 'openalgo-charts';
import type { AccountStateSource } from './account';
import type { OrderDuration, TradingFeatureSource } from './features';
import type { ClientOrderState } from './order-state-machine';
import type { OrderRole, OrderSide, OrderStatus, OrderType } from './types';
import type { OrderConstraints } from './validation';

export interface PlaceRequest {
  symbol: string;
  exchange?: string | undefined;
  side: OrderSide;
  type: OrderType;
  qty: number;
  price?: number | undefined;
  triggerPrice?: number | undefined;
  /** Product: CNC (delivery), NRML (F&O carry), MIS (intraday). Required by OpenAlgo. */
  product?: 'CNC' | 'NRML' | 'MIS' | undefined;
  /** Idempotency token; a retry with the same token is never double-sent. */
  clientToken?: string | undefined;
  /** The account the order is for. Needs the `accounts` feature; never dropped on the way to the wire. */
  account?: string;
  /** Time in force. Omitted leaves the provider's own default. Needs the provider to list it. */
  duration?: OrderDuration;
  /** When a `GTD` order lapses, UTC seconds. Only with `GTD`. */
  expiresAt?: number;
  /** Margin multiplier to request. Needs the `leverage` feature. */
  leverage?: number;
}

/** What a provider says an order would cost before it is placed. Absent fields were not reported. */
export interface OrderPreview {
  readonly accountId?: string;
  readonly estimatedPrice?: number;
  readonly estimatedValue?: number;
  readonly marginRequired?: number;
  readonly marginAvailableAfter?: number;
  readonly fees?: number;
  readonly currency?: string;
  readonly warnings?: readonly string[];
  /** Set when the provider would refuse the order, and why. */
  readonly rejectReason?: string;
  /** UTC seconds. */
  readonly asOf?: number;
}

export type PreviewResult =
  | { ok: true; preview: OrderPreview; request: PlaceRequest }
  | { ok: false; reason: string; unsupported?: boolean; stale?: boolean };

/** Identifies the position a command acts on. */
export interface PositionCommandRequest {
  symbol: string;
  exchange?: string;
  product?: 'CNC' | 'NRML' | 'MIS';
  account?: string;
  /** Idempotency token for this command alone. */
  clientToken?: string;
}

export interface ClosePositionRequest extends PositionCommandRequest {
  /** How much to close. Omitted closes the whole position; a quantity is a partial close. */
  qty?: number;
}

export type ReversePositionRequest = PositionCommandRequest;

/** An entry whose stop and target legs the provider places and links itself. */
export interface BracketOrderRequest extends PlaceRequest {
  /** Trigger of the protective stop leg. */
  stopLoss: number;
  /** Limit price of the target leg. */
  takeProfit: number;
}

/** The broker's handle on a position command. `commandId` is what its order stream reports on. */
export interface CommandReceipt {
  commandId: string;
  orderIds?: readonly string[];
}

export interface BracketReceipt {
  orderId: string;
  stopLossId?: string;
  takeProfitId?: string;
}

export type TradingCommandKind = 'close' | 'reverse' | 'bracket';

/** What a command confirmation is asked to approve. The request carries the account it will use. */
export type TradingCommand =
  | { kind: 'close'; request: Readonly<ClosePositionRequest> }
  | { kind: 'reverse'; request: Readonly<ReversePositionRequest> }
  | { kind: 'bracket'; request: Readonly<BracketOrderRequest> };

export type OrderKind = 'order' | TradingCommandKind | 'bracket-stop' | 'bracket-target';

/**
 * One authoritative order row from the broker, with the client token it echoes
 * when it has one. An `Order` row spreads into it as it is.
 */
export interface BrokerOrderUpdate {
  id: string;
  clientToken?: string;
  status: OrderStatus;
  /** For a leg the provider placed and linked itself: the broker id of its entry. */
  parentId?: string;
  /** For such a leg: `sl` for the stop, `tp` for the target. With `parentId`, it finds a leg that echoes no token. */
  role?: OrderRole;
}

/** Fields a modify may change. Whole-order feeds fill the rest from their cache. */
export interface ModifyPatch {
  price?: number;
  triggerPrice?: number;
  qty?: number;
}

/**
 * The minimal broker write interface the `OrderEngine` drives: place / modify /
 * cancel. `OpenAlgoTradeFeed` implements this. Distinct from the base-tier
 * `TradeFeed` (a higher-level place + subscribe shape in `openalgo-charts`):
 * implement `OrderFeed` for the engine's write path.
 */
export interface OrderFeed {
  /** Optional support declaration; a configured provider can report unavailable metadata. */
  readonly capabilities?: TradingCapabilitySource | undefined;
  /** Declares preview, durations, leverage, accounts and the position commands. Omitted declares none. */
  readonly features?: TradingFeatureSource | undefined;
  place(req: PlaceRequest & { mode: TradeMode }): Promise<{ orderId: string }>;
  modify(orderId: string, patch: ModifyPatch): Promise<void>;
  cancel(orderId: string): Promise<void>;
  /** Read-only: what the order would cost. Must not place anything. */
  previewOrder?(req: PlaceRequest & { mode: TradeMode }): Promise<OrderPreview>;
  closePosition?(req: ClosePositionRequest & { mode: TradeMode }): Promise<CommandReceipt>;
  reversePosition?(req: ReversePositionRequest & { mode: TradeMode }): Promise<CommandReceipt>;
  /**
   * `legClientTokens` are the client tokens the engine gives the stop and
   * target legs. A provider that echoes them on the legs' rows lets a bracket
   * whose answer was lost be reconciled leg by leg.
   */
  placeBracket?(req: BracketOrderRequest & { mode: TradeMode; legClientTokens: { stopLoss: string; takeProfit: string } }): Promise<BracketReceipt>;
}

export type TradeMode = 'live' | 'analyzer';
export type GateFn = (req: PlaceRequest) => boolean | Promise<boolean>;

/**
 * Client-owned lifecycle of an intent, kept apart from the broker's own view.
 *
 *   BLOCKED            never sent: validation failed, the gate declined, or the
 *                      feed proved the request never left
 *   SUBMITTING         in flight
 *   SUBMITTED          transport returned success. NOT an order yet.
 *   AMBIGUOUS          transport failed, or a fresh book does not mention it.
 *                      May or may not be live at the exchange. Absorbing until
 *                      the broker speaks.
 *   ACKNOWLEDGED       the broker has accounted for it
 *   MODIFY_SUBMITTING  a modify is in flight
 *   CANCEL_SUBMITTING  a cancel is in flight
 *   RECONCILING        our picture may be behind; a snapshot is being fetched
 *   SETTLED            the broker reported a final state
 */
export type IntentState =
  | 'BLOCKED'
  | 'SUBMITTING'
  | 'SUBMITTED'
  | 'AMBIGUOUS'
  | 'ACKNOWLEDGED'
  | 'MODIFY_SUBMITTING'
  | 'CANCEL_SUBMITTING'
  | 'RECONCILING'
  | 'SETTLED';

/**
 * What a feed throws when the request PROVABLY never left: it failed before the
 * socket was written (bad arguments, no context cached, offline, DNS). Only this
 * marker releases an idempotency token, because only this proves there is
 * nothing live to double up on. See the catch in `placeOrder`.
 */
export interface PreflightFailure {
  readonly preflight: true;
}

/** True when a thrown value declares itself a pre-flight failure. */
export function isPreflightFailure(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { preflight?: unknown }).preflight === true;
}

/**
 * What a feed throws when the broker ANSWERED and refused: the request arrived
 * and was turned down, so nothing is live. That is an authoritative outcome,
 * unlike a transport failure, and it settles the intent as rejected. The token
 * stays claimed because the request did leave; a retry is a new decision.
 */
export interface BrokerRejection {
  readonly rejected: true;
}

/** True when a thrown value is the broker's explicit refusal rather than a lost answer. */
export function isBrokerRejection(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { rejected?: unknown }).rejected === true;
}

/** Extra fields for the one-click market order, which a chart button cannot otherwise set. */
export interface MarketOrderOptions {
  exchange?: string;
  product?: 'CNC' | 'NRML' | 'MIS';
  /** Idempotency token, so a double-clicked button places one order, not two. */
  clientToken?: string;
}

export interface ModifyOptions {
  /**
   * Explicit stop trigger. Omitted, the trigger follows the order type: SL-M
   * treats the dragged level as the trigger, SL carries its trigger at the
   * offset the order was placed with, and the rest have none.
   */
  triggerPrice?: number;
}

export interface OrderEngineOptions {
  feed: OrderFeed;
  /** Host restrictions combined with the feed's, rechecked before every write. */
  capabilities?: TradingCapabilitySource;
  constraints: OrderConstraints;
  mode?: TradeMode;
  /** Armed = fire immediately; otherwise the gate must approve each order. */
  armed?: boolean;
  gate?: GateFn;
  minModifyIntervalMs?: number;
  now?: () => number;
  idGen?: () => string;
  /** Called for modify validation and unsupported modify/cancel operations. */
  onValidationError?: (reason: string) => void;
  /**
   * How many settled orders stay readable before the oldest are dropped. A
   * trading session is a long-lived page and the per-order maps used to grow
   * for its whole life. 0 drops each order the moment it settles.
   */
  maxSettledOrders?: number;
  /** Host restrictions on the newer operations, combined with the feed's `features`; either can refuse. */
  features?: TradingFeatureSource;
  /**
   * The account selection. When set, every order and command is stamped with
   * it, one naming another account is refused, and a change while confirming
   * sends nothing. Pass the account view itself (an `AccountManager`) and a
   * selection from the other ledger is refused as well: a bare id cannot say
   * whether it is a live account about to take a sandbox order.
   */
  selectedAccount?: (() => string | null | undefined) | Pick<AccountStateSource, 'getState'>;
  /** Approves close, reverse and bracket commands when not armed. Omitted declines them. */
  confirmCommand?: (command: TradingCommand) => boolean | Promise<boolean>;
  /** Wall clock in UTC seconds, for expiry checks. Default `Date.now() / 1000`. */
  clock?: () => number;
}

export interface PlaceResult {
  ok: boolean;
  clientId?: string;
  state?: ClientOrderState | undefined;
  /** Client-owned intent. `ok: true` means SUBMITTED, never acknowledged. */
  intent?: IntentState | undefined;
  reason?: string;
}

export interface CommandResult extends PlaceResult {
  kind: TradingCommandKind;
  /** Client ids of a bracket's legs the provider has named, in its receipt or on its order stream. */
  legs?: { stopLoss?: string; takeProfit?: string };
}
