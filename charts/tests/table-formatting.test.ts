import { describe, expect, it } from 'vitest';
import { ChartTable, type ChartTableOptions, type TableCell } from '../src/primitives/table';
import { SvgContext } from '../src/render/svg-export';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx } from './helpers/fake-ctx';

const rc = (dpr = 1) => ({ dpr, plotWidth: 600, plotHeight: 400, theme: darkTheme }) as PrimitiveRenderContext;

function paint(rows: readonly (readonly TableCell[])[], options: Partial<ChartTableOptions> = {}, dpr = 1) {
  const { ctx, rec } = makeCtx();
  const measured: { text: string; font: string }[] = [];
  ctx.measureText = text => {
    measured.push({ text, font: ctx.font });
    const size = Number(/([\d.]+)px/.exec(ctx.font)![1]);
    return { width: text.length * size / 2 } as TextMetrics;
  };
  const table = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 100, cellHeight: 50, fontSize: 10, ...options });
  table.setRows(rows);
  table.draw(ctx, rc(dpr));
  return { table, ctx, rec, measured, text: rec.ops.filter(op => op.type === 'fillText') };
}

describe('table text formatting', () => {
  it.each([
    { dpr: 1, cellHeight: 4, font: '6px system-ui, sans-serif' },
    { dpr: 1.5, cellHeight: 20, font: '8px system-ui, sans-serif' },
  ])('retains legacy single-line automatic sizing at DPR $dpr and height $cellHeight', ({ dpr, cellHeight, font }) => {
    const result = paint([[{ text: '88888888' }]], { cellWidth: 10, cellHeight, fontSize: 'auto' }, dpr);
    expect(result.text[0].font).toBe(font);
  });

  it.each([1, 2])('uses italic and a font-family list for both measurement and paint at DPR %s', dpr => {
    const result = paint([[{ text: 'abcdefgh', italic: true, bold: true, fontFamily: '"Custom Face", monospace' }]], {
      cellWidth: 'auto', background: '#101010',
    }, dpr);
    const expected = dpr === 1 ? 'italic 600 10px "Custom Face", monospace' : 'italic 600 20px "Custom Face", monospace';
    expect(result.measured).toEqual([{ text: 'abcdefgh', font: expected }]);
    expect(result.text[0].font).toBe(expected);
    expect(result.rec.ops.find(op => op.type === 'fillRect')?.args).toEqual(dpr === 1 ? [0, 0, 50, 50] : [0, 0, 100, 100]);
  });

  it.each([
    { verticalAlign: 'top' as const, y: [10, 22] },
    { verticalAlign: 'middle' as const, y: [19, 31] },
    { verticalAlign: 'bottom' as const, y: [28, 40] },
  ])('places a multiline block at $verticalAlign', ({ verticalAlign, y }) => {
    const result = paint([[{ text: 'first\nsecond', verticalAlign, align: 'left' }]]);
    expect(result.text.map(op => [op.text, ...op.args])).toEqual([['first', 4, y[0]], ['second', 4, y[1]]]);
  });

  it('normalizes newline forms and retains blank lines in the block height', () => {
    const result = paint([[{ text: 'A\r\n\rB', align: 'right' }]], { cellHeight: 60 });
    expect(result.text.map(op => [op.text, ...op.args])).toEqual([['A', 96, 18], ['', 96, 30], ['B', 96, 42]]);
  });

  it('measures the widest line instead of concatenating the block', () => {
    const result = paint([[{ text: 'abcdefgh\nx' }]], { cellWidth: 'auto', background: '#101010' });
    expect(result.rec.ops.find(op => op.type === 'fillRect')?.args[2]).toBe(50);
    expect(result.measured.map(item => item.text)).toEqual(['abcdefgh', 'x']);
  });

  it.each([
    { dpr: 1, font: '8px system-ui, sans-serif', y: [25.2, 34.8], x: 20 },
    { dpr: 2, font: '16px system-ui, sans-serif', y: [50.4, 69.6], x: 40 },
  ])('fits every line to the available width at DPR $dpr', ({ dpr, font, y, x }) => {
    const result = paint([[{ text: '88888888\n8' }]], { cellWidth: 40, cellHeight: 60, fontSize: 'auto' }, dpr);
    expect(result.text.map(op => op.font)).toEqual([font, font]);
    expect(result.text.map(op => op.args)).toEqual([[x, y[0]], [x, y[1]]]);
  });

  it('caps the automatic minimum by the row height', () => {
    const result = paint([[{ text: 'one\ntwo' }]], { cellHeight: 18, fontSize: 'auto' });
    expect(result.text.map(op => op.font)).toEqual(['4px system-ui, sans-serif', '4px system-ui, sans-serif']);
  });

  it('omits text when the multiline block has no room for a positive font size', () => {
    const result = paint([[{ text: 'one\ntwo' }]], { cellHeight: 8, fontSize: 'auto' });
    expect(result.text).toEqual([]);
  });

  it('clamps fixed multiline fonts before automatic column measurement', () => {
    const result = paint([[{ text: 'abcdefgh\nx', fontSize: 40 }]], { cellWidth: 'auto', cellHeight: 40, background: '#101010' });
    expect(result.text.map(op => op.font)).toEqual(['13px system-ui, sans-serif', '13px system-ui, sans-serif']);
    expect(result.rec.ops.find(op => op.type === 'fillRect')?.args[2]).toBe(62);
  });
});

describe('declarative table spans', () => {
  it('paints only the merged anchor using its appearance and one clip', () => {
    const result = paint([
      [{ text: 'anchor', colSpan: 2, rowSpan: 2, bgColor: '#123', textColor: '#abc' }, { text: 'covered', bgColor: '#456' }, { text: 'right' }],
      [{ text: 'covered', bgColor: '#456' }, { text: 'covered', bgColor: '#456' }, { text: 'right below' }],
    ], { cellWidth: [30, 70, 50], cellHeight: 20, borderColor: '#777' });
    expect(result.text.map(op => op.text)).toEqual(['anchor', 'right', 'right below']);
    expect(result.text[0].args).toEqual([50, 20]);
    expect(result.text[0].fillStyle).toBe('#abc');
    expect(result.rec.ops.filter(op => op.type === 'fillRect').map(op => op.args)).toEqual([[0, 0, 100, 40]]);
    expect(result.rec.ops.filter(op => op.type === 'rect').map(op => op.args)).toEqual([[0, 0, 100, 40], [100, 0, 50, 20], [100, 20, 50, 20]]);
    expect(result.rec.ops.filter(op => op.type === 'strokeRect').map(op => op.args)).toEqual([[0, 0, 100, 40], [100, 0, 50, 20], [100, 20, 50, 20]]);
  });

  it('uses weighted percentage dimensions for a merged cell at DPR 2', () => {
    const result = paint([
      [{ text: 'merged', colSpan: 2, rowSpan: 2, bgColor: '#123' }, { text: '' }, { text: '' }],
      [],
      [{ text: 'last' }],
    ], { margin: 10, cellWidth: [30, 70, 50], widthPercent: 50, heightPercent: 50, rowWeights: [1, 2, 1], id: 'grid' }, 2);
    expect(result.rec.ops.find(op => op.type === 'fillRect')?.args).toEqual([20, 20, 400, 300]);
    expect(result.text[0].args).toEqual([220, 170]);
    expect(result.rec.ops.find(op => op.type === 'rect')?.args).toEqual([20, 20, 400, 300]);
    expect(result.table.hitTest(310, 210)?.externalId).toBe('grid');
    expect(result.table.hitTest(310.01, 210)).toBeNull();
  });

  it('lets a span cover absent cells within the existing rectangular bounds', () => {
    const result = paint([[{ text: 'merged', colSpan: 3, rowSpan: 2 }], [{ text: 'hidden' }, { text: '' }, { text: '' }]], { cellWidth: 20, cellHeight: 20 });
    expect(result.text.map(op => op.text)).toEqual(['merged']);
    expect(result.rec.ops.find(op => op.type === 'rect')?.args).toEqual([0, 0, 60, 40]);
  });

  it('ends a fractional-origin rowspan exactly at the following rounded row boundary', () => {
    const result = paint([[{ text: '' }], [{ text: '', rowSpan: 2, bgColor: '#123' }], [], [{ text: '', bgColor: '#456' }]], {
      cellWidth: 20, cellHeight: 1, rowWeights: [1.4, 0.6, 0.6, 1],
    });
    expect(result.rec.ops.filter(op => op.type === 'fillRect').map(op => op.args)).toEqual([[0, 1, 20, 2], [0, 3, 20, 1]]);
  });

  it('ends a fractional-origin colspan exactly at the following rounded column boundary', () => {
    const result = paint([[{ text: '' }, { text: '', colSpan: 2, bgColor: '#123' }, { text: '' }, { text: '', bgColor: '#456' }]], {
      cellWidth: [1.4, 0.6, 0.6, 1], cellHeight: 20,
    });
    expect(result.rec.ops.filter(op => op.type === 'fillRect').map(op => op.args)).toEqual([[1, 0, 2, 20], [3, 0, 1, 20]]);
  });

  it('sizes ordinary columns first and distributes a merged width deficit evenly', () => {
    const result = paint([
      [{ text: 'abcdefghijkl', colSpan: 2, bgColor: '#111' }, { text: 'ignored huge covered content' }, { text: '' }],
      [{ text: 'aa', bgColor: '#222' }, { text: 'bbbbbb', bgColor: '#333' }, { text: '', bgColor: '#444' }],
    ], { cellWidth: 'auto', cellHeight: 20 });
    expect(result.rec.ops.filter(op => op.type === 'fillRect').map(op => op.args)).toEqual([
      [0, 0, 70, 20], [0, 20, 29, 20], [29, 20, 41, 20], [70, 20, 28, 20],
    ]);
    expect(result.measured.some(item => item.text.includes('ignored'))).toBe(false);
  });

  it('clamps and measures a rowspan font against its entire merged height', () => {
    const result = paint([[{ text: 'abcdefgh', rowSpan: 2, fontSize: 40 }], []], {
      cellHeight: 10, cellWidth: 'auto', background: '#101010',
    });
    expect(result.text[0].font).toBe('12px system-ui, sans-serif');
    expect(result.rec.ops.find(op => op.type === 'fillRect')?.args[2]).toBe(58);
  });

  it.each([
    { colSpan: 0 }, { colSpan: -1 }, { colSpan: 1.5 }, { colSpan: NaN }, { colSpan: Infinity }, { colSpan: Number.MAX_SAFE_INTEGER + 1 },
    { rowSpan: 0 }, { rowSpan: -1 }, { rowSpan: 1.5 }, { rowSpan: NaN }, { rowSpan: Infinity }, { rowSpan: Number.MAX_SAFE_INTEGER + 1 },
    { colSpan: null as unknown as number }, { rowSpan: '2' as unknown as number },
    { colSpan: 3 }, { rowSpan: 3 },
  ])('rejects an invalid span atomically: %j', span => {
    const table = new ChartTable();
    const original = [[{ text: 'original' }]];
    table.setRows(original);
    let updates = 0;
    table.attached({ requestUpdate: () => { updates++; } });
    expect(() => table.setRows([[{ text: 'bad', ...span }, { text: '' }], []])).toThrow(RangeError);
    expect(table.rows()).toBe(original);
    expect(updates).toBe(0);
  });

  it.each([
    [[{ text: '', colSpan: 2 }, { text: '', rowSpan: 2 }], [{ text: '' }, { text: '' }]],
    [[{ text: '' }, { text: '', rowSpan: 2 }], [{ text: '', colSpan: 2 }, { text: '' }]],
  ])('rejects intersecting explicit spans regardless of anchor order', (...rows) => {
    const table = new ChartTable();
    expect(() => table.setRows(rows)).toThrow(RangeError);
  });

  it('validates malformed spans even when the cell is covered', () => {
    const table = new ChartTable();
    expect(() => table.setRows([[{ text: '', colSpan: 2 }, { text: '', rowSpan: 0 }]])).toThrow(RangeError);
  });

  it('accepts explicit unit spans inside a merged cell as ordinary covered content', () => {
    const result = paint([[{ text: 'merged', colSpan: 2 }, { text: 'covered', colSpan: 1, rowSpan: 1 }]]);
    expect(result.text.map(op => op.text)).toEqual(['merged']);
  });
});

describe('table outer frame and context', () => {
  it('draws a distinct outer frame after the cell contents without enlarging hit bounds', () => {
    const svg = new SvgContext(600, 400, { strict: true });
    const table = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 30, cellHeight: 20,
      borderColor: '#111', borderWidth: 1, frameColor: '#fed', frameWidth: 3, id: 'grid' });
    table.setRows([[{ text: 'A' }, { text: 'B' }]]);
    table.draw(svg.asCanvasContext(), rc(2));
    expect(svg.toString()).toContain('<rect x="0" y="0" width="120" height="40" fill="none" stroke="#fed" stroke-width="6"');
    expect(svg.toString().lastIndexOf('stroke="#fed"')).toBeGreaterThan(svg.toString().lastIndexOf('>B</text>'));
    expect(table.hitTest(60, 20)?.externalId).toBe('grid');
    expect(table.hitTest(61, 20)).toBeNull();
  });

  it.each([undefined, 0])('uses an independent frame width %s with the internal border disabled', frameWidth => {
    const result = paint([[{ text: '' }, { text: '' }]], { borderWidth: 0, frameColor: '#fed', frameWidth });
    expect(result.rec.ops.filter(op => op.type === 'strokeRect').map(op => op.args)).toEqual(frameWidth === 0 ? [] : [[0, 0, 200, 50]]);
  });

  it('exports multiline merged formatting in strict SVG and restores incoming state', () => {
    const svg = new SvgContext(600, 400, { strict: true });
    svg.font = '23px serif'; svg.fillStyle = '#123456'; svg.textAlign = 'right'; svg.textBaseline = 'top';
    svg.strokeStyle = '#abcdef'; svg.lineWidth = 5;
    const table = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 'auto', cellHeight: 50, frameColor: '#fed' });
    table.setRows([[{ text: 'A\nB', italic: true, bold: true, fontFamily: 'monospace', fontSize: 10, colSpan: 2 }, { text: 'covered' }]]);
    table.draw(svg.asCanvasContext(), rc());
    expect(svg.unsupported).toEqual([]);
    expect(svg.toString()).toContain('font-family="monospace" font-size="10" font-weight="600" font-style="italic"');
    expect(svg.toString()).toContain('d="M0 0h56v50h-56Z"');
    expect(svg.toString()).toContain('x="28" y="19"');
    expect(svg.toString()).not.toContain('covered');
    expect([svg.font, svg.fillStyle, svg.textAlign, svg.textBaseline, svg.strokeStyle, svg.lineWidth]).toEqual(['23px serif', '#123456', 'right', 'top', '#abcdef', 5]);
  });
});
