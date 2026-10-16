import { describe, expect, it } from 'vitest';
import { BUILTIN_DRAWING_TOOLS, registerBuiltinDrawingTools } from '../src/draw/tools';
import { anchoredVwapAnalysis, fixedRangeVolumeProfileAnalysis } from '../src/draw/analysis';
import { getDrawingTool } from '../src/draw/registry';
import type { Bar, PrimitiveRenderContext } from '../src';
import type { Drawing } from '../src/draw/types';
import { RecordingContext } from './helpers/fake-ctx';
import { applyDrawingSettings, readDrawingSettings } from '../src/draw/schema';
import { Chart } from '../src/core/chart';
import { DrawingController } from '../src/draw/controller';
import { fakeDocument } from './helpers/fake-dom';

registerBuiltinDrawingTools();
const bar = (time: number, close: number, volume?: number): Bar => ({ time, open: close, high: close, low: close, close, volume });
function context(bars: Bar[], dpr = 1): PrimitiveRenderContext {
  return {
    plotWidth: 500, plotHeight: 400, dpr, bars: () => bars,
    dataLayer: { timeToIndexFloat: (time: number) => time / 60 },
    timeScale: { indexToX: (index: number) => 50 + index * 100 },
    priceScale: { priceToY: (price: number) => 400 - price * 10, format: (price: number) => price.toFixed(2) },
  } as unknown as PrimitiveRenderContext;
}
function drawing(id: string, props: Record<string, unknown> = {}): Drawing {
  return { id: 'analysis', tool: id, paneIndex: 0, zIndex: 0,
    points: [{ time: 0, price: 12 }, ...(id === 'fixed-range-volume-profile' ? [{ time: 120, price: 25 }] : [])],
    style: { ...getDrawingTool(id).defaultStyle }, props };
}
function paint(d: Drawing, rc: PrimitiveRenderContext): RecordingContext {
  const rec = new RecordingContext();
  getDrawingTool(d.tool).draw({
    drawing: d, rc, ctx: rec as unknown as CanvasRenderingContext2D,
    pts: d.points.map(p => ({ x: rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(p.time)) * rc.dpr, y: rc.priceScale.priceToY(p.price) * rc.dpr })),
    style: { color: '#123456', lineWidth: 1.5, ...d.style }, selected: false, formatPrice: p => p.toFixed(2),
  });
  return rec;
}
const texts = (rec: RecordingContext) => rec.ops.filter(o => o.type === 'fillText').map(o => o.text);

describe('analysis calculations', () => {
  it('uses the first timestamp at or after an anchor and stable weighted population variance', () => {
    const result = anchoredVwapAnalysis([bar(0, 1000, 1000), bar(60, 10, 1), bar(120, 20, 3)], 30);
    expect(result.status).toBe('ready');
    expect(result.points.map(p => p.time)).toEqual([60, 120]);
    expect(result.points[1].value).toBe(17.5);
    expect(result.points[1].deviation).toBeCloseTo(Math.sqrt(18.75), 12);
    const large = anchoredVwapAnalysis([bar(0, 1e12 + 1, 1e250), bar(60, 1e12 + 3, 1e250)], 0);
    expect(large.points[1].value).toBe(1e12 + 2);
    expect(large.points[1].deviation).toBe(1);
  });
  it('uses the selected source and carries zero-volume candles without inventing weight', () => {
    const bars = [{ ...bar(0, 18, 2), low: 6, high: 12 }, bar(60, 1000, 0)];
    expect(anchoredVwapAnalysis(bars, 0, { source: 'hlc3' }).points.map(p => p.value)).toEqual([12, 12]);
    expect(anchoredVwapAnalysis(bars, 0, { source: 'close' }).points.map(p => p.value)).toEqual([18, 18]);
  });
  it('marks missing volume separately from zero and incomplete samples', () => {
    expect(anchoredVwapAnalysis([bar(0, 10)], 0).status).toBe('missing-volume');
    expect(anchoredVwapAnalysis([bar(0, 10, 0)], 0).status).toBe('zero-volume');
    expect(anchoredVwapAnalysis([bar(0, 10, 1), bar(60, 20)], 0).status).toBe('partial');
    expect(anchoredVwapAnalysis([bar(0, 10, 1)], 60).status).toBe('empty');
    expect(fixedRangeVolumeProfileAnalysis([bar(0, 10)], 0, 0).status).toBe('missing-volume');
    expect(fixedRangeVolumeProfileAnalysis([bar(0, 10, 0)], 0, 0).status).toBe('zero-volume');
  });
  it('distributes candle volume across overlapping rows and conserves selected volume', () => {
    const bars = [{ ...bar(0, 10, 40), low: 0, high: 40 }, { ...bar(60, 10, 30), low: 5, high: 15 }, bar(120, 35, 30), bar(180, 500, 500)];
    const result = fixedRangeVolumeProfileAnalysis(bars, 120, 0, { rows: 4, valueArea: 70 });
    expect(result.status).toBe('ready');
    expect(result.rows.map(row => row.volume)).toEqual([25, 25, 10, 40]);
    expect(result.totalVolume).toBe(100);
    expect(result.poc).toBe(35);
    expect(result.valueAreaLow).toBe(10);
    expect(result.valueAreaHigh).toBe(40);
  });
  it('bounds rows and supports flat prices and live revisions', () => {
    const bars = [bar(0, 10, 10), bar(60, 20, 30)];
    expect(fixedRangeVolumeProfileAnalysis(bars, 0, 60, { rows: 1e9 }).rows).toHaveLength(200);
    expect(fixedRangeVolumeProfileAnalysis(bars, 0, 60, { rows: -10 }).rows).toHaveLength(4);
    expect(fixedRangeVolumeProfileAnalysis([bar(0, 10, 7)], 0, 0).rows).toEqual([{ low: 10, high: 10, volume: 7, valueArea: true }]);
    bars[1].volume = 90;
    expect(fixedRangeVolumeProfileAnalysis(bars, 0, 60).totalVolume).toBe(100);
  });
  it('locates a selected window without scanning unrelated history', () => {
    let reads = 0;
    const bars = Array.from({ length: 100_000 }, (_, i) => ({ ...bar(i, 10, 1), get time() { reads++; return i; } }));
    expect(fixedRangeVolumeProfileAnalysis(bars, 99_989, 99_999).totalVolume).toBe(11);
    expect(reads).toBeLessThan(100);
    reads = 0;
    expect(anchoredVwapAnalysis(bars, 99_989).points).toHaveLength(11);
    expect(reads).toBeLessThan(100);
  });
  it('avoids multiplying histogram work by the row count', () => {
    let reads = 0;
    const bars = Array.from({ length: 10_000 }, (_, i) => ({ ...bar(i, 10, 1), get low() { reads++; return 0; }, get high() { reads++; return 100; } }));
    const result = fixedRangeVolumeProfileAnalysis(bars, 0, 9_999, { rows: 200 });
    expect(result.rows.map(row => row.volume).reduce((sum, v) => sum + v, 0)).toBeCloseTo(10_000, 6);
    expect(reads).toBeLessThan(100_000);
  });
  it('keeps negative, nonfinite and absent volume out of measurements', () => {
    const bars = [bar(0, 10, -1), bar(60, 20, NaN), bar(120, 30, Infinity), bar(180, 40, 2)];
    const vwap = anchoredVwapAnalysis(bars, 0);
    expect(vwap.missingVolumeBars).toBe(3);
    expect(vwap.points).toEqual([{ time: 180, value: 40, deviation: 0, breakBefore: true }]);
    const profile = fixedRangeVolumeProfileAnalysis(bars, 0, 180);
    expect(profile.missingVolumeBars).toBe(3);
    expect(profile.totalVolume).toBe(2);
    expect(profile.status).toBe('partial');
  });
  it('reports unusable price ranges and numeric overflow without nonfinite output', () => {
    const broken = [{ ...bar(0, 10, 5), low: 20, high: 10 }];
    expect(fixedRangeVolumeProfileAnalysis(broken, 0, 0).status).toBe('invalid-data');
    expect(anchoredVwapAnalysis([bar(0, NaN, 5)], 0).status).toBe('invalid-data');
    expect(fixedRangeVolumeProfileAnalysis([bar(0, 10, 1e308), bar(60, 20, 1e308)], 0, 60).status).toBe('invalid-data');
  });
  it('marks calculations partial until the requested start is covered by loaded history', () => {
    const bars = [bar(60, 20, 1), bar(120, 40, 1)];
    const vwap = anchoredVwapAnalysis(bars, 0);
    expect(vwap).toMatchObject({ status: 'partial', historyPartial: true, missingVolumeBars: 0 });
    expect(vwap.points[1].value).toBe(30);
    expect(fixedRangeVolumeProfileAnalysis(bars, 120, 0)).toMatchObject({ status: 'partial', historyPartial: true, totalVolume: 2 });
    bars.unshift(bar(0, 100, 100));
    const complete = anchoredVwapAnalysis(bars, 0);
    expect(complete).toMatchObject({ status: 'ready', historyPartial: false });
    expect(complete.points[2].value).toBeCloseTo(98.62745098039215);
    expect(fixedRangeVolumeProfileAnalysis(bars, 0, 120)).toMatchObject({ status: 'ready', historyPartial: false, totalVolume: 102 });
  });
  it.each([
    [1e12, 1e12 + 0.001, 100],
    [-1e12, -1e12 + 0.001, 100],
    [1, 1 + Number.EPSILON, 1e308],
  ])('uses representable rows and conserves volume over narrow prices %s..%s', (low, high, volume) => {
    const result = fixedRangeVolumeProfileAnalysis([{ ...bar(0, low, volume), low, high }], 0, 0, { rows: 200 });
    expect(result.status).toBe('ready');
    expect(result.rows.length).toBeGreaterThan(0);
    expect(result.rows.every(row => row.high > row.low && Number.isFinite(row.volume))).toBe(true);
    expect(result.rows.reduce((sum, row) => sum + row.volume / volume, 0)).toBeCloseTo(1, 12);
    expect(result.rows[0].low).toBe(low);
    expect(result.rows[result.rows.length - 1].high).toBe(high);
  });
});

describe('interactive analysis drawings', () => {
  it('registers tools with one and two time anchors', () => {
    expect(BUILTIN_DRAWING_TOOLS.find(t => t.id === 'anchored-vwap')?.points).toBe(1);
    expect(BUILTIN_DRAWING_TOOLS.find(t => t.id === 'fixed-range-volume-profile')?.points).toBe(2);
  });
  it('paints the weighted average in device pixels and hits its curve in media pixels', () => {
    const d = drawing('anchored-vwap', { showBands: false });
    const rc = context([bar(0, 10, 1), bar(60, 20, 3)], 2);
    const rec = paint(d, rc);
    expect(rec.ops.filter(o => o.type === 'lineTo').some(o => o.args[0] === 300 && o.args[1] === 450)).toBe(true);
    expect(getDrawingTool(d.tool).distance(150, 225, { drawing: d, rc, pts: [] })).toBe(0);
    expect(getDrawingTool(d.tool).distance(501, 225, { drawing: d, rc, pts: [] })).toBeNull();
  });
  it('recomputes the forming candle without relying on array identity', () => {
    const bars = [bar(0, 10, 1), bar(60, 20, 3)], rc = context(bars);
    const d = drawing('anchored-vwap', { showBands: false });
    const before = paint(d, rc);
    bars[1].close = bars[1].high = bars[1].low = 30;
    expect(texts(paint(d, rc))).not.toEqual(texts(before));
    expect(getDrawingTool(d.tool).distance(150, 150, { drawing: d, rc, pts: [] })).toBe(0);
  });
  it.each(['anchored-vwap', 'fixed-range-volume-profile'])('%s explains missing, zero and incomplete volume', id => {
    const d = drawing(id);
    expect(texts(paint(d, context([bar(0, 10)]))).join(' ')).toMatch(/volume unavailable/i);
    expect(texts(paint(d, context([bar(0, 10, 0)]))).join(' ')).toMatch(/zero volume/i);
    expect(texts(paint(d, context([bar(0, 10, 1), bar(60, 20)]))).join(' ')).toMatch(/partial volume/i);
  });
  it.each(['anchored-vwap', 'fixed-range-volume-profile'])('%s identifies incomplete history when numeric labels are disabled', id => {
    const d = drawing(id);
    d.style.showLabels = false;
    const label = texts(paint(d, context([bar(60, 20, 1), bar(120, 40, 1)]))).join(' ');
    expect(label).toContain('partial history');
    expect(label).not.toContain('partial volume');
  });
  it('paints a histogram with selectable volume bars and fresh last-bar volume', () => {
    const bars = [bar(0, 10, 10), bar(60, 20, 20), bar(120, 30, 30)], rc = context(bars);
    const d = drawing('fixed-range-volume-profile', { rows: 4 });
    const rec = paint(d, rc), rect = rec.ops.find(o => o.type === 'fillRect')!;
    expect(rect).toBeDefined();
    expect(getDrawingTool(d.tool).distance(rect.args[0] + rect.args[2] / 2, rect.args[1] + rect.args[3] / 2, { drawing: d, rc, pts: [] })).toBe(0);
    bars[2].volume = 300;
    expect(paint(d, rc).ops).not.toEqual(rec.ops);
  });
  it.each(['anchored-vwap', 'fixed-range-volume-profile'])('%s clips at the plot and rejects outside hits', id => {
    const d = drawing(id), rc = context([bar(0, 10, 10), bar(60, 100, 10), bar(120, 30, 30)], 2);
    const rec = paint(d, rc);
    expect(rec.ops.filter(o => o.type === 'rect').map(o => o.args)).toContainEqual([0, 0, 1000, 800]);
    expect(getDrawingTool(d.tool).distance(-1, 100, { drawing: d, rc, pts: [] })).toBeNull();
  });
  it.each(['anchored-vwap', 'fixed-range-volume-profile'])('%s keeps an unavailable analysis selectable', id => {
    const d = drawing(id), rc = context([bar(0, 10)]);
    const rec = paint(d, rc);
    expect(rec.ops.some(o => o.type === 'stroke')).toBe(true);
    expect(getDrawingTool(d.tool).distance(50, 280, { drawing: d, rc, pts: [] })).toBe(0);
  });
  it('exposes effective settings defaults and clamps imported numeric settings', () => {
    const avwap = drawing('anchored-vwap'), profile = drawing('fixed-range-volume-profile');
    const avSchema = getDrawingTool(avwap.tool).settings!, vpSchema = getDrawingTool(profile.tool).settings!;
    expect(readDrawingSettings(avwap, avSchema)).toMatchObject({ 'props.source': 'hlc3', 'props.showBands': true, 'props.bandMultiplier': 1 });
    expect(readDrawingSettings(profile, vpSchema)).toMatchObject({ 'props.rows': 48, 'props.valueArea': 70, 'props.width': 35 });
    expect(applyDrawingSettings(profile, { 'props.rows': '99999', 'props.valueArea': '-1' }, vpSchema).props).toMatchObject({ rows: 200, valueArea: 1 });
    profile.props = { rows: 1e9, width: 1e9, valueArea: NaN };
    expect(paint(profile, context([bar(0, 10, 1), bar(120, 30, 3)])).ops.every(op => op.args.every(Number.isFinite))).toBe(true);
  });
  it('zero band multiplier paints the same curve as disabling the bands', () => {
    const rc = context([bar(0, 10, 1), bar(60, 20, 3)]);
    const plain = paint(drawing('anchored-vwap', { showBands: false }), rc);
    const zero = paint(drawing('anchored-vwap', { bandMultiplier: 0 }), rc);
    expect(zero.ops.filter(op => op.type === 'lineTo')).toEqual(plain.ops.filter(op => op.type === 'lineTo'));
  });
  it.each(['anchored-vwap', 'fixed-range-volume-profile'])('%s retains timestamps and settings through drag, undo and JSON restore', id => {
    (globalThis as unknown as { window: object }).window ??= {};
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div') as unknown as HTMLElement, {
      document, raf: { schedule: cb => { cb(); return 0; } }, pixelRatio: () => 1, shortcuts: false,
    });
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    series.setData([bar(0, 10, 10), bar(60, 20, 30), bar(120, 30, 30)]);
    const controller = new DrawingController(chart), input = drawing(id, { source: 'close', rows: 24 });
    const added = controller.add(input);
    controller.select([added.id]);
    chart.emit('drag', { id: `draw:${added.id}#0`, time: 30, price: 15, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(controller.get(added.id)?.points[0].time).toBe(30);
    expect(controller.undo()).toBe(true);
    expect(controller.get(added.id)?.points[0].time).toBe(0);
    expect(controller.redo()).toBe(true);
    const saved = controller.toJSON();
    series.setData([bar(-60, 5, 5), bar(0, 10, 10), bar(60, 20, 30), bar(120, 30, 30)]);
    controller.fromJSON(saved);
    expect(controller.get(added.id)?.points[0].time).toBe(30);
    expect(controller.get(added.id)?.props).toEqual({ source: 'close', rows: 24 });
    controller.remove(added.id);
    expect(controller.get(added.id)).toBeUndefined();
    expect(controller.undo()).toBe(true);
    expect(controller.get(added.id)?.tool).toBe(id);
    controller.destroy(); chart.destroy();
  });
});
