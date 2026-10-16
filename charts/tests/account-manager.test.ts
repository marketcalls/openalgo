import { describe, expect, it, vi } from 'vitest';
import { AccountManager, type AccountFeed, type AccountSnapshot, type AccountState } from '../src/trade/account';
import { FakeBroker, type FakeAccountSeed, type FakeBrokerOperation } from '../src/trade/fake-broker';

function deferred<T = void>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const SANDBOX: FakeAccountSeed[] = [
  { id: 'SBX-1', name: 'Sandbox one', mode: 'analyzer', currency: 'INR', balance: 100_000 },
  { id: 'SBX-2', name: 'Sandbox two', mode: 'analyzer', currency: 'INR', balance: 250_000, leverage: 5, maxLeverage: 5 },
  { id: 'LIVE-1', name: 'Live', mode: 'live', currency: 'INR', balance: 9_000_000 },
];

/** A broker whose reads for one account can be held until a test releases them. */
function heldBroker(seeds = SANDBOX) {
  const holds = new Map<string, Array<{ promise: Promise<void>; resolve: () => void }>>();
  let clock = 1_700_000_000;
  const broker = new FakeBroker({
    accounts: seeds,
    now: () => clock,
    latency: (operation: FakeBrokerOperation, accountId?: string) => {
      const queue = holds.get(`${operation}:${accountId ?? ''}`);
      const next = queue?.shift();
      return next?.promise;
    },
  });
  const hold = (operation: FakeBrokerOperation, accountId?: string) => {
    const gate = deferred();
    const key = `${operation}:${accountId ?? ''}`;
    holds.set(key, [...(holds.get(key) ?? []), gate]);
    return gate;
  };
  return { broker, hold, tick: (seconds = 1) => { clock += seconds; } };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

describe('account capability', () => {
  it('reports unsupported, with the reason, when the provider declares no accounts', async () => {
    const legacy = new AccountManager({ feed: new FakeBroker() });
    expect(legacy.getState()).toMatchObject({ status: 'unsupported', reason: 'Account data is not declared by this provider', accounts: [], selectedId: null, snapshot: null });
    expect(await legacy.refresh()).toMatchObject({ ok: false, reason: 'Account data is not declared by this provider' });
    expect(await legacy.select('SBX-1')).toMatchObject({ ok: false });
    const refused = new AccountManager({ feed: new FakeBroker({ accounts: SANDBOX, features: { accounts: false } }) });
    expect(refused.getState()).toMatchObject({ status: 'unsupported', reason: 'Account data is not supported' });
  });

  it('lets a host restriction refuse accounts a provider supports', async () => {
    const manager = new AccountManager({ feed: new FakeBroker({ accounts: SANDBOX }), mode: 'analyzer', features: { accounts: false } });
    expect(manager.getState().status).toBe('unsupported');
    expect((await manager.refresh()).ok).toBe(false);
  });

  it('refuses a feed that declares accounts without the read methods', () => {
    const feed: AccountFeed = { features: { accounts: true } };
    expect(new AccountManager({ feed }).getState()).toMatchObject({ status: 'unsupported', reason: 'Account data is not implemented by this feed' });
  });
});

describe('account listing and selection', () => {
  it('lists only accounts of its own mode, so a sandbox view never shows live balances', async () => {
    const { broker } = heldBroker();
    const sandbox = new AccountManager({ feed: broker, mode: 'analyzer' });
    expect(await sandbox.refresh()).toMatchObject({ ok: true });
    const state = sandbox.getState();
    expect(state.accounts.map(account => account.id)).toEqual(['SBX-1', 'SBX-2']);
    expect(state).toMatchObject({ status: 'ready', selectedId: 'SBX-1', mode: 'analyzer' });
    expect(state.snapshot).toMatchObject({ accountId: 'SBX-1', mode: 'analyzer', balance: 100_000, equity: 100_000, marginUsed: 0, marginAvailable: 100_000 });
    expect(await sandbox.select('LIVE-1')).toMatchObject({ ok: false, reason: 'Account LIVE-1 is not available in analyzer mode' });
    expect(sandbox.selectedAccount()).toBe('SBX-1');
    const live = new AccountManager({ feed: broker, mode: 'live' });
    await live.refresh();
    expect(live.getState().accounts.map(account => account.id)).toEqual(['LIVE-1']);
  });

  it('honours an initial account and keeps the selection across a refresh', async () => {
    const { broker } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer', initialAccount: 'SBX-2' });
    await manager.refresh();
    expect(manager.selectedAccount()).toBe('SBX-2');
    expect(manager.getState().snapshot).toMatchObject({ accountId: 'SBX-2', leverage: 5 });
    await manager.select('SBX-1');
    await manager.refresh();
    expect(manager.selectedAccount()).toBe('SBX-1');
  });

  it('notifies listeners, isolates a throwing listener, and stops after unsubscribe', async () => {
    const { broker } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    const seen: AccountState['status'][] = [];
    manager.subscribe(() => { throw new Error('host bug'); });
    const off = manager.subscribe(state => seen.push(state.status));
    await manager.refresh();
    expect(seen).toContain('loading');
    expect(seen[seen.length - 1]).toBe('ready');
    off();
    await manager.select('SBX-2');
    expect(seen[seen.length - 1]).toBe('ready');
    expect(seen.filter(status => status === 'ready')).toHaveLength(1);
  });
});

describe('stale account responses', () => {
  it('drops a snapshot that answers after the user has switched accounts, and aborts its request', async () => {
    const { broker, hold } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    const signals: AbortSignal[] = [];
    const original = broker.getAccountSnapshot.bind(broker);
    broker.getAccountSnapshot = (id: string, signal: AbortSignal) => { signals.push(signal); return original(id, signal); };
    const slow = hold('snapshot', 'SBX-1');
    const first = manager.select('SBX-1');
    const second = manager.select('SBX-2');
    expect(signals[0].aborted).toBe(true);
    expect(await second).toMatchObject({ ok: true });
    expect(manager.getState()).toMatchObject({ status: 'ready', selectedId: 'SBX-2' });
    slow.resolve();
    expect(await first).toMatchObject({ ok: false, cancelled: true });
    expect(manager.getState().snapshot).toMatchObject({ accountId: 'SBX-2', balance: 250_000 });
  });

  it('ignores a pushed snapshot for another account, an older reading, and a push after the switch', async () => {
    const pushes: Array<(snapshot: AccountSnapshot) => void> = [];
    const unsubscribed = vi.fn();
    const base = (accountId: string, asOf: number, equity: number): AccountSnapshot => ({ accountId, mode: 'analyzer', asOf, equity });
    const feed: AccountFeed = {
      features: { accounts: true },
      listAccounts: async () => [{ id: 'A', mode: 'analyzer' }, { id: 'B', mode: 'analyzer' }],
      getAccountSnapshot: async (id: string) => base(id, 100, id === 'A' ? 10 : 20),
      subscribeAccount: (_id, onSnapshot) => { pushes.push(onSnapshot); return unsubscribed; },
    };
    const manager = new AccountManager({ feed, mode: 'analyzer' });
    await manager.refresh();
    const pushA = pushes[0];
    pushA(base('B', 200, 999));
    pushA(base('A', 99, 1));
    expect(manager.getState().snapshot).toMatchObject({ accountId: 'A', asOf: 100, equity: 10 });
    pushA(base('A', 101, 11));
    expect(manager.getState().snapshot).toMatchObject({ asOf: 101, equity: 11 });
    await manager.select('B');
    expect(unsubscribed).toHaveBeenCalledTimes(1);
    pushA(base('A', 500, 12));
    expect(manager.getState().snapshot).toMatchObject({ accountId: 'B', equity: 20 });
  });

  it('refuses a snapshot from the other ledger instead of showing it', async () => {
    const feed: AccountFeed = {
      features: { accounts: true },
      listAccounts: async () => [{ id: 'A', mode: 'analyzer' }],
      getAccountSnapshot: async () => ({ accountId: 'A', mode: 'live', asOf: 1, equity: 5_000_000 }),
    };
    const manager = new AccountManager({ feed, mode: 'analyzer' });
    expect(await manager.refresh()).toMatchObject({ ok: false });
    expect(manager.getState()).toMatchObject({ status: 'error', snapshot: null });
    expect(manager.getState().reason).toContain('live');
  });

  it('fails closed on an unreadable figure rather than showing a guess', async () => {
    const feed: AccountFeed = {
      features: { accounts: true },
      listAccounts: async () => [{ id: 'A', mode: 'analyzer' }, { id: '', mode: 'analyzer' }, { id: 'X', mode: 'simulated' as never }],
      getAccountSnapshot: async () => ({ accountId: 'A', mode: 'analyzer', asOf: 1, equity: Number.NaN }),
    };
    const manager = new AccountManager({ feed, mode: 'analyzer' });
    await manager.refresh();
    expect(manager.getState().accounts.map(account => account.id)).toEqual(['A']);
    expect(manager.getState()).toMatchObject({ status: 'error', snapshot: null, reason: 'The account snapshot could not be read: equity' });
  });
});

describe('disconnect and reconnect', () => {
  it('keeps the last figures marked stale, then replaces them after reconnecting', async () => {
    const { broker, tick } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    const before = manager.getState().snapshot!;
    broker.disconnect();
    expect(manager.getState()).toMatchObject({ status: 'stale', snapshot: before });
    expect(manager.getState().reason).toContain('connection');
    tick(5);
    expect(await manager.reconnect()).toMatchObject({ ok: false });
    expect(manager.getState().status).toBe('stale');
    broker.reconnect();
    expect(await manager.reconnect()).toMatchObject({ ok: true });
    expect(manager.getState()).toMatchObject({ status: 'ready' });
    expect(manager.getState().snapshot!.asOf).toBeGreaterThan(before.asOf);
    // The resubscribed stream delivers again.
    broker.setMark('SYN', 100);
    await broker.place({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 10, mode: 'analyzer', account: 'SBX-1' });
    expect(manager.getState().snapshot).toMatchObject({ marginUsed: 1000 });
  });

  it('treats a host-reported disconnect the same way and ignores responses from before it', async () => {
    const { broker, hold } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    const slow = hold('snapshot', 'SBX-2');
    const pending = manager.select('SBX-2');
    manager.disconnected();
    slow.resolve();
    expect(await pending).toMatchObject({ ok: false, cancelled: true });
    expect(manager.getState().status).toBe('error');
  });
});

describe('account history reads', () => {
  it('reads positions, executions and order history for the selected account only', async () => {
    const { broker } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    broker.setMark('SYN', 100);
    await broker.place({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 4, mode: 'analyzer', account: 'SBX-1', clientToken: 't1' });
    await broker.place({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 7, mode: 'analyzer', account: 'SBX-2' });
    expect(await manager.positions()).toMatchObject({ ok: true, accountId: 'SBX-1', rows: [{ symbol: 'SYN', netQty: 4, avgPrice: 100 }] });
    const executions = await manager.executions();
    expect(executions).toMatchObject({ ok: true, accountId: 'SBX-1' });
    expect(executions.ok && executions.rows.map(row => row.qty)).toEqual([4]);
    const history = await manager.orderHistory({ symbol: 'SYN' });
    expect(history.ok && history.rows.map(row => [row.accountId, row.order.status, row.clientToken])).toEqual([['SBX-1', 'filled', 't1']]);
  });

  it('cancels a history read when the account changes before it answers', async () => {
    const { broker, hold } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    const slow = hold('executions', 'SBX-1');
    const read = manager.executions();
    await manager.select('SBX-2');
    slow.resolve();
    expect(await read).toMatchObject({ ok: false, cancelled: true });
  });

  it('drops rows that belong to another account', async () => {
    const feed: AccountFeed = {
      features: { accounts: true, executions: true },
      listAccounts: async () => [{ id: 'A', mode: 'analyzer' }],
      getAccountSnapshot: async () => ({ accountId: 'A', mode: 'analyzer', asOf: 1 }),
      getExecutions: async () => [
        { id: 'e1', accountId: 'A', orderId: 'o1', symbol: 'S', side: 'BUY', qty: 1, price: 10, time: 1 },
        { id: 'e2', accountId: 'Z', orderId: 'o2', symbol: 'S', side: 'SELL', qty: 1, price: 10, time: 2 },
        { id: 'e3', accountId: 'A', orderId: 'o3', symbol: 'S', side: 'HOLD' as never, qty: 1, price: 10, time: 3 },
      ],
    };
    const manager = new AccountManager({ feed, mode: 'analyzer' });
    await manager.refresh();
    expect(await manager.executions()).toMatchObject({ ok: true, dropped: 2, rows: [{ id: 'e1' }] });
    expect(await manager.orderHistory()).toMatchObject({ ok: false, unsupported: true, reason: 'Order history is not declared by this provider' });
  });

  it('drops a position row that names another account, and keeps one that names none', async () => {
    const feed: AccountFeed = {
      features: { accounts: true },
      listAccounts: async () => [{ id: 'A', mode: 'analyzer' }],
      getAccountSnapshot: async () => ({ accountId: 'A', mode: 'analyzer', asOf: 1 }),
      getAccountPositions: async () => [
        { symbol: 'S', netQty: 1, avgPrice: 10, accountId: 'A' },
        { symbol: 'T', netQty: 2, avgPrice: 5, accountId: 'Z' },
        { symbol: 'U', netQty: 3, avgPrice: 1 },
      ],
    };
    const manager = new AccountManager({ feed, mode: 'analyzer' });
    await manager.refresh();
    const read = await manager.positions();
    expect(read).toMatchObject({ ok: true, accountId: 'A', dropped: 1 });
    expect(read.ok && read.rows.map(row => row.symbol)).toEqual(['S', 'U']);
  });

  it('gets positions from the simulated provider stamped with their account', async () => {
    const { broker } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    broker.setMark('SYN', 100);
    await broker.place({ symbol: 'SYN', side: 'BUY', type: 'MARKET', qty: 4, mode: 'analyzer', account: 'SBX-1' });
    expect(await manager.positions()).toMatchObject({ ok: true, dropped: 0, rows: [{ symbol: 'SYN', netQty: 4, accountId: 'SBX-1' }] });
  });

  it('stops notifying and aborts reads after destroy', async () => {
    const { broker, hold } = heldBroker();
    const manager = new AccountManager({ feed: broker, mode: 'analyzer' });
    await manager.refresh();
    const listener = vi.fn();
    manager.subscribe(listener);
    const slow = hold('positions', 'SBX-1');
    const read = manager.positions();
    manager.destroy();
    slow.resolve();
    expect(await read).toMatchObject({ ok: false, cancelled: true });
    await flush();
    broker.setMark('SYN', 1);
    expect(listener).not.toHaveBeenCalled();
    expect(await manager.refresh()).toMatchObject({ ok: false });
  });
});
