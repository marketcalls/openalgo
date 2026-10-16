/**
 * The anchor of a paired study input: a handle at the time and price two
 * settings name, dragged by a real pointer through the real chart, written
 * as one settings patch and walked by the drawing history's undo.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorInput } from '../src/model/indicator-registry';
import type { IndicatorApi } from '../src/model/indicator-instance';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { DrawingController, studyInputTarget } from '../src/draw/index';
import { darkTheme } from '../src/theme';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';

const T0 = 1700000000;
let serial = 0;
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.unstubAllGlobals(); });

function register(price: Partial<Extract<IndicatorInput, { type: 'price' }>> = {}, placement: 'onchart' | 'pane' = 'onchart'): string {
  const id = `anchor-study-${++serial}`;
  registerIndicator({ id, name: 'Anchored level', placement, inputs: [
    { key: 'at', type: 'timestamp', label: 'Anchor time', default: T0 + 10 * 60, min: T0, pick: true },
    { key: 'level', type: 'price', label: 'Anchor price', default: 100, min: 50, max: 150, pick: true, timeKey: 'at', anchor: true, ...price } as IndicatorInput,
  ], plots: [{ key: 'v', title: 'Level', type: 'line', style: { color: '#ff8800' } }],
  calc: (bars, settings) => ({ v: bars.map(bar => (bar.time >= (settings.at as number) ? settings.level as number : NaN)) }) });
  return id;
}

function mount(options: { inputAnchors?: boolean } = {}) {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el as unknown as HTMLElement, { document: doc, pixelRatio: () => 1, shortcuts: false, branding: false,
    timeNavigator: false, animZoom: false, animAutoscale: false, raf: { schedule: () => 0, cancel: () => {} } });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 40 }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: T0 + i * 60, open: c - 1, high: c + 2, low: c - 2, close: c };
  }));
  chart.setVisibleLogicalRange({ from: 0, to: 39 });
  const draw = new DrawingController(chart, options.inputAnchors === undefined ? {} : { inputAnchors: options.inputAnchors });
  cleanups.push(() => chart.destroy(), () => draw.destroy());
  const move = (x: number, y: number, pressed = false) => el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0 }));
  const press = (x: number, y: number) => { move(x, y); el.dispatch('pointerdown', pointer('down', x, y)); };
  const dragTo = (x0: number, y0: number, x1: number, y1: number, release = true) => {
    press(x0, y0);
    for (let i = 1; i <= 5; i++) move(x0 + ((x1 - x0) * i) / 5, y0 + ((y1 - y0) * i) / 5, true);
    if (release) el.dispatch('pointerup', pointer('up', x1, y1));
  };
  return { chart, draw, el, move, press, dragTo };
}

/** The handle the anchors put on a pane for one input. */
function handleOf(chart: Chart, study: IndicatorApi, key = 'level'): IPrimitive | undefined {
  return chart.panes().flatMap(pane => [...pane.primitives()])
    .find(item => (item as { id?: unknown }).id === `input-anchor:${study.id}:${key}`);
}

/** Container px of the point a study's pair names, read through its target scale. */
function pointOf(chart: Chart, study: IndicatorApi, time?: number, price?: number) {
  const settings = study.settings();
  const target = studyInputTarget(chart, study, 'level')!;
  const scale = chart.panes()[target.paneIndex].scaleFor(target.priceScaleId);
  const rect = chart.plotRect(target.paneIndex)!;
  return { x: chart.timeToCoordinate(time ?? settings.at as number)!, y: rect.top + scale.priceToY(price ?? settings.level as number), scale, rect };
}

function context(chart: Chart, paneIndex: number): PrimitiveRenderContext {
  const pane = chart.panes()[paneIndex], rect = chart.plotRect(paneIndex)!;
  return { timeScale: chart.timeScale, dataLayer: chart.dataLayer, priceScale: pane.priceScale,
    plotWidth: rect.width, plotHeight: rect.height, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
}

describe('a study input anchor', () => {
  it('sits at the stored point on the pane and scale a pick of the price reads', () => {
    const { chart } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const handle = handleOf(chart, study)!;
    expect(handle).toBeDefined();
    expect(chart.panes()[0].hasPrimitive(handle)).toBe(true);
    const at = pointOf(chart, study);
    const hit = handle.hitTest!(at.x - at.rect.left, at.y - at.rect.top, context(chart, 0));
    expect(hit).toMatchObject({ externalId: `input-anchor:${study.id}:level`, draggable: true, cancelOnEscape: true, cursor: 'move' });
    expect(hit!.priceScale).toBe(at.scale);
    expect(handle.hitTest!(at.x - at.rect.left + 30, at.y - at.rect.top, context(chart, 0))).toBeNull();
    // It paints in the study's own colour, with no guides until it is in hand.
    const { ctx, rec } = makeCtx();
    handle.draw(ctx, context(chart, 0));
    expect(rec.ops.some(op => op.type === 'stroke' && op.strokeStyle === '#ff8800')).toBe(true);
    expect(rec.ops.filter(op => op.type === 'lineTo')).toHaveLength(0);
  });

  it('drags the time and the price together as one settings patch', () => {
    const { chart, dragTo } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const write = vi.spyOn(study, 'setSettings');
    const from = pointOf(chart, study);
    const toX = chart.timeToCoordinate(T0 + 25 * 60)! + 4;
    dragTo(from.x, from.y, toX, from.y - 60);
    expect(write).toHaveBeenCalledOnce();
    const patch = write.mock.calls[0][0];
    expect(Object.keys(patch).sort()).toEqual(['at', 'level']);
    // The time is the bar under the release, the price is read on the target scale.
    expect(patch.at).toBe(T0 + 25 * 60);
    expect(patch.level).toBeCloseTo(from.scale.yToPrice(from.y - 60 - from.rect.top), 9);
    expect(study.settings()).toMatchObject(patch);
    expect(study.values().v.slice(0, 25).every(v => v === null || Number.isNaN(v))).toBe(true);
  });

  it('is one step of the drawing history, walked in order with the drawings', () => {
    const { chart, draw, dragTo } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const before = study.settings();
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 60, price: 97 }] });
    const from = pointOf(chart, study);
    dragTo(from.x, from.y, chart.timeToCoordinate(T0 + 20 * 60)!, from.y + 40);
    const after = study.settings();
    expect(after.at).toBe(T0 + 20 * 60);
    expect(draw.canUndo()).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: before.at, level: before.level });
    expect(draw.get(line.id)).toBeDefined();
    expect(draw.undo()).toBe(true);
    expect(draw.get(line.id)).toBeUndefined();
    expect(study.settings()).toMatchObject({ at: before.at, level: before.level });
    expect(draw.redo()).toBe(true);
    expect(draw.get(line.id)).toBeDefined();
    expect(draw.redo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: after.at, level: after.level });
  });

  it('announces the step so a host refreshes its Undo and Redo controls', () => {
    const { chart, draw, dragTo } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const changes: unknown[] = [];
    chart.on('drawing:change', event => changes.push(event));
    const from = pointOf(chart, study);
    dragTo(from.x, from.y, from.x + 60, from.y + 30);
    // No drawing changed, so no id is named: the history did.
    expect(changes).toEqual([{ ids: [], kind: 'update' }]);
    draw.undo();
    draw.redo();
    expect(changes.slice(1)).toEqual([{ ids: [], kind: 'undo' }, { ids: [], kind: 'redo' }]);
  });

  it('takes back a point a settings dialog picked outside the anchors first, and never a drawing made before it', () => {
    const { chart, draw, dragTo } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const start = { at: study.settings().at, level: study.settings().level };
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 60, price: 97 }] });
    const from = pointOf(chart, study);
    dragTo(from.x, from.y, chart.timeToCoordinate(T0 + 20 * 60)!, from.y + 40);
    const dragged = { at: study.settings().at, level: study.settings().level };
    expect(dragged.at).toBe(T0 + 20 * 60);
    // What a settings dialog's Pick point on chart writes: both halves, through the settings.
    const picked = { at: T0 + 30 * 60, level: 120 };
    expect(study.setSettings(picked)).toBe(true);

    // The press takes the pick back: the line drawn before any of it stays.
    expect(draw.undo()).toBe(true);
    expect(draw.get(line.id)).toBeDefined();
    expect(study.settings()).toMatchObject(dragged);
    expect(draw.undo()).toBe(true);
    expect(draw.get(line.id)).toBeDefined();
    expect(study.settings()).toMatchObject(start);
    expect(draw.undo()).toBe(true);
    expect(draw.get(line.id)).toBeUndefined();
    expect(study.settings()).toMatchObject(start);
    expect(draw.canUndo()).toBe(false);
    for (let i = 0; i < 3; i++) expect(draw.redo()).toBe(true);
    expect(study.settings()).toMatchObject(picked);
    expect(draw.get(line.id)).toBeDefined();
    expect(draw.canRedo()).toBe(false);
  });

  it('takes back a picked point with no drag before it, a hidden study\'s too, and never the drawing before it', () => {
    const { chart, draw } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const start = { at: study.settings().at, level: study.settings().level };
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 60, price: 97 }] });
    study.setSettings({ at: T0 + 30 * 60, level: 120 });
    // Hidden, it has no handle, and its point is still the chart's to take back.
    study.setVisible(false);
    study.setSettings({ level: 125 });
    expect(draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: T0 + 30 * 60, level: 120 });
    expect(draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject(start);
    expect(draw.get(line.id)).toBeDefined();
    expect(draw.undo()).toBe(true);
    expect(draw.get(line.id)).toBeUndefined();
  });

  it('records no step for a point the host writes inside untracked or forces on a study the user may not configure, and hands none to a host timeline', () => {
    const m = mount();
    const study = m.chart.addIndicator(register());
    m.chart.exportSVG();
    m.draw.untracked(() => study.setSettings({ level: 110 }));
    expect(m.draw.canUndo()).toBe(false);
    study.setPolicy({ configurable: false });
    expect(study.setSettings({ level: 111 }, { force: true })).toBe(true);
    expect(m.draw.canUndo()).toBe(false);
    study.setPolicy(null);
    // A host timeline observes the settings it writes itself: only the anchors' own moves go to it.
    const steps: unknown[] = [];
    const giveBack = m.draw.delegateInputAnchorSteps(step => steps.push(step));
    study.setSettings({ level: 112 });
    expect(steps).toEqual([]);
    expect(m.draw.canUndo()).toBe(false);
    giveBack();
    // A study brought in with its point already set is no step: nothing moved it.
    m.chart.addIndicator(register(), { at: T0 + 5 * 60, level: 90 });
    expect(m.draw.canUndo()).toBe(false);
    study.setSettings({ level: 113 });
    expect(m.draw.canUndo()).toBe(true);
    expect(m.draw.undo()).toBe(true);
    expect(study.settings().level).toBe(112);
  });

  it('writes nothing when Escape cancels the drag, and puts the handle back', () => {
    const { chart, el, dragTo } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const write = vi.spyOn(study, 'setSettings');
    const from = pointOf(chart, study);
    dragTo(from.x, from.y, from.x + 120, from.y - 50, false);
    const handle = handleOf(chart, study) as unknown as { time: number; price: number };
    expect(handle.time).not.toBe(study.settings().at);
    el.dispatch('keydown', { key: 'Escape', target: null, preventDefault() {} });
    el.dispatch('pointerup', pointer('up', from.x + 120, from.y - 50));
    expect(write).not.toHaveBeenCalled();
    expect(handle.time).toBe(study.settings().at);
    expect(handle.price).toBe(study.settings().level);
  });

  it.each([
    ['a drawing tool is chosen', (m: ReturnType<typeof mount>) => m.draw.setTool('horizontal-line')],
    ['a pick starts', (m: ReturnType<typeof mount>) => { m.chart.beginPick('price', () => {}); }],
    ['the data context changes', (m: ReturnType<typeof mount>) => { m.chart.emit('data:context', { symbol: 'OTHER' }); }],
  ])('drops a drag in hand when %s, and the release writes nothing', (_name, interrupt) => {
    const m = mount();
    const study = m.chart.addIndicator(register());
    m.chart.exportSVG();
    const write = vi.spyOn(study, 'setSettings');
    const from = pointOf(m.chart, study);
    m.dragTo(from.x, from.y, from.x + 120, from.y - 50, false);
    const handle = handleOf(m.chart, study) as unknown as { time: number; price: number };
    expect(handle.time).not.toBe(study.settings().at);
    interrupt(m);
    // Back at the stored point at once, before the pointer is even let go.
    expect(handle.time).toBe(study.settings().at);
    expect(handle.price).toBe(study.settings().level);
    m.move(from.x + 160, from.y - 70, true);
    m.el.dispatch('pointerup', pointer('up', from.x + 160, from.y - 70));
    expect(write).not.toHaveBeenCalled();
    expect(m.draw.canUndo()).toBe(false);
  });

  it('takes a point a host control picked as one step, so undo walks it with the drags', () => {
    const m = mount();
    const study = m.chart.addIndicator(register());
    m.chart.exportSVG();
    const start = { ...study.settings() };
    const from = pointOf(m.chart, study);
    m.dragTo(from.x, from.y, m.chart.timeToCoordinate(T0 + 20 * 60)!, from.y - 30);
    const dragged = { ...study.settings() };
    // A point pick, the way a host button offers one, then Undo and Redo.
    m.chart.beginPick('point', p => m.draw.moveInputAnchor(study.id, 'level', p));
    const x = m.chart.timeToCoordinate(T0 + 30 * 60)! + 3, y = from.y + 20;
    m.move(x, y);
    m.el.dispatch('pointerdown', pointer('down', x, y));
    m.el.dispatch('pointerup', pointer('up', x, y));
    expect(study.settings().at).toBe(T0 + 30 * 60);
    expect(m.draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: dragged.at, level: dragged.level });
    expect(m.draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: start.at, level: start.level });
    expect(m.draw.redo()).toBe(true);
    expect(m.draw.redo()).toBe(true);
    expect(study.settings().at).toBe(T0 + 30 * 60);
    // Held in bounds like a drag, refused for a study the user may not configure, and false for no anchor.
    expect(m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 5 * 60, price: 999 })).toBe(true);
    expect(study.settings().level).toBe(150);
    study.setPolicy({ configurable: false });
    expect(m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 6 * 60, price: 90 })).toBe(false);
    expect(m.draw.moveInputAnchor(study.id, 'at', { time: T0 + 6 * 60, price: 90 })).toBe(false);
    expect(m.draw.moveInputAnchor('missing', 'level', { time: T0 + 6 * 60, price: 90 })).toBe(false);
  });

  it('hands each move to a host timeline that took the steps, and records none of its own', () => {
    const m = mount();
    const study = m.chart.addIndicator(register());
    m.chart.exportSVG();
    const start = { ...study.settings() };
    const changes: unknown[] = [];
    m.chart.on('drawing:change', event => changes.push(event));
    const steps: { undo(): boolean; redo(): boolean }[] = [];
    const giveBack = m.draw.delegateInputAnchorSteps(step => steps.push(step));
    const from = pointOf(m.chart, study);
    m.dragTo(from.x, from.y, m.chart.timeToCoordinate(T0 + 20 * 60)!, from.y - 30);
    const dragged = { ...study.settings() };
    expect(dragged.at).toBe(T0 + 20 * 60);
    expect(m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 30 * 60, price: 120 })).toBe(true);
    expect(steps).toHaveLength(2);
    expect(m.draw.canUndo()).toBe(false);
    expect(m.draw.historySteps()).toEqual({ undo: [], redo: [] });
    expect(changes).toEqual([]);
    // The steps walk the settings back and forth for the host.
    expect(steps[1].undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: dragged.at, level: dragged.level });
    expect(steps[0].undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: start.at, level: start.level });
    expect(steps[0].undo()).toBe(false);
    expect(steps[0].redo()).toBe(true);
    // A move inside `untracked` is the host's own: no step here or there.
    m.draw.untracked(() => m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 5 * 60, price: 90 }));
    expect(steps).toHaveLength(2);
    expect(m.draw.canUndo()).toBe(false);
    // A later owner takes them; giving back an earlier one's leaves it be.
    const later: unknown[] = [];
    const giveBackLater = m.draw.delegateInputAnchorSteps(step => later.push(step));
    giveBack();
    expect(m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 6 * 60, price: 91 })).toBe(true);
    expect(later).toHaveLength(1);
    giveBackLater();
    expect(m.draw.moveInputAnchor(study.id, 'level', { time: T0 + 7 * 60, price: 92 })).toBe(true);
    expect(later).toHaveLength(1);
    expect(m.draw.canUndo()).toBe(true);
    expect(changes).toEqual([{ ids: [], kind: 'update' }]);
  });

  it('gives the press to an active drawing tool, and a pick the click', () => {
    const { chart, draw, press, el } = mount();
    const study = chart.addIndicator(register());
    chart.exportSVG();
    const write = vi.spyOn(study, 'setSettings');
    const at = pointOf(chart, study);
    draw.setTool('horizontal-line');
    expect(handleOf(chart, study)!.hitTest!(at.x - at.rect.left, at.y - at.rect.top, context(chart, 0))).toBeNull();
    press(at.x, at.y);
    el.dispatch('pointerup', pointer('up', at.x, at.y));
    expect(draw.drawings().map(d => d.tool)).toEqual(['horizontal-line']);
    draw.setTool(null);
    // The line just placed would take the click itself.
    draw.remove(draw.drawings()[0].id);
    const picked = vi.fn();
    chart.beginPick('point', picked);
    press(at.x, at.y);
    el.dispatch('pointerup', pointer('up', at.x, at.y));
    expect(picked).toHaveBeenCalledOnce();
    expect(write).not.toHaveBeenCalled();
  });

  it('keeps still for a study the user may not configure, and hides with its study', () => {
    const { chart, dragTo } = mount();
    const study = chart.addIndicator(register(), {}, { policy: { configurable: false } });
    chart.exportSVG();
    const at = pointOf(chart, study);
    expect(handleOf(chart, study)!.hitTest!(at.x - at.rect.left, at.y - at.rect.top, context(chart, 0))).toBeNull();
    dragTo(at.x, at.y, at.x + 100, at.y + 30);
    expect(study.settings().at).toBe(T0 + 10 * 60);
    study.setVisible(false);
    expect(handleOf(chart, study)).toBeUndefined();
    study.setVisible(true);
    expect(handleOf(chart, study)).toBeDefined();
    study.remove({ force: true });
    expect(handleOf(chart, study)).toBeUndefined();
  });

  it('reads the price on the scale its target names, in a pane of its own', () => {
    const { chart, dragTo } = mount();
    const study = chart.addIndicator(register({ min: -1000, max: 1000 }, 'pane'), {}, { priceScaleId: 'overlay:anchor' });
    chart.exportSVG();
    const target = studyInputTarget(chart, study, 'level');
    expect(target).toEqual({ paneIndex: 1, priceScaleId: 'overlay:anchor' });
    const handle = handleOf(chart, study)!;
    expect(chart.panes()[1].hasPrimitive(handle)).toBe(true);
    const from = pointOf(chart, study);
    dragTo(from.x, from.y, from.x, from.y + 20);
    expect(study.settings().level).toBeCloseTo(from.scale.yToPrice(from.y + 20 - from.rect.top), 9);
    expect(from.scale).not.toBe(chart.panes()[1].priceScale);
  });

  it('holds a dragged point inside the bounds its inputs declare', () => {
    const { chart, dragTo } = mount();
    const study = chart.addIndicator(register({ max: 101 }));
    chart.exportSVG();
    const from = pointOf(chart, study, undefined, 100);
    dragTo(from.x, from.y, from.x, from.rect.top + 2);
    expect(study.settings().level).toBe(101);
  });

  it('draws none when the controller is built without input anchors', () => {
    const { chart } = mount({ inputAnchors: false });
    const study = chart.addIndicator(register());
    expect(handleOf(chart, study)).toBeUndefined();
  });

  it('draws none for a pair that did not ask for one', () => {
    const { chart } = mount();
    const study = chart.addIndicator(register({ anchor: false }));
    expect(handleOf(chart, study)).toBeUndefined();
  });
});
