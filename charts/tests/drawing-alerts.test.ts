import { afterEach, describe, expect, it, vi } from 'vitest';
import { AlertController, Chart, PriceLine, PriceScale, registerIndicator, TickSchedule } from '../src/index';
import { roundToTick } from '../src/helpers/math';
import { DrawingController, type DrawingInput } from '../src/draw/index';
import type { AlertSource, AlertControllerOptions, AlertTriggeredPayload, Bar, PrimitiveRenderContext } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';

const cleanup: (() => void)[] = [];
afterEach(() => { for (const destroy of cleanup.splice(0).reverse()) destroy(); });
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
const point = (time: number, price: number) => ({ time, price });

function setup(times = [60, 120, 180, 240, 300]) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  cleanup.push(() => chart.destroy());
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(times.map(time => bar(time, 100)));
  const draw = new DrawingController(chart);
  cleanup.push(() => draw.destroy());
  return { chart, series, draw };
}

function add(draw: DrawingController, input: Omit<DrawingInput, 'style' | 'paneIndex'> & Partial<Pick<DrawingInput, 'style' | 'paneIndex'>>) {
  return draw.add({ style: {}, paneIndex: 0, ...input });
}

describe('drawing alert values', () => {
  it('resolves a finite trend segment and returns no value beyond its endpoints', () => {
    const { draw } = setup();
    const drawing = add(draw, { tool: 'trend-line', points: [point(120, 100), point(240, 200)] });
    expect(draw.valueAt(drawing.id, 180)?.price).toBeCloseTo(150);
    expect(draw.valueAt(drawing.id, 120)?.price).toBeCloseTo(100);
    expect(draw.valueAt(drawing.id, 240)?.price).toBeCloseTo(200);
    expect(draw.valueAt(drawing.id, 60)).toBeUndefined();
    expect(draw.valueAt(drawing.id, 300)).toBeUndefined();
    expect(draw.alertInfo(drawing.id)).toMatchObject({ available: true, paneIndex: 0 });
  });

  it('uses logical spacing across a collapsed session gap', () => {
    const { draw, chart } = setup([60, 120, 90000]);
    const drawing = add(draw, { tool: 'trend-line', points: [point(60, 100), point(90000, 200)] });
    expect(draw.valueAt(drawing.id, 120)?.price).toBeCloseTo(150);
    chart.setVisibleLogicalRange({ from: -10, to: 10 });
    expect(draw.valueAt(drawing.id, 120)?.price).toBeCloseTo(150);
  });

  it('uses the same logarithmic projection as the drawn line', () => {
    const { draw, chart } = setup();
    chart.panes()[0].priceScale.setOptions({ mode: 'logarithmic' });
    const drawing = add(draw, { tool: 'trend-line', points: [point(120, 100), point(240, 400)] });
    const renderedMid = (chart.priceToCoordinate(100)! + chart.priceToCoordinate(400)!) / 2;
    const expected = chart.coordinateToPrice(renderedMid)!;
    expect(draw.valueAt(drawing.id, 180)?.price).toBeCloseTo(expected, 6);
    expect(expected).not.toBeCloseTo(250);
    chart.panes()[0].priceScale.setOptions({ inverted: true });
    expect(draw.valueAt(drawing.id, 180)?.price).toBeCloseTo(expected, 6);
  });

  it.each([
    ['ray', {}, 300, 250, 60],
    ['ray', { extendLeft: true, extendRight: false }, 60, 50, 300],
    ['extended-line', {}, 300, 250, undefined],
    ['extended-line', {}, 60, 50, undefined],
  ] as const)('honors %s extensions %j', (tool, style, time, value, absent) => {
    const { draw } = setup();
    const drawing = add(draw, { tool, style, points: [point(120, 100), point(240, 200)] });
    expect(draw.valueAt(drawing.id, time)?.price).toBeCloseTo(value);
    if (absent !== undefined) expect(draw.valueAt(drawing.id, absent)).toBeUndefined();
  });

  it('keeps reversed anchors and explicit extensions consistent with the rendered segment', () => {
    const { draw } = setup();
    const drawing = add(draw, { tool: 'trend-line', points: [point(240, 200), point(120, 100)] });
    expect(draw.valueAt(drawing.id, 180)?.price).toBeCloseTo(150);
    draw.update(drawing.id, { style: { extendLeft: true } });
    expect(draw.valueAt(drawing.id, 60)?.price).toBeCloseTo(50);
    expect(draw.valueAt(drawing.id, 180)).toBeUndefined();
  });

  it('resolves horizontal levels and the finite start of a horizontal ray', () => {
    const { draw } = setup();
    const line = add(draw, { tool: 'horizontal-line', points: [point(180, 0)] });
    const ray = add(draw, { tool: 'horizontal-ray', points: [point(180, 105)] });
    expect(draw.valueAt(line.id, 60)?.price).toBe(0);
    expect(draw.valueAt(ray.id, 120)).toBeUndefined();
    expect(draw.valueAt(ray.id, 240)?.price).toBe(105);
  });

  it('resolves both channel boundaries, the middle and a sorted band', () => {
    const { draw } = setup();
    const drawing = add(draw, { tool: 'parallel-channel', points: [point(120, 100), point(240, 120), point(180, 130)] });
    expect(draw.valueAt(drawing.id, 180)).toMatchObject({ price: 110, upperPrice: 130, paneIndex: 0 });
    expect(draw.valueAt(drawing.id, 180, 'base')?.price).toBeCloseTo(110);
    expect(draw.valueAt(drawing.id, 180, 'boundary')?.price).toBeCloseTo(130);
    expect(draw.valueAt(drawing.id, 180, 'middle')?.price).toBeCloseTo(120);
    expect(draw.valueAt(drawing.id, 300)).toBeUndefined();
    draw.update(drawing.id, { points: [point(120, 100), point(240, 120), point(180, 90)] });
    const band = draw.valueAt(drawing.id, 180)!;
    expect(band.price).toBeCloseTo(90);
    expect(band.upperPrice).toBeCloseTo(110);
  });

  it.each([
    ['disjoint-channel', [point(120, 100), point(240, 120), point(120, 90), point(240, 100)], 95, 110],
    ['flat-top-bottom', [point(120, 100), point(240, 120), point(180, 90)], 90, 110],
  ] as const)('resolves %s against its actual boundaries', (tool, points, lower, upper) => {
    const { draw } = setup();
    const drawing = add(draw, { tool, points: [...points] });
    const value = draw.valueAt(drawing.id, 180)!;
    expect(value.price).toBeCloseTo(lower);
    expect(value.upperPrice).toBeCloseTo(upper);
  });

  it('uses screen-edge extension for reversed advanced channel anchors', () => {
    const { draw } = setup();
    const drawing = add(draw, { tool: 'disjoint-channel', style: { extendLeft: true },
      points: [point(240, 120), point(120, 100), point(240, 100), point(120, 90)] });
    const value = draw.valueAt(drawing.id, 180)!;
    expect(value.price).toBeCloseTo(95);
    expect(value.upperPrice).toBeCloseTo(110);
    expect(draw.valueAt(drawing.id, 60)).toBeDefined();
    expect(draw.valueAt(drawing.id, 300)).toBeUndefined();
  });

  it.each([
    ['fib-retracement', [point(120, 100), point(240, 200)], 150],
    ['fib-extension', [point(120, 100), point(180, 200), point(240, 120)], 170],
    ['fib-extension-two-point', [point(120, 100), point(240, 200)], 150],
  ] as const)('requires a specific active rung for %s', (tool, points, value) => {
    const { draw, chart } = setup();
    const drawing = add(draw, { tool, points: [...points], style: { levels: [{ ratio: 0.5, label: 'Half' }, { ratio: 0.8, enabled: false }] } });
    expect(draw.valueAt(drawing.id, 180)).toBeUndefined();
    expect(draw.alertInfo(drawing.id).levels).toEqual([{ id: 'ratio:0.5', title: 'Half' }]);
    expect(draw.valueAt(drawing.id, 180, 'ratio:0.5')?.price).toBe(value);
    expect(draw.valueAt(drawing.id, 180, 'ratio:0.8')).toBeUndefined();
    expect(draw.valueAt(drawing.id, 300, 'ratio:0.5')).toBeUndefined();
    draw.update(drawing.id, { style: { extendRight: true } });
    chart.panes()[0].priceScale.setOptions({ mode: 'logarithmic' });
    expect(draw.valueAt(drawing.id, 300, 'ratio:0.5')?.price).toBe(value);
  });

  it('uses the actual shifted anchors of each fib channel rung', () => {
    const { draw } = setup();
    const drawing = add(draw, { tool: 'fib-channel', points: [point(120, 100), point(240, 120), point(300, 160)],
      style: { levels: [{ ratio: 0.5 }] } });
    expect(draw.valueAt(drawing.id, 120, 'ratio:0.5')).toBeUndefined();
    expect(draw.valueAt(drawing.id, 180, 'ratio:0.5')?.price).toBeCloseTo(125);
  });

  it('reports unsupported tools and degenerate geometry without inventing a level', () => {
    const { draw } = setup();
    const shape = add(draw, { tool: 'ellipse', points: [point(120, 100), point(240, 200)] });
    const vertical = add(draw, { tool: 'trend-line', points: [point(120, 100), point(120, 200)] });
    expect(draw.alertInfo(shape.id)).toMatchObject({ available: false, reason: expect.stringMatching(/numeric|value/i) });
    expect(draw.valueAt(shape.id, 180)).toBeUndefined();
    expect(draw.valueAt(vertical.id, 120)).toBeUndefined();
    expect(draw.alertInfo('missing')).toMatchObject({ available: false, reason: expect.stringMatching(/missing|unavailable/i) });
  });
});

function alertSetup(times?: number[], options: AlertControllerOptions = {}) {
  const rig = setup(times);
  const alerts = new AlertController(rig.chart, { drawings: rig.draw, ...options });
  cleanup.push(() => alerts.destroy());
  const fired: AlertTriggeredPayload[] = [];
  rig.chart.on('alert:triggered', event => fired.push(event as AlertTriggeredPayload));
  return { ...rig, alerts, fired };
}

describe('drawing alert evaluation and lifecycle', () => {
  it('follows a moved level, using fresh market observations after the edit', () => {
    const { draw, series, alerts, fired } = alertSetup([60, 120]);
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 110)] });
    alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, condition: 'crossingUp', policy: 'onTouch' });
    draw.update(drawing.id, { points: [point(120, 105)] });
    series.update({ ...bar(120, 100), high: 104 });
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 100), high: 106 });
    expect(fired.map(event => event.price)).toEqual([105]);
  });

  it('compares each closed bar with the line value at that bar, rather than one fixed threshold', () => {
    const { draw, series, alerts, fired } = alertSetup([60, 120]);
    const drawing = add(draw, { tool: 'extended-line', points: [point(60, 105), point(120, 95)] });
    alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, condition: 'crossingUp' });
    series.update(bar(180, 100));
    expect(fired).toHaveLength(1);
    expect(fired[0]).toMatchObject({ time: 120, price: 100 });
  });

  it('distinguishes a touched drawing from an unconfirmed erased wick', () => {
    const { draw, series, alerts, fired } = alertSetup([60, 120]);
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 105)] });
    const close = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, condition: 'crossingUp' });
    const touch = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, condition: 'crossingUp', policy: 'onTouch' });
    series.update({ ...bar(120, 100), high: 106 });
    series.update(bar(120, 100));
    series.update(bar(180, 100));
    expect(fired.map(event => event.alertId)).toEqual([touch.id]);
    expect(alerts.list().find(item => item.id === close.id)?.state).toBe('armed');
  });

  it('evaluates entering and leaving a channel band with moving boundaries', () => {
    const { draw, series, alerts, fired } = alertSetup([60, 120]);
    const drawing = add(draw, { tool: 'parallel-channel', points: [point(60, 105), point(180, 105), point(120, 115)] });
    alerts.add({ source: { kind: 'drawing', drawingId: drawing.id, level: 'band' }, condition: 'enteringRange' });
    series.update(bar(120, 110));
    series.update(bar(180, 120));
    expect(fired.map(event => event.time)).toEqual([120]);
    alerts.add({ source: { kind: 'drawing', drawingId: drawing.id, level: 'band' }, condition: 'leavingRange' });
    series.update(bar(240, 120));
    expect(fired.map(event => event.time)).toEqual([120, 180]);
  });

  it.each(['remove', 'undo', 'replace'] as const)('removes anchored alerts when drawings disappear through %s', method => {
    const { chart, draw, alerts } = alertSetup();
    const removed: unknown[] = [];
    chart.on('alert:removed', value => removed.push(value));
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 105)] });
    const alert = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id } });
    if (method === 'remove') draw.remove(drawing.id);
    if (method === 'undo') draw.undo();
    if (method === 'replace') draw.fromJSON({ version: 2, drawings: [] });
    expect(alerts.list()).toEqual([]);
    expect(removed).toHaveLength(1);
    expect(removed[0]).toMatchObject({ alert: { id: alert.id }, reason: 'drawing-removed' });
    if (method === 'undo') { draw.redo(); expect(alerts.list()).toEqual([]); }
  });

  it('keeps a drawing alert while its instrument, and so its drawing, is off the chart', () => {
    const { chart, draw, alerts, series, fired } = alertSetup([60, 120]);
    const removed: unknown[] = [];
    chart.on('alert:removed', value => removed.push(value));
    chart.setDataContext({ symbol: 'AAA', exchange: 'NSE', interval: '1m' });
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 105)] });
    const alert = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, condition: 'crossingUp', policy: 'onTouch' });
    const saved = draw.toJSON();
    // Another instrument's drawings replace this one's, the way a host keeping
    // drawings per instrument swaps them, and one of them reuses the id.
    chart.setDataContext({ symbol: 'BBB', exchange: 'NSE', interval: '1m' });
    draw.fromJSON({ version: 2, drawings: [{ ...saved.drawings[0], points: [point(120, 95)] }] });
    draw.fromJSON({ version: 2, drawings: [] });
    expect(removed).toEqual([]);
    expect(alerts.availability(alert.id)).toMatchObject({ available: false, reason: 'Instrument context differs' });
    // Restored while another instrument is on the chart, it is kept too.
    alerts.fromJSON(alerts.toJSON());
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
    chart.setDataContext({ symbol: 'AAA', exchange: 'NSE', interval: '1m' });
    draw.fromJSON(saved);
    series.setData([bar(60, 100), bar(120, 100)]);
    series.update({ ...bar(120, 100), high: 106 });
    expect(fired.map(event => event.alertId)).toEqual([alert.id]);
    // On its own instrument a missing drawing still takes the alert with it.
    draw.remove(drawing.id);
    expect(removed).toHaveLength(1);
  });

  it('does not compare a non-price drawing against the primary price', () => {
    registerIndicator({ id: 'drawing-alert-reading', name: 'Reading', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'Value', type: 'line' }], calc: bars => ({ v: bars.map(item => item.volume ?? null) }) });
    const { chart, draw, series, alerts, fired } = alertSetup([60, 120]);
    series.setData([{ ...bar(60, 100), volume: 20 }, { ...bar(120, 100), volume: 20 }]);
    const study = chart.addIndicator('drawing-alert-reading');
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 25)], paneIndex: study.paneIndex });
    const missing = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id }, policy: 'onTouch', condition: 'greaterThan' });
    expect(alerts.availability(missing.id)).toMatchObject({ available: false, reason: expect.stringMatching(/input|plot/i) });
    const alert = alerts.add({ source: { kind: 'drawing', drawingId: drawing.id, input: { instanceId: study.id, plotKey: 'v' } },
      policy: 'onTouch', condition: 'crossingUp' });
    series.update({ ...bar(120, 200), volume: 20 });
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 200), volume: 30 });
    expect(fired.map(event => event.alertId)).toEqual([alert.id]);
    expect(fired[0].price).toBe(30);
  });

  it('keeps reading and firing a drawing on a pane folded to a strip', () => {
    registerIndicator({ id: 'drawing-alert-strip', name: 'Strip reading', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'Value', type: 'line' }], calc: bars => ({ v: bars.map(item => item.volume ?? null) }) });
    const { chart, draw, series, alerts, fired } = alertSetup([60, 120, 180]);
    series.setData([60, 120, 180].map(time => ({ ...bar(time, 100), volume: 20 })));
    const study = chart.addIndicator('drawing-alert-strip');
    const pane = study.paneIndex;
    const trend = add(draw, { tool: 'trend-line', points: [point(60, 10), point(180, 40)], paneIndex: pane });
    chart.panes()[pane].priceScale.setOptions({ mode: 'logarithmic' });
    const open = draw.valueAt(trend.id, 120)?.price;
    // Halfway along in log space: the geometric mean, not the linear 25.
    expect(open).toBeCloseTo(20, 6);
    // The chart maps no price on a strip, yet the level is the one drawn on the
    // open pane, logarithmic projection included.
    expect(chart.setPaneCollapsed(pane, true)).toBe(true);
    expect(chart.priceToCoordinate(10, pane)).toBeNull();
    expect(draw.valueAt(trend.id, 120)?.price).toBeCloseTo(open!, 6);

    const level = add(draw, { tool: 'horizontal-line', points: [point(120, 25)], paneIndex: pane });
    const alert = alerts.add({ source: { kind: 'drawing', drawingId: level.id, input: { instanceId: study.id, plotKey: 'v' } },
      policy: 'onTouch', condition: 'crossingUp' });
    series.update({ ...bar(180, 100), volume: 30 });
    expect(fired.map(event => event.alertId)).toEqual([alert.id]);
    expect(chart.paneCollapsed(pane)).toBe(true);
  });

  it('reports unsupported tools and missing selected rungs as unavailable', () => {
    const { draw, alerts, series, fired } = alertSetup([60, 120]);
    const shape = add(draw, { tool: 'ellipse', points: [point(60, 90), point(120, 110)] });
    const shapeAlert = alerts.add({ source: { kind: 'drawing', drawingId: shape.id } });
    expect(alerts.availability(shapeAlert.id).available).toBe(false);
    const fib = add(draw, { tool: 'fib-retracement', points: [point(60, 100), point(120, 120)], style: { extendRight: true } });
    const alert = alerts.add({ source: { kind: 'drawing', drawingId: fib.id, level: 'ratio:0.5' }, condition: 'crossingUp', policy: 'onTouch' });
    draw.update(fib.id, { style: { levels: [{ ratio: 0.5, enabled: false }] } });
    expect(alerts.availability(alert.id).available).toBe(false);
    series.update(bar(120, 130));
    expect(fired).toEqual([]);
  });
});

describe('alert line visuals', () => {
  it('uses PriceLine and visibly distinguishes every lifecycle state', () => {
    const { chart, alerts, series } = alertSetup([60, 120]);
    const attach = vi.spyOn(chart, 'addPrimitive');
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout', policy: 'onTouch', condition: 'crossingUp' });
    const line = attach.mock.calls.map(([primitive]) => primitive).find(primitive => primitive instanceof PriceLine) as PriceLine;
    expect(line).toBeInstanceOf(PriceLine);
    const colors = [line.options().color];
    // The ordinary state says what the line IS, not which state it is in:
    // "Armed" on a chart is the engine's word for the state every alert is in
    // almost all the time, and it reads as jargon. The other three stay,
    // because each tells you something the line cannot show on its own.
    expect(line.options().badge).toBe('Alert');
    series.update({ ...bar(120, 100), high: 106 });
    colors.push(line.options().color);
    expect(line.options().badge?.toLowerCase()).toContain('triggered');
    alerts.disable(alert.id);
    colors.push(line.options().color);
    expect(line.options().badge?.toLowerCase()).toContain('disabled');
    alerts.update(alert.id, { state: 'armed', expiresAt: 1 });
    colors.push(line.options().color);
    expect(line.options().badge?.toLowerCase()).toContain('expired');
    expect(new Set(colors).size).toBe(4);
    expect(chart.exportSVG()).toContain('Breakout');
  });

  it('moves a drawing level in place and removes its visual with its alert', () => {
    const { chart, draw, alerts } = alertSetup();
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 105)] });
    const attach = vi.spyOn(chart, 'addPrimitive');
    const detach = vi.spyOn(chart, 'removePrimitive');
    alerts.add({ source: { kind: 'drawing', drawingId: drawing.id } });
    const lines = attach.mock.calls.map(([primitive]) => primitive).filter(primitive => primitive instanceof PriceLine) as PriceLine[];
    expect(lines).toHaveLength(1);
    draw.update(drawing.id, { points: [point(120, 115)] });
    expect(lines[0].price).toBe(115);
    expect(attach.mock.calls.filter(([primitive]) => primitive instanceof PriceLine)).toHaveLength(1);
    draw.remove(drawing.id);
    expect(detach).toHaveBeenCalledWith(lines[0]);
  });

  it('hides an instrument level during a context mismatch and cleans it on destroy', () => {
    const { chart, alerts } = alertSetup();
    chart.setDataContext({ symbol: 'ONE' });
    alerts.add({ source: { kind: 'price', price: 105 }, title: 'Owned level' });
    expect(chart.exportSVG()).toContain('Owned level');
    chart.setDataContext({ symbol: 'TWO' });
    expect(chart.exportSVG()).not.toContain('Owned level');
    chart.setDataContext({ symbol: 'ONE' });
    expect(chart.exportSVG()).toContain('Owned level');
    alerts.destroy();
    expect(chart.exportSVG()).not.toContain('Owned level');
  });
});

describe('moving an alert by dragging its line', () => {
  const event = (chart: Chart, type: string, id: string, price: number, extra = {}) =>
    chart.emit(type, { id, price, ...extra });
  const lineFor = (chart: Chart, id: string, index = 0): PriceLine => chart.panes()
    .flatMap(pane => [...pane.primitives()]).find(item => item instanceof PriceLine && item.options().id === `alert:${id}:${index}`) as PriceLine;
  const renderContext = (priceScale: PriceScale, readoutPriceScale?: PriceScale): PrimitiveRenderContext => ({
    priceScale, readoutPriceScale, timeScale: new TimeScale(), dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
  });
  const begin = (chart: Chart, id: string, price: number, index = 0) => event(chart, 'drag:start', `alert:${id}:${index}`, price);
  const move = (chart: Chart, id: string, price: number, index = 0) => event(chart, 'drag', `alert:${id}:${index}`, price);
  const end = (chart: Chart, id: string, price: number, index = 0) => event(chart, 'drag:end', `alert:${id}:${index}`, price);
  let studyId = 0;
  function study(chart: Chart) {
    const id = `alert-drag-study-${++studyId}`;
    registerIndicator({ id, name: 'Reading', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'Reading', type: 'line' }], calc: bars => ({ v: bars.map(() => 30) }) });
    return chart.addIndicator(id);
  }

  it('previews only the visual, keeps evaluation and persistence unchanged, and commits once', () => {
    const { chart, alerts, series, fired } = alertSetup([60, 120]);
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, condition: 'greaterThan', policy: 'onTouch' });
    const updated = vi.fn(); chart.on('alert:updated', updated);
    begin(chart, alert.id, 105);
    move(chart, alert.id, 95);
    expect(lineFor(chart, alert.id).price).toBe(95);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
    expect(chart.getState().alerts?.alerts[0].source).toEqual({ kind: 'price', price: 105 });
    expect(updated).not.toHaveBeenCalled();
    expect(lineFor(chart, alert.id).autoscaleInfo()).toEqual({ min: 105, max: 105 });
    series.update(bar(120, 101));
    expect(fired).toHaveLength(0);
    end(chart, alert.id, 110);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 110 });
    expect(updated).toHaveBeenCalledTimes(1);
    end(chart, alert.id, 115);
    expect(updated).toHaveBeenCalledTimes(1);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 110 });
  });

  it('does not commit a click near the line or an unowned release', () => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    const updated = vi.fn(); chart.on('alert:updated', updated);
    end(chart, alert.id, 200);
    begin(chart, alert.id, 104);
    end(chart, alert.id, 104);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
    expect(lineFor(chart, alert.id).price).toBe(105);
    expect(updated).not.toHaveBeenCalled();
  });

  it('reverts a cancelled preview and ignores the old release', () => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    begin(chart, alert.id, 105); move(chart, alert.id, 110);
    chart.emit('drag:cancel', { id: `alert:${alert.id}:0`, reason: 'pointercancel' });
    expect(lineFor(chart, alert.id).price).toBe(105);
    end(chart, alert.id, 115);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
  });

  it.each([0, 1])('clamps range bound %s without moving the other bound', index => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 100, upperPrice: 120 }, condition: 'enteringRange' });
    begin(chart, alert.id, index ? 120 : 100, index);
    move(chart, alert.id, index ? 90 : 130, index);
    expect(lineFor(chart, alert.id, index).price).toBe(index ? 100 : 120);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 100, upperPrice: 120 });
    end(chart, alert.id, index ? 90 : 130, index);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: index ? 100 : 120, upperPrice: index ? 100 : 120 });
  });

  it.each([-1, 1, 2, 99])('ignores nonexistent single-line bound %s', index => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    begin(chart, alert.id, 105, index); move(chart, alert.id, 115, index); end(chart, alert.id, 115, index);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
  });

  it.each(['pause', 'replay', 'context', 'restoring', 'reset'] as const)('cancels ownership on %s', guard => {
    const { chart, alerts, series } = alertSetup();
    chart.setDataContext({ symbol: 'ONE' });
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    begin(chart, alert.id, 105); move(chart, alert.id, 110);
    if (guard === 'pause') alerts.setPaused(true);
    if (guard === 'replay') chart.emit('replay:start', {});
    if (guard === 'context') chart.setDataContext({ symbol: 'TWO' });
    if (guard === 'restoring') chart.emit('state:restore:start', {});
    if (guard === 'reset') series.setData([bar(60, 100), bar(120, 100)]);
    end(chart, alert.id, 115);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
  });

  it.each(['update', 'restore', 'replace'] as const)('cannot overwrite a newer %s with a stale release', replace => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    begin(chart, alert.id, 105); move(chart, alert.id, 110);
    if (replace === 'update') alerts.update(alert.id, { source: { kind: 'price', price: 200 } });
    if (replace === 'restore') {
      const document = alerts.toJSON(); document.alerts[0].source = { kind: 'price', price: 200 }; alerts.fromJSON(document);
    }
    if (replace === 'replace') { alerts.remove(alert.id); alerts.add({ id: alert.id, source: { kind: 'price', price: 200 } }); }
    end(chart, alert.id, 115);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 200 });
  });

  it('cancels when a study source is removed', () => {
    const { chart, alerts } = alertSetup();
    const instance = study(chart);
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: instance.id, plotKey: 'v', value: 30 } });
    begin(chart, alert.id, 30); move(chart, alert.id, 40);
    chart.removeIndicator(instance.id);
    end(chart, alert.id, 50);
    expect(alerts.list()[0].source).toMatchObject({ value: 30 });
  });

  it.each(['trigger', 'expiry', 'disable'] as const)('cancels a preview after lifecycle change %s', action => {
    let now = 1000;
    const { chart, alerts, series } = alertSetup([60, 120], { now: () => now });
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, policy: 'onTouch', expiresAt: 1001 });
    begin(chart, alert.id, 105); move(chart, alert.id, 110);
    if (action === 'trigger') series.update({ ...bar(120, 100), high: 106 });
    if (action === 'expiry') { now = 1002; series.update(bar(120, 100)); }
    if (action === 'disable') alerts.disable(alert.id);
    end(chart, alert.id, 115);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
    expect(alerts.list()[0].state).toBe(action === 'trigger' ? 'triggered' : action === 'expiry' ? 'expired' : 'disabled');
    expect(lineFor(chart, alert.id).price).toBe(105);
  });

  it.each([false, true])('updates hit testing when pause changes (initial: %s)', paused => {
    const { chart, alerts } = alertSetup();
    alerts.setPaused(paused);
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    const line = lineFor(chart, alert.id);
    const scale = new PriceScale(); scale.setHeight(400); scale.setPriceRange({ min: 90, max: 120 });
    const rc = renderContext(scale);
    expect(Boolean(line.hitTest(400, scale.priceToY(105), rc))).toBe(!paused);
    alerts.setPaused(!paused);
    const hit = line.hitTest(400, scale.priceToY(105), rc);
    expect(Boolean(hit)).toBe(paused);
    expect(line.options().cursor).toBe(paused ? 'ns-resize' : undefined);
    if (hit) expect(hit.draggable).toBe(true);
  });

  it.each(['triggered', 'expired', 'disabled'] as const)('does not grab or edit an alert in state %s', state => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    const document = alerts.toJSON(); document.alerts[0].state = state; alerts.fromJSON(document);
    const scale = new PriceScale(); scale.setHeight(400); scale.setPriceRange({ min: 90, max: 120 });
    const line = lineFor(chart, alert.id);
    expect(line.hitTest(400, scale.priceToY(105), renderContext(scale))).toBeNull();
    expect(line.options().cursor).toBeUndefined();
    begin(chart, alert.id, 105); move(chart, alert.id, 115); end(chart, alert.id, 115);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
    alerts.enable(alert.id);
    expect(line.hitTest(400, scale.priceToY(105), renderContext(scale))?.draggable).toBe(true);
  });

  it('updates hit testing when a price alert becomes drawing-owned and back', () => {
    const { chart, draw, alerts } = alertSetup();
    const drawing = add(draw, { tool: 'horizontal-line', points: [point(120, 105)] });
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    const line = lineFor(chart, alert.id);
    const scale = new PriceScale(); scale.setHeight(400); scale.setPriceRange({ min: 90, max: 120 });
    const rc = renderContext(scale);
    alerts.update(alert.id, { source: { kind: 'drawing', drawingId: drawing.id } });
    expect(line.hitTest(400, scale.priceToY(105), rc)).toBeNull();
    expect(line.options().cursor).toBeUndefined();
    alerts.update(alert.id, { source: { kind: 'price', price: 105 } });
    expect(line.hitTest(400, scale.priceToY(105), rc)?.draggable).toBe(true);
  });

  it('draws, hit-tests and converts a primary alert on the primary readout scale', () => {
    const { chart, alerts, series } = alertSetup();
    chart.movePriceAxis(0, 'right', 'left');
    const scale = series.priceScale(); scale.setHeight(400); scale.setPriceRange({ min: 90, max: 130 });
    const wrong = new PriceScale(); wrong.setHeight(400); wrong.setPriceRange({ min: 0, max: 10 });
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    const line = lineFor(chart, alert.id), rc = renderContext(wrong, scale), paint = makeCtx();
    line.draw(paint.ctx, rc);
    expect(paint.rec.ops.find(op => op.type === 'moveTo')?.args[1]).toBe(Math.round(scale.priceToY(105)) + 0.5);
    expect(paint.rec.ops.filter(op => op.type === 'rect').some(op => op.args.join(',') === '0,0,600,400')).toBe(true);
    expect(line.autoscaleInfo()).toBeNull();
    expect(line.hitTest(400, scale.priceToY(105), rc)?.draggable).toBe(true);
    const id = `alert:${alert.id}:0`;
    event(chart, 'drag:start', id, 1, { point: { x: 400, y: scale.priceToY(105) }, paneIndex: 0 });
    event(chart, 'drag', id, 2, { point: { x: 400, y: scale.priceToY(115) }, paneIndex: 0 });
    event(chart, 'drag:end', id, 2, { point: { x: 400, y: scale.priceToY(115) }, paneIndex: 0 });
    expect(alerts.list()[0].source).toMatchObject({ price: 115 });
  });

  it('draws and converts a study threshold through its series scale, not the pane right scale', () => {
    const { chart, alerts } = alertSetup();
    const instance = study(chart), scale = instance.series('v')!.priceScale();
    scale.setHeight(400); scale.setPriceRange({ min: 0, max: 100 });
    const wrong = new PriceScale(); wrong.setHeight(400); wrong.setPriceRange({ min: 1000, max: 2000 });
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: instance.id, plotKey: 'v', value: 30 } });
    const line = lineFor(chart, alert.id), rc = renderContext(wrong), paint = makeCtx();
    line.draw(paint.ctx, rc);
    expect(paint.rec.ops.find(op => op.type === 'moveTo')?.args[1]).toBe(Math.round(scale.priceToY(30)) + 0.5);
    expect(line.hitTest(400, scale.priceToY(30), rc)?.draggable).toBe(true);
    const id = `alert:${alert.id}:0`;
    event(chart, 'drag:start', id, 1500, { point: { x: 400, y: scale.priceToY(30) }, paneIndex: instance.paneIndex });
    event(chart, 'drag:end', id, 1800, { point: { x: 400, y: scale.priceToY(70) }, paneIndex: instance.paneIndex });
    expect(alerts.list()[0].source).toMatchObject({ value: 70 });
  });

  it('never autoscales the right axis from an independent study, including its first frame', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} },
    });
    cleanup.push(() => chart.destroy());
    chart.applySize(800, 600);
    const series = chart.addSeries('candlestick');
    series.setData([60, 120, 180].map(time => bar(time, 100)));
    const id = `alert-drag-independent-${++studyId}`;
    registerIndicator({ id, name: 'Independent', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', title: 'Reading', type: 'line', priceScaleId: 'overlay:large' }],
      calc: bars => ({ v: bars.map(() => 1e6) }) });
    const instance = chart.addIndicator(id);
    chart.exportSVG();
    const before = series.priceScale().priceRange();
    const alerts = new AlertController(chart);
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: instance.id, plotKey: 'v', value: 1e6 } });
    chart.exportSVG();
    expect(series.priceScale().priceRange()).toEqual(before);
    expect(lineFor(chart, alert.id).autoscaleInfo()).toBeNull();
    alerts.remove(alert.id);
    alerts.add({ source: { kind: 'price', price: 150 } });
    chart.exportSVG();
    expect(series.priceScale().priceRange().max).toBeGreaterThanOrEqual(150);
  });

  it.each(['price', 'indicator'] as const)('snaps the %s source scale in preview and commit', kind => {
    const { chart, alerts, series } = alertSetup();
    let scale = series.priceScale();
    let source: AlertSource = { kind: 'price', price: 105 };
    if (kind === 'price') {
      chart.movePriceAxis(0, 'right', 'left');
    } else {
      const id = `tick-overlay-${++studyId}`;
      registerIndicator({ id, name: 'Tick reading', placement: 'onchart', inputs: [],
        plots: [{ key: 'v', title: 'Reading', type: 'line', priceScaleId: 'overlay:tick' }],
        calc: bars => ({ v: bars.map(() => 100) }) });
      const instance = chart.addIndicator(id);
      scale = instance.series('v')!.priceScale();
      source = { kind: 'indicator', instanceId: instance.id, plotKey: 'v', value: 105 };
    }
    chart.panes()[0].priceScale.setOptions({ minMove: 0.01 });
    scale.setOptions({ minMove: 0.25 });
    const alert = alerts.add({ source });
    scale.setHeight(400); scale.setPriceRange({ min: 90, max: 120 });
    const line = lineFor(chart, alert.id);
    line.draw(makeCtx().ctx, renderContext(chart.panes()[0].priceScale, series.priceScale()));
    const id = `alert:${alert.id}:0`;
    const at = (price: number) => ({ point: { y: scale.priceToY(price) }, paneIndex: 0 });
    event(chart, 'drag:start', id, 999, at(105));
    event(chart, 'drag', id, 999, at(106.13));
    expect(line.price).toBe(106.25);
    expect(alerts.list()[0].source).toEqual(source);
    event(chart, 'drag:end', id, 999, at(106.13));
    expect(alerts.list()[0].source).toMatchObject(kind === 'price' ? { price: 106.25 } : { value: 106.25 });
  });

  it.each([0, 1])('keeps snapped range bound %s within an off-tick opposite bound', index => {
    const { chart, alerts } = alertSetup();
    chart.panes()[0].priceScale.setOptions({ minMove: 0.25 });
    const alert = alerts.add({ source: { kind: 'price', price: 100.13, upperPrice: 105.13 }, condition: 'enteringRange' });
    begin(chart, alert.id, index === 0 ? 100.13 : 105.13, index);
    move(chart, alert.id, index === 0 ? 110 : 90, index);
    expect(lineFor(chart, alert.id, index).price).toBe(index === 0 ? 105 : 100.25);
    end(chart, alert.id, index === 0 ? 110 : 90, index);
    expect(alerts.list()[0].source).toMatchObject(index === 0 ? { price: 105, upperPrice: 105.13 } : { price: 100.13, upperPrice: 100.25 });
  });

  it.each([0, 1])('can meet an opposite decimal tick from bound %s', index => {
    const { chart, alerts } = alertSetup();
    chart.panes()[0].priceScale.setOptions({ minMove: 0.05 });
    const alert = alerts.add({ source: { kind: 'price', price: 100.1, upperPrice: 110.1 }, condition: 'enteringRange' });
    begin(chart, alert.id, index === 0 ? 100.1 : 110.1, index);
    end(chart, alert.id, index === 0 ? 120 : 90, index);
    expect(alerts.list()[0].source).toMatchObject(index === 0 ? { price: 110.1 } : { upperPrice: 100.1 });
  });

  it.each([[105.13, 100], [105.12, 105]])('keeps callback-only snapping inside range %s', (bound, expected) => {
    const { chart } = setup();
    chart.panes()[0].priceScale.setOptions({ minMove: 0.25 });
    const host = {
      primaryBars: () => chart.primaryBars(), getDataContext: () => chart.getDataContext(),
      on: chart.on.bind(chart), emit: chart.emit.bind(chart), snapPrice: chart.snapPrice.bind(chart),
    };
    const alerts = new AlertController(host, { visuals: false });
    cleanup.push(() => alerts.destroy());
    const alert = alerts.add({ source: { kind: 'price', price: 100, upperPrice: bound }, condition: 'enteringRange' });
    begin(chart, alert.id, 100); end(chart, alert.id, 110);
    expect(alerts.list()[0].source).toMatchObject({ price: expected, upperPrice: bound });
  });

  it('rejects an invalid release without retaining its preview', () => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    begin(chart, alert.id, 105); move(chart, alert.id, 110); end(chart, alert.id, Number.NaN);
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 105 });
    expect(lineFor(chart, alert.id).price).toBe(105);
  });
});

describe('a dragged alert lands on the instrument tick', () => {
  /**
   * Reported from a live chart: an alert dropped where the axis read 1255.90
   * was stored as 1255.8706204379562. A pointer's pixel maps to a price with a
   * dozen decimals behind it, so the line, the editor and the axis each showed
   * a different number for one alert, and the stored one was a price the
   * instrument cannot trade at.
   */
  const dragTo = (
    chart: { emit(name: string, payload: unknown): void },
    id: string,
    price: number,
    from = 100
  ) => {
    // The gesture starts where the line is. Starting it at the destination
    // means nothing moved, and a gesture that did not move commits nothing,
    // which is 2.4.7's own rule and would make every case below pass vacuously.
    chart.emit('drag:start', { id, price: from, paneIndex: 0 });
    // No `point`: with one, the controller converts the y coordinate through
    // the scale and the price passed here is ignored, which is right for a
    // real gesture and useless for stating the price a test is about.
    chart.emit('drag', { id, price, paneIndex: 0 });
    chart.emit('drag:end', { id, price, paneIndex: 0 });
  };

  it('rounds to the tick the pane axis is written with', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0.05 });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, title: 'T' });
    dragTo(chart, `alert:${alert.id}:0`, 105.8706204379562);
    const stored = alerts.list()[0].source as { price: number };
    // 105.8706... is between ticks. 105.85 and 105.90 are not.
    expect(Math.round(stored.price / 0.05) * 0.05).toBeCloseTo(stored.price, 10);
    expect(stored.price).toBeCloseTo(105.85, 10);
  });

  it('asks the chart rather than deciding the tick itself', () => {
    // The scale is the only thing that knows, because it is the same tick the
    // axis is written with. A controller that picked its own would disagree
    // with the axis beside it.
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0.5 });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, title: 'T' });
    dragTo(chart, `alert:${alert.id}:0`, 105.8706204379562);
    expect((alerts.list()[0].source as { price: number }).price).toBeCloseTo(106, 10);
  });

  it('leaves the price alone when the scale declares no tick', () => {
    // Nothing to round to. Inventing a tick would move a price somebody chose,
    // which is worse than an ugly number.
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0 });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, title: 'T' });
    dragTo(chart, `alert:${alert.id}:0`, 105.8706204379562);
    expect((alerts.list()[0].source as { price: number }).price).toBeCloseTo(105.8706204379562, 9);
  });

  it('snaps the preview too, not only what is committed', () => {
    // Otherwise the line slides between ticks under the pointer and jumps as
    // it is let go, which reads as the drag having missed.
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0.05 });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, title: 'T' });
    chart.emit('drag:start', { id: `alert:${alert.id}:0`, price: 100, paneIndex: 0 });
    chart.emit('drag', { id: `alert:${alert.id}:0`, price: 105.8706204379562, paneIndex: 0 });
    expect((chart.panes()[0].primitives().find(item => item instanceof PriceLine && item.options().id === `alert:${alert.id}:0`) as PriceLine).price).toBeCloseTo(105.85, 10);
    // Committed value is untouched mid-drag, which 2.4.7 already guarantees.
    expect((alerts.list()[0].source as { price: number }).price).toBe(100);
    chart.emit('drag:end', { id: `alert:${alert.id}:0`, price: 105.8706204379562, paneIndex: 0 });
    expect((alerts.list()[0].source as { price: number }).price).toBeCloseTo(105.85, 10);
  });
});

describe('a dragged alert lands on the band of the instrument tick schedule', () => {
  // Synthetic bands: 0.01 below 100, 0.25 from 100. The axis holds the common
  // grid, 0.01, which is every price the instrument can trade at, not only
  // the ones it can trade at in the band a price falls in.
  const BANDS = () => new TickSchedule([{ tick: 0.01 }, { from: 100, tick: 0.25 }]);
  const drag = (chart: Chart, id: string, from: number, to: number) => {
    chart.emit('drag:start', { id, price: from, paneIndex: 0 });
    chart.emit('drag', { id, price: to, paneIndex: 0 });
  };
  const lineAt = (chart: Chart, id: string) => chart.panes()[0].primitives()
    .find(item => item instanceof PriceLine && item.options().id === id) as PriceLine;

  it('rounds with the band a price falls in, on the price pane only', () => {
    const { chart } = setup();
    chart.panes()[0].priceScale.setOptions({ minMove: 0.01 });
    expect(chart.snapPrice(0, 105.8706204379562)).toBe(105.87);
    chart.setTickSchedule(BANDS());
    expect(chart.tickSchedule()?.bands).toHaveLength(2);
    expect(chart.snapPrice(0, 105.8706204379562)).toBe(105.75);
    expect(chart.snapPrice(0, 99.8706204379562)).toBe(99.87);
    expect(chart.snapPrice(0, 99.996)).toBe(100);
    // A study pane is written in its own units, which no instrument trades in.
    const id = `tick-band-pane-${Math.random()}`;
    registerIndicator({ id, name: 'Reading', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'Reading', type: 'line' }], calc: bars => ({ v: bars.map(() => 30) }) });
    const study = chart.addIndicator(id);
    chart.panes()[study.paneIndex].priceScale.setOptions({ minMove: 0.01 });
    expect(chart.snapPrice(study.paneIndex, 105.8706204379562)).toBe(105.87);
    chart.setTickSchedule(null);
    expect(chart.tickSchedule()).toBeNull();
    expect(chart.snapPrice(0, 105.8706204379562)).toBe(105.87);
  });

  it('refuses a schedule that was never validated', () => {
    const { chart } = setup();
    expect(() => chart.setTickSchedule([{ tick: 0.01 }] as unknown as TickSchedule)).toThrow(/new TickSchedule/);
    // A lookalike with `round` alone would throw inside the drag that pushes a range bound past the other.
    expect(() => chart.setTickSchedule({ round: (price: number) => price } as unknown as TickSchedule)).toThrow(/new TickSchedule/);
    expect(chart.tickSchedule()).toBeNull();
  });

  it('drops a price alert dragged into the coarse band on a price that band trades at', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0.01 });
    chart.primarySeries()!.priceScale().setOptions({ minMove: 0.01 });
    chart.setTickSchedule(BANDS());
    const alert = alerts.add({ source: { kind: 'price', price: 99 }, title: 'T' });
    const id = `alert:${alert.id}:0`;
    drag(chart, id, 99, 105.8706204379562);
    expect(lineAt(chart, id).price).toBe(105.75);
    chart.emit('drag:end', { id, price: 105.8706204379562, paneIndex: 0 });
    expect((alerts.list()[0].source as { price: number }).price).toBe(105.75);
    // Below the boundary the fine band still applies.
    drag(chart, id, 105.75, 99.8706204379562);
    chart.emit('drag:end', { id, price: 99.8706204379562, paneIndex: 0 });
    expect((alerts.list()[0].source as { price: number }).price).toBe(99.87);
  });

  it('keeps a banded range bound inside an opposite bound that is off every tick', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    chart.setTickSchedule(BANDS());
    const alert = alerts.add({ source: { kind: 'price', price: 98, upperPrice: 105.13 }, condition: 'enteringRange' });
    const id = `alert:${alert.id}:0`;
    drag(chart, id, 98, 110);
    // 105.13 rounds up to 105.25, past the bound, so the drag stops a tick below.
    expect(lineAt(chart, id).price).toBe(105);
    chart.emit('drag:end', { id, price: 110, paneIndex: 0 });
    expect(alerts.list()[0].source).toMatchObject({ price: 105, upperPrice: 105.13 });
  });

  it('keeps the constant tick exactly as it was without a schedule', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    chart.panes()[0].priceScale.setOptions({ minMove: 0.05 });
    chart.primarySeries()!.priceScale().setOptions({ minMove: 0.05 });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, title: 'T' });
    const id = `alert:${alert.id}:0`;
    drag(chart, id, 100, 105.8706204379562);
    chart.emit('drag:end', { id, price: 105.8706204379562, paneIndex: 0 });
    expect((alerts.list()[0].source as { price: number }).price).toBe(roundToTick(105.8706204379562, 0.05));
  });
});

describe('the alert the pointer is over', () => {
  it('does not offer a removed numeric line after changing to a candle condition', () => {
    const { chart, alerts } = alertSetup();
    const alert = alerts.add({ source: { kind: 'price', price: 105 } });
    chart.emit('hover', { id: `alert:${alert.id}:0` });
    alerts.update(alert.id, { source: { kind: 'barCondition', id: 'bullish' }, condition: 'matches' });
    expect(alerts.hovered()).toBeUndefined();
  });

  it.each(['context', 'restore', 'replace'] as const)('forgets stale hover after %s', change => {
    const { chart, alerts } = alertSetup();
    chart.setDataContext({ symbol: 'ONE', interval: '5m' });
    const alert = alerts.add({ id: 'same-id', source: { kind: 'price', price: 105 } });
    chart.emit('hover', { id: `alert:${alert.id}:0` });
    expect(alerts.hovered()).toBe(alert.id);
    if (change === 'context') chart.setDataContext({ symbol: 'TWO', interval: '5m' });
    if (change === 'restore') alerts.fromJSON(alerts.toJSON());
    if (change === 'replace') { alerts.remove(alert.id); alerts.add({ id: alert.id, source: { kind: 'price', price: 110 } }); }
    expect(alerts.hovered()).toBeUndefined();
  });

  it('is reported while hovered and forgotten when it is gone', () => {
    // What a Delete key needs to know before anybody presses it, which is the
    // same fact the drawing tier keeps about its own hovered shape.
    const { chart, alerts } = alertSetup([60, 120]);
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'T' });
    expect(alerts.hovered()).toBeUndefined();
    chart.emit('hover', { id: `alert:${alert.id}:0` });
    expect(alerts.hovered()).toBe(alert.id);
    chart.emit('hover', { id: null });
    expect(alerts.hovered()).toBeUndefined();
  });

  it('is not reported for something that is not an alert', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    alerts.add({ source: { kind: 'price', price: 105 }, title: 'T' });
    chart.emit('hover', { id: 'draw:trend-1' });
    expect(alerts.hovered()).toBeUndefined();
    chart.emit('hover', { id: 'order:7::close' });
    expect(alerts.hovered()).toBeUndefined();
  });

  it('stops reporting one that has been removed', () => {
    // The hover event does not fire again just because an alert went away, so
    // a stale id here is a Delete that removes nothing and reports success.
    const { chart, alerts } = alertSetup([60, 120]);
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'T' });
    chart.emit('hover', { id: `alert:${alert.id}:0` });
    expect(alerts.hovered()).toBe(alert.id);
    alerts.remove(alert.id);
    expect(alerts.hovered()).toBeUndefined();
  });

  it('follows the pointer from one alert to another', () => {
    const { chart, alerts } = alertSetup([60, 120]);
    const first = alerts.add({ source: { kind: 'price', price: 105 }, title: 'A' });
    const second = alerts.add({ source: { kind: 'price', price: 110 }, title: 'B' });
    chart.emit('hover', { id: `alert:${first.id}:0` });
    expect(alerts.hovered()).toBe(first.id);
    chart.emit('hover', { id: `alert:${second.id}:0` });
    expect(alerts.hovered()).toBe(second.id);
  });
});

/**
 * A host may ask for a spent alert to stop drawing.
 *
 * Both readings are defensible and they are opposites, which is why this is an
 * option rather than a change. Keeping the line is the default and the reason
 * every lifecycle state has its own badge and colour: the line says what became
 * of the level, which is worth knowing on a chart somebody has just come back
 * to. A terminal left open through a session reads it the other way, because it
 * accumulates levels that will never fire again and the ones still watching
 * become the hardest to pick out of them.
 *
 * What must not change either way is the record. It is what stops a once-only
 * alert firing again every time a host reloads it.
 */
describe('a host that hides the lines of spent alerts', () => {
  it('draws nothing for a triggered alert, and keeps the alert', () => {
    const { chart, alerts, series } = alertSetup([60, 120], { spentLines: 'hide' });
    const remove = vi.spyOn(chart, 'removePrimitive');
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout', policy: 'onTouch', condition: 'crossingUp' });
    series.update({ ...bar(120, 100), high: 106 });

    expect(remove).toHaveBeenCalled();
    const held = alerts.list().find(one => one.id === alert.id);
    expect(held?.state).toBe('triggered');
  });

  it('draws nothing for an expired alert either', () => {
    const { chart, alerts } = alertSetup([60, 120], { spentLines: 'hide' });
    const remove = vi.spyOn(chart, 'removePrimitive');
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout' });
    alerts.update(alert.id, { state: 'armed', expiresAt: 1 });

    expect(remove).toHaveBeenCalled();
    expect(alerts.list().find(one => one.id === alert.id)?.state).toBe('expired');
  });

  it('keeps the line of an alert that is still watching', () => {
    // The direction that matters as much as the other: an option that hid every
    // line would pass the two tests above and be useless.
    const { chart, alerts } = alertSetup([60, 120], { spentLines: 'hide' });
    const attach = vi.spyOn(chart, 'addPrimitive');
    alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout' });
    expect(attach.mock.calls.some(([primitive]) => primitive instanceof PriceLine)).toBe(true);
  });

  it('keeps the line of a repeating alert after it fires', () => {
    // `triggered` is reached only by `repeat: 'once'`, so a repeating alert is
    // still watching and must still be marked.
    const { chart, alerts, series, fired } = alertSetup([60, 120], { spentLines: 'hide' });
    const alert = alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout', policy: 'onTouch', condition: 'crossingUp', repeat: 'everyTime' });
    const remove = vi.spyOn(chart, 'removePrimitive');
    series.update({ ...bar(120, 100), high: 106 });

    expect(fired.length).toBeGreaterThan(0);
    expect(alerts.list().find(one => one.id === alert.id)?.state).toBe('armed');
    expect(remove).not.toHaveBeenCalled();
  });

  it('leaves a spent line alone when the host has not asked', () => {
    // The default, stated here rather than only implied by the tests above.
    const { chart, alerts, series } = alertSetup([60, 120]);
    const remove = vi.spyOn(chart, 'removePrimitive');
    alerts.add({ source: { kind: 'price', price: 105 }, title: 'Breakout', policy: 'onTouch', condition: 'crossingUp' });
    series.update({ ...bar(120, 100), high: 106 });
    expect(remove).not.toHaveBeenCalled();
  });
});
