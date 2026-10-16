import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { applyChartSettings, readChartSettings } from '../src/model/chart-settings';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const bars = Array.from({ length: 200 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100, high: 102, low: 98, close: 101,
}));
const charts: Chart[] = [];
afterEach(() => {
  charts.splice(0).forEach((chart) => chart.destroy());
  vi.unstubAllGlobals();
});

function mount(options: Partial<ChartOptions> = {}, load = true) {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const el = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel() {} }, ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  if (load) series.setData(bars);
  return { chart, el, series };
}

describe('mouse panning preferences', () => {
  it('keeps autofit during a horizontal mouse drag with minor vertical jitter', () => {
    const { chart, series, el } = mount({ navigation: { defaultBarSpacing: 8 }, animAutoscale: false });
    series.setData(bars.map((bar, i) => i === 70 ? { ...bar, high: 200 } : bar));
    chart.resetScale();
    const scale = chart.panes()[0].priceScale;
    expect(scale.priceRange().max).toBeLessThan(110);
    el.dispatch('pointerdown', pointer('down', 200, 220));
    el.dispatch('pointermove', pointer('move', 350, 221));
    el.dispatch('pointermove', pointer('move', 600, 222));
    el.dispatch('pointerup', pointer('up', 600, 222));
    expect(scale.autoScale).toBe(true);
    expect(scale.priceRange().max).toBeGreaterThan(200);
    expect(readChartSettings(chart)['scales.autoScale']).toBe(true);
  });

  it('still allows deliberate vertical movement after a small mouse adjustment', () => {
    const { chart, el } = mount({ animAutoscale: false });
    const scale = chart.panes()[0].priceScale;
    const before = { ...scale.priceRange() };
    el.dispatch('pointerdown', pointer('down', 200, 220));
    el.dispatch('pointermove', pointer('move', 210, 221));
    expect(scale.autoScale).toBe(true);
    el.dispatch('pointermove', pointer('move', 240, 240));
    el.dispatch('pointerup', pointer('up', 240, 240));
    expect(scale.autoScale).toBe(false);
    expect(scale.priceRange().min).toBeGreaterThan(before.min);
    expect(scale.priceRange().max - scale.priceRange().min).toBeCloseTo(before.max - before.min);
  });

  it.each(['mouse', 'pen'])('shows a grabbing hand only while a %s holds the plot', (pointerType) => {
    const { chart, el } = mount();
    el.dispatch('pointerdown', pointer('down', 400, 220, { pointerType }));
    expect(el.style.cursor).toBe('grabbing');
    el.dispatch('pointerleave', {});
    expect(el.style.cursor).toBe('grabbing');
    el.dispatch('pointermove', pointer('move', 450, 260, { pointerType }));
    el.dispatch('pointerup', pointer('up', 450, 260, { pointerType }));
    expect(el.style.cursor).toBe('');
    const offset = chart.timeScale.rightOffset;
    const range = { ...chart.panes()[0].priceScale.priceRange() };
    el.dispatch('pointermove', pointer('up', 500, 300, { pointerType }));
    expect(chart.timeScale.rightOffset).toBe(offset);
    expect(chart.panes()[0].priceScale.priceRange()).toEqual(range);
  });

  it.each(['mouse', 'pen', 'touch'])('keeps release momentum exclusive to touch (%s)', (pointerType) => {
    let time = 0;
    let nextId = 0;
    const frames = new Map<number, () => void>();
    const frame = () => {
      time += 16;
      const batch = [...frames.values()];
      frames.clear();
      batch.forEach((cb) => cb());
    };
    const { chart, el } = mount({ now: () => time, animZoom: false,
      raf: { schedule: (cb) => { frames.set(++nextId, cb); return nextId; }, cancel: (id) => { frames.delete(id); } },
    });
    frame();
    el.dispatch('pointerdown', pointer('down', 400, 220, { pointerType }));
    frame();
    el.dispatch('pointermove', pointer('move', 490, 270, { pointerType }));
    frame();
    const offset = chart.timeScale.rightOffset;
    const range = { ...chart.panes()[0].priceScale.priceRange() };
    el.dispatch('pointerup', pointer('up', 490, 270, { pointerType }));
    for (let i = 0; i < 60; i++) frame();
    if (pointerType === 'touch') expect(chart.timeScale.rightOffset).toBeLessThan(offset);
    else expect(chart.timeScale.rightOffset).toBe(offset);
    expect(chart.panes()[0].priceScale.priceRange()).toEqual(range);
  });

  it.each(['pointercancel', 'lostpointercapture', 'missed-release'])('ends a held pan on %s', (end) => {
    const { chart, el } = mount();
    const clicks = vi.fn();
    chart.on('click', clicks);
    el.dispatch('pointerdown', pointer('down', 400, 220));
    el.dispatch('pointermove', pointer('move', 450, 260));
    if (end === 'missed-release') el.dispatch('pointermove', pointer('up', 450, 260));
    else el.dispatch(end, pointer('up', 450, 260, { type: end }));
    expect(el.style.cursor).toBe('');
    const offset = chart.timeScale.rightOffset;
    const range = { ...chart.panes()[0].priceScale.priceRange() };
    el.dispatch('pointermove', pointer('move', 500, 300));
    el.dispatch('pointerup', pointer('up', 500, 300));
    expect(chart.timeScale.rightOffset).toBe(offset);
    expect(chart.panes()[0].priceScale.priceRange()).toEqual(range);
    expect(clicks).not.toHaveBeenCalled();
  });

  it('does not turn axis resizing or drawing placement into a plot grab', () => {
    const { chart, el } = mount();
    el.dispatch('pointerdown', pointer('down', 780, 220));
    expect(el.style.cursor).not.toBe('grabbing');
    el.dispatch('pointerup', pointer('up', 780, 220));
    chart.setPlacementMode(true);
    el.dispatch('pointerdown', pointer('down', 400, 220));
    expect(el.style.cursor).not.toBe('grabbing');
    el.dispatch('pointerup', pointer('up', 400, 220));
  });

  it.each(['plot', 'line'])('ignores another pen hovering or releasing during a held %s gesture', (target) => {
    const { chart, el } = mount();
    const end = vi.fn();
    const click = vi.fn();
    chart.on('click', click);
    chart.subscribeDrag(vi.fn(), end);
    if (target === 'line') chart.addPriceLine({ id: 'test-line', price: 100, color: '#336699', cursor: 'ns-resize' });
    const y = target === 'line' ? chart.priceToCoordinate(100)! : 220;
    el.dispatch('pointerdown', pointer('down', 400, y));
    const cursor = el.style.cursor;
    const offset = chart.timeScale.rightOffset;
    const range = { ...chart.panes()[0].priceScale.priceRange() };
    el.dispatch('pointermove', pointer('up', 500, y + 50, { pointerId: 2, pointerType: 'pen' }));
    el.dispatch('pointerup', pointer('up', 500, y + 50, { pointerId: 2, pointerType: 'pen' }));
    expect(end).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    expect(el.style.cursor).toBe(cursor);
    expect(chart.timeScale.rightOffset).toBe(offset);
    expect(chart.panes()[0].priceScale.priceRange()).toEqual(range);
    el.dispatch('pointermove', pointer('move', 440, y + 20));
    el.dispatch('pointerup', pointer('up', 440, y + 20));
    if (target === 'line') expect(end).toHaveBeenCalledOnce();
    else expect(chart.timeScale.rightOffset).not.toBe(offset);
  });

  it('clears a plot grab when a drawing tool is armed during the held gesture', () => {
    const { chart, el } = mount();
    el.dispatch('pointerdown', pointer('down', 400, 220));
    el.dispatch('pointermove', pointer('move', 450, 260));
    chart.setPlacementMode(true);
    el.dispatch('pointerup', pointer('up', 450, 260));
    expect(el.style.cursor).toBe('');
  });

  it('shows a grabbing hand when a passive plot guide is under the press', () => {
    const { chart, el } = mount();
    chart.addPriceLine({ id: 'guide', price: 100, color: '#336699', cursor: 'crosshair' });
    const y = chart.priceToCoordinate(100)!;
    el.dispatch('pointerdown', pointer('down', 400, y));
    expect(el.style.cursor).toBe('grabbing');
    const offset = chart.timeScale.rightOffset;
    el.dispatch('pointermove', pointer('move', 450, y + 20));
    expect(chart.timeScale.rightOffset).not.toBe(offset);
    el.dispatch('pointerup', pointer('up', 450, y + 20));
    expect(el.style.cursor).toBe('');
  });

  it.each(['mouse', 'pen'])('pans time and price by default with a %s', (pointerType) => {
    const { chart, el } = mount();
    const scale = chart.panes()[0].priceScale;
    const before = { ...scale.priceRange() };
    const offset = chart.timeScale.rightOffset;
    el.dispatch('pointerdown', pointer('down', 400, 220, { pointerType }));
    el.dispatch('pointermove', pointer('move', 450, 260, { pointerType }));
    expect(chart.timeScale.rightOffset).toBeLessThan(offset);
    expect(scale.autoScale).toBe(false);
    expect(scale.priceRange()).not.toEqual(before);
  });

  it('preserves price autoscale when horizontal-only panning is selected in settings', () => {
    const { chart, el } = mount();
    applyChartSettings(chart, { 'navigation.mousePan': 'horizontal' });
    const scale = chart.panes()[0].priceScale;
    const before = { ...scale.priceRange() };
    const offset = chart.timeScale.rightOffset;
    el.dispatch('pointerdown', pointer('down', 400, 220));
    el.dispatch('pointermove', pointer('move', 450, 260));
    expect(chart.timeScale.rightOffset).toBeLessThan(offset);
    expect(scale.autoScale).toBe(true);
    expect(scale.priceRange()).toEqual(before);
  });

  it('keeps direct price-axis adjustment available with horizontal mouse panning', () => {
    const { chart, el } = mount({ navigation: { mousePan: 'horizontal' } });
    const scale = chart.panes()[0].priceScale;
    const before = scale.priceRange().max - scale.priceRange().min;
    el.dispatch('pointerdown', pointer('down', 780, 220));
    el.dispatch('pointermove', pointer('move', 780, 260));
    expect(scale.autoScale).toBe(false);
    expect(scale.priceRange().max - scale.priceRange().min).toBeGreaterThan(before);
  });

  it('resets a manually adjusted left price axis as well as the right axis', () => {
    const { chart, el } = mount();
    const left = chart.addSeries('line', { priceScaleId: 'left' });
    left.setData(bars.map((bar) => ({ time: bar.time, value: 1000 })));
    const scale = left.priceScale();
    const before = { ...scale.priceRange() };
    el.dispatch('pointerdown', pointer('down', 20, 220));
    el.dispatch('pointermove', pointer('move', 20, 260));
    el.dispatch('pointerup', pointer('up', 20, 260));
    expect(scale.autoScale).toBe(false);
    chart.resetScale();
    expect(scale.autoScale).toBe(true);
    expect(scale.priceRange()).toEqual(before);
  });
});

describe('preferred visible bar count', () => {
  it.each([0, 50])('waits for a visible container before fitting a %i-bar preference', (count) => {
    const { chart, series } = mount({ navigation: { defaultVisibleBars: count } }, false);
    chart.applySize(0, 0);
    series.setData(bars);
    chart.applySize(800, 600);
    expect(chart.getVisibleLogicalRange()).toEqual({ from: count === 0 ? -1 : 149, to: 203 });
  });

  it('starts at the latest requested bars, retains history and uses the same view on reset', () => {
    const { chart, series } = mount({ navigation: { defaultVisibleBars: 50 } });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    expect(series.getData()).toHaveLength(200);
    chart.setVisibleLogicalRange({ from: 20, to: 60 });
    chart.resetScale();
    expect(chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    chart.fitContent();
    expect(chart.getVisibleLogicalRange()).toEqual({ from: -1, to: 203 });
  });

  it('applies a settings edit immediately and restores the preference before new data arrives', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'navigation.defaultVisibleBars': 75, 'navigation.mousePan': 'horizontal' });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: 124, to: 203 });
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    const next = mount({}, false);
    next.chart.restoreState(saved);
    next.series.setData(bars);
    expect(next.chart.getVisibleLogicalRange()).toEqual({ from: 124, to: 203 });
    expect(readChartSettings(next.chart)['navigation.mousePan']).toBe('horizontal');
    next.chart.setVisibleLogicalRange({ from: 20, to: 80 });
    next.chart.resetScale();
    expect(next.chart.getVisibleLogicalRange()).toEqual({ from: 124, to: 203 });
  });

  it('uses available bars for short histories and ignores invalid saved preferences', () => {
    const { chart } = mount({ navigation: { defaultVisibleBars: 500 } });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: -1, to: 203 });
    chart.setNavigationOptions({ defaultVisibleBars: 50 });
    chart.restoreState({ version: 1, navigation: { defaultVisibleBars: 'wrong', mousePan: 'wrong' } });
    expect(chart.navigationOptions()).toEqual({ defaultVisibleBars: 50, mousePan: 'both', panEnabled: true, zoomEnabled: true });
    chart.setNavigationOptions({ defaultVisibleBars: Number.NaN });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    applyChartSettings(chart, { 'navigation.defaultVisibleBars': 0 });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: -1, to: 203 });
  });
});

describe('preferred bar spacing', () => {
  it('uses the same candle density across desktop and mobile widths', () => {
    for (const width of [390, 1200]) {
      const { chart, series } = mount({ navigation: { defaultBarSpacing: 8 } }, false);
      chart.applySize(width, 600);
      series.setData(bars);
      expect(chart.timeScale.barSpacing).toBe(8);
      expect(chart.getVisibleLogicalRange().to).toBe(203);
      expect(series.getData()).toHaveLength(200);
    }
  });

  it('retains zoom on resize and restores density on reset after a data change', () => {
    const { chart, series } = mount({ navigation: { defaultBarSpacing: 8 } });
    chart.timeScale.setBarSpacing(12);
    chart.applySize(390, 600);
    expect(chart.timeScale.barSpacing).toBe(12);
    series.setData(bars.slice(0, 100));
    chart.resetScale();
    expect(chart.timeScale.barSpacing).toBe(8);
    expect(chart.getVisibleLogicalRange().to).toBe(103);
    chart.fitContent();
    expect(chart.getVisibleLogicalRange()).toEqual({ from: -1, to: 103 });
    chart.resetScale();
    expect(chart.timeScale.barSpacing).toBe(8);
  });

  it('waits for measurement and saves density independently of the current zoom', () => {
    const { chart, series } = mount({ navigation: { defaultBarSpacing: 9 } }, false);
    chart.applySize(0, 0);
    series.setData(bars);
    chart.applySize(390, 600);
    expect(chart.timeScale.barSpacing).toBe(9);
    chart.setVisibleLogicalRange({ from: 100, to: 130 });
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    const next = mount({}, false);
    next.chart.restoreState(saved);
    next.series.setData(bars);
    next.chart.resetScale();
    expect(next.chart.timeScale.barSpacing).toBe(9);
    expect(next.chart.getVisibleLogicalRange().to).toBe(203);
  });

  it('switches between density, bar count and fitting all history through settings', () => {
    const { chart } = mount();
    applyChartSettings(chart, { 'navigation.defaultBarSpacing': 8 });
    expect(chart.timeScale.barSpacing).toBe(8);
    expect(readChartSettings(chart)['navigation.defaultBarSpacing']).toBe(8);
    const saved = readChartSettings(chart);
    applyChartSettings(chart, { 'navigation.defaultVisibleBars': 50 });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: 149, to: 203 });
    expect(readChartSettings(chart)['navigation.defaultBarSpacing']).toBe(0);
    applyChartSettings(chart, saved);
    expect(chart.timeScale.barSpacing).toBe(8);
    applyChartSettings(chart, { 'navigation.defaultBarSpacing': 0 });
    expect(chart.getVisibleLogicalRange()).toEqual({ from: -1, to: 203 });
  });

  it('ignores invalid persisted density and applies the configured zoom limits', () => {
    const { chart } = mount({ navigation: { defaultBarSpacing: 8 }, timeScale: { maxBarSpacing: 20 } });
    for (const value of [-1, NaN, Infinity, 'wrong']) {
      chart.restoreState({ version: 1, navigation: { defaultBarSpacing: value } });
      chart.resetScale();
      expect(chart.timeScale.barSpacing).toBe(8);
    }
    chart.setNavigationOptions({ defaultBarSpacing: 25 });
    expect(chart.timeScale.barSpacing).toBe(20);
  });
});
