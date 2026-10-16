import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { SMA } from '../src/indicators/trend';
import type { AlertSource, AlertsDocument } from '../src/alerts/types';
import { fakeDocument } from './helpers/fake-dom';

registerIndicator(SMA);
const charts: Chart[] = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

function mount(): Chart {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 500);
  chart.addSeries('line').setData([1, 3, 5, 7].map((value, index) => ({ time: index * 60, value })));
  return chart;
}

function alertDocument(kind: 'indicator' | 'drawing', instanceId: string): AlertsDocument {
  const source: AlertSource = kind === 'indicator'
    ? { kind, instanceId, plotKey: 'ma', value: 4 }
    : { kind, drawingId: 'retained-level', input: { instanceId, plotKey: 'ma' } };
  return { version: 1, alerts: [{
    id: 'retained-alert', source, condition: 'greaterThan', policy: 'onTouch', repeat: 'everyTime',
    state: 'armed', title: 'Retained alert', cooldownSeconds: 0, scope: {},
  }] };
}

describe('anonymous restore identity reservation', () => {
  it.each(['indicator', 'drawing'] as const)('reserves an incoming %s alert anchor before restore-start callbacks', kind => {
    const chart = mount();
    const previous = chart.addIndicator('sma');
    const nextId = `sma-${Number(previous.id.slice(4)) + 1}`;
    previous.remove();
    let callbackId: string | undefined;
    chart.on('state:restore:start', () => {
      callbackId = chart.addIndicator('sma', { length: 1 }).id;
    });
    const alerts = alertDocument(kind, nextId);

    expect(chart.restoreState({ version: 1, alerts }).applied).toBe(true);
    expect(callbackId).toBeDefined();
    expect(callbackId).not.toBe(nextId);
    expect(chart.alertState()).toEqual(alerts);
    expect(chart.indicators().map(indicator => indicator.id)).toEqual([callbackId]);
  });

  it('reserves an incoming missing dependency before restore-start callbacks', () => {
    const chart = mount();
    const previous = chart.addIndicator('sma');
    const nextId = `sma-${Number(previous.id.slice(4)) + 1}`;
    previous.remove();
    let callbackId: string | undefined;
    chart.on('state:restore:start', () => {
      callbackId = chart.addIndicator('sma', { length: 1 }).id;
    });
    const source = { kind: 'indicator', instanceId: nextId, plotKey: 'ma' };

    expect(chart.restoreState({ version: 1, indicators: [
      { indicatorId: 'sma', instanceId: 'restored-consumer', settings: { length: 2, source }, paneIndex: 0 },
    ] }).applied).toBe(true);
    expect(callbackId).toBeDefined();
    expect(callbackId).not.toBe(nextId);
    const [consumer] = chart.indicators();
    expect(consumer.id).toBe('restored-consumer');
    expect(consumer.settings().source).toEqual(source);
    expect(consumer.values().ma).toEqual([null, null, null, null]);
    expect(consumer.dataStatus()?.state).toBe('error');
  });

  it.each(['runtime', 'restore'] as const)('keeps later native additions away from %s alert anchors', mode => {
    const chart = mount();
    const previous = chart.addIndicator('sma');
    const nextId = `sma-${Number(previous.id.slice(4)) + 1}`;
    previous.remove();
    const alerts = alertDocument('indicator', nextId);
    if (mode === 'runtime') chart.setAlertState(alerts);
    else expect(chart.restoreState({ version: 1, alerts }).applied).toBe(true);
    expect(chart.addIndicator('sma').id).not.toBe(nextId);
  });

  it.each(['indicator', 'drawing'] as const)('does not acquire an incoming %s alert anchor after chart reload', kind => {
    const original = mount();
    expect(original.restoreState({ version: 1, indicators: [
      { indicatorId: 'sma', settings: { length: 2 }, paneIndex: 0 },
    ] }).applied).toBe(true);
    const retired = original.indicators()[0];
    const oldId = retired.id;
    original.setAlertState(alertDocument(kind, oldId));
    retired.remove();
    const state = original.getState();
    state.indicators = [{ indicatorId: 'sma', settings: { length: 1 }, paneIndex: 0 }];
    const restored = mount();
    expect(restored.restoreState(JSON.parse(JSON.stringify(state))).applied).toBe(true);
    expect(restored.indicators()[0].id).not.toBe(oldId);
    expect(restored.alertState()).toEqual(alertDocument(kind, oldId));
  });

  it.each(['indicator', 'drawing'] as const)('reserves a current %s anchor when the incoming state omits alerts', kind => {
    const original = mount();
    original.restoreState({ version: 1, indicators: [
      { indicatorId: 'sma', settings: { length: 2 }, paneIndex: 0 },
    ] });
    const oldId = original.indicators()[0].id;
    const restored = mount();
    restored.setAlertState(alertDocument(kind, oldId));
    expect(restored.restoreState({ version: 1, indicators: [
      { indicatorId: 'sma', settings: { length: 1 }, paneIndex: 0 },
    ] }).applied).toBe(true);
    expect(restored.indicators()[0].id).not.toBe(oldId);
  });
});
