/**
 * Every settings control must be undoable. Set it away from where it was, set
 * it back, and the chart has to be where it started: not approximately, and
 * not only in the control's own readback.
 *
 * That second half is the whole point. A control that reads back its own write
 * while having quietly overwritten something else is worse than one that does
 * nothing, because the damage is invisible from the dialog and there is nothing
 * the user can press to reverse it. Three shipped that way:
 *
 *  - Plot margins swept the *hidden overlay* scales along with the visible
 *    axes, so the volume histogram's 0.82 top margin (its placement in the
 *    bottom fifth of the price pane) was replaced by the dialog's number. Going
 *    back to 10 wrote 0.1, not the 0.82 nobody had recorded.
 *  - Auto-fit was chart-wide, so turning it back on re-measured an oscillator
 *    pane against its own values: an RSI band declared as 0..100 came back as
 *    18..86, relabelled, with the declared band gone.
 *  - `restoreState` set each pane's price scale before rebuilding the
 *    indicators, and rebuilding one takes its pane's axis with it, so the
 *    restored scale was thrown away by the rest of the same restore.
 *
 * So the assertions here are made against a snapshot of what is actually
 * drawn (every scale on every pane, including the hidden ones) and not
 * against `readChartSettings` alone, which was true throughout all three.
 *
 * It is deliberately generic: every numeric and boolean control the schema
 * declares is walked, so a control added later is covered the moment it
 * appears.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins (RSI)
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import {
  chartSettingsSchema, readChartSettings, applyChartSettings,
  type ChartSettingsInput, type ChartSettingsValue, type ChartSettingsValues,
} from '../src/model/chart-settings';
import type { Bar } from '../src/model/bar';
import type { SeriesType } from '../src/model/chart-type-registry';

const T0 = 1700000000;
const MIN = 60;

/** Enough bars for RSI to warm up and for the price band to have some shape. */
const BARS: Bar[] = Array.from({ length: 140 }, (_, i) => {
  const close = 100 + Math.sin(i / 5) * 10 + i * 0.05;
  const open = i % 2 === 0 ? close - 1.2 : close + 1.2;
  return {
    time: T0 + i * MIN,
    open,
    close,
    high: Math.max(open, close) + 0.8,
    low: Math.min(open, close) - 0.8,
    volume: 1000 + i * 37,
  };
});

/**
 * A chart in the shape the reference host builds: a price series, a volume
 * histogram on the pane's hidden overlay scale pinned to the bottom fifth, and
 * an oscillator on a pane of its own that declares its own 0..100 band.
 *
 * All three matter. Two of the three defects above were invisible on a chart
 * carrying only a price series, which is why they shipped.
 *
 * Painted synchronously (see the `raf` here and `applySize` below), because a
 * chart that has never rendered leaves every scale on its 0..1 placeholder and
 * every range assertion below would compare zero to zero.
 */
function mount(type: SeriesType = 'candlestick'): Chart {
  return build(type).chart;
}

function build(type: SeriesType = 'candlestick'): { chart: Chart; el: FakeElement } {
  const doc = fakeDocument();
  // `_attachInput` bails without a window, and without its listeners the chart
  // never learns where the cursor is, so no crosshair is ever drawn.
  const el = doc.createElement('div') as unknown as FakeElement;
  Object.assign(el, { clientWidth: 900, clientHeight: 600 });
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(900, 600);
  chart.addSeries(type).setData(BARS);
  const volume = chart.addSeries('histogram', { priceScaleId: '' });
  volume.setData(BARS.map((b) => ({ time: b.time, value: b.volume ?? 0 })));
  volume.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 });
  chart.addIndicator('rsi');
  return { chart, el };
}

/** Every scale on every pane, hidden ones included: the state a pixel diff sees. */
interface ScaleSnapshot {
  pane: number;
  autoScale: boolean;
  range: { min: number; max: number };
  marginTop: number;
  marginBottom: number;
  mode: string;
  inverted: boolean;
}

function scales(chart: Chart): ScaleSnapshot[] {
  return chart.panes().flatMap((pane, i) =>
    pane.scales().map((scale) => ({
      pane: i,
      autoScale: scale.autoScale,
      range: scale.priceRange(),
      marginTop: scale.options.marginTop,
      marginBottom: scale.options.marginBottom,
      mode: scale.options.mode,
      inverted: scale.options.inverted,
    })));
}

/** Every numeric and boolean control the schema declares, flattened. */
interface Knob {
  key: string;
  kind: 'number' | 'boolean';
  min?: number;
  max?: number;
}

function knobs(input: ChartSettingsInput): Knob[] {
  if (input.type === 'colorPair') {
    // The only value on a paired row that is not a colour is its switch.
    return input.enabled === undefined ? [] : [{ key: input.enabled.key, kind: 'boolean' }];
  }
  if (input.type === 'boolean') return [{ key: input.key, kind: 'boolean' }];
  if (input.type === 'number') return [{ key: input.key, kind: 'number', min: input.min, max: input.max }];
  return [];
}

function allKnobs(chart: Chart): Knob[] {
  return chartSettingsSchema(chart).flatMap((tab) => tab.inputs.flatMap(knobs));
}

/**
 * A value the control does not currently hold. The far end of the declared
 * range rather than one step away: a margin of 49% or a grid at 200 px is where
 * a control that rescales from an already-scaled range shows it, and one step
 * of rounding error hides in the noise.
 */
function away(knob: Knob, current: ChartSettingsValue): ChartSettingsValue {
  if (knob.kind === 'boolean') return current !== true;
  const min = knob.min ?? 0;
  const max = knob.max ?? 100;
  return current === max ? min : max;
}

describe('settings reversibility', () => {
  for (const type of ['candlestick', 'line'] as const) {
    it(`puts every numeric and boolean control back where it was (${type})`, () => {
      const chart = mount(type);
      const list = allKnobs(chart);
      // A guard against a vacuous pass: an empty schema would sail through.
      expect(list.length).toBeGreaterThan(15);

      for (const knob of list) {
        const values: ChartSettingsValues = readChartSettings(chart);
        const before = values[knob.key];
        const drawn = scales(chart);

        applyChartSettings(chart, { [knob.key]: away(knob, before) });
        applyChartSettings(chart, { [knob.key]: before });

        expect(readChartSettings(chart)[knob.key], `${knob.key} reads back changed`).toEqual(before);
        // The one that matters: nothing else moved on the way there and back.
        expect(scales(chart), `${knob.key} left the scales changed`).toEqual(drawn);
      }
    });
  }

  it('leaves the volume overlay where its host put it when plot margins move', () => {
    const chart = mount();
    const overlay = chart.panes()[0].scales().find((s) => s.options.marginTop === 0.82);
    expect(overlay).toBeDefined();

    applyChartSettings(chart, { 'canvas.margins.top': 30 });

    // The dialog moved the price axis, and only the price axis.
    expect(chart.priceScaleOptions().marginTop).toBeCloseTo(0.3, 10);
    expect(overlay?.options.marginTop).toBe(0.82);
    expect(overlay?.options.marginBottom).toBe(0);
  });

  it('returns an oscillator pane to its declared band when auto-fit comes back on', () => {
    const chart = mount();
    const rsi = chart.panes()[1].priceScale;
    expect(rsi.priceRange()).toEqual({ min: 0, max: 100 });

    applyChartSettings(chart, { 'scales.autoScale': false });
    applyChartSettings(chart, { 'scales.autoScale': true });

    expect(rsi.priceRange()).toEqual({ min: 0, max: 100 });
    // Still declared, not measured: the chart-wide switch does not hand a
    // declared axis to the measuring pass, it only re-applies the declaration.
    expect(rsi.autoScale).toBe(false);
    // And it says so: the declared band is readable off the scale, which is
    // what a host greying the axis menu's auto-fit row has to go on.
    expect(chart.panes()[1].priceScale.fixedRange).toEqual({ min: 0, max: 100 });
    expect(chart.panes()[0].priceScale.fixedRange).toBeNull();
    // The price pane did follow it.
    expect(chart.priceAxisState(0)?.autoFit).toBe(true);
  });

  it('restores into a fresh chart exactly what it captured', () => {
    const source = mount();
    const state = JSON.parse(JSON.stringify(source.getState()));

    // The reload path: a new chart, the host's own series rebuilt from its
    // cached bars, then the saved state applied over the top.
    const reloaded = mount();
    const report = reloaded.restoreState(state);

    expect(report.applied).toBe(true);
    expect(report.indicators).toBe(1);
    expect(scales(reloaded)).toEqual(scales(source));
    expect(readChartSettings(reloaded)).toEqual(readChartSettings(source));

    // And the restored chart is as durable as the one it copied: a restored
    // indicator is handed its pane rather than claiming one, so it declares
    // nothing on the way in, and a scale that has forgotten it is declared
    // gives itself away the next time anything asks the chart to auto-fit.
    applyChartSettings(reloaded, { 'scales.autoScale': false });
    applyChartSettings(reloaded, { 'scales.autoScale': true });
    expect(scales(reloaded)).toEqual(scales(source));
  });

  it('gives an oscillator pane back the range the user left it at, not the declared one', () => {
    const source = mount();
    // What an axis drag on the RSI strip does: the user compressed the band by
    // hand, so it is no longer the 0..100 the indicator asks for.
    source.panes()[1].priceScale.scaleAroundCenter(1.5);
    const dragged = source.panes()[1].priceScale.priceRange();
    expect(dragged).not.toEqual({ min: 0, max: 100 });

    const reloaded = mount();
    reloaded.restoreState(JSON.parse(JSON.stringify(source.getState())));

    // The saved state is the most specific answer there is, and it has to
    // survive the indicator rebuild that happens in the middle of the restore.
    expect(reloaded.panes()[1].priceScale.priceRange()).toEqual(dragged);
    expect(reloaded.panes()[1].priceScale.autoScale).toBe(false);
    // Auto-fit still knows where home is: the band the indicator declares.
    applyChartSettings(reloaded, { 'scales.autoScale': true });
    expect(reloaded.panes()[1].priceScale.priceRange()).toEqual({ min: 0, max: 100 });
  });

  // Without a window `_attachInput` bails, and with no listeners the chart
  // never learns where the cursor is, so no crosshair is ever drawn.
  beforeEach(() => vi.stubGlobal('window', {}));
  afterEach(() => vi.unstubAllGlobals());

  // Finding 4 of the same pass: `drawTimeAxisPill` had no production caller. It
  // is the richer version of the tag the crosshair already drew on the time
  // strip, so the choice was to route the tag through it or delete it. Routed:
  // the strip is the one place a tag lands over labels that are already on the
  // canvas underneath it, which is what the pill's opaque backplate is for.
  it('draws the crosshair time tag as the axis pill, not as a bare box', () => {
    const { chart, el } = build();
    el.dispatch('pointermove', pointer('move', 450, 300, { buttons: 0 }));

    const bottom = chart.panes()[chart.panes().length - 1];
    const all = (bottom.top.ctx as unknown as RecordingContext).ops;
    // The recorder accumulates across frames, so read the latest one only.
    const ops = all.slice(all.map((o) => o.type).lastIndexOf('clearRect'));
    // The branding plate also uses roundRect, but lives inside the plot.
    const pill = ops.filter((o) => o.type === 'roundRect' && o.args[1] >= bottom.priceScale.height);
    expect(pill).toHaveLength(1);
    // 18px tall, one px clear of the axis separator: the pill's geometry and
    // not the 16px square box `drawCrosshairTag` draws.
    expect(pill[0].args[3]).toBe(18);
    // Backplate then fill: the tick labels underneath are cut out rather than
    // shown through a translucent theme colour.
    const after = ops.slice(ops.indexOf(pill[0]));
    expect(after.filter((o) => o.type === 'fill').length).toBeGreaterThanOrEqual(2);
    // And the date it is carrying is on top of it.
    expect(after.some((o) => o.type === 'fillText' && (o.text ?? '').length > 0)).toBe(true);
  });

  it('captures and restores the axis-strip switches', () => {
    const chart = mount();
    expect(readChartSettings(chart)['axisChrome.barCountdown']).toBe(false);
    expect(readChartSettings(chart)['axisChrome.sessionClock']).toBe(false);

    applyChartSettings(chart, { 'axisChrome.barCountdown': true, 'axisChrome.sessionClock': true });
    expect(chart.axisChromeOptions()).toMatchObject({ barCountdown: true, sessionClock: true });

    const reloaded = mount();
    reloaded.restoreState(JSON.parse(JSON.stringify(chart.getState())));
    expect(reloaded.axisChromeOptions()).toMatchObject({ barCountdown: true, sessionClock: true });
  });

  it('keeps a host-configured corner clock across an off and on again', () => {
    const chart = mount();
    chart.setAxisChromeOptions({ sessionClock: { showOffset: false } });

    applyChartSettings(chart, { 'axisChrome.sessionClock': false });
    applyChartSettings(chart, { 'axisChrome.sessionClock': true });

    expect(chart.axisChromeOptions().sessionClock).toEqual({ showOffset: false });
  });
});
