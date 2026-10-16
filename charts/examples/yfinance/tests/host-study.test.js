// Study policies in the reference host: the protected VWAP the host places,
// and the chips, the settings dialog and the menus drawing a protected study
// as protected rather than offering controls the chart would refuse.
import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
import '../../../src/indicators/index.ts';
import { Chart, ChartObjects } from '../../../src/index.ts';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { HOST_STUDY_POLICY, addHostStudy, hostStudy, keepHostStudy, removeHostStudy, studyAllows } from '../src/host-study.js';

const charts = [];
afterEach(() => charts.splice(0).forEach((chart) => chart.destroy()));
function mount() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 0 },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 40 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 100,
  })));
  charts.push(chart);
  return chart;
}

describe('the protected VWAP', () => {
  it('is added once, withholds the user actions and goes only with the host row', () => {
    const chart = mount();
    const study = addHostStudy(chart);
    expect(addHostStudy(chart)).toBe(study);
    expect(study.policy()).toEqual(HOST_STUDY_POLICY);
    expect(HOST_STUDY_POLICY).toEqual({ removable: false, configurable: false, movable: false });
    for (const flag of ['removable', 'configurable', 'movable']) expect(studyAllows(study, flag)).toBe(false);
    expect(studyAllows(study, 'listed')).toBe(true);
    const objects = new ChartObjects(chart);
    const row = objects.get('indicator:' + study.id);
    expect(row.capabilities).toMatchObject({ remove: false, settings: false, move: false, reorder: false, place: false, visibility: true });
    expect(chart.removeIndicator(study.id)).toBe(false);
    expect(study.setSettings({ anchor: 'week' })).toBe(false);
    // Saved with the layout, so a reload brings it back protected.
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    const next = mount();
    expect(next.restoreState(saved).applied).toBe(true);
    expect(hostStudy(next)?.policy()).toEqual(HOST_STUDY_POLICY);
    expect(removeHostStudy(chart)).toBe(true);
    expect(hostStudy(chart)).toBeUndefined();
    expect(removeHostStudy(chart)).toBe(false);
    objects.destroy();
  });

  it('stays on the chart through a layout the user applies, once, and a chart without it stays without', () => {
    const chart = mount();
    const other = mount();
    other.addIndicator('sma');
    other.addIndicator('rsi');
    // A layout from elsewhere, holding two ordinary studies and none of the host's.
    const layout = JSON.parse(JSON.stringify(other.getState()));
    expect(keepHostStudy(chart, layout)).toBe(layout);
    const study = addHostStudy(chart);
    const applied = keepHostStudy(chart, layout);
    expect(chart.restoreState(applied).applied).toBe(true);
    expect(chart.indicators().map((item) => item.indicatorId)).toEqual(['sma', 'rsi', 'vwap']);
    expect(hostStudy(chart)?.id).toBe(study.id);
    expect(hostStudy(chart)?.policy()).toEqual(HOST_STUDY_POLICY);
    // The host's own save already holds it: nothing is added.
    const own = JSON.parse(JSON.stringify(chart.getState()));
    expect(keepHostStudy(chart, own)).toBe(own);
    expect(chart.restoreState(keepHostStudy(chart, own)).applied).toBe(true);
    expect(chart.indicators().filter((item) => item.indicatorId === 'vwap')).toHaveLength(1);
    // An id a study in the layout already has goes to that study; the host's takes a new one.
    const clash = { ...layout, indicators: [...layout.indicators, { indicatorId: 'ema', settings: {}, paneIndex: 0, instanceId: study.id }] };
    const merged = keepHostStudy(chart, clash);
    expect(chart.restoreState(merged).applied).toBe(true);
    expect(chart.indicators().map((item) => item.indicatorId)).toEqual(['sma', 'rsi', 'ema', 'vwap']);
    expect(hostStudy(chart)?.policy()).toEqual(HOST_STUDY_POLICY);
  });

  it('treats an engine without policies as allowing everything', () => {
    expect(studyAllows({}, 'removable')).toBe(true);
    expect(studyAllows(undefined, 'configurable')).toBe(true);
  });
});
