/**
 * The point and figure and Renko settings dialog the top bar opens beside the
 * chart type while the chart builds one of them: its controls write the
 * transform's options and the renderer's colours through the chart's public
 * API, in one undo step, and what they write is saved and restored with the
 * layout.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { generateBars, getSeriesTransform, readChartSettings, type SeriesTransformSpec } from '../src/index';
import { createWidget, STATE_KEY, type Widget, type WidgetOptions } from '../src/widget/index';
import '../src/transform/index';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

/** A seeded random walk that trades like a stock, one bar a minute. */
const walk = generateBars(1_700_000_000, 240, 60);

function fed(options: WidgetOptions = {}): Widget {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, pixelRatio: () => 1,
    rail: false, panels: false, mobile: 'never', animZoom: false, animAutoscale: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} },
    symbol: 'AAA', exchange: 'X', interval: '1m', now: () => walk[walk.length - 1].time + 30,
    feed: { getBars: async () => walk.slice() }, ...options,
  });
  widgets.push(widget);
  widget.chart.applySize(800, 600);
  return widget;
}

const root = (widget: Widget): FakeElement => widget.root as unknown as FakeElement;
const typeButton = (widget: Widget): FakeElement => root(widget).querySelector('.oac-topbar__type-settings')!;
const dialog = (widget: Widget): FakeElement | null => root(widget).querySelector('.oac-ctset');
const spec = (widget: Widget): SeriesTransformSpec | null => widget.chart.seriesTransform(widget.series);

/** Open the dialog from the top bar, as a user does. */
function open(widget: Widget): FakeElement {
  expect(typeButton(widget).hidden).toBe(false);
  typeButton(widget).click();
  const found = dialog(widget);
  expect(found).not.toBeNull();
  return found!;
}

const sizeInput = (d: FakeElement): FakeElement => d.querySelector('.oac-ctset__size input')!;
const methodSelect = (d: FakeElement): FakeElement => d.querySelector('.oac-ctset__size select')!;
const atrInput = (d: FakeElement): FakeElement => d.querySelector('[data-key="atrPeriod"] input')!;
const radio = (d: FakeElement, value: string): FakeElement => d.querySelectorAll('.oac-ctset__radio input').find(input => input.value === value)!;
const preset = (d: FakeElement, percent: number): FakeElement => d.querySelector(`.oac-ctset__preset[data-percent="${percent}"]`)!;
const actions = (d: FakeElement): FakeElement[] => d.querySelectorAll('.oac-dialog__actions button');
const ok = (d: FakeElement): void => { actions(d)[1].click(); };
const cancel = (d: FakeElement): void => { actions(d)[0].click(); };

function type(input: FakeElement, value: string): void { input.value = value; fire(input, 'input'); }
function choose(select: FakeElement, value: string): void { select.value = value; fire(select, 'change'); }
function check(input: FakeElement): void { input.checked = true; fire(input, 'change'); }
/** Pick a colour the way the swatch's own input reports one. */
function color(d: FakeElement, key: string, value: string): void {
  const input = d.querySelectorAll('input[type="color"]').find(node => node.id.endsWith(`-${key.replace('.', '-')}`))!;
  input.value = value;
  fire(input, 'change');
}

/** The elements the transform builds from the walk with these options. */
const built = (kind: string, options: Record<string, number | string>) => {
  const run = getSeriesTransform(kind).create(options);
  run.setData(walk);
  return run.elements().slice();
};

describe('the point and figure and Renko settings dialog', () => {
  it('is offered in the top bar only while the chart builds point and figure or Renko', async () => {
    const widget = fed();
    await flush();
    expect(typeButton(widget).hidden).toBe(true);
    widget.setChartType('kagi');
    expect(typeButton(widget).hidden).toBe(true);
    widget.setChartType('point-figure');
    expect(typeButton(widget).getAttribute('aria-label')).toBe('Point and figure settings');
    let d = open(widget);
    expect(d.querySelector('.oac-dialog__title')!.textContent).toBe('Point and figure settings');
    expect(actions(d).map(b => b.textContent)).toEqual(['Cancel', 'OK']);
    cancel(d);
    expect(dialog(widget)).toBeNull();
    widget.setChartType('renko');
    expect(typeButton(widget).getAttribute('aria-label')).toBe('Renko settings');
    d = open(widget);
    expect(d.querySelector('.oac-dialog__title')!.textContent).toBe('Renko settings');
    cancel(d);
    widget.setChartType('candlestick');
    expect(typeButton(widget).hidden).toBe(true);
  });

  it('is not offered for point and figure drawn from a host\'s own elements, which has no box size', () => {
    const document = fakeWidgetDocument();
    const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
      document: document as unknown as Document, pixelRatio: () => 1, rail: false, panels: false, mobile: 'never',
      raf: { schedule: cb => { cb(); return 1; }, cancel() {} },
    });
    widgets.push(widget);
    widget.series.setData(walk);
    widget.setChartType('point-figure');
    expect(widget.chartType()).toBe('point-figure');
    expect(widget.chart.seriesTransform(widget.series)).toBeNull();
    expect(typeButton(widget).hidden).toBe(true);
  });

  it('sets the method to Percent and the size to a preset, and OK writes it', async () => {
    const widget = fed({ chartType: 'point-figure' });
    await flush();
    const d = open(widget);
    expect(d.querySelectorAll('.oac-ctset__preset').map(b => b.textContent))
      .toEqual(['0.05%', '0.10%', '0.15%', '0.25%', '0.50%', '1%', '2%', '3%']);
    preset(d, 0.25).click();
    expect(methodSelect(d).value).toBe('percent');
    expect(sizeInput(d).value).toBe('0.25');
    expect(preset(d, 0.25).getAttribute('aria-pressed')).toBe('true');
    expect(preset(d, 0.5).getAttribute('aria-pressed')).toBe('false');
    // Nothing reaches the chart before OK.
    expect(spec(widget)).toEqual({ type: 'point-figure' });
    ok(d);
    expect(dialog(widget)).toBeNull();
    expect(spec(widget)).toEqual({ type: 'point-figure', options: { mode: 'percent', percent: 0.25 } });
    expect(widget.chart.primaryBars()).toEqual(built('point-figure', { mode: 'percent', percent: 0.25 }));
  });

  it('offers the Renko presets, up to five percent', async () => {
    const widget = fed({ chartType: 'renko' });
    await flush();
    const d = open(widget);
    expect(d.querySelectorAll('.oac-ctset__preset').map(b => b.textContent))
      .toEqual(['0.05%', '0.10%', '0.25%', '0.50%', '1%', '2%', '3%', '5%']);
    preset(d, 5).click();
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko', options: { mode: 'percent', percent: 5 } });
  });

  it('writes the option each method sizes the box by', async () => {
    const widget = fed({ chartType: 'point-figure' });
    await flush();
    const cases: Array<[string, string, string | null, Record<string, number | string>]> = [
      ['fixed', '2', null, { boxSize: 2 }],
      ['percent', '0.5', null, { mode: 'percent', percent: 0.5 }],
      ['atr', '1.5', '10', { mode: 'atr', atrMultiplier: 1.5, atrPeriod: 10 }],
      ['atrPercent', '30', null, { mode: 'atrPercent', percent: 30 }],
    ];
    for (const [method, size, length, options] of cases) {
      widget.chart.setSeriesTransform(widget.series, { type: 'point-figure' });
      const d = open(widget);
      choose(methodSelect(d), method);
      // The ATR length is a row of the two ATR methods alone.
      expect((d.querySelector('[data-key="atrPeriod"]') as FakeElement).hidden).toBe(method !== 'atr' && method !== 'atrPercent');
      type(sizeInput(d), size);
      if (length !== null) type(atrInput(d), length);
      ok(d);
      expect(spec(widget), method).toEqual({ type: 'point-figure', options });
      expect(widget.chart.primaryBars()).toEqual(built('point-figure', options));
    }
    // Blank in Absolute is the size from history, the transform's default, so the spec drops it.
    widget.chart.setSeriesTransform(widget.series, { type: 'point-figure', options: { boxSize: 4 } });
    const d = open(widget);
    expect(sizeInput(d).value).toBe('4');
    type(sizeInput(d), '');
    ok(d);
    expect(spec(widget)).toEqual({ type: 'point-figure' });
  });

  it('writes the Renko methods with the Renko transform', async () => {
    const widget = fed({ chartType: 'renko' });
    await flush();
    const d = open(widget);
    choose(methodSelect(d), 'atr');
    type(sizeInput(d), '0.5');
    type(atrInput(d), '20');
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko', options: { mode: 'atr', atrMultiplier: 0.5, atrPeriod: 20 } });
    expect(widget.chart.primaryBars()).toEqual(built('renko', { mode: 'atr', atrMultiplier: 0.5, atrPeriod: 20 }));
  });

  it('shows the size each method holds, and keeps the others when the method changes', async () => {
    const widget = fed({ chartType: 'renko' });
    await flush();
    widget.chart.setSeriesTransform(widget.series, { type: 'renko', options: { mode: 'atr', atrMultiplier: 2, percent: 0.3, boxSize: 1.25 } });
    const d = open(widget);
    expect(methodSelect(d).value).toBe('atr');
    expect(sizeInput(d).value).toBe('2');
    choose(methodSelect(d), 'percent');
    expect(sizeInput(d).value).toBe('0.3');
    choose(methodSelect(d), 'fixed');
    expect(sizeInput(d).value).toBe('1.25');
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko', options: { atrMultiplier: 2, percent: 0.3, boxSize: 1.25 } });
  });

  it('sets the reversal and which prices move the boxes, and leaves a default out of the spec', async () => {
    const widget = fed({ chartType: 'point-figure' });
    await flush();
    let d = open(widget);
    const reversal = d.querySelector('[data-key="reversal"] select')!;
    expect(reversal.querySelectorAll('option').map(o => o.value)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']);
    expect(reversal.value).toBe('3');
    // Point and figure moves on the high and low unless told otherwise.
    expect(radio(d, 'hl').checked).toBe(true);
    expect(radio(d, 'close').checked).toBe(false);
    choose(reversal, '5');
    check(radio(d, 'close'));
    expect(radio(d, 'hl').checked).toBe(false);
    ok(d);
    expect(spec(widget)).toEqual({ type: 'point-figure', options: { reversal: 5, method: 'close' } });
    expect(widget.chart.primaryBars()).toEqual(built('point-figure', { reversal: 5, method: 'close' }));
    d = open(widget);
    choose(d.querySelector('[data-key="reversal"] select')!, '3');
    check(radio(d, 'hl'));
    ok(d);
    expect(spec(widget)).toEqual({ type: 'point-figure' });

    // Renko has no reversal, and moves on the close unless told otherwise.
    widget.setChartType('renko');
    d = open(widget);
    expect(d.querySelector('[data-key="reversal"]')).toBeNull();
    expect(radio(d, 'close').checked).toBe(true);
    check(radio(d, 'hl'));
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko', options: { method: 'hl' } });
  });

  it('offers the colours each renderer paints as paired rows, and writes them on OK', async () => {
    const widget = fed({ chartType: 'point-figure' });
    await flush();
    let d = open(widget);
    // Point and figure: the X and O colours, one row.
    const pf = d.querySelector('[data-key="symbol.body"]')!;
    expect(pf.querySelectorAll('input[type="color"]').length).toBe(2);
    color(d, 'symbol.upColor', '#112233');
    color(d, 'symbol.downColor', '#445566');
    expect(widget.chart.primarySeriesInfo()?.style.upColor).not.toBe('#112233');
    ok(d);
    expect(widget.chart.primarySeriesInfo()?.style).toMatchObject({ upColor: '#112233', downColor: '#445566' });

    // Renko draws its bricks as candles: the body and the border, each with its switch, and no wick a brick never has.
    widget.setChartType('renko');
    d = open(widget);
    expect(d.querySelector('[data-key="symbol.body"] input[type="checkbox"]')).not.toBeNull();
    expect(d.querySelectorAll('[data-key="symbol.borders"] input[type="color"]').length).toBe(2);
    expect(d.querySelector('[data-key="symbol.wick"]')).toBeNull();
    color(d, 'symbol.borderDownColor', '#778899');
    const borders = d.querySelector('[data-key="symbol.borders"] input[type="checkbox"]')!;
    borders.checked = false;
    fire(borders, 'change');
    ok(d);
    expect(widget.chart.primarySeriesInfo()?.style).toMatchObject({ borderDownColor: '#778899', borderVisible: false });
  });

  it('shows an invalid size or ATR length, and OK leaves the chart as it was', async () => {
    const widget = fed({ chartType: 'renko' });
    await flush();
    const d = open(widget);
    choose(methodSelect(d), 'percent');
    for (const bad of ['-2', '0', 'abc', '']) {
      type(sizeInput(d), bad);
      expect(sizeInput(d).getAttribute('aria-invalid'), bad).toBe('true');
      expect((d.querySelector('[data-key="size"] .oac-input-error') as FakeElement).hidden).toBe(false);
      ok(d);
      expect(dialog(widget)).not.toBeNull();
      expect(spec(widget)).toEqual({ type: 'renko' });
    }
    type(sizeInput(d), '0.4');
    expect(sizeInput(d).getAttribute('aria-invalid')).toBe('false');
    choose(methodSelect(d), 'atr');
    type(sizeInput(d), '1');
    type(atrInput(d), '2.5');
    expect(atrInput(d).getAttribute('aria-invalid')).toBe('true');
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko' });
    // An ATR length only the ATR methods read does not hold up another method.
    choose(methodSelect(d), 'percent');
    ok(d);
    expect(dialog(widget)).toBeNull();
    expect(spec(widget)).toEqual({ type: 'renko', options: { mode: 'percent', percent: 0.4 } });
  });

  it('changes nothing on Cancel, the close button or Escape, and leaves no undo step', async () => {
    const widget = fed({ chartType: 'point-figure' });
    await flush();
    widget.history.clear();
    const style = { ...widget.chart.primarySeriesInfo()?.style };
    const bars = widget.chart.primaryBars().slice();
    for (const dismiss of [
      (d: FakeElement) => cancel(d),
      (d: FakeElement) => (d.querySelector('.oac-dialog__head button') as FakeElement).click(),
      (d: FakeElement) => fire(d, 'keydown', { key: 'Escape' }),
    ]) {
      const d = open(widget);
      preset(d, 2).click();
      choose(d.querySelector('[data-key="reversal"] select')!, '7');
      check(radio(d, 'close'));
      color(d, 'symbol.upColor', '#010203');
      dismiss(d);
      expect(dialog(widget)).toBeNull();
      expect(spec(widget)).toEqual({ type: 'point-figure' });
      expect(widget.chart.primarySeriesInfo()?.style).toEqual(style);
      expect(widget.chart.primaryBars()).toEqual(bars);
    }
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(widget.history.canUndo()).toBe(false);
  });

  it('is one undo step, options and colours together', async () => {
    const widget = fed({ chartType: 'renko' });
    await flush();
    widget.history.clear();
    const style = readChartSettings(widget.chart)['symbol.upColor'];
    const d = open(widget);
    preset(d, 0.5).click();
    color(d, 'symbol.upColor', '#0a0b0c');
    ok(d);
    expect(spec(widget)).toEqual({ type: 'renko', options: { mode: 'percent', percent: 0.5 } });
    widget.history.undo();
    expect(spec(widget)).toEqual({ type: 'renko' });
    expect(readChartSettings(widget.chart)['symbol.upColor']).toBe(style);
    widget.history.redo();
    expect(spec(widget)).toEqual({ type: 'renko', options: { mode: 'percent', percent: 0.5 } });
    expect(widget.chart.primarySeriesInfo()?.style.upColor).toBe('#0a0b0c');
  });

  it('saves what it writes with the layout, and a new widget on the same store builds the same boxes', async () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value); }, removeItem: (key: string) => { store.delete(key); },
    };
    const first = fed({ persist: true, storage, chartType: 'point-figure' });
    await flush();
    const d = open(first);
    choose(methodSelect(d), 'atrPercent');
    type(sizeInput(d), '40');
    choose(d.querySelector('[data-key="reversal"] select')!, '2');
    color(d, 'symbol.downColor', '#a1b2c3');
    ok(d);
    const options = { mode: 'atrPercent', percent: 40, reversal: 2 };
    expect(first.getState().chart.series?.[0]).toMatchObject({ transform: { type: 'point-figure', options }, style: { downColor: '#a1b2c3' } });
    // The save is debounced; the history step schedules it.
    await new Promise(resolve => setTimeout(resolve, 400));
    expect(first.context.storage.get(STATE_KEY)).toMatchObject({ chart: { series: [{ transform: { type: 'point-figure', options }, style: { downColor: '#a1b2c3' } }] } });
    const saved = first.getState();
    first.destroy();
    const second = fed({ persist: true, storage });
    await flush();
    expect(second.chartType()).toBe('point-figure');
    expect(spec(second)).toEqual({ type: 'point-figure', options });
    expect(second.chart.primaryBars()).toEqual(built('point-figure', options));
    // And the dialog reads it back.
    const again = open(second);
    expect(methodSelect(again).value).toBe('atrPercent');
    expect(sizeInput(again).value).toBe('40');
    expect(again.querySelector('[data-key="reversal"] select')!.value).toBe('2');
    // The colours come back too, on the stored layout and through restoreState.
    expect(second.chart.primarySeriesInfo()?.style.downColor).toBe('#a1b2c3');
    const third = fed({ chartType: 'point-figure' });
    await flush();
    expect(third.restoreState(saved).applied).toBe(true);
    expect(third.chart.primarySeriesInfo()?.style.downColor).toBe('#a1b2c3');
  });

  it('keeps a style saved for another chart type off the series on screen', async () => {
    const first = fed({ chartType: 'point-figure' });
    await flush();
    const d = open(first);
    color(d, 'symbol.downColor', '#a1b2c3');
    ok(d);
    const second = fed();
    await flush();
    const state = { ...first.getState(), chartType: undefined };
    expect(second.restoreState(state).applied).toBe(true);
    expect(second.chart.primarySeriesInfo()?.style.downColor).not.toBe('#a1b2c3');
  });
});
