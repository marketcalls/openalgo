// Pinning a drawing to the screen from the reference host: the properties
// bar's pin toggle, which converts through the real controller, and the
// inline editor opening over a pinned note wherever the chart has panned.
import { describe, it, expect, beforeEach } from 'vitest';
import { installDom } from './fake-dom.js';
import { DrawingController } from '/dist/openalgo-charts.draw.mjs';
import { fakeChart, rect, line, text, T0, timeToX, priceToY, PX_PER_BAR } from './draw-host.js';

const { mountPropertiesBar } = await import('../src/properties.js');
const { openTextEditor } = await import('../src/text-editor.js');

const PLOT_W = 960;
const PLOT_H = 500;

/**
 * The draw host's fake chart with the rest of what a viewport drawing needs:
 * a time axis, a pane whose projection matches `priceToCoordinate`, and the
 * plot rectangle the chart reports (`plotRect`), which a pane folded to no
 * height has none of. The plot starts at container x 0, so the fractions
 * below can be worked out by hand.
 */
function viewportChart() {
  const chart = fakeChart();
  chart.timeScale = { width: PLOT_W, indexToX: (i) => i * PX_PER_BAR, xToIndex: (x) => x / PX_PER_BAR };
  chart.panes = () => [{ priceToY, yToPrice: (y) => (500 - y) / 2, priceScale: { height: PLOT_H } }];
  chart.plotRect = (paneIndex) => {
    const height = chart.panes()[paneIndex]?.priceScale.height ?? 0;
    return height > 0 ? { left: 0, top: 0, width: PLOT_W, height } : null;
  };
  return chart;
}

describe('the pin toggle on the properties bar', () => {
  let dom, chart, draw, app, bar;
  const q = (sel) => bar.el.querySelector(sel);

  beforeEach(() => {
    dom = installDom();
    chart = viewportChart();
    draw = new DrawingController(chart);
    app = { chart, draw, draw2: null, chart2: null, focusPane: 1, props: null, shortcuts: {} };
    bar = mountPropertiesBar(app, dom.stage);
    bar.attach();
  });

  it('pins a rectangle where it is on screen, and unpins it back to the same bars', () => {
    const r = rect(draw);
    const original = draw.get(r.id).points.map((p) => ({ ...p }));
    draw.select(r.id);
    const pin = q('[data-path="space"]');
    expect(pin).not.toBeNull();
    expect(pin.getAttribute('aria-pressed')).toBe('false');
    pin.click();
    const pinned = draw.get(r.id);
    expect(pinned.space).toBe('viewport');
    expect(pinned.points).toEqual([]);
    expect(pinned.viewportPoints[0].x).toBeCloseTo(timeToX(T0 + 600) / PLOT_W, 9);
    expect(pinned.viewportPoints[0].y).toBeCloseTo(priceToY(100) / PLOT_H, 9);
    expect(q('[data-path="space"]').getAttribute('aria-pressed')).toBe('true');
    expect(q('[data-path="space"]').classList.contains('is-on')).toBe(true);
    q('[data-path="space"]').click();
    const back = draw.get(r.id);
    expect(back.space).toBeUndefined();
    back.points.forEach((p, i) => { expect(p.time).toBeCloseTo(original[i].time, 6); expect(p.price).toBeCloseTo(original[i].price, 9); });
  });

  it('says why the drawing did not move when its pane has no plot on screen, both ways', () => {
    const toasts = () => document.querySelectorAll('.toast__msg').map((n) => n.textContent);
    const onScreen = chart.panes;
    // A pane folded to its strip, or hidden behind a maximized one, has no height.
    const fold = () => { chart.panes = () => [{ priceToY, yToPrice: (y) => (500 - y) / 2, priceScale: { height: 0 } }]; };
    const r = rect(draw);
    draw.select(r.id);
    fold();
    q('[data-path="space"]').click();
    expect(draw.get(r.id).space).toBeUndefined();
    expect(q('[data-path="space"]').getAttribute('aria-pressed')).toBe('false');
    expect(toasts()).toEqual(['A drawing can be pinned only while its pane is on screen']);
    // On screen again, the same click pins it and says nothing.
    chart.panes = onScreen;
    q('[data-path="space"]').click();
    expect(draw.get(r.id).space).toBe('viewport');
    expect(toasts()).toHaveLength(1);
    fold();
    q('[data-path="space"]').click();
    expect(draw.get(r.id).space).toBe('viewport');
    expect(q('[data-path="space"]').getAttribute('aria-pressed')).toBe('true');
    expect(toasts()[1]).toBe('A drawing can be unpinned only while its pane is on screen');
  });

  it('is left off the bar for a tool that cannot be pinned', () => {
    const l = line(draw);
    draw.select(l.id);
    expect(q('[data-path="space"]')).toBeNull();
  });

  it('places the bar by a pinned drawing\'s place on screen', () => {
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.5, y: 0.6 }, { x: 0.7, y: 0.8 }] });
    draw.select(r.id);
    expect(bar.el.hidden).toBe(false);
    // Above the drawing's top-left corner, 60% down a 500 px plot, with the
    // chart container 42 px into the stage.
    expect(bar.el.style.left).toBe((0.5 * PLOT_W + 42) + 'px');
    expect(bar.el.style.top).toBe((0.6 * PLOT_H - bar.el.offsetHeight - 10) + 'px');
  });
});

describe('the inline editor over a pinned note', () => {
  it('opens at the controller\'s place for it, not at a time and price', () => {
    const dom = installDom();
    const chart = viewportChart();
    const draw = new DrawingController(chart);
    const t = text(draw);
    draw.update(t.id, { space: 'viewport', viewportPoints: [{ x: 0.25, y: 0.1 }] });
    expect(draw.get(t.id).space).toBe('viewport');
    const ed = openTextEditor({ app: { chart, draw }, id: t.id, host: dom.stage, chartEl: dom.chart });
    expect(ed).not.toBeNull();
    const [at] = draw.screenPoints(t.id);
    expect(at).toEqual({ x: 0.25 * PLOT_W, y: 0.1 * PLOT_H });
    // The chart container sits 42 px into the stage, past the rail.
    expect(ed.el.style.left).toBe(Math.round(at.x + 42) + 'px');
    expect(ed.el.style.top).toBe(Math.round(at.y) + 'px');
    ed.el.textContent = 'Pinned note';
    ed.commit();
    expect(draw.get(t.id).text.value).toBe('Pinned note');
    expect(draw.get(t.id).viewportPoints).toEqual([{ x: 0.25, y: 0.1 }]);
  });
});
