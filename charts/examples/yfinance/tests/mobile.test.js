import { beforeEach, describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
import {
  initMobile, initRail, magnetMode, setMagnetMode, syncMobileControls, observeMobileControls, focusChart, zoomVisibleRange,
} from '../src/rail.js';
import { chartMotionOptions } from '../src/ui.js';

function add(doc, parent, tag, id) {
  const node = doc.createElement(tag);
  node.id = id;
  parent.appendChild(node);
  return node;
}

function fakeDraw() {
  let tool = null;
  const history = { undo: false, redo: false };
  return {
    history,
    setTool: vi.fn((next) => { tool = next; }),
    activeTool: () => tool,
    undo: vi.fn(),
    redo: vi.fn(),
    setOptions: vi.fn(),
    selected: () => null,
    selection: () => [],
    drawings: () => [],
    canUndo: () => history.undo,
    canRedo: () => history.redo,
  };
}

function fakeChart(from = 10, to = 110, { width = 100, min = 1, max = 80 } = {}) {
  let range = { from, to };
  const handlers = {};
  const timeScale = {
    width,
    barSpacing: width / (to - from),
    constrainBarSpacing: vi.fn((value) => Math.max(min, Math.min(max, value))),
  };
  return {
    timeScale,
    getVisibleLogicalRange: vi.fn(() => ({ ...range })),
    setVisibleLogicalRange: vi.fn((next) => {
      range = { ...next };
      timeScale.barSpacing = width / (range.to - range.from);
    }),
    resetScale: vi.fn(),
    on: vi.fn((event, handler) => {
      (handlers[event] = handlers[event] || []).push(handler);
      return () => {};
    }),
    emit(event, detail = {}) { for (const handler of handlers[event] || []) handler(detail); },
  };
}

function setup() {
  const page = installDom({ width: 390, height: 700 });
  const { document: doc, stage } = page;
  const mobile = add(doc, stage, 'div', 'mobilebar');
  const tool = add(doc, mobile, 'select', 'mobile-draw');
  add(doc, doc.body, 'button', 'fit');
  add(doc, doc.body, 'button', 'toolbar-fit');
  for (const id of ['mobile-cursor', 'mobile-undo', 'mobile-redo', 'mobile-magnet', 'mobile-zoom-out', 'mobile-zoom-in', 'mobile-fit']) {
    add(doc, mobile, 'button', id);
  }
  add(doc, doc.body, 'select', 'drawtool');
  add(doc, doc.body, 'input', 'magnet').type = 'checkbox';
  add(doc, doc.body, 'span', 'status');
  const chart2box = add(doc, doc.body, 'div', 'chart2');
  const app = {
    chart: fakeChart(),
    chart2: fakeChart(20, 60),
    draw: fakeDraw(),
    draw2: fakeDraw(),
    focusPane: 1,
    shortcuts: {},
  };
  initRail(app);
  setMagnetMode('off');
  initMobile(app);
  return { ...page, chart2box, mobile, tool, app };
}

beforeEach(() => {
  delete globalThis.matchMedia;
});

describe('chart motion options', () => {
  it('disables zoom and autoscale animation for reduced motion', () => {
    const view = { matchMedia: vi.fn(() => ({ matches: true })) };
    expect(chartMotionOptions(view)).toEqual({ animZoom: false, animAutoscale: false });
    expect(view.matchMedia).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)');
  });

  it('leaves engine animation defaults intact otherwise', () => {
    expect(chartMotionOptions({ matchMedia: () => ({ matches: false }) })).toEqual({});
    expect(chartMotionOptions({})).toEqual({});
  });
});

describe('compact controls', () => {
  const motionControls = ['mobile-zoom-in', 'mobile-zoom-out', 'mobile-fit', 'toolbar-fit'];
  const assertControls = (doc, disabled, primaryDisabled = disabled) => {
    for (const id of [...motionControls, 'fit']) {
      const expected = id === 'fit' ? primaryDisabled : disabled;
      expect(doc.getElementById(id).disabled, id).toBe(expected);
      expect(doc.getElementById(id).getAttribute('aria-disabled'), id).toBe(String(expected));
    }
  };

  it('updates disabled and accessible states immediately when the selected policy changes', () => {
    const { document: doc, app } = setup();
    let zoomEnabled = true; app.chart.navigationOptions = () => ({ zoomEnabled });
    syncMobileControls(null); assertControls(doc, false);
    zoomEnabled = false; app.chart.emit('objects:change'); assertControls(doc, true);
    for (const id of ['mobile-fit', 'mobile-zoom-in', 'mobile-zoom-out']) doc.getElementById(id).click();
    expect(app.chart.resetScale).not.toHaveBeenCalled();
    expect(app.chart.setVisibleLogicalRange).not.toHaveBeenCalled();
    expect(doc.getElementById('mobile-cursor').disabled).toBe(false);
    zoomEnabled = true; app.chart.emit('objects:change'); assertControls(doc, false);
    doc.getElementById('mobile-fit').click(); expect(app.chart.resetScale).toHaveBeenCalledOnce();
  });

  it('keeps selected controls and primary-only Fit attached to their own policies', () => {
    const { document: doc, app } = setup();
    let primaryEnabled = false;
    app.chart.navigationOptions = () => ({ zoomEnabled: primaryEnabled });
    app.chart2.navigationOptions = () => ({ zoomEnabled: true });
    app.chart.emit('objects:change'); assertControls(doc, true);
    focusChart(2); assertControls(doc, false, true);
    primaryEnabled = true; app.chart.emit('objects:change'); assertControls(doc, false, false);
    primaryEnabled = false; app.chart.emit('objects:change'); assertControls(doc, false, true);
    focusChart(1); assertControls(doc, true);
  });

  it('follows restore and ignores obsolete policy values from replaced charts', () => {
    const { document: doc, app } = setup(), old = app.chart;
    old.navigationOptions = () => ({ zoomEnabled: false });
    old.emit('state:restore:end'); assertControls(doc, true);
    app.chart = fakeChart(); app.chart.navigationOptions = () => ({ zoomEnabled: true });
    observeMobileControls(app.chart, app.draw); syncMobileControls(null); assertControls(doc, false);
    old.emit('objects:change'); old.emit('state:restore:end'); assertControls(doc, false);
    app.chart.isDestroyed = true; app.chart.emit('destroy'); assertControls(doc, true);
  });

  it('observes navigation on a chart without a drawing controller and disables unavailable targets', () => {
    const { document: doc, app } = setup();
    app.chart = fakeChart(); app.draw = null;
    let zoomEnabled = true; app.chart.navigationOptions = () => ({ zoomEnabled });
    observeMobileControls(app.chart, null); syncMobileControls(null); assertControls(doc, false);
    zoomEnabled = false; app.chart.emit('objects:change'); assertControls(doc, true);
    app.chart = null; syncMobileControls(null); assertControls(doc, true);
    app.chart = fakeChart(); syncMobileControls(null); assertControls(doc, false);
  });

  it('can attach drawing history after navigation was observed without a controller', () => {
    const { document: doc, app } = setup();
    app.chart = fakeChart(); app.draw = null; observeMobileControls(app.chart, null);
    syncMobileControls(null); expect(doc.getElementById('mobile-undo').disabled).toBe(true);
    app.draw = fakeDraw(); observeMobileControls(app.chart, app.draw);
    app.draw.history.undo = true; app.chart.emit('draw:add');
    expect(doc.getElementById('mobile-undo').disabled).toBe(false);
  });

  it('routes drawing controls to the existing controller and keeps their state current', () => {
    const { tool, document: doc, app } = setup();
    expect(tool.children.length).toBeGreaterThan(20);

    tool.value = 'trend-line';
    tool.fire('change');
    expect(app.draw.setTool).toHaveBeenLastCalledWith('trend-line');

    doc.getElementById('mobile-cursor').click();
    expect(app.draw.setTool).toHaveBeenLastCalledWith(null);
    expect(tool.value).toBe('');

    doc.getElementById('mobile-undo').click();
    doc.getElementById('mobile-redo').click();
    expect(app.draw.undo).toHaveBeenCalledOnce();
    expect(app.draw.redo).toHaveBeenCalledOnce();

    doc.getElementById('mobile-magnet').click();
    expect(magnetMode()).toBe('weak');
    expect(doc.getElementById('mobile-magnet').textContent).toBe('Magnet: weak');

    syncMobileControls('rectangle');
    expect(tool.value).toBe('rectangle');
  });

  it('refreshes Undo and Redo after controller history changes outside the mobile buttons', () => {
    const { document: doc, app } = setup();
    const undo = doc.getElementById('mobile-undo');
    const redo = doc.getElementById('mobile-redo');
    expect(undo.disabled).toBe(true);
    expect(redo.disabled).toBe(true);

    app.draw.history.undo = true;
    app.chart.emit('draw:add');
    expect(undo.disabled).toBe(false);

    app.draw.history.undo = false;
    app.draw.history.redo = true;
    app.chart.emit('drawing:change');
    expect(undo.disabled).toBe(true);
    expect(redo.disabled).toBe(false);
  });

  it('zooms and resets the chart for the last plot touched', () => {
    const { document: doc, chart2box, app } = setup();
    doc.getElementById('mobile-zoom-in').click();
    expect(app.chart.setVisibleLogicalRange).toHaveBeenLastCalledWith({ from: 20, to: 100 });

    chart2box.fire('pointerdown');
    doc.getElementById('mobile-zoom-out').click();
    expect(app.chart2.setVisibleLogicalRange).toHaveBeenLastCalledWith({ from: 15, to: 65 });
    doc.getElementById('mobile-fit').click();
    expect(app.chart2.resetScale).toHaveBeenCalledOnce();
  });

  it('keeps explicit selection while another chart is only hovered and supports keyboard focus', () => {
    const { document: doc, chart2box, app } = setup();
    chart2box.fire('pointerdown');
    expect(app.focusPane).toBe(2);
    doc.getElementById('chart').fire('pointerenter');
    expect(app.focusPane).toBe(2);
    expect(chart2box.getAttribute('data-chart-focused')).toBe('true');
    doc.getElementById('chart').fire('focusin');
    expect(app.focusPane).toBe(1);
    expect(chart2box.getAttribute('data-chart-focused')).toBe('false');
    expect(doc.getElementById('chart').tabIndex).toBe(0);
  });

  it('keeps pointer presses on the controls out of the chart gesture path', () => {
    const { mobile } = setup();
    const event = mobile.fire('pointerdown');
    expect(event._stop).toBe(true);
  });
});

describe('logical range zoom', () => {
  it('preserves the center while scaling the visible span', () => {
    const chart = fakeChart();
    expect(zoomVisibleRange(chart, 0.8)).toBe(true);
    expect(chart.setVisibleLogicalRange).toHaveBeenLastCalledWith({ from: 20, to: 100 });
    expect(zoomVisibleRange(null, 0.8)).toBe(false);
  });

  it('does not pan the range when zoom is already at the minimum or maximum spacing', () => {
    const atMinimum = fakeChart(10, 110);
    expect(zoomVisibleRange(atMinimum, 1.25)).toBe(false);
    expect(atMinimum.setVisibleLogicalRange).not.toHaveBeenCalled();

    const atMaximum = fakeChart(40, 41.25);
    expect(zoomVisibleRange(atMaximum, 0.8)).toBe(false);
    expect(atMaximum.setVisibleLogicalRange).not.toHaveBeenCalled();
  });

  it('uses the legal span when a zoom step reaches a spacing boundary', () => {
    const chart = fakeChart(10, 80 / 7, { max: 80 });
    expect(zoomVisibleRange(chart, 0.8)).toBe(true);
    expect(chart.timeScale.constrainBarSpacing.mock.calls[0][0]).toBeCloseTo(87.5, 10);
    const legal = chart.setVisibleLogicalRange.mock.calls[0][0];
    expect(legal.from).toBeCloseTo(10.089285714285714, 12);
    expect(legal.to).toBeCloseTo(11.339285714285714, 12);
  });
});
