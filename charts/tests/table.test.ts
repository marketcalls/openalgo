import { describe, it, expect } from 'vitest';
import { ChartTable, tableOrigin, type ChartTableOptions, type TableCell } from '../src/primitives/table';
import { SvgContext } from '../src/render/svg-export';
import { makeCtx } from './helpers/fake-ctx';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

function rc(dpr = 1): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 0, max: 100 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr, theme: darkTheme,
  };
}

const grid = [
  [{ text: 'Year' }, { text: 'Jan' }],
  [{ text: '2024', bgColor: '#222222' }, { text: '1.2%', bgColor: '#26a69a' }],
];

describe('tableOrigin', () => {
  it('pins each corner inside the margin', () => {
    // 100x40 table in a 600x400 plot, margin 8.
    expect(tableOrigin('top-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 8 });
    expect(tableOrigin('bottom-right', 8, 100, 40, 600, 400)).toEqual({ x: 492, y: 352 });
    expect(tableOrigin('top-right', 8, 100, 40, 600, 400)).toEqual({ x: 492, y: 8 });
    expect(tableOrigin('bottom-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 352 });
  });

  it('centres on the axis the keyword names, ignoring the margin there', () => {
    expect(tableOrigin('middle-center', 8, 100, 40, 600, 400)).toEqual({ x: 250, y: 180 });
    expect(tableOrigin('top-center', 8, 100, 40, 600, 400)).toEqual({ x: 250, y: 8 });
    expect(tableOrigin('middle-left', 8, 100, 40, 600, 400)).toEqual({ x: 8, y: 180 });
  });
});

describe('ChartTable', () => {
  it('draws one filled rect per cell that declares a background', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ cellWidth: 50, cellHeight: 20 });
    t.setRows(grid);
    t.draw(ctx, rc());
    // Only the second row's two cells carry a bgColor; a cell without one is
    // left transparent so the pane shows through.
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(2);
  });

  it('draws nothing at all when there are no rows', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable();
    t.draw(ctx, rc());
    expect(rec.ops).toHaveLength(0);
  });

  it('scales geometry by the device ratio', () => {
    const at = (dpr: number): number => {
      const { ctx, rec } = makeCtx();
      const t = new ChartTable({ position: 'top-left', margin: 10, cellWidth: 50, cellHeight: 20 });
      t.setRows(grid);
      t.draw(ctx, rc(dpr));
      return rec.ops.find((o) => o.type === 'fillRect')?.args[0] ?? -1;
    };
    // The first filled cell sits at x = margin, so its bitmap x is margin * dpr.
    expect(at(1)).toBe(10);
    expect(at(2)).toBe(20);
  });

  it('derives readable ink from the cell background when no text colour is given', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable();
    // A near-white fill must not take white text.
    t.setRows([[{ text: 'x', bgColor: '#ffffff' }]]);
    t.draw(ctx, rc());
    const inks = rec.ops.filter((o) => o.type === 'fillText').map((o) => o.fillStyle);
    expect(inks[0]).not.toBe('#ffffff');
  });

  it('honours a per-column width array', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: [30, 90], cellHeight: 20 });
    t.setRows([[{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#222' }]]);
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[2]).toBe(30); // first column width
    expect(rects[1].args[0]).toBe(30); // second column starts where the first ends
    expect(rects[1].args[2]).toBe(90);
  });

  it('is a top-layer primitive so it never hides under a series', () => {
    expect(new ChartTable().zOrder()).toBe('top');
  });

  it('hit-tests only inside its own rect, and only when given an id', () => {
    const { ctx } = makeCtx();
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 50, cellHeight: 20, id: 'seasonality' });
    t.setRows(grid);
    t.draw(ctx, rc());
    expect(t.hitTest(10, 10)?.externalId).toBe('seasonality');
    expect(t.hitTest(500, 300)).toBeNull();

    const anon = new ChartTable({ position: 'top-left', margin: 0 });
    anon.setRows(grid);
    anon.draw(ctx, rc());
    expect(anon.hitTest(10, 10)).toBeNull();
  });

  it('reports no hit before it has ever drawn', () => {
    const t = new ChartTable({ id: 'x' });
    t.setRows(grid);
    expect(t.hitTest(0, 0)).toBeNull();
  });

  it('tolerates ragged rows, drawing each to its own length', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ cellWidth: 40, cellHeight: 20 });
    t.setRows([
      [{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#111' }, { text: 'c', bgColor: '#111' }],
      [{ text: 'd', bgColor: '#111' }],
    ]);
    t.draw(ctx, rc());
    expect(rec.ops.filter((o) => o.type === 'fillRect')).toHaveLength(4);
  });
});

describe('ChartTable percentage sizing', () => {
  it('stretches to a share of the plot width, keeping column proportions', () => {
    const { ctx, rec } = makeCtx();
    // Declared 30/90 is a 1:3 split. At 100% of a 600px plot that must become
    // 150/450, not 30/90 nudged over.
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: [30, 90], cellHeight: 20, widthPercent: 100,
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }, { text: 'b', bgColor: '#222' }]]);
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[2]).toBe(150);
    expect(rects[1].args[0]).toBe(150);
    expect(rects[1].args[2]).toBe(450);
  });

  it('divides a share of the plot height evenly across the rows', () => {
    const { ctx, rec } = makeCtx();
    // 50% of a 400px plot is 200px over 4 rows, so each row is 50px.
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, heightPercent: 50 });
    t.setRows(Array.from({ length: 4 }, () => [{ text: 'x', bgColor: '#111' }]));
    t.draw(ctx, rc());
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects[0].args[3]).toBe(50);
    expect(rects[1].args[1]).toBe(50); // second row starts where the first ends
  });

  it('falls back to the fixed cell sizes when a percentage is zero or absent', () => {
    const at = (opts: Record<string, unknown>): number[] => {
      const { ctx, rec } = makeCtx();
      const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, cellHeight: 20, ...opts });
      t.setRows([[{ text: 'x', bgColor: '#111' }]]);
      t.draw(ctx, rc());
      const r = rec.ops.find((o) => o.type === 'fillRect');
      return [r?.args[2] ?? -1, r?.args[3] ?? -1];
    };
    expect(at({})).toEqual([40, 20]);
    expect(at({ widthPercent: 0, heightPercent: 0 })).toEqual([40, 20]);
  });

  it('shrinks the type rather than overflowing a short stretched row', () => {
    const { ctx, rec } = makeCtx();
    // 10% of 400px over 10 rows is a 4px row; an 11px font would spill.
    const t = new ChartTable({ position: 'top-left', margin: 0, cellWidth: 40, fontSize: 11, heightPercent: 10 });
    t.setRows(Array.from({ length: 10 }, () => [{ text: 'x' }]));
    t.draw(ctx, rc());
    const fonts = rec.ops.filter((o) => o.type === 'fillText');
    expect(fonts.length).toBeGreaterThan(0);
    // 4px row * 0.62 floors to 2px, well under the declared 11.
    expect(ctx.font).toContain('2px');
  });
});

describe('ChartTable row weights', () => {
  it('splits a stretched height in proportion to the weights', () => {
    const { ctx, rec } = makeCtx();
    // Weights 1/0.5/1 over 200px (50% of a 400px plot): 80 / 40 / 80.
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: 40, heightPercent: 50,
      rowWeights: [1, 0.5, 1],
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }], [{ text: 'b', bgColor: '#222' }], [{ text: 'c', bgColor: '#333' }]]);
    t.draw(ctx, rc());
    const r = rec.ops.filter((o) => o.type === 'fillRect');
    expect(r.map((o) => o.args[3])).toEqual([80, 40, 80]);
    expect(r.map((o) => o.args[1])).toEqual([0, 80, 120]);
  });

  it('treats a missing, zero or negative weight as 1', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: 40, cellHeight: 10,
      rowWeights: [2, 0, -1],
    });
    t.setRows([[{ text: 'a', bgColor: '#111' }], [{ text: 'b', bgColor: '#222' }], [{ text: 'c', bgColor: '#333' }]]);
    t.draw(ctx, rc());
    expect(rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.args[3])).toEqual([20, 10, 10]);
  });
});

describe('a cell stays inside its own cell', () => {
  /**
   * The reported case: a grid of readings where one column's text was wider
   * than the column, so it was painted straight across the column beside it.
   * Two numbers on top of each other, both unreadable, and nothing in the grid
   * to say which belonged where.
   */
  const WIDE = [
    [{ text: 'Moving averages' }, { text: 'Oscillators' }],
    [{ text: 'SMA 20: 1244.95' }, { text: 'RSI: 27.22' }],
  ]

  it('clips a cell whose text is wider than its column', () => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ cellWidth: 40, fontSize: 11 });
    t.setRows(WIDE);
    t.draw(ctx, rc());
    // One clip per drawn cell. Without it the text simply overflows, and the
    // op stream is identical apart from these: that is why this asserts the
    // clip and not the pixels.
    const clips = rec.ops.filter((op) => op.type === 'clip').length;
    const texts = rec.ops.filter((op) => op.type === 'fillText').length;
    expect(texts).toBe(4);
    expect(clips).toBeGreaterThanOrEqual(texts);
  });

  /** The width the grid actually painted, read off its own background fill. */
  const drawnWidth = (
    rows: readonly (readonly { text: string }[])[],
    options: Partial<ConstructorParameters<typeof ChartTable>[0]>
  ): number | null => {
    const { ctx, rec } = makeCtx();
    const t = new ChartTable({ background: '#101010', ...options });
    t.setRows(rows);
    t.draw(ctx, rc());
    const fill = rec.ops.find((op) => op.type === 'fillRect');
    return fill ? fill.args[2] : null;
  };

  it('measures each column to its widest cell when asked', () => {
    // The fake context measures 6px per character, so the widths are known.
    // 'Moving averages' is the widest of column 0 at 15 characters and
    // 'Oscillators' the widest of column 1 at 11, plus padding for each.
    const auto = drawnWidth(WIDE, { cellWidth: 'auto', fontSize: 11 });
    const fixed = drawnWidth(WIDE, { cellWidth: 64, fontSize: 11 });
    expect(auto).toBeGreaterThan(15 * 6 + 11 * 6);
    expect(auto).toBeLessThan(15 * 6 + 11 * 6 + 40);
    // The point of it: the two columns are sized differently, which a single
    // number cannot do however it is chosen.
    expect(auto).not.toBe(fixed);
  });

  it('gives an empty column a column of room', () => {
    // A grid keeps the shape the caller declared. A column of blanks collapsing
    // to nothing would silently turn a four column grid into a three.
    const width = drawnWidth(
      [
        [{ text: 'A' }, { text: '' }],
        [{ text: 'B' }, { text: '' }],
      ],
      { cellWidth: 'auto' }
    );
    expect(width).toBeGreaterThan(28);
  });

  it('still honours an explicit width, per column and uniform', () => {
    // Auto is opt-in. A caller that measured its own content keeps control.
    expect(drawnWidth(WIDE, { cellWidth: 50 })).toBe(100);
    expect(drawnWidth(WIDE, { cellWidth: [30, 90] })).toBe(120);
  });
});

describe('ChartTable measured fonts', () => {
  const render = (
    rows: readonly (readonly TableCell[])[],
    options: Partial<ChartTableOptions> = {},
    dpr = 1,
  ) => {
    // The recording context has constant text metrics and no state stack.
    // SVG exercises font-dependent measurement and real save/restore together.
    const ctx = new SvgContext(600 * dpr, 400 * dpr, { strict: true });
    const table = new ChartTable({
      position: 'top-left', margin: 0, cellWidth: 'auto', background: '#101010', ...options,
    });
    table.setRows(rows);
    table.draw(ctx.asCanvasContext(), rc(dpr));
    const svg = ctx.toString();
    const width = Number(/<rect\b[^>]* width="([\d.]+)"/.exec(svg)?.[1]);
    const fonts = [...svg.matchAll(/<text\b[^>]* font-size="([\d.]+)"/g)].map((m) => Number(m[1]));
    return { ctx, table, svg, width, fonts };
  };

  it.each([
    { dpr: 1, size: 11, width: 34 },
    { dpr: 1.25, size: 14, width: 43 },
    { dpr: 2, size: 22, width: 68 },
  ])('measures the row-clamped table font at DPR $dpr', ({ dpr, size, width }) => {
    const result = render([[{ text: '8888' }]], { cellHeight: 18, fontSize: 40 }, dpr);
    expect(result.fonts).toEqual([size]);
    expect(result.width).toBe(width);
  });

  it.each([11, 'auto'] as const)('measures a bold cell override after clamping with table font %s', (fontSize) => {
    const result = render([[{ text: '8888', fontSize: 40, bold: true }]], { fontSize });
    expect(result.fonts).toEqual([11]);
    expect(result.svg).toContain('font-weight="600"');
    expect(result.width).toBe(35);
  });

  it('selects the widest rendered cell after applying row weights', () => {
    const result = render([[{ text: '8888' }], [{ text: '88888888' }]], {
      cellHeight: 18, rowWeights: [2, 0.5], fontSize: 40,
    });
    expect(result.fonts).toEqual([22, 5]);
    expect(result.width).toBe(58);
  });

  it.each([
    { dpr: 1, fonts: [6, 18], width: 50 },
    { dpr: 1.5, fonts: [9, 27], width: 74 },
  ])('measures weighted percentage rows at DPR $dpr', ({ dpr, fonts, width }) => {
    const result = render([[{ text: '88888888' }], [{ text: '8888' }]], {
      heightPercent: 10, rowWeights: [1, 3], fontSize: 40,
    }, dpr);
    expect(result.fonts).toEqual(fonts);
    expect(result.width).toBe(width);
  });

  it('uses measured column proportions when stretching and hit-testing the table', () => {
    const result = render([[{ text: '8888' }, { text: '88888888', fontSize: 5 }]], {
      fontSize: 40, widthPercent: 50, id: 'readings',
    });
    // The clamped columns measure 34.2 and 32 media px before stretching.
    expect(result.width).toBe(300);
    expect(result.svg).toMatch(/<clipPath[^>]*><path d="M0 0h155v18h-155Z"/);
    expect(result.svg).toMatch(/<clipPath[^>]*><path d="M155 0h145v18h-145Z"/);
    expect(result.table.hitTest(300, 18)?.externalId).toBe('readings');
    expect(result.table.hitTest(300.01, 18)).toBeNull();
  });

  it('restores the incoming context before a following primitive draws', () => {
    const ctx = new SvgContext(600, 400, { strict: true });
    ctx.font = '23px monospace';
    ctx.fillStyle = '#123456';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    const table = new ChartTable({ cellWidth: 'auto', background: '#101010' });
    table.setRows([[{ text: '8888', bold: true }]]);
    table.draw(ctx.asCanvasContext(), rc());
    ctx.fillText('following primitive', 50, 60);

    expect(ctx.font).toBe('23px monospace');
    expect(ctx.fillStyle).toBe('#123456');
    expect(ctx.textAlign).toBe('right');
    expect(ctx.textBaseline).toBe('top');
    expect(ctx.toString()).toMatch(/<\/g><text x="50" y="60" font-family="monospace" font-size="23"/);
  });

  it('keeps a stable 11px width baseline when both the width and font are automatic', () => {
    const rows = [[{ text: '88888888' }]];
    const tall = render(rows, { fontSize: 'auto', cellHeight: 100 });
    const short = render(rows, { fontSize: 'auto', cellHeight: 10 });
    expect(tall.width).toBe(58);
    expect(short.width).toBe(58);
    expect(tall.fonts).toEqual([11]);
    expect(short.fonts).toEqual([6]);
  });

  it('keeps empty columns and missing cells in the measured bounds', () => {
    const result = render([[{ text: '8888' }, { text: '' }], []], { id: 'empty-column' });
    expect(result.width).toBe(62);
    expect(result.table.hitTest(62, 36)?.externalId).toBe('empty-column');
    expect(result.table.hitTest(62.3, 36)).toBeNull();

    result.table.setRows([[], []]);
    result.table.draw(result.ctx.asCanvasContext(), rc());
    expect(result.table.hitTest(0, 0)).toBeNull();
  });

  it('clips fixed-width cells separately and restores the clip before later drawing', () => {
    const result = render([[{ text: 'Moving averages' }, { text: 'RSI: 27.22' }]], {
      cellWidth: [40, 70],
    });
    result.ctx.fillText('following primitive', 300, 100);
    const svg = result.ctx.toString();
    expect(svg).toMatch(/<clipPath[^>]*><path d="M0 0h40v18h-40Z"/);
    expect(svg).toMatch(/<clipPath[^>]*><path d="M40 0h70v18h-70Z"/);
    expect(svg).toMatch(/>Moving averages<\/text><\/g><g clip-path=/);
    expect(svg).toMatch(/>RSI: 27.22<\/text><\/g><text x="300"/);
  });
});
