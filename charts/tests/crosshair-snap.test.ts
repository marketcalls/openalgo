import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions, type CrosshairMoveEvent } from '../src/core/chart';
import { applyChartSettings, readChartSettings } from '../src/model/chart-settings';
import type { Bar } from '../src/model/bar';
import { fakeDocument, pointer } from './helpers/fake-dom';

const bars: Bar[] = Array.from({ length: 12 }, (_, i) => ({
  time: 1735689600 + i * 60, open: 100 + i, high: 110 + i,
  low: 90 + i, close: 103 + i, volume: 10,
}));
const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function mount(options: Partial<ChartOptions> = {}, data = bars) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} }, ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(data);
  chart.setVisibleLogicalRange({ from: -1, to: 14 });
  const paint = vi.spyOn(chart.panes()[0], 'paintTop');
  const move = (x: number, y = 247) => {
    (chart as unknown as { _onPointerMove(event: unknown): void })._onPointerMove(pointer('move', x, y, { buttons: 0 }));
    return paint.mock.lastCall?.[0];
  };
  const center = chart.timeToCoordinate(bars[6].time)!;
  const spacing = chart.timeToCoordinate(bars[7].time)! - center;
  return { chart, paint, move, center, pointerX: center + spacing * 0.3 };
}

describe('candle-center crosshair', () => {
  it('keeps the default pointer-following behaviour', () => {
    const h = mount();
    expect(h.move(h.pointerX)?.x).toBeCloseTo(h.pointerX);
  });

  it('snaps the painted vertical line while preserving pointer position and price', () => {
    const h = mount({ crosshairSnapToBar: true });
    const events: CrosshairMoveEvent[] = [];
    h.chart.subscribeCrosshairMove(event => events.push(event));
    const cross = h.move(h.pointerX);
    expect(cross?.x).toBeCloseTo(h.center);
    expect(cross?.yLocal).toBe(247);
    expect(events[0].point).toEqual({ x: h.pointerX, y: 247 });
    expect(events[0].bar?.time).toBe(bars[6].time);
  });

  it('repaints an existing cursor immediately when toggled in either direction', () => {
    const h = mount();
    h.move(h.pointerX);
    h.chart.applyOptions({ crosshairSnapToBar: true });
    expect(h.paint.mock.lastCall?.[0]?.x).toBeCloseTo(h.center);
    h.chart.applyOptions({ crosshairSnapToBar: false });
    expect(h.paint.mock.lastCall?.[0]?.x).toBeCloseTo(h.pointerX);
  });

  it('combines center snapping with the independent horizontal price magnet', () => {
    const h = mount({ crosshairSnapToBar: true, crosshairMode: 'magnet' });
    const cross = h.move(h.pointerX);
    expect(cross?.x).toBeCloseTo(h.center);
    expect(cross?.yLocal).not.toBe(247);
    const price = h.chart.panes()[0].yToPrice(cross!.yLocal!);
    expect([bars[6].open, bars[6].high, bars[6].low, bars[6].close]).toContainEqual(expect.closeTo(price, 8));
  });

  it('does not invent a candle in empty data or future space', () => {
    const empty = mount({ crosshairSnapToBar: true }, []);
    expect(empty.move(413.25)?.x).toBe(413.25);
    const h = mount({ crosshairSnapToBar: true });
    const future = h.center + (h.pointerX - h.center) / 0.3 * 7.2;
    expect(h.move(future)?.x).toBeCloseTo(future);
  });

  it('round-trips through chart state and the generated settings schema', () => {
    const a = mount();
    applyChartSettings(a.chart, { 'canvas.crosshairSnapToBar': true });
    expect(a.chart.crosshairSnapToBar()).toBe(true);
    expect(readChartSettings(a.chart)['canvas.crosshairSnapToBar']).toBe(true);
    const b = mount();
    b.chart.restoreState(JSON.parse(JSON.stringify(a.chart.getState())));
    expect(b.move(b.pointerX)?.x).toBeCloseTo(b.center);
    applyChartSettings(a.chart, { 'canvas.crosshairSnapToBar': false });
    b.chart.restoreState(a.chart.getState());
    expect(b.move(b.pointerX)?.x).toBeCloseTo(b.pointerX);
  });

  it('ignores a malformed saved option and preserves older layout behaviour', () => {
    const h = mount();
    h.chart.restoreState({ version: 1, crosshairSnapToBar: 'true' });
    expect(h.move(h.pointerX)?.x).toBeCloseTo(h.pointerX);
    h.chart.restoreState({ version: 1 });
    expect(h.move(h.pointerX)?.x).toBeCloseTo(h.pointerX);
  });
});
