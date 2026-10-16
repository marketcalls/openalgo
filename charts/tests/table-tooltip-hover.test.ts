import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import type { IPrimitive, PrimitiveHit, PrimitiveRenderContext } from '../src/primitives/primitive';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { ChartTable } from '../src/primitives/table';
import { registerIndicator } from '../src/model/indicator-registry';
import type { RecordingContext } from './helpers/fake-ctx';

type HoverHit = PrimitiveHit;
type HoverContext = PrimitiveRenderContext;
const charts: Chart[] = [];
let nextStudy = 0;
function nativeFixture(deferred = false) {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const frames: (() => void)[] = [];
  const flush = () => { for (let i = 0; i < 100 && frames.length; i++) frames.shift()!(); expect(frames).toHaveLength(0); };
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false, branding: false,
    timeNavigator: false, animAutoscale: false,
    raf: { schedule: callback => { if (deferred) frames.push(callback); else callback(); return 1; }, cancel() {} } });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('line').setData([{ time: 1000, value: 10 }, { time: 1060, value: 20 }]);
  flush();
  const clear = () => { for (const pane of chart.panes()) (pane.top.ctx as unknown as RecordingContext).ops.length = 0; };
  const texts = (index: number) => {
    const ops = (chart.panes()[index].top.ctx as unknown as RecordingContext).ops;
    let from = 0;
    for (let i = 0; i < ops.length; i++) if (ops[i].type === 'clearRect') from = i;
    return ops.slice(from).filter(op => op.type === 'fillText' && op.font === '11px system-ui, sans-serif').map(op => op.text);
  };
  const move = (paneIndex: number, x = 70, y = 70) => {
    clear();
    const screenY = chart.priceToCoordinate(chart.panes()[paneIndex].yToPrice(y), paneIndex)!;
    element.dispatch('pointermove', pointer('move', x, screenY, { buttons: 0 }));
    flush();
  };
  return { chart, element, move, texts, clear, flush };
}
function summaryTable(text: string) {
  const table = new ChartTable({ position: 'top-left', margin: 60, cellWidth: 100, cellHeight: 24, id: 'shared' });
  table.setRows([[{ text: 'Value', tooltip: text }]]);
  return table;
}
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

describe('native table hover routing', () => {
  it('isolates painted tooltips in two panes sharing the same external ID', () => {
    const h = nativeFixture();
    h.chart.addSeries('line', { paneIndex: 1 }).setData([{ time: 1000, value: 3 }, { time: 1060, value: 4 }]);
    const first = summaryTable('first detail'), second = summaryTable('second detail');
    h.chart.addPrimitive(first, 0); h.chart.addPrimitive(second, 1);
    h.move(0); expect(h.texts(0)).toContain('first detail'); expect(h.texts(1)).not.toContain('second detail');
    h.move(1); expect(h.texts(0)).not.toContain('first detail'); expect(h.texts(1)).toContain('second detail');
    h.clear(); h.element.dispatch('pointerleave', pointer('move', 900, 700));
    expect(h.texts(0)).not.toContain('first detail'); expect(h.texts(1)).not.toContain('second detail');
  });

  it('disposes hover content when the owning study updates, hides or is removed', () => {
    const h = nativeFixture(), id = `table-tooltip-owner-${++nextStudy}`;
    registerIndicator({ id, name: 'Table detail', placement: 'pane', plots: [],
      inputs: [{ key: 'detail', type: 'text', label: 'Detail', default: 'old detail' }], calc: () => ({}),
      tables: ({ settings }) => [{ id: 'summary', options: { id: 'shared', position: 'top-left', margin: 60, cellWidth: 100, cellHeight: 24 },
        rows: [[{ text: 'Value', tooltip: String(settings.detail) }]] }],
    });
    const study = h.chart.addIndicator(id);
    h.move(1); expect(h.texts(1)).toContain('old detail');
    h.clear(); study.setSettings({ detail: 'new detail' });
    expect(h.texts(1)).not.toContain('old detail'); expect(h.texts(1)).not.toContain('new detail');
    h.move(1); expect(h.texts(1)).toContain('new detail');
    const table = h.chart.panes()[1].primitives().find(item => item instanceof ChartTable) as ChartTable;
    h.clear(); study.setVisible(false);
    expect(h.texts(1)).not.toContain('new detail'); expect(table.hitTest(70, 70)).toBeNull();
    study.setVisible(true); h.move(1); expect(h.texts(1)).toContain('new detail');
    study.remove(); expect(table.hitTest(70, 70)).toBeNull();
  });

  it('omits transient detail from SVG and restores live hit geometry after resized export', () => {
    const h = nativeFixture(), table = summaryTable('private hover detail');
    table.setOptions({ position: 'bottom-right' }); h.chart.addPrimitive(table);
    const width = 800 - h.chart.priceAxisLayout().reduce((sum, slot) => sum + slot.width, 0);
    const height = h.chart.panes()[0].priceScale.height;
    // Read the scale's actual chart coordinate for a point inside the final row.
    const y = height - 70, x = width - 70;
    h.move(0, x, y); expect(h.texts(0)).toContain('private hover detail');
    const hovered: (string | null | undefined)[] = [];
    const draw = table.draw.bind(table);
    vi.spyOn(table, 'draw').mockImplementation((ctx, rc) => { hovered.push(rc.hoverKey); draw(ctx, rc); });
    const svg = h.chart.exportSVG({ width: 1200, height: 800, background: false });
    expect(svg).toContain('Value'); expect(svg).not.toContain('private hover detail');
    expect(hovered).toContain(null);
    expect(table.hitTest(x, y)?.externalId).toBe('shared');
    expect(table.hitTest(x + 400, y + 200)).toBeNull();
    h.move(0, x, y); expect(h.texts(0)).toContain('private hover detail');
    h.chart.removePrimitive(table); expect(table.hitTest(x, y)).toBeNull();
    h.chart.addPrimitive(table); h.move(0, x, y); expect(h.texts(0)).toContain('private hover detail');
  });

  it('rejects export-sized hit geometry before the next live repaint', () => {
    const h = nativeFixture(true), table = summaryTable('detail');
    table.setOptions({ position: 'bottom-right' });
    let live: PrimitiveRenderContext | null = null;
    const draw = table.draw.bind(table);
    vi.spyOn(table, 'draw').mockImplementation((ctx, rc) => { live = rc; draw(ctx, rc); });
    h.chart.addPrimitive(table); h.flush();
    const before = live!;
    const x = before.plotWidth - 70, y = before.plotHeight - 70;
    expect(table.hitTest(x, y, before)).not.toBeNull();
    h.chart.exportSVG({ width: 1200, height: 800 });
    expect(table.hitTest(x, y, before)).toBeNull();
    h.flush(); expect(table.hitTest(x, y, before)?.externalId).toBe('shared');
    h.move(0, x, y); expect(h.texts(0)).toContain('detail');
  });

  it('forwards hover identity through an actual Chart without changing click or hover event IDs', () => {
    vi.stubGlobal('window', {});
    const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
    const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false, branding: false,
      timeNavigator: false, raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
    charts.push(chart); chart.applySize(800, 600);
    chart.addSeries('line').setData([{ time: 1000, value: 10 }, { time: 1060, value: 20 }]);
    const drawn: (string | null | undefined)[] = [], clicked: unknown[] = [], hovered: unknown[] = [];
    const primitive: IPrimitive = {
      zOrder: () => 'top', draw: (_, rc) => { drawn.push((rc as HoverContext).hoverKey); },
      hitTest: x => ({ externalId: 'summary', hoverKey: x < 70 ? 'cell-A' : 'cell-B', zOrder: 'top', distance: 0 } as HoverHit),
    };
    chart.addPrimitive(primitive);
    chart.on('hover', event => hovered.push(event)); chart.on('click', event => clicked.push(event));
    element.dispatch('pointermove', pointer('move', 30, 80, { buttons: 0 }));
    expect(drawn[drawn.length - 1]).toBe('cell-A');
    element.dispatch('pointermove', pointer('move', 110, 80, { buttons: 0 }));
    expect(drawn[drawn.length - 1]).toBe('cell-B');
    expect(hovered).toEqual([{ id: 'summary' }]);
    element.dispatch('pointerdown', pointer('down', 110, 80)); element.dispatch('pointerup', pointer('up', 110, 80));
    expect(clicked).toHaveLength(1); expect(clicked[0]).toMatchObject({ id: 'summary' });
  });
});
