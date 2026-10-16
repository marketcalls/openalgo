/**
 * At a whole-number device pixel ratio the panes are laid out the way 2.5.5
 * laid them out: a 1 px border between panes, the lower pane's canvases
 * starting under it, and pane-local y measured from the pane box's top.
 *
 * Pane boundaries are rounded onto device pixels at every ratio, so a chart
 * whose panes share the height in whole pixels is the case with nothing to
 * round. For that chart everything that decides the pixels on screen is
 * pinned here: the pane boxes' styles, each canvas's store and CSS box, what
 * else the pane lays over its canvases, every op a full frame draws on each
 * canvas, and the coordinates a host and a pointer read. The digests were
 * recorded by running this file against v2.5.5, so any change to the default
 * layout at a whole ratio fails here rather than on someone's screen.
 *
 * Only a fractional ratio lays a one-device-pixel rule over the lower pane
 * instead, where a 1 px border would start the canvases part way into a
 * device pixel (tests/device-pixels.test.ts).
 */
import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import type { Bar } from '../src/model/bar';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

const T0 = 1_700_000_000;
const BARS: Bar[] = Array.from({ length: 120 }, (_, i) => {
  const close = 100 + Math.sin(i / 7) * 6;
  return { time: T0 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
});

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

/**
 * A price pane over two line panes at 1 : 0.25 : 0.25 in 800 x 600, which
 * splits into 400, 100 and 100 px: whole pixels, nothing to round.
 */
function mount(ratio: number): { chart: Chart; el: FakeElement } {
  const document = fakeDocument();
  const el = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document, pixelRatio: () => ratio, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  chart.addSeries('line', { paneIndex: 1 }).setData(BARS.map(b => ({ time: b.time, value: 50 + Math.sin(b.time / 3000) * 10 })));
  chart.addSeries('line', { paneIndex: 2 }).setData(BARS.map(b => ({ time: b.time, value: b.volume ?? 0 })));
  chart.setPaneWeight(1, 0.25);
  chart.setPaneWeight(2, 0.25);
  return { chart, el };
}

const PANE_STYLE = ['position', 'width', 'flex', 'display', 'overflow', 'boxSizing', 'borderTopStyle', 'borderTopWidth', 'borderTopColor'];
const CANVAS_STYLE = ['position', 'top', 'left', 'width', 'height', 'zIndex'];
const pick = (style: Record<string, string>, keys: readonly string[]): Record<string, string | undefined> =>
  Object.fromEntries(keys.map(key => [key, style[key]]));
const ops = (ctx: CanvasRenderingContext2D): unknown[] => (ctx as unknown as RecordingContext).ops;

/** The DOM each pane is on screen: its box, its canvases, and anything else it shows over them. */
function layout(chart: Chart): unknown {
  return chart.panes().map(pane => {
    const layers = [pane.base, pane.top];
    const children = (pane.element as unknown as { children: { style: Record<string, string> }[] }).children;
    return {
      box: pick(pane.element.style as unknown as Record<string, string>, PANE_STYLE),
      canvases: layers.map(layer => ({
        width: layer.element.width, height: layer.element.height,
        style: pick(layer.element.style as unknown as Record<string, string>, CANVAS_STYLE),
      })),
      shownOver: children.filter(child => !layers.some(layer => layer.element === (child as unknown)) && child.style.display !== 'none').length,
    };
  });
}

/** Every op a full frame draws, pane by pane, base canvas then top canvas. */
function frame(chart: Chart): unknown {
  for (const pane of chart.panes()) {
    ops(pane.base.ctx).length = 0;
    ops(pane.top.ctx).length = 0;
  }
  chart.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
  return chart.panes().map(pane => [ops(pane.base.ctx), ops(pane.top.ctx)]);
}

/**
 * What a host and a pointer read, container y to pane and price and back, and
 * where on the container each pane's canvas row 0 is: the pane box's top plus
 * the border the canvases start under. The last is what ties a pane-local y to
 * the pixel on screen.
 */
function coordinates(chart: Chart, el: FakeElement): unknown {
  let top = 0;
  const origins = chart.panes().map(pane => {
    const origin = top + (parseFloat(pane.element.style.borderTopWidth ?? '') || 0);
    top += parseFloat(pane.element.style.flex.split(' ')[2]);
    return origin;
  });
  const prices = [[96, 100, 104], [45, 50, 55], [120, 160, 200]];
  const host = chart.panes().map((_, i) => prices[i].map(price => {
    const y = chart.priceToCoordinate(price, i);
    return { y, back: y === null ? null : chart.coordinateToPrice(y, i) };
  }));
  const heard: unknown[] = [];
  chart.on('crosshair:move', (e) => {
    const move = e as { paneIndex: number | null; price: number | null; point: { x: number; y: number } | null };
    heard.push({ paneIndex: move.paneIndex, price: move.price, point: move.point });
  });
  // Either side of each boundary and on it.
  for (const y of [5, 250, 399, 400, 401, 450, 499, 500, 501, 560]) el.dispatch('pointermove', pointer('move', 300, y, { buttons: 0 }));
  return { origins, host, pointer: heard };
}

/** SHA-256 of the JSON form, through the platform digest so the suite needs no runtime typings. */
const digest = async (value: unknown): Promise<string> => {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
};

describe('panes at a whole-number device pixel ratio', () => {
  it('wear the 1 px border, with the lower panes\' canvases under it, as in 2.5.5', () => {
    const { chart } = mount(1);
    const separator = chart.theme().paneSeparator;
    const panes = chart.panes();
    expect(panes.map(pane => pane.element.style.flex)).toEqual(['0 0 400px', '0 0 100px', '0 0 100px']);
    expect(panes[0].element.style.borderTopWidth).toBe('0px');
    for (const pane of panes.slice(1)) {
      expect([pane.element.style.borderTopStyle, pane.element.style.borderTopWidth, pane.element.style.borderTopColor])
        .toEqual(['solid', '1px', separator]);
      expect(pane.element.style.boxSizing).toBe('border-box');
    }
  });

  it('lays the panes out and paints them byte for byte as 2.5.5 did, at a ratio of 1', async () => {
    const { chart } = mount(1);
    expect(await digest(layout(chart))).toBe(RATIO_1_LAYOUT);
    const painted = frame(chart) as unknown[][][];
    // Something to compare: candles, lines, axes and grid on every pane.
    expect(painted.every(([base]) => base.length > 50)).toBe(true);
    expect(await digest(painted)).toBe(RATIO_1_FRAME);
  });

  it('keeps pane-local coordinates where 2.5.5 had them, at a ratio of 1', async () => {
    const { chart, el } = mount(1);
    const read = coordinates(chart, el) as { origins: number[] };
    // Canvas row 0 of a lower pane is the row under its border.
    expect(read.origins).toEqual([0, 401, 501]);
    expect(await digest(read)).toBe(RATIO_1_COORDINATES);
  });

  it('keeps the 2.5.5 layout at a ratio of 2 as well', async () => {
    const { chart } = mount(2);
    expect(await digest(layout(chart))).toBe(RATIO_2_LAYOUT);
    expect(await digest(frame(chart))).toBe(RATIO_2_FRAME);
  });
});

// Recorded on v2.5.5 (b282ae1), and the same on a9ee498, the base of this change.
// The frames were recorded again for 2.5.9, where the last-price tag is drawn
// in a second pass through its strip's clip, after the pane's price lines
// (tests/pane-axis-tags.test.ts). Against the 8071693 streams the only new ops
// are one restore, save, beginPath, rect, clip and translate per pane, where
// the first pass now ends and the second begins: no op that draws moved or
// changed, and no tick label here sits near enough to an edge to be dropped.
const RATIO_1_LAYOUT = 'bd1455549dc7857ae92474247590dc228a56c18ccb554149d23045aeee3e73f2';
const RATIO_1_FRAME = '519a178b6b9d57c9226f49078f81432f35e8f89a61f52255677b6de0fb2a4541';
const RATIO_1_COORDINATES = 'e040a4f3863f6dc97925f6bd5af6871c5700c9e1062810a2b99caa3855968e03';
const RATIO_2_LAYOUT = '9e5b14d0efc2eb945d62b04efceb2b8a5fb986a1d3d0073f22a7ce3bbb7f4b97';
const RATIO_2_FRAME = '90ca0eaaa801ad3d6e1dc1ccb87a1fb636c2db03ff3a5ecf84465d3bae200361';
