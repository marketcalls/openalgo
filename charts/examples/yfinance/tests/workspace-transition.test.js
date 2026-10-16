import { describe, it, expect, vi } from 'vitest';
import '/dist/openalgo-charts.indicators.mjs';
vi.mock('../src/feed.js', () => ({ fetchBars: vi.fn(), abortFetch: vi.fn() }));
import { fetchBars } from '../src/feed.js';
import { prepareReferenceWorkspace, ReferenceWorkspaceTransition } from '../src/workspace-transition.js';
import { workspaceFromLayout } from '../src/workspace-document.js';

const bars = [{ time: 1700000000, open: 100, high: 102, low: 99, close: 101, volume: 5, openInterest: 42 }];
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const fixture = () => workspaceFromLayout({ schema: 2, version: 1, timezone: 'America/New_York',
  request: { symbol: 'AAPL', interval: '1d', period: '1y' }, chartType: 'line',
  secondary: { request: { symbol: 'TSLA/MSFT', interval: '15m', period: '1mo' }, chartType: 'candlestick',
    state: { version: 1, timezone: 'Asia/Kolkata' }, width: 40 } });

describe('reference workspace preparation', () => {
  it('waits for every pane with its own source, interval, period and timezone', async () => {
    const second = deferred();
    const fetch = vi.fn((request, options) => request.symbol === 'AAPL' ? Promise.resolve(bars) : second.promise);
    const pending = prepareReferenceWorkspace(fixture(), { fetch });
    const finished = vi.fn(); pending.then(finished);
    await Promise.resolve(); expect(finished).not.toHaveBeenCalled();
    // The layout saved its daily chart over one year: it loads the five year daily floor.
    expect(fetch.mock.calls.map(([request, options]) => [request, options.timezone])).toEqual([
      [{ symbol: 'AAPL', interval: '1d', period: '5y' }, 'America/New_York'],
      [{ symbol: 'TSLA/MSFT', interval: '15m', period: '1mo' }, 'Asia/Kolkata'],
    ]);
    second.resolve(bars);
    const prepared = await pending;
    expect(prepared.bars).toEqual([bars, bars]);
    expect(prepared.layout.secondary.request.symbol).toBe('TSLA/MSFT');
  });

  it('rejects unsupported studies before any history request', async () => {
    const doc = fixture();
    doc.panes[1].chart.indicators = [{ instanceId: 'lost', indicatorId: 'not-registered-here', settings: {}, paneIndex: 1 }];
    const fetch = vi.fn();
    await expect(prepareReferenceWorkspace(doc, { fetch })).rejects.toThrow(/study|indicator/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('aborts every sibling request when one fails and never accepts empty history', async () => {
    const signals = [];
    const fetch = vi.fn((request, options) => {
      signals.push(options.signal);
      return request.symbol === 'AAPL' ? Promise.reject(new Error('Feed failed')) : new Promise(() => {});
    });
    await expect(prepareReferenceWorkspace(fixture(), { fetch })).rejects.toThrow('Feed failed');
    expect(signals.every(signal => signal.aborted)).toBe(true);
    await expect(prepareReferenceWorkspace(fixture(), { fetch: async () => [] })).rejects.toThrow(/no.*history|no.*bars/i);
  });

  it('refuses linked source conflicts and missing drawing tools before requesting history', async () => {
    const fetch = vi.fn();
    const linked = fixture(); linked.sync.interval = true;
    await expect(prepareReferenceWorkspace(linked, { fetch })).rejects.toThrow(/linked|sync/i);
    const drawing = fixture(); drawing.panes[0].chart.drawings = { version: 2, drawings: [{ tool: 'unknown-host-drawing' }] };
    await expect(prepareReferenceWorkspace(drawing, { fetch })).rejects.toThrow(/drawing/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('takes a drawing document of every version this build reads, and refuses a newer one', async () => {
    const line = { id: 'l1', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: 1700000000, price: 101 }, { time: 1700086400, price: 104 }] };
    const withDrawings = (drawings) => { const doc = fixture(); doc.panes[0].chart.drawings = drawings; return doc; };
    const fetch = async () => bars;
    // A save with no interval range is still version 2; one with a range is 3.
    await expect(prepareReferenceWorkspace(withDrawings({ version: 2, drawings: [line] }), { fetch })).resolves.toBeTruthy();
    await expect(prepareReferenceWorkspace(withDrawings({ version: 3, drawings: [{ ...line, intervals: { to: '1h' } }] }), { fetch })).resolves.toBeTruthy();
    await expect(prepareReferenceWorkspace(withDrawings({ version: 4, drawings: [line] }), { fetch })).rejects.toThrow(/drawing document version/);
  });

  it('stops waiting promptly on cancellation and consumes a late rejected request', async () => {
    const gate = deferred(), controller = new AbortController();
    const pending = prepareReferenceWorkspace(fixture(), { fetch: () => gate.promise, signal: controller.signal });
    controller.abort(new Error('Cancelled by owner'));
    await expect(pending).rejects.toThrow('Cancelled by owner');
    gate.reject(new Error('Late network failure'));
    await Promise.resolve();
  });

  it('forwards the same cancellation owner through the real expression loader to every leg', async () => {
    const gate = deferred(), controller = new AbortController();
    fetchBars.mockImplementation(symbol => symbol === 'MSFT' ? gate.promise : Promise.resolve(bars));
    const pending = prepareReferenceWorkspace(fixture(), { signal: controller.signal });
    expect(fetchBars.mock.calls.map(call => call[0])).toEqual(['AAPL', 'TSLA', 'MSFT']);
    const signals = fetchBars.mock.calls.map(call => call[3].signal);
    expect(new Set(signals).size).toBe(1);
    expect(fetchBars.mock.calls.every(call => call[3].slot === undefined)).toBe(true);
    controller.abort(new Error('Expression owner cancelled'));
    await expect(pending).rejects.toThrow('Expression owner cancelled');
    expect(signals.every(signal => signal.aborted)).toBe(true);
    gate.reject(new Error('Late expression leg'));
  });

  it.each([
    { version: 99, drawings: [] },
    { version: 2, drawings: [{ id: 'broken', tool: 'horizontal-line', points: [], style: {} }] },
    { version: 2, drawings: ['one', 'two'].map(() => ({ id: 'duplicate', tool: 'horizontal-line', points: [{ time: 1, price: 100 }], style: {} })) },
  ])('rejects drawing documents that would lose shapes or their identities', async drawings => {
    const doc = fixture(); doc.panes[0].chart.drawings = drawings;
    const fetch = vi.fn(async () => bars);
    await expect(prepareReferenceWorkspace(doc, { fetch })).rejects.toThrow(/drawing/i);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('reference workspace publication', () => {
  function host(overrides = {}) {
    const prior = { layout: { name: 'Current' }, bars: [bars] };
    return { capture: vi.fn(() => prior), current: vi.fn(() => true),
      prepare: vi.fn(async () => ({ layout: { name: 'Next' }, bars: [bars] })),
      install: vi.fn(), setPending: vi.fn(), watch: vi.fn(() => vi.fn()), ...overrides };
  }

  it('does not publish until preparation and persistence finish, and releases its watch', async () => {
    const ready = deferred(), stored = deferred(), release = vi.fn();
    const callbacks = host({ prepare: vi.fn(() => ready.promise), watch: vi.fn(() => release) });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    const persist = vi.fn(() => stored.promise);
    const pending = transition.open(fixture(), persist);
    expect(callbacks.capture).toHaveBeenCalledTimes(1);
    expect(callbacks.install).not.toHaveBeenCalled(); expect(persist).not.toHaveBeenCalled();
    ready.resolve({ layout: {}, bars: [bars] }); await vi.waitFor(() => expect(persist).toHaveBeenCalledTimes(1));
    expect(callbacks.install).not.toHaveBeenCalled();
    stored.resolve(); await pending;
    expect(callbacks.install).toHaveBeenCalledTimes(1);
    expect(callbacks.setPending.mock.calls).toEqual([[true], [false]]);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it('keeps the current workspace on history or storage failure', async () => {
    for (const phase of ['prepare', 'persist']) {
      const callbacks = host(phase === 'prepare' ? { prepare: async () => { throw new Error('No history'); } } : {});
      const transition = new ReferenceWorkspaceTransition(callbacks);
      await expect(transition.open(fixture(), async () => { throw new Error('Write refused'); })).rejects.toThrow();
      expect(callbacks.install).not.toHaveBeenCalled();
      expect(callbacks.setPending.mock.calls).toEqual([[true], [false]]);
    }
  });

  it('cancels and supersedes an unresolved preparation without publishing a late completion', async () => {
    const first = deferred();
    const callbacks = host({ prepare: vi.fn().mockImplementationOnce(() => first.promise)
      .mockResolvedValue({ layout: { name: 'Newest' }, bars: [bars] }) });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    const oldPersist = vi.fn();
    const old = transition.open(fixture(), oldPersist);
    const rejection = expect(old).rejects.toThrow(/cancel/i);
    await transition.open(fixture(), async () => {}); await rejection;
    first.resolve({ layout: { name: 'Late' }, bars: [bars] }); await Promise.resolve();
    expect(oldPersist).not.toHaveBeenCalled();
    expect(callbacks.install).toHaveBeenCalledTimes(1);
    expect(callbacks.install.mock.calls[0][0].layout.name).toBe('Newest');
  });

  it('invalidates pending storage with the same abort signal when its owner changes', async () => {
    let invalidate, signal;
    const callbacks = host({ watch: fn => { invalidate = fn; return vi.fn(); } });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    const pending = transition.open(fixture(), value => {
      signal = value;
      return new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      });
    });
    await vi.waitFor(() => expect(signal).toBeDefined());
    invalidate();
    await expect(pending).rejects.toThrow(/cancel/i);
    expect(signal.aborted).toBe(true);
    expect(callbacks.install).not.toHaveBeenCalled();
  });

  it('rejects an unobserved stale owner before storage and releases the pending state', async () => {
    const callbacks = host({ current: () => false });
    const transition = new ReferenceWorkspaceTransition(callbacks), persist = vi.fn();
    await expect(transition.open(fixture(), persist)).rejects.toThrow(/changed|cancel/i);
    expect(persist).not.toHaveBeenCalled(); expect(callbacks.install).not.toHaveBeenCalled();
    expect(callbacks.setPending).toHaveBeenLastCalledWith(false);
  });

  it('rolls back a synchronous installation failure using captured raw bars', async () => {
    const callbacks = host({ install: vi.fn().mockImplementationOnce(() => { throw new Error('Render failed'); }) });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    await expect(transition.open(fixture(), async () => {})).rejects.toThrow('Render failed');
    expect(callbacks.install).toHaveBeenCalledTimes(2);
    expect(callbacks.install.mock.calls[1][0]).toBe(callbacks.capture.mock.results[0].value);
    expect(callbacks.setPending).toHaveBeenLastCalledWith(false);
  });

  it('compensates a committed selection if the owner becomes stale at the storage boundary', async () => {
    let current = true;
    const rollback = vi.fn();
    const callbacks = host({ current: () => current });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    await expect(transition.open(fixture(), async () => { current = false; return { rollback }; })).rejects.toThrow(/changed|cancel/i);
    expect(rollback).toHaveBeenCalledTimes(1);
    expect(callbacks.install).not.toHaveBeenCalled();
  });

  it('receives and compensates storage committed just before a watched cancellation', async () => {
    let invalidate;
    const rollback = vi.fn();
    const callbacks = host({ watch: fn => { invalidate = fn; return vi.fn(); } });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    await expect(transition.open(fixture(), async () => {
      invalidate();
      return { rollback };
    })).rejects.toThrow(/cancel/i);
    expect(rollback).toHaveBeenCalledTimes(1);
    expect(callbacks.install).not.toHaveBeenCalled();
  });

  it('destroy cancels pending work and refuses subsequent opens', async () => {
    const callbacks = host({ prepare: () => new Promise(() => {}) });
    const transition = new ReferenceWorkspaceTransition(callbacks);
    const pending = transition.open(fixture(), vi.fn()); transition.destroy();
    await expect(pending).rejects.toThrow(/cancel/i);
    await expect(transition.open(fixture(), vi.fn())).rejects.toThrow(/closed/i);
    expect(callbacks.install).not.toHaveBeenCalled();
  });
});
