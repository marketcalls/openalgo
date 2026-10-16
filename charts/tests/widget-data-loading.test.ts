import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart, IndicatorInputError, registerIndicator, type Bar, type DataFeed, type BarsRequest } from '../src/index';
import { createTier2Indicator } from '../src/indicators/external';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const live: Widget[] = [];
afterEach(() => { for (const widget of live.splice(0)) widget.destroy(); vi.restoreAllMocks(); });
const bar = (time: number, close = 10): Bar => ({ time, open: 10, high: Math.max(12, close), low: 9, close });
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function make(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    symbol: 'AAA', exchange: 'X', interval: '1m', now: () => 60_000_000, ...options,
  });
  widget.chart.applySize(800, 600);
  live.push(widget);
  return { widget, root: widget.root as unknown as FakeElement, doc };
}

describe('widget managed data loading', () => {
  it('shares feed work across widgets and cancels only the departing consumer', async () => {
    const requests: BarsRequest[] = [];
    let resolve!: (bars: Bar[]) => void;
    const feed: DataFeed = { getBars: request => { requests.push(request); return new Promise(yes => { resolve = yes; }); } };
    const first = make({ feed }).widget;
    const second = make({ feed }).widget;
    expect(first.dataController).toBeDefined();
    expect(requests).toHaveLength(1);
    first.destroy();
    expect(requests[0].signal?.aborted).toBe(false);
    resolve([bar(60)]);
    await flush();
    expect(second.series.getData()).toEqual([bar(60)]);
  });

  it('clears the previous source and supplies the next context while history is pending', async () => {
    let resolve!: (bars: Bar[]) => void;
    const { widget } = make({ feed: { getBars: request => request.symbol === 'AAA'
      ? Promise.resolve([bar(60)]) : new Promise(yes => { resolve = yes; }) } });
    await flush();
    widget.setSymbol('BBB', 'Y');
    expect(widget.series.getData()).toEqual([]);
    expect(widget.chart.getDataContext()).toEqual({ symbol: 'BBB', exchange: 'Y', interval: '1m' });
    resolve([bar(60, 20)]);
    await flush();
    expect(widget.series.getData()).toEqual([bar(60, 20)]);
  });

  it('provides accessible retry outside canvas input and keeps the user view on reload', async () => {
    let calls = 0;
    const { widget, root } = make({ feed: { getBars: async () => {
      if (++calls === 1) throw new Error('offline');
      return Array.from({ length: 30 }, (_, i) => bar(i * 60));
    } } });
    await flush();
    const status = root.querySelector('.oac-data-status')!;
    expect(status.getAttribute('role')).toBe('status');
    expect(status.textContent).toContain('Could not load');
    const retry = status.querySelector('button')!;
    expect(retry.getAttribute('aria-label')).toBe('Retry chart data');
    let shortcut = 0;
    widget.context.keymap.register('x', () => { shortcut++; return true; }, 'widget');
    retry.focus();
    fireKey(retry, 'x');
    expect(shortcut).toBe(0);
    expect(fire(retry, 'pointerdown').propagationStopped).toBe(true);
    retry.click();
    await flush();
    expect(widget.series.getData()).toHaveLength(30);
    widget.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    const view = widget.chart.getVisibleLogicalRange();
    await widget.reload();
    expect(widget.chart.getVisibleLogicalRange()).toEqual(view);
    expect(status.hidden).toBe(true);
  });

  it('loads backward history through the chart hook and preserves the visible time anchor', async () => {
    const hook = vi.spyOn(Chart.prototype, 'setHistoryLoader');
    const { widget } = make({ feed: {
      getBars: async () => Array.from({ length: 20 }, (_, i) => bar((i + 30) * 60)),
      getBarsPage: async () => ({ bars: Array.from({ length: 20 }, (_, i) => bar((i + 10) * 60)), hasMore: false }),
    } });
    await flush();
    widget.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    const view = widget.chart.getVisibleLogicalRange();
    const before = widget.series.getData()[Math.round(view.from)].time;
    const complete = vi.spyOn(widget.chart, 'historyLoadComplete');
    expect(hook).toHaveBeenCalled();
    hook.mock.calls[0][0]();
    await flush();
    expect(widget.series.getData()).toHaveLength(40);
    expect(widget.series.getData()[Math.round(widget.chart.getVisibleLogicalRange().from)].time).toBe(before);
    expect(complete).toHaveBeenCalledTimes(1);
    expect(widget.dataController?.getState().historyStatus).toBe('exhausted');
  });

  it('shows unsupported study state and retries through the indicator instance', async () => {
    let supported = false;
    const descriptor = createTier2Indicator({
      id: 'widget-managed-study', name: 'External value', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'Value', type: 'line' }],
      supports: () => supported, fetch: async () => [{ time: 60, values: { v: 33 } }],
    });
    registerIndicator(descriptor);
    const { widget, root } = make();
    widget.series.setData([bar(60)]);
    const indicator = widget.chart.addIndicator(descriptor.id);
    await flush();
    const status = root.querySelector('.oac-data-status')!;
    expect(status.textContent).toContain('External value: Unsupported');
    supported = true;
    status.querySelector('button')!.click();
    await flush();
    expect(indicator.values().v).toEqual([33]);
    expect(status.hidden).toBe(true);
    widget.chart.removeIndicator(indicator.id);
    expect(widget.chart.panes()).toHaveLength(1);
  });

  it('says why a study its inputs refuse is off, with no Retry that cannot help', async () => {
    registerIndicator({
      id: 'widget-refused-study', name: 'Session fold', placement: 'onchart',
      inputs: [{ key: 'mode', type: 'select', label: 'Mode', default: 'plain', options: [{ value: 'plain', label: 'Plain' }, { value: 'fold', label: 'Fold' }, { value: 'broken', label: 'Broken' }] }],
      plots: [{ key: 'v', title: 'Value', type: 'line' }],
      calc: (bars, settings) => {
        if (settings.mode === 'fold') throw new IndicatorInputError('Session fold: this chart draws transformed bars, which cannot be folded');
        if (settings.mode === 'broken') throw new Error('division by zero');
        return { v: bars.map(b => b.close) };
      },
    });
    const { widget, root } = make();
    widget.series.setData(Array.from({ length: 30 }, (_, i) => bar(i * 60, 10 + (i % 7) * 0.5)));
    const study = widget.chart.addIndicator('widget-refused-study');
    const status = root.querySelector('.oac-data-status')!;
    study.setSettings({ mode: 'fold' });
    await flush();
    expect(study.dataStatus()?.state).toBe('error');
    // The refusal names the study once, and a retry would be refused the same way.
    expect(status.textContent).toBe('Session fold: this chart draws transformed bars, which cannot be folded');
    expect(status.querySelector('button')).toBeNull();
    // Any other failure keeps the words and the retry it had.
    study.setSettings({ mode: 'broken' });
    await flush();
    expect(status.textContent).toContain('Session fold: Could not load');
    expect(status.querySelector('button')?.getAttribute('aria-label')).toBe('Retry Session fold');
    study.setSettings({ mode: 'plain' });
    await flush();
    expect(status.hidden).toBe(true);
  });

  it('holds replay bars while the managed store continues receiving live data', async () => {
    let push!: (value: Bar) => void;
    const { widget } = make({ feed: { getBars: async () => [bar(60), bar(120)], subscribeBars: (_req, cb) => { push = cb; return () => {}; } } });
    await flush();
    widget.dataController?.setPaused(true);
    widget.series.setData([bar(60)]);
    push(bar(180));
    expect(widget.series.getData()).toEqual([bar(60)]);
    expect(widget.dataController?.bars()).toHaveLength(3);
    widget.dataController?.setPaused(false);
    expect(widget.series.getData()).toHaveLength(3);
  });
  it('restores a persisted viewport after the first asynchronous history arrives', async () => {
    const entries = new Map<string, string>();
    const storage = { getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => { entries.set(key, value); }, removeItem: (key: string) => { entries.delete(key); } };
    const first = make({ persist: 'view', storage }).widget;
    first.series.setData(Array.from({ length: 40 }, (_, i) => bar(i * 60)));
    first.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    const view = first.chart.getVisibleLogicalRange();
    first.destroy();
    const second = make({ persist: 'view', storage, feed: { getBars: async () => Array.from({ length: 40 }, (_, i) => bar(i * 60)) } }).widget;
    await flush();
    expect(second.chart.getVisibleLogicalRange()).toEqual(view);
    second.setSymbol('BBB');
    await flush();
    expect(second.chart.getVisibleLogicalRange()).not.toEqual(view);
  });

  it('keeps a pending saved viewport scoped to its original instrument', async () => {
    const entries = new Map<string, string>();
    const storage = { getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => { entries.set(key, value); }, removeItem: (key: string) => { entries.delete(key); } };
    const first = make({ persist: 'pending-view', storage }).widget;
    first.series.setData(Array.from({ length: 40 }, (_, i) => bar(i * 60)));
    first.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    const view = first.chart.getVisibleLogicalRange();
    first.destroy();
    const second = make({ persist: 'pending-view', storage, feed: { getBars: req => req.symbol === 'AAA'
      ? new Promise(() => {}) : Promise.resolve(Array.from({ length: 40 }, (_, i) => bar(i * 60))) } }).widget;
    second.setSymbol('BBB');
    await flush();
    expect(second.chart.getVisibleLogicalRange()).not.toEqual(view);
  });

  it('updates study context for a host supplying bars without a feed', () => {
    const { widget } = make();
    widget.series.setData([bar(60)]);
    widget.setInterval('5m');
    expect(widget.chart.getDataContext()?.interval).toBe('5m');
    expect(widget.series.getData()).toEqual([]);
  });

  it('threads pagination and the optional controller clock through the public options', async () => {
    let pageRequest: BarsRequest | undefined;
    let initialRequest: BarsRequest | undefined;
    const { widget } = make({ loading: { now: () => 9000, pageSize: 7, pageWindowSec: 120 }, feed: {
      getBars: async request => { initialRequest = request; return [bar(600)]; },
      getBarsPage: async request => { pageRequest = request; return { bars: [], hasMore: false }; },
    } });
    await flush();
    expect(initialRequest?.to).toBe(9000);
    await widget.dataController?.loadMore();
    expect(pageRequest?.countBack).toBe(7);
    expect(pageRequest?.from).toBe(480);
  });

  it('does not restore a saved view onto another exchange', async () => {
    const entries = new Map<string, string>();
    const storage = { getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => { entries.set(key, value); }, removeItem: (key: string) => { entries.delete(key); } };
    const first = make({ persist: 'exchange-view', storage }).widget;
    first.series.setData(Array.from({ length: 40 }, (_, i) => bar(i * 60)));
    first.chart.setVisibleLogicalRange({ from: 5, to: 15 });
    const view = first.chart.getVisibleLogicalRange();
    first.destroy();
    const second = make({ persist: 'exchange-view', storage, exchange: 'Y', feed: {
      getBars: async () => Array.from({ length: 40 }, (_, i) => bar(i * 60)),
    } }).widget;
    await flush();
    expect(second.chart.getVisibleLogicalRange()).not.toEqual(view);
  });

  it('counts one loaded bar in the singular', async () => {
    const { root } = make({ feed: { getBars: async () => [bar(600)] } });
    await flush();
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('1 bar');
  });

  it('releases a failed paging gesture and exposes a working older-history retry', async () => {
    const hook = vi.spyOn(Chart.prototype, 'setHistoryLoader');
    let calls = 0;
    const { widget, root } = make({ feed: {
      getBars: async () => [bar(600), bar(660)],
      getBarsPage: async () => {
        if (++calls === 1) throw new Error('older history unavailable');
        return { bars: [bar(540)], hasMore: false };
      },
    } });
    await flush();
    const complete = vi.spyOn(widget.chart, 'historyLoadComplete');
    hook.mock.calls[0][0]();
    await flush();
    expect(complete).toHaveBeenCalledTimes(1);
    const retry = root.querySelector('button[aria-label="Retry older history"]')!;
    expect(retry).not.toBeNull();
    retry.click();
    await flush();
    expect(widget.series.getData().map(value => value.time)).toEqual([540, 600, 660]);
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('3 bars');
    expect(widget.dataController?.getState().historyStatus).toBe('exhausted');
  });

  it('shows a retention limit without claiming the provider has no older bars', async () => {
    const { widget, root } = make({ loading: { maxBars: 3 }, feed: {
      getBars: async () => [bar(600), bar(660)],
      getBarsPage: async () => ({ bars: [bar(480), bar(540)], hasMore: true }),
    } });
    await flush();
    await widget.dataController?.loadMore();
    expect(root.querySelector('.oac-data-status')?.textContent).toContain('History retention limit reached');
    expect(widget.dataController?.getState().hasMore).toBe(true);
  });

});
