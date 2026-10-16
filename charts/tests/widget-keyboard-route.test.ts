/**
 * `keyboardRoute`: a host holding several widgets on one document decides
 * which one answers a chord. Without it both the widget keymap and the
 * engine's shortcuts follow pointer or focus, so the chart under the pointer
 * and the chart holding the focus both act on one key press.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ShortcutManager, type Bar } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const live: Widget[] = [];
afterEach(() => { for (const widget of live.splice(0)) widget.destroy(); });

const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => ({ time: 60 + i * 60, open: 10, high: 12, low: 9, close: 11 }));

function pair(route?: [() => boolean | undefined, () => boolean | undefined], extra: Partial<WidgetOptions> = {}) {
  const doc: FakeDocument = fakeWidgetDocument();
  const make = (keyboardRoute?: WidgetOptions['keyboardRoute']): Widget => {
    const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, rail: false,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} }, keyboardRoute, ...extra,
    });
    widget.chart.applySize(800, 600);
    widget.series.setData(bars(200));
    live.push(widget);
    return widget;
  };
  const widgets = [make(route?.[0]), make(route?.[1])];
  const hits = [0, 0];
  widgets.forEach((widget, i) => widget.context.keymap.register('x', () => { hits[i]++; return true; }, 'widget'));
  const chartEl = (i: number): FakeElement => (widgets[i].root as unknown as FakeElement).querySelector('.oac-chart')!;
  return { doc, widgets, hits, chartEl };
}

describe('widget keyboard routing', () => {
  it('lets both widgets answer when the pointer is on one and the focus on the other', () => {
    const { doc, hits, chartEl } = pair();
    chartEl(1).focus();
    fire(chartEl(0).parentElement!.parentElement!, 'pointerenter');
    fire(chartEl(0), 'pointerenter');
    fireKey(doc.activeElement, 'x');
    expect(hits).toEqual([1, 1]);
  });

  it('silences a widget whose route is false, keymap and chart shortcuts alike', () => {
    const { doc, widgets, hits, chartEl } = pair([() => false, () => undefined]);
    chartEl(1).focus();
    fire(chartEl(0).parentElement!.parentElement!, 'pointerenter');
    fire(chartEl(0), 'pointerenter');
    fireKey(doc.activeElement, 'x');
    expect(hits).toEqual([0, 1]);
    const [a, b] = widgets.map(widget => widget.chart.getVisibleLogicalRange());
    fireKey(doc.activeElement, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(widgets[0].chart.getVisibleLogicalRange()).toEqual(a);
    expect(widgets[1].chart.getVisibleLogicalRange()).not.toEqual(b);
  });

  it('sends chords to a widget whose route is true with neither pointer nor focus on it', () => {
    const { doc, widgets, hits } = pair([() => true, () => false]);
    fireKey(doc.body, 'x');
    expect(hits).toEqual([1, 0]);
    const before = widgets[0].chart.getVisibleLogicalRange();
    fireKey(doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(widgets[0].chart.getVisibleLogicalRange()).not.toEqual(before);
  });

  it('routes the chart shortcuts of a manager the host shares between widgets', () => {
    const shared = new ShortcutManager();
    const { doc, widgets, chartEl } = pair([() => false, () => true], { shortcuts: shared });
    fire(chartEl(0).parentElement!.parentElement!, 'pointerenter');
    fire(chartEl(0), 'pointerenter');
    const [a, b] = widgets.map(widget => widget.chart.getVisibleLogicalRange());
    fireKey(doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(widgets[0].chart.getVisibleLogicalRange()).toEqual(a);
    expect(widgets[1].chart.getVisibleLogicalRange()).not.toEqual(b);
    // Still the host's manager: a rebinding made on it reaches both charts.
    shared.setBinding('panLeft', 'KeyJ');
    const c = widgets[1].chart.getVisibleLogicalRange();
    fireKey(doc.body, 'j', { code: 'KeyJ' });
    expect(widgets[1].chart.getVisibleLogicalRange()).not.toEqual(c);
    expect(widgets[0].chart.shortcuts?.list()).toEqual(shared.list());
  });

  it('keeps a host global scope when the route leaves the choice open', () => {
    const { doc, widgets } = pair([() => undefined, () => false], { shortcuts: { scope: 'global' } });
    const before = widgets[0].chart.getVisibleLogicalRange();
    fireKey(doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(widgets[0].chart.getVisibleLogicalRange()).not.toEqual(before);
  });

  it('keeps the hover scope when the route leaves the choice open', () => {
    const { doc, widgets } = pair([() => undefined, () => false]);
    const before = widgets[0].chart.getVisibleLogicalRange();
    fireKey(doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(widgets[0].chart.getVisibleLogicalRange()).toEqual(before);
  });

  it('keeps the chart shortcuts off when the host turns them off', () => {
    const doc = fakeWidgetDocument();
    const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, rail: false, shortcuts: false, keyboardRoute: () => true,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    });
    live.push(widget);
    expect(widget.chart.shortcuts).toBeNull();
  });
});
