import { describe, it, expect, vi } from 'vitest';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

/**
 * The hover-revealed zoom / step controls above the time axis. Hidden until the
 * pointer nears the bottom of the chart, then faded in.
 */

function rc(dpr = 1): PrimitiveRenderContext {
  return {
    dpr,
    plotWidth: 800, plotHeight: 400, priceAxisWidth: 56,
    timeScale: {} as never,
    priceScale: {} as never,
    dataLayer: {} as never,
    theme: { axisText: '#8b91a7', axisLine: '#2a3046', background: '#0d0e12' },
  } as unknown as PrimitiveRenderContext;
}

/** A canvas stub that records what was painted and at what alpha. */
function recorder() {
  const ops: { type: string; alpha: number; text?: string }[] = [];
  const ctx: Record<string, unknown> = {
    canvas: {}, globalAlpha: 1,
    fillStyle: '', strokeStyle: '', lineWidth: 1, lineCap: '', lineJoin: '',
    font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, setLineDash() {},
    roundRect() {}, arc() {},
    measureText: () => ({ width: 40 }),
    fill() { ops.push({ type: 'fill', alpha: ctx.globalAlpha as number }); },
    stroke() { ops.push({ type: 'stroke', alpha: ctx.globalAlpha as number }); },
    fillText(text: string) { ops.push({ type: 'fillText', alpha: ctx.globalAlpha as number, text }); },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, ops };
}

describe('TimeNavigator', () => {
  it('draws nothing until the pointer reaches the reveal band', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    const { ctx, ops } = recorder();

    nav.draw(ctx, rc());                       // never hovered
    expect(ops).toHaveLength(0);

    nav.setPointer({ x: 400, y: 100 });        // well above the band
    nav.draw(ctx, rc());
    expect(ops).toHaveLength(0);

    nav.setPointer({ x: 400, y: 380 });        // inside the bottom 64px
    nav.draw(ctx, rc());
    expect(ops.length).toBeGreaterThan(0);
  });

  it('hides again when the pointer leaves', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    nav.setPointer({ x: 400, y: 380 });
    const shown = recorder();
    nav.draw(shown.ctx, rc());
    expect(shown.ops.length).toBeGreaterThan(0);

    nav.setPointer(null);
    const hidden = recorder();
    nav.draw(hidden.ctx, rc());
    expect(hidden.ops).toHaveLength(0);
  });

  it('fades in over time rather than snapping', () => {
    let t = 0;
    const nav = new TimeNavigator({ fadeSeconds: 0.2 }, () => t);
    nav.setPointer({ x: 400, y: 380 });

    // First frame establishes the clock; nothing has elapsed yet.
    nav.draw(recorder().ctx, rc());
    t = 100;                                    // 0.1s -> halfway
    const mid = recorder();
    nav.draw(mid.ctx, rc());
    const alphas = mid.ops.map((o) => o.alpha);
    expect(alphas.length).toBeGreaterThan(0);
    expect(Math.max(...alphas)).toBeGreaterThan(0);
    expect(Math.max(...alphas)).toBeLessThan(1);
    expect(nav.animating()).toBe(true);

    t = 400;                                    // well past the fade
    nav.draw(recorder().ctx, rc());
    expect(nav.animating()).toBe(false);
  });

  it('hit-tests its buttons only while visible', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    const { ctx } = recorder();

    nav.setPointer({ x: 400, y: 380 });
    nav.draw(ctx, rc());
    // Buttons are centred on the plot; probe the middle of the row.
    const y = 400 - 10 - 26 / 2;
    let found: string[] = [];
    for (let x = 300; x < 500; x++) {
      const h = nav.hitTest(x, y);
      if (h && !found.includes(h.externalId)) found.push(h.externalId);
    }
    expect(found).toEqual([
      'timenav::zoomOut', 'timenav::zoomIn', 'timenav::resetScale',
      'timenav::panLeftBar', 'timenav::panRightBar',
    ]);
    expect(nav.hitTest(400, y)?.externalId).toBe('timenav::resetScale');
    expect(nav.hitTest(379, y)).toBeNull();
    expect(nav.hitTest(421, y)).toBeNull();

    // Hidden: the same probe must find nothing, so the chart body keeps its clicks.
    nav.setPointer(null);
    nav.draw(ctx, rc());
    found = [];
    for (let x = 300; x < 500; x++) if (nav.hitTest(x, y)) found.push('hit');
    expect(found).toHaveLength(0);
  });

  it('reports pointer as a cursor hint on a button', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    nav.setPointer({ x: 400, y: 380 });
    nav.draw(recorder().ctx, rc());
    const y = 400 - 10 - 26 / 2;
    for (let x = 300; x < 500; x++) {
      const h = nav.hitTest(x, y);
      if (h) { expect(h.cursor).toBe('pointer'); return; }
    }
    throw new Error('no button found');
  });

  it('shows the reset tooltip when a host supplies the original four labels', () => {
    const nav = new TimeNavigator({
      fadeSeconds: 0,
      labels: {
        zoomOut: 'Less detail', zoomIn: 'More detail',
        panLeftBar: 'Earlier', panRightBar: 'Later',
      },
    });
    nav.setPointer({ x: 400, y: 377 });
    const reset = recorder();
    nav.draw(reset.ctx, rc());
    expect(reset.ops.filter((op) => op.type === 'fillText').map((op) => op.text)).toEqual(['Reset view']);

    nav.setPointer({ x: 358, y: 377 });
    const zoom = recorder();
    nav.draw(zoom.ctx, rc());
    expect(zoom.ops.filter((op) => op.type === 'fillText').map((op) => op.text)).toEqual(['More detail']);
  });

  it('preserves reset and other tooltips when one label is patched', () => {
    const nav = new TimeNavigator({ fadeSeconds: 0, labels: { zoomIn: 'More detail' } });
    nav.setOptions({ labels: { zoomOut: 'Less detail' } });
    for (const [x, label] of [[328, 'Less detail'], [358, 'More detail'], [400, 'Reset view']] as const) {
      nav.setPointer({ x, y: 377 });
      const { ctx, ops } = recorder();
      nav.draw(ctx, rc());
      expect(ops.filter((op) => op.type === 'fillText').map((op) => op.text)).toEqual([label]);
    }
  });
});

// ── integration: the chart owns one and its buttons drive the time scale ─────

function mountChart(options: Record<string, unknown> = {}) {
  const doc = fakeDocument();
  const container = doc.createElement('div') as unknown as Record<string, unknown>;
  container.clientWidth = 800;
  container.clientHeight = 600;
  container.ownerDocument = doc;
  container.contains = () => false;
  container.tabIndex = 0;

  const chart = new Chart(container as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
    ...options,
  });
  chart.addSeries('candlestick').setData([
    { time: 1000, open: 10, high: 12, low: 8, close: 11 },
    { time: 1060, open: 11, high: 13, low: 9, close: 12 },
    { time: 1120, open: 12, high: 14, low: 10, close: 13 },
  ]);
  return { chart, el: container as unknown as FakeElement };
}

function stubEnv(): void {
  vi.stubGlobal('window', {});
  vi.stubGlobal('requestAnimationFrame', () => 0);
  vi.stubGlobal('cancelAnimationFrame', () => {});
}

describe('chart time navigator', () => {
  it('is present by default and can be turned off', () => {
    stubEnv();
    const on = mountChart().chart;
    const has = (c: Chart): boolean =>
      c.panes().some((p) => p.primitives().some((x) => x instanceof TimeNavigator));
    expect(has(on)).toBe(true);

    const off = mountChart({ timeNavigator: false }).chart;
    expect(has(off)).toBe(false);
    vi.unstubAllGlobals();
  });

  it('zoom and step buttons move the time scale', () => {
    stubEnv();
    const { chart } = mountChart();
    const nav = chart.panes()
      .flatMap((p) => p.primitives())
      .find((x) => x instanceof TimeNavigator) as TimeNavigator;

    // Reveal, then paint so the buttons have geometry to hit.
    nav.setPointer({ x: 300, y: 560 });
    chart.applySize(800, 600);

    // A fresh chart sits at max bar spacing, so zoom *out* first: zooming in
    // from the clamp would look like a no-op and prove nothing.
    const beforeSpacing = chart.timeScale.barSpacing;
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::zoomOut');
    const zoomedOut = chart.timeScale.barSpacing;
    expect(zoomedOut).toBeLessThan(beforeSpacing);

    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::zoomIn');
    expect(chart.timeScale.barSpacing).toBeGreaterThan(zoomedOut);

    // One bar per step, in each direction.
    const offset = chart.timeScale.rightOffset;
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::panRightBar');
    expect(chart.timeScale.rightOffset).toBe(offset + 1);
    (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction('timenav::panLeftBar');
    expect(chart.timeScale.rightOffset).toBe(offset);
    vi.unstubAllGlobals();
  });

  it('clicking the reset button restores the time view and automatic price scaling', () => {
    stubEnv();
    const { chart, el } = mountChart({ timeNavigator: { fadeSeconds: 0 } });
    try {
      chart.applySize(800, 600);
      const priceScale = chart.panes()[0].priceScale;
      const fittedRange = { ...priceScale.priceRange() };
      expect(fittedRange.min).toBeLessThan(8);
      expect(fittedRange.max).toBeGreaterThan(14);

      chart.timeScale.setVisibleLogicalRange({ from: -4, to: 50 });
      priceScale.panByPixels(80);
      expect(chart.timeScale.rightOffset).not.toBe(4);
      expect(chart.timeScale.barSpacing).toBeLessThan(80);
      expect(priceScale.autoScale).toBe(false);
      expect(priceScale.priceRange()).not.toEqual(fittedRange);

      const nav = chart.panes()[0].primitives().find((p) => p instanceof TimeNavigator) as TimeNavigator;
      const x = chart.timeScale.width / 2;
      const y = 555;
      el.dispatch('pointermove', pointer('move', x, y, { buttons: 0 }));
      chart.applySize(800, 600);
      expect(nav.hitTest(x, y)?.externalId).toBe('timenav::resetScale');

      el.dispatch('pointerdown', pointer('down', x, y));
      el.dispatch('pointerup', pointer('up', x, y));
      expect(chart.timeScale.rightOffset).toBe(4);
      expect(chart.timeScale.barSpacing).toBe(80);
      expect(priceScale.autoScale).toBe(true);
      expect(priceScale.priceRange()).toEqual(fittedRange);
    } finally {
      chart.destroy();
      vi.unstubAllGlobals();
    }
  });

  it('keeps the navigator on the bottom pane when panes are added', () => {
    stubEnv();
    const { chart } = mountChart();
    const paneOf = (): number =>
      chart.panes().findIndex((p) => p.primitives().some((x) => x instanceof TimeNavigator));
    expect(paneOf()).toBe(0);

    // A second pane pushes the time axis down; the controls must follow it.
    chart.addSeries('histogram', { paneIndex: 1 })
      .setData([{ time: 1000, open: 0, high: 5, low: 0, close: 5 }]);
    chart.applySize(800, 600);
    expect(paneOf()).toBe(1);
    expect(chart.panes()[0].primitives().some((x) => x instanceof TimeNavigator)).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe('TimeNavigator colours', () => {
  /** The fill and stroke of the first button's plate, for one theme. */
  function plate(theme: { axisText: string; axisLine: string; background: string }): { fill: string; stroke: string } {
    const nav = new TimeNavigator({ fadeSeconds: 0 });
    nav.setPointer({ x: 10, y: 380 });   // in the band, over no button
    const styles: { fill: string[]; stroke: string[] } = { fill: [], stroke: [] };
    const ctx: Record<string, unknown> = {
      canvas: {}, globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1,
      save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, roundRect() {}, arc() {},
      measureText: () => ({ width: 40 }), fillText() {},
      fill() { styles.fill.push(String(ctx.fillStyle)); },
      stroke() { styles.stroke.push(String(ctx.strokeStyle)); },
    };
    nav.draw(ctx as unknown as CanvasRenderingContext2D, { ...rc(), theme } as PrimitiveRenderContext);
    return { fill: styles.fill[0]!, stroke: styles.stroke[0]! };
  }

  it('mixes the plate from six-digit and rgb() theme colours as it always has', () => {
    expect(plate({ axisText: '#8b91a7', axisLine: '#2a3046', background: '#0d0e12' }))
      .toEqual({ fill: 'rgb(28,30,36)', stroke: 'rgba(42,48,70,0.8)' });
    expect(plate({ axisText: 'rgba(139, 145, 167, 1)', axisLine: 'rgb(42,48,70)', background: 'rgb(13,14,18)' }))
      .toEqual({ fill: 'rgb(28,30,36)', stroke: 'rgba(42,48,70,0.8)' });
  });

  it('reads a four-digit #rgba theme colour as its channels', () => {
    // #fff8 is white at about half alpha. Read as the six-digit form it is
    // not, it was the number 0xfff8, a blue green.
    expect(plate({ axisText: '#fff8', axisLine: '#0008', background: '#000f' }))
      .toEqual({ fill: 'rgb(31,31,31)', stroke: 'rgba(0,0,0,0.8)' });
  });
});
