import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type CrosshairMoveEvent } from '../src/core/chart';
import { DrawingController, DrawingLayer } from '../src/draw/index';
import { darkTheme } from '../src/theme';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.unstubAllGlobals(); });

function mount(magnet: 'off' | 'strong' = 'off') {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, { document: doc, raf: { schedule: () => 0 }, shortcuts: false, timeNavigator: false });
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  const bars = Array.from({ length: 100 }, (_, i) => ({ time: 1700000000 + i * 60, open: 100, high: 102, low: 98, close: 101 }));
  series.setData(bars);
  chart.setVisibleLogicalRange({ from: -40, to: 140 });
  const draw = new DrawingController(chart, { magnet });
  cleanups.push(() => chart.destroy(), () => draw.destroy());
  const move = (x: number, y: number, pressed = false) => el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0 }));
  const click = (x: number, y: number) => {
    move(x, y);
    el.dispatch('pointerdown', pointer('down', x, y));
    el.dispatch('pointerup', pointer('up', x, y));
  };
  const paint = () => {
    const { ctx, rec } = makeCtx();
    const pane = chart.panes()[0];
    const layer = pane.primitives().find(p => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;
    layer.draw(ctx, { timeScale: chart.timeScale, dataLayer: chart.dataLayer, priceScale: pane.priceScale,
      plotWidth: chart.timeScale.width, plotHeight: 578, priceAxisWidth: 56, dpr: 1, theme: darkTheme });
    return rec;
  };
  return { chart, draw, el, move, click, paint, series, bars };
}

describe('drawing into empty time-axis space', () => {
  it.each([['before the first bar', 100], ['after the last bar', 700]] as const)(
    'keeps a trend-line preview at the pointer %s', (_edge, x) => {
      const { chart, draw, click, move, paint } = mount();
      let crosshair: CrosshairMoveEvent | undefined;
      chart.subscribeCrosshairMove(event => { crosshair = event; });
      draw.setTool('trend-line');
      click(400, 200);
      move(x, 360);
      expect(crosshair?.time).toBeNull();
      expect(crosshair?.bar).toBeNull();
      const end = paint().ops.find(op => op.type === 'lineTo');
      expect(end).toBeDefined();
      expect(end?.args[0]).toBeCloseTo(x, 6);
      expect(end?.args[1]).toBeCloseTo(360, 6);
    },
  );

  it('does not pull a future endpoint back to the last candle in strong magnet mode', () => {
    const { draw, click, move, paint } = mount('strong');
    draw.setTool('trend-line');
    click(400, 200);
    move(700, 360);
    const end = paint().ops.find(op => op.type === 'lineTo');
    expect(end?.args[0]).toBeCloseTo(700, 6);
    expect(end?.args[1]).toBeCloseTo(360, 6);
  });

  it('records freehand samples beyond the latest candle', () => {
    const { chart, draw, el, move } = mount();
    draw.setTool('brush');
    move(620, 250);
    el.dispatch('pointerdown', pointer('down', 620, 250));
    move(620, 250, true);
    move(650, 220, true);
    move(700, 310, true);
    el.dispatch('pointerup', pointer('up', 700, 310));
    expect(draw.drawings()).toHaveLength(1);
    const points = draw.drawings()[0].points;
    expect(points.length).toBeGreaterThanOrEqual(3);
    expect(points.every(p => chart.timeToCoordinate(p.time) > 600)).toBe(true);
    expect(chart.timeToCoordinate(points[points.length - 1].time)).toBeCloseTo(700, 6);
  });

  it('hides the preview when the pointer leaves and restores it on reentry', () => {
    const { draw, el, click, move, paint } = mount();
    draw.setTool('trend-line');
    click(400, 200);
    move(700, 360);
    expect(paint().count('lineTo')).toBeGreaterThan(0);
    el.dispatch('pointerleave', pointer('move', 810, 360, { buttons: 0 }));
    expect(paint().count('lineTo')).toBe(0);
    move(680, 340);
    expect(paint().ops.find(op => op.type === 'lineTo')?.args[0]).toBeCloseTo(680, 6);
  });

  it('keeps committed future anchors through a new bar, state restore and undo/redo', () => {
    const { chart, draw, click, series, bars } = mount();
    draw.setTool('trend-line');
    click(400, 200);
    click(700, 360);
    const saved = JSON.parse(JSON.stringify(draw.toJSON()));
    const points = draw.drawings()[0].points.map(p => ({ ...p }));
    expect(points[1].time).toBeGreaterThan(bars[bars.length - 1].time);
    series.update({ ...bars[bars.length - 1], time: bars[bars.length - 1].time + 60 });
    draw.fromJSON(saved);
    expect(draw.drawings()[0].points).toEqual(points);
    expect(Number.isFinite(chart.timeToCoordinate(points[1].time))).toBe(true);
    draw.remove(draw.drawings()[0].id);
    draw.undo();
    expect(draw.drawings()[0].points).toEqual(points);
    draw.redo();
    expect(draw.drawings()).toHaveLength(0);
  });
});
