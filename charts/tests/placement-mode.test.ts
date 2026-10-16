import { describe, it, expect, vi, afterEach } from 'vitest';
import { Chart, type ChartClickEvent } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

/**
 * Regression: drawing a rectangle by press-drag-release placed nothing and
 * scrolled the chart instead.
 *
 * A press-drag-release is how every charting UI draws a two-point shape, but the
 * chart's click branch only fires when the pointer never moved, so the gesture
 * produced no anchors at all, while the pan path happily consumed it. Placement
 * mode makes the chart treat the gesture as anchor placement: no pan, and the
 * press and release points are reported as two clicks.
 */

function stubEnv(): void {
  vi.stubGlobal('window', {});                 // _attachInput bails without it
  vi.stubGlobal('requestAnimationFrame', () => 0);  // kinetic fling after a pan
  vi.stubGlobal('cancelAnimationFrame', () => {});
}

function mount() {
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
  });
  chart.addSeries('candlestick').setData([
    { time: 1000, open: 10, high: 12, low: 8, close: 11 },
    { time: 1060, open: 11, high: 13, low: 9, close: 12 },
    { time: 1120, open: 12, high: 14, low: 10, close: 13 },
  ]);

  const clicks: ChartClickEvent[] = [];
  chart.on('click', (p) => clicks.push(p));

  const el = container as unknown as FakeElement;
  const drag = (from: [number, number], to: [number, number]) => {
    el.dispatch('pointerdown', pointer('down', from[0], from[1]));
    const steps = 6;
    for (let i = 1; i <= steps; i++) {
      el.dispatch('pointermove', pointer('move',
        from[0] + ((to[0] - from[0]) * i) / steps,
        from[1] + ((to[1] - from[1]) * i) / steps));
    }
    el.dispatch('pointerup', pointer('up', to[0], to[1]));
  };
  return { chart, clicks, drag };
}

describe('placement mode', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reports a press-drag-release as two clicks, the release tagged viaDrag', () => {
    stubEnv();
    const { chart, clicks, drag } = mount();
    chart.setPlacementMode(true);

    drag([120, 100], [400, 300]);

    expect(clicks).toHaveLength(2);
    expect(clicks[0].viaDrag).toBeUndefined();
    expect(clicks[1].viaDrag).toBe(true);
    // Distinct anchors: identical ones collapse the shape to nothing.
    expect(clicks[0].point).toEqual({ x: 120, y: 100 });
    expect(clicks[1].point.x).toBe(400);
    expect(clicks[0].price).not.toBe(clicks[1].price);
    expect(clicks[0].time).not.toBe(clicks[1].time);
  });

  it('does not pan the chart while placing', () => {
    stubEnv();
    const { chart, drag } = mount();
    chart.setPlacementMode(true);
    const before = chart.timeScale.rightOffset;

    drag([400, 300], [120, 100]);

    expect(chart.timeScale.rightOffset).toBe(before);
  });

  it('still pans, and emits no click, when placement mode is off', () => {
    stubEnv();
    const { chart, clicks, drag } = mount();
    const before = chart.timeScale.rightOffset;

    drag([400, 300], [120, 100]);

    expect(clicks).toHaveLength(0);
    expect(chart.timeScale.rightOffset).not.toBe(before);
  });

  it('a plain click in placement mode is a single click', () => {
    stubEnv();
    const { chart, clicks } = mount();
    chart.setPlacementMode(true);
    const el = (chart as unknown as { _container: FakeElement })._container;

    el.dispatch('pointerdown', pointer('down', 200, 150));
    el.dispatch('pointerup', pointer('up', 200, 150));

    expect(clicks).toHaveLength(1);
    expect(clicks[0].viaDrag).toBeUndefined();
  });
});
