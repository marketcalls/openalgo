/**
 * OpenAlgo WebSocket adapter (ARCHITECTURE.md §10). Speaks the documented
 * OpenAlgo WS proxy protocol (default port 8765, or wss://host/ws in production):
 *
 *   1. authenticate: { action:'authenticate', api_key }
 *      server answers { type:'auth', status:'success' } (or a refusal)
 *   2. subscribe   : { action:'subscribe', symbol, exchange, mode }   mode 1=LTP 2=Quote 3=Depth
 *                    (Depth adds depth_level, e.g. 5/20/30/50)
 *   3. server pushes { type:'market_data', symbol, exchange, mode, data:{...} }
 *   4. heartbeat   : OpenAlgo's proxy pings at the protocol level, which a
 *      browser answers without telling JavaScript, so the client keeps its own
 *      watchdog and asks { action:'ping' } when the stream goes quiet. An
 *      application-level 'ping' frame, which some builds send, is ponged.
 *
 * Maps inbound LTP / Quote / Depth into typed callbacks the chart consumes
 * (candle builder, last price, DOM ladder). The socket is injectable so the
 * adapter is unit-testable with a fake socket and no network.
 *
 * Step 1 is a gate, not a formality. Nothing but the auth frame leaves the
 * socket until the server acknowledges: a proxy that drops pre-auth frames
 * otherwise leaves a chart that believes it is subscribed and is permanently
 * silent, which under a Buy button is the worst state this library can be in.
 */
import type { MarketDepth } from './types';
import { epochMsToUtcSeconds } from './time';
import type { LooseOptional } from '../helpers/types';
import { later } from '../helpers/timers';
import { dispatch } from '../helpers/dispatch';

export type WsMode = 'LTP' | 'Quote' | 'Depth';

/**
 * Socket lifecycle reported by `onState`.
 *
 * 'open' means authenticated and carrying traffic, not merely TCP-connected:
 * the window between transport open and the auth acknowledgement still reads
 * as 'connecting', because nothing can be sent in it.
 */
export type WsState = 'connecting' | 'open' | 'closed' | 'error' | 'reconnecting';

/** A non-market-data control frame (auth / subscribe ack, or a server error). */
export interface WsControlMessage {
  type?: string;
  status?: string;
  message?: string;
  [k: string]: unknown;
}

/**
 * A warning the client raised about its own connection, delivered on the same
 * control channel. `type` is deliberately a value no server frame uses, so a
 * host can never mistake one for the other.
 */
export interface WsClientWarning extends WsControlMessage {
  type: 'client_warning';
  /**
   * AUTH_TIMEOUT | AUTH_FAILED | AUTH_UNACKNOWLEDGED | RECONNECT_ABANDONED |
   * HEARTBEAT_DEAD | STREAM_RESYNC | SEQUENCE_GAP
   */
  code: string;
  message: string;
}

/** The number the OpenAlgo proxy expects in a subscribe frame's `mode` field for each data mode. */
const MODE_NUMBER: Record<WsMode, number> = { LTP: 1, Quote: 2, Depth: 3 };

/** Minimal socket surface (the browser WebSocket satisfies this). */
export interface SocketLike {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror?: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  /** 1 === OPEN (browser WebSocket.OPEN). Used to gate sends. */
  readyState?: number;
}

export type SocketFactory = (url: string) => SocketLike;

export interface OpenAlgoWsConfig {
  url: string; // e.g. ws://127.0.0.1:8765 (or wss://host/ws)
  apiKey: string;
  socketFactory?: SocketFactory | undefined;
  /**
   * Auto-reconnect after an unexpected close: re-authenticate and resubscribe
   * every active subscription, with jittered exponential backoff. Enabled by
   * default; `close()` is treated as intentional and never reconnects.
   */
  reconnect?: {
    enabled?: boolean;
    baseDelayMs?: number;
    maxDelayMs?: number;
    maxAttempts?: number;
    /** Full jitter on each delay (default true). Off gives the old lockstep timing. */
    jitter?: boolean;
    /** Injectable [0,1) source, so a test pins the delay instead of guessing it. */
    random?: () => number;
  } | undefined;
  /** Handshake gating. Data frames wait for the server's answer to `authenticate`. */
  auth?: {
    /**
     * Require a positive acknowledgement (default true). Set false only for a
     * proxy build known to answer nothing: the connection then counts as
     * authenticated on transport open, and one AUTH_UNACKNOWLEDGED warning is
     * raised per connection so the missing guarantee is visible rather than
     * silently assumed.
     */
    requireAck?: boolean;
    /** Wait for the acknowledgement this long before failing the connection (default 5000). */
    ackTimeoutMs?: number;
  } | undefined;
  /**
   * Liveness watchdog. After `timeoutMs` with no inbound frame the client asks
   * the far end a direct question and gives it `probeMs` to answer; only
   * silence to that counts as death, and the socket is then reconnected
   * (defaults 45000 and 5000; a `timeoutMs` of 0 disables the watchdog).
   */
  heartbeat?: { timeoutMs?: number; probeMs?: number } | undefined;
}

export interface LtpEvent {
  symbol: string;
  exchange: string;
  ltp: number;
  ltq?: number;
  /** Cumulative day volume (Quote mode): feeds the candle builder's day-delta mode. */
  volume?: number;
  timeSec: number;
}

/** Pure: the auth handshake message that must precede any subscription. */
function formatAuthenticate(apiKey: string): string {
  return JSON.stringify({ action: 'authenticate', api_key: apiKey });
}

/** Pure: subscribe to the account-level order-update stream (no symbols/modes). */
function formatSubscribeOrders(): string {
  return JSON.stringify({ action: 'subscribe_orders' });
}

function formatUnsubscribeOrders(): string {
  return JSON.stringify({ action: 'unsubscribe_orders' });
}

/**
 * Real-time order lifecycle event from the `subscribe_orders` stream: fills,
 * partial fills, rejections, cancellations, pushed by the broker (or by the
 * sandbox engine in analyze mode).
 */
export interface OrderUpdateEvent {
  orderId: string;
  symbol: string;
  exchange: string;
  action: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  /** Undefined when the broker reports 0 (plain LIMIT/MARKET). */
  triggerPrice?: number;
  pricetype: string;
  product: string;
  /** Lowercase OpenAlgo status: open | trigger pending | complete | rejected | cancelled | ... */
  status: string;
  filledQuantity: number;
  pendingQuantity: number;
  averagePrice: number;
  /** Broker RMS/OMS text when rejected. */
  rejectionReason: string;
  /** 'live' for broker events, 'analyze' for sandbox events. */
  mode: string;
}

/** Pure: parse an inbound `order_update` frame; null for any other message. */
export function parseOrderUpdate(raw: unknown): OrderUpdateEvent | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const m = raw as Record<string, unknown>;
  if (m.type !== 'order_update') return null;
  const num = (v: unknown): number => {
    if (typeof v === 'number') return v;
    if (typeof v === 'string' && v.trim() !== '') { const n = Number(v); return Number.isNaN(n) ? 0 : n; }
    return 0;
  };
  const str = (v: unknown): string => (typeof v === 'string' ? v : '');
  const trig = num(m.trigger_price);
  // No trigger is an undefined `triggerPrice`, which the event reads as absent.
  return {
    orderId: str(m.orderid),
    symbol: str(m.symbol),
    exchange: str(m.exchange),
    action: m.action === 'SELL' ? 'SELL' : 'BUY',
    quantity: num(m.quantity),
    price: num(m.price),
    triggerPrice: trig > 0 ? trig : undefined,
    pricetype: str(m.pricetype) === '' ? 'LIMIT' : str(m.pricetype),
    product: str(m.product),
    status: str(m.order_status).toLowerCase(),
    filledQuantity: num(m.filled_quantity),
    pendingQuantity: num(m.pending_quantity),
    averagePrice: num(m.average_price),
    rejectionReason: str(m.rejection_reason),
    mode: str(m.mode),
  } satisfies LooseOptional<OrderUpdateEvent> as OrderUpdateEvent;
}

/**
 * Pure: build a subscribe message, `{ action, symbol, exchange, mode }`, where
 * `mode` is the numeric OpenAlgo data mode. Depth subscriptions may request a
 * book depth (broker-dependent: 5/20/30/50).
 *
 * The wire key the proxy reads is `depth`; 1.x sent `depth_level`, which the
 * proxy never read, so every request above the default was silently served
 * at five levels. Both keys go out: `depth` for the proxy, `depth_level` for
 * any consumer that learned the old name from this library. A wire key has no
 * declaration to tag, so COMPATIBILITY.md lists `depth_level` as deprecated:
 * 3.0.0 stops sending it.
 */
export function formatSubscribe(mode: WsMode, symbol: string, exchange: string, depthLevel?: number): string {
  const msg: Record<string, unknown> = { action: 'subscribe', symbol, exchange, mode: MODE_NUMBER[mode] };
  if (mode === 'Depth' && depthLevel !== undefined) {
    msg.depth = depthLevel;
    msg.depth_level = depthLevel;
  }
  return JSON.stringify(msg);
}

export function formatUnsubscribe(mode: WsMode, symbol: string, exchange: string): string {
  return JSON.stringify({ action: 'unsubscribe', symbol, exchange, mode: MODE_NUMBER[mode] });
}

interface DepthLevel { price: number; quantity: number; orders?: number }
interface RawData {
  symbol?: string;
  exchange?: string;
  ltp?: number;
  last_price?: number;
  last_trade_quantity?: number;
  ltq?: number;
  volume?: number; // cumulative day volume (Quote mode)
  timestamp?: number | string;
  /** Market event times can precede the proxy's delivery timestamp. */
  ltt?: number | string;
  last_trade_time?: number | string;
  exchange_timestamp?: number | string;
  depth?: { buy?: DepthLevel[]; sell?: DepthLevel[] };
}
interface RawMsg {
  type?: string;
  mode?: number;
  topic?: string;
  data?: RawData;
}

/** Coerce a WS timestamp (epoch s/ms or ISO-8601 string) to UTC seconds. */
function toSec(ts: number | string | undefined): number {
  if (typeof ts === 'string' && /^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(ts.trim())) ts = Number(ts);
  if (typeof ts === 'number') return Number.isFinite(ts) && ts > 0
    ? (ts > 1e12 ? epochMsToUtcSeconds(ts) : Math.floor(ts)) : 0;
  if (typeof ts === 'string' && ts.trim() !== '') {
    const ms = Date.parse(ts); // ISO-8601 with 'Z' is unambiguous UTC
    if (Number.isFinite(ms) && ms > 0) return Math.floor(ms / 1000);
  }
  return 0;
}

function marketTimeSec(data: RawData): number {
  // Replayed/cached quotes may be delivered today but describe an earlier
  // session. Delivery time must not turn that snapshot into a new candle.
  for (const value of [data.last_trade_time, data.ltt, data.exchange_timestamp, data.timestamp]) {
    const seconds = toSec(value);
    if (seconds > 0) return seconds;
  }
  return 0;
}

/** True if the inbound frame is a heartbeat ping (plain "ping" or { type:'ping' }). */
function isPing(raw: unknown): boolean {
  if (raw === 'ping') return true;
  return typeof raw === 'object' && raw !== null && (raw as { type?: string }).type === 'ping';
}

/**
 * Pure: split the documented `SYMBOL.EXCHANGE` topic.
 *
 * Only that two-part form is accepted. Guessing at other separators would
 * misattribute a tick to the wrong instrument, and a wrong price on the right
 * chart is worse than no price at all.
 */
export function parseTopic(topic: unknown): { symbol: string; exchange: string } | null {
  if (typeof topic !== 'string') return null;
  const parts = topic.split('.');
  if (parts.length !== 2) return null;
  const [symbol, exchange] = parts as [string, string];
  if (symbol === '' || exchange === '') return null;
  return { symbol, exchange };
}

/**
 * Pure: classify the server's answer to the handshake as 'ok', 'failed', or
 * null for a frame that is not about authentication at all.
 *
 * Absence of an error is never an acknowledgement, so 'ok' is only ever
 * returned for a frame that says so. An error frame counts as a refusal
 * because the handshake is the only thing outstanding when it arrives, and it
 * is recognised by `status: 'error'` as well as by `type: 'error'`: OpenAlgo's
 * proxy answers a bad key with `{ status:'error', code, message }` and no type
 * at all, so keying only on the type left the one refusal that matters
 * unclassified and retried on a timer until the key got rate limited.
 */
export function classifyAuthAck(raw: unknown): 'ok' | 'failed' | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const m = raw as { type?: unknown; status?: unknown; message?: unknown };
  const type = typeof m.type === 'string' ? m.type.toLowerCase() : '';
  const status = typeof m.status === 'string' ? m.status.toLowerCase() : '';
  const ok = status === 'success' || status === 'ok' || status === 'authenticated';
  if (type === 'auth' || type === 'authenticate' || type === 'auth_response') return ok ? 'ok' : 'failed';
  if (type === 'error' || status === 'error') return 'failed';
  // Some proxy builds answer with a bare { status, message } and no type. Only
  // a message that names the handshake is read as one, so an unrelated status
  // frame cannot open the gate.
  if (type === '' && ok && typeof m.message === 'string' && /auth/i.test(m.message)) return 'ok';
  return null;
}

/**
 * Pure: the per-topic sequence number on an inbound frame, when the server
 * sends one.
 *
 * OpenAlgo's documented market_data frame carries no sequence, so the gap
 * detection built on this is inert against a stock proxy, and that is
 * deliberate: a client cannot see a silent drop on an unsequenced stream, and
 * claiming gap detection the wire does not support would be a lie in the UI.
 * A proxy that does number its frames gets the warnings for free.
 */
export function readSequence(raw: unknown): number | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined;
  const m = raw as Record<string, unknown> & { data?: Record<string, unknown> };
  const pick = (o: Record<string, unknown> | undefined): number | undefined => {
    if (o === undefined) return undefined;
    for (const k of ['seq', 'sequence', 'sequence_number'] as const) {
      const v = o[k];
      if (typeof v === 'number' && Number.isFinite(v)) return v;
    }
    return undefined;
  };
  return pick(m) ?? pick(m.data);
}

/**
 * Full-jitter backoff: attempt n waits somewhere in [ceiling/2, ceiling).
 *
 * Deterministic backoff has every client in a fleet reconnecting in the same
 * millisecond after a proxy restart, which knocks the recovering server back
 * down. `random` is a parameter so a test gets an exact number.
 */
export function backoffDelayMs(
  attempt: number,
  opts: { baseDelayMs: number; maxDelayMs: number; jitter?: boolean },
  random: () => number = Math.random,
): number {
  const ceiling = Math.min(opts.maxDelayMs, opts.baseDelayMs * 2 ** attempt);
  if (opts.jitter === false) return ceiling;
  return Math.floor(ceiling / 2 + random() * (ceiling / 2));
}

/**
 * Pure: classify + normalise an inbound message into an LTP or Depth event.
 * Payload fields live under `data` per the protocol, but the parser also
 * tolerates a flat shape for resilience across broker adapters.
 *
 * The proxy puts identity on the envelope. Existing nested broker identity
 * takes precedence, with `topic` retained as the final fallback.
 */
export function parseMessage(raw: unknown): { kind: 'ltp'; event: LtpEvent } | { kind: 'depth'; symbol: string; exchange: string; depth: MarketDepth } | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const m = raw as RawMsg & RawData;
  const d: RawData = m.data ?? m;
  const t = parseTopic(m.topic);
  // Empty identity fields must not hide the envelope or legacy topic identity.
  const symbol = d.symbol || m.symbol || t?.symbol || '';
  const exchange = d.exchange || m.exchange || t?.exchange || '';
  if (d.depth && (d.depth.buy || d.depth.sell)) {
    const bids = (d.depth.buy ?? []).map((b) => ({ price: b.price, qty: b.quantity }));
    const asks = (d.depth.sell ?? []).map((a) => ({ price: a.price, qty: a.quantity }));
    const ltp = d.ltp ?? d.last_price ?? (bids[0]?.price ?? 0);
    const timeSec = marketTimeSec(d);
    return { kind: 'depth', symbol, exchange, depth: { bids, asks, ltp,
      ...(Number.isFinite(timeSec) && timeSec > 0 ? { timeSec } : {}),
    } };
  }
  const price = d.ltp ?? d.last_price;
  if (typeof price === 'number') {
    // A quantity the frame lacks stays undefined, which the event reads as absent.
    return { kind: 'ltp', event: { symbol, exchange, ltp: price, ltq: d.last_trade_quantity ?? d.ltq, volume: d.volume, timeSec: marketTimeSec(d) } satisfies LooseOptional<LtpEvent> as LtpEvent };
  }
  return null;
}

/**
 * Connection phase. Not the same thing as `WsState`, which is what a host is
 * told: 'ready' is the only phase in which a data frame may leave, and there is
 * deliberately no phase meaning "transport open and usable", because such a
 * socket does not exist until the handshake is answered.
 */
type Phase = 'idle' | 'connecting' | 'authenticating' | 'ready' | 'backoff' | 'closed' | 'fatal';

export class OpenAlgoWsFeed {
  private readonly _config: OpenAlgoWsConfig;
  private readonly _factory: SocketFactory;
  private _sock: SocketLike | null = null;
  private _phase: Phase = 'idle';
  /**
   * Guards every socket callback. A socket we have abandoned keeps its handlers
   * (a host may still hold the reference and fire them) but a stale one must
   * not schedule a second reconnect for an event we already handled.
   */
  private _epoch = 0;
  private readonly _ltpCbs = new Set<(e: LtpEvent) => void>();
  private readonly _depthCbs = new Set<(symbol: string, exchange: string, depth: MarketDepth) => void>();
  private readonly _stateCbs = new Set<(state: WsState) => void>();
  private readonly _controlCbs = new Set<(msg: WsControlMessage) => void>();
  private readonly _orderCbs = new Set<(e: OrderUpdateEvent) => void>();
  private _ordersSubscribed = false;
  /**
   * Desired subscription state, keyed by mode:symbol:exchange, replayed in full
   * once each connection authenticates. This replaces the old frame queue on
   * purpose: a queue can hold two frames for one key (one queued, one replayed)
   * and grows without bound during a long outage, while desired state is
   * inherently deduplicated and bounded by the number of subscriptions.
   */
  private readonly _subs = new Map<string, { mode: WsMode; symbol: string; exchange: string; depthLevel?: number | undefined }>();
  /** Last sequence seen per topic. Only ever populated by a server that numbers frames. */
  private readonly _seq = new Map<string, number>();
  private _userClosed = false;
  /** The server refused the key. Retrying that on a timer gets it blocked, so we do not. */
  private _fatal = false;
  private _everAuthed = false;
  private _attempts = 0;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _authTimer: ReturnType<typeof setTimeout> | null = null;
  private _liveTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly _rc: { enabled: boolean; baseDelayMs: number; maxDelayMs: number; maxAttempts: number; jitter: boolean; random: () => number };
  private readonly _auth: { requireAck: boolean; ackTimeoutMs: number };
  private readonly _hbTimeoutMs: number;
  private readonly _hbProbeMs: number;

  public constructor(config: OpenAlgoWsConfig) {
    this._config = config;
    const f = config.socketFactory
      ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);
    this._factory = f;
    const r = config.reconnect ?? {};
    this._rc = {
      enabled: r.enabled ?? true,
      baseDelayMs: r.baseDelayMs ?? 1000,
      maxDelayMs: r.maxDelayMs ?? 30000,
      maxAttempts: r.maxAttempts ?? Infinity,
      jitter: r.jitter ?? true,
      random: r.random ?? Math.random,
    };
    const a = config.auth ?? {};
    this._auth = { requireAck: a.requireAck ?? true, ackTimeoutMs: a.ackTimeoutMs ?? 5000 };
    this._hbTimeoutMs = config.heartbeat?.timeoutMs ?? 45000;
    this._hbProbeMs = config.heartbeat?.probeMs ?? 5000;
  }

  /**
   * Open the socket. Also the deliberate way back from a refused key or an
   * earlier `close()`: both are user-intent states, and only user intent clears
   * them, so this is the one way out of the fatal state back to connecting.
   */
  public connect(): void {
    if (this._sock !== null) return;
    this._userClosed = false;
    this._fatal = false;
    this._attempts = 0;
    if (this._reconnectTimer !== null) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    this._openSocket();
  }

  /** True once the handshake is acknowledged: the only time data frames go out. */
  public isReady(): boolean {
    return this._phase === 'ready';
  }

  private _openSocket(): void {
    if (this._sock !== null) return;
    this._phase = 'connecting';
    this._emitState('connecting');
    const sock = this._factory(this._config.url);
    const token = ++this._epoch;
    sock.onmessage = (ev): void => { if (token === this._epoch) this._dispatch(ev.data); };
    sock.onopen = (): void => { if (token === this._epoch) this._onOpen(); };
    sock.onclose = (): void => { if (token === this._epoch) this._onClose(); };
    sock.onerror = (): void => { if (token === this._epoch) this._emitState('error'); };
    this._sock = sock;
    // Some sockets connect synchronously (readyState OPEN) before onopen fires.
    if (sock.readyState === 1) this._onOpen();
  }

  /** Subscribe to socket lifecycle (connecting / open / closed / error). */
  public onState(cb: (state: WsState) => void): () => void {
    this._stateCbs.add(cb);
    return () => this._stateCbs.delete(cb);
  }

  /** Subscribe to control frames: auth / subscribe acks, server errors, client warnings. */
  public onControl(cb: (msg: WsControlMessage) => void): () => void {
    this._controlCbs.add(cb);
    return () => this._controlCbs.delete(cb);
  }

  // Every host callback goes through `dispatch`, as on the chart bus: a throw
  // reaches neither the other listeners nor the state change that emitted.
  private _emitState(s: WsState): void {
    dispatch(this._stateCbs, s);
  }

  private _emitControl(msg: WsControlMessage): void {
    dispatch(this._controlCbs, msg);
  }

  private _warn(code: string, message: string): void {
    const w: WsClientWarning = { type: 'client_warning', code, message };
    this._emitControl(w);
  }

  /**
   * Transport open. Send the handshake and nothing else: the subscription
   * replay waits for the acknowledgement, because a proxy that discards
   * pre-auth frames would swallow it and leave the chart silent.
   */
  private _onOpen(): void {
    if (this._phase !== 'connecting') return;
    this._phase = 'authenticating';
    this._sock?.send(formatAuthenticate(this._config.apiKey));
    if (!this._auth.requireAck) {
      // Declared, not assumed: the caller has told us this proxy answers
      // nothing, so the gap in the guarantee is stated once per connection
      // rather than papered over.
      this._warn('AUTH_UNACKNOWLEDGED', 'proceeding without an auth acknowledgement (auth.requireAck is false)');
      this._onAuthenticated();
      return;
    }
    this._authTimer = later(
      () => this._failConnection('AUTH_TIMEOUT', `no auth acknowledgement within ${this._auth.ackTimeoutMs}ms`),
      this._auth.ackTimeoutMs,
    );
  }

  private _onAuthenticated(): void {
    if (this._phase !== 'authenticating') return;
    this._clearTimer('auth');
    this._phase = 'ready';
    // Only an authenticated session proves the endpoint is usable. Resetting on
    // transport open let a server that accepts and immediately drops spin a hot
    // reconnect loop at the base delay forever.
    this._attempts = 0;
    this._armLiveness();
    // Replay before announcing 'open': a host that subscribes from its onState
    // handler would otherwise be iterated into the replay and get two frames.
    for (const s of Array.from(this._subs.values())) {
      this._sock?.send(formatSubscribe(s.mode, s.symbol, s.exchange, s.depthLevel));
    }
    if (this._ordersSubscribed) this._sock?.send(formatSubscribeOrders());
    if (this._everAuthed) {
      // The stream carries no sequence, so nothing can tell us what was missed
      // across the gap. Every reconnect is therefore treated as a gap, which is
      // the only safe assumption: the forming bar is the one datum guaranteed
      // to be wrong now.
      this._seq.clear();
      this._warn('STREAM_RESYNC', 'reconnected: ticks were missed and the forming bar is stale, refetch it');
    }
    this._everAuthed = true;
    this._emitState('open');
  }

  private _onAuthFailed(raw: unknown): void {
    const message = typeof raw === 'object' && raw !== null && typeof (raw as { message?: unknown }).message === 'string'
      ? (raw as { message: string }).message
      : 'authentication refused';
    // The server said no. The same key retried on a timer will be refused again
    // and get rate limited on the way, and it is the one failure a human has to
    // fix, so this does not auto-reconnect. connect() clears it.
    this._fatal = true;
    this._warn('AUTH_FAILED', message);
    this._emitState('error');
    this._dropSocket();
    this._clearTimer('auth');
    this._clearTimer('live');
    this._phase = 'fatal';
    this._emitState('closed');
  }

  /** A failure we detected ourselves: drop the socket and back off as if it had closed. */
  private _failConnection(code: string, message: string): void {
    this._warn(code, message);
    this._emitState('error');
    this._dropSocket();
    this._clearTimer('auth');
    this._clearTimer('live');
    this._phase = 'idle';
    this._emitState('closed');
    this._maybeReconnect();
  }

  private _onClose(): void {
    this._sock = null;
    this._clearTimer('auth');
    this._clearTimer('live');
    this._phase = this._userClosed ? 'closed' : 'idle';
    this._emitState('closed');
    this._maybeReconnect();
  }

  /** Schedule a reconnect with jittered exponential backoff unless the user closed us. */
  private _maybeReconnect(): void {
    if (this._userClosed || this._fatal || !this._rc.enabled) return;
    if (this._attempts >= this._rc.maxAttempts) {
      // Giving up silently leaves a host waiting on a socket that is never
      // coming back. Default maxAttempts is Infinity, so this only fires for a
      // caller who asked for a limit.
      if (this._phase !== 'fatal') {
        this._phase = 'fatal';
        this._warn('RECONNECT_ABANDONED', `gave up after ${this._attempts} attempts; call connect() to retry`);
      }
      return;
    }
    const n = this._attempts++;
    const delay = backoffDelayMs(n, this._rc, this._rc.random);
    this._phase = 'backoff';
    this._emitState('reconnecting');
    this._reconnectTimer = later(() => {
      this._reconnectTimer = null;
      this._sock = null;
      this._openSocket();
    }, delay);
  }

  /**
   * Send a data frame, or hold it back until the handshake is answered.
   *
   * Held frames are not queued: the caller's intent is already recorded in
   * `_subs` / `_ordersSubscribed`, and that is what gets replayed.
   */
  private _sendGated(msg: string): void {
    if (this._phase === 'ready' && this._sock !== null) this._sock.send(msg);
  }

  /**
   * Restart the liveness watchdog. A TCP connection routinely stays open after
   * the far end is gone and `onclose` may never fire; left alone that shows a
   * connected badge over a frozen price. Any inbound frame counts, including a
   * ping or a control ack.
   */
  private _armLiveness(): void {
    if (this._hbTimeoutMs <= 0 || this._phase !== 'ready') return;
    this._clearTimer('live');
    this._liveTimer = later(() => this._probeLiveness(), this._hbTimeoutMs);
  }

  /**
   * Silence is not death, so ask before concluding one.
   *
   * OpenAlgo's proxy keeps the connection alive with protocol-level WebSocket
   * pings, which a browser answers itself and never surfaces to JavaScript, and
   * it broadcasts nothing else on a schedule. A quiet symbol out of hours
   * therefore produces no inbound frame at all, and a bare timeout would hang
   * up on a perfectly healthy socket and resubscribe every `timeoutMs` all
   * night. The proxy answers `{ action:'ping' }` with a pong, and a build that
   * does not know the action answers an error, which proves the far end is
   * there just as well: any reply at all rearms the watchdog through
   * `_dispatch`. Only silence to a direct question is death.
   */
  private _probeLiveness(): void {
    if (this._phase !== 'ready' || this._sock === null) return;
    this._sock.send(JSON.stringify({ action: 'ping' }));
    this._liveTimer = later(
      () => this._failConnection('HEARTBEAT_DEAD', `no answer to a liveness ping within ${this._hbProbeMs}ms`),
      this._hbProbeMs,
    );
  }

  private _clearTimer(which: 'auth' | 'live' | 'reconnect'): void {
    const t = which === 'auth' ? this._authTimer : which === 'live' ? this._liveTimer : this._reconnectTimer;
    if (t !== null) clearTimeout(t);
    if (which === 'auth') this._authTimer = null;
    else if (which === 'live') this._liveTimer = null;
    else this._reconnectTimer = null;
  }

  /** Abandon the current socket: stale callbacks are disarmed by the epoch bump. */
  private _dropSocket(): void {
    const s = this._sock;
    this._sock = null;
    this._epoch++;
    if (s === null) return;
    try { s.close(); } catch { /* already closing or closed */ }
  }

  public onLtp(cb: (e: LtpEvent) => void): () => void {
    this._ltpCbs.add(cb);
    return () => this._ltpCbs.delete(cb);
  }

  public onDepth(cb: (symbol: string, exchange: string, depth: MarketDepth) => void): () => void {
    this._depthCbs.add(cb);
    return () => this._depthCbs.delete(cb);
  }

  public subscribe(mode: WsMode, symbol: string, exchange: string, depthLevel?: number): void {
    this._subs.set(`${mode}:${symbol}:${exchange}`, { mode, symbol, exchange, depthLevel });
    this._sendGated(formatSubscribe(mode, symbol, exchange, depthLevel));
  }

  public unsubscribe(mode: WsMode, symbol: string, exchange: string): void {
    this._subs.delete(`${mode}:${symbol}:${exchange}`);
    // Nothing to undo on the wire while gated: this connection never sent the
    // subscribe, and the replay reads the map we just updated.
    this._sendGated(formatUnsubscribe(mode, symbol, exchange));
  }

  /** Subscribe to real-time order updates (fills / cancels / rejections). Account-level; replayed on reconnect. */
  public onOrderUpdate(cb: (e: OrderUpdateEvent) => void): () => void {
    this._orderCbs.add(cb);
    return () => this._orderCbs.delete(cb);
  }

  public subscribeOrders(): void {
    this._ordersSubscribed = true;
    this._sendGated(formatSubscribeOrders());
  }

  public unsubscribeOrders(): void {
    this._ordersSubscribed = false;
    this._sendGated(formatUnsubscribeOrders());
  }

  /**
   * Close intentionally. The instance is reusable afterwards: `connect()` opens
   * a fresh session.
   *
   * Bookkeeping is cleared with the socket because after this call nothing is
   * subscribed, and state that says otherwise is a lie a later reconnect would
   * act on. Event callbacks survive: the caller holds their unsubscribe
   * functions and never asked to drop them.
   */
  public close(): void {
    this._userClosed = true; // intentional: never auto-reconnect after this
    this._clearTimer('reconnect');
    this._clearTimer('auth');
    this._clearTimer('live');
    this._dropSocket();
    this._subs.clear();
    this._ordersSubscribed = false;
    this._seq.clear();
    this._attempts = 0;
    this._everAuthed = false;
    this._fatal = false;
    this._phase = 'closed';
    this._emitState('closed');
  }

  /**
   * Gap check for a numbered stream. Returns false for a duplicate, which is
   * normal right after a resubscribe. Inert when the server sends no sequence,
   * which is the documented OpenAlgo case.
   */
  private _sequenceOk(topic: string, raw: unknown): boolean {
    const seq = readSequence(raw);
    if (seq === undefined) return true;
    const last = this._seq.get(topic);
    if (last !== undefined && seq <= last) return false;
    if (last !== undefined && seq > last + 1) {
      this._warn('SEQUENCE_GAP', `${topic}: ${seq - last - 1} frame(s) missing, the forming bar is suspect`);
    }
    this._seq.set(topic, seq);
    return true;
  }

  private _dispatch(data: string): void {
    let raw: unknown;
    try { raw = JSON.parse(data); } catch { raw = data; } // heartbeats may be plain text
    this._armLiveness(); // any inbound frame proves the far end is still there
    if (isPing(raw)) { this._sock?.send(JSON.stringify({ action: 'pong' })); return; }
    if (this._phase === 'authenticating') {
      const verdict = classifyAuthAck(raw);
      if (verdict !== null) {
        this._emitControl(raw as WsControlMessage); // hosts render the ack, keep surfacing it
        if (verdict === 'ok') this._onAuthenticated();
        else this._onAuthFailed(raw);
        return;
      }
    }
    const orderUpdate = parseOrderUpdate(raw);
    if (orderUpdate !== null) {
      if (!this._sequenceOk('orders', raw)) return;
      dispatch(this._orderCbs, orderUpdate);
      return;
    }
    const parsed = parseMessage(raw);
    if (parsed === null) {
      // Non-market-data frame (auth / subscribe ack, or a server error): surface it.
      if (typeof raw === 'object' && raw !== null) this._emitControl(raw as WsControlMessage);
      return;
    }
    const rawTopic = (raw as RawMsg).topic;
    if (parsed.kind === 'ltp') {
      if (!this._sequenceOk(rawTopic ?? `ltp:${parsed.event.symbol}.${parsed.event.exchange}`, raw)) return;
      dispatch(this._ltpCbs, parsed.event);
    } else {
      if (!this._sequenceOk(rawTopic ?? `depth:${parsed.symbol}.${parsed.exchange}`, raw)) return;
      const { symbol, exchange, depth } = parsed;
      dispatch([...this._depthCbs].map(cb => () => cb(symbol, exchange, depth)), undefined);
    }
  }
}
