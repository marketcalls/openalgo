import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { AlertController } from '../src/alerts/controller';
import type { Alert, AlertTriggeredPayload } from '../src/alerts/types';
import type { Bar } from '../src/model/bar';
import { DrawingController } from '../src/draw/controller';
import '../src/draw/index';
import '../src/indicators/index';
import { parseIndicatorTemplate, parseWorkspaceDocument, WorkspaceDocumentError } from '../src/workspace/documents';
import { fakeDocument } from './helpers/fake-dom';
import { workspaceFixture } from './helpers/workspace-fixture';

const cleanup: (() => void)[] = [];
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close, low: close, close });
afterEach(() => { for (const dispose of cleanup.splice(0).reverse()) dispose(); });

function chartOnly(initial = [bar(60, 10), bar(120, 10), bar(180, 10), bar(240, 10), bar(300, 10)]) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  cleanup.push(() => chart.destroy());
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'ONE', exchange: 'TEST', interval: '1m' });
  const series = chart.addSeries('candlestick');
  series.setData(initial);
  const fired: AlertTriggeredPayload[] = [];
  chart.on('alert:triggered', event => fired.push(event as AlertTriggeredPayload));
  return { chart, series, fired };
}

function setup(now = () => 1000, initial?: Bar[]) {
  const host = chartOnly(initial);
  const drawings = new DrawingController(host.chart);
  cleanup.push(() => drawings.destroy());
  const alerts = new AlertController(host.chart, { drawings, now });
  cleanup.push(() => alerts.destroy());
  return { ...host, drawings, alerts };
}

const saved = (patch: Partial<Alert> = {}): Alert => ({
  id: 'saved', source: { kind: 'price', price: 13 }, condition: 'crossingUp',
  policy: 'onBarClose', repeat: 'once', state: 'armed', title: 'Saved alert', cooldownSeconds: 0,
  scope: { symbol: 'ONE', exchange: 'TEST', interval: '1m' }, ...patch,
});

describe('alert documents and chart restoration', () => {
  it('round-trips detached payloads and lifecycle through chart state', () => {
    const a = setup();
    a.alerts.add({ id: 'level', source: { kind: 'price', price: 13 }, title: 'Breakout',
      payload: { route: 'desktop', labels: ['watch'], enabled: false, count: 0 } });
    const state = a.chart.getState();
    expect(state.alerts).toMatchObject({ version: 1, alerts: [{ id: 'level', policy: 'onBarClose', state: 'armed' }] });
    expect(state).toEqual(JSON.parse(JSON.stringify(state)));
    const b = setup();
    expect(b.chart.restoreState(JSON.parse(JSON.stringify(state))).applied).toBe(true);
    expect(b.alerts.list()[0]).toMatchObject({ id: 'level', title: 'Breakout', payload: { count: 0, enabled: false, labels: ['watch'] } });
    (state.alerts!.alerts[0].payload as { labels: string[] }).labels.push('changed');
    expect(a.alerts.toJSON().alerts[0].payload).toMatchObject({ labels: ['watch'] });
    expect(b.fired).toEqual([]);
  });

  it('keeps repeated study identities and restores drawings before validating alert anchors', () => {
    const a = setup();
    const slow = a.chart.addIndicator('ema', { length: 5 });
    const fast = a.chart.addIndicator('ema', { length: 1 });
    const line = a.drawings.add({ id: 'level-line', tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 300, price: 13 }] });
    a.alerts.add({ id: 'slow', source: { kind: 'indicator', instanceId: slow.id, plotKey: 'ma', value: 13 }, condition: 'crossingUp' });
    a.alerts.add({ id: 'fast', source: { kind: 'indicator', instanceId: fast.id, plotKey: 'ma', value: 13 }, condition: 'crossingUp' });
    a.alerts.add({ id: 'line', source: { kind: 'drawing', drawingId: line.id }, condition: 'crossingUp' });
    const state = JSON.parse(JSON.stringify(a.chart.getState()));
    const b = setup();
    const phases: string[] = [];
    b.chart.on('drawings:restore', () => phases.push('drawings'));
    b.chart.on('alerts:restore', () => phases.push('alerts'));
    b.chart.restoreState(state);
    expect(phases).toEqual(['drawings', 'alerts']);
    expect(b.chart.indicators().map(item => item.id)).toEqual([slow.id, fast.id]);
    expect(b.drawings.get('level-line')?.points[0].price).toBe(13);
    expect(b.alerts.list().map(item => item.id)).toEqual(['slow', 'fast', 'line']);
    expect(b.fired).toEqual([]);
    b.series.update(bar(300, 14));
    b.series.update(bar(360, 14));
    expect(b.fired.map(item => item.alertId)).toEqual(['fast', 'line']);
  });

  it('replaces alert state on repeated restores and clears it for a legacy chart', () => {
    const { chart, alerts, drawings, fired } = setup();
    alerts.add({ id: 'old', source: { kind: 'price', price: 1 } });
    drawings.add({ id: 'old-line', tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 300, price: 1 }] });
    const state = { version: 1, alerts: { version: 1, alerts: [saved()] } };
    chart.restoreState(state);
    chart.restoreState(state);
    expect(alerts.list().map(item => item.id)).toEqual(['saved']);
    expect(drawings.get('old-line')).toBeUndefined();
    chart.restoreState({ version: 1 });
    expect(alerts.list()).toEqual([]);
    expect(fired).toEqual([]);
  });

  it('migrates a bare alert list with omitted policy to confirmed-bar evaluation', () => {
    const { policy: _policy, ...legacy } = saved();
    const { alerts, series, fired } = setup();
    alerts.fromJSON([legacy]);
    expect(alerts.list()[0].policy).toBe('onBarClose');
    series.update({ ...bar(300, 10), high: 14 });
    expect(fired).toEqual([]);
    series.update(bar(300, 10));
    series.update(bar(360, 10));
    expect(fired).toEqual([]);
  });

  it('round-trips without controllers and evaluates only after explicit attachment', () => {
    const { chart, series, fired } = chartOnly();
    chart.restoreState({ version: 1, alerts: { version: 1, alerts: [saved()] } });
    series.update(bar(300, 14));
    series.update(bar(360, 14));
    expect(fired).toEqual([]);
    expect(chart.getState().alerts?.alerts[0].state).toBe('armed');
    const alerts = new AlertController(chart);
    cleanup.push(() => alerts.destroy());
    expect(alerts.list()[0].id).toBe('saved');
    expect(fired).toEqual([]);
    series.update(bar(360, 10));
    series.update(bar(420, 14));
    series.update(bar(480, 14));
    expect(fired.map(item => item.alertId)).toEqual(['saved']);
  });

  it('drops dangling drawing and plot anchors after restoration, with reasons', () => {
    const { chart, alerts, fired } = setup();
    const study = chart.addIndicator('ema', { length: 1 });
    const removed: { alert: Alert; reason: string }[] = [];
    chart.on('alert:removed', event => removed.push(event as typeof removed[number]));
    alerts.fromJSON({ version: 1, alerts: [
      saved({ id: 'missing-line', source: { kind: 'drawing', drawingId: 'absent' } }),
      saved({ id: 'missing-study', source: { kind: 'indicator', instanceId: 'absent', plotKey: 'ma', value: 13 } }),
      saved({ id: 'missing-plot', source: { kind: 'indicator', instanceId: study.id, plotKey: 'absent', value: 13 } }),
      saved(),
    ] });
    expect(alerts.list().map(item => item.id)).toEqual(['saved']);
    expect(removed.map(item => [item.alert.id, item.reason])).toEqual([
      ['missing-line', 'drawing-missing'], ['missing-study', 'indicator-missing'], ['missing-plot', 'plot-missing'],
    ]);
    expect(fired).toEqual([]);
  });

  it.each([
    ['version', { version: 2, alerts: [saved()] }],
    ['duplicate ids', { version: 1, alerts: [saved(), saved()] }],
    ['empty id', { version: 1, alerts: [saved({ id: '' })] }],
    ['infinite price', { version: 1, alerts: [saved({ source: { kind: 'price', price: Infinity } })] }],
    ['backwards range', { version: 1, alerts: [saved({ condition: 'enteringRange', source: { kind: 'price', price: 20, upperPrice: 10 } })] }],
    ['invalid cooldown', { version: 1, alerts: [saved({ cooldownSeconds: -1 })] }],
    ['invalid policy', { version: 1, alerts: [{ ...saved(), policy: 'sometimes' }] }],
    ['invalid scope', { version: 1, alerts: [{ ...saved(), scope: { symbol: 12 } }] }],
  ])('rejects %s atomically in both controller and chart restoration', (_name, input) => {
    const { chart, alerts } = setup();
    chart.addIndicator('ema', { length: 5 });
    alerts.add({ id: 'keep', source: { kind: 'price', price: 13 } });
    const before = chart.getState();
    expect(() => alerts.fromJSON(input)).toThrow();
    expect(chart.getState()).toEqual(before);
    expect(chart.restoreState({ version: 1, grid: { vertLines: false, horzLines: false }, indicators: [], alerts: input }).applied).toBe(false);
    expect(chart.getState()).toEqual(before);
  });

  it('refuses lossy payload persistence while keeping opaque runtime payloads usable', () => {
    const { chart, alerts } = setup();
    const payload = { deliver: () => 1 };
    const record = alerts.add({ source: { kind: 'price', price: 13 }, payload });
    expect(alerts.list()[0].payload).toBe(payload);
    expect(() => alerts.toJSON()).toThrow(/JSON|payload/i);
    expect(() => chart.getState()).toThrow(/JSON|payload/i);
    alerts.update(record.id, { payload: { channel: 'desktop' } });
    expect(alerts.toJSON().alerts[0].payload).toEqual({ channel: 'desktop' });
  });

  it('rejects cyclic, non-JSON and accessor payloads without evaluating accessors', () => {
    const { alerts } = setup();
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    let reads = 0;
    const accessor = { get dangerous() { reads++; return 'value'; } };
    const symbol = { [Symbol('hidden')]: 1 };
    for (const payload of [cyclic, accessor, symbol, new Date(), 1n, { missing: undefined }, [undefined], [NaN]]) {
      expect(() => alerts.fromJSON({ version: 1, alerts: [saved({ payload })] })).toThrow(/JSON|cycle/i);
    }
    expect(reads).toBe(0);
    expect(alerts.list()).toEqual([]);
  });

  it('rejects missing array elements and never invokes record accessors', () => {
    const { alerts } = setup();
    let reads = 0;
    const list: unknown[] = [];
    Object.defineProperty(list, '0', { enumerable: true, get: () => { reads++; return saved(); } });
    expect(() => alerts.fromJSON({ version: 1, alerts: list })).toThrow(/JSON|data/i);
    expect(reads).toBe(0);
    expect(() => alerts.fromJSON({ version: 1, alerts: new Array(1) })).toThrow(/JSON|data/i);
    expect(alerts.list()).toEqual([]);
  });

  it('treats explicit null configuration as invalid rather than substituting a default', () => {
    const { alerts } = setup();
    for (const field of ['condition', 'policy', 'repeat', 'state', 'title', 'cooldownSeconds', 'scope']) {
      expect(() => alerts.fromJSON({ version: 1, alerts: [{ ...saved(), [field]: null }] })).toThrow();
    }
    expect(alerts.list()).toEqual([]);
  });

  it('rejects a workspace payload that would otherwise lose private routing fields', () => {
    const fixture = workspaceFixture();
    const pane = fixture.panes[0];
    expect(() => parseWorkspaceDocument({ ...fixture, panes: [{ ...pane,
      chart: { version: 1, alerts: { version: 1, alerts: [saved({ payload: { accountId: 'routing-account' } })] } },
    }], activePaneId: 'p0', layout: { rows: 1, columns: 1, slots: [fixture.layout.slots[0]] } })).toThrow(/payload/i);
  });

  it('does not let extra scope fields bypass JSON-safe persistence', () => {
    const { alerts } = setup();
    expect(() => alerts.fromJSON({ version: 1, alerts: [{ ...saved(), scope: { symbol: 'ONE', callback: () => 1 } }] })).toThrow(/JSON/i);
  });

  it('rejects opaque workspace payload properties that JSON cannot retain', () => {
    const fixture = workspaceFixture();
    const hidden = Object.defineProperty({}, 'route', { value: 'hidden' });
    const extraArray = Object.assign([1], { route: 'hidden' });
    for (const payload of [{ [Symbol('route')]: 'hidden' }, hidden, extraArray]) {
      expect(() => parseWorkspaceDocument({ ...fixture, panes: [{ ...fixture.panes[0],
        chart: { version: 1, alerts: { version: 1, alerts: [saved({ payload })] } },
      }], activePaneId: 'p0', layout: { rows: 1, columns: 1, slots: [fixture.layout.slots[0]] } })).toThrow(/payload/i);
    }
  });

  it('preserves consumed intrabar matches, including a cooldown-suppressed bar', () => {
    let now = 1000;
    const a = setup(() => now);
    a.alerts.add({ id: 'repeat', source: { kind: 'price', price: 13 }, condition: 'greaterThan',
      policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 100 });
    a.series.update(bar(300, 14));
    now = 1010;
    a.series.update(bar(360, 15));
    expect(a.fired).toHaveLength(1);
    const document = a.alerts.toJSON();
    now = 1200;
    const b = setup(() => now, [bar(60, 10), bar(120, 10), bar(180, 10), bar(240, 10), bar(300, 10)]);
    b.alerts.fromJSON(document);
    b.series.update(bar(300, 16));
    b.series.update(bar(360, 17));
    expect(b.fired).toEqual([]);
    b.series.update(bar(420, 18));
    expect(b.fired.map(item => item.time)).toEqual([420]);
  });

  it('keeps closed-bar watermarks when restored history moves backwards', () => {
    const a = setup();
    a.alerts.add({ source: { kind: 'price', price: 13 }, condition: 'greaterThan', repeat: 'everyTime' });
    a.series.update(bar(360, 10));
    const b = setup();
    b.alerts.fromJSON(a.alerts.toJSON());
    b.series.update(bar(300, 14));
    b.series.update(bar(360, 14));
    expect(b.fired).toEqual([]);
    b.series.update(bar(420, 14));
    expect(b.fired.map(item => item.time)).toEqual([360]);
  });

  it('preserves once-state and cooldown, and expires elapsed armed alerts on restore', () => {
    const a = setup();
    a.alerts.fromJSON({ version: 1, alerts: [
      saved({ id: 'once', state: 'triggered', lastTriggeredAt: 990, lastTriggeredTime: 240 }),
      saved({ id: 'cooldown', condition: 'greaterThan', repeat: 'everyTime', cooldownSeconds: 100,
        lastTriggeredAt: 990, lastTriggeredTime: 240 }),
      saved({ id: 'expired', expiresAt: 999 }), saved({ id: 'disabled', state: 'disabled' }),
    ] });
    expect(a.alerts.list().map(item => item.state)).toEqual(['triggered', 'armed', 'expired', 'disabled']);
    a.series.update(bar(300, 14));
    a.series.update(bar(360, 14));
    expect(a.fired).toEqual([]);
    expect(a.alerts.toJSON().alerts[1].lastTriggeredAt).toBe(990);
  });

  it('rejects duplicate restored study identities before changing chart state', () => {
    const { chart } = setup();
    const study = chart.addIndicator('ema', { length: 1 });
    const before = chart.getState();
    const bad = { ...before, indicators: [
      { indicatorId: 'ema', instanceId: study.id, settings: { length: 2 }, paneIndex: 0 },
      { indicatorId: 'ema', instanceId: study.id, settings: { length: 5 }, paneIndex: 0 },
    ] };
    expect(chart.restoreState(bad).applied).toBe(false);
    expect(chart.getState()).toEqual(before);
  });

  it('retains a real once trigger across a JSON workspace reload without delivering it again', () => {
    const a = setup();
    a.alerts.add({ id: 'once', source: { kind: 'price', price: 13 }, condition: 'crossingUp' });
    a.series.update(bar(300, 14));
    a.series.update(bar(360, 14));
    expect(a.fired).toHaveLength(1);
    const b = setup();
    b.chart.restoreState(JSON.parse(JSON.stringify(a.chart.getState())));
    expect(b.alerts.list()[0]).toMatchObject({ id: 'once', state: 'triggered', lastTriggeredAt: 1000, lastTriggeredTime: 300 });
    b.series.update(bar(300, 14));
    b.series.update(bar(360, 14));
    expect(b.fired).toEqual([]);
  });

  it('keeps two years of loaded candles silent until the first live append', () => {
    const history = Array.from({ length: 730 }, (_, i) => ({ ...bar((i + 1) * 86400, 14), open: 10 }));
    const { chart, alerts, series, fired } = setup(() => 1000, history);
    alerts.fromJSON({ version: 1, alerts: [saved({ source: { kind: 'barCondition', id: 'bullish' }, condition: 'matches', repeat: 'everyTime' })] });
    chart.restoreState(JSON.parse(JSON.stringify(chart.getState())));
    series.setData(history);
    series.prependData([{ ...bar(0, 14), open: 10 }]);
    expect(fired).toEqual([]);
    series.update({ ...bar(731 * 86400, 14), open: 10 });
    expect(fired.map(item => item.time)).toEqual([730 * 86400]);
  });

  it('avoids generated-id collisions with a restored identity that appears later in the list', () => {
    const { chart } = setup();
    const probe = chart.addIndicator('ema');
    const next = Number(probe.id.slice(probe.id.lastIndexOf('-') + 1)) + 1;
    const retained = `ema-${next}`;
    chart.restoreState({ version: 1, indicators: [
      { indicatorId: 'ema', settings: { length: 3 }, paneIndex: 0 },
      { indicatorId: 'ema', instanceId: retained, settings: { length: 5 }, paneIndex: 0 },
    ] });
    const ids = chart.indicators().map(item => item.id);
    expect(ids[1]).toBe(retained);
    expect(ids[0]).not.toBe(retained);
    expect(new Set([...ids, chart.addIndicator('ema').id]).size).toBe(3);
  });

  it('retains alerts and study identities through workspace parsing but strips identities from templates', () => {
    const { chart, alerts } = setup();
    const study = chart.addIndicator('ema', { length: 1 });
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 13 } });
    const fixture = workspaceFixture();
    const workspace = parseWorkspaceDocument({ ...fixture, panes: [{ ...fixture.panes[0], chart: chart.getState() }],
      activePaneId: 'p0', layout: { rows: 1, columns: 1, slots: [fixture.layout.slots[0]] } });
    expect(workspace.panes[0].chart.indicators?.[0].instanceId).toBe(study.id);
    expect(workspace.panes[0].chart.alerts?.alerts[0].source).toMatchObject({ instanceId: study.id });
    const template = parseIndicatorTemplate({ kind: 'indicator-template', version: 1, id: 'studies', name: 'Studies',
      createdAt: 1, updatedAt: 1, indicators: chart.getState().indicators });
    expect(template.indicators[0].instanceId).toBeUndefined();
    chart.restoreState({ version: 1, indicators: template.indicators });
    expect(chart.indicators()[0].id).not.toBe(study.id);
    expect(alerts.list()).toEqual([]);
  });

  it('reports invalid embedded alerts through the workspace document error contract', () => {
    const fixture = workspaceFixture();
    expect(() => parseWorkspaceDocument({ ...fixture, panes: [{ ...fixture.panes[0],
      chart: { version: 1, alerts: { version: 99, alerts: [] } },
    }], activePaneId: 'p0', layout: { rows: 1, columns: 1, slots: [fixture.layout.slots[0]] } })).toThrow(WorkspaceDocumentError);
  });
});
