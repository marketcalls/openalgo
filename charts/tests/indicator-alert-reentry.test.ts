import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import type { Bar } from '../src/model/bar';
import { registerIndicator, type IndicatorAlertContext, type IndicatorAlertPayload, type IndicatorAlertSpec, type IndicatorAttachContext, type IndicatorDescriptor } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';

const bar = (time: number, close = 1): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
const charts: Chart[] = [];
const replays: ReplayController[] = [];
let sequence = 0;
afterEach(() => {
  replays.splice(0).forEach(replay => replay.stop());
  charts.splice(0).forEach(chart => chart.destroy());
});

function mount(alerts: readonly IndicatorAlertSpec[], calc: IndicatorDescriptor['calc'] = bars => ({ v: bars.map(item => item.close) })) {
  const document = fakeDocument();
  const pending = new Map<number, () => void>();
  let handle = 0;
  const clock = { now: 121 };
  const chart = new Chart(document.createElement('div'), {
    document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
    axisChrome: { clock: () => clock.now },
    raf: {
      schedule: callback => { pending.set(++handle, callback); return handle; },
      cancel: key => { pending.delete(key); },
    },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'ALERTS', interval: '1m' });
  const source = chart.addSeries('candlestick');
  source.setData([bar(0, 1), bar(60, 2), bar(120, 3)], { confirmation: 'forming' });
  const events: IndicatorAlertPayload[] = [];
  chart.on('indicator:alert', payload => events.push(payload as IndicatorAlertPayload));
  const id = `alert-reentry-${sequence++}`;
  let attachment!: IndicatorAttachContext;
  registerIndicator({
    id, name: 'Alert reentry', placement: 'onchart',
    inputs: [{ key: 'threshold', type: 'number', label: 'Threshold', default: 0 }],
    plots: [{ key: 'v', type: 'line', title: 'Value' }], alerts,
    calc,
    attach: context => { attachment = context; },
  });
  const indicator = chart.addIndicator(id);
  indicator.values();
  return { chart, source, indicator, events, id, clock, refresh: () => attachment.requestRecompute() };
}

function spec(id: string, frequency: NonNullable<IndicatorAlertSpec['frequency']>, patch: Partial<IndicatorAlertSpec> = {}): IndicatorAlertSpec {
  return { id, title: id, frequency, when: () => true, ...patch };
}

const eventKeys = (events: readonly IndicatorAlertPayload[]) => events.map(event => `${event.alertId}:${event.time}`);

describe('native alert callback reentry', () => {
  it.each([false, true])('retains a nested calculation failure when an old predicate returns (throws: %s)', throws => {
    const nestedError = new Error('Invalid nested settings');
    const staleError = new Error('Obsolete alert predicate');
    let mutate = (): void => {};
    const h = mount([spec('signal', 'everyUpdate', { when: () => { mutate(); return true; } })], (bars, settings) => {
      if (Number(settings.threshold) < 0) throw nestedError;
      return { v: bars.map(item => item.close) };
    });
    mutate = () => {
      mutate = () => {};
      h.indicator.setSettings({ threshold: -1 });
      if (throws) throw staleError;
    };
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    expect(h.indicator.dataStatus()).toEqual({ state: 'error', error: nestedError });
  });

  it('ignores an obsolete calculation error after settings reentry completed a newer calculation', () => {
    let mutate = (): void => {};
    const h = mount([spec('signal', 'everyUpdate')], (bars, settings) => {
      mutate();
      return { v: bars.map(item => item.close + Number(settings.threshold)) };
    });
    mutate = () => {
      mutate = () => {};
      h.indicator.setSettings({ threshold: 10 });
      throw new Error('Obsolete calculation');
    };
    h.source.update(bar(180, 4));
    expect(h.indicator.values().v).toEqual([11, 12, 13, 14]);
    expect(h.indicator.dataStatus()?.state).not.toBe('error');
    expect(h.events).toEqual([]);
  });

  it('retains newer calculation output when an old calculation returns after settings reentry', () => {
    let mutate = (): void => {};
    const h = mount([spec('signal', 'everyUpdate')], (bars, settings) => {
      mutate();
      return { v: bars.map(item => item.close + Number(settings.threshold)) };
    });
    mutate = () => {
      mutate = () => {};
      h.indicator.setSettings({ threshold: 10 });
    };
    h.source.update(bar(180, 4));
    expect(h.indicator.values().v).toEqual([11, 12, 13, 14]);
    expect(h.indicator.settings().threshold).toBe(10);
    expect(h.events).toEqual([]);
    h.source.update(bar(180, 5));
    expect(h.indicator.values().v).toEqual([11, 12, 13, 15]);
    expect(eventKeys(h.events)).toEqual(['signal:180']);
  });

  it('preserves a callback source write when a nested values read cannot flush yet', () => {
    let mutate = (): boolean => true;
    const h = mount([spec('signal', 'everyUpdate', { when: () => mutate() })]);
    mutate = () => {
      mutate = () => true;
      h.source.update(bar(240, 9));
      h.indicator.values();
      return false;
    };
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    expect(h.indicator.values().v).toEqual([1, 2, 3, 4, 9]);
    expect(eventKeys(h.events)).toEqual(['signal:240']);
  });

  it.each(['predicate', 'message'] as const)('abandons an old source candidate and retains the next flush after %s reentry', stage => {
    let mutate = (): void => {};
    const h = mount([spec('signal', 'oncePerBar', {
      when: () => { if (stage === 'predicate') mutate(); return true; },
      message: () => { if (stage === 'message') mutate(); return 'Signal'; },
    })]);
    mutate = () => {
      mutate = () => {};
      h.source.update(bar(240, 9));
      h.indicator.values();
    };
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    expect(h.indicator.values().v).toEqual([1, 2, 3, 4, 9]);
    expect(eventKeys(h.events)).toEqual(['signal:240']);
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['signal:240']);
  });

  it.each(['predicate', 'message'] as const)('does not spend once after %s changes settings', stage => {
    let mutate = (): void => {};
    const h = mount([spec('signal', 'once', {
      when: context => {
        if (stage === 'predicate') mutate();
        return context.bars[context.index].close > Number(context.settings.threshold);
      },
      message: () => { if (stage === 'message') mutate(); return 'Signal'; },
    })]);
    mutate = () => { mutate = () => {}; h.indicator.setSettings({ threshold: 10 }); };
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    h.source.update(bar(180, 11));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['signal:180']);
    h.source.update(bar(240, 12));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['signal:180']);
  });

  it.each(['predicate', 'message'] as const)('does not dispatch after removal inside the %s', stage => {
    let remove = (): void => {};
    const h = mount([
      spec('first', 'everyUpdate', {
        when: () => { if (stage === 'predicate') remove(); return true; },
        message: () => { if (stage === 'message') remove(); return 'Signal'; },
      }),
      spec('second', 'everyUpdate'),
    ]);
    remove = () => h.indicator.remove();
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    expect(h.chart.indicators()).toHaveLength(0);
  });

  it('commits an emitted candidate and abandons old siblings when its listener changes source', () => {
    const h = mount([spec('first', 'oncePerBar'), spec('second', 'oncePerBar')]);
    let changed = false;
    h.chart.on('indicator:alert', () => {
      if (changed) return;
      changed = true;
      h.source.update(bar(240, 9));
      h.indicator.values();
    });
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['first:180']);
    expect(h.indicator.values().v).toEqual([1, 2, 3, 4, 9]);
    expect(eventKeys(h.events)).toEqual(['first:180', 'first:240', 'second:240']);
    h.indicator.values();
    expect(h.events).toHaveLength(3);
  });

  it.each(['settings', 'removal'] as const)('stops sibling dispatch after a listener changes %s', change => {
    const h = mount([spec('first', 'everyUpdate'), spec('second', 'everyUpdate')]);
    let changed = false;
    h.chart.on('indicator:alert', () => {
      if (changed) return;
      changed = true;
      if (change === 'settings') h.indicator.setSettings({ threshold: 10 });
      else h.indicator.remove();
    });
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['first:180']);
    if (change === 'settings') {
      h.source.update(bar(180, 11));
      h.indicator.values();
      expect(eventKeys(h.events)).toEqual(['first:180', 'first:180', 'second:180']);
    }
  });
});

describe('native alert errors and historical boundaries', () => {
  it.each(['predicate', 'message'] as const)('retains successful sibling checkpoints after a %s error', stage => {
    const error = new Error(`Broken ${stage}`);
    let broken = true;
    let attempts = 0;
    const attempt = (): void => { attempts++; if (broken) throw error; };
    const h = mount([
      spec('broken', 'once', {
        when: () => { if (stage === 'predicate') attempt(); return true; },
        message: () => { if (stage === 'message') attempt(); return 'Recovered'; },
      }),
      spec('healthy', 'oncePerBar'),
    ]);
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['healthy:180']);
    expect(h.indicator.dataStatus()).toEqual({ state: 'error', error });
    h.indicator.values(); h.indicator.values(); h.refresh();
    expect(attempts).toBe(1);
    expect(eventKeys(h.events)).toEqual(['healthy:180']);
    broken = false;
    h.source.update(bar(180, 5));
    h.indicator.values();
    expect(attempts).toBe(2);
    expect(eventKeys(h.events)).toEqual(['healthy:180', 'broken:180']);
  });

  it('reports the first callback error after evaluating independent siblings', () => {
    const first = new Error('First predicate failure');
    const second = new Error('Second message failure');
    const calls: string[] = [];
    const h = mount([
      spec('first', 'everyUpdate', { when: () => { calls.push('first'); throw first; } }),
      spec('second', 'everyUpdate', { message: () => { calls.push('second'); throw second; } }),
      spec('healthy', 'everyUpdate', { when: () => { calls.push('healthy'); return true; } }),
    ]);
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(calls).toEqual(['first', 'second', 'healthy']);
    expect(eventKeys(h.events)).toEqual(['healthy:180']);
    expect(h.indicator.dataStatus()).toEqual({ state: 'error', error: first });
    h.indicator.values();
    expect(calls).toHaveLength(3);
  });

  it('seeds a historical correction plus append batch before the next live revision', () => {
    const policies = ['everyUpdate', 'oncePerBar', 'onBarClose', 'once'] as const;
    const h = mount(policies.map(policy => spec(policy, policy)));
    h.source.update(bar(60, 20));
    h.source.update(bar(180, 4));
    h.indicator.values();
    expect(h.events).toEqual([]);
    h.source.update(bar(180, 5), { confirmation: 'confirmed' });
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(policies.map(policy => `${policy}:180`));
    h.indicator.values(); h.refresh(); h.indicator.setSettings({ threshold: 1 });
    expect(h.events).toHaveLength(4);
  });

  it('does not consume once from settings or asynchronous refresh while source data is dirty', () => {
    const h = mount([spec('signal', 'once')]);
    h.source.update(bar(180, 4));
    h.indicator.setSettings({ threshold: 1 });
    h.refresh(); h.indicator.values();
    expect(h.events).toEqual([]);
    h.source.update(bar(180, 5));
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['signal:180']);
  });

  it('limits close predicate and message snapshots to each newly completed observation', () => {
    const inspected: { phase: string; times: number[]; values: (number | null)[]; index: number }[] = [];
    const inspect = (phase: string, context: IndicatorAlertContext): void => {
      inspected.push({ phase, times: context.bars.map(item => item.time), values: [...context.values.v], index: context.index });
    };
    const h = mount([spec('close', 'onBarClose', {
      when: context => { inspect('predicate', context); return true; },
      message: context => { inspect('message', context); return 'Closed'; },
    })]);
    h.source.update(bar(180, 4)); h.source.update(bar(240, 5), { confirmation: 'forming' });
    h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['close:120', 'close:180']);
    expect(inspected).toEqual([
      { phase: 'predicate', times: [0, 60, 120], values: [1, 2, 3], index: 2 },
      { phase: 'message', times: [0, 60, 120], values: [1, 2, 3], index: 2 },
      { phase: 'predicate', times: [0, 60, 120, 180], values: [1, 2, 3, 4], index: 3 },
      { phase: 'message', times: [0, 60, 120, 180], values: [1, 2, 3, 4], index: 3 },
    ]);
  });

  it('keeps the once latch through reset, source replacement and replay until instance removal', () => {
    const h = mount([spec('once', 'once')]);
    h.source.update(bar(180, 4)); h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['once:180']);
    h.source.setData([bar(0, 10), bar(60, 20), bar(120, 30), bar(180, 40)]);
    h.indicator.values();
    h.source.update(bar(240, 50)); h.indicator.values();
    h.source.remove();
    const replacement = h.chart.addSeries('candlestick');
    replacement.setData([bar(600, 10), bar(660, 20)]);
    h.indicator.values();
    replacement.update(bar(720, 30)); h.indicator.values();
    const replay = new ReplayController(h.chart, { series: replacement, startIndex: 0 });
    replays.push(replay);
    h.indicator.values(); replay.step(); h.indicator.values(); replay.stop(); h.indicator.values();
    replacement.update(bar(780, 40)); h.indicator.values();
    expect(eventKeys(h.events)).toEqual(['once:180']);
    h.indicator.remove();
    const recreated = h.chart.addIndicator(h.id);
    replacement.update(bar(840, 50)); recreated.values();
    expect(eventKeys(h.events)).toEqual(['once:180', 'once:840']);
    expect(h.events[0].instanceId).not.toBe(h.events[1].instanceId);
  });
});
