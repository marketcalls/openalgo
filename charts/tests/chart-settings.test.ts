import { describe, it, expect, vi, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import type { ContextMenuEvent } from '../src/core/chart';
import {
  chartSettingsSchema, readChartSettings, applyChartSettings, CHART_TIMEZONES,
  type ChartSettingsValue, type ChartSettingsValues,
  type ChartSettingsInput, type ChartSettingsColorPairInput,
} from '../src/model/chart-settings';
import { registerIndicator, type IndicatorInput } from '../src/model/indicator-registry';
import { PaneLegend } from '../src/primitives/pane-legend';
import { ReplayController } from '../src/replay/controller';
import type { IPrimitive } from '../src/primitives/primitive';
import type { SeriesType } from '../src/model/chart-type-registry';
import type { SeriesApi } from '../src/model/series';
import type { Bar } from '../src/model/bar';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 100 + i };
});

/** Alternating direction, so both halves of an up/down pair actually draw. */
const MIXED: Bar[] = BARS.map((b, i) => (i % 2 === 0
  ? b
  : { ...b, open: b.close + 0.5, close: b.open }));

interface Mounted {
  chart: Chart;
  el: FakeElement;
  series: SeriesApi;
}

function mount(type: SeriesType = 'candlestick', withData = true): Mounted {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  Object.assign(el, { clientWidth: 800, clientHeight: 600 });
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    // Synchronous scheduler: an option that repaints has done so by the time
    // the setter returns, so a test can read the recorded draw ops straight after.
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    shortcuts: false,
    timeNavigator: false,
  });
  chart.applySize(800, 600);
  const series = chart.addSeries(type);
  if (withData) series.setData(BARS);
  return { chart, el, series };
}

const baseRec = (chart: Chart, pane = 0): RecordingContext =>
  chart.panes()[pane].base.ctx as unknown as RecordingContext;

/**
 * Every value key a row carries, as the single-value inputs a host renders
 * them from. A `colorPair` is one row over two or three keys, so this is the
 * expansion the dialog itself does; everything below drives the schema through
 * it rather than assuming one key per row.
 */
function valueInputs(input: ChartSettingsInput): IndicatorInput[] {
  if (input.type !== 'colorPair') return [input];
  const pair = input;
  const out: IndicatorInput[] = [];
  if (pair.enabled !== undefined) {
    out.push({ key: pair.enabled.key, type: 'boolean', label: pair.label, default: pair.enabled.default });
  }
  out.push({ key: pair.up.key, type: 'color', label: pair.up.label, default: pair.up.default });
  out.push({ key: pair.down.key, type: 'color', label: pair.down.label, default: pair.down.default });
  return out;
}

/** Every value key of the whole dialog, in display order. */
function allInputs(chart: Chart): IndicatorInput[] {
  return chartSettingsSchema(chart).flatMap((t) => t.inputs.flatMap(valueInputs));
}

/** The paired-colour rows of a tab, by row key. */
function pairs(tabInputs: readonly ChartSettingsInput[]): ChartSettingsColorPairInput[] {
  return tabInputs.filter((i): i is ChartSettingsColorPairInput => i.type === 'colorPair');
}

/** A value the control does not currently hold, so a write is observable. */
function mutate(input: IndicatorInput, current: ChartSettingsValue): ChartSettingsValue {
  switch (input.type) {
    case 'text': return current === 'Research' ? '' : 'Research';
    case 'boolean': return current !== true;
    case 'color': return current === '#abcdef' ? '#123456' : '#abcdef';
    case 'number': {
      const min = input.min ?? 0;
      const step = input.step ?? 1;
      return current === min ? min + step : min;
    }
    case 'select': {
      const other = input.options.find((o) => o.value !== current);
      return other === undefined ? current : other.value;
    }
    default: return current;
  }
}

describe('chart settings schema', () => {
  it('describes our five tabs, each with controls', () => {
    const { chart } = mount();
    const tabs = chartSettingsSchema(chart);
    expect(tabs.map((t) => t.id)).toEqual(['price', 'readout', 'axes', 'appearance', 'trading']);
    for (const tab of tabs) expect(tab.inputs.length).toBeGreaterThan(0);
  });

  it('names the scale and its auto-fit the way the axis menu does', () => {
    const { chart } = mount();
    const byKey = new Map(allInputs(chart).map((i) => [i.key, i]));
    const mode = byKey.get('scales.mode') as { options?: { value: string; label: string }[] };
    expect(mode.options?.find((o) => o.value === 'linear')?.label).toBe('Linear');
    expect(byKey.get('scales.autoScale')?.label).toBe('Auto-fit to the data');
  });

  it('offers no alerts or events tab, because neither ships', () => {
    const { chart } = mount();
    const tabs = chartSettingsSchema(chart);
    expect(tabs.map((t) => t.id)).not.toContain('events');
    expect(tabs.map((t) => t.id)).not.toContain('alerts');
    expect(allInputs(chart).map((i) => i.key).filter((k) => k.startsWith('events.'))).toEqual([]);
  });

  it('keys are unique across the whole dialog, rows and values alike', () => {
    const { chart } = mount();
    const rowKeys = chartSettingsSchema(chart).flatMap((t) => t.inputs.map((i) => i.key));
    expect(new Set(rowKeys).size).toBe(rowKeys.length);
    const valueKeys = allInputs(chart).map((i) => i.key);
    expect(new Set(valueKeys).size).toBe(valueKeys.length);
    // A row key must not collide with a value key either: a host keys its
    // widgets by one and its patch by the other.
    const rowOnly = rowKeys.filter((k) => !valueKeys.includes(k));
    expect(new Set([...rowOnly, ...valueKeys]).size).toBe(rowOnly.length + valueKeys.length);
  });

  it('shows the HLC area band in the colour the renderer paints when none is set', () => {
    const { chart } = mount('hlc-area');
    const band = allInputs(chart).find((i) => i.key === 'symbol.areaTopColor');
    const read = readChartSettings(chart)['symbol.areaTopColor'];
    // The renderer fills the band with this when the style sets none, on both themes.
    const fills = baseRec(chart).ops.filter((o) => o.type === 'fill').map((o) => o.fillStyle);
    expect(fills).toContain(read);
    expect(band?.default).toBe(read);
    // A colour the user picks is what both the dialog and the band show.
    applyChartSettings(chart, { 'symbol.areaTopColor': '#8844aa' });
    expect(readChartSettings(chart)['symbol.areaTopColor']).toBe('#8844aa');
  });

  it('shows the controls the primary series type actually honours', () => {
    const candle = allInputs(mount('candlestick').chart).map((i) => i.key);
    expect(candle).toContain('symbol.wickUpColor');
    expect(candle).not.toContain('symbol.lineStyle');

    const line = allInputs(mount('line').chart).map((i) => i.key);
    expect(line).toContain('symbol.lineStyle');
    expect(line).not.toContain('symbol.wickUpColor');

    // Area strokes its outline as a plain line, dash and all, so it offers
    // the control; baseline and HLC area stroke with a fixed style and do not.
    const area = allInputs(mount('area').chart).map((i) => i.key);
    expect(area).toContain('symbol.areaTopColor');
    expect(area).toContain('symbol.lineStyle');
    for (const fixed of ['baseline', 'hlc-area'] as const) {
      expect(allInputs(mount(fixed).chart).map((i) => i.key), fixed).not.toContain('symbol.lineStyle');
    }
  });
});

describe('paired colour controls', () => {
  it('gives body, borders and wick one row each, not a section apiece', () => {
    const { chart } = mount();
    const price = chartSettingsSchema(chart)[0];
    const rows = pairs(price.inputs);
    expect(rows.map((r) => r.key)).toEqual(['symbol.body', 'symbol.borders', 'symbol.wick']);
    expect(rows.map((r) => r.label)).toEqual(['Body', 'Borders', 'Wick']);
    // One row, two colours: the up and down swatches are on the row, not in
    // separate inputs a host would stack.
    expect(rows[0].up.key).toBe('symbol.upColor');
    expect(rows[0].down.key).toBe('symbol.downColor');
    // A colour pair is not also emitted as two plain colour inputs.
    const colorRows = price.inputs.filter((i) => i.type === 'color').map((i) => i.key);
    expect(colorRows).not.toContain('symbol.upColor');
    expect(colorRows).not.toContain('symbol.borderDownColor');
  });

  it('carries the enable flag only where a flag exists', () => {
    const { chart } = mount();
    const rows = pairs(chartSettingsSchema(chart)[0].inputs);
    const byKey = new Map(rows.map((r) => [r.key, r]));
    // All three candle rows carry a switch, and each one writes a real
    // SeriesStyle flag. `symbol.body` was the exception until `bodyVisible`
    // existed: the row went without a checkbox rather than offering one that
    // wrote nowhere. The rule has not changed, only what the renderer can do.
    expect(byKey.get('symbol.body')?.enabled?.key).toBe('symbol.bodyVisible');
    expect(byKey.get('symbol.borders')?.enabled?.key).toBe('symbol.borderVisible');
    expect(byKey.get('symbol.wick')?.enabled?.key).toBe('symbol.wickVisible');
  });

  it('round-trips all three of its values through read and apply', () => {
    const { chart } = mount();
    applyChartSettings(chart, {
      'symbol.borderVisible': false,
      'symbol.borderUpColor': '#0a0b0c',
      'symbol.borderDownColor': '#0d0e0f',
    });
    const after = readChartSettings(chart);
    expect(after['symbol.borderVisible']).toBe(false);
    expect(after['symbol.borderUpColor']).toBe('#0a0b0c');
    expect(after['symbol.borderDownColor']).toBe('#0d0e0f');
    // The row key itself is not a value: it names the widget, nothing else.
    expect(after['symbol.borders']).toBeUndefined();
  });

  it('both halves of a pair reach the pixels independently', () => {
    const { chart, series } = mount();
    series.setData(MIXED); // the sine bars all close above their open
    const rec = baseRec(chart);
    rec.ops.length = 0;
    applyChartSettings(chart, { 'symbol.upColor': '#ff00ff', 'symbol.downColor': '#00ff88' });
    const filled = new Set(rec.ops.filter((o) => o.fillStyle !== undefined).map((o) => o.fillStyle));
    expect(filled.has('#ff00ff')).toBe(true);
    expect(filled.has('#00ff88')).toBe(true);
  });

  it("a pair's switch stops the marks it owns", () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'symbol.wickUpColor': '#123456', 'symbol.wickDownColor': '#123456' });
    const rec = baseRec(chart);
    const wicks = (): number => rec.ops.filter((o) => o.fillStyle === '#123456').length;
    rec.ops.length = 0;
    applyChartSettings(chart, { 'symbol.wickVisible': false });
    expect(wicks()).toBe(0);
    rec.ops.length = 0;
    applyChartSettings(chart, { 'symbol.wickVisible': true });
    expect(wicks()).toBeGreaterThan(0);
  });

  it('pairs the trade colours that are read against each other', () => {
    const { chart } = mount();
    const trading = chartSettingsSchema(chart)[4];
    const rows = pairs(trading.inputs);
    expect(rows.map((r) => [r.up.key, r.down.key])).toEqual([
      ['trading.longColor', 'trading.shortColor'],
      ['trading.tpColor', 'trading.slColor'],
      ['trading.buyColor', 'trading.sellColor'],
    ]);
    // The resting order has no opposite, so it stays a single swatch.
    expect(trading.inputs.filter((i) => i.type === 'color').map((i) => i.key)).toEqual(['trading.orderColor']);
  });
});

describe('read / apply round-trip', () => {
  it('reading every control and applying it back changes nothing', () => {
    const { chart } = mount();
    const before = readChartSettings(chart);
    applyChartSettings(chart, before);
    expect(readChartSettings(chart)).toEqual(before);
  });

  it('every declared control writes through to real chart state', () => {
    const { chart } = mount();
    const seen: string[] = [];
    for (const input of allInputs(chart)) {
      const before = readChartSettings(chart)[input.key];
      const next = mutate(input, before);
      // A control whose mutation is a no-op would pass the assertion below
      // for free, which is exactly the dead control this test hunts.
      expect([input.key, next]).not.toEqual([input.key, before]);
      applyChartSettings(chart, { [input.key]: next });
      expect([input.key, readChartSettings(chart)[input.key]]).toEqual([input.key, next]);
      seen.push(input.key);
    }
    // Every key the schema declares is a key `read` reports back: a declared
    // control that read nothing would be missing from the snapshot.
    expect(Object.keys(readChartSettings(chart)).sort()).toEqual([...seen].sort());
  });

  it('round-trips a fully mutated snapshot applied in one patch', () => {
    const { chart } = mount();
    const base = readChartSettings(chart);
    const patch: ChartSettingsValues = {};
    for (const input of allInputs(chart)) patch[input.key] = mutate(input, base[input.key]);
    applyChartSettings(chart, patch);
    expect(readChartSettings(chart)).toEqual(patch);
  });

  it('ignores keys it does not know, so an old build can read a new state', () => {
    const { chart } = mount();
    const before = readChartSettings(chart);
    applyChartSettings(chart, { 'canvas.hyperspace': true, 'symbol.upColor': '#010203' });
    expect(readChartSettings(chart)['symbol.upColor']).toBe('#010203');
    expect(Object.keys(readChartSettings(chart))).toEqual(Object.keys(before));
  });
});

describe('controls reach the renderer, not just an option bag', () => {
  it('a grid colour lands on the stroke the pane draws', () => {
    const { chart } = mount();
    const rec = baseRec(chart);
    rec.ops.length = 0;
    applyChartSettings(chart, { 'canvas.grid.vertColor': '#ff00ff' });
    expect(rec.ops.some((o) => o.type === 'stroke' && o.strokeStyle === '#ff00ff')).toBe(true);
  });

  it('switching an axis off removes its lines entirely', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'canvas.grid.vertColor': '#ff00ff', 'canvas.grid.horzColor': '#00ff00' });
    const rec = baseRec(chart);
    rec.ops.length = 0;
    applyChartSettings(chart, { 'canvas.grid.vertLines': false });
    expect(rec.ops.some((o) => o.type === 'stroke' && o.strokeStyle === '#ff00ff')).toBe(false);
    expect(rec.ops.some((o) => o.type === 'stroke' && o.strokeStyle === '#00ff00')).toBe(true);
  });

  it('precision overrides what the price scale formats', () => {
    const { chart } = mount();
    const scale = chart.panes()[0].priceScale;
    applyChartSettings(chart, { 'symbol.precision': '3' });
    expect(scale.format(1.23456)).toBe('1.235');
    applyChartSettings(chart, { 'symbol.precision': 'default' });
    expect(scale.format(1.23456)).not.toBe('1.235');
  });

  it('precision does not start snapping prices to whole numbers', () => {
    const { chart } = mount();
    const scale = chart.panes()[0].priceScale;
    applyChartSettings(chart, { 'symbol.precision': '0' });
    expect(scale.format(101.4)).toBe('101');
    expect(scale.snapToTick(101.4)).toBe(101.4); // minMove untouched
  });

  it('the status-line switches reach every legend on the chart', () => {
    const { chart } = mount();
    const legend = new PaneLegend({ id: 'symbol', title: 'AAPL' });
    chart.addPrimitive(legend, 0);
    applyChartSettings(chart, { 'statusLine.volume': false, 'statusLine.titleMode': 'ticker' });
    expect(legend.options().statusLine?.volume).toBe(false);
    expect(legend.options().statusLine?.titleMode).toBe('ticker');
  });

  it('keeps the OI preference when capability suppresses the readout and across state restoration', () => {
    const { chart } = mount();
    const legend = new PaneLegend({ id: 'symbol', title: 'Contract' });
    chart.addPrimitive(legend, 0);
    expect(readChartSettings(chart)['statusLine.openInterest']).toBe(false);
    applyChartSettings(chart, { 'statusLine.openInterest': true });
    expect(legend.options().statusLine?.openInterest).toBe(true);
    chart.setDataContext({ hasOpenInterest: false });
    expect(legend.options().hasOpenInterest).toBe(false);
    expect(legend.options().statusLine?.openInterest).toBe(true);
    expect(readChartSettings(chart)['statusLine.openInterest']).toBe(true);
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const restored = mount().chart;
    restored.setDataContext({ hasOpenInterest: false });
    restored.restoreState(state);
    const added = new PaneLegend({ id: 'restored', title: 'Cash' });
    restored.addPrimitive(added, 0);
    expect(restored.statusLineOptions().openInterest).toBe(true);
    expect(added.options().hasOpenInterest).toBe(false);
    restored.setDataContext({ hasOpenInterest: true });
    expect(added.options().hasOpenInterest).toBe(true);
    expect(added.options().statusLine?.openInterest).toBe(true);
    chart.setDataContext(undefined);
    expect(legend.options().statusLine?.openInterest).toBe(true);
  });

  it('a legend added after the switches still obeys them', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'statusLine.barChange': false });
    const legend = new PaneLegend({ id: 'symbol', title: 'AAPL' });
    chart.addPrimitive(legend, 0);
    expect(legend.options().statusLine?.barChange).toBe(false);
  });

  it('leaves the event strip to the host that feeds it', () => {
    const { chart } = mount();
    chart.setEvents([
      { time: BARS[10].time, type: 'earnings', label: 'E', id: 'e1' },
      { time: BARS[20].time, type: 'dividend', label: 'D', id: 'd1' },
    ]);
    const rec = baseRec(chart);
    rec.ops.length = 0;
    // The dialog no longer offers these switches (nothing in the engine sources
    // corporate actions), but the option they used to drive is still the
    // chart's, and a host feeding its own events still gets it.
    chart.setEventOptions({ dividend: false });
    expect(rec.ops.filter((o) => o.type === 'arc').length).toBe(1);
    expect(chart.getState().events?.dividend).toBe(false);
  });

  it('names its primary series, so replay can drive it unprompted', () => {
    const { chart, series } = mount();
    expect(chart.primarySeries()).toBe(series);
    expect(chart.primarySeriesInfo()?.type).toBe('candlestick');
    const replay = new ReplayController(chart, { startIndex: 9 });
    expect(replay.state().total).toBe(BARS.length);
    expect(replay.state().bar?.time).toBe(BARS[9].time);
    replay.stop();
  });

  it('forgets the primary series when it is removed', () => {
    const { chart, series } = mount();
    series.remove();
    expect(chart.primarySeries()).toBeNull();
    expect(chart.primarySeriesInfo()).toBeNull();
  });

  it('trading colours are held without instantiating the trade layer', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'trading.longColor': '#00ff00' });
    expect(chart.hasTrading()).toBe(false); // reading settings must not claim the click callback
    expect(chart.tradingSettings().long).toBe('#00ff00');
    expect(chart.trading.getSettings().long).toBe('#00ff00'); // handed over on creation
  });
});

describe('timezone control', () => {
  const tzInput = (chart: Chart): IndicatorInput => {
    const found = allInputs(chart).find((i) => i.key === 'time.timezone');
    if (found === undefined) throw new Error('no timezone control');
    return found;
  };

  it('sits on the Axes tab as a zone list, not a bolt-on the host must add', () => {
    const { chart } = mount();
    const axes = chartSettingsSchema(chart).find((t) => t.id === 'axes');
    expect(axes?.inputs.some((i) => i.key === 'time.timezone')).toBe(true);
    const input = tzInput(chart);
    expect(input.type).toBe('select');
    if (input.type !== 'select') return;
    expect(input.options.map((o) => o.value)).toEqual([...CHART_TIMEZONES]);
    expect(input.group).toBe('Time axis');
  });

  it('reaches chart.setTimezone, and reads the chart back', () => {
    const { chart } = mount();
    const spy = vi.spyOn(chart, 'setTimezone');
    expect(readChartSettings(chart)['time.timezone']).toBe('Asia/Kolkata');
    applyChartSettings(chart, { 'time.timezone': 'America/New_York' });
    expect(spy).toHaveBeenCalledWith('America/New_York');
    expect(chart.timezone()).toBe('America/New_York');
    expect(readChartSettings(chart)['time.timezone']).toBe('America/New_York');
    spy.mockRestore();
  });

  it('relabels the time axis it was changed for', () => {
    const { chart } = mount();
    const label = (): string[] => {
      const rec = baseRec(chart);
      rec.ops.length = 0;
      chart.applySize(800, 601); // force a repaint, so the axis re-renders
      return rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');
    };
    const ist = label();
    applyChartSettings(chart, { 'time.timezone': 'UTC' });
    expect(label()).not.toEqual(ist);
  });

  it('keeps a zone the chart was built with in the list', () => {
    const doc = fakeDocument();
    const el = doc.createElement('div') as unknown as FakeElement;
    Object.assign(el, { clientWidth: 800, clientHeight: 600 });
    const chart = new Chart(el, {
      document: doc,
      pixelRatio: () => 1,
      raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
      shortcuts: false,
      timeNavigator: false,
      timezone: 'Pacific/Auckland',
    });
    chart.applySize(800, 600);
    const input = tzInput(chart);
    if (input.type !== 'select') throw new Error('expected a select');
    expect(input.options.map((o) => o.value)).toContain('Pacific/Auckland');
    expect(readChartSettings(chart)['time.timezone']).toBe('Pacific/Auckland');
  });

  it('skips a zone the runtime does not know instead of throwing', () => {
    const { chart } = mount();
    expect(() => applyChartSettings(chart, { 'time.timezone': 'Mars/Olympus' })).not.toThrow();
    expect(chart.timezone()).toBe('Asia/Kolkata');
  });
});

describe('rebasing price-scale modes', () => {
  it('percentage takes its baseline from the first visible bar', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'scales.mode': 'percentage' });
    const scale = chart.panes()[0].priceScale;
    expect(scale.baseline).not.toBeNull();
    const base = scale.baseline as number;
    // No sign on a value that rounds to zero: it is the baseline, not a move.
    expect(scale.format(base)).toBe('0.00%');
    expect(scale.format(base * 1.05)).toBe('+5.00%');
  });

  it('indexed-to-100 quotes the same baseline as an index', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'scales.mode': 'indexed-to-100' });
    const scale = chart.panes()[0].priceScale;
    const base = scale.baseline as number;
    expect(scale.format(base)).toBe('100.00');
    expect(scale.format(base * 1.05)).toBe('105.00');
  });

  it('a manually pinned scale still gets a baseline to label itself', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'scales.mode': 'percentage', 'scales.autoScale': false });
    const scale = chart.panes()[0].priceScale;
    scale.setPriceRange({ min: 90, max: 110 });
    chart.applySize(800, 601); // force a relayout + autoscale pass
    expect(scale.baseline).not.toBeNull();
  });

  it('back to linear drops the rebased labels', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'scales.mode': 'percentage' });
    applyChartSettings(chart, { 'scales.mode': 'linear' });
    expect(chart.panes()[0].priceScale.format(100)).not.toContain('%');
  });
});

describe('settings survive getState / restoreState', () => {
  const patch: ChartSettingsValues = {
    // Both halves of a pair and its switch, so the paired control is proved to
    // survive the save and not only the dialog.
    'symbol.upColor': '#111111',
    'symbol.downColor': '#222222',
    'symbol.borderVisible': false,
    'symbol.wickUpColor': '#333333',
    'symbol.precision': '3',
    'symbol.priceLineVisible': false,
    'symbol.lastValueVisible': false,
    'statusLine.volume': false,
    'statusLine.background': true,
    'scales.mode': 'percentage',
    'scales.inverted': true,
    'time.timezone': 'America/New_York',
    'canvas.grid.vertColor': '#ff0000',
    'canvas.grid.horzStyle': 'dotted',
    'canvas.crosshair.style': 'dotted',
    'canvas.scales.fontSize': 13,
    'canvas.margins.top': 20,
    'canvas.crosshairMode': 'magnet',
    'trading.longColor': '#00ff00',
    'trading.sellColor': '#0000ff',
  };

  it('restores through a JSON round-trip', () => {
    const a = mount();
    applyChartSettings(a.chart, patch);
    const state = JSON.parse(JSON.stringify(a.chart.getState())) as unknown;

    const b = mount('candlestick', false);
    const report = b.chart.restoreState(state);
    expect(report.applied).toBe(true);
    // Series data is the app's, so the chart reports the descriptor instead of
    // recreating it; re-applying that style is the documented restore flow.
    const descriptor = report.series.find((s) => s.paneIndex === 0);
    expect(descriptor).toBeDefined();
    b.series.applyOptions(descriptor?.style ?? {});
    b.series.setData(BARS);

    const after = readChartSettings(b.chart);
    for (const [key, value] of Object.entries(patch)) expect([key, after[key]]).toEqual([key, value]);
  });

  it('a state saved before these options existed still restores', () => {
    const { chart } = mount();
    const legacy = { version: 1, grid: { vertLines: false, horzLines: true }, crosshairMode: 'magnet' };
    expect(chart.restoreState(legacy).applied).toBe(true);
    expect(chart.gridOptions().vertLines).toBe(false);
    expect(chart.crosshairMode()).toBe('magnet');
  });
});

describe('contextmenu event', () => {
  registerIndicator({
    id: 'context-source', name: 'Context source', placement: 'onchart',
    inputs: [],
    plots: [{ key: 'first', type: 'line', title: 'First' }, { key: 'second', type: 'line', title: 'Second' }],
    calc: bars => ({ first: bars.map(() => 130), second: bars.map((_, index) => index === 25 ? null : 150) }),
  });
  afterEach(() => vi.unstubAllGlobals());

  const drawing: IPrimitive = {
    zOrder: () => 'normal',
    draw: () => {},
    hitTest: (x, y) => (x >= 300 && x <= 400 && y >= 200 && y <= 260
      ? { externalId: 'draw:trend-1', zOrder: 'normal', distance: 0 }
      : null),
  };

  function nativeEvent(x: number, y: number): Record<string, unknown> {
    return {
      clientX: x, clientY: y, defaultPrevented: false,
      preventDefault(this: Record<string, unknown>) { this.defaultPrevented = true; },
    };
  }

  function menuAt(m: Mounted, x: number, y: number): ContextMenuEvent[] {
    const seen: ContextMenuEvent[] = [];
    const off = m.chart.on('contextmenu', (p) => seen.push(p as ContextMenuEvent));
    m.el.dispatch('contextmenu', nativeEvent(x, y));
    off();
    return seen;
  }

  it('a crosshair colour reaches the overlay the cursor paints', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    applyChartSettings(m.chart, { 'canvas.crosshair.color': '#00ffff' });
    const top = m.chart.panes()[0].top.ctx as unknown as RecordingContext;
    top.ops.length = 0;
    m.el.dispatch('pointermove', { clientX: 400, clientY: 300, pointerId: 1, pointerType: 'mouse', buttons: 0 });
    expect(top.ops.some((o) => o.type === 'stroke' && o.strokeStyle === '#00ffff')).toBe(true);
  });

  it('classifies a drawing under the pointer', () => {
    vi.stubGlobal('window', {}); // _attachInput bails when window is undefined
    const m = mount();
    m.chart.addPrimitive(drawing, 0);
    const [e] = menuAt(m, 350, 230);
    expect(e.target).toEqual({ kind: 'drawing', id: 'draw:trend-1' });
    expect(e.paneIndex).toBe(0);
    expect(e.price).not.toBeNull();
  });

  it('classifies a legend row, and an indicator row by its instance', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    m.chart.addPrimitive(new PaneLegend({ id: 'symbol', title: 'AAPL' }), 0);
    expect(menuAt(m, 20, 12)[0].target).toEqual({ kind: 'legend', id: 'symbol::row' });

    m.chart.addPrimitive(new PaneLegend({ id: 'indicator:rsi-1', title: 'RSI', row: 1 }), 0);
    const target = menuAt(m, 20, 30)[0].target;
    expect(target.kind).toBe('indicator');
    expect(target.instanceId).toBe('rsi-1');
  });

  it('classifies the series under the pointer, and reports its bar', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const bar = BARS[20];
    const x = m.chart.timeToCoordinate(bar.time);
    const y = m.chart.priceToCoordinate(bar.close, 0) ?? 0;
    const [e] = menuAt(m, x, y);
    expect(e.target.kind).toBe('series');
    expect(e.target.seriesType).toBe('candlestick');
    expect(e.time).toBe(bar.time);
    expect(e.index).toBe(20);
  });

  it('identifies the exact plot of the topmost study and ignores hidden or missing readings', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const first = m.chart.addIndicator('context-source');
    const second = m.chart.addIndicator('context-source');
    first.values(); second.values();
    const x = m.chart.timeToCoordinate(BARS[20].time);
    const y = m.chart.priceToCoordinate(150, 0)!;
    expect(menuAt(m, x, y)[0].target).toMatchObject({ kind: 'indicator', instanceId: second.id, plotKey: 'second' });
    second.series('second')!.applyOptions({ visible: false });
    expect(menuAt(m, x, y)[0].target).toMatchObject({ kind: 'indicator', instanceId: first.id, plotKey: 'second' });
    expect(menuAt(m, m.chart.timeToCoordinate(BARS[25].time), y)[0].target.kind).toBe('empty');
    expect(menuAt(m, x, m.chart.priceToCoordinate(130, 0)!)[0].target)
      .toMatchObject({ kind: 'indicator', instanceId: second.id, plotKey: 'first' });
    m.chart.addPrimitive({ zOrder: () => 'top', draw: () => {},
      hitTest: () => ({ externalId: 'draw:above-study', zOrder: 'top', distance: 0 }) }, 0);
    expect(menuAt(m, x, y)[0].target).toEqual({ kind: 'drawing', id: 'draw:above-study' });
    m.chart.destroy();
  });

  it('classifies empty space, and the two axis strips', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    // Halfway between the top edge and the highest bar: inside the plot, on nothing.
    const top = m.chart.priceToCoordinate(Math.max(...BARS.map((b) => b.high)), 0) ?? 0;
    expect(menuAt(m, 700, top / 2)[0].target).toEqual({ kind: 'empty', id: null });
    expect(menuAt(m, 780, 300)[0].target.kind).toBe('price-scale');
    expect(menuAt(m, 400, 595)[0].target.kind).toBe('time-scale');
  });

  it('hands the host a preventDefault that suppresses the native menu', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const native = nativeEvent(700, 300);
    m.chart.on('contextmenu', (p) => (p as ContextMenuEvent).preventDefault());
    m.el.dispatch('contextmenu', native);
    expect(native.defaultPrevented).toBe(true);
  });

  it('keeps the save-image snapshot as the fallback when nothing listens', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const top = m.chart.panes()[0].top.ctx as unknown as RecordingContext;
    top.ops.length = 0;
    m.el.dispatch('contextmenu', nativeEvent(350, 230));
    // The base layer is composited under the overlay so the browser's own
    // "Save image as" captures the visible chart rather than a blank overlay.
    expect(top.ops.some((o) => o.type === 'drawImage')).toBe(true);
  });

  it('skips the snapshot once a listener takes over the menu', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const top = m.chart.panes()[0].top.ctx as unknown as RecordingContext;
    const off = m.chart.on('contextmenu', () => {});
    top.ops.length = 0;
    m.el.dispatch('contextmenu', nativeEvent(350, 230));
    off();
    expect(top.ops.some((o) => o.type === 'drawImage')).toBe(false);
  });

  it('restores the fallback once the last listener unsubscribes', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    m.chart.on('contextmenu', () => {})();
    const top = m.chart.panes()[0].top.ctx as unknown as RecordingContext;
    top.ops.length = 0;
    m.el.dispatch('contextmenu', nativeEvent(350, 230));
    expect(top.ops.some((o) => o.type === 'drawImage')).toBe(true);
  });

  it('stays out of the way when the app already called preventDefault', () => {
    vi.stubGlobal('window', {});
    const m = mount();
    const seen: ContextMenuEvent[] = [];
    m.chart.on('contextmenu', (p) => seen.push(p as ContextMenuEvent));
    m.el.dispatch('contextmenu', { ...nativeEvent(350, 230), defaultPrevented: true });
    expect(seen).toEqual([]);
  });
});
