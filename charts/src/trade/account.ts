/**
 * Read-only account state: which accounts a provider offers, the selected
 * one's balances and margin, its positions, executions and order history.
 *
 * Nothing in this file writes. Selecting an account changes what the host
 * reads and which account a later order names; it never sends, re-routes or
 * cancels an order. Three hazards shape the rest:
 *
 * - **A late answer for the old account.** Switching from A to B while A's
 *   snapshot is in flight must not paint A's equity under B's name. Every
 *   selection bumps a generation, aborts the old request and unsubscribes the
 *   old stream, and every answer is checked against the generation, the
 *   account id and the reading's own time before it is shown.
 * - **The other ledger.** An analyzer (sandbox) view must never show a live
 *   balance, or the reverse. Accounts of the other mode are not listed, and a
 *   snapshot that names the other mode is refused, not displayed.
 * - **A figure nobody could read.** A non-finite balance is reported as an
 *   unreadable snapshot. Zero would be a confident, wrong number.
 */
import type { Order, OrderSide, Position } from './types';
import type { TradeMode } from './order-engine';
import { checkTradingFeature, type OrderDuration, type TradingFeature, type TradingFeatureSource } from './features';
import { errorText, nonEmpty } from './text';

export interface TradingAccount {
  readonly id: string;
  readonly name?: string;
  /** The ledger the account belongs to. */
  readonly mode: TradeMode;
  readonly currency?: string;
}

/** One reading of an account. Money fields are in `currency`; absent means the provider did not say. */
export interface AccountSnapshot {
  readonly accountId: string;
  readonly mode: TradeMode;
  /** When the provider took the reading, UTC seconds (fractions allowed). Orders readings. */
  readonly asOf: number;
  readonly currency?: string;
  readonly balance?: number;
  readonly equity?: number;
  readonly marginUsed?: number;
  readonly marginAvailable?: number;
  readonly unrealizedPnl?: number;
  readonly realizedPnl?: number;
  readonly leverage?: number;
}

export interface Execution {
  readonly id: string;
  readonly accountId: string;
  readonly orderId: string;
  readonly symbol: string;
  readonly exchange?: string;
  readonly side: OrderSide;
  readonly qty: number;
  readonly price: number;
  /** UTC seconds, the unit bar times use, so a fill can be placed on its bar. */
  readonly time: number;
}

export interface OrderHistoryEntry {
  readonly accountId: string;
  /** The order as the provider last reported it. */
  readonly order: Order;
  /** Last update, UTC seconds. */
  readonly time: number;
  /** The client token the provider echoes, which is how an ambiguous write is found again. */
  readonly clientToken?: string;
  readonly duration?: OrderDuration;
  /** UTC seconds. */
  readonly expiresAt?: number;
  /** Set when the order is a provider-native command rather than a plain order. */
  readonly command?: 'close' | 'reverse' | 'bracket';
}

export interface AccountHistoryQuery {
  readonly accountId: string;
  readonly symbol?: string;
  /** Inclusive bounds, UTC seconds. */
  readonly from?: number;
  readonly to?: number;
  readonly limit?: number;
}

/**
 * The read half of a broker. Every member is optional because providers vary;
 * `features` says which are real, and a method without a declaration is unused.
 */
export interface AccountFeed {
  readonly features?: TradingFeatureSource | undefined;
  listAccounts?(signal: AbortSignal): Promise<readonly TradingAccount[]>;
  getAccountSnapshot?(accountId: string, signal: AbortSignal): Promise<AccountSnapshot>;
  /** Push readings as they change. `onError` reports a dead stream; the returned function stops it. */
  subscribeAccount?(accountId: string, onSnapshot: (snapshot: AccountSnapshot) => void, onError?: (error: unknown) => void): () => void;
  getAccountPositions?(accountId: string, signal: AbortSignal): Promise<readonly Position[]>;
  getExecutions?(query: AccountHistoryQuery, signal: AbortSignal): Promise<readonly Execution[]>;
  getOrderHistory?(query: AccountHistoryQuery, signal: AbortSignal): Promise<readonly OrderHistoryEntry[]>;
}

/**
 * `unsupported`: the provider or host declares no account data (see `reason`).
 * `idle`: supported, nothing loaded yet. `stale`: the last figures are kept but
 * may be out of date. `error`: nothing trustworthy to show.
 */
export type AccountStatus = 'unsupported' | 'idle' | 'loading' | 'ready' | 'stale' | 'error';

export interface AccountState {
  readonly status: AccountStatus;
  readonly reason?: string;
  readonly mode: TradeMode;
  readonly accounts: readonly TradingAccount[];
  readonly selectedId: string | null;
  readonly snapshot: AccountSnapshot | null;
  /** Bumped by every selection, refresh and disconnect, so a reader can tell epochs apart. */
  readonly generation: number;
}

export type AccountSelectResult =
  | { ok: true; snapshot: AccountSnapshot }
  | { ok: false; reason: string; cancelled?: boolean };

export type AccountReadResult<T> =
  | { ok: true; accountId: string; rows: readonly T[]; dropped: number }
  | { ok: false; reason: string; cancelled?: boolean; unsupported?: boolean };

/** What a host control needs to show and switch accounts. `AccountManager` implements it. */
export interface AccountStateSource {
  getState(): AccountState;
  subscribe(listener: (state: AccountState) => void): () => void;
  select(accountId: string): Promise<AccountSelectResult>;
}

export interface AccountManagerOptions {
  feed: AccountFeed;
  /** The ledger this manager shows. Accounts of the other mode are never listed. Default `live`. */
  mode?: TradeMode;
  /** Host restrictions combined with the feed's declaration; either can refuse. */
  features?: TradingFeatureSource;
  /** Selected after the first listing when the provider offers it. Default: the first account. */
  initialAccount?: string;
}

/** A change to the state. `reason: undefined` clears the reason, which the state then omits. */
type AccountPatch = Partial<Omit<AccountState, 'reason'>> & { readonly reason?: string | undefined };

const CANCELLED = 'The account changed before the read finished';
const DISCONNECTED = 'The connection dropped; account figures may be out of date';
const MONEY_FIELDS = ['balance', 'equity', 'marginUsed', 'marginAvailable', 'unrealizedPnl', 'realizedPnl', 'leverage'] as const;

const isMode = (value: unknown): value is TradeMode => value === 'live' || value === 'analyzer';

function readAccount(raw: unknown): TradingAccount | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (!nonEmpty(r.id) || !isMode(r.mode)) return null;
  return {
    id: r.id, mode: r.mode,
    ...(nonEmpty(r.name) ? { name: r.name } : {}),
    ...(nonEmpty(r.currency) ? { currency: r.currency } : {}),
  };
}

/** A readable snapshot, or the name of the first field that is not. */
function readSnapshot(raw: unknown): AccountSnapshot | string {
  if (typeof raw !== 'object' || raw === null) return 'snapshot';
  const r = raw as Record<string, unknown>;
  if (!nonEmpty(r.accountId)) return 'accountId';
  if (!isMode(r.mode)) return 'mode';
  if (typeof r.asOf !== 'number' || !Number.isFinite(r.asOf)) return 'asOf';
  const out: Record<string, unknown> = { accountId: r.accountId, mode: r.mode, asOf: r.asOf };
  if (nonEmpty(r.currency)) out.currency = r.currency;
  for (const key of MONEY_FIELDS) {
    const value = r[key];
    if (value === undefined) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) return key;
    out[key] = value;
  }
  return out as unknown as AccountSnapshot;
}

function readExecution(raw: unknown, accountId: string): Execution | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
  if (r.accountId !== accountId || !nonEmpty(r.id) || !nonEmpty(r.orderId) || !nonEmpty(r.symbol)) return null;
  if ((r.side !== 'BUY' && r.side !== 'SELL') || !finite(r.qty) || r.qty <= 0 || !finite(r.price) || !finite(r.time)) return null;
  return raw as Execution;
}

function readHistory(raw: unknown, accountId: string): OrderHistoryEntry | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const order = r.order as Record<string, unknown> | undefined;
  if (r.accountId !== accountId || typeof r.time !== 'number' || !Number.isFinite(r.time)) return null;
  if (typeof order !== 'object' || order === null || !nonEmpty(order.id) || !nonEmpty(order.symbol)) return null;
  return raw as OrderHistoryEntry;
}

export class AccountManager implements AccountStateSource {
  private readonly _feed: AccountFeed;
  private readonly _mode: TradeMode;
  private readonly _hostFeatures?: TradingFeatureSource | undefined;
  private readonly _initial?: string | undefined;
  private readonly _listeners = new Set<(state: AccountState) => void>();
  /** Aborted together whenever the generation moves on. */
  private _aborts = new Set<AbortController>();
  private _unsubscribe: (() => void) | null = null;
  private _state: AccountState;
  private _destroyed = false;

  public constructor(options: AccountManagerOptions) {
    this._feed = options.feed;
    this._mode = options.mode ?? 'live';
    this._hostFeatures = options.features;
    this._initial = options.initialAccount;
    const support = this._support('accounts');
    this._state = {
      status: support === null ? 'idle' : 'unsupported',
      ...(support === null ? {} : { reason: support }),
      mode: this._mode, accounts: [], selectedId: null, snapshot: null, generation: 0,
    };
  }

  public get mode(): TradeMode { return this._mode; }
  public getState(): AccountState { return this._state; }
  public selectedAccount(): string | null { return this._state.selectedId; }

  public subscribe(listener: (state: AccountState) => void): () => void {
    this._listeners.add(listener);
    return () => { this._listeners.delete(listener); };
  }

  /** Null when the feature is usable, otherwise why not. */
  private _support(feature: TradingFeature): string | null {
    const request = { feature, mode: this._mode, account: this._state?.selectedId ?? undefined };
    const feed = checkTradingFeature(this._feed.features, request);
    if (!feed.supported) return feed.reason;
    if (this._hostFeatures !== undefined) {
      const host = checkTradingFeature(this._hostFeatures, request);
      if (!host.supported) return host.reason;
    }
    const f = this._feed;
    const implemented = feature === 'accounts' ? f.listAccounts !== undefined && f.getAccountSnapshot !== undefined
      : feature === 'executions' ? f.getExecutions !== undefined
        : feature === 'orderHistory' ? f.getOrderHistory !== undefined : true;
    return implemented ? null : `${feature === 'accounts' ? 'Account data' : feature === 'executions' ? 'Execution history' : 'Order history'} is not implemented by this feed`;
  }

  private _set(patch: AccountPatch): void {
    const merged = { ...this._state, ...patch };
    if (patch.reason === undefined && 'reason' in patch) delete (merged as { reason?: string }).reason;
    // Only a patch brings `reason: undefined`, and the line above removed it.
    const next = merged as AccountState;
    this._state = next;
    for (const listener of [...this._listeners]) {
      try { listener(next); } catch { /* A host listener's bug must not stop the others or the manager. */ }
    }
  }

  /** Move to a new epoch: abort everything in flight and drop the stream. */
  private _advance(): number {
    for (const abort of this._aborts) abort.abort();
    this._aborts = new Set();
    this._unsubscribe?.();
    this._unsubscribe = null;
    return this._state.generation + 1;
  }

  private _controller(): AbortController {
    const abort = new AbortController();
    this._aborts.add(abort);
    return abort;
  }

  /** List accounts, keep or choose a selection, and load its snapshot. */
  public async refresh(): Promise<AccountSelectResult> {
    if (this._destroyed) return { ok: false, reason: 'The account manager was destroyed' };
    const support = this._support('accounts');
    if (support !== null) {
      this._advance();
      this._set({ status: 'unsupported', reason: support, accounts: [], selectedId: null, snapshot: null, generation: this._state.generation + 1 });
      return { ok: false, reason: support };
    }
    const generation = this._advance();
    const previous = this._state.status;
    const keep = previous === 'stale' || previous === 'ready' ? this._state.snapshot : null;
    // Figures already on screen stay there, in the state they were in, until
    // the fresh answer arrives: a refresh is not a reason to call them stale.
    this._set({ status: keep === null ? 'loading' : previous, generation, ...(keep === null ? { reason: undefined } : {}) });
    const abort = this._controller();
    let listed: readonly TradingAccount[];
    try {
      const raw = await this._feed.listAccounts!(abort.signal);
      if (this._state.generation !== generation || this._destroyed) return { ok: false, reason: CANCELLED, cancelled: true };
      listed = (Array.isArray(raw) ? raw : []).map(readAccount).filter((a): a is TradingAccount => a !== null && a.mode === this._mode);
    } catch (error) {
      if (this._state.generation !== generation || this._destroyed) return { ok: false, reason: CANCELLED, cancelled: true };
      const reason = `Could not list accounts: ${errorText(error)}`;
      this._set(keep === null ? { status: 'error', reason } : { status: 'stale', reason: DISCONNECTED });
      return { ok: false, reason };
    } finally {
      this._aborts.delete(abort);
    }
    const current = this._state.selectedId;
    const target = listed.find(a => a.id === current) ?? listed.find(a => a.id === this._initial) ?? listed[0];
    if (target === undefined) {
      const reason = `The provider listed no ${this._mode} account`;
      this._set({ status: 'error', reason, accounts: [], selectedId: null, snapshot: null });
      return { ok: false, reason };
    }
    this._set({ accounts: listed });
    return this._load(target.id, generation, keep !== null && keep.accountId === target.id ? keep : null);
  }

  /** Select an account and load its snapshot. A later selection cancels this one. */
  public async select(accountId: string): Promise<AccountSelectResult> {
    if (this._destroyed) return { ok: false, reason: 'The account manager was destroyed' };
    const support = this._support('accounts');
    if (support !== null) return { ok: false, reason: support };
    if (!this._state.accounts.some(account => account.id === accountId)) {
      return { ok: false, reason: `Account ${accountId} is not available in ${this._mode} mode` };
    }
    return this._load(accountId, this._advance(), null);
  }

  private async _load(accountId: string, generation: number, keep: AccountSnapshot | null): Promise<AccountSelectResult> {
    // Another account's figures must never sit under this account's name, so
    // a switch clears them; a refresh of the same account keeps them, stale.
    this._set({ selectedId: accountId, snapshot: keep, generation, status: keep === null ? 'loading' : this._state.status });
    const abort = this._controller();
    let snapshot: AccountSnapshot;
    try {
      const raw = await this._feed.getAccountSnapshot!(accountId, abort.signal);
      if (this._state.generation !== generation || this._destroyed) return { ok: false, reason: CANCELLED, cancelled: true };
      const read = this._accept(raw, accountId);
      if (typeof read === 'string') {
        this._set({ status: 'error', reason: read, snapshot: null });
        return { ok: false, reason: read };
      }
      snapshot = read;
    } catch (error) {
      if (this._state.generation !== generation || this._destroyed) return { ok: false, reason: CANCELLED, cancelled: true };
      const reason = `Could not load account ${accountId}: ${errorText(error)}`;
      this._set(keep === null ? { status: 'error', reason } : { status: 'stale', reason: DISCONNECTED });
      return { ok: false, reason };
    } finally {
      this._aborts.delete(abort);
    }
    this._set({ status: 'ready', reason: undefined, snapshot });
    this._stream(accountId, generation);
    return { ok: true, snapshot };
  }

  /** Validate a reading for `accountId`; a string explains the refusal. */
  private _accept(raw: unknown, accountId: string): AccountSnapshot | string {
    const read = readSnapshot(raw);
    if (typeof read === 'string') return `The account snapshot could not be read: ${read}`;
    if (read.accountId !== accountId) return `The provider answered for account ${read.accountId}, not ${accountId}`;
    if (read.mode !== this._mode) return `The provider returned figures from the ${read.mode} ledger for this ${this._mode} view`;
    return read;
  }

  private _stream(accountId: string, generation: number): void {
    const subscribe = this._feed.subscribeAccount;
    if (subscribe === undefined) return;
    const live = (): boolean => !this._destroyed && this._state.generation === generation && this._state.selectedId === accountId;
    try {
      this._unsubscribe = subscribe.call(this._feed, accountId, raw => {
        if (!live()) return;
        const read = this._accept(raw, accountId);
        // A push for another account or ledger is somebody else's reading, and
        // one older than what is shown arrived out of order: neither replaces it.
        if (typeof read === 'string') return;
        const shown = this._state.snapshot;
        if (shown !== null && read.asOf < shown.asOf) return;
        this._set({ status: 'ready', reason: undefined, snapshot: read });
      }, () => { if (live()) this.disconnected(); });
    } catch {
      this._unsubscribe = null;
    }
  }

  /**
   * The provider or the host lost the connection. The last figures stay on
   * screen marked stale; anything still in flight is abandoned, because it was
   * asked for over the connection that just failed.
   */
  public disconnected(reason = DISCONNECTED): void {
    if (this._destroyed || this._state.status === 'unsupported') return;
    const generation = this._advance();
    const snapshot = this._state.snapshot;
    this._set(snapshot === null
      ? { status: 'error', reason, generation }
      : { status: 'stale', reason, generation });
  }

  /** Re-list and reload after a disconnect. The same as `refresh`, named for the call site. */
  public reconnect(): Promise<AccountSelectResult> { return this.refresh(); }

  /**
   * A position row carries its account only when the provider stamps one. A
   * row naming another account is dropped and counted; one naming none is the
   * selected account's, because that is the account the provider was asked for.
   */
  public positions(): Promise<AccountReadResult<Position>> {
    return this._read('accounts', (id, signal) => this._feed.getAccountPositions?.(id, signal), (row: unknown, accountId) => {
      const r = row as Partial<Position> | null;
      if (r === null || typeof r !== 'object' || (r.accountId !== undefined && r.accountId !== accountId)) return null;
      return nonEmpty(r.symbol) && Number.isFinite(r.netQty) && Number.isFinite(r.avgPrice) ? row as Position : null;
    });
  }

  public executions(query: Omit<AccountHistoryQuery, 'accountId'> = {}): Promise<AccountReadResult<Execution>> {
    return this._read('executions', (accountId, signal) => this._feed.getExecutions!({ ...query, accountId }, signal), readExecution);
  }

  public orderHistory(query: Omit<AccountHistoryQuery, 'accountId'> = {}): Promise<AccountReadResult<OrderHistoryEntry>> {
    return this._read('orderHistory', (accountId, signal) => this._feed.getOrderHistory!({ ...query, accountId }, signal), readHistory);
  }

  /**
   * One read for the selected account. Rows for any other account are dropped
   * and counted, not merged: a provider that answers with a neighbour's fills
   * is wrong, and showing them would be worse than showing fewer.
   */
  private async _read<T>(
    feature: TradingFeature,
    fetch: (accountId: string, signal: AbortSignal) => Promise<readonly unknown[]> | undefined,
    read: (row: unknown, accountId: string) => T | null,
  ): Promise<AccountReadResult<T>> {
    if (this._destroyed) return { ok: false, reason: 'The account manager was destroyed', cancelled: true };
    const support = this._support('accounts') ?? (feature === 'accounts' ? null : this._support(feature));
    if (support !== null) return { ok: false, reason: support, unsupported: true };
    const accountId = this._state.selectedId;
    if (accountId === null) return { ok: false, reason: 'No account is selected' };
    const generation = this._state.generation;
    const abort = this._controller();
    try {
      const pending = fetch(accountId, abort.signal);
      if (pending === undefined) return { ok: false, reason: 'Account positions are not implemented by this feed', unsupported: true };
      const raw = await pending;
      if (this._destroyed || this._state.generation !== generation) return { ok: false, reason: CANCELLED, cancelled: true };
      const rows: T[] = [];
      const list = Array.isArray(raw) ? raw : [];
      for (const row of list) {
        const value = read(row, accountId);
        if (value !== null) rows.push(value);
      }
      return { ok: true, accountId, rows, dropped: list.length - rows.length };
    } catch (error) {
      if (this._destroyed || this._state.generation !== generation) return { ok: false, reason: CANCELLED, cancelled: true };
      return { ok: false, reason: errorText(error) };
    } finally {
      this._aborts.delete(abort);
    }
  }

  /** Abort everything, drop the stream and the listeners. Later calls refuse. */
  public destroy(): void {
    if (this._destroyed) return;
    this._advance();
    this._destroyed = true;
    this._listeners.clear();
  }
}
