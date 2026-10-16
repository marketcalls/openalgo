/**
 * The crosshair price tag is written in the scale text style, like every
 * other label on the axis strip. It used to set its own 11 px font, so the
 * settings dialog's "Scale text" size (canvas.scales.fontSize) or a theme's
 * axisFontSize moved every axis label except the one under the pointer. The
 * left-axis tag's width was restated from that font in the pane, so the two
 * had to change together; both now come from render/crosshair.ts.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

/** A seeded random walk, so the fixture looks like a traded stock. */
function walk(n = 90): Bar[] {
  let seed = 11;
  const rand = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const out: Bar[] = [];
  let close = 842;
  for (let i = 0; i < n; i++) {
    const open = close;
    close = Math.round((open + (rand() - 0.5) * 9) * 100) / 100;
    out.push({ time: 1735699500 + i * 300, open, high: Math.max(open, close) + rand() * 3, low: Math.min(open, close) - rand() * 3, close, volume: 500 + Math.round(rand() * 700) });
  }
  return out;
}

function build(): { chart: Chart; el: FakeElement } {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(walk());
  return { chart, el };
}

/** The font the latest overlay frame wrote the crosshair price tag in. */
function tagFont(chart: Chart, el: FakeElement, y: number): string | undefined {
  el.dispatch('pointermove', pointer('move', 300, y, { buttons: 0 }));
  const pane = chart.panes()[0]!;
  const text = pane.priceScale.format(pane.priceScale.yToPrice(y));
  const all = (pane.top.ctx as unknown as RecordingContext).ops;
  const ops = all.slice(all.map((o) => o.type).lastIndexOf('clearRect'));
  return ops.filter((o) => o.type === 'fillText' && o.text === text).pop()?.font;
}

describe('the crosshair price tag', () => {
  it('keeps the 11 px default when nothing sets the scale text', () => {
    const { chart, el } = build();
    expect(tagFont(chart, el, 200)).toBe('11px system-ui, sans-serif');
  });

  it('follows the scale text size', () => {
    const { chart, el } = build();
    chart.setCanvasOptions({ scales: { fontSize: 14 } });
    expect(tagFont(chart, el, 200)).toMatch(/^14px /);
  });

  it('follows the theme axis font size', () => {
    const { chart, el } = build();
    chart.setTheme({ ...chart.theme(), axisFontSize: 13 });
    expect(tagFont(chart, el, 240)).toMatch(/^13px /);
  });
});
