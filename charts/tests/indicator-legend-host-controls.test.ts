import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { applyChartSettings, chartSettingsSchema, readChartSettings } from '../src/model/chart-settings';
import { parseWorkspaceDocument } from '../src/workspace/index';
import { fakeDocument } from './helpers/fake-dom';
import { workspaceFixture } from './helpers/workspace-fixture';

describe('indicator legend preference in hosts', () => {
  it('offers a reversible display preference without changing existing readout options', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), { document, shortcuts: false, raf: { schedule: () => 0 } });
    try {
      chart.setStatusLineOptions({ title: false, chartValues: true, lastValueLabel: false });
      const options = chart.statusLineOptions();
      const before = readChartSettings(chart);
      const control = chartSettingsSchema(chart).flatMap(tab => tab.inputs).find(input => input.key === 'statusLine.indicatorsCollapsed');
      expect(control).toMatchObject({ type: 'boolean', default: false });
      applyChartSettings(chart, { 'statusLine.indicatorsCollapsed': true });
      expect(chart.indicatorLegendCollapsed()).toBe(true);
      expect(chart.statusLineOptions()).toEqual(options);
      applyChartSettings(chart, before);
      expect(chart.indicatorLegendCollapsed()).toBe(false);
    } finally { chart.destroy(); }
  });

  it.each([true, false])('retains independent chart choices in portable workspaces (%s)', value => {
    const source = workspaceFixture();
    const input = { ...source, panes: source.panes.map((pane, index) => ({ ...pane,
      chart: { ...pane.chart, indicatorLegendCollapsed: index === 0 ? value : !value },
    })) };
    expect(parseWorkspaceDocument(input).panes.map(pane => pane.chart.indicatorLegendCollapsed)).toEqual([value, !value]);
  });

  it.each([null, 0, 'true', [], {}].map(value => ({ value })))('refuses malformed persisted choices (%j)', ({ value }) => {
    const source = workspaceFixture();
    const input = { ...source, panes: [{ ...source.panes[0], chart: { ...source.panes[0].chart, indicatorLegendCollapsed: value } }, source.panes[1]] };
    expect(() => parseWorkspaceDocument(input)).toThrow();
  });
});
