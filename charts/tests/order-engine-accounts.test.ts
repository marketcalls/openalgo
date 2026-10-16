import { describe, expect, it, vi } from 'vitest';
import { OrderEngine, type BracketReceipt, type OrderEngineOptions, type OrderFeed, type PlaceRequest } from '../src/trade/order-engine';
import { AccountManager } from '../src/trade/account';
import { FakeBroker, type FakeAccountSeed, type FakeBrokerOperation } from '../src/trade/fake-broker';
import { OpenAlgoTradeFeed } from '../src/feed/openalgo-trade';
import type { Order } from '../src/trade/types';

function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

const SEEDS: FakeAccountSeed[] = [
  { id: 'SBX-1', name: 'Sandbox one', mode: 'analyzer', currency: 'INR', balance: 100_000 },
  { id: 'SBX-2', name: 'Sandbox two', mode: 'analyzer', currency: 'INR', balance: 200_000, leverage: 2, maxLeverage: 4 },
  { id: 'LIVE-1', mode: 'live', currency: 'INR', balance: 5_000_000 },
];
const NOW = 1_700_000_000;

function setup(options: { engine?: Partial<OrderEngineOptions>; broker?: ConstructorParameters<typeof FakeBroker>[0] } = {}) {
  const holds = new Map<string, Array<() => Promise<void>>>();
  const broker = new FakeBroker({
    accounts: SEEDS, now: () => NOW,
    latency: (operation: FakeBrokerOperation, accountId?: string) => holds.get(`${operation}:${accountId ?? ''}`)?.shift()?.(),
    ...options.broker,
  });
  broker.setMark('SYN', 100);
  const hold = (operation: FakeBrokerOperation, accountId?: string) => {
    const gate = deferred();
    const key = `${operation}:${accountId ?? ''}`;
    holds.set(key, [...(holds.get(key) ?? []), () => gate.promise]);
    return gate;
  };
  const accounts = new AccountManager({ feed: broker, mode: 'analyzer' });
  const engine = new OrderEngine({
    feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05, freezeQty: 1000 },
    selectedAccount: () => accounts.selectedAccount(), clock: () => NOW, ...options.engine,
  });
  // The order stream is the authority: every status the broker reports reaches the engine,
  // by the client token it echoes when it has one and by broker id otherwise. The row
  // itself carries a bracket leg's entry and role.
  broker.onOrderUpdate((order: Order, info) => engine.onBrokerOrder({ ...order, clientToken: info.clientToken }));
  return { broker, accounts, engine, hold };
}

const market = (extra: Partial<PlaceRequest> = {}): PlaceRequest => ({ symbol: 'SYN', exchange: 'NSE', side: 'BUY', type: 'MARKET', qty: 10, ...extra });

describe('request schema: account, duration, expiry and leverage', () => {
  it('stamps the selected account on an order and sends it to that ledger', async () => {
    const { broker, accounts, engine } = setup();
    await accounts.refresh();
    const placed = await engine.placeOrder(market({ clientToken: 'a1' }));
    expect(placed).toMatchObject({ ok: true });
    expect(engine.orderAccount('a1')).toBe('SBX-1');
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
    expect(broker.accountPositions('SBX-2')).toEqual([]);
    expect(engine.brokerStatus('a1')).toBe('filled');
  });

  it('refuses before sending when no account is selected or the order names a different one', async () => {
    const { broker, accounts, engine } = setup();
    const place = vi.spyOn(broker, 'place');
    expect(await engine.placeOrder(market())).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'No account is selected' });
    await accounts.refresh();
    expect(await engine.placeOrder(market({ account: 'SBX-2' }))).toMatchObject({
      ok: false, intent: 'BLOCKED', reason: 'The order names account SBX-2 but SBX-1 is selected',
    });
    expect(place).not.toHaveBeenCalled();
  });

  it('never drops an account, duration or leverage a provider cannot carry', async () => {
    const legacy = new FakeBroker();
    const place = vi.spyOn(legacy, 'place');
    const engine = new OrderEngine({ feed: legacy, armed: true, constraints: { tickSize: 0.05 } });
    for (const extra of [{ account: 'X' }, { duration: 'IOC' as const }, { leverage: 2 }, { duration: 'GTD' as const, expiresAt: NOW + 60 }]) {
      const result = await engine.placeOrder(market(extra));
      expect(result).toMatchObject({ ok: false, intent: 'BLOCKED' });
      expect(result.reason).toMatch(/not declared by this provider/);
    }
    expect(place).not.toHaveBeenCalled();
    // The legacy route itself is unchanged.
    expect(await engine.placeOrder(market())).toMatchObject({ ok: true });
  });

  it('checks durations against the provider list and expiry against the clock', async () => {
    const { broker, accounts, engine } = setup({ broker: { features: { accounts: true, orderHistory: true, durations: ['DAY', 'GTD'] } } });
    await accounts.refresh();
    const place = vi.spyOn(broker, 'place');
    expect(await engine.placeOrder(market({ duration: 'IOC' }))).toMatchObject({ ok: false, reason: 'Duration IOC is not supported' });
    expect(await engine.placeOrder(market({ duration: 'GTD' }))).toMatchObject({ ok: false, reason: 'A GTD order needs an expiry' });
    expect(await engine.placeOrder(market({ duration: 'GTD', expiresAt: NOW - 1 }))).toMatchObject({ ok: false, reason: 'The expiry is not in the future' });
    expect(await engine.placeOrder(market({ duration: 'DAY', expiresAt: NOW + 60 }))).toMatchObject({ ok: false, reason: 'An expiry needs the GTD duration' });
    expect(await engine.placeOrder(market({ duration: 'SOON' as never }))).toMatchObject({ ok: false, reason: 'Unknown duration SOON' });
    expect(await engine.placeOrder(market({ leverage: 2 }))).toMatchObject({ ok: false, reason: 'Leverage is not declared by this provider' });
    expect(place).not.toHaveBeenCalled();
    const gtd = await engine.placeOrder({ ...market({ duration: 'GTD', expiresAt: NOW + 3600, clientToken: 'g1' }), type: 'LIMIT', price: 95 });
    expect(gtd).toMatchObject({ ok: true });
    const history = await accounts.orderHistory();
    expect(history.ok && history.rows.find(row => row.clientToken === 'g1')).toMatchObject({ duration: 'GTD', expiresAt: NOW + 3600, order: { status: 'working' } });
  });

  it('never lets a cancel rewrite a filled order in the broker history', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    // Without the stream the engine still reads the market order as working.
    broker.muteOrderUpdates(true);
    await engine.placeOrder(market({ clientToken: 'm1' }));
    expect(engine.state('m1')).toBe('working');
    await engine.cancelOrder('m1');
    const history = await accounts.orderHistory();
    expect(history.ok && history.rows.map(row => row.order.status)).toEqual(['filled']);
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
  });

  it('lets the duration change what the broker does with a resting order', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    await engine.placeOrder({ ...market({ duration: 'IOC', clientToken: 'ioc' }), type: 'LIMIT', price: 90 });
    await engine.placeOrder({ ...market({ duration: 'DAY', clientToken: 'day' }), type: 'LIMIT', price: 90 });
    expect(engine.brokerStatus('ioc')).toBe('cancelled');
    expect(engine.brokerStatus('day')).toBe('working');
    expect(broker.orders().filter(order => order.status === 'working')).toHaveLength(1);
  });

  it('carries leverage into the margin a provider reserves, within its limit', async () => {
    const { accounts, engine } = setup();
    await accounts.refresh();
    await accounts.select('SBX-2');
    await engine.placeOrder(market({ qty: 20, leverage: 4 }));
    expect(accounts.getState().snapshot).toMatchObject({ marginUsed: 500 });
    expect(await engine.placeOrder(market({ leverage: 8, clientToken: 'too-high' }))).toMatchObject({ ok: false, intent: 'SETTLED' });
    expect(engine.brokerStatus('too-high')).toBe('rejected');
  });
});

describe('order preview', () => {
  it('is explicit when unsupported and never places anything', async () => {
    const legacy = new FakeBroker();
    const place = vi.spyOn(legacy, 'place');
    const engine = new OrderEngine({ feed: legacy, armed: true, constraints: { tickSize: 0.05 } });
    expect(await engine.previewOrder(market())).toEqual({ ok: false, unsupported: true, reason: 'Order preview is not declared by this provider' });
    const noMethod: OrderFeed = { features: { preview: true }, place: vi.fn(), modify: vi.fn(), cancel: vi.fn() };
    expect(await new OrderEngine({ feed: noMethod, armed: true, constraints: { tickSize: 0.05 } }).previewOrder(market()))
      .toMatchObject({ ok: false, unsupported: true, reason: 'Order preview is not implemented by this feed' });
    expect(place).not.toHaveBeenCalled();
  });

  it('returns the provider figures without claiming the idempotency token', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    const place = vi.spyOn(broker, 'place');
    const preview = await engine.previewOrder(market({ clientToken: 'same' }));
    expect(preview).toMatchObject({ ok: true, preview: { accountId: 'SBX-1', estimatedPrice: 100, estimatedValue: 1000, marginRequired: 1000, marginAvailableAfter: 99_000, currency: 'INR' } });
    expect(place).not.toHaveBeenCalled();
    expect(await engine.placeOrder(market({ clientToken: 'same' }))).toMatchObject({ ok: true });
    const tooLarge = await engine.previewOrder(market({ qty: 999 }));
    expect(tooLarge).toMatchObject({ ok: true, preview: { rejectReason: 'Insufficient margin: 99900.00 required, 99000.00 available' } });
  });

  it('reports a preview stale when the account changes before it answers', async () => {
    const { accounts, engine, hold } = setup();
    await accounts.refresh();
    const slow = hold('preview', 'SBX-1');
    const pending = engine.previewOrder(market());
    await accounts.select('SBX-2');
    slow.resolve();
    expect(await pending).toMatchObject({ ok: false, stale: true });
  });
});

describe('switching accounts during a pending order', () => {
  it('sends nothing when the account changes while the user is confirming', async () => {
    const confirmed = deferred<boolean>();
    const { accounts, engine, broker } = setup({ engine: { armed: false, gate: () => confirmed.promise } });
    await accounts.refresh();
    const place = vi.spyOn(broker, 'place');
    const pending = engine.placeOrder(market({ clientToken: 'switch' }));
    await accounts.select('SBX-2');
    confirmed.resolve(true);
    expect(await pending).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'The account changed before the order was sent; nothing was sent' });
    expect(place).not.toHaveBeenCalled();
    // Nothing left, so the same token is free for a deliberate second attempt.
    expect(await engine.placeOrder(market({ clientToken: 'switch' }))).toMatchObject({ ok: true });
    expect(engine.orderAccount('switch')).toBe('SBX-2');
  });

  it('keeps an order already in flight on the account it was sent for', async () => {
    const { accounts, engine, broker, hold } = setup();
    await accounts.refresh();
    const slow = hold('place', 'SBX-1');
    const pending = engine.placeOrder(market({ clientToken: 'inflight' }));
    await accounts.select('SBX-2');
    slow.resolve();
    expect(await pending).toMatchObject({ ok: true });
    expect(engine.orderAccount('inflight')).toBe('SBX-1');
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
    expect(broker.accountPositions('SBX-2')).toEqual([]);
    expect(accounts.getState().snapshot).toMatchObject({ accountId: 'SBX-2', marginUsed: 0 });
  });

  it('refuses an account from the other ledger before sending, when given the account view', async () => {
    const broker = new FakeBroker({ accounts: SEEDS, now: () => NOW });
    broker.setMark('SYN', 100);
    const live = new AccountManager({ feed: broker, mode: 'live' });
    await live.refresh();
    const place = vi.spyOn(broker, 'place');
    const close = vi.spyOn(broker, 'closePosition');
    const bracket = vi.spyOn(broker, 'placeBracket');
    const engine = new OrderEngine({ feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05 }, selectedAccount: live });
    const reason = 'The selected account LIVE-1 is in live mode, not analyzer';
    expect(await engine.placeOrder(market())).toMatchObject({ ok: false, intent: 'BLOCKED', reason });
    expect(await engine.closePosition({ symbol: 'SYN' })).toMatchObject({ ok: false, intent: 'BLOCKED', reason });
    expect(await engine.placeBracket({ ...market(), stopLoss: 95, takeProfit: 110 })).toMatchObject({ ok: false, reason });
    expect(await engine.previewOrder(market())).toMatchObject({ ok: false, reason });
    expect(place).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
    expect(bracket).not.toHaveBeenCalled();
    expect(broker.accountPositions('LIVE-1')).toEqual([]);
    // A host's own view that lists a live account under a sandbox heading is caught by the account's mode.
    const mixed = { getState: () => ({ ...live.getState(), mode: 'analyzer' as const }) };
    const fooled = new OrderEngine({ feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05 }, selectedAccount: mixed });
    expect(await fooled.placeOrder(market())).toMatchObject({ ok: false, intent: 'BLOCKED', reason });
    expect(place).not.toHaveBeenCalled();
  });

  it('takes the selection from the account view in its own mode, and still sends nothing after a switch while confirming', async () => {
    const broker = new FakeBroker({ accounts: SEEDS, now: () => NOW });
    broker.setMark('SYN', 100);
    const accounts = new AccountManager({ feed: broker, mode: 'analyzer' });
    const confirmed = deferred<boolean>();
    const engine = new OrderEngine({ feed: broker, mode: 'analyzer', constraints: { tickSize: 0.05 }, selectedAccount: accounts, gate: () => confirmed.promise });
    expect(await engine.placeOrder(market())).toMatchObject({ ok: false, reason: 'No account is selected' });
    await accounts.refresh();
    const pending = engine.placeOrder(market({ clientToken: 'view' }));
    await accounts.select('SBX-2');
    confirmed.resolve(true);
    expect(await pending).toMatchObject({ ok: false, reason: 'The account changed before the order was sent; nothing was sent' });
    const armed = new OrderEngine({ feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05 }, selectedAccount: accounts });
    expect(await armed.placeOrder(market({ clientToken: 'view' }))).toMatchObject({ ok: true });
    expect(armed.orderAccount('view')).toBe('SBX-2');
    expect(broker.accountPositions('SBX-2')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
  });

  it('refuses a sandbox order routed to a live account at the broker as well', async () => {
    const broker = new FakeBroker({ accounts: SEEDS, now: () => NOW });
    broker.setMark('SYN', 100);
    await expect(broker.place({ ...market(), mode: 'analyzer', account: 'LIVE-1' })).rejects.toMatchObject({ rejected: true });
    expect(broker.accountPositions('LIVE-1')).toEqual([]);
  });
});

describe('explicit close, partial close and reverse', () => {
  async function long(qty = 10) {
    const s = setup();
    await s.accounts.refresh();
    await s.engine.placeOrder(market({ qty, clientToken: 'open' }));
    return s;
  }

  it('closes natively and never falls back to an opposite order', async () => {
    const legacy = new FakeBroker();
    const place = vi.spyOn(legacy, 'place');
    const engine = new OrderEngine({ feed: legacy, armed: true, constraints: { tickSize: 0.05 } });
    for (const run of [() => engine.closePosition({ symbol: 'SYN' }), () => engine.closePosition({ symbol: 'SYN', qty: 1 }), () => engine.reversePosition({ symbol: 'SYN' })]) {
      const result = await run();
      expect(result).toMatchObject({ ok: false, intent: 'BLOCKED' });
      expect(result.reason).toMatch(/not declared by this provider/);
    }
    const missing: OrderFeed = { features: { close: true }, place: vi.fn(async () => ({ orderId: 'x' })), modify: vi.fn(), cancel: vi.fn() };
    expect(await new OrderEngine({ feed: missing, armed: true, constraints: { tickSize: 0.05 } }).closePosition({ symbol: 'SYN' }))
      .toMatchObject({ ok: false, reason: 'Closing a position is not implemented by this feed' });
    expect(missing.place).not.toHaveBeenCalled();
    expect(place).not.toHaveBeenCalled();
  });

  it('closes a whole position, part of one, and reverses one, each settled by the broker', async () => {
    const { engine, broker } = await long(10);
    const partial = await engine.closePosition({ symbol: 'SYN', exchange: 'NSE', qty: 4, clientToken: 'part' });
    expect(partial).toMatchObject({ ok: true, kind: 'close', intent: 'SETTLED' });
    expect(engine.brokerStatus('part')).toBe('filled');
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 6, avgPrice: 100 }]);
    const reversed = await engine.reversePosition({ symbol: 'SYN', exchange: 'NSE', clientToken: 'flip' });
    expect(reversed).toMatchObject({ ok: true, kind: 'reverse' });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: -6, avgPrice: 100 }]);
    expect(await engine.closePosition({ symbol: 'SYN', exchange: 'NSE', clientToken: 'all' })).toMatchObject({ ok: true });
    expect(broker.accountPositions('SBX-1')).toEqual([]);
    expect(engine.orderKind('flip')).toBe('reverse');
    expect(engine.orderAccount('all')).toBe('SBX-1');
  });

  it('refuses a repeated command token without a second send', async () => {
    const { engine, broker } = await long(10);
    const close = vi.spyOn(broker, 'closePosition');
    await engine.closePosition({ symbol: 'SYN', qty: 2, clientToken: 'once' });
    expect(await engine.closePosition({ symbol: 'SYN', qty: 2, clientToken: 'once' })).toMatchObject({ ok: false, reason: 'duplicate clientToken (idempotent skip)' });
    expect(await engine.reversePosition({ symbol: 'SYN', clientToken: 'open' })).toMatchObject({ ok: false });
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('reports a server rejection as settled and leaves the position alone', async () => {
    const { engine, broker } = await long(10);
    const rejected = await engine.closePosition({ symbol: 'SYN', qty: 25, clientToken: 'big' });
    expect(rejected).toMatchObject({ ok: false, intent: 'SETTLED', state: 'rejected' });
    expect(rejected.reason).toContain('exceeds the open position');
    expect(engine.brokerStatus('big')).toBe('rejected');
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
    expect(await engine.closePosition({ symbol: 'NONE', clientToken: 'flat' })).toMatchObject({ ok: false, intent: 'SETTLED' });
  });

  it('holds an ambiguous close, blocks a second one, and resolves it from the broker book', async () => {
    const { engine, broker } = await long(10);
    const updates: string[] = [];
    broker.onOrderUpdate((_order, info) => updates.push(info.clientToken ?? ''));
    broker.failNext('close', 'lost-response');
    broker.muteOrderUpdates(true);
    const lost = await engine.closePosition({ symbol: 'SYN', qty: 4, clientToken: 'lost' });
    expect(lost).toMatchObject({ ok: false, intent: 'AMBIGUOUS' });
    expect(lost.reason).toContain('may have reached the broker');
    // The broker did apply it; the client cannot know yet.
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 6, avgPrice: 100 }]);
    const close = vi.spyOn(broker, 'closePosition');
    expect(await engine.closePosition({ symbol: 'SYN', qty: 4, clientToken: 'second' })).toMatchObject({
      ok: false, intent: 'BLOCKED', reason: 'A previous close or reverse for SYN is unresolved; reconcile it with the broker first',
    });
    expect(await engine.closePosition({ symbol: 'SYN', qty: 4, clientToken: 'lost' })).toMatchObject({
      ok: false, reason: 'duplicate clientToken: the first attempt was never confirmed and may be live',
    });
    expect(close).not.toHaveBeenCalled();
    // Authoritative reconciliation: the broker's history echoes the token.
    broker.muteOrderUpdates(false);
    const history = await broker.getOrderHistory({ accountId: 'SBX-1' }, new AbortController().signal);
    const row = history.find(entry => entry.clientToken === 'lost')!;
    engine.onBrokerOrder({ id: row.order.id, clientToken: 'lost', status: row.order.status });
    expect(engine.intentState('lost')).toBe('SETTLED');
    expect(engine.brokerStatus('lost')).toBe('filled');
    // The state follows the broker's word, not the guess made when the answer was lost.
    expect(engine.state('lost')).toBe('filled');
    expect(await engine.closePosition({ symbol: 'SYN', qty: 6, clientToken: 'rest' })).toMatchObject({ ok: true });
    expect(broker.accountPositions('SBX-1')).toEqual([]);
    expect(updates).toContain('rest');
  });

  it('holds the position whether or not a command names its exchange', async () => {
    const { engine, broker } = await long(10);
    broker.muteOrderUpdates(true);
    broker.failNext('close', 'lost-response');
    expect(await engine.closePosition({ symbol: 'SYN', qty: 4, clientToken: 'bare' })).toMatchObject({ intent: 'AMBIGUOUS' });
    const close = vi.spyOn(broker, 'closePosition');
    const reverse = vi.spyOn(broker, 'reversePosition');
    const unresolved = { ok: false, intent: 'BLOCKED', reason: 'A previous close or reverse for SYN is unresolved; reconcile it with the broker first' };
    // An omitted exchange is the provider's default, so it may be this very position.
    expect(await engine.closePosition({ symbol: 'SYN', exchange: 'NSE', qty: 4 })).toMatchObject(unresolved);
    expect(await engine.reversePosition({ symbol: 'SYN', exchange: 'NSE' })).toMatchObject(unresolved);
    expect(close).not.toHaveBeenCalled();
    expect(reverse).not.toHaveBeenCalled();
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 6, avgPrice: 100 }]);
  });

  it('holds a position named with its exchange against a command that omits it', async () => {
    const { engine, broker } = await long(10);
    broker.muteOrderUpdates(true);
    broker.failNext('close', 'lost-response');
    expect(await engine.closePosition({ symbol: 'SYN', exchange: 'NSE', qty: 4 })).toMatchObject({ intent: 'AMBIGUOUS' });
    expect(await engine.closePosition({ symbol: 'SYN', qty: 4 })).toMatchObject({ ok: false, intent: 'BLOCKED' });
    // A different exchange named outright is a different position.
    expect(await engine.closePosition({ symbol: 'SYN', exchange: 'BSE', qty: 1 })).toMatchObject({ ok: true });
  });

  it('lets the host release an ambiguous command the broker never received', async () => {
    const { engine, broker } = await long(10);
    broker.failNext('reverse', 'timeout');
    expect(await engine.reversePosition({ symbol: 'SYN', clientToken: 'never' })).toMatchObject({ ok: false, intent: 'AMBIGUOUS' });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 10, avgPrice: 100 }]);
    expect(engine.releaseAmbiguous('open')).toBe(false);
    expect(engine.releaseAmbiguous('never')).toBe(true);
    expect(engine.intentState('never')).toBeUndefined();
    expect(await engine.reversePosition({ symbol: 'SYN', clientToken: 'never' })).toMatchObject({ ok: true });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: -10, avgPrice: 100 }]);
  });

  it('reconciles commands on reconnect instead of assuming them lost', async () => {
    const { engine, broker } = await long(10);
    broker.muteOrderUpdates(true);
    const sent = await engine.closePosition({ symbol: 'SYN', qty: 2, clientToken: 'rc' });
    expect(sent).toMatchObject({ ok: true, intent: 'SUBMITTED' });
    engine.beginReconcile();
    expect(engine.intentState('rc')).toBe('RECONCILING');
    const book = new Set((await broker.getOrderHistory({ accountId: 'SBX-1' }, new AbortController().signal)).map(row => row.order.id));
    engine.onReconnect(book);
    expect(engine.intentState('rc')).toBe('ACKNOWLEDGED');
    engine.beginReconcile();
    engine.onReconnect(new Set());
    expect(engine.intentState('rc')).toBe('AMBIGUOUS');
  });

  it('asks for confirmation of a command when not set to send immediately', async () => {
    const { accounts, broker } = setup();
    await accounts.refresh();
    const confirmCommand = vi.fn(() => false);
    const engine = new OrderEngine({ feed: broker, mode: 'analyzer', constraints: { tickSize: 0.05 }, selectedAccount: () => accounts.selectedAccount(), confirmCommand });
    const close = vi.spyOn(broker, 'closePosition');
    expect(await engine.closePosition({ symbol: 'SYN', clientToken: 'ask' })).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'not confirmed' });
    expect(confirmCommand).toHaveBeenCalledWith({ kind: 'close', request: expect.objectContaining({ symbol: 'SYN', account: 'SBX-1' }) });
    expect(close).not.toHaveBeenCalled();
    const unconfigured = new OrderEngine({ feed: broker, mode: 'analyzer', constraints: { tickSize: 0.05 }, selectedAccount: () => accounts.selectedAccount() });
    expect(await unconfigured.reversePosition({ symbol: 'SYN' })).toMatchObject({ ok: false, reason: 'not confirmed' });
  });

  it('honours a host lock on writes for commands too', async () => {
    const { accounts, broker } = setup();
    await accounts.refresh();
    let locked = true;
    const engine = new OrderEngine({ feed: broker, mode: 'analyzer', armed: true, constraints: { tickSize: 0.05, lotSize: 5 },
      selectedAccount: () => accounts.selectedAccount(), capabilities: () => ({ place: !locked, orderTypes: ['LIMIT'] }) });
    expect(await engine.closePosition({ symbol: 'SYN' })).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'Placing orders is not supported' });
    locked = false;
    expect(await engine.closePosition({ symbol: 'SYN', qty: 3 })).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'quantity 3 is not a multiple of lot size 5' });
    // An order-type list describes new orders; a native close has no order type of its own.
    expect(await engine.closePosition({ symbol: 'SYN', clientToken: 'typeless' })).toMatchObject({ ok: false, intent: 'SETTLED' });
  });
});

describe('a dropped connection', () => {
  it('blocks what is sent while it is down, so nothing is held ambiguous and the same token goes out later', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    await engine.placeOrder(market({ qty: 50, clientToken: 'open' }));
    broker.disconnect();
    const close = await engine.closePosition({ symbol: 'SYN', qty: 20, clientToken: 'down' });
    expect(close).toMatchObject({ ok: false, kind: 'close', intent: 'BLOCKED' });
    expect(close.reason).not.toContain('may have reached the broker');
    expect(await engine.reversePosition({ symbol: 'SYN', clientToken: 'down-flip' })).toMatchObject({ ok: false, intent: 'BLOCKED' });
    expect(await engine.placeOrder(market({ clientToken: 'down-buy' }))).toMatchObject({ ok: false, intent: 'BLOCKED' });
    expect(await engine.placeBracket({ ...market({ clientToken: 'down-br' }), stopLoss: 95, takeProfit: 110 })).toMatchObject({ ok: false, intent: 'BLOCKED' });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 50, avgPrice: 100 }]);
    broker.reconnect();
    expect(await engine.closePosition({ symbol: 'SYN', qty: 20, clientToken: 'down' })).toMatchObject({ ok: true, intent: 'SETTLED' });
    expect(await engine.reversePosition({ symbol: 'SYN', clientToken: 'down-flip' })).toMatchObject({ ok: true });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: -30, avgPrice: 100 }]);
  });

  it('leaves a modify or cancel sent while it is down where the order was', async () => {
    const errors: string[] = [];
    const { accounts, engine, broker } = setup({ engine: { minModifyIntervalMs: 0, onValidationError: reason => errors.push(reason) } });
    await accounts.refresh();
    await engine.placeOrder({ ...market({ clientToken: 'rest' }), type: 'LIMIT', price: 90 });
    broker.disconnect();
    await engine.cancelOrder('rest');
    engine.requestModify('rest', 91);
    await new Promise(done => setTimeout(done, 0));
    expect([engine.state('rest'), engine.intentState('rest'), engine.brokerStatus('rest')]).toEqual(['working', 'ACKNOWLEDGED', 'working']);
    expect(errors).toHaveLength(2);
    expect(broker.orders().find(order => order.status === 'working')).toMatchObject({ price: 90 });
  });

  it('keeps a call already out when it drops ambiguous, because a client cannot tell that from a lost answer', async () => {
    const { accounts, engine, broker, hold } = setup();
    await accounts.refresh();
    await engine.placeOrder(market({ qty: 50 }));
    const slow = hold('close', 'SBX-1');
    const pending = engine.closePosition({ symbol: 'SYN', qty: 20, clientToken: 'out' });
    broker.disconnect();
    slow.resolve();
    expect(await pending).toMatchObject({ ok: false, intent: 'AMBIGUOUS' });
    expect(broker.accountPositions('SBX-1')).toEqual([{ symbol: 'SYN', netQty: 50, avgPrice: 100 }]);
  });
});

describe('an ambiguous write the broker later reports', () => {
  const resting = (clientToken: string): PlaceRequest => ({ ...market({ clientToken }), type: 'LIMIT', price: 90 });

  it('becomes a live order that can be modified and cancelled, and is never pruned as settled', async () => {
    const { accounts, engine, broker } = setup({ engine: { maxSettledOrders: 0, minModifyIntervalMs: 0 } });
    await accounts.refresh();
    broker.muteOrderUpdates(true);
    broker.failNext('place', 'lost-response');
    expect(await engine.placeOrder(resting('L1'))).toMatchObject({ ok: false, intent: 'AMBIGUOUS', state: 'rejected' });
    const live = broker.orders().find(order => order.status === 'working')!;
    broker.muteOrderUpdates(false);

    engine.onBrokerOrder({ id: live.id, clientToken: 'L1', status: 'working' });
    // State, intent and the broker's word agree, and with no settled rows kept
    // the row is still here: a live order has not settled.
    expect([engine.state('L1'), engine.intentState('L1'), engine.brokerStatus('L1')]).toEqual(['working', 'ACKNOWLEDGED', 'working']);

    engine.requestModify('L1', 91);
    await new Promise(done => setTimeout(done, 0));
    expect(broker.orders().find(order => order.id === live.id)?.price).toBe(91);
    const cancel = vi.spyOn(broker, 'cancel');
    await engine.cancelOrder('L1');
    expect(cancel).toHaveBeenCalledWith(live.id);
    expect(broker.orders().some(order => order.id === live.id)).toBe(false);
  });

  it('routes the fills of an adopted order and settles it from them', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    broker.muteOrderUpdates(true);
    broker.failNext('place', 'lost-response');
    await engine.placeOrder(resting('L2'));
    const live = broker.orders().find(order => order.status === 'working')!;
    broker.muteOrderUpdates(false);
    engine.onBrokerOrder({ id: live.id, clientToken: 'L2', status: 'working' });
    broker.fill(live.id);
    expect([engine.state('L2'), engine.intentState('L2'), engine.brokerStatus('L2')]).toEqual(['filled', 'SETTLED', 'filled']);
  });

  it('brings back a row a snapshot missed once the broker reports it working', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    await engine.placeOrder(resting('S1'));
    engine.beginReconcile();
    engine.onReconnect(new Set());
    expect([engine.state('S1'), engine.intentState('S1')]).toEqual(['stale', 'AMBIGUOUS']);
    const live = broker.orders().find(order => order.status === 'working')!;
    engine.onBrokerOrder({ id: live.id, clientToken: 'S1', status: 'working' });
    expect([engine.state('S1'), engine.intentState('S1')]).toEqual(['working', 'ACKNOWLEDGED']);
    await engine.cancelOrder('S1');
    expect([engine.state('S1'), engine.brokerStatus('S1')]).toEqual(['cancelled', 'cancelled']);
  });

  it('keeps a row the broker reports as pending, not yet working, cancellable', async () => {
    const feed: OrderFeed = { place: vi.fn(async () => { throw new Error('socket reset'); }), modify: vi.fn(), cancel: vi.fn(async () => {}) };
    const engine = new OrderEngine({ feed, armed: true, constraints: { tickSize: 0.05 } });
    await engine.placeOrder(resting('P1'));
    expect(engine.intentState('P1')).toBe('AMBIGUOUS');
    engine.onBrokerOrder({ id: 'X9', clientToken: 'P1', status: 'pending' });
    expect([engine.state('P1'), engine.intentState('P1'), engine.brokerStatus('P1')]).toEqual(['working', 'ACKNOWLEDGED', 'pending']);
    await engine.cancelOrder('P1');
    expect(feed.cancel).toHaveBeenCalledWith('X9');
  });
});

describe('provider-native brackets', () => {
  it('places the entry and both legs as one command, with native one-cancels-other', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    const bracket = vi.spyOn(broker, 'placeBracket');
    const result = await engine.placeBracket({ ...market({ clientToken: 'br' }), stopLoss: 95.02, takeProfit: 110 });
    expect(result).toMatchObject({ ok: true, kind: 'bracket', legs: { stopLoss: 'br:stop', takeProfit: 'br:target' } });
    expect(bracket).toHaveBeenCalledWith(expect.objectContaining({ legClientTokens: { stopLoss: 'br:stop', takeProfit: 'br:target' } }));
    expect(engine.orderKind('br:stop')).toBe('bracket-stop');
    // The stream described both legs while the command was out; those first reports are kept.
    expect([engine.brokerStatus('br:stop'), engine.brokerStatus('br:target')]).toEqual(['working', 'working']);
    const legs = broker.orders().filter(order => order.parentId !== undefined);
    expect(legs.map(order => [order.role, order.type, order.triggerPrice ?? order.price])).toEqual([['sl', 'SL-M', 95], ['tp', 'LIMIT', 110]]);
    const target = legs.find(order => order.role === 'tp')!;
    broker.fill(target.id);
    expect(engine.brokerStatus('br:target')).toBe('filled');
    expect(engine.brokerStatus('br:stop')).toBe('cancelled');
    expect(broker.accountPositions('SBX-1')).toEqual([]);
  });

  const entry = (clientToken: string) => ({ ...market({ clientToken }), type: 'LIMIT' as const, price: 99, stopLoss: 95, takeProfit: 110 });

  it('adopts the legs of a bracket whose answer was lost from the broker history, in any order', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    broker.muteOrderUpdates(true);
    broker.failNext('bracket', 'lost-response');
    expect(await engine.placeBracket(entry('bx'))).toMatchObject({ ok: false, kind: 'bracket', intent: 'AMBIGUOUS' });
    expect(engine.bracketLegs('bx')).toBeUndefined();
    broker.muteOrderUpdates(false);

    const history = await broker.getOrderHistory({ accountId: 'SBX-1' }, new AbortController().signal);
    expect(history.map(row => row.clientToken)).toEqual(['bx:target', 'bx:stop', 'bx']);
    // Newest first, so each leg arrives before its entry: its own token finds it.
    for (const row of history) engine.onBrokerOrder({ ...row.order, clientToken: row.clientToken });
    expect(engine.bracketLegs('bx')).toEqual({ stopLoss: 'bx:stop', takeProfit: 'bx:target' });
    expect([engine.orderKind('bx:stop'), engine.orderKind('bx:target')]).toEqual(['bracket-stop', 'bracket-target']);
    expect([engine.state('bx'), engine.intentState('bx'), engine.brokerStatus('bx')]).toEqual(['working', 'ACKNOWLEDGED', 'working']);
    expect([engine.state('bx:stop'), engine.intentState('bx:stop'), engine.brokerStatus('bx:stop')]).toEqual(['working', 'ACKNOWLEDGED', 'pending']);

    // From here the legs are live orders: an entry fill starts them, and a stop fill
    // settles the stop and cancels the target, all reaching the engine.
    broker.fill(history[2].order.id);
    expect(engine.brokerStatus('bx:target')).toBe('working');
    broker.fill(history[1].order.id);
    expect([engine.state('bx:stop'), engine.brokerStatus('bx:stop')]).toEqual(['filled', 'filled']);
    expect([engine.state('bx:target'), engine.brokerStatus('bx:target')]).toEqual(['cancelled', 'cancelled']);
    expect(broker.accountPositions('SBX-1')).toEqual([]);
  });

  it('adopts the legs from the order stream when only the answer was lost, and cancels one on request', async () => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    broker.failNext('bracket', 'lost-response');
    // The stream reported the entry before the answer was lost, so the command is known live.
    const result = await engine.placeBracket(entry('bs'));
    expect(result).toMatchObject({ ok: true, kind: 'bracket', legs: { stopLoss: 'bs:stop', takeProfit: 'bs:target' } });
    const target = broker.orders().find(order => order.role === 'tp')!;
    const cancel = vi.spyOn(broker, 'cancel');
    await engine.cancelOrder('bs:target');
    expect(cancel).toHaveBeenCalledWith(target.id);
    expect(engine.brokerStatus('bs:target')).toBe('cancelled');
    expect(broker.orders().some(order => order.id === target.id)).toBe(false);
  });

  it.each([
    ['newest first, as the history lists them', <T>(rows: readonly T[]) => [...rows]],
    ['oldest first', <T>(rows: readonly T[]) => [...rows].reverse()],
  ])('adopts legs by their entry and role from a provider that echoes no leg token, %s', async (_order, arrange) => {
    const { accounts, engine, broker } = setup();
    await accounts.refresh();
    broker.muteOrderUpdates(true);
    broker.failNext('bracket', 'timeout');
    // A timeout applies nothing, so this one has no legs anywhere.
    expect(await engine.placeBracket(entry('bt'))).toMatchObject({ intent: 'AMBIGUOUS' });
    expect(broker.orders()).toHaveLength(0);
    broker.failNext('bracket', 'lost-response');
    expect(await engine.placeBracket(entry('bp'))).toMatchObject({ intent: 'AMBIGUOUS' });
    const history = await broker.getOrderHistory({ accountId: 'SBX-1' }, new AbortController().signal);
    expect(history.map(row => row.order.role ?? 'entry')).toEqual(['tp', 'sl', 'entry']);
    // Only the entry echoes a token; each leg names nothing but its entry and role.
    for (const row of arrange(history)) {
      engine.onBrokerOrder({ ...row.order, clientToken: row.order.parentId === undefined ? row.clientToken : undefined });
    }
    expect(engine.bracketLegs('bp')).toEqual({ stopLoss: 'bp:stop', takeProfit: 'bp:target' });
    expect([engine.orderKind('bp:stop'), engine.orderKind('bp:target')]).toEqual(['bracket-stop', 'bracket-target']);
    expect([engine.state('bp'), engine.intentState('bp'), engine.brokerStatus('bp')]).toEqual(['working', 'ACKNOWLEDGED', 'working']);
    for (const leg of ['bp:stop', 'bp:target']) {
      expect([engine.state(leg), engine.intentState(leg), engine.brokerStatus(leg)]).toEqual(['working', 'ACKNOWLEDGED', 'pending']);
    }
    expect(engine.bracketLegs('bt')).toBeUndefined();

    // Each leg is bound to its own broker order: cancelling the target cancels that
    // order, and the entry's fill starts the stop the engine holds.
    broker.muteOrderUpdates(false);
    const [target, stop, parent] = history.map(row => row.order.id);
    const cancel = vi.spyOn(broker, 'cancel');
    await engine.cancelOrder('bp:target');
    expect(cancel).toHaveBeenCalledWith(target);
    expect([engine.state('bp:target'), engine.brokerStatus('bp:target')]).toEqual(['cancelled', 'cancelled']);
    broker.fill(parent);
    expect(engine.brokerStatus('bp:stop')).toBe('working');
    broker.fill(stop);
    expect([engine.state('bp:stop'), engine.brokerStatus('bp:stop')]).toEqual(['filled', 'filled']);
    expect(broker.accountPositions('SBX-1')).toEqual([]);
  });

  it('holds legs the stream reports before the receipt names their entry, and applies the latest word', async () => {
    const receipt = deferred<BracketReceipt>();
    const cancel = vi.fn(async () => {});
    const feed: OrderFeed = { features: { brackets: true }, place: vi.fn(), modify: vi.fn(), cancel, placeBracket: vi.fn(() => receipt.promise) };
    const engine = new OrderEngine({ feed, armed: true, constraints: { tickSize: 0.05 } });
    const placed = engine.placeBracket(entry('bh'));
    engine.onBrokerOrder({ id: 'S1', parentId: 'E1', role: 'sl', status: 'pending' });
    engine.onBrokerOrder({ id: 'T1', parentId: 'E1', role: 'tp', status: 'pending' });
    engine.onBrokerOrder({ id: 'S1', parentId: 'E1', role: 'sl', status: 'working' });
    expect(engine.bracketLegs('bh')).toBeUndefined();
    // The receipt names the entry and neither leg.
    receipt.resolve({ orderId: 'E1' });
    expect(await placed).toMatchObject({ ok: true, kind: 'bracket', legs: { stopLoss: 'bh:stop', takeProfit: 'bh:target' } });
    expect([engine.brokerStatus('bh:stop'), engine.brokerStatus('bh:target')]).toEqual(['working', 'pending']);
    await engine.cancelOrder('bh:target');
    expect(cancel).toHaveBeenCalledWith('T1');
  });

  it('holds no leg row while no bracket it could belong to is waiting for its entry', async () => {
    const feed: OrderFeed = {
      features: { brackets: true }, place: vi.fn(), modify: vi.fn(), cancel: vi.fn(async () => {}),
      placeBracket: vi.fn(async (): Promise<BracketReceipt> => ({ orderId: 'E1' })),
    };
    const engine = new OrderEngine({ feed, armed: true, constraints: { tickSize: 0.05 } });
    // Reported before this engine sent any bracket, so it is some other session's leg.
    engine.onBrokerOrder({ id: 'S1', parentId: 'E1', role: 'sl', status: 'working' });
    expect(await engine.placeBracket(entry('bn'))).toMatchObject({ ok: true, kind: 'bracket' });
    expect(engine.bracketLegs('bn')).toBeUndefined();
  });

  it('claims the leg tokens with the entry token, and frees all three only when nothing was sent', async () => {
    const offline = Object.assign(new Error('offline'), { preflight: true });
    const placeBracket = vi.fn(async (): Promise<BracketReceipt> => { throw offline; });
    const feed: OrderFeed = { features: { brackets: true }, place: vi.fn(async () => ({ orderId: 'P1' })), modify: vi.fn(), cancel: vi.fn(), placeBracket };
    const engine = new OrderEngine({ feed, armed: true, constraints: { tickSize: 0.05 } });
    expect(await engine.placeOrder({ ...market({ clientToken: 'bq:stop' }), type: 'LIMIT', price: 99 })).toMatchObject({ ok: true });
    expect(await engine.placeBracket(entry('bq'))).toMatchObject({ ok: false, kind: 'bracket', reason: 'duplicate clientToken (idempotent skip)' });
    expect(await engine.placeBracket(entry('bf'))).toMatchObject({ ok: false, intent: 'BLOCKED', reason: 'offline' });
    placeBracket.mockImplementationOnce(async () => { throw new Error('socket reset'); });
    expect(await engine.placeBracket(entry('bf'))).toMatchObject({ ok: false, intent: 'AMBIGUOUS' });
    expect(await engine.placeOrder({ ...market({ clientToken: 'bf:target' }), type: 'LIMIT', price: 99 }))
      .toMatchObject({ ok: false, reason: 'duplicate clientToken (idempotent skip)' });
    // The host has shown the bracket never arrived, so its legs' tokens are free with it.
    expect(engine.releaseAmbiguous('bf')).toBe(true);
    placeBracket.mockImplementationOnce(async () => ({ orderId: 'E1', stopLossId: 'S1', takeProfitId: 'T1' }));
    expect(await engine.placeBracket(entry('bf'))).toMatchObject({ ok: true, legs: { stopLoss: 'bf:stop', takeProfit: 'bf:target' } });
    expect(placeBracket).toHaveBeenCalledTimes(3);
  });

  it('refuses legs on the wrong side, and brackets a provider does not declare', async () => {
    const { accounts, engine, broker } = setup({ broker: { features: { accounts: true, brackets: false } } });
    await accounts.refresh();
    const bracket = vi.spyOn(broker, 'placeBracket');
    expect(await engine.placeBracket({ ...market(), stopLoss: 110, takeProfit: 95 })).toMatchObject({
      ok: false, intent: 'BLOCKED', reason: 'The stop and target are on the wrong side of the entry',
    });
    expect(await engine.placeBracket({ ...market(), type: 'LIMIT', price: 100, stopLoss: 101, takeProfit: 120 })).toMatchObject({ ok: false });
    expect(await engine.placeBracket({ ...market(), stopLoss: 95, takeProfit: 110 })).toMatchObject({ ok: false, reason: 'Bracket placement is not supported' });
    expect(bracket).not.toHaveBeenCalled();
  });
});

describe('the OpenAlgo route', () => {
  it('refuses fields its placeorder payload has no place for, before any network call', async () => {
    const fetchImpl = vi.fn();
    const feed = new OpenAlgoTradeFeed({ baseUrl: 'http://x', apiKey: 'k', fetchImpl: fetchImpl as unknown as typeof fetch, verifyMode: 'off' });
    for (const extra of [{ account: 'A' }, { duration: 'DAY' as const }, { expiresAt: NOW }, { leverage: 2 }]) {
      await expect(feed.place({ ...market(extra), mode: 'live' })).rejects.toMatchObject({ preflight: true });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
