import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import type { Bar } from '../src/model/bar';
import { registerIndicator, type IndicatorCalcContext, type IndicatorValues } from '../src/model/indicator-registry';
import { registerInterval } from '../src/feed/intervals';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const releases: (() => void)[] = [];
let sequence = 0;
afterEach(() => {
  releases.splice(0).forEach(release => release());
  charts.splice(0).forEach(chart => chart.destroy());
});

const bar = (time: number, close = 1): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });

function mount(data = [bar(0, 1), bar(60, 2), bar(120, 3)], interval = '1m', now = 121, loadWithUpdates = false) {
  const document = fakeDocument();
  const clock = { now };
  const chart = new Chart(document.createElement('div'), {
    document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
    axisChrome: { clock: () => clock.now }, raf: { schedule: () => 1, cancel: () => {} },
  });
  chart.applySize(800, 600);
  charts.push(chart);
  chart.setDataContext({ symbol: 'SAMPLE', interval });
  const source = chart.addSeries('candlestick');
  if (loadWithUpdates) for (const item of data) source.update(item);
  else source.setData(data);
  const calls: { path: 'full' | 'tail'; ctx: IndicatorCalcContext }[] = [];
  const alerts: number[] = [];
  chart.on('indicator:alert', value => alerts.push((value as { time: number }).time));
  const calculate = (bars: readonly Bar[], from: number, previous?: IndicatorValues): number[] => {
    let total = from > 0 ? Number(previous?.total[from - 1] ?? 0) : 0;
    return bars.slice(from).map(value => total += value.close);
  };
  const id = `provenance-${sequence++}`;
  registerIndicator({
    id, name: 'Provenance', placement: 'onchart', inputs: [],
    plots: [{ key: 'total', title: 'Total', type: 'line' }],
    alerts: [{ id: 'all', title: 'All', when: () => true }],
    calc(bars, _settings, _store, ctx) {
      calls.push({ path: 'full', ctx: ctx! });
      return { total: calculate(bars, 0) };
    },
    calcTail(bars, _settings, from, previous, _store, ctx) {
      calls.push({ path: 'tail', ctx: ctx! });
      return { total: calculate(bars, from, previous) };
    },
  });
  const indicator = chart.addIndicator(id);
  const latest = () => { indicator.values(); return calls[calls.length - 1]; };
  return { chart, source, indicator, clock, calls, alerts, latest, id };
}

describe('source mutation provenance', () => {
  it.each([[false, 0], [true, 0], [true, 300]] as const)('rebuilds after primary replacement (extra update: %s, time offset: %s)', (extraUpdate, offset) => {
    const p = mount([bar(0, 1), bar(60, 2)], '1m', 121, true);
    expect(p.indicator.values().total).toEqual([1, 3]);
    const sourceId = p.latest().ctx.execution!.sourceId;
    p.source.remove();
    const replacement = p.chart.addSeries('candlestick');
    replacement.update(bar(offset, 10));
    replacement.update(bar(offset + 60, 20));
    if (extraUpdate) replacement.update(bar(offset + 60, 30));
    expect(p.indicator.values().total).toEqual([10, extraUpdate ? 40 : 30]);
    expect(p.latest().path).toBe('full');
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', change: 'initial' });
    const replacementId = p.latest().ctx.execution!.sourceId;
    expect(replacementId).not.toBe(sourceId);
    expect(p.latest().ctx.barState).toMatchObject({ isRealtime: false, isNew: false });
    expect(p.alerts).toEqual([]);
    replacement.update(bar(offset + 60, 50));
    expect(p.indicator.values().total).toEqual([10, 60]);
    expect(p.latest().path).toBe('tail');
    expect(p.latest().ctx.barState.isRealtime).toBe(true);
    expect(p.latest().ctx.execution!.sourceId).toBe(replacementId);
    replacement.update(bar(offset + 120, 5));
    expect(p.indicator.values().total).toEqual([10, 60, 65]);
    expect(p.alerts).toEqual([offset + 120]);
  });

  it('treats a matching historical reset as history after live activity', () => {
    const p = mount();
    p.source.update(bar(120, 4));
    expect(p.latest().ctx.barState.isRealtime).toBe(true);
    p.source.setData([bar(0, 10), bar(60, 20), bar(120, 30)]);
    expect(p.latest().path).toBe('full');
    expect(p.latest().ctx.barState).toMatchObject({ isRealtime: false, isNew: false });
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', change: 'reset' });
    expect(p.indicator.values().total).toEqual([10, 30, 60]);
  });

  it('rebuilds interior corrections even when count and endpoint times do not change', () => {
    const p = mount();
    p.source.update(bar(0, 10));
    expect(p.latest().path).toBe('full');
    expect(p.indicator.values().total).toEqual([10, 12, 15]);
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', change: 'correction' });
  });

  it('retains history invalidation across a coalesced correction and tail update', () => {
    const p = mount();
    const revision = p.latest().ctx.execution!.historyRevision;
    p.source.update(bar(0, 10));
    p.source.update(bar(120, 4));
    expect(p.latest().path).toBe('full');
    expect(p.indicator.values().total).toEqual([10, 12, 16]);
    expect(p.latest().ctx.execution!.historyRevision).toBeGreaterThan(revision);
  });

  it('classifies a source append independently from the shared axis', () => {
    const p = mount();
    p.chart.addSeries('line').setData([bar(180, 8), bar(240, 9)]);
    p.source.update(bar(180, 4));
    expect(p.latest().path).toBe('tail');
    expect(p.latest().ctx.barState).toMatchObject({ isNew: true, isRealtime: true });
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'live', change: 'append' });
    expect(p.alerts).toEqual([180]);
  });

  it('suppresses alerts on historical append, prepend and dataset replacement', () => {
    const p = mount();
    p.source.update(bar(180, 4), { source: 'history' });
    expect(p.latest().ctx.barState.isRealtime).toBe(false);
    p.source.prependData([bar(-60, 5)]);
    expect(p.latest().path).toBe('full');
    expect(p.latest().ctx.execution?.change).toBe('prepend');
    p.source.setData([...p.source.getData(), bar(240, 6)]);
    expect(p.latest().ctx.barState.isRealtime).toBe(false);
    expect(p.alerts).toEqual([]);
    p.source.update(bar(300, 7));
    p.latest();
    expect(p.alerts).toEqual([300]);
  });

  it('does not label settings refresh or initial attachment as a live update', () => {
    const p = mount();
    expect(p.latest().ctx.execution?.change).toBe('initial');
    p.source.update(bar(180, 4));
    p.latest();
    p.indicator.setSettings({ scale: 2 });
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', change: 'refresh' });
    expect(p.latest().ctx.barState.isRealtime).toBe(false);
    expect(p.alerts).toEqual([180]);
    p.source.update(bar(180, 8));
    p.latest();
    p.chart.addIndicator(p.id);
    expect(p.calls[p.calls.length - 1].ctx.execution).toMatchObject({ provenance: 'history', change: 'initial' });
    expect(p.calls[p.calls.length - 1].ctx.barState).toMatchObject({ isNew: false, isRealtime: false });
  });

  it('restores revised tail calculations rather than accumulating discarded values', () => {
    const p = mount();
    for (const value of [5, 8, 2, 7]) {
      p.source.update(bar(120, value));
      expect(p.indicator.values().total).toEqual([1, 3, 3 + value]);
      expect(p.latest().path).toBe('tail');
    }
  });

  it('marks the first live bar after empty history as new', () => {
    const p = mount([]);
    expect(p.latest().ctx.execution?.confirmationSource).toBe('empty');
    expect(p.latest().ctx.barState).toMatchObject({ isNew: false, isConfirmed: true, lastIndex: -1 });
    p.source.update(bar(0, 5));
    expect(p.latest().ctx.barState).toMatchObject({ isNew: true, isRealtime: true, lastIndex: 0 });
    expect(p.indicator.values().total).toEqual([5]);
  });

  it('reports a new tail after several appends coalesce into one calculation', () => {
    const p = mount();
    const revision = p.latest().ctx.execution!.revision;
    const count = p.calls.length;
    p.source.update(bar(180, 4));
    p.source.update(bar(240, 5));
    p.source.update(bar(240, 6));
    expect(p.calls).toHaveLength(count);
    expect(p.latest().ctx.barState).toMatchObject({ isNew: true, isRealtime: true });
    expect(p.latest().ctx.execution!.revision).toBe(revision + 3);
    expect(p.latest().path).toBe('full');
    expect(p.indicator.values().total).toEqual([1, 3, 6, 10, 16]);
  });
});

describe('provider confirmation', () => {
  it.each(['ticks', 'volume'] as const)('can settle %s bars without a clock-derived close', mode => {
    const code = `provenance-${mode}-${sequence++}`;
    releases.push(registerInterval({ code, bucketing: mode === 'ticks' ? { mode, count: 5 } : { mode, perBar: 50 } }));
    const p = mount([bar(0), bar(10)], code, 10000);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    const revision = p.latest().ctx.execution!.revision;
    p.source.update(bar(10), { confirmation: 'confirmed' });
    expect(p.latest().ctx.barState).toMatchObject({ isConfirmed: true, isNew: false });
    expect(p.latest().ctx.execution?.confirmationSource).toBe('provider');
    expect(p.latest().ctx.execution!.revision).toBeGreaterThan(revision);
    p.source.update(bar(20));
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    expect(p.latest().ctx.execution?.confirmationSource).toBe('unknown');
  });

  it('honors a forming override until the provider closes it or requests clock inference', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.update(bar(120, 3), { confirmation: 'forming' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.source.update(bar(120, 4));
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.source.update(bar(120, 4), { confirmation: 'auto' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
    expect(p.latest().ctx.execution?.confirmationSource).toBe('clock');
  });

  it('retains a tail override through prepend and clears it on replacement or instrument change', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.setData(p.source.getData(), { confirmation: 'forming' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.source.prependData([bar(-60)]);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.chart.setDataContext({ symbol: 'OTHER', interval: '1m' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
    expect(p.latest().path).toBe('full');
    p.source.update(bar(120), { confirmation: 'forming' });
    p.latest();
    p.source.setData(p.source.getData());
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
  });

  it('validates metadata before changing source data', () => {
    const p = mount();
    const original = p.source.getData();
    const revision = p.latest().ctx.execution!.revision;
    for (const options of [null, [], { confirmation: true }, { confirmation: 'closed' }, { source: 'replay' }]) {
      expect(() => p.source.update(bar(180), options as never)).toThrow(TypeError);
    }
    expect(p.source.getData()).toEqual(original);
    expect(p.latest().ctx.execution!.revision).toBe(revision);
    for (const options of [null, [], { confirmation: true }, { confirmation: 'closed' }]) {
      expect(() => p.source.setData([bar(500)], options as never)).toThrow(TypeError);
    }
    expect(p.source.getData()).toEqual(original);
    expect(p.latest().ctx.execution!.revision).toBe(revision);
  });

  it('keeps confirmation attached to the source tail rather than another series', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.update(bar(120), { confirmation: 'forming' });
    const revision = p.latest().ctx.execution!.revision;
    const secondary = p.chart.addSeries('line');
    secondary.setData([bar(120)], { confirmation: 'confirmed' });
    secondary.update(bar(180), { confirmation: 'confirmed' });
    expect(p.latest().ctx.execution!.revision).toBe(revision);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.source.update(bar(0, 2));
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.chart.setDataContext({ symbol: 'SAMPLE', interval: '5m' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
  });

  it('ignores confirmation attached to an older correction', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.update(bar(120), { confirmation: 'forming' });
    p.latest();
    p.source.update(bar(0, 5), { confirmation: 'confirmed' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', confirmationSource: 'provider' });
    p.clock.now = 121;
    p.source.update(bar(120), { confirmation: 'confirmed' });
    p.latest();
    p.source.update(bar(60, 8), { confirmation: 'auto' });
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
    expect(p.latest().ctx.execution?.confirmationSource).toBe('provider');
  });

  it('retains provider state when instrument and interval context are unchanged', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.update(bar(120), { confirmation: 'forming' });
    const revision = p.latest().ctx.execution!.revision;
    p.chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
    expect(p.latest().ctx.execution!.revision).toBe(revision);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    p.chart.setDataContext({ symbol: 'SAMPLE', interval: '1m', hasOpenInterest: true });
    expect(p.latest().ctx.execution!.revision).toBe(revision);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
  });
});

describe('replay provenance', () => {
  it('restores provider state when replay starts inside primary creation notification', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.remove();
    let replay: ReplayController | undefined;
    let entered = false;
    let publishedType: string | null = null;
    releases.push(p.chart.on('objects:change', () => {
      if (entered) return;
      const primary = p.chart.primarySeries();
      if (!primary) return;
      entered = true;
      publishedType = p.chart.seriesType(primary);
      primary.setData([bar(0, 1), bar(60, 2)], { confirmation: 'forming' });
      replay = new ReplayController(p.chart, { series: primary, startIndex: 0 });
    }));
    const replacement = p.chart.addSeries('candlestick');
    expect(replay).toBeDefined();
    releases.push(() => replay?.stop());
    replay!.stop();
    expect(replacement.getData()).toEqual([bar(0, 1), bar(60, 2)]);
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    expect(p.latest().ctx.execution?.confirmationSource).toBe('provider');
    expect(publishedType).toBe('candlestick');
  });

  it('keeps replay historical, suppresses alerts and restores the saved provider state', () => {
    const p = mount(undefined, '1m', 10000);
    p.source.update(bar(120), { confirmation: 'forming' });
    p.latest();
    const restored = p.source.getData();
    const replay = new ReplayController(p.chart, { startIndex: 0 });
    releases.push(() => replay.stop());
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'replay', confirmationSource: 'replay' });
    expect(p.latest().ctx.barState).toMatchObject({ isRealtime: false, isConfirmed: true });
    replay.step();
    expect(p.latest().path).toBe('full');
    expect(p.latest().ctx.barState.isRealtime).toBe(false);
    replay.stepBack();
    expect(p.indicator.values().total).toEqual([1]);
    replay.stop();
    expect(p.source.getData()).toEqual(restored);
    expect(p.latest().ctx.execution).toMatchObject({ provenance: 'history', confirmationSource: 'provider' });
    expect(p.latest().ctx.barState).toMatchObject({ isRealtime: false, isConfirmed: false });
    expect(p.alerts).toEqual([]);
  });

  it('uses replay formation rather than an old candle wall-clock close', () => {
    const p = mount([bar(0), bar(120)], '2m', 10000);
    const replay = new ReplayController(p.chart, {
      startIndex: 0, subBars: [bar(0), bar(60), bar(120), bar(180)],
    });
    releases.push(() => replay.stop());
    replay.step();
    expect(replay.state().subIndex).toBe(0);
    expect(p.latest().ctx.barState).toMatchObject({ isRealtime: false, isConfirmed: false });
    replay.pause();
    p.indicator.setSettings({ scale: 2 });
    expect(p.latest().ctx.execution?.provenance).toBe('replay');
    expect(p.latest().ctx.barState.isConfirmed).toBe(false);
    replay.step();
    expect(p.latest().ctx.barState.isConfirmed).toBe(true);
    expect(p.alerts).toEqual([]);
  });
});
