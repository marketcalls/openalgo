import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import type { SymbolSearchRequest } from '../src/feed/types';
import { mountSymbolPicker } from '../src/widget/symbol-picker';
import { mountQuickEntry } from '../src/widget/quick-entry';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, FakeEvent, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const live: Widget[] = [];
afterEach(() => { for (const widget of live.splice(0)) if (!widget.isDestroyed) widget.destroy(); vi.useRealTimers(); });

function make() {
  const doc = fakeWidgetDocument();
  const host = fakeContainer(doc);
  const widget = createWidget(host as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    topbar: false,
    mobile: 'never',
  });
  live.push(widget);
  const input = doc.createElement('input');
  widget.root.appendChild(input as unknown as HTMLElement);
  return { doc, widget, input, root: widget.root as unknown as FakeElement };
}

describe('shared symbol picker', () => {
  it('does not select or repaint previous hits while a new query is pending', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const selected = vi.fn();
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: query => query === 'a' ? [{ symbol: 'A', exchange: 'NSE', assetClass: 'Equity' },
        { symbol: 'AA', exchange: 'BSE', assetClass: 'Index' }] : [{ symbol: 'B', exchange: 'NSE' }],
      onSelect: selected,
    });
    input.focus(); input.value = 'a'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    expect(root.querySelectorAll('.oac-symbol-picker__row')).toHaveLength(2);
    input.value = 'b'; fire(input, 'input');
    fireKey(input, 'ArrowDown');
    expect(root.querySelectorAll('.oac-symbol-picker__row')).toHaveLength(0);
    fireKey(input, 'Enter');
    expect(selected).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(150);
    fireKey(input, 'Enter');
    expect(selected).toHaveBeenCalledOnce();
    expect(selected).toHaveBeenCalledWith('B', 'NSE');
    picker.destroy();
  });

  it('leaves composition confirmation Enter to the input method', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const selected = vi.fn();
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: () => [{ symbol: 'NSEI', exchange: 'NSE' }], onSelect: selected,
    });
    input.focus(); input.value = 'n'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    const composing = Object.assign(new FakeEvent('keydown', { key: 'Enter' }), { isComposing: true });
    input.dispatchEvent(composing);
    const confirm = Object.assign(new FakeEvent('keydown', { key: 'Enter' }), { keyCode: 229 });
    input.dispatchEvent(confirm);
    expect(selected).not.toHaveBeenCalled();
    expect(root.querySelector('.oac-symbol-picker__row')).not.toBeNull();
    fireKey(input, 'Enter');
    expect(selected).toHaveBeenCalledWith('NSEI', 'NSE');
    picker.destroy();
  });

  it('ignores earlier answers and answers after close or context change', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const pending: Array<(hits: readonly { symbol: string }[]) => void> = [];
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: () => new Promise(resolve => pending.push(resolve)),
      onSelect: () => {},
      context: () => widget.symbol(),
    });
    input.focus();
    input.value = 'a'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    input.value = 'ab'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    pending[0]([{ symbol: 'OLD' }]); await Promise.resolve();
    expect(root.querySelector('.oac-symbol-picker__row')).toBeNull();
    pending[1]([{ symbol: 'NEW' }]); await Promise.resolve();
    expect(root.querySelector('.oac-symbol-picker__row')?.textContent).toContain('NEW');
    input.value = 'abc'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    widget.setSymbol('OTHER');
    pending[2]([{ symbol: 'STALE' }]); await Promise.resolve();
    expect(root.querySelector('.oac-symbol-picker__row')).toBeNull();
    picker.close();
    expect(root.querySelector('.oac-symbol-picker__row')).toBeNull();
    picker.destroy();
  });

  it('filters categories and expands host contracts with their own exchange', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const selected: Array<[string, string | undefined]> = [];
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: () => [
        { symbol: 'CASH', exchange: 'NSE', assetClass: 'Equity' },
        { symbol: 'ROOT', exchange: 'NFO', assetClass: 'Futures', contractGroup: { label: 'Expiry', contracts: [
          { symbol: 'ROOT26OCT', exchange: 'NFO' }, { symbol: 'ROOT26NOV', exchange: 'BFO' },
        ] } },
      ],
      onSelect: (symbol, exchange) => selected.push([symbol, exchange]),
    });
    input.focus(); input.value = 'r'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    // Focus stays in the field: a host that restores its text on blur would otherwise void the press.
    expect(fire(root.querySelector('.oac-symbol-picker__row')!, 'mousedown', { bubbles: true }).defaultPrevented).toBe(true);
    const futures = root.querySelectorAll('.oac-symbol-picker__category').find(el => el.textContent === 'Futures')!;
    futures.click();
    expect(root.querySelectorAll('.oac-symbol-picker__row')).toHaveLength(1);
    (root.querySelector('.oac-symbol-picker__row') as FakeElement).click();
    expect(root.querySelectorAll('.oac-symbol-picker__row')).toHaveLength(2);
    root.querySelectorAll('.oac-symbol-picker__row')[1].click();
    expect(selected).toEqual([['ROOT26NOV', 'BFO']]);
    picker.destroy();
  });

  it('renders provider strings as text and rejects unsafe icon URLs', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: () => [{ symbol: '<script>', name: '<img src=x>', iconUrl: 'javascript:alert(1)' }],
      onSelect: () => {},
    });
    input.focus(); input.value = 'x'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    expect(root.querySelector('.oac-symbol-picker__row')?.textContent).toContain('<img src=x>');
    expect(root.querySelector('.oac-symbol-picker__row img')).toBeNull();
    picker.destroy();
  });

  it('cancels a superseded lookup and shows a failure while typed entry stays available', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    const signals: AbortSignal[] = [];
    let fail = false;
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: (_query, context) => {
        signals.push(context!.signal);
        return fail ? Promise.reject(new Error('backend detail')) : new Promise(() => {});
      },
      onSelect: () => {},
    });
    input.focus(); input.value = 'a'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    input.value = 'ab'; fire(input, 'input');
    expect(signals[0].aborted).toBe(true);
    fail = true;
    await vi.advanceTimersByTimeAsync(150);
    expect(signals[1].aborted).toBe(false);
    const status = root.querySelector('.oac-symbol-picker__status') as FakeElement;
    expect(status.textContent).toBe('Search unavailable');
    expect(status.getAttribute('role')).toBe('status');
    expect(root.textContent).not.toContain('backend detail');
    expect(picker.canCommitRaw()).toBe(true);
    picker.close();
    expect(signals[1].aborted).toBe(true);
    picker.destroy();
  });

  it('drops a result if the context changes without a widget bus event', async () => {
    vi.useFakeTimers();
    const { widget, input, root } = make();
    let context = 'first';
    let answer!: (hits: readonly { symbol: string }[]) => void;
    const picker = mountSymbolPicker(widget.context, input as unknown as HTMLInputElement, {
      search: () => new Promise(resolve => { answer = resolve; }), onSelect: () => {}, context: () => context,
    });
    input.focus(); input.value = 'x'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    context = 'second'; answer([{ symbol: 'WRONG' }]); await Promise.resolve();
    expect(root.querySelector('.oac-symbol-picker__row')).toBeNull();
    picker.destroy();
  });
});

describe('widget search controls', () => {
  it.each(['desktop', 'mobile'])('uses category and contract selection on %s', async kind => {
    vi.useFakeTimers();
    const doc = fakeWidgetDocument();
    const host = fakeContainer(doc);
    const widget = createWidget(host as unknown as HTMLElement, {
      document: doc as unknown as Document,
      pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      mobile: kind === 'mobile' ? 'always' : 'never',
      symbolSearch: () => [
        { symbol: 'ABC', exchange: 'NSE', assetClass: 'Equity' },
        { symbol: 'ROOT', exchange: 'NFO', assetClass: 'Futures', contractGroup: { contracts: [{ symbol: 'ROOT26OCT', exchange: 'BFO' }] } },
      ],
    });
    live.push(widget);
    const root = widget.root as unknown as FakeElement;
    const input = root.querySelector(kind === 'mobile' ? '.oac-mobile__symbol' : '.oac-sym__input') as FakeElement;
    input.focus(); input.value = 'root'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    root.querySelectorAll('.oac-symbol-picker__category').find(el => el.textContent === 'Futures')!.click();
    (root.querySelector('.oac-symbol-picker__row') as FakeElement).click();
    (root.querySelector('.oac-symbol-picker__row') as FakeElement).click();
    expect(widget.symbol()).toBe('ROOT26OCT');
    expect(widget.exchange()).toBe('BFO');
  });
});

describe('Enter while a search is pending', () => {
  it.each(['desktop', 'mobile'])('waits for the lookup on %s instead of charting the typed text', async kind => {
    vi.useFakeTimers();
    let answer!: (hits: readonly { symbol: string; exchange: string }[]) => void;
    const doc = fakeWidgetDocument();
    const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      mobile: kind === 'mobile' ? 'always' : 'never', symbol: 'RELIANCE', exchange: 'NSE',
      symbolSearch: () => new Promise(resolve => { answer = resolve; }),
    });
    live.push(widget);
    const root = widget.root as unknown as FakeElement;
    const input = root.querySelector(kind === 'mobile' ? '.oac-mobile__symbol' : '.oac-sym__input') as FakeElement;
    input.focus(); input.value = 'rel'; fire(input, 'input');
    fireKey(input, 'Enter');
    expect(widget.symbol()).toBe('RELIANCE');
    await vi.advanceTimersByTimeAsync(150);
    fireKey(input, 'Enter');
    expect(widget.symbol()).toBe('RELIANCE');
    answer([{ symbol: 'RELINFRA', exchange: 'BSE' }]); await vi.advanceTimersByTimeAsync(0);
    fireKey(input, 'Enter');
    expect(widget.symbol()).toBe('RELINFRA');
    expect(widget.exchange()).toBe('BSE');
  });
});

describe('search through the feed', () => {
  function feedWidget(options: Partial<WidgetOptions>) {
    const doc = fakeWidgetDocument();
    const host = fakeContainer(doc);
    const widget = createWidget(host as unknown as HTMLElement, {
      document: doc as unknown as Document,
      pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      mobile: 'never', symbol: 'RELIANCE', exchange: 'NSE',
      ...options,
    });
    live.push(widget);
    const root = widget.root as unknown as FakeElement;
    return { widget, root, input: root.querySelector('.oac-sym__input') as FakeElement };
  }

  it('looks symbols up through the feed when the host passes no lookup', async () => {
    vi.useFakeTimers();
    const requests: SymbolSearchRequest[] = [];
    const { widget, root, input } = feedWidget({ feed: { getBars: async () => [], searchSymbols: async request => {
      requests.push(request);
      return [{ symbol: 'INFY', exchange: 'BSE', name: 'INFOSYS LIMITED' }, { symbol: 'INFY', exchange: 'NSE', name: 'INFOSYS LIMITED' }];
    } } });
    input.focus(); input.value = 'infy'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    expect(requests).toHaveLength(1);
    expect(requests[0].query).toBe('infy');
    expect(requests[0].signal).toBeInstanceOf(AbortSignal);
    const rows = root.querySelectorAll('.oac-symbol-picker__row');
    // The exact symbol on the chart's own exchange comes first, so Enter keeps the venue.
    expect(rows.map(row => row.querySelector('.oac-menu__label')!.textContent)).toEqual(['NSE:INFY', 'BSE:INFY']);
    fireKey(input, 'Enter');
    expect(widget.symbol()).toBe('INFY');
    expect(widget.exchange()).toBe('NSE');
  });

  it('prefers the host lookup over the feed', async () => {
    vi.useFakeTimers();
    const searchSymbols = vi.fn(async () => [{ symbol: 'FEED', exchange: 'NSE' }]);
    const { root, input } = feedWidget({
      feed: { getBars: async () => [], searchSymbols },
      symbolSearch: () => [{ symbol: 'HOST', exchange: 'NSE' }],
    });
    input.focus(); input.value = 'x'; fire(input, 'input'); await vi.advanceTimersByTimeAsync(150);
    expect(root.querySelector('.oac-symbol-picker__row')?.textContent).toContain('HOST');
    expect(searchSymbols).not.toHaveBeenCalled();
  });
});

describe('direct keyboard entry', () => {
  it('commits the highlighted exchange-qualified hit once', async () => {
    vi.useFakeTimers();
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    const onSymbol = vi.fn();
    const entry = mountQuickEntry(widget.context, {
      enabled: () => true, onSymbol, onInterval: () => {},
      search: () => [{ symbol: 'ROOT26OCT', exchange: 'NFO' }, { symbol: 'ROOT26NOV', exchange: 'BFO' }],
    });
    fireKey(chart, 'r');
    await vi.advanceTimersByTimeAsync(150);
    const input = root.querySelector('.oac-quick-entry__input') as FakeElement;
    fireKey(input, 'ArrowDown');
    fireKey(input, 'Enter');
    expect(onSymbol).toHaveBeenCalledTimes(1);
    expect(onSymbol).toHaveBeenCalledWith('ROOT26NOV', 'BFO');
    entry.destroy();
  });

  it('waits for active symbol search before allowing raw entry', async () => {
    vi.useFakeTimers();
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    let answer!: (hits: readonly { symbol: string; exchange: string }[]) => void;
    const onSymbol = vi.fn();
    const entry = mountQuickEntry(widget.context, {
      enabled: () => true, onSymbol, onInterval: () => {},
      search: () => new Promise(resolve => { answer = resolve; }),
    });
    fireKey(chart, 'r');
    await vi.advanceTimersByTimeAsync(150);
    const input = root.querySelector('.oac-quick-entry__input') as FakeElement;
    fireKey(input, 'Enter');
    expect(onSymbol).not.toHaveBeenCalled();
    answer([{ symbol: 'ROOT26OCT', exchange: 'NFO' }]); await Promise.resolve();
    fireKey(input, 'Enter');
    expect(onSymbol).toHaveBeenCalledWith('ROOT26OCT', 'NFO');
    entry.destroy();
  });

  it('maps a numeric minute count to a recognized interval and reserves Digit0', () => {
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    const entry = mountQuickEntry(widget.context, { enabled: () => true, onSymbol: () => {}, onInterval: code => widget.setInterval(code) });
    fireKey(chart, '0', { code: 'Digit0' });
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    fireKey(chart, '1', { code: 'Digit1' });
    const input = root.querySelector('.oac-quick-entry__input') as FakeElement;
    input.value = '15'; fireKey(input, 'Enter');
    expect(widget.interval()).toBe('15m');
    entry.destroy();
  });

  it('opens symbol and interval entry only when eligible and preserves shortcut keys', () => {
    const { doc, widget, root } = make();
    const chart = doc.createElement('div');
    chart.tabIndex = 0;
    root.appendChild(chart);
    let eligible = true;
    const entry = mountQuickEntry(widget.context, {
      enabled: () => eligible,
      onSymbol: (symbol) => widget.setSymbol(symbol),
      onInterval: (interval) => widget.setInterval(interval),
    });
    chart.focus();
    fireKey(chart, 'r');
    const symbol = root.querySelector('.oac-quick-entry__input') as FakeElement;
    expect(symbol).not.toBeNull();
    expect(symbol.value).toBe('r');
    fireKey(symbol, 'Escape');
    eligible = false;
    fireKey(chart, 'x');
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    eligible = true;
    widget.context.keymap.register('d', () => {}, 'widget');
    fireKey(chart, 'd');
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    entry.destroy();
  });

  it('validates interval codes without changing the chart and ignores editable and modifier keys', () => {
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    const entry = mountQuickEntry(widget.context, { enabled: () => true, onSymbol: () => {}, onInterval: code => widget.setInterval(code) });
    fireKey(chart, '5');
    const input = root.querySelector('.oac-quick-entry__input') as FakeElement;
    input.value = '5q'; fireKey(input, 'Enter');
    expect(widget.interval()).toBe('1d');
    expect(root.querySelector('[role="alert"]')?.textContent).toContain('recognized interval');
    input.value = '5m'; fireKey(input, 'Enter');
    expect(widget.interval()).toBe('5m');
    const editable = doc.createElement('input'); root.appendChild(editable); editable.focus();
    fireKey(editable, '3');
    fireKey(chart, '6', { ctrlKey: true });
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    entry.destroy();
  });

  it('leaves composition, overlays and active drawing tools to their owners', () => {
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    const entry = mountQuickEntry(widget.context, { enabled: () => true, onSymbol: () => {}, onInterval: () => {} });
    const composing = new FakeEvent('keydown', { key: 'a' });
    Object.assign(composing, { isComposing: true });
    chart.dispatchEvent(composing);
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    const overlay = doc.createElement('div');
    const closeOverlay = widget.context.openOverlay(overlay as unknown as HTMLElement, { initialFocus: null });
    fireKey(chart, 'a');
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    closeOverlay();
    widget.draw.setTool('trend-line');
    fireKey(chart, 'a');
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    entry.destroy();
  });

  it('closes an open entry when the chart context changes', () => {
    const { doc, widget, root } = make();
    const chart = doc.createElement('div'); chart.tabIndex = 0; root.appendChild(chart); chart.focus();
    const entry = mountQuickEntry(widget.context, { enabled: () => true, onSymbol: () => {}, onInterval: () => {} });
    fireKey(chart, 'r');
    expect(root.querySelector('.oac-quick-entry__input')).not.toBeNull();
    widget.setInterval('5m');
    expect(root.querySelector('.oac-quick-entry__input')).toBeNull();
    entry.destroy();
  });
});
