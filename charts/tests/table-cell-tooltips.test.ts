import { describe, expect, it } from 'vitest';
import { ChartTable, type TableCell } from '../src/primitives/table';
import type { IPrimitive, PrimitiveHit, PrimitiveRenderContext } from '../src/primitives/primitive';
import { darkTheme } from '../src/theme';
import { SvgContext } from '../src/render/svg-export';
import { makeCtx } from './helpers/fake-ctx';

type HoverHit = PrimitiveHit;
type HoverContext = PrimitiveRenderContext;
type TooltipCell = TableCell;
const context = (patch: Partial<HoverContext> = {}): HoverContext => ({
  dpr: 1, plotWidth: 240, plotHeight: 160, theme: darkTheme, hoverId: null, hoverKey: null,
  ...patch,
} as HoverContext);
function fixture(rows: TooltipCell[][], dpr = 1, id?: string) {
  const table = new ChartTable({ position: 'top-left', margin: 20, cellWidth: [50, 70], cellHeight: 25, id });
  const { ctx, rec } = makeCtx(), rc = context({ dpr });
  table.setRows(rows); table.draw(ctx, rc);
  const hit = (x: number, y: number, next = rc): HoverHit | null => (table as IPrimitive).hitTest!(x, y, next) as HoverHit | null;
  const hover = (target: HoverHit | null) => {
    rec.ops.length = 0;
    table.draw(ctx, { ...rc, hoverId: target?.externalId ?? null, hoverKey: target?.hoverKey ?? null } as HoverContext);
    return rec.ops.filter(op => op.type === 'fillText').map(op => op.text);
  };
  return { table, ctx, rec, rc, hit, hover };
}

describe('table cell hover details', () => {
  it('leaves cells without tooltips noninteractive when the table has no ID', () => {
    const h = fixture([[{ text: 'ordinary' }]]);
    expect(h.hit(25, 25)).toBeNull();
    expect(h.hover(null)).toEqual(['ordinary']);
  });

  it('shows literal multiline detail only while a tooltip cell is hovered', () => {
    const h = fixture([[{ text: 'value', tooltip: '<b>literal</b>\nsecond' }]]);
    const hit = h.hit(25, 25);
    expect(hit).not.toBeNull();
    expect(h.hover(hit)).toEqual(['value', '<b>literal</b>', 'second']);
    expect(h.hover(null)).toEqual(['value']);
  });

  it('keeps one click ID while distinguishing adjacent tooltip cells', () => {
    const h = fixture([[{ text: 'A', tooltip: 'first detail' }, { text: 'B', tooltip: 'second detail' }]], 1, 'summary');
    const first = h.hit(25, 25), second = h.hit(85, 25);
    expect(first?.externalId).toBe('summary'); expect(second?.externalId).toBe('summary');
    expect(first?.hoverKey).toBeTypeOf('string');
    expect(first?.hoverKey).not.toBe(second?.hoverKey);
    expect(h.hover(first)).toEqual(['A', 'B', 'first detail']);
    expect(h.hover(second)).toEqual(['A', 'B', 'second detail']);
  });

  it.each([1, 1.5, 2])('uses the entire merged rectangle and anchor detail at DPR %s', dpr => {
    const h = fixture([
      [{ text: 'anchor', colSpan: 2, rowSpan: 2, tooltip: 'merged detail' }, { text: 'covered', tooltip: 'wrong detail' }],
      [{ text: 'covered', tooltip: 'wrong detail' }, { text: 'covered' }],
    ], dpr, 'merged');
    const anchor = h.hit(21, 21), far = h.hit(139, 69);
    expect(anchor?.hoverKey).toBeTypeOf('string'); expect(far?.hoverKey).toBe(anchor?.hoverKey);
    expect(h.hover(far)).toEqual(['anchor', 'merged detail']);
    expect(h.hit(140.1, 69)).toBeNull();
  });

  it('supports tooltip content on a cell with no visible text', () => {
    const h = fixture([[{ text: '', tooltip: 'empty value explanation' }]]);
    const hit = h.hit(25, 25); expect(hit).not.toBeNull();
    expect(h.hover(hit)).toEqual(['empty value explanation']);
  });

  it('clears old hit geometry immediately after accepted row replacement', () => {
    const h = fixture([[{ text: 'old', tooltip: 'old detail' }]], 1, 'summary');
    const old = h.hit(25, 25);
    h.table.setRows([[{ text: 'new', tooltip: 'new detail' }]]);
    expect(h.hit(25, 25)).toBeNull();
    expect(h.hover(old)).toEqual(['new']);
    expect(h.hover(h.hit(25, 25))).toEqual(['new', 'new detail']);
  });

  it('clears old hit geometry when rows are hidden or the primitive detaches', () => {
    const h = fixture([[{ text: 'value', tooltip: 'detail' }]], 1, 'summary');
    h.table.setRows([]); expect(h.hit(25, 25)).toBeNull();
    h.table.setRows([[{ text: 'value', tooltip: 'detail' }]]); h.table.draw(h.ctx, h.rc);
    h.table.detached(); expect(h.hit(25, 25)).toBeNull();
  });

  it('invalidates hit geometry after option or render-size changes until measured again', () => {
    const h = fixture([[{ text: 'value', tooltip: 'detail' }]], 1, 'summary');
    h.table.setOptions({ position: 'bottom-right' }); expect(h.hit(25, 25)).toBeNull();
    h.table.draw(h.ctx, h.rc); expect(h.hit(185, 120)).not.toBeNull();
    expect(h.hit(185, 120, context({ plotWidth: 480 }))).toBeNull();
  });

  it('retains accepted hover geometry when an invalid span replacement is rejected', () => {
    const h = fixture([[{ text: 'value', tooltip: 'detail' }]], 1, 'summary');
    const original = h.hit(25, 25);
    expect(() => h.table.setRows([[{ text: 'bad', colSpan: 2 }]])).toThrow();
    expect(h.hit(25, 25)).toEqual(original);
  });

  it('treats an empty tooltip as omitted and preserves table-wide clicks on plain cells', () => {
    const bare = fixture([[{ text: 'value', tooltip: '' }]]);
    expect(bare.hit(25, 25)).toBeNull();
    const identified = fixture([[{ text: 'value' }]], 1, 'summary');
    expect(identified.hit(25, 25)).toEqual({ externalId: 'summary', zOrder: 'top', distance: 0, cursor: 'default' });
  });

  it('hits rounded cell pixels even when the unrounded table origin lies farther inward', () => {
    const h = fixture([[{ text: 'value', tooltip: 'detail' }]]);
    h.table.setOptions({ margin: 0.4 }); h.table.draw(h.ctx, h.rc);
    const hit = h.hit(0.1, 0.1);
    expect(hit).not.toBeNull(); expect(h.hover(hit)).toContain('detail');
  });

  it('rejects malformed tooltip text without replacing accepted rows or hits', () => {
    const h = fixture([[{ text: 'value', tooltip: 'detail' }]], 1, 'summary');
    const rows = h.table.rows(), hit = h.hit(25, 25);
    expect(() => h.table.setRows([[{ text: 'bad', tooltip: 12 } as unknown as TableCell]])).toThrow(TypeError);
    expect(h.table.rows()).toBe(rows); expect(h.hit(25, 25)).toEqual(hit);
  });

  it('positions multiline detail below a top cell using its measured line heights', () => {
    const h = fixture([[{ text: 'value', tooltip: 'first\nsecond' }]]);
    h.hover(h.hit(25, 25));
    const detail = h.rec.ops.filter(op => op.type === 'fillText').slice(1);
    expect(detail.map(op => op.args)).toEqual([[27, 63.425], [27, 78.275]]);
    expect(detail.map(op => op.font)).toEqual(['11px system-ui, sans-serif', '11px system-ui, sans-serif']);
    expect(h.rec.ops.filter(op => op.type === 'rect').map(op => op.args)).toContainEqual([0, 0, 240, 160]);
  });

  it('wraps an oversized word and bounds the plate to the plot', () => {
    const h = fixture([[{ text: 'value', tooltip: 'abcdefghijklmnopqrstuvwxyz' }]]);
    const rc = context({ plotWidth: 90, plotHeight: 100 });
    h.table.draw(h.ctx, rc); const target = h.hit(25, 25, rc)!;
    h.rec.ops.length = 0;
    h.table.draw(h.ctx, { ...rc, hoverId: target.externalId, hoverKey: target.hoverKey } as HoverContext);
    const detail = h.rec.ops.filter(op => op.type === 'fillText').slice(1);
    expect(detail.map(op => op.text)).toEqual(['abcdefghijklm', 'nopqrstuvwxyz']);
    expect(detail.every(op => op.args[0] >= 0 && op.args[0] + op.text!.length * 6 <= 90)).toBe(true);
    expect(h.rec.ops.filter(op => op.type === 'rect').map(op => op.args)).toContainEqual([0, 0, 90, 100]);
    expect(h.hit(-1, 25, rc)).toBeNull();
  });

  it('restores a strict SVG context and excludes detail when hover is absent', () => {
    const h = fixture([[{ text: 'value', tooltip: '<detail>' }]], 1, 'summary');
    const target = h.hit(25, 25)!;
    const svg = new SvgContext(240, 160, { strict: true });
    svg.font = '17px serif'; svg.fillStyle = '#123456'; svg.textAlign = 'right';
    h.table.draw(svg.asCanvasContext(), { ...h.rc, hoverId: target.externalId, hoverKey: target.hoverKey } as HoverContext);
    expect(svg.font).toBe('17px serif'); expect(svg.fillStyle).toBe('#123456'); expect(svg.textAlign).toBe('right');
    expect(svg.toString()).toContain('&lt;detail&gt;'); expect(svg.unsupported).toEqual([]);
    const clean = new SvgContext(240, 160, { strict: true }); h.table.draw(clean.asCanvasContext(), h.rc);
    expect(clean.toString()).toContain('value'); expect(clean.toString()).not.toContain('detail');
  });

  it('isolates tables sharing an external click ID', () => {
    const first = fixture([[{ text: 'A', tooltip: 'first detail' }]], 1, 'shared');
    const second = fixture([[{ text: 'B', tooltip: 'second detail' }]], 1, 'shared');
    const a = first.hit(25, 25), b = second.hit(25, 25);
    expect(a?.hoverKey).toBeTypeOf('string'); expect(a?.hoverKey).not.toBe(b?.hoverKey);
    expect(first.hover(b)).toEqual(['A']);
    expect(second.hover(b)).toEqual(['B', 'second detail']);
  });

});
