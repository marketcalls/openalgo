import { describe, expect, it, vi } from 'vitest';
import { OrderEngine, type ModifyPatch, type OrderFeed, type PlaceRequest } from '../src/trade/order-engine';
import { OpenAlgoTradeFeed } from '../src/feed/openalgo-trade';

const order = (): PlaceRequest => ({
  symbol: 'SYNTHETIC', exchange: 'NSE', side: 'BUY', type: 'LIMIT', qty: 1,
  price: 100, product: 'MIS', clientToken: 'intent-1',
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function memoryFeed() {
  return {
    place: vi.fn<OrderFeed['place']>(async () => ({ orderId: 'broker-1' })),
    modify: vi.fn<OrderFeed['modify']>(async () => {}),
    cancel: vi.fn<OrderFeed['cancel']>(async () => {}),
  };
}

describe('detached trading requests', () => {
  it('preserves the admitted engine request while the caller mutates it during confirmation', async () => {
    const approved = deferred<boolean>();
    const feed = memoryFeed();
    const manager = new OrderEngine({
      feed, constraints: { tickSize: 0.05 }, gate: () => approved.promise,
      capabilities: { orderTypes: ['LIMIT'], modes: ['live'] },
    });
    const request = order();
    const pending = manager.placeOrder(request);
    Object.assign(request, { symbol: 'CHANGED', exchange: 'OTHER', type: 'MARKET', qty: 5,
      price: 999, product: 'CNC', clientToken: 'changed-token' });
    approved.resolve(true);
    expect(await pending).toMatchObject({ ok: true, clientId: 'intent-1' });
    expect(feed.place).toHaveBeenCalledWith({ ...order(), triggerPrice: undefined, mode: 'live' });
  });

  it('does not let the confirmation callback mutate the submitted values', async () => {
    const feed = memoryFeed();
    const manager = new OrderEngine({
      feed, constraints: { tickSize: 0.05 }, capabilities: { orderTypes: ['LIMIT'] },
      gate: request => { request.type = 'MARKET'; request.qty = 50; request.symbol = 'CHANGED'; return true; },
    });
    expect(await manager.placeOrder(order())).toMatchObject({ ok: true });
    expect(feed.place).toHaveBeenCalledWith({ ...order(), triggerPrice: undefined, mode: 'live' });
  });

  it('preserves the direct-feed request across the asynchronous mode lookup', async () => {
    const mode = deferred<Response>();
    const bodies: Record<string, unknown>[] = [];
    const fetchImpl = vi.fn<typeof fetch>(async (url, init) => {
      if (String(url).endsWith('/analyzer/')) return mode.promise;
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return { ok: true, json: async () => ({ orderid: 'broker-1' }) } as Response;
    });
    const feed = new OpenAlgoTradeFeed({
      baseUrl: 'https://broker.invalid', apiKey: 'synthetic-placeholder', fetchImpl, verifyMode: 'always',
      capabilities: { orderTypes: ['LIMIT'], modes: ['live'] },
    });
    const request = { ...order(), mode: 'live' as const };
    const pending = feed.place(request);
    Object.assign(request, { symbol: 'CHANGED', exchange: 'OTHER', type: 'MARKET', qty: 5,
      price: 999, product: 'CNC', clientToken: 'changed-token', mode: 'analyzer' });
    mode.resolve({ ok: true, json: async () => ({ data: { mode: 'live' } }) } as Response);
    await pending;
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ symbol: 'SYNTHETIC', exchange: 'NSE', pricetype: 'LIMIT',
      quantity: 1, price: 100, product: 'MIS' });
    expect(feed.tokenState('intent-1')).toBe('sent');
    expect(feed.tokenState('changed-token')).toBe('unknown');
  });

  it('detaches direct modify patches before invoking capability providers', async () => {
    const patch: ModifyPatch = { price: 101 };
    const bodies: Record<string, unknown>[] = [];
    const feed = new OpenAlgoTradeFeed({
      baseUrl: 'https://broker.invalid', apiKey: 'synthetic-placeholder', verifyMode: 'off',
      capabilities: request => { if (request.operation === 'modify') patch.price = 999; return {}; },
      fetchImpl: async (_url, init) => {
        bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return { ok: true, json: async () => ({ orderid: 'broker-1' }) } as Response;
      },
    });
    await feed.place({ ...order(), mode: 'live' });
    await feed.modify('broker-1', patch);
    expect(patch.price).toBe(999);
    expect(bodies[1].price).toBe(101);
  });

  it('captures modify options before capability callbacks can mutate them', async () => {
    const feed = memoryFeed();
    const options = { triggerPrice: 102 };
    const manager = new OrderEngine({
      feed, constraints: { tickSize: 0.05 }, armed: true,
      capabilities: request => { if (request.operation === 'modify') options.triggerPrice = 999; return {}; },
    });
    await manager.placeOrder(order());
    manager.requestModify('intent-1', 101, options);
    await manager.commitModify('intent-1');
    expect(feed.modify).toHaveBeenCalledWith('broker-1', { price: 101, triggerPrice: 102 });
  });

  it('keeps submitted stop offsets when a feed mutates its received modify patch', async () => {
    const feed = memoryFeed();
    const received: ModifyPatch[] = [];
    feed.modify.mockImplementation(async (_id, patch) => {
      received.push({ ...patch });
      patch.price = 500; patch.triggerPrice = 700;
    });
    const manager = new OrderEngine({ feed, constraints: { tickSize: 0.05 }, armed: true, minModifyIntervalMs: 0 });
    await manager.placeOrder({ ...order(), type: 'SL', triggerPrice: 101 });
    manager.requestModify('intent-1', 101);
    await Promise.resolve();
    manager.requestModify('intent-1', 102);
    await Promise.resolve();
    expect(received).toEqual([{ price: 101, triggerPrice: 102 }, { price: 102, triggerPrice: 103 }]);
  });
});

describe('broker authority over asynchronous write completions', () => {
  for (const operation of ['modify', 'cancel'] as const) {
    it.each(['success', 'transport-failure', 'preflight-refusal'] as const)(
      `keeps a newer broker fill after pending ${operation} completes with %s`, async outcome => {
        const response = deferred<void>();
        const feed = memoryFeed();
        feed[operation].mockReturnValueOnce(response.promise);
        const manager = new OrderEngine({ feed, constraints: { tickSize: 0.05 }, armed: true });
        await manager.placeOrder(order());
        manager.onBrokerUpdate('broker-1', 'working');
        const completion = operation === 'cancel'
          ? manager.cancelOrder('intent-1')
          : (manager.requestModify('intent-1', 101), manager.commitModify('intent-1'));
        manager.onBrokerUpdate('broker-1', 'filled');
        if (outcome === 'success') response.resolve();
        else response.reject(Object.assign(new Error('Synthetic write refusal'), outcome === 'preflight-refusal' ? { preflight: true } : {}));
        await completion;
        await Promise.resolve();
        expect(manager.state('intent-1')).toBe('filled');
        expect(manager.intentState('intent-1')).toBe('SETTLED');
        expect(manager.brokerStatus('intent-1')).toBe('filled');
      },
    );
  }

  it('does not let an older modify failure overwrite a later modify completion', async () => {
    const first = deferred<void>(), second = deferred<void>();
    const feed = memoryFeed();
    feed.modify.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const manager = new OrderEngine({ feed, constraints: { tickSize: 0.05 }, armed: true, minModifyIntervalMs: 0 });
    await manager.placeOrder(order());
    manager.onBrokerUpdate('broker-1', 'working');
    manager.requestModify('intent-1', 101);
    manager.requestModify('intent-1', 102);
    second.resolve();
    await Promise.resolve();
    first.reject(new Error('Older response lost'));
    await Promise.resolve();
    expect(manager.state('intent-1')).toBe('working');
    expect(manager.intentState('intent-1')).toBe('ACKNOWLEDGED');
    expect(manager.brokerStatus('intent-1')).toBe('working');
  });

  it('keeps reconciliation pending when an older write completes', async () => {
    const response = deferred<void>();
    const feed = memoryFeed();
    feed.modify.mockReturnValueOnce(response.promise);
    const manager = new OrderEngine({ feed, constraints: { tickSize: 0.05 }, armed: true });
    await manager.placeOrder(order());
    manager.requestModify('intent-1', 101);
    manager.beginReconcile();
    response.resolve();
    await Promise.resolve();
    expect(manager.intentState('intent-1')).toBe('RECONCILING');
    manager.onReconnect(new Set());
    expect(manager.intentState('intent-1')).toBe('AMBIGUOUS');
  });
});
