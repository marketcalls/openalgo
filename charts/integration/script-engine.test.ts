import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { DiagnosticBag, VERSION as ENGINE_VERSION, check, emit, isError, parse, sourceFile } from 'script-engine-under-test';
import { descriptorFor } from 'script-engine-under-test/adapters/charts';
import { Chart as PublicChart, registerIndicator as registerPublicIndicator } from 'openalgo-charts';
import { captureIndicatorTemplate, planIndicatorTemplateState } from 'openalgo-charts/workspace';
import 'openalgo-charts/transform';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesMarker } from '../src/primitives/markers';
import { ChartTable } from '../src/primitives/table';
import { IndicatorFill } from '../src/primitives/indicator-fill';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { VERSION } from '../src/version';
import { securityExpression } from '../src/indicators/security';
import { alignRequestedExpression, type RequestedExpression } from '../src/indicators/requested-context';
import { createRequestedIndicator } from '../src/indicators/requested-indicator';
import { createTier2Indicator } from '../src/indicators/external';
import { SMA } from '../src/indicators/trend';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from '../tests/helpers/fake-dom';
import { makeCtx } from '../tests/helpers/fake-ctx';

const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

/**
 * Compile a study. `options` goes to the adapter as a variable rather than a
 * literal, so a field an older engine does not declare (`chartVersion`
 * before 0.8.0) still type checks against it.
 */
function compile(text: string, extra: Record<string, unknown> = {}): IndicatorDescriptor {
  const file = sourceFile('compatibility.oscript', text);
  const bag = new DiagnosticBag();
  const ast = parse(file, bag);
  const checked = check(file, ast, bag);
  const result = emit(file, checked, bag, {});
  const errors = bag.ordered().filter(isError);
  expect(errors.map(error => `${error.code}: ${error.message}`)).toEqual([]);
  if (!result.program) throw new Error('script engine emitted no program');
  const options = { id: `script-compat-${sequence++}`, ...extra };
  // This assignment is checked against the actual public adapter declarations.
  // The integration runner fails compilation if the chart contract drifts.
  const descriptor: IndicatorDescriptor = descriptorFor(result.program, options);
  return descriptor;
}

/**
 * Whether the engine under test is at least `wanted`, as its build reports it.
 * Not its package.json: a checkout whose manifest moved on without a rebuild
 * still runs the older build, and a newer case must skip there, not fail.
 */
function engineAtLeast(wanted: string): boolean {
  const have = ENGINE_VERSION.split(/[-+]/)[0].split('.').map(Number);
  const want = wanted.split('.').map(Number);
  for (let i = 0; i < 3; i++) if (have[i] !== want[i]) return have[i] > want[i];
  return !ENGINE_VERSION.includes('-');
}

function makeChart(data: Bar[], now: number, updatesOnly = false) {
  const clock = { now };
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
    axisChrome: { clock: () => clock.now },
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
  const series = chart.addSeries('candlestick');
  if (updatesOnly) for (const item of data) series.update(item);
  else series.setData(data);
  return { chart, series, clock };
}

const bar = (time: number, close: number): Bar => ({ time, open: 1, high: close + 1, low: 0, close });

describe('compiled script engine on an actual Chart', () => {
  it('copies a compiled study through public template planning with independent scale settings', () => {
    const compiled = compile(`version 1
study("Template mean", overlay = true)
factor = input(10, "Factor", min = 1, max = 20)
plot(close, "Price")
plot(sma(close, 2) * factor, "Mean")
`);
    registerPublicIndicator(compiled);
    const document = fakeDocument();
    const chart = new PublicChart(document.createElement('div'), {
      document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} },
    });
    try {
      chart.applySize(800, 600);
      chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
      const source = chart.addSeries('candlestick');
      source.setData([1, 3, 5, 7].map((close, index) => bar(index * 60, close)));
      const priceKey = compiled.plots.find(plot => plot.title === 'Price')!.key;
      const meanKey = compiled.plots.find(plot => plot.title === 'Mean')!.key;
      const scaleId = 'overlay:template-mean';
      const original = chart.addIndicator(compiled.id, {}, { plotPriceScaleIds: { [meanKey]: scaleId } });
      const originalId = original.id, scale = original.series(meanKey)!.priceScale();
      scale.setOptions({ inverted: true, minMove: 0.25, minPrecision: 2 });
      scale.setAutoScale(false); scale.setPriceRange({ min: 0, max: 100 });
      chart.setPriceAxisPlacement(0, scaleId, 'left');
      source.priceScale().setPriceFormatter(value => `Q${value}`);
      const data = source.getData(), values = original.values();
      expect(values[meanKey]).toEqual([null, 20, 40, 60]);

      const payload = captureIndicatorTemplate(chart);
      const plan = planIndicatorTemplateState(chart, payload, 'append', { rangePolicy: 'preserve' });
      expect(chart.indicators()).toEqual([original]);
      expect(plan.indicators).toHaveLength(2);
      const copyId = plan.indicators[1].instanceId!;
      expect(copyId).not.toBe(originalId);
      const report = chart.restoreState({ version: 1, indicators: plan.indicators, panes: plan.panes }, plan.restoreOptions);
      expect(report.applied).toBe(true); expect(report.indicators).toBe(2);
      const restored = chart.indicators().find(study => study.id === originalId)!;
      const copied = chart.indicators().find(study => study.id === copyId)!;
      const copiedScaleId = copied.plotPriceScaleId(meanKey)!;
      expect(copiedScaleId).not.toBe(scaleId);
      expect(copied.series(meanKey)!.priceScale()).not.toBe(scale);
      expect(copied.series(meanKey)!.priceScale()).not.toBe(source.priceScale());
      expect(copied.series(meanKey)!.priceScale().options).toMatchObject({ inverted: true, minMove: 0.25, minPrecision: 2 });
      expect(copied.series(meanKey)!.priceScale().priceRange()).toEqual({ min: 0, max: 100 });
      expect(chart.priceAxisPlacement(0, copiedScaleId)).toEqual({ side: 'left', order: 1 });
      expect(restored.series(meanKey)!.priceScale()).toBe(scale);
      expect(copied.series(priceKey)!.priceScale()).toBe(source.priceScale());
      expect(chart.primarySeries()).toBe(source);
      expect(source.getData()).toEqual(data);
      expect(source.priceScale().format(2)).toBe('Q2');
      expect(restored.values()).toEqual(values); expect(copied.values()).toEqual(values);

      source.update(bar(180, 9));
      for (const study of [restored, copied]) {
        expect(study.values()[priceKey]).toEqual([1, 3, 5, 9]);
        expect(study.values()[meanKey]).toEqual([null, 20, 40, 70]);
        expect(study.series(meanKey)!.getData()[3].close).toBe(70);
      }
      expect(chart.primarySeries()).toBe(source);
      expect(copied.series(meanKey)!.priceScale()).not.toBe(restored.series(meanKey)!.priceScale());
    } finally { chart.destroy(); }
  });

  it('keeps compiled plots independent through per-plot reassignment and restoration', () => {
    const compiled = compile(`version 1
study("Separate plot units", overlay = true)
plot(close, "Price")
plot(close * 100, "Scaled")
`);
    registerIndicator(compiled);
    const { chart, series } = makeChart([1, 3, 5].map((close, index) => bar(index * 60, close)), 130);
    const [price, scaled] = compiled.plots.map(plot => plot.key);
    const study = chart.addIndicator(compiled.id, {}, { plotPriceScaleIds: { [scaled]: 'overlay:compiled-units' } });
    expect(study.values()[price]).toEqual([1, 3, 5]);
    expect(study.values()[scaled]).toEqual([100, 300, 500]);
    expect(study.series(price)!.priceScale()).toBe(series.priceScale());
    expect(study.series(scaled)!.priceScale()).not.toBe(series.priceScale());
    const values = study.values(), plot = study.series(scaled);
    expect(study.setPlotPriceScales({ [scaled]: 'left' })).toBe(true);
    expect(study.values()).toBe(values);
    expect(study.series(scaled)).toBe(plot);
    expect(study.series(price)!.priceScale()).toBe(series.priceScale());
    expect(chart.restoreState(chart.getState()).applied).toBe(true);
    const restored = chart.indicators()[0];
    expect(restored.plotPriceScaleIds()).toEqual({ [scaled]: 'left' });
    expect(restored.series(scaled)!.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
    series.update(bar(120, 7));
    expect(restored.values()[price]).toEqual([1, 3, 7]);
    expect(restored.values()[scaled]).toEqual([100, 300, 700]);
  });

  it('keeps compiled study outputs and scale identity through native axis placement and restoration', () => {
    const compiled = compile(`version 1
study("Independent output", overlay = true)
factor = input(2, "Factor", min = 1, max = 20)
plot(close * factor, "Scaled")
`);
    registerIndicator(compiled);
    const { chart, series } = makeChart([1, 3, 5, 7].map((close, index) => bar(index * 60, close)), 190);
    const scaleId = 'overlay:compiled';
    const setting = compiled.inputs[0].key, key = compiled.plots[0].key;
    const study = chart.addIndicator(compiled.id, { [setting]: 10 }, { priceScaleId: scaleId });
    const plot = study.series(key)!, scale = plot.priceScale(), primaryScale = series.priceScale();
    const values = study.values(), data = plot.getData();
    expect(values[key]).toEqual([10, 30, 50, 70]);
    expect(data.map(point => point.close)).toEqual(values[key]);
    expect(scale).not.toBe(primaryScale);
    expect(chart.priceAxisLayout().map(slot => slot.scaleId)).toEqual(['right']);
    scale.setAutoScale(false);
    scale.setPriceRange({ min: 0, max: 100 });
    scale.setPriceFormatter(value => `C${value}`);

    expect(chart.setPriceAxisPlacement(0, scaleId, 'right')).toBe(true);
    expect(chart.priceAxisLayout()).toEqual([
      { scaleId: 'right', side: 'right', order: 0, x: 688, width: 56 },
      { scaleId, side: 'right', order: 1, x: 744, width: 56 },
    ]);
    expect(chart.exportSVG()).toContain('>C20</text>');
    expect(chart.setPriceAxisPlacement(0, scaleId, 'right', 0)).toBe(true);
    expect(chart.priceAxisLayout().map(slot => slot.scaleId)).toEqual([scaleId, 'right']);
    expect(chart.setPriceAxisPlacement(0, scaleId, 'left')).toBe(true);
    expect(chart.setPriceAxisPlacement(0, 'right', 'left', 0)).toBe(true);
    expect(chart.priceAxisLayout()).toEqual([
      { scaleId: 'right', side: 'left', order: 0, x: 56, width: 56 },
      { scaleId, side: 'left', order: 1, x: 0, width: 56 },
    ]);
    chart.setVisibleLogicalRange({ from: 0, to: 3 });
    expect(chart.indicators()[0]).toBe(study);
    expect(study.series(key)).toBe(plot);
    expect(plot.priceScale()).toBe(scale);
    expect(series.priceScale()).toBe(primaryScale);
    expect(study.values()).toBe(values);
    expect(plot.getData()).toEqual(data);
    expect(scale.priceRange()).toEqual({ min: 0, max: 100 });

    const saved = chart.getState(), layout = chart.priceAxisLayout();
    expect(saved.indicators?.[0]).toMatchObject({ instanceId: study.id, priceScaleId: scaleId, settings: { [setting]: 10 } });
    expect(saved.panes?.[0].scales?.[scaleId]?.placement).toEqual({ side: 'left', order: 1 });
    chart.setVisibleLogicalRange({ from: 1, to: 3 });
    chart.setPriceAxisPlacement(0, scaleId, 'hidden');
    expect(study.values()).toBe(values);
    expect(plot.getData()).toEqual(data);
    expect(chart.restoreState(saved).applied).toBe(true);
    const restored = chart.indicators().find(item => item.id === study.id)!;
    expect(restored.settings()[setting]).toBe(10);
    expect(restored.priceScaleId()).toBe(scaleId);
    expect(restored.series(key)?.priceScale()).toBe(scale);
    expect(series.priceScale()).toBe(primaryScale);
    expect(restored.values()[key]).toEqual([10, 30, 50, 70]);
    expect(restored.series(key)?.getData()).toEqual(data);
    expect(chart.priceAxisLayout()).toEqual(layout);
    expect(scale.priceRange()).toEqual({ min: 0, max: 100 });
    expect(scale.format(20)).toBe('C20');
    expect(chart.exportSVG()).toContain('>C20</text>');

    series.update(bar(180, 9));
    expect(restored.values()[key]).toEqual([10, 30, 50, 90]);
    expect(restored.series(key)?.getData()[3].close).toBe(90);
    expect(restored.series(key)?.priceScale()).toBe(scale);
  });

  it('uses compiled scalar outputs as native study inputs through updates and restoration', () => {
    const compiled = compile(`version 1
study("Connected output")
plot(close * 3, "Value")
`);
    registerIndicator(compiled);
    registerIndicator(SMA);
    const { chart, series } = makeChart([1, 3, 5, 7].map((close, index) => bar(index * 60, close)), 190);
    const producer = chart.addIndicator(compiled.id);
    const consumer = chart.addIndicator('sma', { length: 2, source: {
      kind: 'indicator', instanceId: producer.id, plotKey: compiled.plots[0].key,
    } });
    expect(consumer.values().ma).toEqual([null, 6, 12, 18]);
    series.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, 6, 12, 21]);
    producer.setVisible(false);
    const saved = chart.getState();
    saved.indicators!.reverse();
    chart.restoreState(saved);
    const restored = chart.indicators().find(item => item.id === consumer.id)!;
    expect(restored.values().ma).toEqual([null, 6, 12, 21]);
    series.update(bar(240, 11));
    expect(restored.values().ma).toEqual([null, 6, 12, 21, 30]);
  });

  it('fires a compiled alert on each brick one source bar completes on a Renko chart', () => {
    const compiled = compile(`version 1
study("Brick steps", overlay = true)
if close > close[1]
    alert("up brick at " + text(close, 2), id = "up", title = "Up brick")
plot(close, "Close")
`);
    registerPublicIndicator(compiled);
    const document = fakeDocument();
    const chart = new PublicChart(document.createElement('div'), {
      document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} },
    });
    try {
      chart.applySize(800, 600);
      chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
      const series = chart.addSeries('candlestick', { transform: { type: 'renko', options: { boxSize: 1 } } });
      // Bricks close at 101 and 102; the next bar closes at 104.3 and completes two more.
      series.setData([100.2, 101.3, 102.4, 102.6].map((close, i) => bar(i * 60, close)));
      const events: { time: number; message: string }[] = [];
      chart.on('indicator:alert', payload => events.push(payload as { time: number; message: string }));
      const indicator = chart.addIndicator(compiled.id);
      series.update(bar(240, 104.3)); indicator.values();
      expect(chart.primaryBars().map(brick => brick.close)).toEqual([101, 102, 103, 104]);
      expect(events.map(event => [event.time, event.message])).toEqual([[240, 'up brick at 103.00'], [241, 'up brick at 104.00']]);
    } finally {
      chart.destroy();
    }
  });

  it('evaluates native close alerts from compiled outputs with provider confirmation', () => {
    const compiled = compile(`version 1
study("Confirmed output")
plot(close * 3, "Value")
`);
    const key = compiled.plots[0].key;
    registerIndicator({ ...compiled, alerts: [{
      id: 'confirmed', title: 'Confirmed value', frequency: 'onBarClose',
      when: context => context.values[key][context.index]! > 0,
      message: context => String(context.values[key][context.index]),
    }] });
    const { chart, series } = makeChart([bar(0, 2), bar(60, 3)], 61);
    const events: { time: number; message: string }[] = [];
    chart.on('indicator:alert', payload => events.push(payload as { time: number; message: string }));
    const indicator = chart.addIndicator(compiled.id);
    series.update(bar(60, 4), { confirmation: 'forming' }); indicator.values();
    expect(events).toEqual([]);
    series.update(bar(60, 4), { confirmation: 'confirmed' }); indicator.values();
    series.update(bar(60, 5), { confirmation: 'confirmed' }); indicator.values();
    series.update(bar(120, 6), { confirmation: 'forming' }); indicator.values();
    series.update(bar(120, 7), { confirmation: 'confirmed' }); indicator.values();
    expect(events.map(event => [event.time, event.message])).toEqual([[60, '12'], [120, '21']]);
    expect(indicator.values()[key]).toEqual([6, 15, 21]);
  });

  it('refreshes a compiled external mean on same-time ticks and provider replacement', async () => {
    const compiled = compile(`version 1
study("External rolling mean")
plot(sma(close, 2), "Mean")
`);
    const key = compiled.plots[0].key;
    let requested = [bar(0, 10), bar(60, 20), bar(120, 30)];
    const descriptor = createTier2Indicator({
      id: compiled.id, name: compiled.name, placement: compiled.placement,
      inputs: compiled.inputs, plots: compiled.plots,
      fetch: async context => {
        // Fetch the calculation's warmup before converting its output to points.
        const bars = await context.requestBars!({
          symbol: 'EXTERNAL', interval: '1m', from: 0, to: context.to, signal: context.signal,
        });
        const values = compiled.calc(bars, context.settings, {});
        return bars.map((item, index) => ({ time: item.time, values: { [key]: values[key][index] } }));
      },
    });
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(0, 100), bar(60, 200), bar(120, 300)], 140);
    chart.setBarsProvider(async () => requested);
    const indicator = chart.addIndicator(descriptor.id);
    await vi.waitFor(() => expect(indicator.values()[key]).toEqual([null, 15, 25]));
    requested = [bar(0, 10), bar(60, 20), bar(120, 60)];
    series.update(bar(120, 301));
    await vi.waitFor(() => expect(indicator.values()[key]).toEqual([null, 15, 40]));
    chart.setBarsProvider(async () => [bar(0, 100), bar(60, 200), bar(120, 300)]);
    expect(indicator.values()[key]).toEqual([null, null, null]);
    await vi.waitFor(() => expect(indicator.values()[key]).toEqual([null, 150, 250]));
    expect(indicator.series(key)?.getData()[2].close).toBe(250);
  });

  it('runs a compiled requested expression through confirmation and provider replacement', async () => {
    const compiled = compile(`version 1
study("Managed external mean")
plot(sma(close, 2), "Mean")
`);
    const key = compiled.plots[0].key;
    let requested = {
      bars: [bar(0, 10), bar(120, 20)], availableAt: [60, 180], confirmed: [true, false],
    };
    const descriptor = createRequestedIndicator({
      id: compiled.id, name: compiled.name, placement: compiled.placement,
      inputs: compiled.inputs, plots: compiled.plots,
      request: () => ({ symbol: 'EXTERNAL', interval: '2m', from: 0, to: 300 }),
      expression: (bars, settings) => compiled.calc(bars, settings, {}),
    });
    registerIndicator(descriptor);
    const { chart } = makeChart([0, 60, 120, 180, 240, 300].map(time => bar(time, 1000 + time)), 360);
    chart.setBarsProvider({ requestBars: async () => requested.bars, requestSnapshot: async () => requested });
    const indicator = chart.addIndicator(descriptor.id);
    await vi.waitFor(() => expect(indicator.dataStatus()?.state).toBe('ready'));
    expect(indicator.values()[key]).toEqual([null, null, null, null, null, null]);
    requested = { ...requested, confirmed: [true, true] };
    chart.invalidateRequestedData();
    await vi.waitFor(() => expect(indicator.values()[key]).toEqual([null, null, null, 15, 15, 15]));
    chart.setBarsProvider({ requestBars: async () => [], requestSnapshot: async () => ({
      bars: [bar(0, 50), bar(120, 70)], availableAt: [60, 180], confirmed: [true, true],
    }) });
    await vi.waitFor(() => expect(indicator.values()[key]).toEqual([null, null, null, 60, 60, 60]));
    expect(indicator.series(key)?.getData()[5].close).toBe(60);
  });

  it('calculates a compiled expression on separate requested bars before availability alignment', () => {
    const compiled = compile(`version 1
study("External mean")
plot(sma(close, 2), "Mean")
`);
    const requested = {
      bars: [bar(0, 10), bar(120, 20), bar(240, 30)],
      availableAt: [60, 180, 300], confirmed: [true, true, true],
    };
    const observed: number[][] = [];
    const expression: RequestedExpression = bars => {
      observed.push(bars.map(item => item.close));
      return compiled.calc(bars, {}, {});
    };
    const key = compiled.plots[0].key;
    const descriptor: IndicatorDescriptor = {
      ...compiled,
      plots: [
        { key: 'carry', type: 'line', title: 'Carried mean' },
        { key: 'missing', type: 'line', title: 'New mean' },
      ],
      calcTail: undefined,
      calc: bars => {
        const times = bars.map(item => item.time);
        return {
          carry: alignRequestedExpression(times, requested, expression)[key],
          missing: alignRequestedExpression(times, requested, expression, { gaps: 'missing' })[key],
        };
      },
    };
    registerIndicator(descriptor);
    const { chart } = makeChart([0, 60, 120, 180, 240, 300].map(time => bar(time, 1000 + time)), 360);
    const indicator = chart.addIndicator(descriptor.id);
    expect(observed).toEqual([[10, 20, 30], [10, 20, 30]]);
    expect(indicator.values().carry).toEqual([null, null, null, 15, 15, 25]);
    expect(indicator.values().missing).toEqual([null, null, null, 15, null, 25]);
    expect(indicator.series('carry')?.getData()[4].close).toBe(15);
    expect(Number.isNaN(indicator.series('missing')!.getData()[4].close)).toBe(true);
  });

  it('rebuilds the compiled execution when a replacement primary has overlapping source revisions', () => {
    const descriptor = compile(`version 1
study("Source replacement")
var accumulated = 0
accumulated = accumulated + close
plot(accumulated, "Total")
`);
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(120, 1), bar(180, 2)], 240, true);
    const indicator = chart.addIndicator(descriptor.id);
    const key = descriptor.plots[0].key;
    expect(indicator.values()[key]).toEqual([1, 3]);
    series.remove();
    const replacement = chart.addSeries('candlestick');
    replacement.update(bar(120, 10));
    replacement.update(bar(180, 20));
    replacement.update(bar(180, 30));
    expect(indicator.values()[key]).toEqual([10, 40]);
  });

  it('rebuilds persistent calculations after same-shaped history replacement and coalesced corrections', () => {
    const descriptor = compile(`version 1
study("Accumulated values")
var accumulated = 0
accumulated = accumulated + close
plot(accumulated, "Total")
`);
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(120, 2), bar(180, 3), bar(240, 4)], 300);
    const indicator = chart.addIndicator(descriptor.id);
    const key = descriptor.plots[0].key;
    expect(indicator.values()[key]).toEqual([2, 5, 9]);
    series.setData([bar(120, 20), bar(180, 30), bar(240, 40)]);
    expect(indicator.values()[key]).toEqual([20, 50, 90]);
    series.update(bar(180, 10));
    series.update(bar(240, 8));
    expect(indicator.values()[key]).toEqual([20, 30, 38]);
  });

  it('rolls back ordinary persistent values across repeated updates to a forming bar', () => {
    const descriptor = compile(`version 1
study("Persistent tail")
var accumulated = 0
accumulated = accumulated + close
plot(accumulated, "Total")
`);
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(120, 2), bar(180, 3)], 190);
    const indicator = chart.addIndicator(descriptor.id);
    const key = descriptor.plots[0].key;
    expect(indicator.values()[key]).toEqual([2, 5]);
    for (const close of [4, 5, 6]) {
      series.update(bar(180, close));
      expect(indicator.values()[key]).toEqual([2, 2 + close]);
    }
    series.update(bar(240, 7));
    expect(indicator.values()[key]).toEqual([2, 8, 15]);
    const fresh = makeChart([bar(120, 2), bar(180, 6), bar(240, 7)], 250);
    expect(fresh.chart.addIndicator(descriptor.id).values()[key]).toEqual(indicator.values()[key]);
  });

  it('publishes a provider-confirmed count-bar signal without a price change', () => {
    const descriptor = compile(`version 1
study("Provider confirmation", overlay = true)
if close > open
    signal("SETTLED", shape = "triangleUp", at = "below", color = lime)
plot(close, "Close")
`);
    let drawn: readonly SeriesMarker[] = [];
    const markers = descriptor.markers;
    descriptor.markers = context => { drawn = markers?.(context) ?? []; return drawn; };
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(120, 2), bar(180, 3)], 10000);
    chart.setDataContext({ symbol: 'SAMPLE', interval: '100t' });
    series.setData([bar(120, 2), bar(180, 3)], { confirmation: 'forming' });
    const indicator = chart.addIndicator(descriptor.id);
    expect(drawn.map(marker => marker.time)).toEqual([120]);
    series.update(bar(180, 3), { confirmation: 'confirmed' });
    indicator.values();
    expect(drawn.map(marker => marker.time)).toEqual([120, 180]);
    series.update(bar(180, 3));
    indicator.values();
    expect(drawn.map(marker => marker.time)).toEqual([120, 180]);
  });

  it('passes historical and replay provenance and replay confirmation through the existing adapter', () => {
    const descriptor = compile(`version 1
study("Execution state")
plot(bar.isRealtime ? 1 : 0, "Live")
plot(bar.isConfirmed ? 1 : 0, "Confirmed")
`);
    registerIndicator(descriptor);
    const data = [bar(120, 2), bar(180, 3), bar(240, 4)];
    const { chart, series } = makeChart(data, 10000);
    const indicator = chart.addIndicator(descriptor.id);
    const liveKey = descriptor.plots.find(plot => plot.title === 'Live')!.key;
    const confirmedKey = descriptor.plots.find(plot => plot.title === 'Confirmed')!.key;
    series.update(bar(240, 5));
    expect(indicator.values()[liveKey][2]).toBe(1);
    series.setData(data);
    expect(indicator.values()[liveKey][2]).toBe(0);
    const replay = new ReplayController(chart, {
      series, bars: data, startIndex: 0,
      subBars: data.flatMap(item => [bar(item.time, 2), bar(item.time + 20, 3), bar(item.time + 40, 4)]),
    });
    try {
      expect(indicator.values()[liveKey]).toEqual([0]);
      expect(indicator.values()[confirmedKey]).toEqual([1]);
      replay.step();
      expect(indicator.values()[liveKey]).toEqual([0, 0]);
      expect(indicator.values()[confirmedKey]).toEqual([1, 0]);
      replay.step(2);
      expect(indicator.values()[confirmedKey]).toEqual([1, 1]);
      replay.stepBack(3);
      expect(indicator.values()[liveKey]).toEqual([0]);
      expect(indicator.values()[confirmedKey]).toEqual([1]);
    } finally { replay.stop(); }
    expect(indicator.values()[liveKey]).toEqual([0, 0, 0]);
  });

  it('composes a compiled calculation with native timeframe aggregation and live alignment', () => {
    const compiled = compile(`version 1
study("Requested mean")
plot(sma(close, 2), "Mean")
`);
    const descriptor: IndicatorDescriptor = {
      ...compiled,
      calcTail: undefined,
      calc: (bars, settings) => securityExpression(bars, '3m', requested =>
        compiled.calc(requested, settings, {}), { timezone: 'UTC' }),
    };
    registerIndicator(descriptor);
    const source = Array.from({ length: 9 }, (_, i) => bar(i * 60, i + 1));
    const { chart, series } = makeChart(source, 500);
    const indicator = chart.addIndicator(descriptor.id);
    const key = descriptor.plots[0].key;
    expect(indicator.values()[key]).toEqual([null, null, null, null, null, null, 4.5, 4.5, 4.5]);
    series.update(bar(480, 90));
    expect(indicator.values()[key]).toEqual([null, null, null, null, null, null, 4.5, 4.5, 4.5]);
    series.update(bar(540, 10));
    expect(indicator.values()[key]).toEqual([null, null, null, null, null, null, 4.5, 4.5, 4.5, 48]);
    expect(indicator.series(key)?.getData()[9].close).toBe(48);
  });

  it('preserves arithmetic and seconds-to-milliseconds conversion through the adapter', () => {
    const descriptor = compile(`version 1
study("Boundary")
plot(close * 2 + open, "Value")
plot(time, "Time")
`);
    registerIndicator(descriptor);
    const { chart } = makeChart([bar(120, 2), bar(180, 3)], 240);
    const indicator = chart.addIndicator(descriptor.id);
    const value = descriptor.plots.find(plot => plot.title === 'Value')!;
    const time = descriptor.plots.find(plot => plot.title === 'Time')!;
    expect(indicator.values()[value.key]).toEqual([5, 7]);
    expect(indicator.values()[time.key]).toEqual([120000, 180000]);
    expect(indicator.series(value.key)?.getData().map(point => point.close)).toEqual([5, 7]);
  });

  it('publishes a deferred signal at the minute close after a weekend gap', () => {
    const descriptor = compile(`version 1
study("Settled signals", overlay = true)
if close > open
    signal("UP", shape = "triangleUp", at = "below", color = lime)
plot(close, "Close")
`);
    const friday = Date.parse('2026-09-18T09:59:00Z') / 1000;
    const monday = Date.parse('2026-09-21T03:45:00Z') / 1000;
    let drawn: readonly SeriesMarker[] = [];
    const markers = descriptor.markers;
    descriptor.markers = context => { drawn = markers?.(context) ?? []; return drawn; };
    registerIndicator(descriptor);
    const { chart, series, clock } = makeChart([bar(friday, 2), bar(monday, 3)], monday + 59);
    const indicator = chart.addIndicator(descriptor.id);
    expect(drawn.map(marker => marker.time)).toEqual([friday]);
    clock.now = monday + 60;
    series.update(bar(monday, 4));
    indicator.values();
    expect(drawn.map(marker => marker.time)).toEqual([friday, monday]);
    expect(drawn[1].text).toBe('UP');
    series.update(bar(monday, 5));
    indicator.values();
    expect(drawn.map(marker => marker.time)).toEqual([friday, monday]);
  });

  it('keeps tail updates equal to a fresh execution and isolates settings between instances', () => {
    const descriptor = compile(`version 1
study("Scaled")
factor = input(2, "Factor", min = 1, max = 10)
plot(close * factor, "Scaled")
`);
    registerIndicator(descriptor);
    const { chart, series, clock } = makeChart([bar(120, 2), bar(180, 3)], 240);
    const first = chart.addIndicator(descriptor.id);
    const second = chart.addIndicator(descriptor.id);
    const key = descriptor.plots[0].key;
    const setting = descriptor.inputs[0].key;
    first.setSettings({ [setting]: 3 });
    expect(first.values()[key]).toEqual([6, 9]);
    expect(second.values()[key]).toEqual([4, 6]);
    clock.now = 300;
    series.update(bar(240, 4));
    series.update(bar(240, 5));
    expect(first.values()[key]).toEqual([6, 9, 15]);
    expect(second.values()[key]).toEqual([4, 6, 10]);
    const fresh = makeChart([bar(120, 2), bar(180, 3), bar(240, 5)], 300);
    expect(fresh.chart.addIndicator(descriptor.id).values()[key]).toEqual(second.values()[key]);
    first.remove();
    series.update(bar(240, 6));
    expect(second.values()[key]).toEqual([4, 6, 12]);
  });

  it('updates a declared table on the chart and removes its resources with the study', () => {
    const descriptor = compile(`version 1
study("Panel", overlay = true)
panel = table("Panel", 1, 1, position = "topLeft")
cell(panel, 0, 0, text(close, 2))
plot(close, "Close")
`);
    registerIndicator(descriptor);
    const { chart, series } = makeChart([bar(120, 2), bar(180, 3)], 240);
    const indicator = chart.addIndicator(descriptor.id);
    const tables = () => chart.panes().flatMap(pane => pane.primitives()).filter(p => p instanceof ChartTable);
    expect(tables()).toHaveLength(1);
    expect(tables()[0].rows()[0][0].text).toBe('3.00');
    series.update(bar(180, 5));
    indicator.values();
    expect(tables()[0].rows()[0][0].text).toBe('5.00');
    indicator.remove();
    expect(tables()).toHaveLength(0);
  });

  it('draws every declared grid and a band coloured per bar when the host states the chart version', context => {
    // The adapter draws both only from 0.8.0, and refuses such a study before.
    context.skip(!engineAtLeast('0.8.0'),
      `script engine build ${ENGINE_VERSION} is older than 0.8.0, whose adapter first draws several grids and a band colour computed per bar`);
    const descriptor = compile(`version 1
study("Grids and band", overlay = true)
upper = plot(close + 1, "Upper")
lower = plot(close - 1, "Lower")
fill(upper, lower, color = close > open ? lime : red)
first = table("First", 1, 1, position = "topLeft")
cell(first, 0, 0, text(close, 2))
second = table("Second", 1, 2, position = "bottomRight")
cell(second, 0, 0, "Open")
cell(second, 0, 1, text(open, 1))
`, { chartVersion: VERSION });
    registerIndicator(descriptor);
    const candle = (time: number, open: number, close: number): Bar => ({ time, open, high: Math.max(open, close) + 1, low: 0, close });
    // Up, down, down, up, up. The band between two bars takes the colour the
    // script computed on the first of them, one fill per run of a colour.
    const { chart, series } = makeChart([candle(120, 1, 3), candle(180, 5, 2), candle(240, 4, 3), candle(300, 2, 4), candle(360, 3, 5)], 400);
    const indicator = chart.addIndicator(descriptor.id);
    const primitives = () => chart.panes().flatMap(pane => pane.primitives());
    const tables = () => primitives().filter((item): item is ChartTable => item instanceof ChartTable);
    const texts = () => tables().map(table => table.rows().map(row => row.map(cell => cell.text)));
    indicator.values();
    expect(tables()).toHaveLength(2);
    expect(texts()).toEqual([[['5.00']], [['Open', '3.0']]]);
    expect(tables().map(table => table.options().position)).toEqual(['top-left', 'bottom-right']);

    const band = primitives().find((item): item is IndicatorFill => item instanceof IndicatorFill);
    expect(band).toBeDefined();
    const shades = (): (string | undefined)[] => {
      indicator.values();
      const { ctx, rec } = makeCtx();
      band!.draw(ctx, { dpr: 1, timeScale: chart.timeScale, priceScale: { priceToY: (value: number) => 100 - value } } as unknown as PrimitiveRenderContext);
      return rec.ops.filter(op => op.type === 'fill').map(op => op.fillStyle);
    };
    const up = 'rgba(0, 255, 0, 1)', down = 'rgba(255, 0, 0, 1)';
    expect(shades()).toEqual([up, down, up]);
    // Live bars the script computes down, and a grid written on the last one.
    series.update(candle(420, 6, 2));
    series.update(candle(480, 2, 1));
    expect(shades()).toEqual([up, down, up, down]);
    expect(texts()).toEqual([[['1.00']], [['Open', '2.0']]]);
    indicator.remove();
    expect(tables()).toHaveLength(0);
    expect(primitives().some(item => item instanceof IndicatorFill)).toBe(false);
  });

  it('carries the message of the bar a brick completed on, for a study on the underlying bars', context => {
    // Before 0.8.1 the adapter read a message at the brick's position in the run.
    context.skip(!engineAtLeast('0.8.1'),
      `script engine build ${ENGINE_VERSION} is older than 0.8.1, whose adapter first reads an alert message at the underlying bar`);
    const descriptor = compile(`version 1
study("Brick alert", overlay = true)
if close > open
    alert("Close " + text(close, 2), id = "up", title = "Up bar")
plot(close, "Close")
`);
    // The public chart, with the transform tier a host imports to have the chart form bricks itself.
    registerPublicIndicator(descriptor);
    const candle = (time: number, open: number, close: number): Bar => ({ time, open, high: Math.max(open, close), low: Math.min(open, close), close });
    // One-point bricks. Bar 0 anchors at 100 and bars 3, 6 and 9 each complete
    // one, so the live bar below completes brick 3. Bar 3 rose too, so a message
    // read at the brick's position carries bar 3's close instead of its own.
    const closes = [100, 100.4, 100.2, 101.1, 101.5, 101.3, 102.2, 102.6, 102.4, 103.3];
    const history = closes.map((close, i) => candle(60 * (i + 1), i === 0 ? 99.8 : closes[i - 1], close));
    const document = fakeDocument();
    const chart = new PublicChart(document.createElement('div'), {
      document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} },
    });
    onTestFinished(() => chart.destroy());
    chart.applySize(800, 600);
    chart.setDataContext({ symbol: 'SAMPLE', interval: '1m' });
    const series = chart.addSeries('candlestick');
    series.setData(history);
    expect(chart.setSeriesTransform(series, { type: 'renko', options: { boxSize: 1 } })).toBe(true);
    const events: { time: number; message: string }[] = [];
    chart.on('indicator:alert', payload => events.push(payload as { time: number; message: string }));
    const indicator = chart.addIndicator(descriptor.id, {}, { barSource: 'underlying' });
    indicator.values();
    expect(chart.primaryBars()).toHaveLength(3);
    // A live bar completing one brick, which is a step the chart alerts on.
    series.update(candle(660, 103.3, 104.1), { confirmation: 'confirmed' });
    indicator.values();
    expect(chart.primaryBars()).toHaveLength(4);
    expect(events.map(event => [event.time, event.message])).toEqual([[660, 'Close 104.10']]);
  });
});
