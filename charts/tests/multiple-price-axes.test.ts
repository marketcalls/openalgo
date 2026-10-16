import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

function fixture() {
  vi.stubGlobal('window', {});
  const doc = fakeDocument(), container = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(container, { document: doc, shortcuts: false, branding: false, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  chart.applySize(800, 600);
  const primary = chart.addSeries('candlestick');
  const second = chart.addSeries('line', { priceScaleId: 'overlay:second' });
  const bars = Array.from({ length: 100 }, (_, i) => ({ time: 1700000000 + i * 60,
    open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i }));
  primary.setData(bars);
  second.setData(bars.map(bar => ({ ...bar, open: bar.open * 10, high: bar.high * 10, low: bar.low * 10, close: bar.close * 10 })));
  chart.setVisibleLogicalRange({ from: 0, to: 30 });
  return { chart, primary, second, container };
}

afterEach(() => vi.unstubAllGlobals());

describe('multiple visible price axes', () => {
  it('preserves a vacant scale when reordering a surviving peer changes its placement', () => {
    const { chart, second } = fixture();
    second.remove();
    chart.addSeries('line', { priceScaleId: 'overlay:later' });
    chart.setPriceAxisPlacement(0, 'overlay:later', 'hidden', 0);
    const before = chart.priceAxisPlacement(0, 'overlay:second');
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    chart.restoreState(saved);
    expect(chart.priceAxisPlacement(0, 'overlay:second')).toEqual(before);
    expect(chart.priceAxisPlacement(0, 'overlay:later')).toEqual({ side: 'hidden', order: 0 });
    chart.destroy();
  });

  it.each(['overlay:second', 'overlay:later'] as const)('retains reordered hidden placements after removing %s', removed => {
    const { chart, second } = fixture();
    const later = chart.addSeries('line', { priceScaleId: 'overlay:later' });
    chart.setPriceAxisPlacement(0, 'overlay:second', 'hidden', 1);
    (removed === 'overlay:second' ? second : later).remove();
    const placements = ['overlay:second', 'overlay:later'].map(id => chart.priceAxisPlacement(0, id as 'overlay:second' | 'overlay:later'));
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    chart.restoreState(saved);
    expect(['overlay:second', 'overlay:later'].map(id => chart.priceAxisPlacement(0, id as 'overlay:second' | 'overlay:later'))).toEqual(placements);
    expect(chart.priceAxisLayout().map(slot => slot.scaleId)).toEqual(['right']);
    chart.destroy();
  });

  it('rejects invalid public placement requests before allocating or changing scales', () => {
    const { chart } = fixture(), before = chart.getState();
    for (const paneIndex of [-1, 0.5, NaN, 4, '0', 'constructor'] as number[]) {
      expect(chart.setPriceAxisPlacement(paneIndex, 'overlay:new', 'right')).toBe(false);
      expect(chart.priceAxisPlacement(paneIndex, 'right')).toBeNull();
      expect(chart.priceAxisLayout(paneIndex)).toEqual([]);
    }
    expect(chart.setPriceAxisPlacement(0, 'overlay:new', 'right', -1)).toBe(false);
    expect(chart.setPriceAxisPlacement(0, 'overlay:new', 'hidden')).toBe(false);
    expect(chart.getState()).toEqual(before);
    chart.destroy();
    expect(chart.setPriceAxisPlacement(0, 'right', 'left')).toBe(false);
    expect(chart.priceAxisPlacement(0, 'right')).toBeNull();
    expect(chart.priceAxisLayout()).toEqual([]);
  });

  it('does not reserve a default right column for an unused secondary pane', () => {
    const { chart } = fixture();
    chart.setPriceAxisPlacement(0, 'right', 'left');
    const secondary = chart.addSeries('line', { paneIndex: 1, priceScaleId: 'left' });
    secondary.remove();
    expect(chart.timeScale.width).toBe(744);
    expect(chart.priceAxisLayout(1)).toEqual([]);
    chart.destroy();
  });

  it('keeps the legacy move destination after an earlier placement override', () => {
    const { chart, primary } = fixture(), scale = primary.priceScale();
    chart.setPriceAxisPlacement(0, 'left', 'right');
    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(true);
    expect(primary.priceScale()).toBe(scale);
    expect(chart.priceAxisLayout()).toEqual([{ scaleId: 'left', side: 'left', order: 0, x: 0, width: 56 }]);
    chart.destroy();
  });

  it('restores autofit to every visible column while retaining hidden-scale policy', () => {
    const { chart, primary, second } = fixture();
    chart.setPriceAxisPlacement(0, 'overlay:second', 'right');
    const hidden = chart.addSeries('line', { priceScaleId: 'overlay:hidden' });
    hidden.priceScale().setAutoScale(false);
    chart.setPriceAxisAutoFit(0, 'right', false);
    chart.setPriceAxisAutoFit(0, 'overlay:second', false);
    chart.setAutoScale(true);
    expect([primary.priceScale().autoScale, second.priceScale().autoScale]).toEqual([true, true]);
    expect(hidden.priceScale().autoScale).toBe(false);
    chart.destroy();
  });

  it('allocates independent columns without changing source identities or manual state', () => {
    const { chart, second } = fixture(), scale = second.priceScale();
    scale.setPriceFormatter(value => `B:${value}`);
    scale.setAutoScale(false);
    scale.setPriceRange({ min: 900, max: 2000 });
    const range = scale.priceRange();
    // Optional invocation makes the old renderer fail on its actual one-column width.
    chart.setPriceAxisPlacement?.(0, 'overlay:second', 'right');
    expect(chart.timeScale.width).toBe(688);
    expect(chart.priceAxisLayout()).toEqual([
      { scaleId: 'right', side: 'right', order: 0, x: 688, width: 56 },
      { scaleId: 'overlay:second', side: 'right', order: 1, x: 744, width: 56 },
    ]);
    expect(second.priceScale()).toBe(scale);
    expect(scale.priceRange()).toEqual(range);
    expect(scale.format(100)).toBe('B:100');
    expect(chart.panes()[0].series()[1].scaleId).toBe('overlay:second');
    chart.destroy();
  });

  it('moves and reorders stable identities on an occupied side', () => {
    const { chart, primary, second } = fixture();
    const scales = [primary.priceScale(), second.priceScale()];
    expect(chart.setPriceAxisPlacement(0, 'overlay:second', 'left')).toBe(true);
    expect(chart.setPriceAxisPlacement(0, 'right', 'left', 0)).toBe(true);
    expect(chart.priceAxisLayout()).toEqual([
      { scaleId: 'right', side: 'left', order: 0, x: 56, width: 56 },
      { scaleId: 'overlay:second', side: 'left', order: 1, x: 0, width: 56 },
    ]);
    expect([primary.priceScale(), second.priceScale()]).toEqual(scales);
    expect(chart.setPriceAxisPlacement(0, 'right', 'left', 1)).toBe(true);
    expect(chart.priceAxisLayout().map(slot => slot.scaleId)).toEqual(['overlay:second', 'right']);
    expect(chart.setPriceAxisPlacement(0, 'right', 'left')).toBe(false);
    chart.destroy();
  });

  it('routes the outer column wheel and drag to its own scale', () => {
    const { chart, primary, second, container } = fixture();
    chart.setPriceAxisPlacement(0, 'overlay:second', 'right');
    const primaryBefore = primary.priceScale().priceRange(), secondBefore = second.priceScale().priceRange();
    container.dispatch('wheel', { clientX: 775, clientY: 220, deltaX: 0, deltaY: 80, deltaMode: 0, preventDefault() {} });
    expect(primary.priceScale().priceRange()).toEqual(primaryBefore);
    expect(second.priceScale().priceRange()).not.toEqual(secondBefore);
    const wheeled = second.priceScale().priceRange();
    container.dispatch('pointerdown', pointer('down', 775, 220));
    container.dispatch('pointermove', pointer('move', 775, 270));
    container.dispatch('pointerup', pointer('up', 775, 270));
    expect(primary.priceScale().priceRange()).toEqual(primaryBefore);
    expect(second.priceScale().priceRange()).not.toEqual(wheeled);
    chart.destroy();
  });

  it('restores placements and resets omitted metadata to defaults', () => {
    const { chart } = fixture();
    chart.setPriceAxisPlacement(0, 'overlay:second', 'left');
    chart.setPriceAxisPlacement(0, 'right', 'left', 0);
    const saved = chart.getState(), expected = chart.priceAxisLayout();
    chart.setPriceAxisPlacement(0, 'right', 'right');
    expect(chart.restoreState(saved).applied).toBe(true);
    expect(chart.priceAxisLayout()).toEqual(expected);
    for (const pane of saved.panes ?? []) {
      delete pane.priceScale.placement;
      for (const scale of Object.values(pane.scales ?? {})) if (scale) delete scale.placement;
    }
    chart.restoreState(saved);
    expect(chart.priceAxisLayout().map(slot => slot.scaleId)).toEqual(['right']);
    chart.destroy();
  });

  it('keeps plot coordinates aligned and ignores vacant outer columns', () => {
    const { chart, container, primary } = fixture();
    chart.addSeries('line', { paneIndex: 1, priceScaleId: 'overlay:lower' }).setData([
      { time: 1700000000, value: 10 }, { time: 1700000060, value: 11 },
    ]);
    chart.setPriceAxisPlacement(1, 'overlay:lower', 'right');
    chart.addSeries('line', { paneIndex: 1 }).setData([{ time: 1700000000, value: 100 }]);
    expect(chart.priceAxisLayout(0)).toEqual([{ scaleId: 'right', side: 'right', order: 0, x: 688, width: 56 }]);
    const before = primary.priceScale().priceRange(), viewport = chart.getVisibleLogicalRange();
    container.dispatch('wheel', { clientX: 775, clientY: 100, deltaY: 80, deltaX: 0, deltaMode: 0, preventDefault() {} });
    container.dispatch('pointerdown', pointer('down', 775, 100));
    container.dispatch('pointermove', pointer('move', 775, 150));
    container.dispatch('pointerup', pointer('up', 775, 150));
    expect(primary.priceScale().priceRange()).toEqual(before);
    expect(chart.getVisibleLogicalRange()).toEqual(viewport);
    const clicks: unknown[] = [];
    chart.on('click', event => clicks.push(event));
    chart.setPlacementMode(true);
    container.dispatch('pointerdown', pointer('down', 775, 100));
    container.dispatch('pointermove', pointer('move', 720, 140));
    container.dispatch('pointerup', pointer('up', 720, 140));
    expect(clicks).toEqual([]);
    chart.destroy();
  });

  it('compresses columns on narrow layouts and restores live geometry after export', () => {
    const { chart } = fixture();
    chart.setPriceAxisPlacement(0, 'overlay:second', 'right');
    const before = chart.priceAxisLayout();
    const svg = chart.exportSVG({ width: 90, height: 400 });
    expect(svg).not.toMatch(/NaN|Infinity/);
    expect(chart.priceAxisLayout()).toEqual(before);
    chart.applySize(90, 400);
    expect(chart.timeScale.width).toBe(30);
    expect(chart.priceAxisLayout().map(slot => [slot.x, slot.width])).toEqual([[30, 30], [60, 30]]);
    chart.destroy();
  });
});
