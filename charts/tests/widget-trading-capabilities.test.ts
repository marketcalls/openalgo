import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { ReplayController, type ContextMenuEvent, type TradingCapabilities } from '../src/index';
import { createWidget, contextMenuEntries, type MenuItem, type Widget, type WidgetOptions } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const widgets: Widget[] = [];
const replay: ReplayController[] = [];
afterEach(() => { for (const controller of replay.splice(0)) controller.stop(); for (const widget of widgets.splice(0)) widget.destroy(); });
function make(options: WidgetOptions = {}) {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, mobile: 'never', symbol: 'BHEL', exchange: 'NSE',
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} }, ...options,
  });
  widget.chart.applySize(800, 600);
  widget.series.setData([{ time: 1000, open: 100, high: 101, low: 99, close: 100 }, { time: 2000, open: 100, high: 102, low: 99, close: 101 }]);
  widgets.push(widget);
  return widget;
}
function event(): ContextMenuEvent {
  return { target: { kind: 'series', id: null, seriesType: 'candlestick' }, paneIndex: 0, price: 100, index: 0,
    time: 1000, point: { x: 100, y: 100 } } as unknown as ContextMenuEvent;
}
function orders(widget: Widget, hooks: Parameters<typeof contextMenuEntries>[2] = {}): MenuItem[] {
  return contextMenuEntries(widget.context, event(), hooks).filter((item): item is MenuItem => 'id' in item && item.id?.startsWith('order-') === true);
}

describe('widget trading capability and replay guards', () => {
  it('shows a disabled explanation when configured capabilities are unavailable', () => {
    const widget = make();
    const onOrder = vi.fn();
    const provider = vi.fn(() => { throw new Error('account unavailable'); });
    const plain = contextMenuEntries(widget.context, event(), { tradingCapabilities: provider });
    expect(provider).not.toHaveBeenCalled();
    expect(plain.some(item => 'id' in item && item.id === 'trading-unavailable')).toBe(false);
    const entries = contextMenuEntries(widget.context, event(), { onOrder, tradingCapabilities: provider });
    const diagnostic = entries.find(item => 'id' in item && item.id === 'trading-unavailable');
    expect(diagnostic).toMatchObject({ disabled: true, label: 'Order entry is unavailable', note: 'Trading capabilities are unavailable' });
    expect('run' in diagnostic!).toBe(false);
    expect(onOrder).not.toHaveBeenCalled();
  });

  it('preserves legacy order routes and hides explicitly unsupported placement and types', () => {
    const widget = make();
    const onOrder = vi.fn();
    expect(orders(widget, { onOrder })).toHaveLength(6);
    expect(orders(widget, { onOrder, tradingCapabilities: { place: false } })).toEqual([]);
    expect(orders(widget, { onOrder, tradingCapabilities: { orderTypes: ['LIMIT'] } }).map(row => row.id))
      .toEqual(['order-buy-limit', 'order-sell-limit']);
    expect(orders(widget, { onOrder, tradingCapabilities: { place: 'unknown' } })).toEqual([]);
    expect(orders(widget, { onOrder, tradingCapabilities: { modes: ['analyzer'] } })).toEqual([]);
    expect(orders(widget, { onOrder, tradingCapabilities: { modes: ['analyzer'] }, tradingMode: 'analyzer' })).toHaveLength(6);
    expect(orders(widget, { onOrder, tradingCapabilities: () => { throw new Error('unavailable'); } })).toEqual([]);
  });

  it('rechecks account capabilities before a stale menu callback can invoke the host', () => {
    const widget = make();
    const onOrder = vi.fn();
    let capabilities: TradingCapabilities = { place: true };
    const provider = vi.fn(() => capabilities);
    const row = orders(widget, { onOrder, tradingCapabilities: provider })[0];
    capabilities = { place: false };
    row.run?.();
    expect(onOrder).not.toHaveBeenCalled();
    expect(provider).toHaveBeenLastCalledWith(expect.objectContaining({ operation: 'place', type: 'MARKET', symbol: 'BHEL', exchange: 'NSE' }));
    expect(widget.root.textContent).toContain('Order entry is unavailable');
    capabilities = { place: true };
    row.run?.();
    expect(onOrder).toHaveBeenCalledTimes(1);
  });

  it('blocks active replay and a host replay selection lock at callback time', () => {
    const widget = make();
    const onOrder = vi.fn();
    let locked = false;
    const hooks = { onOrder, tradingLocked: () => locked };
    const row = orders(widget, hooks)[0];
    locked = true;
    row.run?.();
    expect(onOrder).not.toHaveBeenCalled();
    expect(orders(widget, hooks).every(item => item.disabled)).toBe(true);
    locked = false;
    const controller = new ReplayController(widget.chart, { startIndex: 0 });
    replay.push(controller);
    row.run?.();
    expect(onOrder).not.toHaveBeenCalled();
    expect(orders(widget, hooks).every(item => item.disabled)).toBe(true);
    controller.stop();
    row.run?.();
    expect(onOrder).toHaveBeenCalledTimes(1);
  });

  it('fails closed after context changes, destroy or throwing host locks', () => {
    const widget = make();
    const onOrder = vi.fn();
    const row = orders(widget, { onOrder })[0];
    widget.setSymbol('INFY');
    row.run?.();
    expect(onOrder).not.toHaveBeenCalled();
    const locked = orders(widget, { onOrder, tradingLocked: () => { throw new Error('host unavailable'); } })[0];
    expect(locked.disabled).toBe(true);
    locked.run?.();
    expect(onOrder).not.toHaveBeenCalled();
    expect(widget.root.textContent).toContain('Order entry is unavailable');
    const latest = orders(widget, { onOrder })[0];
    widget.destroy();
    latest.run?.();
    expect(onOrder).not.toHaveBeenCalled();
  });

  it('threads widget options into the actual menu and blocks a lock changed after opening', () => {
    const onOrder = vi.fn();
    let locked = false;
    const widget = make({ onOrder, tradingCapabilities: { orderTypes: ['LIMIT'] }, tradingLocked: () => locked,
      translate: (_key, fallback) => `Local ${fallback}` });
    widget.chart.emit('contextmenu', { ...event(), preventDefault: () => {} });
    const root = widget.root as unknown as FakeElement;
    expect(root.querySelector('[data-act="order-buy-market"]')).toBeNull();
    const buy = root.querySelector('[data-act="order-buy-limit"]')!;
    expect(buy.textContent).toBe('Local Buy limit at 100.00');
    locked = true;
    fire(buy, 'click');
    expect(onOrder).not.toHaveBeenCalled();
    expect(root.querySelector('.oac-statusline__msg')?.textContent).toBe('Local Order entry is locked by the host');
  });
});
