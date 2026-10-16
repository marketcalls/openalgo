import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerInterval } from '../src/feed/intervals';
import {
  registerIndicator, type IndicatorAlertFrequency, type IndicatorAlertPayload,
  type IndicatorAlertSpec, type IndicatorAttachContext,
} from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const releases: (() => void)[] = [];
let sequence = 0;
afterEach(() => {
  releases.splice(0).forEach(release => release());
  charts.splice(0).forEach(chart => chart.destroy());
});
const bar = (time: number, close = 5): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });

function mount(frequency: IndicatorAlertFrequency | undefined, options: {
  data?: Bar[]; now?: number; interval?: string; timezone?: string;
  spec?: Partial<IndicatorAlertSpec>;
} = {}) {
  const document = fakeDocument();
  const clock = { now: options.now ?? 121 };
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, timezone: options.timezone ?? 'Etc/UTC',
    axisChrome: { clock: () => clock.now }, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart); chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', interval: options.interval ?? '1m' });
  const source = chart.addSeries('candlestick');
  source.setData(options.data ?? [bar(0), bar(60), bar(120)]);
  const events: IndicatorAlertPayload[] = [];
  chart.on('indicator:alert', value => events.push(value as IndicatorAlertPayload));
  let attachment!: IndicatorAttachContext;
  const id = `alert-frequency-${sequence++}`;
  registerIndicator({
    id, name: 'Alert frequency', placement: 'pane', inputs: [],
    plots: [{ key: 'value', type: 'line', title: 'Value' }],
    calc: bars => ({ value: bars.map(item => item.close) }),
    attach: context => { attachment = context; },
    alerts: [{ id: 'match', title: 'Matched', frequency,
      when: context => context.values.value[context.index]! > 10, ...options.spec }],
  });
  const indicator = chart.addIndicator(id);
  return { chart, source, indicator, events, clock,
    refresh: () => attachment.requestRecompute(),
    update: (time: number, close: number) => { source.update(bar(time, close)); indicator.values(); },
  };
}

describe('native indicator alert frequency', () => {
  it('evaluates every observed live update while repeated reads and style edits remain silent', () => {
    const h = mount('everyUpdate');
    h.update(120, 12); h.update(120, 13);
    expect(h.events.map(event => event.time)).toEqual([120, 120]);
    h.indicator.values(); h.indicator.values(); h.indicator.setSettings({ 'value:color': '#dd3344' }); h.refresh();
    expect(h.events).toHaveLength(2);
    h.update(180, 14);
    expect(h.events.map(event => event.time)).toEqual([120, 120, 180]);
  });

  it('collapses ticks within a bar and judges each bar a coalesced pass appended', () => {
    const h = mount('everyUpdate');
    h.source.update(bar(120, 11)); h.source.update(bar(180, 12)); h.source.update(bar(240, 13));
    expect(h.events).toEqual([]);
    h.indicator.values();
    // The tick on 120 was superseded before any calculation; 180 and 240 are new bars.
    expect(h.events.map(event => [event.time, event.index])).toEqual([[180, 3], [240, 4]]);
    h.source.update(bar(240, 14)); h.source.update(bar(240, 15));
    h.indicator.values();
    expect(h.events.map(event => [event.time, event.index])).toEqual([[180, 3], [240, 4], [240, 4]]);
  });

  it('waits for the first matching update within each bar', () => {
    const h = mount('oncePerBar');
    h.update(120, 6); h.update(120, 12); h.update(120, 14);
    h.update(180, 7); h.update(180, 15); h.update(180, 16);
    expect(h.events.map(event => event.time)).toEqual([120, 180]);
  });

  it('delivers a once-only match on the current bar and preserves the latch through settings', () => {
    const h = mount('once');
    h.update(120, 12); h.indicator.setSettings({ 'value:color': '#33aa77' });
    h.update(120, 14); h.update(180, 16);
    expect(h.events.map(event => event.time)).toEqual([120]);
  });

  it('retains omitted-frequency evaluation on newly appended bars', () => {
    const h = mount(undefined);
    h.update(120, 12); h.update(180, 8); h.update(180, 14); h.update(240, 15);
    expect(h.events.map(event => event.time)).toEqual([240]);
  });

  it('does not announce a confirmed bar loaded as history', () => {
    const h = mount('onBarClose', { data: [bar(0, 12), bar(60, 13), bar(120, 14)], now: 1000 });
    h.update(120, 15);
    expect(h.events).toEqual([]);
    h.update(180, 16);
    expect(h.events.map(event => event.time)).toEqual([180]);
  });

  it('closes a forming tail only on a live execution after the clock boundary', () => {
    const h = mount('onBarClose');
    h.update(120, 12);
    h.clock.now = 180;
    h.indicator.setSettings({ 'value:color': '#dd3344' }); h.refresh(); h.indicator.values();
    expect(h.events).toEqual([]);
    h.update(120, 12); h.update(120, 13);
    expect(h.events.map(event => event.time)).toEqual([120]);
  });

  it('consumes a false close rather than retrying after a later revision', () => {
    const h = mount('onBarClose');
    h.clock.now = 180; h.update(120, 8); h.update(120, 20);
    expect(h.events).toEqual([]);
  });

  it('confirms count bars from the provider and from a newer opening', () => {
    const h = mount('onBarClose', { interval: '100t', now: 10000 });
    h.update(120, 12); expect(h.events).toEqual([]);
    h.source.update(bar(120, 12), { confirmation: 'confirmed' }); h.indicator.values();
    expect(h.events.map(event => event.time)).toEqual([120]);
    h.source.update(bar(180, 14), { confirmation: 'forming' }); h.indicator.values();
    h.source.update(bar(240, 15), { confirmation: 'forming' }); h.indicator.values();
    expect(h.events.map(event => event.time)).toEqual([120, 180]);
  });

  it('uses explicit forming confirmation ahead of an elapsed fixed-duration clock', () => {
    const h = mount('onBarClose');
    h.clock.now = 10000;
    h.source.update(bar(120, 12), { confirmation: 'forming' }); h.indicator.values();
    expect(h.events).toEqual([]);
    h.source.update(bar(120, 12), { confirmation: 'confirmed' }); h.indicator.values();
    expect(h.events.map(event => event.time)).toEqual([120]);
  });

  it('evaluates coalesced completed bars with matching bar and output prefixes', () => {
    const seen: number[][] = [];
    const messages: number[][] = [];
    const h = mount('onBarClose', { data: [bar(0, 12), bar(60, 13), bar(120, 14)], spec: {
      when: context => { seen.push([context.index, context.bars.length, context.values.value.length]); return true; },
      message: context => { messages.push([context.index, context.bars.length, context.values.value.length]); return String(context.bars[context.index].close); },
    } });
    h.source.update(bar(180, 15)); h.source.update(bar(240, 16)); h.indicator.values();
    expect(seen).toEqual([[2, 3, 3], [3, 4, 4]]);
    expect(messages).toEqual(seen);
    expect(h.events.map(event => [event.time, event.message])).toEqual([[120, '14'], [180, '15']]);
  });

  it('confirms a sparse fixed-duration tail without treating the gap as its duration', () => {
    const h = mount('onBarClose', { data: [bar(0, 12), bar(180, 13)], now: 239 });
    h.update(180, 14); expect(h.events).toEqual([]);
    h.clock.now = 240; h.update(180, 14);
    expect(h.events.map(event => event.time)).toEqual([180]);
  });

  it('uses the calendar boundary across an offset change', () => {
    releases.push(registerInterval({ code: 'alert-month', bucketing: { mode: 'calendar', unit: 'month' } }));
    const march = Date.parse('2026-03-01T05:00:00Z') / 1000;
    const april = Date.parse('2026-04-01T04:00:00Z') / 1000;
    const h = mount('onBarClose', { data: [bar(march, 12)], now: april - 1,
      interval: 'alert-month', timezone: 'America/New_York' });
    h.update(march, 13); expect(h.events).toEqual([]);
    h.clock.now = april; h.update(march, 14);
    expect(h.events.map(event => event.time)).toEqual([march]);
  });

  it('rejects an invalid explicit policy before allocating study resources', () => {
    const h = mount(undefined);
    const panes = h.chart.panes().length;
    const studies = h.chart.indicators().length;
    registerIndicator({
      id: 'invalid-alert-frequency', name: 'Invalid', placement: 'pane', inputs: [], plots: [], calc: () => ({}),
      alerts: [{ id: 'bad', title: 'Invalid', frequency: 'sometimes' as IndicatorAlertFrequency, when: () => true }],
    });
    expect(() => h.chart.addIndicator('invalid-alert-frequency')).toThrow(/frequency|policy/i);
    expect(h.chart.panes()).toHaveLength(panes);
    expect(h.chart.indicators()).toHaveLength(studies);
  });
});
