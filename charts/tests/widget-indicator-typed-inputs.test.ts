import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, darkTheme, registerIndicator, type IndicatorInput } from 'openalgo-charts';
import { DrawingController } from 'openalgo-charts/draw';
import { controlsFromInputs } from '../src/widget/form';
import { mountIndicatorSettings } from '../src/widget/dialogs/indicator-settings';
import { createOverlayStack, WidgetBus, WidgetStorage, type WidgetContext } from '../src/widget/context';
import { installDom, asDoc, asEl, type FakeElement } from './widget-form.test';
import type { SymbolSearch } from '../src/widget/symbol-picker';

let serial = 0;
const cleanups: (() => void)[] = [];
const inputs = [
  { key: 'instrument', type: 'symbol', label: 'Instrument', default: 'AAA', exchangeKey: 'venue' },
  { key: 'venue', type: 'text', label: 'Venue', default: 'X1' },
  { key: 'hours', type: 'session', label: 'Session', default: '0900-1700:23456' },
  { key: 'note', type: 'multiline', label: 'Notes', default: 'first\nsecond' },
  { key: 'level', type: 'price', label: 'Price', default: 12.345678901234567, min: 0, max: 100, step: 0.01, pick: true },
  { key: 'when', type: 'timestamp', label: 'Instant', default: 1700000000.125, pick: true },
  { key: 'wall', type: 'time', label: 'Wall time', default: '2026-03-12 09:30' },
] satisfies IndicatorInput[];

function fixture(options: { symbolSearch?: SymbolSearch; mixed?: boolean; inputs?: IndicatorInput[]; paneIndex?: number } = {}) {
  const dom = installDom(), doc = asDoc(dom.doc);
  const chart = new Chart(asEl(dom.chartEl), { document: doc, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  chart.applySize(900, 600);
  chart.addSeries('line').setData([1, 2, 3].map((close, index) => ({
    time: 1700000000 + index * 60, open: close, high: close, low: close, close,
  })));
  const id = `typed-host-${++serial}`;
  registerIndicator({ id, name: 'Typed host inputs', placement: 'onchart', inputs: options.inputs ?? inputs,
    plots: [{ key: 'value', title: 'Value', type: 'line' }, ...(options.mixed ? [{ key: 'second', title: 'Second', type: 'line' as const }] : [])],
    calc: (bars, settings) => ({ value: bars.map(() => settings.level as number), second: bars.map(() => 0.5) }) });
  const inst = chart.addIndicator(id, {}, { paneIndex: options.paneIndex }), draw = new DrawingController(chart);
  const overlays = createOverlayStack(asEl(dom.root), doc);
  const ctx: WidgetContext = { chart, draw, root: asEl(dom.root), document: doc, theme: 'dark', chartTheme: darkTheme,
    keymap: {} as WidgetContext['keymap'], bus: new WidgetBus(), storage: new WidgetStorage('typed', null), locale: undefined,
    toast: vi.fn(() => ({ node: doc.createElement('div'), dismiss() {} })), status() {},
    openOverlay: (node, options) => overlays.open(node, options), overlays,
    tips: { attach() {}, refreshLabel() {}, show() {}, hide() {}, target: () => null, destroy() {} },
    symbol: () => ({ symbol: 'PRIMARY', exchange: 'HOST' }), interval: () => '1m', symbolSearch: options.symbolSearch };
  const panel = mountIndicatorSettings(ctx, undefined, { instanceId: inst.id });
  cleanups.push(() => { overlays.destroy(); draw.destroy(); chart.destroy(); });
  const root = dom.root;
  const field = (key: string): FakeElement => {
    const result = root.querySelector(`#oac-ind-${inst.id}-${key}`);
    expect(result, `field ${key}`).not.toBeNull();
    return result!;
  };
  const button = (label: string): FakeElement => {
    const result = root.querySelectorAll('button').find(node => node.textContent === label);
    expect(result, `button ${label}`).toBeDefined();
    return result!;
  };
  return { dom, ctx, chart, draw, inst, panel, root, overlays, field, button };
}

afterEach(() => { for (const dispose of cleanups.splice(0).reverse()) dispose(); vi.useRealTimers(); });

describe('typed indicator host controls', () => {
  it('maps every new native kind while preserving legacy wall-time strings', () => {
    expect(controlsFromInputs(inputs).map(input => input.kind)).toEqual([
      'symbol', 'text', 'session', 'multiline', 'price', 'timestamp', 'text',
    ]);
  });

  it('preserves multiline text literally and applies prices through the actual study', () => {
    const h = fixture(), note = h.field('note'), price = h.field('level');
    expect(note.tagName).toBe('TEXTAREA');
    expect(price.value).toBe('12.345678901234567');
    note.value = '  <b>literal</b>\nnext\n'; note.fire('change');
    price.value = '23.125'; price.fire('change');
    expect(h.inst.settings().note).toBe('  <b>literal</b>\nnext\n');
    expect(h.inst.values().value).toEqual([23.125, 23.125, 23.125]);
    h.button('Cancel').click();
    expect(h.inst.settings().note).toBe('first\nsecond');
    expect(h.inst.settings().level).toBe(12.345678901234567);
  });

  it('keeps blank and out-of-bounds price drafts without coercion or tab loss', () => {
    const h = fixture(), price = h.field('level');
    for (const raw of ['', '-2', '1e309']) {
      price.value = raw; price.fire('change');
      expect(price.value).toBe(raw);
      expect(price.getAttribute('aria-invalid')).toBe('true');
      expect(h.inst.settings().level).toBe(12.345678901234567);
      h.button('Style').click(); expect(h.field('level').value).toBe(raw);
      h.button('OK').click(); expect(h.panel.isOpen()).toBe(true);
    }
    price.value = '0'; price.fire('change');
    expect(h.inst.settings().level).toBe(0);
    h.button('OK').click(); expect(h.panel.isOpen()).toBe(false);
  });

  it('displays absolute seconds explicitly and retains subsecond values unchanged', () => {
    const h = fixture();
    expect(h.field('when').value).toBe('1700000000.125');
    expect(h.root.textContent).toContain('UTC seconds');
    expect(h.field('wall').value).toBe('2026-03-12 09:30');
    const when = h.field('when'); when.value = '5e-324'; when.fire('change');
    expect(h.inst.settings().when).toBe(Number.MIN_VALUE);
    h.button('OK').click(); expect(h.inst.settings().when).toBe(Number.MIN_VALUE);
  });

  it('retains malformed sessions until corrected and restores defaults explicitly', () => {
    const h = fixture(), session = h.field('hours');
    session.value = '0960-1700'; session.fire('change');
    expect(session.value).toBe('0960-1700');
    expect(session.getAttribute('aria-invalid')).toBe('true');
    expect(h.inst.settings().hours).toBe('0900-1700:23456');
    h.button('Defaults').click();
    expect(h.field('hours').value).toBe('0900-1700:23456');
    h.field('hours').value = '2200-0200:23456'; h.field('hours').fire('change');
    expect(h.inst.settings().hours).toBe('2200-0200:23456');
  });

  it('keeps manual instrument entry available without a search provider', () => {
    const h = fixture(), symbol = h.field('instrument');
    const search = h.button('Search');
    expect(search.disabled).toBe(true); expect(search.title).not.toBe('');
    symbol.value = 'venue:contract'; symbol.fire('change');
    expect(h.inst.settings().instrument).toBe('venue:contract');
    expect(h.ctx.symbol()).toEqual({ symbol: 'PRIMARY', exchange: 'HOST' });
  });

  it('commits searched symbol and exchange as one settings patch without changing the chart symbol', async () => {
    vi.useFakeTimers();
    const h = fixture({ symbolSearch: () => [{ symbol: 'SAME', exchange: 'X2' }] });
    const writes = vi.spyOn(h.inst, 'setSettings');
    h.field('instrument').value = 'sam'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    // A mouse result press first blurs the edited field and fires change.
    h.field('instrument').fire('change');
    h.field('instrument').fire('keydown', { key: 'Enter' });
    expect(writes).toHaveBeenCalledTimes(1);
    expect(writes).toHaveBeenCalledWith({ instrument: 'SAME', venue: 'X2' });
    expect(h.inst.settings()).toMatchObject({ instrument: 'SAME', venue: 'X2' });
    expect(h.ctx.symbol()).toEqual({ symbol: 'PRIMARY', exchange: 'HOST' });
    h.button('Cancel').click();
    expect(h.inst.settings()).toMatchObject({ instrument: 'AAA', venue: 'X1' });
  });

  it('ignores symbol search results after the settings dialog closes', async () => {
    vi.useFakeTimers();
    let answer: (rows: { symbol: string }[]) => void = () => {};
    const h = fixture({ symbolSearch: () => new Promise(resolve => { answer = resolve; }) });
    h.field('instrument').value = 'late'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    h.button('Cancel').click();
    answer([{ symbol: 'LATE' }]); await Promise.resolve();
    expect(h.root.querySelector('.oac-symbol-picker')).toBeNull();
    expect(h.inst.settings().instrument).toBe('AAA');
  });

  it('suspends the modal and scrim for picking, then Escape restores the same session and focus', () => {
    const h = fixture(), trigger = h.root.querySelector('[data-input-action="level"]')!;
    trigger.focus(); trigger.click();
    expect(h.panel.el.hidden).toBe(true);
    expect(h.root.querySelector('.oac-scrim')!.hidden).toBe(true);
    expect(h.overlays.top()).toBeNull();
    expect(h.panel.isOpen()).toBe(true);
    h.dom.doc.activeElement!.fire('keydown', { key: 'Escape' });
    expect(h.panel.el.hidden).toBe(false);
    expect(h.root.querySelector('.oac-scrim')!.hidden).toBe(false);
    expect(h.dom.doc.activeElement).toBe(trigger);
    expect(h.inst.settings().level).toBe(12.345678901234567);
    h.dom.doc.activeElement!.fire('keydown', { key: 'Escape' });
    expect(h.panel.isOpen()).toBe(false);
  });

  it('targets the actual unique study scale and rejects ambiguous mixed scales', () => {
    const h = fixture({ mixed: true });
    h.inst.setPlotPriceScales({ value: 'left' });
    const trigger = h.root.querySelector('[data-input-action="level"]')!;
    expect(trigger.disabled).toBe(true); expect(trigger.title).toContain('explicit');
    h.inst.setPlotPriceScales({ second: 'left' });
    expect(trigger.disabled).toBe(false);
    const start = vi.spyOn(h.chart, 'beginPick');
    trigger.click();
    expect(start.mock.calls[0][0]).toBe('price');
    expect(start.mock.calls[0][2]).toEqual({ paneIndex: 0, priceScaleId: 'left' });
    h.button('Cancel pick').click();
  });

  it('does not arm a settings pick or cancel an active drawing', () => {
    const h = fixture(), trigger = h.root.querySelector('[data-input-action="level"]')!;
    vi.spyOn(h.draw, 'activeTool').mockReturnValue('line');
    const start = vi.spyOn(h.chart, 'beginPick'), cancel = vi.spyOn(h.draw, 'cancel');
    trigger.click();
    expect(start).not.toHaveBeenCalled(); expect(cancel).not.toHaveBeenCalled();
    expect(h.panel.el.hidden).toBe(false);
    expect(h.ctx.toast).toHaveBeenCalledWith(expect.stringContaining('active drawing'), 'info');
  });

  it('disposes an active pick when the edited study is removed', () => {
    const h = fixture(); h.root.querySelector('[data-input-action="level"]')!.click();
    expect(h.root.querySelector('.oac-input-pick')).not.toBeNull();
    h.inst.remove();
    expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    expect(h.panel.isOpen()).toBe(false);
  });

  it('restores nested overlay suspensions in either release order without trapping chart keys', () => {
    const h = fixture(), price = h.field('level'); price.focus();
    const first = h.overlays.suspend!(h.panel.el), second = h.overlays.suspend!(h.panel.el);
    const key = h.dom.chartEl.fire('keydown', { key: 'Tab' });
    expect(key.defaultPrevented).toBe(false);
    first(); expect(h.panel.el.hidden).toBe(true);
    second(); second();
    expect(h.panel.el.hidden).toBe(false);
    expect(h.root.querySelector('.oac-scrim')!.hidden).toBe(false);
    expect(h.dom.doc.activeElement).toBe(price);
  });

  it('uses a hidden scale in the study pane and resumes after a native pick', () => {
    const h = fixture({ paneIndex: 1 });
    h.inst.setPlotPriceScales({ value: 'overlay:typed' });
    const scale = h.inst.series('value')!.priceScale(); scale.setPriceRange({ min: 10, max: 30 });
    const trigger = h.root.querySelector('[data-input-action="level"]')!; trigger.click();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 80 }, price: -999, time: 1700000060, id: null });
    expect(h.panel.el.hidden).toBe(true);
    const expected = scale.yToPrice(80);
    h.chart.emit('click', { paneIndex: 1, point: { x: 250, y: 80 }, price: -999, time: 1700000060, id: null });
    expect(h.inst.settings().level).toBe(expected);
    expect(h.field('level').value).toBe(String(expected));
    expect(h.panel.el.hidden).toBe(false); expect(h.dom.doc.activeElement).toBe(trigger);
    h.root.querySelector('[data-input-action="when"]')!.click();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 80 }, price: 10, time: 1700000060.125, id: null });
    expect(h.inst.settings().when).toBe(1700000060);
    h.button('Cancel').click(); expect(h.inst.settings().level).toBe(12.345678901234567);
  });

  it('does not accept a stale host pick callback after closing the session', () => {
    const h = fixture(); let reply: (value: number) => void = () => {};
    const stop = Object.assign(vi.fn(), { active: () => true });
    vi.spyOn(h.chart, 'beginPick').mockImplementation((_kind, callback) => { reply = callback; return stop; });
    h.root.querySelector('[data-input-action="level"]')!.click();
    h.button('Cancel pick').click(); h.button('Cancel').click(); reply(70);
    expect(stop).toHaveBeenCalledTimes(1);
    expect(h.inst.settings().level).toBe(12.345678901234567);
    expect(h.panel.isOpen()).toBe(false);
  });

  it('cancels pending picking on data context replacement and permits a fresh pick', () => {
    const h = fixture(); h.root.querySelector('[data-input-action="level"]')!.click();
    h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' });
    expect(h.panel.el.hidden).toBe(false); expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 80 }, price: 70, time: 1700000060, id: null });
    expect(h.inst.settings().level).toBe(12.345678901234567);
    h.root.querySelector('[data-input-action="level"]')!.click();
    expect(h.panel.el.hidden).toBe(true); h.button('Cancel pick').click();
  });

  it('can cancel symbol selection when its exchange setting has no separate input', async () => {
    vi.useFakeTimers();
    const h = fixture({ inputs: inputs.filter(input => input.key !== 'venue'), symbolSearch: () => [{ symbol: 'SAME', exchange: 'X2' }] });
    const before = h.inst.settings();
    h.field('instrument').value = 'sam'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    expect(h.inst.settings()).toMatchObject({ instrument: 'SAME', venue: 'X2' });
    h.button('Cancel').click();
    expect(h.panel.isOpen()).toBe(false); expect(h.inst.settings()).toEqual(before);
  });

  it('resets the hidden exchange setting with the symbol in one Defaults write', async () => {
    vi.useFakeTimers();
    const h = fixture({ inputs: inputs.filter(input => input.key !== 'venue'), symbolSearch: () => [{ symbol: 'SAME', exchange: 'X2' }] });
    h.field('instrument').value = 'sam'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    const writes = vi.spyOn(h.inst, 'setSettings'); h.button('Defaults').click();
    expect(writes).toHaveBeenCalledTimes(1);
    expect(writes.mock.calls[0][0]).toMatchObject({ instrument: 'AAA', venue: '' });
    expect(h.inst.settings()).toMatchObject({ instrument: 'AAA', venue: '' });
  });

  it.each(['constructor', '__proto__'])('preserves the own exchange key %s through selection, Defaults and Cancel', async exchangeKey => {
    vi.useFakeTimers();
    const declared: IndicatorInput[] = inputs.filter(input => input.key !== 'venue')
      .map(input => input.type === 'symbol' ? { ...input, exchangeKey } : input);
    const h = fixture({ inputs: declared, symbolSearch: () => [{ symbol: 'SAME', exchange: 'X2' }] });
    const before = h.inst.settings();
    const select = async () => {
      h.field('instrument').value = 'sam'; h.field('instrument').fire('input');
      await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    };
    await select();
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('X2');
    expect(h.inst.settings().instrument).toBe('SAME');
    const writes = vi.spyOn(h.inst, 'setSettings');
    h.button('Defaults').click();
    expect(writes).toHaveBeenCalledTimes(1);
    expect(Object.getOwnPropertyDescriptor(writes.mock.calls[0][0], exchangeKey)?.value).toBe('');
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('');
    expect(h.inst.settings().instrument).toBe('AAA');
    await select();
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('X2');
    h.button('Cancel').click();
    expect(h.inst.settings()).toEqual(before);
    expect(Object.getPrototypeOf(h.inst.settings())).toBe(Object.prototype);
    expect(h.panel.isOpen()).toBe(false);
  });

  it('keeps an invalid draft when an unrelated study is removed', () => {
    const h = fixture(), other = h.chart.addIndicator(h.inst.indicatorId);
    h.field('level').value = '1e'; h.field('level').fire('change');
    other.remove();
    expect(h.field('level').value).toBe('1e');
    expect(h.field('level').getAttribute('aria-invalid')).toBe('true');
  });

  it('closes the session and disposes its pick when the native chart is destroyed', () => {
    const h = fixture(); h.root.querySelector('[data-input-action="level"]')!.click();
    h.chart.destroy();
    expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    expect(h.panel.isOpen()).toBe(false);
  });

  it('replaces an existing unrelated pick without treating its cancellation as the new pick ending', () => {
    const h = fixture(), previous = vi.fn(); h.chart.beginPick('time', previous);
    h.root.querySelector('[data-input-action="level"]')!.click();
    expect(h.panel.el.hidden).toBe(true);
    const expected = h.inst.series('value')!.priceScale().yToPrice(150);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 3, time: 1700000060, id: null });
    expect(previous).not.toHaveBeenCalled(); expect(h.inst.settings().level).toBe(expected);
    expect(h.panel.el.hidden).toBe(false);
  });

  it('yields to a same-kind replacement started by the previous pick cancellation', () => {
    const h = fixture(), newest = vi.fn(); h.chart.beginPick('price', vi.fn());
    const off = h.chart.on('pick:end', () => { off(); h.chart.beginPick('price', newest); });
    h.root.querySelector('[data-input-action="level"]')!.click();
    expect(h.panel.el.hidden).toBe(false); expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 3, time: 1700000060, id: null });
    expect(newest).toHaveBeenCalledExactlyOnceWith(3);
    expect(h.inst.settings().level).toBe(12.345678901234567);
  });

  it('resumes after synchronous cancellation from pick:start without a stale callback', () => {
    const h = fixture(), off = h.chart.on('pick:start', () => h.chart.setPlacementMode(true));
    h.root.querySelector('[data-input-action="level"]')!.click(); off();
    expect(h.panel.el.hidden).toBe(false); expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    h.chart.setPlacementMode(false);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 3, time: 1700000060, id: null });
    expect(h.inst.settings().level).toBe(12.345678901234567);
  });

  it('resumes when a successful pick notification replaces its callback with a newer pick', async () => {
    const h = fixture(), newest = vi.fn();
    const off = h.chart.on('pick:end', event => {
      if ((event as { value: number | null }).value === null) return;
      off(); h.chart.beginPick('price', newest);
    });
    h.root.querySelector('[data-input-action="level"]')!.click();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 3, time: 1700000060, id: null });
    await Promise.resolve();
    expect(h.inst.settings().level).toBe(12.345678901234567);
    expect(h.panel.el.hidden).toBe(false);
    expect(h.root.querySelector('.oac-input-pick')).toBeNull();
    expect(newest).not.toHaveBeenCalled();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 4, time: 1700000060, id: null });
    await Promise.resolve();
    expect(newest).toHaveBeenCalledExactlyOnceWith(4);
    expect(h.inst.settings().level).toBe(12.345678901234567);
    expect(h.panel.el.hidden).toBe(false);
    expect(h.panel.isOpen()).toBe(true);
  });

  it('ignores completed symbol lookups from a previous native data context', async () => {
    vi.useFakeTimers(); let answer: (rows: { symbol: string }[]) => void = () => {};
    const h = fixture({ symbolSearch: () => new Promise(resolve => { answer = resolve; }) });
    h.field('instrument').value = 'late'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' });
    answer([{ symbol: 'LATE' }]); await Promise.resolve();
    expect(h.root.querySelector('.oac-symbol-picker')).toBeNull();
    expect(h.inst.settings().instrument).toBe('AAA');
  });

  it('consumes the completed pick compatibility click but permits the next deliberate click', () => {
    const h = fixture(); h.root.querySelector('[data-input-action="level"]')!.click();
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: 3, time: 1700000060, id: null });
    expect(h.panel.el.hidden).toBe(false);
    const close = h.button('Cancel');
    expect(close.fire('click', { detail: 1 }).defaultPrevented).toBe(true);
    expect(h.panel.isOpen()).toBe(true);
    close.fire('pointerdown', { button: 0 }); close.fire('click', { detail: 1 });
    expect(h.panel.isOpen()).toBe(false);
  });
});

describe('a paired time and price in the settings dialog', () => {
  const paired = [
    { key: 'at', type: 'timestamp', label: 'Anchor time', default: 1700000000, pick: true },
    { key: 'level', type: 'price', label: 'Anchor price', default: 2, min: 0, max: 100, pick: true, timeKey: 'at', anchor: true },
  ] satisfies IndicatorInput[];

  it('picks both from one click and commits them as one patch', () => {
    const h = fixture({ inputs: paired });
    const trigger = h.root.querySelector('[data-input-action="level"]')!;
    expect(trigger.textContent).toBe('Pick point on chart');
    // The time keeps its own time-only pick.
    expect(h.root.querySelector('[data-input-action="at"]')!.textContent).toBe('Pick on chart');
    // Each names the input it picks, so two pick buttons never share one name.
    expect(trigger.getAttribute('aria-label')).toBe('Pick Anchor time and Anchor price on the chart');
    expect(h.root.querySelector('[data-input-action="at"]')!.getAttribute('aria-label')).toBe('Pick Anchor time on the chart');
    const start = vi.spyOn(h.chart, 'beginPick'), write = vi.spyOn(h.inst, 'setSettings');
    trigger.click();
    expect(start.mock.calls[0][0]).toBe('point');
    expect(start.mock.calls[0][2]).toEqual({ paneIndex: 0, priceScaleId: 'right' });
    expect(h.root.querySelector('.oac-input-pick')!.textContent).toContain('Pick Anchor time and Anchor price on the chart');
    const scale = h.chart.panes()[0].priceScale;
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 80 }, price: -999, time: 1700000060.4, id: null });
    expect(write).toHaveBeenCalledOnce();
    expect(write.mock.calls[0][0]).toEqual({ level: scale.yToPrice(80), at: 1700000060 });
    expect(h.inst.settings()).toMatchObject({ level: scale.yToPrice(80), at: 1700000060 });
    expect(h.field('at').value).toBe('1700000060');
    expect(h.field('level').value).toBe(String(scale.yToPrice(80)));
    expect(h.panel.el.hidden).toBe(false);
    h.button('Cancel').click();
    expect(h.inst.settings()).toMatchObject({ level: 2, at: 1700000000 });
  });

  it('writes neither half when the point pick is cancelled', () => {
    const h = fixture({ inputs: paired }), write = vi.spyOn(h.inst, 'setSettings');
    const start = vi.spyOn(h.chart, 'beginPick'), ends: unknown[] = [];
    h.chart.on('pick:end', payload => ends.push(payload));
    h.root.querySelector('[data-input-action="level"]')!.click();
    // The pick under way is the paired one, for both halves at once.
    expect(start.mock.calls.map(call => call[0])).toEqual(['point']);
    h.button('Cancel pick').click();
    expect(ends).toEqual([{ kind: 'point', value: null }]);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 80 }, price: 3, time: 1700000060, id: null });
    expect(write).not.toHaveBeenCalled();
    expect(h.inst.settings()).toMatchObject({ level: 2, at: 1700000000 });
    expect(h.field('at').value).toBe('1700000000');
    expect(h.panel.el.hidden).toBe(false);
  });
});
