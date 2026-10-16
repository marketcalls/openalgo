import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartDragEndEvent, type ChartDragEvent } from '../src/core/chart';
import type { PaneRenderContext } from '../src/core/pane';
import type { PriceScaleId } from '../src/model/series';
import type { IPrimitive, PrimitiveHit } from '../src/primitives/primitive';
import { PriceLine } from '../src/primitives/price-line';
import { darkTheme } from '../src/theme';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); vi.unstubAllGlobals(); });

function fixture(readout: 'right' | 'left' = 'right') {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false, branding: false,
    animZoom: false, animAutoscale: false, raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  charts.push(chart); chart.applySize(800, 600);
  for (const id of [readout, readout === 'right' ? 'left' : 'right'] as const) {
    const value = id === 'right' ? 50 : 1500;
    chart.addSeries('line', { priceScaleId: id }).setData([0, 1, 2].map(index => ({
      time: 1700000000 + index * 60, open: value, high: value, low: value, close: value,
    })));
  }
  const pane = chart.panes()[0];
  for (const [id, min, max] of [['right', 0, 100], ['left', 1000, 2000], ['overlay:drag', 1000, 2000]] as const) {
    const scale = pane.scaleFor(id);
    scale.setAutoScale(false); scale.setPriceRange({ min, max }); scale.setHeight(578);
  }
  chart.setVisibleLogicalRange({ from: -2, to: 5 });
  const context: PaneRenderContext = { timeScale: chart.timeScale, dataLayer: chart.dataLayer, dpr: 1,
    priceAxisWidth: 56, leftAxisWidth: 56, timeAxisHeight: 22, showTimeAxis: true,
    conflate: false, conflationFactor: 1, theme: darkTheme, showVertGrid: false, showHorzGrid: false };
  return { chart, pane, element, context };
}

describe('bound primitive hit coordinates', () => {
  it('copies a bound hit with its coordinate scale and preserves the unbound hit identity', () => {
    const { chart, pane, context } = fixture();
    const original: PrimitiveHit = { externalId: 'grip', zOrder: 'top', distance: 0, draggable: true };
    const primitive: IPrimitive = { zOrder: () => 'top', draw() {}, hitTest: () => original };
    chart.addPrimitive(primitive);
    expect(pane.hitTestPrimitives(100, 200, context)).toBe(original);
    pane.bindPrimitiveScale(primitive, 'left');
    const bound = pane.hitTestPrimitives(100, 200, context)!;
    expect(bound).not.toBe(original);
    expect(bound).toMatchObject({ ...original, priceScale: pane.scaleFor('left') });
    expect(original.priceScale).toBeUndefined();
    pane.bindPrimitiveScale(primitive, null);
    expect(pane.hitTestPrimitives(100, 200, context)).toBe(original);
  });

  it.each([
    ['right', 'left', 1500, 1750, 1800],
    ['right', 'overlay:drag', 1500, 1750, 1800],
    ['left', 'right', 50, 75, 80],
  ] as const)('quotes %s-readout chart drags in the bound %s scale', (readout, target, from, moved, ended) => {
    const { chart, pane, element } = fixture(readout);
    const line = new PriceLine({ id: 'bound-level', price: from, color: '#aa44cc', cursor: 'ns-resize' });
    chart.addPrimitive(line); pane.bindPrimitiveScale(line, target);
    const startEvents: ChartDragEndEvent[] = [], moves: ChartDragEvent[] = [], ends: ChartDragEndEvent[] = [];
    chart.on('drag:start', event => startEvents.push(event as ChartDragEndEvent));
    chart.on('drag', event => moves.push(event as ChartDragEvent));
    chart.on('drag:end', event => ends.push(event as ChartDragEndEvent));
    const callback = vi.fn(), endCallback = vi.fn(); chart.subscribeDrag(callback, endCallback);
    const scale = pane.scaleFor(target as PriceScaleId);
    element.dispatch('pointerdown', pointer('down', 250, scale.priceToY(from)));
    element.dispatch('pointermove', pointer('move', 260, scale.priceToY(moved)));
    element.dispatch('pointerup', pointer('up', 270, scale.priceToY(ended)));
    expect(startEvents).toHaveLength(1); expect(moves).toHaveLength(1); expect(ends).toHaveLength(1);
    expect(startEvents[0].price).toBeCloseTo(from);
    expect(moves[0].price).toBeCloseTo(moved); expect(moves[0].fromPrice).toBeCloseTo(from);
    expect(ends[0].price).toBeCloseTo(ended);
    expect(callback.mock.calls[0][1]).toBeCloseTo(moved); expect(endCallback.mock.calls[0][1]).toBeCloseTo(ended);
  });

  it('retains the bound scale for cancellation release and leaves the next unbound drag on its readout scale', () => {
    const { chart, pane, element } = fixture();
    const bound = new PriceLine({ id: 'bound', price: 1500, color: '#aa44cc', cursor: 'ns-resize' });
    chart.addPrimitive(bound); pane.bindPrimitiveScale(bound, 'left');
    const ends: ChartDragEndEvent[] = [], starts: ChartDragEndEvent[] = [], cancels: string[] = [];
    chart.on('drag:start', event => starts.push(event as ChartDragEndEvent));
    chart.on('drag:end', event => ends.push(event as ChartDragEndEvent));
    chart.on('drag:cancel', event => cancels.push((event as { id: string }).id)); chart.subscribeDrag(() => {});
    element.dispatch('pointerdown', pointer('down', 250, pane.scaleFor('left').priceToY(1500)));
    element.dispatch('pointercancel', pointer('up', 250, pane.scaleFor('left').priceToY(1700)));
    expect(cancels).toEqual(['bound']); expect(ends).toHaveLength(1); expect(ends[0].price).toBeCloseTo(1700);
    chart.removePrimitive(bound);
    const unbound = new PriceLine({ id: 'unbound', price: 25, color: '#aa44cc', cursor: 'ns-resize' });
    chart.addPrimitive(unbound);
    element.dispatch('pointerdown', pointer('down', 250, pane.priceScale.priceToY(25)));
    element.dispatch('pointerup', pointer('up', 250, pane.priceScale.priceToY(40)));
    expect(starts[1].price).toBeCloseTo(25); expect(ends[1].price).toBeCloseTo(40);
  });
});
