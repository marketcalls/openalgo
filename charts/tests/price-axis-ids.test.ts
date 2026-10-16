/**
 * The one-axis family refuses a scale id that names no scale, as placement
 * always did.
 *
 * A pane's `scaleFor` answers the right scale for any id it does not know, so
 * `setPriceAxisOptions(0, 'Left', ...)` from a script host or a saved menu
 * state used to invert the right axis, and `priceAxisState(0, 'x')` described
 * the right scale under a name that does not exist, while
 * `setPriceAxisPlacement(0, 'x', ...)` refused.
 */
import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import type { PriceScaleId } from '../src/model/series';
import { isPriceScaleId } from '../src/model/price-axis-layout';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

/** A seeded random walk, so the fixture looks like a traded stock. */
function walk(n = 60): Bar[] {
  let seed = 5;
  const rand = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const out: Bar[] = [];
  let close = 2310;
  for (let i = 0; i < n; i++) {
    const open = close;
    close = Math.round((open + (rand() - 0.5) * 14) * 100) / 100;
    out.push({ time: 1735699500 + i * 300, open, high: Math.max(open, close) + rand() * 5, low: Math.min(open, close) - rand() * 5, close });
  }
  return out;
}

function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(walk());
  return chart;
}

const BAD = ['Left', 'x', 'overlay', 'RIGHT'] as unknown as PriceScaleId[];

describe('a price scale id that names no scale', () => {
  it('leaves the right axis alone in setPriceAxisOptions and setPriceAxisAutoFit', () => {
    const chart = makeChart();
    const heard: string[] = [];
    chart.on('layout:change', ({ setter }) => heard.push(setter));
    const before = chart.priceAxisState(0, 'right');
    for (const id of BAD) {
      chart.setPriceAxisOptions(0, id, { inverted: true, mode: 'logarithmic' });
      chart.setPriceAxisAutoFit(0, id, false);
    }
    expect(chart.priceAxisState(0, 'right')).toEqual(before);
    expect(heard).toEqual([]);
  });

  it('is refused by setPriceAxisLockRatio and described by nothing', () => {
    const chart = makeChart();
    for (const id of BAD) {
      expect(chart.setPriceAxisLockRatio(0, id, true)).toBe(false);
      expect(chart.priceAxisState(0, id)).toBeNull();
    }
    expect(chart.priceAxisState(0, 'right')?.autoFit).toBe(true);
  });

  it('still reaches every scale a real id names', () => {
    const chart = makeChart();
    chart.setPriceAxisOptions(0, 'right', { inverted: true });
    chart.setPriceAxisOptions(0, 'overlay:vol', { mode: 'percentage' });
    expect(chart.priceAxisState(0, 'right')?.inverted).toBe(true);
    expect(chart.priceAxisState(0, 'overlay:vol')?.mode).toBe('percentage');
  });

  it('is one rule, shared by every reader of an id', () => {
    for (const id of ['right', 'left', '', 'overlay:', 'overlay:vol']) expect(isPriceScaleId(id)).toBe(true);
    for (const id of ['Left', 'x', 'overlay', 'RIGHT', null, 3, undefined]) expect(isPriceScaleId(id)).toBe(false);
  });
});
