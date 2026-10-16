import { describe, expect, it, vi } from 'vitest';
import { FakeBroker, type FakeAccountSeed } from '../src/trade/fake-broker';
import { isBrokerRejection } from '../src/trade/order-engine';
import type { AccountSnapshot } from '../src/trade/account';

const signal = () => new AbortController().signal;
const SEEDS: FakeAccountSeed[] = [
  { id: 'A', name: 'Sandbox A', mode: 'analyzer', currency: 'INR', balance: 50_000 },
  { id: 'L', mode: 'live', currency: 'INR', balance: 1_000_000 },
];

describe('FakeBroker without accounts', () => {
  it('honours a dropped connection as well, failing each write as never sent', async () => {
    const broker = new FakeBroker();
    broker.disconnect();
    await expect(broker.place({ symbol: 'S', side: 'BUY', type: 'LIMIT', price: 1, qty: 5, mode: 'live' })).rejects.toMatchObject({ preflight: true });
    expect(broker.orders()).toEqual([]);
    broker.reconnect();
    expect(await broker.place({ symbol: 'S', side: 'BUY', type: 'LIMIT', price: 1, qty: 5, mode: 'live' })).toEqual({ orderId: 'B1' });
  });

  it('keeps the original book simulation and declares none of the newer operations', async () => {
    const broker = new FakeBroker();
    expect(broker.features).toBeUndefined();
    const book = vi.fn();
    broker.onBook(book);
    expect(await broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 5, mode: 'live' })).toEqual({ orderId: 'B1' });
    expect(broker.orders()).toMatchObject([{ id: 'B1', status: 'filled', qty: 5 }]);
    expect(broker.positions()).toEqual([]);
    expect(await broker.listAccounts(signal())).toEqual([]);
    await expect(broker.closePosition({ symbol: 'S', mode: 'live' })).rejects.toMatchObject({ rejected: true });
    await expect(broker.previewOrder({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'live' })).rejects.toThrow();
    expect(book).toHaveBeenCalledTimes(1);
  });
});

describe('FakeBroker account ledgers', () => {
  it('averages, realizes and marks positions the way the account figures report them', async () => {
    let now = 100;
    const broker = new FakeBroker({ accounts: SEEDS, now: () => now });
    broker.setMark('S', 100);
    await broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 10, mode: 'analyzer' });
    broker.setMark('S', 120);
    await broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 10, mode: 'analyzer' });
    expect(broker.accountPositions('A')).toEqual([{ symbol: 'S', netQty: 20, avgPrice: 110 }]);
    now = 101;
    let snapshot = await broker.getAccountSnapshot('A', signal());
    expect(snapshot).toEqual({
      accountId: 'A', mode: 'analyzer', asOf: 101, currency: 'INR', balance: 50_000, equity: 50_200,
      marginUsed: 2200, marginAvailable: 48_000, unrealizedPnl: 200, realizedPnl: 0, leverage: 1,
    });
    await broker.closePosition({ symbol: 'S', qty: 5, mode: 'analyzer' });
    snapshot = await broker.getAccountSnapshot('A', signal());
    expect(snapshot).toMatchObject({ balance: 50_050, realizedPnl: 50, unrealizedPnl: 150, marginUsed: 1650 });
    expect(broker.accountPositions('L')).toEqual([]);
  });

  it('pushes a fresh snapshot to subscribers when the mark moves an open position', async () => {
    const broker = new FakeBroker({ accounts: SEEDS, now: () => 1 });
    broker.setMark('S', 100);
    await broker.place({ symbol: 'S', side: 'SELL', type: 'MARKET', qty: 2, mode: 'analyzer' });
    const pushed: AccountSnapshot[] = [];
    const off = broker.subscribeAccount('A', snapshot => pushed.push(snapshot));
    broker.emitLtp('S', 90);
    expect(pushed[pushed.length - 1]).toMatchObject({ unrealizedPnl: 20, equity: 50_020 });
    off();
    broker.emitLtp('S', 80);
    expect(pushed).toHaveLength(1);
  });

  it('refuses rather than simulates: unknown accounts, the wrong ledger, no price, missing margin', async () => {
    const broker = new FakeBroker({ accounts: SEEDS });
    const reject = (promise: Promise<unknown>) => promise.then(() => { throw new Error('accepted'); }, (error: unknown) => {
      expect(isBrokerRejection(error)).toBe(true);
      return String((error as Error).message);
    });
    expect(await reject(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer', account: 'NOPE' }))).toContain('unknown account');
    expect(await reject(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'live', account: 'A' }))).toContain('analyzer account');
    expect(await reject(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' }))).toContain('no price');
    broker.setMark('S', 100);
    expect(await reject(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 501, mode: 'analyzer' }))).toContain('Insufficient margin');
    expect(await reject(broker.reversePosition({ symbol: 'S', mode: 'analyzer' }))).toContain('no open position');
    const narrow = new FakeBroker({ accounts: SEEDS, features: { accounts: true, reverse: false } });
    expect(await reject(narrow.reversePosition({ symbol: 'S', mode: 'analyzer' }))).toContain('not supported');
    expect(broker.orders()).toEqual([]);
  });

  it('fails every call while disconnected without applying a write', async () => {
    const broker = new FakeBroker({ accounts: SEEDS });
    broker.setMark('S', 100);
    const errors: unknown[] = [];
    broker.subscribeAccount('A', () => {}, error => errors.push(error));
    broker.disconnect();
    expect(errors).toHaveLength(1);
    // Nothing leaves while the connection is down, so each call says it was never sent,
    // before any refusal a server could only make once the request reached it.
    const never = { preflight: true, message: expect.stringContaining('disconnected') };
    await expect(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' })).rejects.toMatchObject(never);
    await expect(broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer', account: 'NONE' })).rejects.toMatchObject(never);
    await expect(broker.closePosition({ symbol: 'S', mode: 'analyzer' })).rejects.toMatchObject(never);
    await expect(broker.reversePosition({ symbol: 'S', mode: 'analyzer' })).rejects.toMatchObject(never);
    await expect(broker.placeBracket({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, stopLoss: 90, takeProfit: 110, mode: 'analyzer' })).rejects.toMatchObject(never);
    await expect(broker.previewOrder({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' })).rejects.toMatchObject(never);
    await expect(broker.modify('B1', { price: 1 })).rejects.toMatchObject(never);
    await expect(broker.cancel('B1')).rejects.toMatchObject(never);
    await expect(broker.getAccountSnapshot('A', signal())).rejects.toMatchObject(never);
    await expect(broker.getOrderHistory({ accountId: 'A' }, signal())).rejects.toMatchObject(never);
    expect(() => broker.subscribeAccount('A', () => {})).toThrow('disconnected');
    expect(broker.accountPositions('A')).toEqual([]);
    broker.reconnect();
    await broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' });
    expect(broker.accountPositions('A')).toEqual([{ symbol: 'S', netQty: 1, avgPrice: 100 }]);
  });

  it('refuses to cancel or modify an order that has already filled, as a server would', async () => {
    const broker = new FakeBroker({ accounts: SEEDS });
    broker.setMark('S', 100);
    const filled = await broker.place({ symbol: 'S', side: 'BUY', type: 'MARKET', qty: 10, mode: 'analyzer' });
    await expect(broker.cancel(filled.orderId)).rejects.toMatchObject({ rejected: true, message: 'FakeBroker: order B1 is already filled' });
    await expect(broker.modify(filled.orderId, { price: 1 })).rejects.toMatchObject({ rejected: true });
    const status = async (id: string) => (await broker.getOrderHistory({ accountId: 'A' }, signal())).find(row => row.order.id === id)?.order;
    expect(await status(filled.orderId)).toMatchObject({ status: 'filled', price: 100 });
    expect(broker.accountPositions('A')).toEqual([{ symbol: 'S', netQty: 10, avgPrice: 100 }]);
    // A resting order still cancels.
    const resting = await broker.place({ symbol: 'S', side: 'BUY', type: 'LIMIT', price: 90, qty: 1, mode: 'analyzer' });
    await broker.cancel(resting.orderId);
    expect(await status(resting.orderId)).toMatchObject({ status: 'cancelled' });
  });

  it('expires a GTD order at its expiry and filters history by symbol, time and limit', async () => {
    let now = 1000;
    const broker = new FakeBroker({ accounts: SEEDS, now: () => now });
    broker.setMark('S', 100);
    broker.setMark('T', 50);
    await broker.place({ symbol: 'S', side: 'BUY', type: 'LIMIT', price: 90, qty: 1, mode: 'analyzer', duration: 'GTD', expiresAt: 1010, clientToken: 'gtd' });
    now = 1005;
    await broker.place({ symbol: 'T', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' });
    now = 1020;
    const history = await broker.getOrderHistory({ accountId: 'A' }, signal());
    expect(history.find(row => row.clientToken === 'gtd')).toMatchObject({ order: { status: 'cancelled' }, time: 1020 });
    expect((await broker.getOrderHistory({ accountId: 'A', symbol: 'T' }, signal())).map(row => row.order.symbol)).toEqual(['T']);
    expect(await broker.getOrderHistory({ accountId: 'A', from: 1001, to: 1006 }, signal())).toHaveLength(1);
    expect(await broker.getOrderHistory({ accountId: 'A', limit: 1 }, signal())).toHaveLength(1);
    expect(await broker.getExecutions({ accountId: 'A' }, signal())).toMatchObject([{ symbol: 'T', side: 'BUY', qty: 1, price: 50, time: 1005, accountId: 'A' }]);
    expect(broker.orders().some(order => order.status === 'working')).toBe(false);
  });
});
