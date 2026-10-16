/**
 * Deterministic in-memory broker simulator (ARCHITECTURE.md §11.1). Holds order
 * and position snapshots and notifies subscribers, so the trade layer can be
 * tested and demoed with zero network. It answers the order engine's place,
 * modify and cancel with an order state machine of its own, and a host that
 * only reads can seed snapshots and emit LTP.
 *
 * Constructed with `accounts`, it also simulates a provider with account
 * ledgers: balances and margin, fills at a mark price, executions and order
 * history, preview, durations, leverage, native close and reverse, and
 * brackets whose legs it links itself. Without `accounts` it declares none of
 * that and behaves exactly as it always has, so the engine refuses the newer
 * operations against it instead of approximating them.
 *
 * It refuses the way a server would, with an error marked `rejected`, when a
 * request names an unknown account, the other ledger, a feature it was told not
 * to support, or margin it does not have. Test hooks can hold, fail or lose the
 * answer to any call, and drop the connection, so the client's handling of each
 * is testable against the same ledger the reference host uses.
 *
 * A dropped connection fails each call the way a client's own transport would:
 * one made while it is down never leaves, and says so with a pre-flight marker,
 * so the engine blocks it and frees its token. One already out when it drops
 * is not applied and fails with a plain error, which is all a client would see
 * of a lost answer too; only the broker's book can settle that one.
 */
import type { Order, OrderSide, Position } from './types';
import type { MarketDepth } from '../feed/types';
import type {
  BracketOrderRequest, BracketReceipt, BrokerRejection, ClosePositionRequest, CommandReceipt, OrderFeed, OrderPreview,
  PlaceRequest, PreflightFailure, ReversePositionRequest, TradeMode,
} from './order-engine';
import type { AccountFeed, AccountHistoryQuery, AccountSnapshot, Execution, OrderHistoryEntry, TradingAccount } from './account';
import { checkTradingFeature, ORDER_DURATIONS, type OrderDuration, type TradingFeature, type TradingFeatures, type TradingFeatureSource } from './features';

/** One simulated account. */
export interface FakeAccountSeed {
  id: string;
  name?: string;
  mode: TradeMode;
  currency?: string;
  /** Opening cash balance. */
  balance: number;
  /** Margin multiplier when an order names none. Default 1. */
  leverage?: number;
  /** Highest leverage an order may request. Default: `leverage`. */
  maxLeverage?: number;
}

/** Each call a test can hold with `latency` or fail with `failNext`. */
export type FakeBrokerOperation =
  | 'place' | 'modify' | 'cancel' | 'preview' | 'close' | 'reverse' | 'bracket'
  | 'accounts' | 'snapshot' | 'positions' | 'executions' | 'history';

/**
 * `reject`: the server refuses (authoritative). `timeout`: the request is lost
 * before it is applied. `lost-response`: it is applied and the answer is lost.
 * The client cannot tell the last two apart, which is the point.
 */
export type FakeBrokerFailure = 'reject' | 'timeout' | 'lost-response';

export interface FakeBrokerOptions {
  /** Enables account ledgers. Omitted keeps the original book-only simulation. */
  accounts?: readonly FakeAccountSeed[];
  /** What the simulated provider declares. Default with accounts: every feature and duration. */
  features?: TradingFeatureSource;
  /** Clock in UTC seconds for snapshots, executions, history and expiry. Default `Date.now() / 1000`. */
  now?: () => number;
  /** Awaited before each call is answered, so a test can hold one account's answer and release it later. */
  latency?: (operation: FakeBrokerOperation, accountId: string | undefined) => void | Promise<void>;
}

/** Who an order belongs to and what it was, beside the order itself. */
export interface FakeOrderInfo {
  accountId?: string;
  clientToken?: string;
  command?: 'close' | 'reverse' | 'bracket';
}

const ALL_FEATURES: TradingFeatures = {
  accounts: true, executions: true, orderHistory: true, preview: true, durations: ORDER_DURATIONS, leverage: true,
  close: true, partialClose: true, reverse: true, brackets: true,
};

/** A refusal the simulated server makes after reading the request. */
function refusal(message: string): Error & BrokerRejection {
  return Object.assign(new Error(`FakeBroker: ${message}`), { rejected: true } as const);
}

/** A call made while the connection is down: it never left, so nothing it asked for can be live. */
function offline(): Error & PreflightFailure {
  return Object.assign(new Error('FakeBroker: disconnected; nothing was sent'), { preflight: true } as const);
}

const article = (mode: TradeMode): string => (mode === 'analyzer' ? 'an' : 'a');
/** Keeps -0 out of reported figures. */
const clean = (n: number): number => (n === 0 ? 0 : n);

interface Holding { netQty: number; avgPrice: number; leverage: number }

interface Ledger {
  seed: FakeAccountSeed;
  cash: number;
  realized: number;
  positions: Map<string, Holding>;
  executions: Execution[];
  subscribers: Set<{ onSnapshot: (s: AccountSnapshot) => void; onError?: ((e: unknown) => void) | undefined }>;
}

interface Meta extends FakeOrderInfo {
  accountId: string;
  order: Order;
  exchange?: string | undefined;
  duration?: OrderDuration;
  expiresAt?: number;
  leverage: number;
  time: number;
}

export class FakeBroker implements OrderFeed, AccountFeed {
  private _orders: Order[] = [];
  private _positions: Position[] = [];
  private readonly _bookListeners: Array<(o: Order[], p: Position[]) => void> = [];
  private readonly _ltpListeners: Array<(symbol: string, ltp: number) => void> = [];
  private readonly _depthListeners: Array<(symbol: string, depth: MarketDepth) => void> = [];
  private readonly _orderListeners: Array<(order: Order, info: FakeOrderInfo) => void> = [];
  private _idCounter = 0;
  private _execCounter = 0;
  /**
   * Test hook: set to a reason to make the next `place()` throw it once, as a
   * plain error. That is an answer lost on its way back, not a refusal: the
   * engine settles the order as ambiguous and keeps its token, since it may
   * have reached the broker. For a broker's refusal, construct with
   * `accounts` and call `failNext('place', 'reject', reason)`.
   */
  public rejectNextPlace: string | null = null;

  private readonly _ledgers = new Map<string, Ledger>();
  private readonly _meta = new Map<string, Meta>();
  private readonly _marks = new Map<string, number>();
  private readonly _accountMode: boolean;
  private readonly _features?: TradingFeatureSource | undefined;
  private readonly _clock: () => number;
  private readonly _latency?: FakeBrokerOptions['latency'];
  private _failures: Array<{ operation: FakeBrokerOperation; failure: FakeBrokerFailure; reason: string | undefined }> = [];
  private _connected = true;
  private _muted = false;

  public constructor(options: FakeBrokerOptions = {}) {
    this._accountMode = options.accounts !== undefined;
    this._features = options.features ?? (this._accountMode ? ALL_FEATURES : undefined);
    this._clock = options.now ?? (() => Date.now() / 1000);
    this._latency = options.latency;
    for (const seed of options.accounts ?? []) {
      this._ledgers.set(seed.id, { seed: { ...seed }, cash: seed.balance, realized: 0, positions: new Map(), executions: [], subscribers: new Set() });
    }
  }

  /** What this simulated provider declares. Undefined without accounts. */
  public get features(): TradingFeatureSource | undefined { return this._features; }

  public onBook(cb: (orders: Order[], positions: Position[]) => void): void {
    this._bookListeners.push(cb);
  }

  public onLtp(cb: (symbol: string, ltp: number) => void): void {
    this._ltpListeners.push(cb);
  }

  /** The order stream: every status change of every order, with the account and client token behind it. */
  public onOrderUpdate(cb: (order: Order, info: FakeOrderInfo) => void): void {
    this._orderListeners.push(cb);
  }

  /** Replace the current book snapshot and notify (simulates a poll / WS update / reconnect). */
  public setBook(orders: Order[], positions: Position[]): void {
    this._orders = orders.map((o) => ({ ...o }));
    this._positions = positions.map((p) => ({ ...p }));
    for (const cb of this._bookListeners) cb(this._orders, this._positions);
  }

  public emitLtp(symbol: string, ltp: number): void {
    this.setMark(symbol, ltp);
    for (const cb of this._ltpListeners) cb(symbol, ltp);
  }

  /** The price market orders fill at and positions are valued at. Pushes fresh figures to holders. */
  public setMark(symbol: string, price: number): void {
    this._marks.set(symbol, price);
    for (const ledger of this._ledgers.values()) if (ledger.positions.has(symbol)) this._push(ledger);
  }

  public onDepth(cb: (symbol: string, depth: MarketDepth) => void): void {
    this._depthListeners.push(cb);
  }

  public emitDepth(symbol: string, depth: MarketDepth): void {
    for (const cb of this._depthListeners) cb(symbol, depth);
  }

  /** Build a deterministic N-level synthetic book around `ltp` (demo/test helper). */
  public static makeDepth(ltp: number, levels: number, tickSize = 0.05): MarketDepth {
    const bids = [];
    const asks = [];
    for (let i = 1; i <= levels; i++) {
      bids.push({ price: ltp - i * tickSize, qty: 100 + ((i * 37) % 900) });
      asks.push({ price: ltp + i * tickSize, qty: 100 + ((i * 53) % 900) });
    }
    return { bids, asks, ltp };
  }

  public orders(): readonly Order[] { return this._orders; }
  public positions(): readonly Position[] { return this._positions; }

  /** An account's open positions, synchronously (test and demo helper). */
  public accountPositions(accountId: string): Position[] {
    const ledger = this._ledgers.get(accountId);
    if (ledger === undefined) return [];
    return [...ledger.positions].map(([symbol, h]) => ({ symbol, netQty: h.netQty, avgPrice: h.avgPrice }));
  }

  // ── test hooks ─────────────────────────────────────────────────────────

  /** Make the next call of `operation` fail as described (test hook). */
  public failNext(operation: FakeBrokerOperation, failure: FakeBrokerFailure, reason?: string): void {
    this._failures.push({ operation, failure, reason });
  }

  /**
   * Drop the connection. Every call fails without applying: one made while it
   * is down as never sent (`isPreflightFailure`), one already out with a plain
   * error. Account streams report the loss.
   */
  public disconnect(): void {
    this._connected = false;
    for (const ledger of this._ledgers.values()) {
      const subscribers = [...ledger.subscribers];
      ledger.subscribers.clear();
      for (const s of subscribers) s.onError?.(new Error('FakeBroker: disconnected'));
    }
  }

  public reconnect(): void { this._connected = true; }

  /** Stop delivering order-stream updates, as a dropped stream would (test hook). */
  public muteOrderUpdates(muted: boolean): void { this._muted = muted; }

  // ── OrderFeed (write path simulation) ──────────────────────────────────

  public async place(req: PlaceRequest & { mode: TradeMode }): Promise<{ orderId: string }> {
    this._online();
    if (this.rejectNextPlace !== null) {
      const reason = this.rejectNextPlace;
      this.rejectNextPlace = null;
      throw new Error(reason);
    }
    if (!this._accountMode) {
      if (req.account !== undefined || req.duration !== undefined || req.expiresAt !== undefined || req.leverage !== undefined) {
        throw refusal('this broker has no accounts, durations or leverage configured');
      }
      const orderId = `B${++this._idCounter}`;
      const order: Order = {
        id: orderId,
        symbol: req.symbol,
        side: req.side,
        type: req.type,
        qty: req.qty,
        filledQty: 0,
        price: req.price ?? 0,
        triggerPrice: req.triggerPrice,
        status: req.type === 'MARKET' ? 'filled' : 'working',
        role: undefined,
      };
      this._orders.push(order);
      this._emit(order);
      this._notify();
      return { orderId };
    }
    const ledger = this._ledgerFor(req.account, req.mode);
    const lose = await this._enter('place', ledger.seed.id);
    const order = this._placeIn(ledger, req);
    this._changed(ledger);
    if (lose) this._lost('place');
    return { orderId: order.id };
  }

  public async modify(orderId: string, patch: { price?: number; triggerPrice?: number; qty?: number }): Promise<void> {
    this._online();
    const meta = this._meta.get(orderId);
    const lose = meta === undefined ? false : await this._enter('modify', meta.accountId);
    const o = this._orders.find((x) => x.id === orderId);
    if (o === undefined) throw new Error('FakeBroker: unknown order');
    if (meta !== undefined) this._live(o);
    if (patch.price !== undefined) o.price = patch.price;
    if (patch.triggerPrice !== undefined) o.triggerPrice = patch.triggerPrice;
    if (patch.qty !== undefined) o.qty = patch.qty;
    if (meta !== undefined) meta.time = this._clock();
    this._emit(o);
    this._notify();
    if (lose) this._lost('modify');
  }

  public async cancel(orderId: string): Promise<void> {
    this._online();
    const meta = this._meta.get(orderId);
    const lose = meta === undefined ? false : await this._enter('cancel', meta.accountId);
    const o = this._orders.find((x) => x.id === orderId);
    if (o !== undefined && meta !== undefined) this._live(o);
    this._orders = this._orders.filter((x) => x.id !== orderId);
    if (o !== undefined && meta !== undefined) {
      this._close(o, 'cancelled');
      // Cancelling an entry that has not filled takes its waiting legs with it.
      for (const leg of this._orders.filter(x => x.parentId === orderId && x.status === 'pending')) {
        this._orders = this._orders.filter(x => x !== leg);
        this._close(leg, 'cancelled');
      }
    } else if (o !== undefined) {
      this._emit({ ...o, status: 'cancelled' });
    }
    this._notify();
    if (lose) this._lost('cancel');
  }

  /** Simulate a fill for an order (test hook). */
  public fill(orderId: string): void {
    const o = this._orders.find((x) => x.id === orderId);
    if (o === undefined) return;
    const meta = this._meta.get(orderId);
    o.filledQty = o.qty;
    o.status = 'filled';
    this._orders = this._orders.filter((x) => x.id !== orderId);
    if (meta !== undefined) {
      const ledger = this._ledgers.get(meta.accountId)!;
      const price = o.type === 'SL-M' ? (o.triggerPrice ?? o.price) : o.price;
      this._execute(ledger, meta, o.side, o.qty, price);
      meta.time = this._clock();
      this._emit(o);
      // The provider links a bracket's legs itself: an entry fill starts them,
      // and a leg fill cancels its sibling.
      for (const other of this._orders.filter(x => x.parentId !== undefined && (x.parentId === o.id || x.parentId === o.parentId))) {
        if (other.parentId === o.id && other.status === 'pending') {
          other.status = 'working';
          this._emit(other);
        } else if (o.parentId !== undefined && other.parentId === o.parentId && other.id !== o.id) {
          this._orders = this._orders.filter(x => x !== other);
          this._close(other, 'cancelled');
        }
      }
      this._changed(ledger);
      return;
    }
    this._emit(o);
    this._notify();
  }

  public async previewOrder(req: PlaceRequest & { mode: TradeMode }): Promise<OrderPreview> {
    this._online();
    if (!this._accountMode) throw new Error('FakeBroker: order preview needs accounts');
    this._require('preview', req);
    const ledger = this._ledgerFor(req.account, req.mode);
    await this._enter('preview', ledger.seed.id);
    this._sweep();
    const snapshot = this._snapshot(ledger);
    const price = this._entryPrice(req);
    const base = { accountId: ledger.seed.id, asOf: this._clock(), ...(ledger.seed.currency ? { currency: ledger.seed.currency } : {}) };
    if (price === undefined) return { ...base, rejectReason: `no price for ${req.symbol}` };
    const leverage = req.leverage ?? ledger.seed.leverage ?? 1;
    const margin = this._opening(ledger, req.symbol, req.side, req.qty) * price / leverage;
    const available = snapshot.marginAvailable ?? 0;
    let rejectReason: string | undefined;
    try { this._schema(ledger, req); } catch (error) { rejectReason = String((error as Error).message).replace(/^FakeBroker: /, ''); }
    if (rejectReason === undefined && margin > available) rejectReason = `Insufficient margin: ${margin.toFixed(2)} required, ${available.toFixed(2)} available`;
    return {
      ...base, estimatedPrice: price, estimatedValue: req.qty * price, marginRequired: margin,
      marginAvailableAfter: available - margin, ...(rejectReason === undefined ? {} : { rejectReason }),
    };
  }

  public async closePosition(req: ClosePositionRequest & { mode: TradeMode }): Promise<CommandReceipt> {
    this._online();
    if (!this._accountMode) throw refusal('closing a position needs accounts');
    this._require(req.qty === undefined ? 'close' : 'partialClose', req);
    const ledger = this._ledgerFor(req.account, req.mode);
    const lose = await this._enter('close', ledger.seed.id);
    this._sweep();
    const holding = this._holding(ledger, req.symbol);
    const open = Math.abs(holding.netQty);
    const qty = req.qty ?? open;
    if (!(qty > 0) || qty > open) throw refusal(`close quantity ${qty} exceeds the open position of ${open}`);
    const order = this._command(ledger, req, 'close', holding.netQty > 0 ? 'SELL' : 'BUY', qty, holding.leverage);
    if (lose) this._lost('close');
    return { commandId: order.id, orderIds: [order.id] };
  }

  public async reversePosition(req: ReversePositionRequest & { mode: TradeMode }): Promise<CommandReceipt> {
    this._online();
    if (!this._accountMode) throw refusal('reversing a position needs accounts');
    this._require('reverse', req);
    const ledger = this._ledgerFor(req.account, req.mode);
    const lose = await this._enter('reverse', ledger.seed.id);
    this._sweep();
    const holding = this._holding(ledger, req.symbol);
    const side: OrderSide = holding.netQty > 0 ? 'SELL' : 'BUY';
    const mark = this._mark(req.symbol);
    const margin = Math.abs(holding.netQty) * mark / holding.leverage;
    const available = (this._snapshot(ledger).marginAvailable ?? 0) + Math.abs(holding.netQty) * holding.avgPrice / holding.leverage;
    if (margin > available) throw refusal(`Insufficient margin: ${margin.toFixed(2)} required, ${available.toFixed(2)} available`);
    const order = this._command(ledger, req, 'reverse', side, 2 * Math.abs(holding.netQty), holding.leverage);
    if (lose) this._lost('reverse');
    return { commandId: order.id, orderIds: [order.id] };
  }

  public async placeBracket(req: BracketOrderRequest & { mode: TradeMode; legClientTokens?: { stopLoss: string; takeProfit: string } }): Promise<BracketReceipt> {
    this._online();
    if (!this._accountMode) throw refusal('bracket placement needs accounts');
    this._require('brackets', req);
    const ledger = this._ledgerFor(req.account, req.mode);
    const lose = await this._enter('bracket', ledger.seed.id);
    this._sweep();
    const entry = this._entryPrice(req);
    if (entry === undefined) throw refusal(`no price for ${req.symbol}`);
    const [low, high] = req.side === 'BUY' ? [req.stopLoss, req.takeProfit] : [req.takeProfit, req.stopLoss];
    if (!(low < entry && entry < high)) throw refusal('the stop and target are on the wrong side of the entry');
    const parent = this._placeIn(ledger, req, 'bracket');
    const exit: OrderSide = req.side === 'BUY' ? 'SELL' : 'BUY';
    const waiting = parent.status !== 'filled';
    const legIds: string[] = [];
    for (const role of ['sl', 'tp'] as const) {
      const id = `B${++this._idCounter}`;
      const order: Order = {
        id, symbol: req.symbol, side: exit, type: role === 'sl' ? 'SL-M' : 'LIMIT', qty: req.qty, filledQty: 0,
        price: role === 'sl' ? 0 : req.takeProfit, ...(role === 'sl' ? { triggerPrice: req.stopLoss } : {}),
        status: waiting ? 'pending' : 'working', parentId: parent.id, role,
      };
      // Each leg echoes the token the client gave it, so a lost answer can be reconciled leg by leg.
      const clientToken = req.legClientTokens?.[role === 'sl' ? 'stopLoss' : 'takeProfit'];
      this._meta.set(id, {
        accountId: ledger.seed.id, order, exchange: req.exchange, command: 'bracket', leverage: this._meta.get(parent.id)!.leverage, time: this._clock(),
        ...(clientToken === undefined ? {} : { clientToken }),
      });
      this._orders.push(order);
      this._emit(order);
      legIds.push(id);
    }
    this._changed(ledger);
    if (lose) this._lost('bracket');
    // The loop above pushed one id per leg, the stop's first.
    return { orderId: parent.id, stopLossId: legIds[0]!, takeProfitId: legIds[1]! };
  }

  // ── AccountFeed (read path simulation) ─────────────────────────────────

  public async listAccounts(_signal?: AbortSignal): Promise<readonly TradingAccount[]> {
    this._online();
    if (!this._accountMode) return [];
    await this._enter('accounts', undefined);
    return [...this._ledgers.values()].map(({ seed }) => ({
      id: seed.id, mode: seed.mode, ...(seed.name ? { name: seed.name } : {}), ...(seed.currency ? { currency: seed.currency } : {}),
    }));
  }

  public async getAccountSnapshot(accountId: string, _signal?: AbortSignal): Promise<AccountSnapshot> {
    this._online();
    const ledger = this._account(accountId);
    await this._enter('snapshot', accountId);
    this._sweep();
    return this._snapshot(ledger);
  }

  public subscribeAccount(accountId: string, onSnapshot: (s: AccountSnapshot) => void, onError?: (e: unknown) => void): () => void {
    this._online();
    const ledger = this._account(accountId);
    const entry = { onSnapshot, onError };
    ledger.subscribers.add(entry);
    return () => { ledger.subscribers.delete(entry); };
  }

  public async getAccountPositions(accountId: string, _signal?: AbortSignal): Promise<readonly Position[]> {
    this._online();
    this._account(accountId);
    await this._enter('positions', accountId);
    this._sweep();
    return this.accountPositions(accountId).map(position => ({ ...position, accountId }));
  }

  public async getExecutions(query: AccountHistoryQuery, _signal?: AbortSignal): Promise<readonly Execution[]> {
    this._online();
    const ledger = this._account(query.accountId);
    await this._enter('executions', query.accountId);
    return this._window([...ledger.executions].reverse(), row => row.symbol, row => row.time, query).map(row => ({ ...row }));
  }

  public async getOrderHistory(query: AccountHistoryQuery, _signal?: AbortSignal): Promise<readonly OrderHistoryEntry[]> {
    this._online();
    this._account(query.accountId);
    await this._enter('history', query.accountId);
    this._sweep();
    const rows = [...this._meta.values()].filter(meta => meta.accountId === query.accountId)
      .sort((a, b) => b.time - a.time || Number(b.order.id.slice(1)) - Number(a.order.id.slice(1)));
    return this._window(rows, meta => meta.order.symbol, meta => meta.time, query).map(meta => ({
      accountId: meta.accountId, order: { ...meta.order }, time: meta.time,
      ...(meta.clientToken === undefined ? {} : { clientToken: meta.clientToken }),
      ...(meta.duration === undefined ? {} : { duration: meta.duration }),
      ...(meta.expiresAt === undefined ? {} : { expiresAt: meta.expiresAt }),
      ...(meta.command === undefined ? {} : { command: meta.command }),
    }));
  }

  // ── the simulated server ───────────────────────────────────────────────

  private _notify(): void {
    for (const cb of this._bookListeners) cb(this._orders, this._positions);
  }

  private _emit(order: Order): void {
    if (this._muted) return;
    const meta = this._meta.get(order.id);
    const info: FakeOrderInfo = meta === undefined ? {} : {
      accountId: meta.accountId,
      ...(meta.clientToken === undefined ? {} : { clientToken: meta.clientToken }),
      ...(meta.command === undefined ? {} : { command: meta.command }),
    };
    for (const cb of [...this._orderListeners]) cb({ ...order }, info);
  }

  /** Book listeners and the account's own stream both learn of a ledger change. */
  private _changed(ledger: Ledger): void {
    this._notify();
    this._push(ledger);
  }

  private _push(ledger: Ledger): void {
    if (ledger.subscribers.size === 0) return;
    const snapshot = this._snapshot(ledger);
    for (const s of [...ledger.subscribers]) s.onSnapshot({ ...snapshot });
  }

  /** A call made while the connection is down never leaves the client. */
  private _online(): void {
    if (!this._connected) throw offline();
  }

  /** Latency, then the connection, then any queued failure. True: apply, then lose the answer. */
  private async _enter(operation: FakeBrokerOperation, accountId: string | undefined): Promise<boolean> {
    if (this._latency !== undefined) await this._latency(operation, accountId);
    // Out before the drop: not applied, and the client only sees the answer go missing.
    if (!this._connected) throw new Error('FakeBroker: the connection dropped before the answer');
    const i = this._failures.findIndex(f => f.operation === operation);
    const failure = this._failures[i];
    if (failure === undefined) return false;
    this._failures.splice(i, 1);
    if (failure.failure === 'reject') throw refusal(failure.reason ?? `${operation} refused`);
    if (failure.failure === 'timeout') throw new Error(`FakeBroker: ${failure.reason ?? `${operation} timed out`}`);
    return true;
  }

  /**
   * A server refuses to change an order that is already over. Market and
   * command orders stay in the book as filled, so without this a late cancel
   * rewrote a fill as cancelled while its execution and position stayed.
   */
  private _live(order: Order): void {
    if (order.status !== 'working' && order.status !== 'pending' && order.status !== 'partial') {
      throw refusal(`order ${order.id} is already ${order.status}`);
    }
  }

  private _lost(operation: FakeBrokerOperation): never {
    throw new Error(`FakeBroker: the ${operation} answer was lost`);
  }

  private _require(feature: TradingFeature, req: { symbol?: string; account?: string; mode?: TradeMode }): void {
    const support = checkTradingFeature(this._features, { feature, symbol: req.symbol, account: req.account, mode: req.mode });
    if (!support.supported) throw refusal(support.reason);
  }

  private _account(accountId: string): Ledger {
    if (!this._accountMode) throw new Error('FakeBroker: no accounts are configured');
    const ledger = this._ledgers.get(accountId);
    if (ledger === undefined) throw refusal(`unknown account ${accountId}`);
    return ledger;
  }

  /** The named account, or the first of the order's mode; either must belong to that mode. */
  private _ledgerFor(accountId: string | undefined, mode: TradeMode | undefined): Ledger {
    const want = mode ?? 'live';
    if (accountId !== undefined) this._require('accounts', { account: accountId, mode: want });
    const ledger = accountId === undefined
      ? [...this._ledgers.values()].find(l => l.seed.mode === want)
      : this._ledgers.get(accountId);
    if (ledger === undefined) throw refusal(accountId === undefined ? `no ${want} account is configured` : `unknown account ${accountId}`);
    if (ledger.seed.mode !== want) {
      throw refusal(`${ledger.seed.id} is ${article(ledger.seed.mode)} ${ledger.seed.mode} account and cannot take ${article(want)} ${want} order`);
    }
    return ledger;
  }

  private _mark(symbol: string): number {
    const mark = this._marks.get(symbol);
    if (mark === undefined) throw refusal(`no price for ${symbol}`);
    return mark;
  }

  private _holding(ledger: Ledger, symbol: string): Holding {
    const holding = ledger.positions.get(symbol);
    if (holding === undefined || holding.netQty === 0) throw refusal(`no open position in ${symbol}`);
    return holding;
  }

  /** What an order would trade at: the mark for a market order, else its own level. */
  private _entryPrice(req: PlaceRequest): number | undefined {
    if (req.type === 'MARKET') return this._marks.get(req.symbol);
    const level = req.type === 'SL-M' ? req.triggerPrice : req.price;
    return level !== undefined && Number.isFinite(level) ? level : undefined;
  }

  /** The part of an order that adds exposure; reducing an open position needs no new margin. */
  private _opening(ledger: Ledger, symbol: string, side: OrderSide, qty: number): number {
    const net = ledger.positions.get(symbol)?.netQty ?? 0;
    const after = net + (side === 'BUY' ? qty : -qty);
    return Math.max(0, Math.abs(after) - Math.abs(net));
  }

  /** Durations, expiry and leverage as this provider accepts them. Throws a refusal. */
  private _schema(ledger: Ledger, req: PlaceRequest & { mode: TradeMode }): number {
    if (req.duration !== undefined) {
      const support = checkTradingFeature(this._features, { feature: 'duration', duration: req.duration, mode: req.mode });
      if (!support.supported) throw refusal(support.reason);
    }
    if ((req.duration === 'GTD' || req.expiresAt !== undefined)
      && (req.duration !== 'GTD' || req.expiresAt === undefined || !(req.expiresAt > this._clock()))) {
      throw refusal('a GTD order needs an expiry in the future, and only a GTD order takes one');
    }
    const leverage = req.leverage ?? ledger.seed.leverage ?? 1;
    if (req.leverage !== undefined) {
      this._require('leverage', req);
      const max = ledger.seed.maxLeverage ?? ledger.seed.leverage ?? 1;
      if (!(leverage > 0) || leverage > max) throw refusal(`leverage ${leverage} is above the account limit of ${max}`);
    }
    return leverage;
  }

  /** Accept an order into an account: checks, margin, then fill, rest or cancel by type and duration. */
  private _placeIn(ledger: Ledger, req: PlaceRequest & { mode: TradeMode }, command?: 'bracket'): Order {
    this._sweep();
    const leverage = this._schema(ledger, req);
    const price = this._entryPrice(req);
    if (price === undefined) throw refusal(req.type === 'MARKET' ? `no price for ${req.symbol}` : 'the order has no price');
    const margin = this._opening(ledger, req.symbol, req.side, req.qty) * price / leverage;
    const available = this._snapshot(ledger).marginAvailable ?? 0;
    if (margin > available + 1e-9) throw refusal(`Insufficient margin: ${margin.toFixed(2)} required, ${available.toFixed(2)} available`);
    const id = `B${++this._idCounter}`;
    const order: Order = {
      id, symbol: req.symbol, side: req.side, type: req.type, qty: req.qty, filledQty: 0,
      price: req.price ?? 0, triggerPrice: req.triggerPrice, status: 'working', role: undefined,
    };
    const meta: Meta = {
      accountId: ledger.seed.id, order, exchange: req.exchange, leverage, time: this._clock(),
      ...(req.clientToken === undefined ? {} : { clientToken: req.clientToken }),
      ...(req.duration === undefined ? {} : { duration: req.duration }),
      ...(req.expiresAt === undefined ? {} : { expiresAt: req.expiresAt }),
      ...(command === undefined ? {} : { command }),
    };
    this._meta.set(id, meta);
    const immediate = req.duration === 'IOC' || req.duration === 'FOK';
    const mark = this._marks.get(req.symbol);
    const marketable = req.type === 'MARKET'
      || (immediate && req.type === 'LIMIT' && mark !== undefined && (req.side === 'BUY' ? req.price! >= mark : req.price! <= mark));
    if (marketable) {
      const fillPrice = mark!;
      order.price = fillPrice;
      order.filledQty = req.qty;
      order.status = 'filled';
      this._execute(ledger, meta, req.side, req.qty, fillPrice);
      this._orders.push(order);
    } else if (immediate) {
      // Immediate-or-cancel and fill-or-kill never rest: what cannot trade now is cancelled now.
      order.status = 'cancelled';
    } else {
      this._orders.push(order);
    }
    this._emit(order);
    return order;
  }

  /** A native position command, booked as one order the provider marks as that command. */
  private _command(ledger: Ledger, req: PositionCommandLike, command: 'close' | 'reverse', side: OrderSide, qty: number, leverage: number): Order {
    const mark = this._mark(req.symbol);
    const id = `B${++this._idCounter}`;
    const order: Order = { id, symbol: req.symbol, side, type: 'MARKET', qty, filledQty: qty, price: mark, status: 'filled', role: undefined };
    const meta: Meta = {
      accountId: ledger.seed.id, order, exchange: req.exchange, leverage, time: this._clock(), command,
      ...(req.clientToken === undefined ? {} : { clientToken: req.clientToken }),
    };
    this._meta.set(id, meta);
    this._execute(ledger, meta, side, qty, mark);
    this._orders.push(order);
    this._emit(order);
    this._changed(ledger);
    return order;
  }

  /** Book a fill into the account: average in, realize out, flip at the fill price. */
  private _execute(ledger: Ledger, meta: Meta, side: OrderSide, qty: number, price: number): void {
    const symbol = meta.order.symbol;
    const held = ledger.positions.get(symbol) ?? { netQty: 0, avgPrice: 0, leverage: meta.leverage };
    const signed = side === 'BUY' ? qty : -qty;
    let { netQty, avgPrice, leverage } = held;
    if (netQty === 0 || Math.sign(netQty) === Math.sign(signed)) {
      avgPrice = (avgPrice * Math.abs(netQty) + price * qty) / (Math.abs(netQty) + qty);
      if (netQty === 0) leverage = meta.leverage;
      netQty += signed;
    } else {
      const closing = Math.min(qty, Math.abs(netQty));
      const pnl = (price - avgPrice) * closing * Math.sign(netQty);
      ledger.realized += pnl;
      ledger.cash += pnl;
      netQty += signed;
      if (qty > closing) { avgPrice = price; leverage = meta.leverage; }
    }
    if (netQty === 0) ledger.positions.delete(symbol);
    else ledger.positions.set(symbol, { netQty, avgPrice, leverage });
    ledger.executions.push({
      id: `E${++this._execCounter}`, accountId: ledger.seed.id, orderId: meta.order.id, symbol,
      ...(meta.exchange === undefined ? {} : { exchange: meta.exchange }), side, qty, price, time: this._clock(),
    });
  }

  private _snapshot(ledger: Ledger): AccountSnapshot {
    let unrealized = 0;
    let used = 0;
    for (const [symbol, h] of ledger.positions) {
      unrealized += ((this._marks.get(symbol) ?? h.avgPrice) - h.avgPrice) * h.netQty;
      used += Math.abs(h.netQty) * h.avgPrice / h.leverage;
    }
    const equity = ledger.cash + unrealized;
    return {
      accountId: ledger.seed.id, mode: ledger.seed.mode, asOf: this._clock(),
      ...(ledger.seed.currency ? { currency: ledger.seed.currency } : {}),
      balance: clean(ledger.cash), equity: clean(equity), marginUsed: clean(used), marginAvailable: clean(equity - used),
      unrealizedPnl: clean(unrealized), realizedPnl: clean(ledger.realized), leverage: ledger.seed.leverage ?? 1,
    };
  }

  /** Record a final state for an order already out of the book. */
  private _close(order: Order, status: 'cancelled'): void {
    order.status = status;
    const meta = this._meta.get(order.id);
    if (meta !== undefined) meta.time = this._clock();
    this._emit(order);
  }

  /** Lapse GTD orders whose expiry has passed. */
  private _sweep(): void {
    const now = this._clock();
    const touched = new Set<Ledger>();
    for (const order of [...this._orders]) {
      const meta = this._meta.get(order.id);
      if (meta?.expiresAt === undefined || meta.expiresAt > now || (order.status !== 'working' && order.status !== 'pending')) continue;
      this._orders = this._orders.filter(x => x !== order);
      this._close(order, 'cancelled');
      touched.add(this._ledgers.get(meta.accountId)!);
    }
    for (const ledger of touched) this._changed(ledger);
  }

  private _window<T>(rows: readonly T[], symbol: (row: T) => string, time: (row: T) => number, query: AccountHistoryQuery): T[] {
    const out = rows.filter(row => (query.symbol === undefined || symbol(row) === query.symbol)
      && (query.from === undefined || time(row) >= query.from) && (query.to === undefined || time(row) <= query.to));
    return query.limit === undefined ? out : out.slice(0, Math.max(0, query.limit));
  }
}

type PositionCommandLike = { symbol: string; exchange?: string; clientToken?: string };
