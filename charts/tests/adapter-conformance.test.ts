import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BTC_USD_REFRESH_MS } from '../website/lib/market-data/btc-usd.mjs';
import { adapterContractChecks, authoritativeRepair, duplicateHistory, loadInitial, type AdapterHarness } from './conformance/adapter-contract';
import { adapterReferences, createBrokerHarness, createCryptoHarness } from './conformance/reference-adapters';

let active: AdapterHarness[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-09-20T00:30:00Z'));
});

afterEach(() => {
  for (const harness of active) harness.destroy();
  active = [];
  const timers = vi.getTimerCount();
  vi.useRealTimers();
  expect(timers, 'adapter teardown must release owned timers').toBe(0);
});

for (const reference of adapterReferences) {
  describe(`${reference.name} adapter conformance (${reference.evidence} transport)`, () => {
    for (const check of adapterContractChecks) {
      it(check.name, async () => {
        const harness = reference.create();
        active.push(harness);
        await check.run(harness);
      });
    }

    it('negative control: the shared runner rejects duplicate output', async () => {
      const harness = reference.create();
      active.push(harness);
      const defective: AdapterHarness = {
        ...harness,
        snapshot: () => {
          const snapshot = harness.snapshot();
          return { ...snapshot, bars: [...snapshot.bars, ...snapshot.bars.slice(0, 1)] };
        },
      };
      await expect(duplicateHistory(defective)).rejects.toThrow('history must be sorted, unique');
    });

    it('negative control: the shared runner rejects a discarded authoritative repair', async () => {
      const harness = reference.create();
      active.push(harness);
      const defective: AdapterHarness = {
        ...harness,
        snapshot: () => ({ ...harness.snapshot(), bars: harness.fixtures.initialBars }),
      };
      await expect(authoritativeRepair(defective)).rejects.toThrow('an authoritative closed-bar repair');
    });
  });
}

describe('broker stream conformance (synthetic transport)', () => {
  it('does not double-count a repeated cumulative-volume quote or append a duplicate candle', async () => {
    const harness = createBrokerHarness();
    active.push(harness);
    await loadInitial(harness);
    const tail = harness.fixtures.initialBars[2];
    harness.quote(tail.time + 1, tail.close, 1000);
    harness.quote(tail.time + 2, tail.close + 1, 1005);
    const before = harness.snapshot().bars;
    harness.quote(tail.time + 2, tail.close + 1, 1005);
    expect(harness.snapshot().bars).toEqual(before);
    expect(before).toHaveLength(3);
    expect(before[2]).toEqual({ ...tail, close: tail.close + 1, volume: tail.volume! + 5 });
  });

  it('uses the declared late-quote policy without emitting older history through the tail', async () => {
    const harness = createBrokerHarness();
    active.push(harness);
    await loadInitial(harness);
    const tail = harness.fixtures.initialBars[2];
    harness.quote(tail.time + 5, tail.close, 1000);
    harness.quote(tail.time - 1, tail.close + 2, 1000);
    const bars = harness.snapshot().bars;
    expect(bars.slice(0, 2)).toEqual(harness.fixtures.initialBars.slice(0, 2));
    // The existing CandleBuilder default folds a late quote into the current bucket.
    expect(bars[2]).toEqual({ ...tail, close: tail.close + 2 });
    expect(bars).toHaveLength(3);
  });

  it('reauthenticates before resubscribing and buffers quotes through an authoritative repair', async () => {
    const harness = createBrokerHarness();
    active.push(harness);
    await loadInitial(harness);
    const getBars = vi.spyOn(harness.feed, 'getBars');
    const subscribeBars = vi.spyOn(harness.feed, 'subscribeBars');
    const firstSocket = harness.sockets[0];
    const obsoleteDelivery = firstSocket.onmessage;
    const before = harness.snapshot().bars;
    firstSocket.disconnect();
    await vi.advanceTimersByTimeAsync(10);
    expect(harness.sockets).toHaveLength(2);
    const restored = harness.sockets[1];
    expect(restored.frames.map(frame => frame.action)).toEqual(['authenticate']);
    obsoleteDelivery?.({ data: JSON.stringify({ type: 'market_data', mode: 2,
      data: { symbol: harness.request.symbol, exchange: harness.request.exchange,
        timestamp: harness.fixtures.initialBars[2].time + 1, ltp: 9999, volume: 1000 },
    }) });
    expect(harness.snapshot().bars).toEqual(before);
    restored.authenticate();
    expect(restored.frames.map(frame => frame.action)).toEqual(['authenticate', 'subscribe']);
    const repair = await harness.transport.request(1);
    expect(getBars).toHaveBeenCalledWith(expect.objectContaining({ noCache: true, signal: expect.any(AbortSignal) }));
    expect(harness.snapshot().status).toBe('refreshing');
    const tail = harness.fixtures.initialBars[2];
    harness.quote(tail.time + 5, tail.close + 2, 1000);
    expect(harness.snapshot().bars).toEqual(before);
    repair.reply(harness.fixtures.repairPayload);
    await vi.advanceTimersByTimeAsync(0);
    const expected = harness.fixtures.repairedBars.map((bar, index) => index === 2 ? { ...bar, close: tail.close + 2 } : bar);
    expect(harness.snapshot()).toMatchObject({ status: 'ready', bars: expected });
    expect(subscribeBars).toHaveBeenLastCalledWith(expect.anything(), expect.any(Function),
      expect.objectContaining({ seedFrom: expected[2], onResync: expect.any(Function) }));
    expect(restored.frames.filter(frame => frame.action === 'subscribe')).toHaveLength(1);
    expect(restored.frames.filter(frame => frame.action === 'unsubscribe')).toHaveLength(0);
  });

  it('unsubscribes idempotently and stops resync requests once every consumer leaves', async () => {
    const harness = createBrokerHarness();
    active.push(harness);
    await loadInitial(harness);
    const onBar = vi.fn();
    const onResync = vi.fn();
    const release = harness.feed.subscribeBars(harness.request, onBar, { onResync });
    const socket = harness.sockets[0];
    release();
    release();
    expect(socket.frames.filter(frame => frame.action === 'unsubscribe')).toHaveLength(0);
    const publications = harness.publications.length;
    const tail = harness.fixtures.initialBars[2];
    harness.quote(tail.time + 1, tail.close + 1, 1000);
    expect(onBar).not.toHaveBeenCalled();
    expect(harness.publications.length).toBeGreaterThan(publications);
    harness.controller.destroy();
    harness.controller.destroy();
    expect(socket.frames.filter(frame => frame.action === 'unsubscribe')).toEqual([
      expect.objectContaining({ symbol: harness.request.symbol, exchange: harness.request.exchange, mode: 2 }),
    ]);
    const stoppedPublications = harness.publications.length;
    socket.disconnect();
    await vi.advanceTimersByTimeAsync(10);
    harness.sockets[1].authenticate();
    harness.quote(tail.time + 2, tail.close + 2, 1005);
    expect(harness.sockets[1].frames.map(frame => frame.action)).toEqual(['authenticate']);
    expect(onBar).not.toHaveBeenCalled();
    expect(onResync).not.toHaveBeenCalled();
    expect(harness.transport.requests).toHaveLength(1);
    expect(harness.publications).toHaveLength(stoppedPublications);
  });

  it('intentional close cancels a scheduled reconnect', async () => {
    const harness = createBrokerHarness();
    active.push(harness);
    await loadInitial(harness);
    harness.sockets[0].disconnect();
    expect(vi.getTimerCount()).toBe(1);
    harness.destroy();
    await vi.advanceTimersByTimeAsync(100);
    expect(harness.sockets).toHaveLength(1);
    expect(harness.transport.requests).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('crypto polling conformance (synthetic transport)', () => {
  it('keeps fractional volume and UTC-midnight weekend candles without a session reset', async () => {
    const harness = createCryptoHarness();
    active.push(harness);
    await loadInitial(harness);
    const bars = harness.snapshot().bars;
    expect(bars.map(bar => new Date(bar.time * 1000).toISOString())).toEqual([
      '2026-09-19T23:45:00.000Z', '2026-09-20T00:00:00.000Z', '2026-09-20T00:15:00.000Z',
    ]);
    expect(bars.map(bar => bar.volume)).toEqual([0.125, 0.25, 0.375]);
    expect(harness.transport.requests[0].init).toMatchObject({ cache: 'no-store', credentials: 'omit' });
  });

  it('automatically polls again after a transport failure and releases its timer on destroy', async () => {
    const harness = createCryptoHarness();
    active.push(harness);
    await loadInitial(harness);
    await vi.advanceTimersByTimeAsync(BTC_USD_REFRESH_MS);
    (await harness.transport.request(1)).fail(new Error('Synthetic polling interruption'));
    await vi.advanceTimersByTimeAsync(0);
    expect(harness.snapshot().status).toBe('stale');
    expect(harness.snapshot().bars).toEqual(harness.fixtures.initialBars);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(BTC_USD_REFRESH_MS);
    (await harness.transport.request(2)).reply(harness.fixtures.repairPayload);
    await vi.advanceTimersByTimeAsync(0);
    expect(harness.snapshot()).toMatchObject({ status: 'ready', bars: harness.fixtures.repairedBars });
    expect(vi.getTimerCount()).toBe(1);
    harness.destroy();
    await vi.advanceTimersByTimeAsync(BTC_USD_REFRESH_MS * 2);
    expect(harness.transport.requests).toHaveLength(3);
    expect(vi.getTimerCount()).toBe(0);
  });
});
