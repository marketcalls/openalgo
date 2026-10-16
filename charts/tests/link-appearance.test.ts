import { describe, expect, it } from 'vitest';
import { LinkGroup } from '../src/link/group';
import type { LinkChart, LinkMemberOptions } from '../src/link/group';
import { DataLayer } from '../src/model/data-layer';
import { filterLinkAppearance } from '../src/link/appearance';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { applyChartSettings, readChartSettings } from '../src/model/chart-settings';
import { registeredChartTypes } from '../src/model/chart-type-registry';

function makeChart(type = 'candlestick'): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(), raf: { schedule: () => 0 }, pixelRatio: () => 1, shortcuts: false,
  });
  chart.applySize(800, 600);
  chart.addSeries(type as Parameters<Chart['addSeries']>[0]);
  return chart;
}

/**
 * Every chart setting appearance linking leaves out, with the reason. A key the
 * settings gain later fails the test below until it is linked or listed here,
 * so an omission can no longer pass for a decision.
 */
const NOT_LINKED: Readonly<Record<string, string>> = {
  'navigation.defaultBarSpacing': 'navigation is how this chart is moved, not how it looks',
  'navigation.defaultVisibleBars': 'navigation is how this chart is moved, not how it looks',
  'navigation.mousePan': 'navigation is how this chart is moved, not how it looks',
  'navigation.panEnabled': 'navigation is how this chart is moved, not how it looks',
  'navigation.zoomEnabled': 'navigation is how this chart is moved, not how it looks',
  'statusLine.indicatorsCollapsed': "a fold of this chart's own study rows, toggled on the chart itself; each chart has its own studies",
  'time.timezone': 'the zone buckets sessions and recomputes studies: data, not appearance',
  'trading.buyColor': 'trading state stays with each chart',
  'trading.longColor': 'trading state stays with each chart',
  'trading.orderColor': 'trading state stays with each chart',
  'trading.sellColor': 'trading state stays with each chart',
  'trading.shortColor': 'trading state stays with each chart',
  'trading.slColor': 'trading state stays with each chart',
  'trading.tpColor': 'trading state stays with each chart',
  'watermark.text': "names this chart's instrument",
};

function host() {
  const listeners = new Map<string, Set<(p: unknown) => void>>();
  const chart: LinkChart & { emit(event: string): void } = {
    on(event, cb) {
      const set = listeners.get(event) ?? new Set();
      set.add(cb); listeners.set(event, set);
      return () => { set.delete(cb); };
    },
    emit(event) { for (const cb of listeners.get(event) ?? []) cb(undefined); },
    panes: () => [{}], dataLayer: new DataLayer(),
    getVisibleLogicalRange: () => ({ from: 0, to: 1 }), setVisibleLogicalRange() {},
    addPrimitive() {}, removePrimitive() {},
  };
  let values = { 'canvas.grid.vertColor': '#123456', 'symbol.upColor': '#008800' } as Record<string, string | boolean | number>;
  let applies = 0;
  const appearance = {
    read: () => values,
    apply(next: Readonly<Record<string, string | boolean | number>>) {
      values = { ...values, ...next }; applies++; chart.emit('style:change');
    },
  };
  return { chart, appearance, values: () => values, applies: () => applies };
}

describe('appearance linking', () => {
  it('retains the existing readout visibility fields', () => {
    const values = Object.fromEntries(['logo', 'marketStatus', 'chartValues', 'barChange', 'lastDayChange', 'lastValueLabel']
      .map(key => [`statusLine.${key}`, false]));
    expect(filterLinkAppearance(values)).toEqual(values);
  });
  it('is opt-in and copies visual settings without echo or semantic state', () => {
    const a = host(); const b = host(); const c = host();
    const group = new LinkGroup();
    for (const member of [a, b, c]) group.add(member.chart, { appearance: member.appearance } as LinkMemberOptions);
    Object.assign(a.values(), { 'canvas.grid.vertColor': '#abcdef', symbol: 'OTHER', interval: '1h',
      'trading.orderColor': '#ff0000', 'time.timezone': 'UTC', 'navigation.mousePan': 'horizontal',
      'events.visible': false, 'symbol.instrument': 'OTHER', 'watermark.text': 'SOURCE' });
    a.chart.emit('style:change');
    expect(b.values()['canvas.grid.vertColor']).toBe('#123456');
    group.setOptions({ appearance: true });
    a.chart.emit('style:change');
    expect(b.values()).toEqual({ 'canvas.grid.vertColor': '#abcdef', 'symbol.upColor': '#008800' });
    expect(c.values()).toEqual(b.values());
    expect([a.applies(), b.applies(), c.applies()]).toEqual([0, 1, 1]);
  });

  it('supports explicit notifications, fresh copies, removal and disposal', () => {
    const a = host(); const b = host();
    const group = new LinkGroup({ appearance: true });
    group.add(a.chart, { appearance: a.appearance });
    group.add(b.chart, { appearance: b.appearance });
    a.values()['symbol.upColor'] = '#112233';
    group.syncAppearance(a.chart);
    expect(b.values()['symbol.upColor']).toBe('#112233');
    b.values()['symbol.upColor'] = '#ffffff';
    expect(a.values()['symbol.upColor']).toBe('#112233');
    group.remove(b.chart); group.syncAppearance(a.chart);
    expect(b.applies()).toBe(1);
    group.destroy(); group.syncAppearance(a.chart);
    expect(b.applies()).toBe(1);
  });

  it('decides every chart setting: linked, or listed with the reason it is not', () => {
    const undecided = new Set<string>();
    const listed = new Set<string>();
    for (const type of registeredChartTypes()) {
      const chart = makeChart(type);
      const values = readChartSettings(chart);
      const linked = filterLinkAppearance(values);
      for (const key of Object.keys(values)) {
        if (key in linked) continue;
        if (key in NOT_LINKED) listed.add(key); else undecided.add(key);
      }
      chart.destroy();
    }
    expect([...undecided]).toEqual([]);
    // No stale entry: each listed key is a setting, and left out.
    expect(Object.keys(NOT_LINKED).filter(key => !listed.has(key))).toEqual([]);
  });

  it('links the price-only fit with the rest of the price scale', () => {
    const a = makeChart(); const b = makeChart();
    const group = new LinkGroup({ appearance: true });
    for (const chart of [a, b]) {
      group.add(chart, { appearance: { read: () => readChartSettings(chart), apply: values => applyChartSettings(chart, values) } });
    }
    applyChartSettings(a, { 'scales.priceOnly': true, 'scales.inverted': true });
    expect(b.priceOnlyAutoScale()).toBe(true);
    expect(b.priceScaleOptions().inverted).toBe(true);
    group.destroy();
    a.destroy(); b.destroy();
  });
});
