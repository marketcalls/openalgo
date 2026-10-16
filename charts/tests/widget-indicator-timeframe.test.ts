/**
 * The timeframe input of a built-in study in the widget's settings dialog: a
 * select whose first entry is the chart's own timeframe and whose others are
 * the intervals the host serves, when it named them.
 */
import { afterEach, describe, expect, it } from 'vitest';
import 'openalgo-charts/indicators';
import { Chart, darkTheme } from 'openalgo-charts';
import type { Bar } from 'openalgo-charts';
import { DrawingController } from 'openalgo-charts/draw';
import { createOverlayStack, WidgetBus, WidgetStorage, type OverlayStack, type WidgetContext } from '../src/widget/context';
import { mountIndicatorSettings } from '../src/widget/dialogs/index';
import { controlsFromInputs } from '../src/widget/form';
import { installDom, asDoc, asEl, type FakeElement } from './widget-form.test';

/** A seeded random walk of one-minute bars from 09:15 IST. */
function minutes(n: number): Bar[] {
  let s = 17;
  const rnd = (): number => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const out: Bar[] = [];
  let close = 500;
  for (let i = 0; i < n; i++) {
    const open = close;
    close = Math.round(open * (1 + (rnd() - 0.5) * 0.004) * 20) / 20;
    out.push({ time: 1788752700 + i * 60, open, high: Math.max(open, close) + 0.1, low: Math.min(open, close) - 0.1, close, volume: 100 });
  }
  return out;
}

const cleanups: (() => void)[] = [];
afterEach(() => { while (cleanups.length > 0) cleanups.pop()!(); });

function rig(intervals?: readonly string[]): { ctx: WidgetContext; chart: Chart; q(sel: string): FakeElement | null } {
  const dom = installDom();
  const doc = asDoc(dom.doc);
  const chart = new Chart(asEl(dom.chartEl), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(958, 660);
  chart.setDataContext({ interval: '1m' });
  chart.addSeries('candlestick').setData(minutes(240));
  const stack: OverlayStack = createOverlayStack(asEl(dom.root), doc);
  cleanups.push(() => { stack.destroy(); chart.destroy(); });
  const ctx: WidgetContext = {
    chart, draw: new DrawingController(chart), root: asEl(dom.root), document: doc, theme: 'dark', chartTheme: darkTheme,
    keymap: {} as WidgetContext['keymap'], bus: new WidgetBus(), storage: new WidgetStorage('test', null), locale: undefined,
    toast: () => ({ node: doc.createElement('div'), dismiss: () => {} }),
    openOverlay: (el, opts) => stack.open(el, opts), status: () => {},
    tips: { attach() {}, refreshLabel() {}, show() {}, hide() {}, target: () => null, destroy() {} },
    overlays: stack, symbol: () => ({ symbol: 'TEST', exchange: 'NSE' }), interval: () => '1m',
    ...(intervals === undefined ? {} : { intervals }),
  };
  const layer = stack.layer as unknown as FakeElement;
  return { ctx, chart, q: (sel) => layer.querySelector(sel) };
}

describe('the timeframe select in the study settings', () => {
  it('lists the chart first, then the intervals the host serves', () => {
    const r = rig(['1m', '5m', '15m', '1h', 'D']);
    const ema = r.chart.addIndicator('ema', { length: 5 });
    mountIndicatorSettings(r.ctx, undefined, { instanceId: ema.id });
    const select = r.q(`#oac-ind-${ema.id}-timeframe`) as FakeElement;
    expect(select.tagName).toBe('SELECT');
    const options = select.querySelectorAll('option');
    expect(options.map((o) => o.value)).toEqual(['', '1m', '5m', '15m', '1h', 'D']);
    expect(options[0].textContent).toBe('Chart');
    expect(select.value).toBe('');
    const before = ema.values().ma.slice();
    select.value = '15m';
    select.fire('change');
    expect(ema.settings().timeframe).toBe('15m');
    expect(ema.values().ma).not.toEqual(before);
    // Back to the chart's own: the line it drew before.
    (r.q(`#oac-ind-${ema.id}-timeframe`) as FakeElement).value = '';
    (r.q(`#oac-ind-${ema.id}-timeframe`) as FakeElement).fire('change');
    expect(ema.values().ma).toEqual(before);
  });

  it('keeps a saved timeframe the host does not list as an entry of its own', () => {
    const r = rig(['1m', '5m']);
    const ema = r.chart.addIndicator('ema', { timeframe: '1h' });
    mountIndicatorSettings(r.ctx, undefined, { instanceId: ema.id });
    const select = r.q(`#oac-ind-${ema.id}-timeframe`) as FakeElement;
    expect(select.value).toBe('1h');
    expect(select.querySelectorAll('option').map((o) => o.value)).toEqual(['', '1m', '5m', '1h']);
  });

  it('without a host list, offers the codes it always did', () => {
    const r = rig();
    const rsi = r.chart.addIndicator('rsi');
    mountIndicatorSettings(r.ctx, undefined, { instanceId: rsi.id });
    const values = (r.q(`#oac-ind-${rsi.id}-timeframe`) as FakeElement).querySelectorAll('option').map((o) => o.value);
    expect(values).toEqual(['', '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1w']);
  });

  it('shows no timeframe row for a study that does not take one', () => {
    const r = rig(['1m', '5m']);
    const vwap = r.chart.addIndicator('vwap');
    mountIndicatorSettings(r.ctx, undefined, { instanceId: vwap.id });
    expect(r.q(`#oac-ind-${vwap.id}-timeframe`)).toBeNull();
  });

  it('controlsFromInputs takes the host list as its third argument', () => {
    const [tf] = controlsFromInputs([{ key: 'tf', type: 'interval', label: 'Timeframe', default: '' }], undefined, ['5m', '1h']);
    expect(tf.options).toEqual([{ label: 'Chart', value: '' }, { label: '5m', value: '5m' }, { label: '1h', value: '1h' }]);
  });
});
