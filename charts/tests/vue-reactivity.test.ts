/**
 * Why a Vue host keeps the chart out of reactivity, with Vue's own reactivity.
 *
 * `ref(x)` and `reactive(x)` hand back a deep Proxy of `x`, not `x`. A method
 * called on the proxy runs with `this` bound to the proxy, so every field it
 * reads comes back wrapped, and whatever it builds from those reads keeps the
 * wrappers. The chart, its collaborators and every tier that already holds the
 * chart see the raw object instead. The two stop agreeing about identity:
 * module registries keyed on the chart (the replay window, picks, comparison
 * controllers) hold two unrelated entries, and records written through the
 * proxy name objects the raw chart does not own.
 *
 * Each case below shows the failure with `ref()` and the same steps passing
 * with the forms the framework guide's Vue 3 section recommends: `shallowRef`,
 * `markRaw`, or a plain variable. The browser half is
 * tests/e2e/vue-integration.spec.ts.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { isProxy, markRaw, reactive, ref, shallowRef, toRaw } from 'vue';
import { Chart } from '../src/core/chart';
import { generateBars, isReplaying, ReplayController, type ContextMenuEvent } from '../src/index';
import { createWidget, contextMenuEntries, type MenuItem, type Widget } from '../src/widget/index';
import { fakeDocument } from './helpers/fake-dom';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const widgets: Widget[] = [];
const replays: ReplayController[] = [];
afterEach(() => {
  for (const replay of replays.splice(0)) replay.stop();
  for (const widget of widgets.splice(0)) widget.destroy();
});

/** Measured and painting synchronously, so a call's effects are visible when it returns. */
function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

function makeWidget(onOrder: () => void): Widget {
  const document = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(document) as unknown as HTMLElement, {
    document: document as unknown as Document, mobile: 'never', symbol: 'NIFTY', exchange: 'NSE', onOrder,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  widget.chart.applySize(800, 600);
  widget.series.setData(generateBars(1_700_000_000, 60, 300));
  widgets.push(widget);
  return widget;
}

/** The order rows the widget's own right-click menu would offer at this moment. */
function orderRows(widget: Widget, onOrder: () => void): MenuItem[] {
  const event = { target: { kind: 'series', id: null, seriesType: 'candlestick' }, paneIndex: 0, price: 100, index: 0,
    time: 1_700_000_000, point: { x: 100, y: 100 } } as unknown as ContextMenuEvent;
  return contextMenuEntries(widget.context, event, { onOrder })
    .filter((item): item is MenuItem => 'id' in item && item.id?.startsWith('order-') === true);
}

/** What each recommended form hands back when the component reads the box. */
const RECOMMENDED: readonly [string, <T extends object>(value: T) => T][] = [
  ['shallowRef', value => shallowRef(value).value as typeof value],
  ['markRaw inside ref', value => ref(markRaw(value)).value as typeof value],
  ['markRaw inside reactive state', value => reactive({ held: markRaw(value) }).held as typeof value],
  ['a plain variable', value => value],
];

describe('a chart held in Vue reactivity', () => {
  it('ref() and reactive() hand back a proxy, the recommended forms hand back the chart', () => {
    const chart = makeChart();
    const held = ref(chart).value as unknown as Chart;
    expect(held).not.toBe(chart);
    expect(isProxy(held)).toBe(true);
    expect(toRaw(held)).toBe(chart);
    expect(reactive(chart)).not.toBe(chart);
    // Reads through the proxy wrap what they return, so a host comparing
    // handles it got at different times compares a wrapper with the object.
    const series = held.addSeries('candlestick');
    expect(held.primarySeries()).not.toBe(series);
    expect(held.panes()[0]).not.toBe(chart.panes()[0]);

    for (const [form, box] of RECOMMENDED) {
      const plain = makeChart();
      const out = box(plain);
      expect(out, form).toBe(plain);
      expect(isProxy(out), form).toBe(false);
      const s = out.addSeries('candlestick');
      expect(out.primarySeries(), form).toBe(s);
    }
  });

  it('a series added through a ref()-held chart is foreign to the chart that owns it', () => {
    const chart = makeChart();
    const held = ref(chart).value as unknown as Chart;
    const series = held.addSeries('candlestick');
    series.setData(generateBars(1_700_000_000, 50, 3600));
    // The proxy answers for its own writes...
    expect(held.seriesType(series)).toBe('candlestick');
    // ...and the chart, which is what the widget, the drawing controller and
    // the chart's own callbacks hold, does not know the series: the record
    // written through the proxy names a wrapped pane that is not one of its own.
    expect(chart.seriesType(series)).toBeNull();
    expect(chart.seriesStyle(series)).toBeNull();
    expect(chart.setSeriesType(series, 'line')).toBe(false);

    for (const [form, box] of RECOMMENDED) {
      const plain = makeChart();
      const s = box(plain).addSeries('candlestick');
      s.setData(generateBars(1_700_000_000, 50, 3600));
      expect(plain.seriesType(s), form).toBe('candlestick');
      expect(plain.setSeriesType(s, 'line'), form).toBe(true);
    }
  });

  it('replay started through a ref()-held widget leaves right-click order entry open', () => {
    const onOrder = vi.fn();
    const widget = makeWidget(onOrder);
    const held = ref(widget).value as unknown as Widget;
    expect(orderRows(widget, onOrder).length).toBeGreaterThan(0);
    replays.push(new ReplayController(held.chart, { startIndex: 20 }));
    // Replay is registered against the proxy. The widget checks its own chart,
    // finds no replay, and keeps offering live orders against a replayed price.
    expect(isReplaying(held.chart)).toBe(true);
    expect(isReplaying(widget.chart)).toBe(false);
    expect(orderRows(widget, onOrder).some(row => !row.disabled)).toBe(true);

    for (const [form, box] of RECOMMENDED) {
      const plain = makeWidget(onOrder);
      replays.push(new ReplayController(box(plain).chart, { startIndex: 20 }));
      expect(isReplaying(plain.chart), form).toBe(true);
      const rows = orderRows(plain, onOrder);
      expect(rows.length, form).toBeGreaterThan(0);
      expect(rows.every(row => row.disabled), form).toBe(true);
    }
    expect(onOrder).not.toHaveBeenCalled();
  });

  it('a pick armed through a ref()-held widget survives the drawing tool that should cancel it', () => {
    const widget = makeWidget(() => {});
    const held = ref(widget).value as unknown as Widget;
    const pick = held.chart.beginPick('price', () => {});
    // Choosing a drawing tool puts the chart into placement mode, which
    // cancels any pending pick so one click cannot answer both. The widget's
    // drawing controller holds the chart, the pick was keyed on the proxy.
    widget.draw.setTool('trend-line');
    expect(pick.active()).toBe(true);
    pick();

    for (const [form, box] of RECOMMENDED) {
      const plain = makeWidget(() => {});
      const armed = box(plain).chart.beginPick('price', () => {});
      plain.draw.setTool('trend-line');
      expect(armed.active(), form).toBe(false);
    }
  });

  it('bars kept in ref() are stored inside the chart as proxies', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(ref(generateBars(1_700_000_000, 200, 60)).value);
    // Every frame then reads every visible bar through a proxy trap, and the
    // chart keeps a wrapper alive per bar for as long as it holds the data.
    expect(isProxy(chart.primaryBars()[0])).toBe(true);

    const forms: readonly [string, () => readonly unknown[]][] = [
      ['shallowRef', () => shallowRef(generateBars(1_700_000_000, 200, 60)).value],
      ['toRaw of a ref', () => toRaw(ref(generateBars(1_700_000_000, 200, 60)).value)],
      ['a plain variable', () => generateBars(1_700_000_000, 200, 60)],
    ];
    for (const [form, bars] of forms) {
      const plain = makeChart();
      plain.addSeries('candlestick').setData(bars() as ReturnType<typeof generateBars>);
      expect(isProxy(plain.primaryBars()[0]), form).toBe(false);
    }
  });
});
