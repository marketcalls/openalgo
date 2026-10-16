import { describe, expect, it } from 'vitest';
import type {
  Bar, ChartDataContext, IndicatorAttachContext, IndicatorBarsRequest, IndicatorRequestState, IndicatorSnapshotRequest, RequestedBarsSnapshot,
} from '../src/index';
import { createRequestedIndicator } from '../src/indicators/requested-indicator';
import { createTier2Indicator, type Tier2Context } from '../src/indicators/external';

// A study that asks for another instrument's bars asks for them in the chart's
// session and adjustment, so its series lines up with the chart bar for bar.
// And a chart that switches variant has switched source: whatever the study
// fetched for the old one is dropped and asked for again, even when the
// symbol, exchange and interval stayed exactly the same.

const bars = (...times: number[]): Bar[] => times.map(time => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const settle = async (): Promise<void> => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const last = <T>(items: readonly T[]): T => items[items.length - 1];
const extended = { session: 'extended' as const, currency: 'USD' };

function host() {
  let market: ChartDataContext = { symbol: 'PRIMARY', exchange: 'US', interval: '1m' };
  const state: IndicatorRequestState = {
    source: { sourceId: 1, revision: 1, historyRevision: 1, provenance: 'history', change: 'reset' },
    providerRevision: 1, dataRevision: 0, supportsSnapshots: true,
  };
  const listeners = new Set<() => void>();
  const snapshots: { request: IndicatorSnapshotRequest; resolve(value: RequestedBarsSnapshot): void }[] = [];
  const barsRequests: IndicatorBarsRequest[] = [];
  const controller = new AbortController();
  const context: IndicatorAttachContext = {
    bars: () => bars(60, 120), settings: () => ({}), store: {}, signal: controller.signal,
    dataContext: () => market, requestState: () => state,
    subscribeRequestChanges: listener => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    requestSnapshot: request => new Promise(resolve => snapshots.push({ request, resolve })),
    requestBars: async request => { barsRequests.push(request); return bars(60, 120); },
    setDataStatus: () => {}, setDataRetry: () => {}, requestRecompute: () => {},
  };
  return {
    context, snapshots, barsRequests,
    market: (next: ChartDataContext) => { market = next; for (const listener of listeners) listener(); },
    remove: () => controller.abort(),
  };
}

describe('requested contexts follow the chart variant', () => {
  it('asks for the requested series in the chart session and adjustment, not its currency', async () => {
    const h = host();
    const descriptor = createRequestedIndicator({
      id: 'variant-requested', name: 'Requested', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      request: () => ({ symbol: 'BENCH', interval: '1m', from: 0, to: 120 }),
      expression: requested => ({ v: requested.map(bar => bar.close) }),
    });
    descriptor.attach!(h.context);
    expect(h.snapshots).toHaveLength(1);
    expect(h.snapshots[0].request).not.toHaveProperty('variant');
    h.market({ symbol: 'PRIMARY', exchange: 'US', interval: '1m', variant: extended });
    await settle();
    expect(h.snapshots).toHaveLength(2);
    expect(h.snapshots[1].request.variant).toEqual({ session: 'extended' });
    // The request for the old variant is dead: its answer can never land.
    expect(h.snapshots[0].request.signal?.aborted).toBe(true);
    h.remove();
  });

  it('keeps a variant the selection names itself, and refuses a malformed one', async () => {
    const h = host();
    const named = createRequestedIndicator({
      id: 'variant-named', name: 'Named', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      request: () => ({ symbol: 'BENCH', interval: '1m', from: 0, to: 120, variant: { adjustment: 'raw' } }),
      expression: requested => ({ v: requested.map(bar => bar.close) }),
    });
    named.attach!(h.context);
    h.market({ symbol: 'PRIMARY', exchange: 'US', interval: '1m', variant: extended });
    expect(last(h.snapshots)!.request.variant).toEqual({ adjustment: 'raw' });
    h.remove();
    const bad = host();
    const statuses: string[] = [];
    bad.context.setDataStatus = status => { statuses.push(status.state); };
    createRequestedIndicator({
      id: 'variant-bad', name: 'Bad', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      request: () => ({ symbol: 'BENCH', interval: '1m', from: 0, to: 120, variant: { session: 'overnight' as never } }),
      expression: requested => ({ v: requested.map(bar => bar.close) }),
    }).attach!(bad.context);
    expect(bad.snapshots).toHaveLength(0);
    expect(last(statuses)).toBe('error');
    bad.remove();
  });

  it('starts an external study again when only the chart variant changes', async () => {
    const h = host();
    const fetches: Tier2Context[] = [];
    const descriptor = createTier2Indicator({
      id: 'variant-external', name: 'External', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      fetch: async ctx => {
        fetches.push(ctx);
        const other = await ctx.requestBars!({ symbol: 'BENCH', interval: '1m', from: ctx.from, to: ctx.to });
        return other.map(bar => ({ time: bar.time, values: { v: bar.close } }));
      },
    });
    descriptor.attach!(h.context);
    await settle();
    expect(fetches).toHaveLength(1);
    expect(h.barsRequests[0]).not.toHaveProperty('variant');
    h.market({ symbol: 'PRIMARY', exchange: 'US', interval: '1m', variant: extended });
    await settle();
    expect(fetches).toHaveLength(2);
    expect(fetches[1].dataContext?.variant).toEqual(extended);
    expect(h.barsRequests[1].variant).toEqual({ session: 'extended' });
    h.remove();
  });
});
