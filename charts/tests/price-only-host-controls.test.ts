import { describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { applyChartSettings, chartSettingsSchema, readChartSettings } from '../src/model/chart-settings';
import { parseWorkspaceDocument } from '../src/workspace/index';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';
import type { WidgetContext } from '../src/widget/context';
import type { ContextMenuEvent } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { workspaceFixture } from './helpers/workspace-fixture';

describe('primary price fitting host controls', () => {
  it('exposes a reversible settings choice without switching a manual scale to autofit', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), { document, shortcuts: false, raf: { schedule: () => 0 } });
    try {
      chart.addSeries('line');
      chart.setAutoScale(false);
      const control = chartSettingsSchema(chart).flatMap(tab => tab.inputs).find(input => input.key === 'scales.priceOnly');
      expect(control).toMatchObject({ type: 'boolean', default: false });
      const before = readChartSettings(chart);
      applyChartSettings(chart, { 'scales.priceOnly': true });
      expect(chart.priceOnlyAutoScale()).toBe(true);
      expect(chart.panes()[0].priceScale.autoScale).toBe(false);
      applyChartSettings(chart, before);
      expect(chart.priceOnlyAutoScale()).toBe(false);
    } finally { chart.destroy(); }
  });

  it.each([true, false])('retains each chart preference in portable workspaces (%s)', value => {
    const source = workspaceFixture();
    const input = { ...source, panes: source.panes.map((pane, index) => ({ ...pane,
      chart: { ...pane.chart, priceOnlyAutoScale: index === 0 ? value : !value },
    })) };
    expect(parseWorkspaceDocument(input).panes.map(pane => pane.chart.priceOnlyAutoScale)).toEqual([value, !value]);
  });

  it.each([null, 0, 'true', [], {}].map(value => ({ value })))('refuses a malformed persisted preference (%j)', ({ value }) => {
    const source = workspaceFixture();
    const input = { ...source, panes: [{ ...source.panes[0], chart: { ...source.panes[0].chart, priceOnlyAutoScale: value } }, source.panes[1]] };
    expect(() => parseWorkspaceDocument(input)).toThrow();
  });

  it('offers the axis action only on the live primary scale and rejects a stale menu target', () => {
    const selected = {}, other = {};
    let primary = selected, on = false;
    const chart = {
      primarySeries: () => ({ priceScale: () => primary }),
      panes: () => [{ scaleFor: () => selected }],
      priceAxisState: () => ({ active: true, scaled: false, mode: 'linear', autoFit: true }),
      priceAxisPlacement: () => null,
      priceOnlyAutoScale: () => on,
      setPriceOnlyAutoScale: vi.fn((value: boolean) => { on = value; }),
    };
    const context = { chart } as unknown as WidgetContext;
    const event: ContextMenuEvent = { paneIndex: 0, point: { x: 10, y: 10 }, price: null, time: null, index: null,
      preventDefault: () => {}, target: { kind: 'price-scale', id: null, side: 'right', scaleId: 'overlay:price' } };
    const action = () => contextMenuEntries(context, event).find(entry => !entry.kind && entry.id === 'axis-price-only') as MenuItem | undefined;
    const first = action();
    expect(first).toMatchObject({ label: 'Fit primary prices only', mark: 'check', on: false });
    first!.run?.();
    expect(chart.setPriceOnlyAutoScale).toHaveBeenLastCalledWith(true);
    expect(action()?.on).toBe(true);
    primary = other;
    expect(action()).toBeUndefined();
    first!.run?.();
    expect(chart.setPriceOnlyAutoScale).toHaveBeenCalledTimes(1);
  });
});
