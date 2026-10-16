/**
 * Every control in the settings dialog must survive a save and a reload, not
 * just the twenty a hand-written patch happened to name. `chart-settings`
 * already asserts a round trip, but against a fixed list: a control added to
 * the schema later is captured by nothing and the suite stays green, which is
 * the same "declared, threaded, but not persisted" gap that generic liveness
 * checking exists to close on the render side.
 *
 * This walks the schema itself, so a new control is audited the moment it
 * appears.
 *
 * The restore includes the one step the engine deliberately leaves to the host:
 * series data belongs to the app, so `restoreState` reports the primary series
 * as a descriptor rather than recreating it, and re-applying `descriptor.style`
 * is the documented flow. Without that step the twelve `symbol.*` keys read as
 * lost when they are in fact handed back by design.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import {
  chartSettingsSchema, readChartSettings, applyChartSettings,
  type ChartSettingsValue, type ChartSettingsValues, type ChartSettingsInput,
} from '../src/model/chart-settings';
import type { IndicatorInput } from '../src/model/indicator-registry';
import { PaneLegend } from '../src/primitives/pane-legend';
import type { Bar } from '../src/model/bar';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';

const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 100 + i };
});

function mount(withData = true): Chart {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  Object.assign(el, { clientWidth: 800, clientHeight: 600 });
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    shortcuts: false,
    timeNavigator: false,
  });
  chart.applySize(800, 600);
  const s = chart.addSeries('candlestick');
  if (withData) s.setData(BARS);
  // The status-line switches need a legend on the chart to have anything to
  // read back; without one the whole Readout tab would drop out of the schema.
  chart.addPrimitive(new PaneLegend({ id: 'symbol', title: 'ACME', row: 0, actions: [] }), 0);
  return chart;
}

/** A colourPair is one row over two or three keys: the expansion a host renders. */
function valueInputs(input: ChartSettingsInput): IndicatorInput[] {
  if (input.type !== 'colorPair') return [input];
  const p = input;
  const out: IndicatorInput[] = [];
  if (p.enabled !== undefined) {
    out.push({ key: p.enabled.key, type: 'boolean', label: p.label, default: p.enabled.default });
  }
  out.push({ key: p.up.key, type: 'color', label: p.up.label, default: p.up.default });
  out.push({ key: p.down.key, type: 'color', label: p.down.label, default: p.down.default });
  return out;
}

/** A value the control does not currently hold, so a write is observable. */
function mutate(input: IndicatorInput, current: ChartSettingsValue): ChartSettingsValue {
  switch (input.type) {
    case 'text': return current === 'Research' ? '' : 'Research';
    case 'boolean': return current !== true;
    case 'color': return current === '#abcdef' ? '#123456' : '#abcdef';
    case 'number': {
      const min = input.min ?? 0;
      const step = input.step ?? 1;
      return current === min ? min + step : min;
    }
    case 'select': {
      const other = input.options.find((o) => o.value !== current);
      return other === undefined ? current : other.value;
    }
    default: return current;
  }
}

describe('every settings control survives a save and a reload', () => {
  beforeEach(() => vi.stubGlobal('window', {}));
  afterEach(() => vi.unstubAllGlobals());

  it('carries the whole schema through JSON into a fresh chart', () => {
    const inputs = chartSettingsSchema(mount()).flatMap((t) => t.inputs.flatMap(valueInputs));
    // A floor, so a schema that failed to build cannot pass this vacuously.
    expect(inputs.length).toBeGreaterThan(40);

    const defaults = readChartSettings(mount());
    const patch: ChartSettingsValues = {};
    for (const i of inputs) patch[i.key] = mutate(i, defaults[i.key]);

    const saved = mount();
    applyChartSettings(saved, patch);
    const wrote = readChartSettings(saved);
    const state = JSON.parse(JSON.stringify(saved.getState())) as unknown;

    const fresh = mount(false);
    const report = fresh.restoreState(state);
    expect(report.applied).toBe(true);
    const descriptor = report.series.find((s) => s.paneIndex === 0);
    expect(descriptor).toBeDefined();
    fresh.primarySeries()?.applyOptions(descriptor?.style ?? {});
    fresh.primarySeries()?.setData(BARS);

    const after = readChartSettings(fresh);
    const lost = inputs
      .filter((i) => after[i.key] !== wrote[i.key])
      .map((i) => `${i.key}: saved ${String(wrote[i.key])}, restored ${String(after[i.key])}`);
    expect(lost).toEqual([]);
  });

  it('mutates every control away from its default, so the check is not vacuous', () => {
    // If `mutate` returned the current value for some control, that key would
    // "survive" trivially and the test above would report it safe while proving
    // nothing about it.
    const inputs = chartSettingsSchema(mount()).flatMap((t) => t.inputs.flatMap(valueInputs));
    const defaults = readChartSettings(mount());
    const unmoved = inputs.filter((i) => mutate(i, defaults[i.key]) === defaults[i.key]);
    expect(unmoved.map((i) => i.key)).toEqual([]);
  });
});
