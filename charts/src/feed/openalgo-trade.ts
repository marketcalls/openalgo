/**
 * OpenAlgo trade adapter (ARCHITECTURE.md §10.0). Implements the order engine's
 * OrderFeed over OpenAlgo REST (`/api/v1/placeorder`, `/modifyorder`,
 * `/cancelorder`) plus orderbook/positionbook fetches for reconciliation.
 *
 * Payloads match the local OpenAlgo docs: `placeorder` requires
 * strategy/symbol/action/exchange/pricetype/product/quantity; `modifyorder`
 * additionally requires the full order context, so we cache each order's context
 * (from place + the order book) and merge the patch on modify. Book responses
 * return string quantities/prices, which are decoded to numbers. Fetch is
 * injectable for offline tests; verify field names against your OpenAlgo build.
 *
 * Two guarantees live HERE rather than in `OrderEngine`, because the largest
 * consumer drives this class directly and never constructs the engine:
 *
 * - **Reading the book fails closed.** An unmappable enum or an unreadable
 *   number never becomes a tradable order. See `decodeOrder`.
 * - **The analyzer/live mode is checked, not claimed.** See `getServerMode`.
 */
import type { OrderFeed, PlaceRequest, PreflightFailure, TradeMode } from '../trade/order-engine';
import type { Order, OrderStatus, Position } from '../trade/types';
import type { OrderSide, OrderType } from './types';
import { validateQuantity, type OrderConstraints } from '../trade/validation';
import { assertTradingCapability, type TradingCapabilityRequest, type TradingCapabilitySource } from './trading-capabilities';
import type { LooseOptional } from '../helpers/types';

/**
 * An error that says the request PROVABLY never left this process.
 *
 * `OrderEngine` keeps an idempotency token claimed after any failure it cannot
 * rule out, because a failed write says the response did not arrive, not that
 * the request did not. Only this marker releases it, so only a failure raised
 * before `fetch` is called may carry it. A non-ok HTTP response must never be
 * marked: the request plainly left.
 */
function preflight(message: string): Error & PreflightFailure {
  return Object.assign(new Error(message), { preflight: true } as const);
}

/** How hard `place` checks the server's mode against the caller's. */
export type ModeCheck = 'off' | 'auto' | 'always';

export interface OpenAlgoTradeConfig {
  baseUrl: string;
  apiKey: string;
  /** Optional host/broker restrictions; omitted preserves the existing OpenAlgo path. */
  capabilities?: TradingCapabilitySource;
  /**
   * Instrument constraints for the advisory pre-trade check on `place`, looked
   * up per order. Return undefined when the instrument is unknown; the
   * universal checks below still apply.
   *
   * Optional because most of the value needs no configuration: a quantity that
   * is NaN, negative or fractional is wrong for every Indian instrument and is
   * rejected without knowing anything about the symbol. Supply this to add the
   * freeze limit and the lot grid, which do need instrument data.
   */
  constraints?: (symbol: string, exchange: string) => OrderConstraints | undefined;
  /**
   * Turn off the feed-level duplicate guard. Default false, i.e. the guard is
   * on. Only set true if a layer above already owns idempotency AND you have
   * read why that is usually the wrong call: see `_claimToken`.
   */
  disableIdempotency?: boolean;
  /** Strategy label sent with orders (OpenAlgo groups by strategy). */
  strategy?: string;
  /** Default product when a request doesn't specify one. */
  defaultProduct?: 'CNC' | 'NRML' | 'MIS';
  fetchImpl?: typeof fetch;
  /**
   * Mode guard on `place`. Default `'auto'`, which is described in full on
   * `_assertMode`. `'always'` checks both directions and refuses when the
   * server cannot be asked; `'off'` restores the pre-1.6 behaviour of trusting
   * the caller's `mode` outright.
   */
  verifyMode?: ModeCheck;
  /** How long a server-mode reading stays usable, in ms. Default 5000. */
  modeCacheMs?: number;
  /**
   * Called after an order book fetch that had to quarantine rows. Fail-closed
   * parsing drops nothing silently: a host that shows the book must be able to
   * tell the trader that part of it could not be read.
   */
  onDecodeIssue?: (snapshot: OrderBookSnapshot) => void;
  /** Clock, injectable so the mode cache is testable without real timers. */
  now?: () => number;
}

/**
 * Context needed to build a documented modifyorder payload.
 *
 * `price` and `triggerPrice` are held here for the same reason `quantity` is:
 * OpenAlgo's modifyorder takes the WHOLE order, not a delta, so any field the
 * caller does not mention still has to be sent, and it has to be sent at its
 * current value. Defaulting the unmentioned one to 0 does not leave it alone,
 * it overwrites it with zero on a live working order.
 */
interface OrderContext {
  symbol: string;
  exchange: string;
  action: string;
  pricetype: OrderType;
  product: string;
  quantity: number;
  price: number;
  triggerPrice: number;
}

export class OpenAlgoTradeFeed implements OrderFeed {
  private readonly _config: OpenAlgoTradeConfig;
  private readonly _fetch: typeof fetch;
  private readonly _strategy: string;
  private readonly _defaultProduct: string;
  private readonly _ctx = new Map<string, OrderContext>();
  /**
   * Client order ids this feed has put on the wire, and whether the outcome is
   * known. A claimed-but-unresolved entry blocks a repeat. See `_claimToken`.
   */
  private readonly _claimed = new Map<string, 'inflight' | 'sent' | 'ambiguous'>();
  private readonly _verifyMode: ModeCheck;
  private readonly _modeCacheMs: number;
  private readonly _now: () => number;
  private _mode?: TradeMode;
  private _modeAt = 0;

  public constructor(config: OpenAlgoTradeConfig) {
    this._config = config;
    this._strategy = config.strategy ?? 'openalgo-charts';
    this._defaultProduct = config.defaultProduct ?? 'MIS';
    this._verifyMode = config.verifyMode ?? 'auto';
    this._modeCacheMs = config.modeCacheMs ?? 5000;
    this._now = config.now ?? Date.now;
    // Bind to the global object: a stored `this._fetch(...)` of window.fetch
    // throws "Illegal invocation" in browsers.
    const f = config.fetchImpl ?? (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : undefined);
    if (f === undefined) throw new Error('openalgo-charts: no fetch available; pass config.fetchImpl');
    this._fetch = f;
  }

  private async _post(path: string, body: Record<string, unknown>): Promise<unknown> {
    const res = await this._fetch(`${this._config.baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: this._config.apiKey, ...body }),
    });
    if (!res.ok) {
      // Surface OpenAlgo's own error text (e.g. RMS rules, square-off windows)
      // instead of a bare status code: the UI shows this to the trader.
      let detail = '';
      try {
        const j = (await res.json()) as { message?: string };
        if (typeof j.message === 'string' && j.message !== '') detail = `: ${j.message}`;
      } catch { /* non-JSON error body */ }
      throw new Error(`openalgo-charts: ${path} failed (${res.status})${detail}`);
    }
    const json: unknown = await res.json();
    // Warm the mode cache from any response that names the mode. OpenAlgo
    // stamps `mode: "analyze"` on every sandbox response (placeorder,
    // orderbook, positionbook) and returns the pair under `data` from the
    // analyzer endpoint. Live responses say nothing at all, so silence is not
    // evidence of live and only an explicit word counts. This is what keeps
    // the guard in `place` off the network for a host that already polls.
    const mode = readMode(json);
    if (mode !== undefined) { this._mode = mode; this._modeAt = this._now(); }
    return json;
  }

  /* ── analyzer mode ────────────────────────────────────────────────────── */

  /**
   * Read the analyzer mode the SERVER is in.
   *
   * Analyzer mode is a server-side global in OpenAlgo: `get_analyze_mode()`
   * decides where every order goes, and it is flipped at
   * `POST /api/v1/analyzer/toggle`. It is not a per-order flag, there is no
   * mode field on the placeorder payload, and one added there would be read by
   * nothing. So this client never asserts a mode. It asks for the server's,
   * and `place` refuses when the answer disagrees with the caller's belief.
   *
   * Answers younger than `maxAgeMs` are reused, so a host that polls the books
   * (whose sandbox responses carry the mode already) never pays for this call.
   */
  public async getServerMode(maxAgeMs = this._modeCacheMs): Promise<TradeMode> {
    const cached = this._freshMode(maxAgeMs);
    if (cached !== undefined) return cached;
    const mode = readMode(await this._post('/api/v1/analyzer/', {}));
    if (mode === undefined) {
      throw new Error('openalgo-charts: /api/v1/analyzer/ returned no readable mode');
    }
    return mode; // _post already cached it on the way through
  }

  /** The last server-mode reading, if one is still within `maxAgeMs`. */
  public serverMode(maxAgeMs = this._modeCacheMs): TradeMode | undefined {
    return this._freshMode(maxAgeMs);
  }

  private _freshMode(maxAgeMs: number): TradeMode | undefined {
    if (this._mode === undefined) return undefined;
    return this._now() - this._modeAt <= maxAgeMs ? this._mode : undefined;
  }

  /**
   * Refuse to send when the server's mode contradicts the caller's.
   *
   * The default is asymmetric because the two mistakes do not cost the same.
   * Believing you are on the sandbox while the server is live spends real
   * money, so `analyzer` demands a positive answer and probes for one when the
   * cache is cold. Believing you are live while the server is sandboxed is bad
   * but costs nothing, so `live` uses only what the cache already knows and
   * never adds a round trip to a real order. `verifyMode: 'always'` probes in
   * both directions.
   *
   * A caller that passes no mode at all is not checked: it has claimed nothing,
   * so there is nothing to contradict.
   */
  private async _assertMode(expected: TradeMode): Promise<void> {
    if (this._verifyMode === 'off') return;
    if (expected !== 'live' && expected !== 'analyzer') return;
    let actual = this._freshMode(this._modeCacheMs);
    if (actual === undefined && (this._verifyMode === 'always' || expected === 'analyzer')) {
      // Every failure here is pre-flight for the order: the probe is a separate
      // request and the placeorder has not been written yet. Rethrowing it
      // unmarked would tell the trader to go and check an order book for an
      // order that was never sent.
      try {
        actual = await this.getServerMode();
      } catch (err) {
        throw preflight(`openalgo-charts: cannot confirm the server mode, no order was sent (${String((err as Error).message ?? err)})`);
      }
    }
    if (actual === undefined || actual === expected) return;
    throw preflight(
      `openalgo-charts: refusing to place, caller expects ${expected} mode but the OpenAlgo server is in ${actual} mode`,
    );
  }

  /* ── writes ───────────────────────────────────────────────────────────── */

  /**
   * Advisory pre-trade quantity check, applied to EVERY order type.
   *
   * Advisory is the operative word: a user with devtools can call the broker
   * directly, so this cannot be a risk control. It is here because the broker's
   * RMS rejection arrives after a round trip and reads like a server error,
   * while this reads like the mistake it is, immediately.
   *
   * It lives in the feed rather than only in `OrderEngine` because the engine is
   * skippable. OpenAlgo's own terminal calls `place` directly and never
   * constructs an engine, so a guarantee reachable only through the engine is
   * not a guarantee for the largest consumer of this library.
   */
  private _assertQuantity(req: PlaceRequest): void {
    const exchange = req.exchange ?? 'NSE';
    // Universal floor first, so a NaN or a negative is refused with no config.
    const c = this._config.constraints?.(req.symbol, exchange) ?? { tickSize: 0 };
    const v = validateQuantity(req.qty, c);
    if (!v.ok) {
      // Pre-flight by construction: nothing has been sent at this point.
      throw preflight(`openalgo-charts: ${req.symbol} ${exchange}: ${v.reason}`);
    }
  }

  /**
   * Refuse a client order id this feed has already put on the wire.
   *
   * The costs are not symmetric, which is the whole argument. Holding a claim
   * too long costs one deliberate click after a banner. Releasing it too early
   * costs a doubled live position that nobody asked for, discovered later, quite
   * possibly on a leveraged intraday product.
   *
   * So a claim is released ONLY when the request provably never left. A non-ok
   * HTTP response, a timeout, an aborted socket: all of those mean the response
   * did not arrive, and say nothing whatsoever about whether the order did. Those
   * stay claimed and are reported as ambiguous.
   *
   * Enforcement note, because the boundary matters: this stops THIS FEED sending
   * the same id twice. It cannot make the broker deduplicate. Two browser tabs
   * are two feeds and two ledgers, and OpenAlgo's placeorder carries no client
   * order id field, so end-to-end idempotency is not available on this wire.
   * What is available, and what this delivers, is that a double-clicked button
   * or a retried promise does not become two orders.
   */
  private _claimToken(token: string | undefined): string | undefined {
    if (token === undefined || this._config.disableIdempotency === true) return undefined;
    const held = this._claimed.get(token);
    if (held !== undefined) {
      throw preflight(
        held === 'ambiguous'
          ? `openalgo-charts: clientToken ${token} may already be live at the broker; check the order book before retrying`
          : `openalgo-charts: duplicate clientToken ${token}`,
      );
    }
    this._claimed.set(token, 'inflight');
    return token;
  }

  public get capabilities(): TradingCapabilitySource | undefined { return this._config.capabilities; }

  /**
   * Place an order through OpenAlgo's placeorder route.
   *
   * An order without `exchange` goes to `NSE`, and one without `product` takes
   * the feed's `defaultProduct`. Both defaults are documented and hosts place
   * through them, so they stay through 2.x. `modify()` is stricter on purpose:
   * it never guesses an exchange or product for an order the book does not
   * describe, since a guess there moves a live order somewhere its owner did
   * not put it. A host that trades on any other exchange passes `exchange`
   * with every order.
   *
   * Every refusal before the request is sent is a pre-flight error, so the
   * caller can correct and retry knowing nothing reached the broker.
   */
  public async place(request: PlaceRequest & { mode: TradeMode }): Promise<{ orderId: string }> {
    const req = { ...request };
    // placeorder has no account, duration, expiry or leverage field; one key is
    // one account. Dropping them would place the order on the key's account at
    // the broker's default validity, which is not what was asked for.
    if (req.account !== undefined || req.duration !== undefined || req.expiresAt !== undefined || req.leverage !== undefined) {
      throw preflight('openalgo-charts: the OpenAlgo placeorder route has no account, duration, expiry or leverage field; nothing was sent');
    }
    const capabilityRequest = { operation: 'place' as const, symbol: req.symbol,
      exchange: req.exchange ?? 'NSE', type: req.type, mode: req.mode };
    assertTradingCapability(this.capabilities, capabilityRequest);
    // `mode` is a guard, not a payload field: OpenAlgo routes on its own global
    // and would ignore a mode in the body, so putting one there would look like
    // a control while doing nothing.
    await this._assertMode(req.mode);
    assertTradingCapability(this.capabilities, capabilityRequest);
    // Both throw pre-flight, so a refusal here provably sent nothing and the
    // caller may correct and retry without wondering whether an order is live.
    this._assertQuantity(req);
    const token = this._claimToken(req.clientToken);
    const ctx: OrderContext = {
      symbol: req.symbol,
      exchange: req.exchange ?? 'NSE',
      action: req.side,
      pricetype: req.type,
      product: req.product ?? this._defaultProduct,
      quantity: req.qty,
      price: req.price ?? 0,
      triggerPrice: req.triggerPrice ?? 0,
    };
    let json: { orderid?: string; order_id?: string };
    try {
      json = (await this._post('/api/v1/placeorder', {
        strategy: this._strategy,
        symbol: ctx.symbol,
        action: ctx.action,
        exchange: ctx.exchange,
        pricetype: ctx.pricetype,
        product: ctx.product,
        quantity: req.qty,
        price: req.price ?? 0,
        trigger_price: req.triggerPrice ?? 0,
        disclosed_quantity: 0,
      })) as { orderid?: string; order_id?: string };
    } catch (err) {
      // The request left. Whatever went wrong afterwards, the order may be live,
      // so the claim is kept and marked. Deleting it here is the bug this whole
      // mechanism exists to prevent: it would make the next attempt look like a
      // first attempt and could double a position.
      if (token !== undefined) this._claimed.set(token, 'ambiguous');
      throw err;
    }
    const orderId = json.orderid ?? json.order_id;
    if (orderId === undefined) throw new Error('openalgo-charts: placeorder returned no orderid');
    if (token !== undefined) this._claimed.set(token, 'sent');
    this._ctx.set(orderId, ctx);
    return { orderId };
  }

  /**
   * Whether a client order id is known to have reached the broker.
   *
   * `'ambiguous'` is the one worth handling: the request left and the outcome is
   * unknown, so the order may be live. A host should say so and offer the order
   * book, not a retry button.
   */
  public tokenState(token: string): 'unknown' | 'inflight' | 'sent' | 'ambiguous' {
    return this._claimed.get(token) ?? 'unknown';
  }

  /**
   * Release a claim after the host has established what really happened, for
   * instance by finding no such order in a freshly fetched book.
   *
   * Deliberately manual. Nothing in this library can safely decide on its own
   * that an ambiguous order did not reach the exchange.
   */
  public releaseToken(token: string): void {
    this._claimed.delete(token);
  }

  public async modify(orderId: string, changes: { price?: number; triggerPrice?: number; qty?: number }): Promise<void> {
    const patch = { ...changes };
    const ctx = this._ctx.get(orderId);
    // An order with no cached context asks without a symbol, which a request reads as absent.
    assertTradingCapability(this.capabilities, { operation: 'modify', orderId,
      symbol: ctx?.symbol, exchange: ctx?.exchange, type: ctx?.pricetype } satisfies LooseOptional<TradingCapabilityRequest> as TradingCapabilityRequest);
    if (ctx === undefined) {
      // Pre-flight: nothing can be built, so nothing is sent, so the order is
      // exactly where it was and the caller may retry once it has the book.
      throw preflight(`openalgo-charts: cannot modify ${orderId}, unknown order context (place it or load the order book first)`);
    }
    // Keep the cache in step with what we are about to send, so a second
    // modify of a different field does not resurrect the previous value.
    if (patch.qty !== undefined) ctx.quantity = patch.qty;
    if (patch.price !== undefined) ctx.price = patch.price;
    if (patch.triggerPrice !== undefined) ctx.triggerPrice = patch.triggerPrice;
    // OpenAlgo modifyorder requires the full order context, not just the delta.
    //
    // The price fields therefore fall back to the CACHED value, never to 0.
    // They used to read `patch.price ?? 0`, which quietly zeroed whichever of
    // the two the caller had not mentioned. Dragging a stop-limit order's line
    // sends only a trigger, so that path sent `price: 0` and wiped the limit
    // price off a live working order at the broker.
    await this._post('/api/v1/modifyorder', {
      orderid: orderId,
      strategy: this._strategy,
      symbol: ctx.symbol,
      action: ctx.action,
      exchange: ctx.exchange,
      pricetype: ctx.pricetype,
      product: ctx.product,
      quantity: ctx.quantity,
      price: ctx.price,
      trigger_price: ctx.triggerPrice,
      disclosed_quantity: 0, // required by the modifyorder API
    });
  }

  public async cancel(orderId: string): Promise<void> {
    const ctx = this._ctx.get(orderId);
    assertTradingCapability(this.capabilities, { operation: 'cancel', orderId, // see modify
      symbol: ctx?.symbol, exchange: ctx?.exchange, type: ctx?.pricetype } satisfies LooseOptional<TradingCapabilityRequest> as TradingCapabilityRequest);
    await this._post('/api/v1/cancelorder', { orderid: orderId, strategy: this._strategy });
  }

  /* ── reads ────────────────────────────────────────────────────────────── */

  /**
   * Fetch the order book, keeping the rows that could not be read.
   *
   * `getOrders` returns the first half of this. A host that renders the book
   * needs the second half too: "2 rows from the broker could not be read" is a
   * thing the trader must see, and a quietly shorter list is not.
   */
  public async getOrderBook(): Promise<OrderBookSnapshot> {
    const json = (await this._post('/api/v1/orderbook', {})) as { data?: { orders?: RawOrder[] } | RawOrder[] };
    const rows = Array.isArray(json.data) ? json.data : (json.data?.orders ?? []);
    const orders: DecodedOrder[] = [];
    const quarantined: QuarantinedRow[] = [];
    for (let i = 0; i < rows.length; i++) {
      const raw = rows[i]!;
      const res = decodeOrder(raw, `orders[${i}]`);
      if (!res.ok) { quarantined.push({ issue: res.issue, raw }); continue; }
      orders.push(res.order);
      // Cache context so a later modify() of a book-loaded order can build its
      // payload, including the price fields, so a drag of an order this session
      // never placed still preserves the field the drag does not touch.
      //
      // Exchange and product are NOT defaulted here any more. They used to read
      // `?? 'NSE'` and `?? this._defaultProduct`, which sends a modify for an
      // MCX order to NSE, or turns a CNC order into MIS. With no context,
      // modify() refuses by name, which is a failure the trader can act on.
      const exchange = str(raw.exchange);
      const product = str(raw.product);
      if (exchange !== undefined && product !== undefined) {
        this._ctx.set(res.order.id, {
          symbol: res.order.symbol, exchange, action: res.order.side, pricetype: res.order.type,
          product, quantity: res.order.qty, price: res.order.price,
          triggerPrice: res.order.triggerPrice ?? 0,
        });
      }
    }
    if (quarantined.length > 0) this._config.onDecodeIssue?.({ orders, quarantined });
    return { orders, quarantined };
  }

  /** Fetch the order book for reconciliation (maps to broker-agnostic orders). */
  public async getOrders(): Promise<DecodedOrder[]> {
    return (await this.getOrderBook()).orders;
  }

  /** Fetch the position book for reconciliation. */
  public async getPositions(): Promise<Position[]> {
    const json = (await this._post('/api/v1/positionbook', {})) as { data?: RawPosition[] };
    return (json.data ?? []).map(mapPosition);
  }
}

export interface RawOrder {
  orderid?: string;
  symbol?: string;
  exchange?: string;
  action?: string;
  pricetype?: string;
  product?: string;
  quantity?: number | string;
  filled_quantity?: number | string;
  price?: number | string;
  trigger_price?: number | string;
  order_status?: string;
}

interface RawPosition {
  symbol?: string;
  quantity?: number | string;
  average_price?: number | string;
}

/* ── fail-closed decoding ───────────────────────────────────────────────── */

export type OrderDecodeCode = 'MISSING' | 'NON_FINITE' | 'RANGE' | 'UNKNOWN_ENUM';

export interface OrderDecodeIssue {
  /** Where it went wrong, e.g. `orders[3].action`. */
  path: string;
  code: OrderDecodeCode;
  /** What a readable value looks like, in words the trader can act on. */
  expected: string;
  /** The offending value, stringified and clipped. Never the whole payload. */
  got: string;
}

/** A book row that had no honest order form, kept for diagnosis. */
export interface QuarantinedRow {
  issue: OrderDecodeIssue;
  raw: RawOrder;
}

export interface OrderBookSnapshot {
  /** Rows that decoded, including any whose status is `unknown`. */
  orders: DecodedOrder[];
  quarantined: QuarantinedRow[];
}

/**
 * An order read from the book.
 *
 * Identical to `Order` except that `status` may be `unknown`: a broker status
 * this adapter cannot map is reported as unknown rather than asserted to be
 * working. Unknown is not terminal, so a later snapshot can still rescue the
 * row, and every consumer that gates on `status === 'working'` treats it as
 * untradable, which is the point.
 *
 * The member is widened here rather than in `OrderStatus` because widening the
 * shared union is a change to `src/trade/types.ts`, deferred to the v2 contract
 * work that owns that file.
 */
export interface DecodedOrder extends Omit<Order, 'status'> {
  status: OrderStatus | 'unknown';
  /** The broker's own status text, kept verbatim whenever `status` is unknown. */
  rawStatus?: string;
}

export type OrderDecodeResult =
  | { ok: true; order: DecodedOrder }
  | { ok: false; issue: OrderDecodeIssue };

/** Decode OpenAlgo's string-or-number numerics. Unreadable is undefined, not 0. */
function decNum(v: unknown): number | undefined {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
  return Number.isFinite(n) ? n : undefined;
}

/** A non-empty trimmed string, or undefined. An empty field is missing, not a value. */
function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;
}

// Shared so the same phrase is not spelled out once per field.
const NON_EMPTY = 'a non-empty string';
const FINITE = 'a finite number';
const NOT_NEGATIVE = 'a number of 0 or more';

function bad(path: string, code: OrderDecodeCode, expected: string, got: unknown): { ok: false; issue: OrderDecodeIssue } {
  const s = typeof got === 'string' ? got : String(got);
  return { ok: false, issue: { path, code, expected, got: s.slice(0, 64) } };
}

const STATUS_MAP: Record<string, OrderStatus | undefined> = {
  open: 'working', pending: 'pending', trigger_pending: 'working',
  'trigger pending': 'working',
  complete: 'filled', cancelled: 'cancelled', rejected: 'rejected',
};

/**
 * Map a lowercase OpenAlgo order_status to the chart's status.
 *
 * An unrecognised status reads `unknown`. It used to read `working`, which
 * asserted that an order nobody could classify was live in the book and
 * draggable on the chart. OpenAlgo's own broker mappings emit the literal
 * string `unknown` when a broker sends a state they do not recognise, so this
 * default was reachable in production, not only from a malformed payload.
 */
export function mapOrderStatus(s: string): OrderStatus | 'unknown' {
  return STATUS_MAP[s.trim().toLowerCase()] ?? 'unknown';
}

/**
 * Decode one order book row, failing closed.
 *
 * The split follows what the field is for. Identity-bearing fields (id, symbol,
 * side, order type, quantity, prices) either read cleanly or the row is
 * quarantined: there is no substitute value that is safe to trade against, and
 * the old `action === 'SELL' ? 'SELL' : 'BUY'` turned a typo, a null and an
 * unrecognised broker enum alike into a BUY.
 *
 * Status is descriptive, so an unmappable one degrades to `unknown` and the row
 * is KEPT. Hiding an order that exists is worse than showing one nobody can
 * classify, which is the opposite trade-off from the identity fields and is
 * deliberate.
 */
export function decodeOrder(r: RawOrder, path = 'order'): OrderDecodeResult {
  const id = str(r.orderid);
  if (id === undefined) return bad(`${path}.orderid`, 'MISSING', NON_EMPTY, r.orderid);
  const symbol = str(r.symbol);
  if (symbol === undefined) return bad(`${path}.symbol`, 'MISSING', NON_EMPTY, r.symbol);
  const side = str(r.action)?.toUpperCase();
  if (side !== 'BUY' && side !== 'SELL') return bad(`${path}.action`, 'UNKNOWN_ENUM', 'BUY or SELL', r.action);
  const type = str(r.pricetype)?.toUpperCase();
  if (type !== 'MARKET' && type !== 'LIMIT' && type !== 'SL' && type !== 'SL-M') {
    return bad(`${path}.pricetype`, 'UNKNOWN_ENUM', 'MARKET, LIMIT, SL or SL-M', r.pricetype);
  }

  const qty = decNum(r.quantity);
  if (qty === undefined) {
    return bad(`${path}.quantity`, r.quantity === undefined ? 'MISSING' : 'NON_FINITE', FINITE, r.quantity);
  }
  if (qty < 0) return bad(`${path}.quantity`, 'RANGE', NOT_NEGATIVE, r.quantity);

  // Absent numerics are the broker's own convention and stay at zero: several
  // OpenAlgo broker mappings omit filled_quantity entirely, and a MARKET row
  // carries no price. A field that is PRESENT and unreadable is a different
  // thing and quarantines the row, because "abc" coerced to 0 puts a live limit
  // order on the chart at zero, which reads as a market order in disguise.
  const filled = r.filled_quantity === undefined ? 0 : decNum(r.filled_quantity);
  if (filled === undefined) return bad(`${path}.filled_quantity`, 'NON_FINITE', FINITE, r.filled_quantity);
  const price = r.price === undefined ? 0 : decNum(r.price);
  if (price === undefined) return bad(`${path}.price`, 'NON_FINITE', FINITE, r.price);
  if (price < 0) return bad(`${path}.price`, 'RANGE', NOT_NEGATIVE, r.price);
  const trigger = r.trigger_price === undefined ? 0 : decNum(r.trigger_price);
  if (trigger === undefined) return bad(`${path}.trigger_price`, 'NON_FINITE', FINITE, r.trigger_price);
  // A negative trigger needs no check of its own: the zero test below already
  // reads it as "no trigger", which draws nothing.

  const rawStatus = str(r.order_status) ?? '';
  const status = STATUS_MAP[rawStatus.toLowerCase()];
  const order: DecodedOrder = {
    id, symbol, side, type, qty, filledQty: filled, price,
    // trigger_price 0 means "no trigger" (a plain LIMIT/MARKET): keep it undefined
    // so `triggerPrice ?? price` doesn't render the line at 0 (?? ignores undefined, not 0).
    triggerPrice: trigger > 0 ? trigger : undefined,
    status: status ?? 'unknown',
  };
  if (status === undefined) order.rawStatus = rawStatus;
  return { ok: true, order };
}

/**
 * Total row mapper, kept for the published surface.
 *
 * Prefer `decodeOrder`, which says WHY a row could not be read instead of
 * handing back a placeholder. A row that fails an identity check has no honest
 * `Order` form, because `OrderSide` has no unknown member and so the
 * placeholder cannot say "side unreadable". It marks the whole record instead,
 * with `status: 'unknown'`, which is inert in every consumer: they all gate on
 * `status === 'working'` before drawing or acting on a row. The broker's own
 * word is passed through rather than replaced, because showing `FOO` is honest
 * and showing `BUY` is exactly the fail-open this replaced.
 *
 * `getOrders` does not use this: it quarantines such rows outright.
 *
 * @deprecated Removed in 3.0.0. Use {@link decodeOrder} (since 1.6.0), which
 * returns the reason a row could not be read, or
 * {@link OpenAlgoTradeFeed.getOrderBook}, which sets such rows aside as
 * `quarantined`.
 */
export function mapOrder(r: RawOrder): DecodedOrder {
  const res = decodeOrder(r);
  if (res.ok) return res.order;
  return {
    id: str(r.orderid) ?? '',
    symbol: str(r.symbol) ?? '',
    side: (str(r.action) ?? '') as OrderSide,
    type: (str(r.pricetype) ?? '') as OrderType,
    qty: decNum(r.quantity) ?? 0,
    filledQty: decNum(r.filled_quantity) ?? 0,
    price: decNum(r.price) ?? 0,
    status: 'unknown',
    rawStatus: str(r.order_status) ?? '',
  };
}

export function mapPosition(r: RawPosition): Position {
  return { symbol: r.symbol ?? '', netQty: decNum(r.quantity) ?? 0, avgPrice: decNum(r.average_price) ?? 0 };
}

/**
 * Read a mode out of any OpenAlgo response.
 *
 * `analyze` is OpenAlgo's word on the wire for what this library calls
 * `analyzer`. Only an explicit word counts: a live response carries no mode
 * field at all, so absence proves nothing and must never be read as live.
 */
function readMode(json: unknown): TradeMode | undefined {
  if (typeof json !== 'object' || json === null) return undefined;
  const o = json as { mode?: unknown; data?: { mode?: unknown; analyze_mode?: unknown } };
  const word = o.mode ?? o.data?.mode;
  if (word === 'analyze') return 'analyzer';
  if (word === 'live') return 'live';
  const flag = o.data?.analyze_mode;
  return typeof flag === 'boolean' ? (flag ? 'analyzer' : 'live') : undefined;
}
