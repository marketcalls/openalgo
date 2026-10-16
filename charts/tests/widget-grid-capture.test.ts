/**
 * One picture of the whole grid: where each chart's own screenshot lands,
 * the ratio it is drawn at, the chrome drawn as a labelled panel, and the
 * refusals: one chart on screen, and a canvas the runtime will not save.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import type { ChartGrid } from '../src/widget/index';
import { captureRatio, composeGridCapture, type GridCapturePiece } from '../src/widget/grid-capture';
import { ensureWindowGlobal, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';
import { el, makeGrid } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

interface Op { op: string; args: unknown[]; fill?: string; font?: string }
/** A canvas whose context records every call with all its arguments. */
function recordingCanvas(): { canvas: HTMLCanvasElement; ops: Op[] } {
  const ops: Op[] = [];
  const ctx = {
    fillStyle: '', font: '', textBaseline: '',
    fillRect(...args: unknown[]) { ops.push({ op: 'fillRect', args, fill: ctx.fillStyle }); },
    drawImage(...args: unknown[]) { ops.push({ op: 'drawImage', args }); },
    fillText(...args: unknown[]) { ops.push({ op: 'fillText', args, fill: ctx.fillStyle, font: ctx.font }); },
  };
  const canvas = { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
  return { canvas, ops };
}
const image = (width: number, height: number): HTMLCanvasElement => ({ width, height }) as HTMLCanvasElement;
const COLORS = { gutter: '#111', panel: '#222', text: '#eee', font: 'sans-serif' };

describe('grid capture composition', () => {
  it('puts each chart image at its place, scaled to device pixels, over its panel and the gutters', () => {
    const { canvas, ops } = recordingCanvas();
    const doc = { createElement: () => canvas } as unknown as Document;
    const left = image(1200, 700), right = image(1188, 700);
    const pieces: GridCapturePiece[] = [
      { cell: { left: 0, top: 0, width: 600, height: 400 }, chart: { left: 0, top: 50, width: 600, height: 350 }, image: left, label: 'AAA 1m' },
      { cell: { left: 604, top: 0, width: 596, height: 400 }, chart: { left: 604, top: 50, width: 594, height: 350 }, image: right, label: 'BBB 5m' },
    ];
    const ratio = captureRatio(pieces, 1);
    expect(ratio).toBe(2);
    const out = composeGridCapture(doc, { width: 1200, height: 400 }, ratio, pieces, COLORS);
    expect([out.width, out.height]).toEqual([2400, 800]);
    expect(ops.filter(o => o.op === 'fillRect')).toEqual([
      { op: 'fillRect', args: [0, 0, 2400, 800], fill: '#111' },
      { op: 'fillRect', args: [0, 0, 1200, 800], fill: '#222' },
      { op: 'fillRect', args: [1208, 0, 1192, 800], fill: '#222' },
    ]);
    expect(ops.filter(o => o.op === 'drawImage')).toEqual([
      { op: 'drawImage', args: [left, 0, 100, 1200, 700] },
      { op: 'drawImage', args: [right, 1208, 100, 1188, 700] },
    ]);
    const labels = ops.filter(o => o.op === 'fillText');
    expect(labels.map(o => [o.args[0], o.args[1], o.args[2], o.fill])).toEqual([['AAA 1m', 16, 50, '#eee'], ['BBB 5m', 1224, 50, '#eee']]);
    expect(labels[0].font).toBe('600 24px sans-serif');
  });

  it('leaves a chart with nothing to show as a plain panel, and writes no label without room for one', () => {
    const { canvas, ops } = recordingCanvas();
    const doc = { createElement: () => canvas } as unknown as Document;
    composeGridCapture(doc, { width: 300, height: 200 }, 1, [
      { cell: { left: 0, top: 0, width: 300, height: 200 }, chart: { left: 0, top: 8, width: 300, height: 192 }, image: image(1, 1), label: 'AAA' },
    ], COLORS);
    expect(ops.filter(o => o.op === 'drawImage')).toEqual([]);
    expect(ops.filter(o => o.op === 'fillText')).toEqual([]);
  });

  it('takes the ratio from the first measured chart, else the fallback', () => {
    const hollow: GridCapturePiece = { cell: { left: 0, top: 0, width: 0, height: 0 }, chart: { left: 0, top: 0, width: 0, height: 0 }, image: image(1, 1), label: '' };
    expect(captureRatio([hollow], 1.5)).toBe(1.5);
    expect(captureRatio([hollow, { ...hollow, chart: { left: 0, top: 0, width: 100, height: 50 }, image: image(300, 150) }], 1)).toBe(3);
    expect(captureRatio([], 0)).toBe(1);
  });

  it('takes the page ratio when a fractional one accounts for the canvas to a pixel, so the picture is not a pixel short', () => {
    // 799.5 CSS px at 1.25 is 999.4 device pixels, drawn on 999: the quotient alone reads 1.2495.
    const piece: GridCapturePiece = { cell: { left: 0, top: 0, width: 800, height: 600 }, chart: { left: 0, top: 30, width: 799.5, height: 570.4 }, image: image(999, 713), label: '' };
    expect(captureRatio([piece], 1.25)).toBe(1.25);
    expect(captureRatio([piece], 1.5)).toBeCloseTo(999 / 799.5, 9);
    expect(captureRatio([piece], 0)).toBeCloseTo(999 / 799.5, 9);
  });
});

describe('grid capture from a grid', () => {
  /** Lay a 1x2 grid out on the page, and record the canvas the grid composes into. */
  function laidOut(grid: ChartGrid, doc: FakeDocument, root: FakeElement) {
    el(root.querySelector('.oac-grid__cells')).rect = { left: 10, top: 40, width: 1204, height: 600 };
    grid.cells().forEach((c, i) => {
      el(c.element).rect = { left: 10 + i * 604, top: 40, width: 600, height: 600 };
      el(c.widget.root).querySelector('.oac-chart')!.rect = { left: 10 + i * 604, top: 80, width: 600, height: 540 };
    });
    const made: Array<{ node: FakeElement; ops: Op[] }> = [];
    const create = doc.createElement.bind(doc);
    doc.createElement = (tag: string): FakeElement => {
      const node = create(tag);
      if (tag === 'canvas') {
        const { canvas, ops } = recordingCanvas();
        (node as unknown as { getContext: unknown }).getContext = (canvas as unknown as { getContext: unknown }).getContext;
        made.push({ node, ops });
      }
      return node;
    };
    return made;
  }

  it('composes every chart at its place inside the cells area, at the charts own ratio', () => {
    const { grid, doc, root } = makeGrid({ preset: '1x2' });
    const made = laidOut(grid, doc, root);
    const out = grid.takeScreenshot() as unknown as FakeElement;
    const composite = made.find(m => m.node === out)!;
    // The charts were measured at 600 px and a ratio of one.
    expect([out.width, out.height]).toEqual([1204, 600]);
    const draws = composite.ops.filter(o => o.op === 'drawImage').map(o => o.args.slice(1));
    expect(draws).toEqual([[0, 40, 600, 540], [604, 40, 600, 540]]);
    expect(composite.ops.filter(o => o.op === 'fillText').map(o => o.args[0])).toEqual(['AAA 1m', 'AAA 1m']);
  });

  it('refuses while one chart is shown, when the others would come out blank', () => {
    const { grid, doc, root } = makeGrid({ preset: '1x2' });
    laidOut(grid, doc, root);
    grid.maximize();
    expect(grid.takeScreenshot()).toBeNull();
    expect(grid.downloadScreenshot()).toBe(false);
    grid.restore();
    expect(grid.takeScreenshot()).not.toBeNull();
  });

  it('saves the picture under a name with the layout, and reports a canvas the runtime will not save', () => {
    const { grid, doc, root } = makeGrid({ preset: '2x2' });
    laidOut(grid, doc, root);
    const anchors: FakeElement[] = [];
    const create = doc.createElement;
    let tainted = false;
    doc.createElement = (tag: string): FakeElement => {
      const node = create(tag);
      if (tag === 'canvas') (node as unknown as { toDataURL(): string }).toDataURL = () => { if (tainted) throw new Error('SecurityError'); return 'data:image/png;base64,AA=='; };
      if (tag === 'a') anchors.push(node);
      return node;
    };
    expect(grid.downloadScreenshot()).toBe(true);
    expect(anchors).toHaveLength(1);
    expect(anchors[0].download).toMatch(/^charts-2x2-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}\.png$/);
    expect(anchors[0].href).toBe('data:image/png;base64,AA==');
    expect(anchors[0].clicks).toBe(1);
    expect(grid.downloadScreenshot('desk.png')).toBe(true);
    expect(anchors[1].download).toBe('desk.png');
    tainted = true;
    expect(grid.downloadScreenshot()).toBe(false);
  });
});
