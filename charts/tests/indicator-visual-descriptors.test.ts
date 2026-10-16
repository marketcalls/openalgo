import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorDescriptor, type IndicatorFillSpec } from '../src/model/indicator-registry';
import { IndicatorFill } from '../src/primitives/indicator-fill';
import { ChartTable } from '../src/primitives/table';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';

const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
const bar = (index: number, close = 60) => ({ time: 1000 + index * 60, open: 50, high: 80, low: 20, close });

function mount(fill: IndicatorFillSpec, extra: Partial<IndicatorDescriptor> = {}) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const source = chart.addSeries('candlestick');
  source.setData([bar(0), bar(1), bar(2), bar(3)]);
  const descriptor: IndicatorDescriptor = {
    id: `visual-descriptor-${sequence++}`, name: 'Band', placement: 'onchart', inputs: [],
    plots: [{ key: 'a', title: 'A', type: 'line' }, { key: 'b', title: 'B', type: 'line' }],
    calc: bars => ({ a: bars.map(item => item.close), b: bars.map(() => 40) }),
    fills: [fill], ...extra,
  };
  registerIndicator(descriptor);
  const indicator = chart.addIndicator(descriptor.id);
  const band = chart.panes().flatMap(pane => pane.primitives()).find(item => item instanceof IndicatorFill) as IndicatorFill;
  function paint() {
    indicator.values();
    const { ctx, rec } = makeCtx();
    band.draw(ctx, {
      dpr: 1, timeScale: chart.timeScale, priceScale: { priceToY: (value: number) => 100 - value },
    } as unknown as PrimitiveRenderContext);
    return rec.ops;
  }
  return { chart, source, indicator, paint };
}

describe('native fill descriptor rendering', () => {
  it('resolves per-bar gradient anchors before plot displacement', () => {
    const f = mount({
      between: ['a', 'b'],
      gradientBy: ({ index, a, b, values }) => {
        expect(a).toBe(values.a[index]);
        expect(b).toBe(values.b[index]);
        return { topValue: index < 2 ? 80 : 60, bottomValue: index < 2 ? 60 : 40, topColor: '#aabbcc', bottomColor: '#ddeeff' };
      },
    }, { plots: [{ key: 'a', title: 'A', type: 'line', offset: 3 }, { key: 'b', title: 'B', type: 'line', offset: 3 }] });
    const ops = f.paint();
    expect(ops.filter(op => op.type === 'createLinearGradient').map(op => op.args)).toEqual([[0, 20, 0, 40], [0, 40, 0, 60]]);
    expect(ops.find(op => op.type === 'moveTo')?.args[0]).toBe(f.chart.timeScale.indexToX(3));
  });

  it('refreshes per-bar gradients on settings and live changes, restoring global fallback', () => {
    const f = mount({
      between: ['a', 'b'],
      gradient: { topValue: 90, bottomValue: 10, topColor: '#112233', bottomColor: '#445566' },
      gradientBy: ({ settings, values }) => settings.graded && values.a[3]! > 65
        ? { topValue: 70, bottomValue: 30, topColor: '#aabbcc', bottomColor: '#ddeeff' } : undefined,
    }, { inputs: [{ key: 'graded', label: 'Gradient', type: 'boolean', default: true }] });
    const stops = () => f.paint().filter(op => op.type === 'addColorStop').map(op => op.text);
    expect(stops()).toEqual(['#112233', '#445566']);
    f.source.update(bar(3, 70));
    expect(stops()).toEqual(['#aabbcc', '#ddeeff']);
    f.indicator.setVisible(false);
    expect(stops()).toEqual([]);
    f.indicator.setVisible(true);
    expect(stops()).toEqual(['#aabbcc', '#ddeeff']);
    f.indicator.setSettings({ graded: false });
    expect(stops()).toEqual(['#112233', '#445566']);
    f.indicator.setSettings({ graded: true });
    f.source.update(bar(3));
    expect(stops()).toEqual(['#112233', '#445566']);
  });

  it('paints colors computed per bar and retains plot displacement', () => {
    const f = mount({
      between: ['a', 'b'], colorUp: '#123456',
      colorBy: ({ index, values, a, b }) => {
        expect(a).toBe(values.a[index]);
        expect(b).toBe(values.b[index]);
        return index < 2 ? '#112233' : '#445566';
      },
    }, { plots: [{ key: 'a', title: 'A', type: 'line', offset: 3 }, { key: 'b', title: 'B', type: 'line', offset: 3 }] });
    const ops = f.paint();
    expect(ops.filter(op => op.type === 'fill').map(op => op.fillStyle)).toEqual(['#112233', '#445566']);
    expect(ops.find(op => op.type === 'moveTo')?.args[0]).toBe(f.chart.timeScale.indexToX(3));
  });

  it('refreshes fill colors after settings and same-bar source updates', () => {
    const f = mount({
      between: ['a', 'b'], colorUp: '#123456',
      colorBy: ({ values, settings }) => settings.highlight && values.a[values.a.length - 1]! > 65 ? '#abcdef' : undefined,
    }, { inputs: [{ key: 'highlight', type: 'boolean', label: 'Highlight', default: false }] });
    f.source.update(bar(3, 70));
    expect(f.paint().filter(op => op.type === 'fill').map(op => op.fillStyle)).toEqual(['#123456']);
    f.indicator.setSettings({ highlight: true });
    expect(f.paint().filter(op => op.type === 'fill').map(op => op.fillStyle)).toContain('#abcdef');
    f.source.update(bar(3, 60));
    expect(f.paint().filter(op => op.type === 'fill').map(op => op.fillStyle)).not.toContain('#abcdef');
    f.indicator.setSettings({ highlight: false });
    expect(f.paint().filter(op => op.type === 'fill').map(op => op.fillStyle)).not.toContain('#abcdef');
  });

  it('passes a price-anchored gradient to the renderer', () => {
    const f = mount({
      between: ['a', 'b'], gradient: { topValue: 70, bottomValue: 30, topColor: '#aabbcc', bottomColor: '#ddeeff' },
    });
    const ops = f.paint();
    expect(ops.filter(op => op.type === 'createLinearGradient').map(op => op.args)).toEqual([[0, 30, 0, 70]]);
    expect(ops.filter(op => op.type === 'addColorStop').map(op => [op.args[0], op.text])).toEqual([[0, '#aabbcc'], [1, '#ddeeff']]);
  });

  it('recalculates gradient settings and lets per-bar colors override them', () => {
    const f = mount({
      between: ['a', 'b'], colorUp: '#123456',
      gradient: ({ settings }) => settings.graded ? { topColor: '#aabbcc', bottomColor: '#ddeeff' } : undefined,
      colorBy: ({ index }) => index < 2 ? '#112233' : undefined,
    }, { inputs: [{ key: 'graded', label: 'Gradient', type: 'boolean', default: true }] });
    expect(f.paint().some(op => op.type === 'createLinearGradient')).toBe(true);
    expect(f.paint().filter(op => op.type === 'fill').map(op => op.fillStyle)).toContain('#112233');
    f.indicator.setSettings({ graded: false });
    const ops = f.paint();
    expect(ops.some(op => op.type === 'createLinearGradient')).toBe(false);
    expect(ops.filter(op => op.type === 'fill').map(op => op.fillStyle)).toEqual(['#112233', '#123456']);
  });
});

function tables(chart: Chart, pane?: number) {
  return (pane === undefined ? chart.panes() : [chart.panes()[pane]])
    .flatMap(item => item.primitives()).filter((item): item is ChartTable => item instanceof ChartTable);
}

describe('native table descriptor ownership', () => {
  it('keeps stable table identities across reordering and live updates', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], inputs: [{ key: 'reverse', label: 'Reverse', type: 'boolean', default: false }],
      tables: ({ bars, settings }) => {
        const grids = [
          { id: 'quote', rows: [[{ text: String(bars[bars.length - 1].close) }]], options: { position: 'top-left' as const } },
          { id: 'count', rows: [[{ text: String(bars.length) }]], options: { position: 'bottom-right' as const } },
        ];
        return settings.reverse ? grids.reverse() : grids;
      },
    });
    const initial = tables(f.chart);
    expect(initial).toHaveLength(2);
    f.indicator.setSettings({ reverse: true });
    f.source.update(bar(3, 75));
    f.indicator.values();
    expect(tables(f.chart)).toEqual(initial);
    expect(initial.map(grid => grid.rows()[0][0].text)).toEqual(['75', '4']);
    expect(initial.map(grid => grid.options().position)).toEqual(['top-left', 'bottom-right']);
  });

  it('hides, restores, removes and disposes grids without leaving resources', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], inputs: [{ key: 'count', label: 'Count', type: 'number', default: 2 }],
      tables: ({ settings }) => Array.from({ length: Number(settings.count) }, (_, i) => ({ id: String(i), rows: [[{ text: String(i) }]] })),
    });
    const initial = tables(f.chart);
    expect(initial).toHaveLength(2);
    f.indicator.setVisible(false);
    expect(tables(f.chart)).toEqual(initial);
    expect(initial.map(grid => grid.rows())).toEqual([[], []]);
    f.indicator.setVisible(true);
    expect(initial.map(grid => grid.rows()[0][0].text)).toEqual(['0', '1']);
    f.indicator.setSettings({ count: 1 });
    expect(tables(f.chart)).toEqual([initial[0]]);
    f.indicator.setSettings({ count: 0 });
    expect(tables(f.chart)).toEqual([]);
    f.indicator.setSettings({ count: 2 });
    f.chart.removeIndicator(f.indicator.id);
    expect(tables(f.chart)).toEqual([]);
  });

  it('moves owned grids while retaining explicit price overlays', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], placement: 'pane',
      tables: () => [
        { id: 'local', rows: [[{ text: 'local' }]] },
        { id: 'price', overlay: true, rows: [[{ text: 'price' }]] },
      ],
    });
    const local = tables(f.chart, 1)[0];
    const price = tables(f.chart, 0)[0];
    expect(local?.rows()[0][0].text).toBe('local');
    expect(price?.rows()[0][0].text).toBe('price');
    f.chart.moveIndicator(f.indicator.id, 0);
    expect(tables(f.chart, 0)).toEqual(expect.arrayContaining([local, price]));
    f.chart.moveIndicator(f.indicator.id, 1);
    expect(tables(f.chart, 0)).toEqual([price]);
    expect(tables(f.chart, 1)).toEqual([local]);
    f.chart.removeIndicator(f.indicator.id);
    expect(tables(f.chart)).toEqual([]);
  });

  it('preserves the legacy table hook and gives the plural hook precedence', () => {
    const legacy = mount({ between: ['a', 'b'] }, { fills: [], table: () => ({ rows: [[{ text: 'legacy' }]] }) });
    expect(tables(legacy.chart)[0].rows()[0][0].text).toBe('legacy');
    const both = mount({ between: ['a', 'b'] }, {
      fills: [], table: () => { throw new Error('legacy hook must not run'); },
      tables: () => [{ id: 'new', rows: [[{ text: 'new' }]] }],
    });
    expect(tables(both.chart).map(grid => grid.rows()[0][0].text)).toEqual(['new']);
  });

  it('validates all identities before changing existing grids', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], inputs: [{ key: 'duplicate', label: 'Duplicate', type: 'boolean', default: false }],
      tables: ({ settings }) => settings.duplicate ? [
        { id: 'same', rows: [[{ text: 'replacement' }]] }, { id: 'same', rows: [] },
      ] : [{ id: 'original', rows: [[{ text: 'original' }]] }],
    });
    const initial = tables(f.chart);
    expect(initial).toHaveLength(1);
    f.indicator.setSettings({ duplicate: true });
    const status = f.indicator.dataStatus();
    expect(status?.state).toBe('error');
    expect(String(status?.state === 'error' ? status.error : '')).toMatch(/table.*id/i);
    expect(tables(f.chart)).toEqual(initial);
    expect(initial[0].rows()[0][0].text).toBe('original');
    f.indicator.setSettings({ duplicate: false });
    expect(f.indicator.dataStatus()?.state).toBe('ready');
  });

  it.each(['onchart', 'pane'] as const)('removes resources from %s when the initial table list is invalid', (placement) => {
    const f = mount({ between: ['a', 'b'] });
    const before = f.chart.panes().flatMap(pane => pane.primitives());
    const paneCount = f.chart.panes().length;
    const id = `invalid-tables-${sequence++}`;
    registerIndicator({
      id, name: 'Invalid tables', placement, inputs: [],
      plots: [{ key: 'a', type: 'line', title: 'A' }], calc: bars => ({ a: bars.map(b => b.close) }),
      tables: () => [{ id: '', rows: [[{ text: 'invalid' }]] }],
    });
    expect(() => f.chart.addIndicator(id)).toThrow(/table.*id/i);
    expect(f.chart.panes()).toHaveLength(paneCount);
    const after = f.chart.panes().flatMap(pane => pane.primitives());
    expect(after).toHaveLength(before.length);
    expect(after).toEqual(expect.arrayContaining(before));
  });

  it('reattaches a table when its overlay setting changes', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], placement: 'pane', inputs: [{ key: 'overlay', label: 'Overlay', type: 'boolean', default: false }],
      tables: ({ settings }) => [{ id: 'grid', overlay: settings.overlay === true, rows: [[{ text: 'grid' }]] }],
    });
    expect(tables(f.chart, 1)).toHaveLength(1);
    f.indicator.setSettings({ overlay: true });
    expect(tables(f.chart, 0)).toHaveLength(1);
    expect(tables(f.chart, 1)).toHaveLength(0);
    f.indicator.setSettings({ overlay: false });
    expect(tables(f.chart, 0)).toHaveLength(0);
    expect(tables(f.chart, 1)).toHaveLength(1);
  });

  it('reports a rejected table refresh when shown and recovers after correcting settings', () => {
    const f = mount({ between: ['a', 'b'] }, {
      fills: [], inputs: [{ key: 'bad', label: 'Invalid identity', type: 'boolean', default: false }],
      tables: ({ settings }) => [{ id: settings.bad ? '' : 'valid', rows: [[{ text: 'grid' }]] }],
    });
    f.indicator.setVisible(false);
    f.indicator.setSettings({ bad: true });
    expect(() => f.indicator.setVisible(true)).not.toThrow();
    expect(f.indicator.visible()).toBe(true);
    expect(f.indicator.dataStatus()?.state).toBe('error');
    expect(tables(f.chart)[0].rows()).toEqual([]);
    f.indicator.setSettings({ bad: false });
    expect(f.indicator.dataStatus()?.state).toBe('ready');
    expect(tables(f.chart)[0].rows()[0][0].text).toBe('grid');
  });
});
