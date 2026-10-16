/**
 * The chart grid's layout catalogue and the reflow onto it: every layout from
 * one chart to sixteen, the uneven ones with their spans, the large slot the
 * active chart takes, and a desk that round-trips through the workspace tier.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/index';
import '../src/indicators/index';
import { layoutIconPath } from '../src/draw/index';
import { parseWorkspacePayload } from '../src/workspace/index';
import {
  CHART_GRID_LAYOUTS, CHART_GRID_LAYOUT_NAMES, CHART_GRID_PRESETS, widgetText,
  type ChartGridLayoutId, type ChartGridLayoutSpec,
} from '../src/widget/index';
import { ensureWindowGlobal } from './helpers/fake-dom-widget';
import { el, makeGrid } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const ids = Object.keys(CHART_GRID_LAYOUTS) as ChartGridLayoutId[];
const area = (spec: ChartGridLayoutSpec, i: number): number => {
  const s = spec.slots[i];
  const sum = (w: readonly number[], at: number, n: number): number => w.slice(at, at + n).reduce((a, v) => a + v, 0);
  return sum(spec.rowWeights, s.row, s.rowSpan) * sum(spec.columnWeights, s.column, s.columnSpan);
};

describe('chart grid layout catalogue', () => {
  it.each(ids)('%s covers its grid once, in reading order, inside the schema bounds', id => {
    const spec = CHART_GRID_LAYOUTS[id];
    expect(spec.rows).toBeGreaterThanOrEqual(1);
    expect(spec.rows).toBeLessThanOrEqual(4);
    expect(spec.columns).toBeLessThanOrEqual(4);
    expect(spec.slots.length).toBeLessThanOrEqual(16);
    expect(spec.rowWeights).toHaveLength(spec.rows);
    expect(spec.columnWeights).toHaveLength(spec.columns);
    for (const w of [...spec.rowWeights, ...spec.columnWeights]) expect(w).toBeGreaterThan(0);
    const owner = new Array<number>(spec.rows * spec.columns).fill(-1);
    spec.slots.forEach((s, k) => {
      for (let r = s.row; r < s.row + s.rowSpan; r++) for (let c = s.column; c < s.column + s.columnSpan; c++) {
        expect(owner[r * spec.columns + c]).toBe(-1);
        owner[r * spec.columns + c] = k;
      }
    });
    expect(owner.every(k => k >= 0)).toBe(true);
    const order = spec.slots.map(s => s.row * spec.columns + s.column);
    expect(order).toEqual(order.slice().sort((a, b) => a - b));
    // The picker draws every tile from these slots; a layout the glyph refused would have no tile.
    expect(layoutIconPath(spec.rows, spec.columns, spec.slots)).toMatch(/^M2 2h12v12H2z/);
  });

  it('offers every count from one to sixteen that a desk is built from, with a name for each layout', () => {
    const counts = new Set(ids.map(id => CHART_GRID_LAYOUTS[id].slots.length));
    expect([...counts].sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6, 8, 9, 12, 16]);
    expect(Object.keys(CHART_GRID_LAYOUT_NAMES).sort()).toEqual(ids.slice().sort());
    expect(new Set(Object.values(CHART_GRID_LAYOUT_NAMES)).size).toBe(ids.length);
    // Listed by count, the order the picker shows them in.
    const listed = ids.map(id => CHART_GRID_LAYOUTS[id].slots.length);
    expect(listed).toEqual(listed.slice().sort((a, b) => a - b));
  });

  it('keeps every preset a uniform layout with the rows and columns it names, the 2.5.9 six first', () => {
    expect(Object.keys(CHART_GRID_PRESETS).slice(0, 6)).toEqual(['1x1', '1x2', '1x3', '2x1', '3x1', '2x2']);
    for (const [id, [rows, columns]] of Object.entries(CHART_GRID_PRESETS)) {
      expect(id).toBe(`${rows}x${columns}`);
      const spec = CHART_GRID_LAYOUTS[id as ChartGridLayoutId];
      expect([spec.rows, spec.columns, spec.slots.length]).toEqual([rows, columns, rows * columns]);
      expect(spec.slots.every(s => s.rowSpan === 1 && s.columnSpan === 1)).toBe(true);
    }
  });

  it('gives each uneven layout one chart larger than the rest', () => {
    for (const id of ['left-2', 'right-2', 'top-2', 'bottom-2', 'left-3', 'top-3', 'left-4', 'top-4', 'corner-5', 'corner-7'] as const) {
      const spec = CHART_GRID_LAYOUTS[id];
      const areas = spec.slots.map((_, i) => area(spec, i));
      const most = Math.max(...areas);
      expect(areas.filter(a => a === most)).toHaveLength(1);
    }
    expect(CHART_GRID_LAYOUTS['corner-7'].slots[0]).toEqual({ row: 0, column: 0, rowSpan: 3, columnSpan: 3 });
    expect(CHART_GRID_LAYOUTS['corner-5'].slots[0]).toEqual({ row: 0, column: 0, rowSpan: 2, columnSpan: 2 });
    expect(CHART_GRID_LAYOUTS['corner-7'].slots).toHaveLength(8);
    expect(CHART_GRID_LAYOUTS['corner-5'].slots).toHaveLength(6);
  });

  it('names layouts through the host translator', () => {
    const translate = (key: string, fallback: string): string => (key === 'Large left, three on the right' ? 'Grande a la izquierda' : fallback);
    expect(widgetText({ translate }, CHART_GRID_LAYOUT_NAMES['left-3'])).toBe('Grande a la izquierda');
  });
});

describe('chart grid reflow onto a layout', () => {
  it.each(ids)('builds %s with its spans, weights and splitters, and round-trips it through the workspace tier', id => {
    const spec = CHART_GRID_LAYOUTS[id];
    const { grid, root } = makeGrid({ preset: '1x1' });
    grid.setPreset(id);
    expect(grid.cells()).toHaveLength(spec.slots.length);
    expect(grid.cells().map(c => ({ row: c.row, column: c.column, rowSpan: c.rowSpan, columnSpan: c.columnSpan }))).toEqual(spec.slots);
    expect(grid.layout()).toEqual({ rows: spec.rows, columns: spec.columns, preset: id, rowWeights: [...spec.rowWeights], columnWeights: [...spec.columnWeights] });
    expect(root.querySelectorAll('.oac-grid__cell')).toHaveLength(spec.slots.length);
    const payload = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(payload.layout).toMatchObject({ rows: spec.rows, columns: spec.columns, preset: id });
    const { grid: other } = makeGrid();
    expect(other.applyWorkspace(payload)).toEqual({ applied: true });
    expect(other.layout()).toEqual(grid.layout());
    expect(other.cells().map(c => [c.row, c.column, c.rowSpan, c.columnSpan])).toEqual(grid.cells().map(c => [c.row, c.column, c.rowSpan, c.columnSpan]));
  });

  it('builds sixteen live charts for four by four and drops back to four without rebuilding the survivors', () => {
    const created = vi.spyOn(Chart.prototype, 'addSeries');
    const { grid } = makeGrid({ preset: '2x2' });
    const first = grid.cells().map(c => c.widget);
    grid.setPreset('4x4');
    expect(created).toHaveBeenCalledTimes(16);
    expect(grid.cells().slice(0, 4).map(c => c.widget)).toEqual(first);
    grid.setPreset('2x2');
    expect(grid.cells().map(c => c.widget)).toEqual(first);
    expect(created).toHaveBeenCalledTimes(16);
  });

  it('puts the active chart in the large slot and keeps the others in reading order', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB', 'CCC'][i]));
    grid.setActive(grid.cells()[2].id);
    grid.setPreset('left-3');
    const symbols = grid.cells().map(c => c.widget.symbol());
    expect(symbols).toEqual(['CCC', 'AAA', 'BBB', 'CCC']);
    expect(grid.cells()[0]).toMatchObject({ rowSpan: 3, columnSpan: 1 });
    expect(grid.active().id).toBe(grid.cells()[0].id);
    // The large slot need not come first: in right-2 it is the second in reading order.
    grid.setActive(grid.cells()[1].id);
    grid.setPreset('right-2');
    expect(grid.cells().map(c => c.widget.symbol())).toEqual(['CCC', 'AAA', 'BBB']);
    expect(grid.cells()[1]).toMatchObject({ row: 0, column: 1, rowSpan: 2 });
    expect(grid.active().id).toBe(grid.cells()[1].id);
    // A uniform layout moves nobody.
    grid.setPreset('1x3');
    expect(grid.cells().map(c => c.widget.symbol())).toEqual(['CCC', 'AAA', 'BBB']);
  });

  it('keeps the active chart for the large slot when it sits past the charts that fit, and a uniform layout keeps its 2.5.9 rule', () => {
    const { grid } = makeGrid({ preset: '2x2' });
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB', 'CCC', 'DDD'][i]));
    const [, , third, fourth] = grid.cells();
    grid.setActive(fourth.id);
    const reasons: string[] = [];
    grid.on('active', ({ id }) => reasons.push(id));
    grid.setPreset('left-2');
    // The chart being worked on stays, large; the last of the others that fit makes room for it.
    expect(grid.cells().map(c => c.widget.symbol())).toEqual(['DDD', 'AAA', 'BBB']);
    expect(grid.active().id).toBe(fourth.id);
    expect(grid.cells()[0].widget).toBe(fourth.widget);
    expect(third.widget.isDestroyed).toBe(true);
    expect(reasons).toEqual([]);
    // A uniform layout has no large slot: the charts that fit are the first ones, as before.
    grid.setPreset('2x2');
    grid.setActive(grid.cells()[3].id);
    grid.setPreset('1x2');
    expect(grid.cells().map(c => c.widget.symbol())).toEqual(['DDD', 'AAA']);
  });

  it('starts an uneven layout with its own track weights, and a uniform one with even tracks', () => {
    const { grid, root } = makeGrid({ preset: '2x2' });
    grid.setPreset('left-3');
    expect(grid.layout().columnWeights).toEqual([2, 1]);
    expect(el(root.querySelector('.oac-grid__cells')).style.gridTemplateColumns).toBe('minmax(0,2fr) 4px minmax(0,1fr)');
    grid.setPreset('3x2');
    expect(grid.layout().columnWeights).toEqual([1, 1]);
  });

  it('stops a splitter where the large chart crosses its boundary', () => {
    const { root, grid } = makeGrid({ preset: 'left-3' });
    const splits = root.querySelectorAll('.oac-grid__split').map(s => [s.dataset.axis, s.style.gridArea]);
    // One column splitter down the whole height, and row splitters only beside the large chart.
    expect(splits).toEqual([['column', '1 / 2 / 6 / 3'], ['row', '2 / 3 / 3 / 4'], ['row', '4 / 3 / 5 / 4']]);
    grid.setPreset('corner-5');
    const rowSplits = root.querySelectorAll('.oac-grid__split[data-axis="row"]').map(s => s.style.gridArea);
    // The boundary between rows 1 and 2 runs through the large chart: only the right column has one.
    expect(rowSplits).toEqual(['2 / 5 / 3 / 6', '4 / 1 / 5 / 6']);
  });

  it('refuses an id outside the catalogue before changing anything', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    for (const bad of ['5x5', '0x1', 'toString', '', 'left-9']) expect(() => grid.setPreset(bad as never)).toThrow(/preset or layout/);
    expect(grid.cells()).toHaveLength(2);
  });

  it('starts on an uneven layout from the options', () => {
    const { grid } = makeGrid({ preset: 'corner-7' });
    expect(grid.cells()).toHaveLength(8);
    expect(grid.layout().preset).toBe('corner-7');
    expect(grid.cells()[0]).toMatchObject({ rowSpan: 3, columnSpan: 3 });
  });
});
