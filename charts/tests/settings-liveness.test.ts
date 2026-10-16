/**
 * Every settings control must move something. A control that reads back its own
 * write but leaves the frame identical is a dead control: the option was
 * declared and stored but no renderer consumes it. This walks the whole schema,
 * flips each control to a value it does not hold, and asserts the painted op
 * stream changed.
 *
 * It is deliberately generic rather than a list of hand-written cases. A control
 * added to the schema later is audited the moment it appears, with no second
 * table to keep in step, which is the failure mode this file exists to close:
 * options that were declared, threaded and persisted, but read by no renderer.
 *
 * The chart is set up the way the reference host sets one up, because several
 * controls only have anything to move once it is: the status-line switches need
 * a `PaneLegend` attached, and the crosshair block needs a cursor on the plot.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { PaneLegend } from '../src/primitives/pane-legend';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';
import {
  chartSettingsSchema, readChartSettings, applyChartSettings,
  type ChartSettingsInput, type ChartSettingsValue, type ChartSettingsValues,
} from '../src/model/chart-settings';
import type { Bar } from '../src/model/bar';
import type { SeriesType } from '../src/model/chart-type-registry';

const T0 = 1700000000;
const MIN = 60;

registerIndicator({ id: 'settings-liveness-overlay', name: 'Distant reading', placement: 'onchart', inputs: [],
  plots: [{ key: 'reading', type: 'line', title: 'Reading' }],
  calc: data => ({ reading: data.map(bar => bar.close * 10) }),
});

/**
 * Bars whose open-vs-close verdict and close-vs-previous-close verdict
 * disagree on some bars. Without that, `colorByPreviousClose` reads as a dead
 * control when it is in fact fully wired: every bar just happens to get the
 * same colour either way.
 */
const BARS: Bar[] = (() => {
  const closes = [100, 103, 101, 104, 102, 105, 103, 106, 104, 107,
    105, 102, 106, 103, 107, 104, 108, 105, 109, 106,
    110, 107, 111, 108, 112, 109, 113, 110, 114, 111];
  return closes.map((close, i) => {
    // Opens alternate above and below the close independently of the trend, so
    // the two verdicts differ on roughly half the bars.
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
})();

interface Harness {
  chart: Chart;
  el: FakeElement;
  /** Every op every pane layer drew on the latest frame, as one string. */
  frame(): string;
}

function mount(type: SeriesType, enableWatermark = true): Harness {
  // `_attachInput` bails when there is no window, and without its listeners the
  // chart never learns where the cursor is, so the crosshair block draws nothing.
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  Object.assign(el, { clientWidth: 800, clientHeight: 600 });
  const chart = new Chart(el, {
    document: doc,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    shortcuts: false,
    timeNavigator: false,
    // The plate is off by default, and its colour and opacity controls have
    // nothing to tint while it is: turn it on so they are audited against a
    // plate that exists rather than skipped.
    statusLine: { background: true },
    // Text styling needs visible content. The false fixture branch exercises
    // the constructor default without passing a watermark override.
    watermark: enableWatermark ? true : undefined,
  });
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'ACME', interval: '1m' });
  // A baseline splits its line and its fill at `baseValue`, which defaults to
  // 0: with prices around 110 every segment would fall above it and the below-
  // base colours would never be drawn, reporting live controls as dead. Put the
  // base through the middle of the data, which is the only configuration in
  // which a baseline chart says anything.
  const series = chart.addSeries(type, type === 'baseline' ? { style: { baseValue: 107 } } : {});
  series.setData(BARS);
  // The host's symbol row. Without one the whole Readout tab has no legend to
  // act on and every switch on it would read as dead.
  // Added through the chart, not the pane: that is what registers it in the
  // legend list the status-line switches are pushed to. Fed the way the
  // reference host feeds it, because a switch over a field the host never
  // supplied hides nothing and would read as dead when it is merely unfed.
  const legend = new PaneLegend({
    id: 'symbol',
    title: 'ACME',
    params: 'Acme Corp',
    row: 0,
    actions: [],
    status: {
      logo: { width: 16, height: 16 } as unknown as CanvasImageSource,
      description: 'Acme Corporation',
      ticker: 'NYSE:ACME',
      marketStatus: { text: 'Market open', color: '#26a69a' },
      lastDayChange: { text: '+1.20 (+0.75%)', color: '#26a69a' },
    },
  });
  // The readings are a separate call, the way a host pushes them on every
  // crosshair move. Each group is tagged, so one switch hides one group.
  legend.setValues([
    { label: 'O', text: '110.00', field: 'ohlc' },
    { label: 'H', text: '112.00', field: 'ohlc' },
    { label: 'L', text: '109.00', field: 'ohlc' },
    { label: 'C', text: '111.00', field: 'ohlc' },
    { text: '+0.90 (+0.82%)', field: 'change' },
    { label: 'Vol', text: '2.07M', field: 'volume' },
    { label: 'OI', text: '1.50M', field: 'openInterest' },
    { text: '111.00' }, // untagged: the row's own last value
  ]);
  chart.addPrimitive(legend, 0);

  /** Put the cursor on the plot, so the crosshair block has something to draw. */
  const hover = (): void => {
    el.dispatch('pointermove', {
      clientX: 400, clientY: 300, pointerId: 1, pointerType: 'mouse', buttons: 0,
      preventDefault() {}, stopPropagation() {},
    });
  };
  hover();

  const recs = (): RecordingContext[] => chart.panes().flatMap((p) => [
    p.base.ctx as unknown as RecordingContext,
    p.top.ctx as unknown as RecordingContext,
  ]);
  return {
    chart, el,
    frame(): string {
      // Re-hover first: the cursor's snapped price is resolved on the move, not
      // on the repaint, so magnet mode only shows up once the pointer has moved
      // again under the new setting.
      hover();
      for (const r of recs()) r.ops = [];
      // A full invalidation. The synchronous raf paints inline, so the ops are
      // on the recorders by the time this returns.
      chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
      const recorded = recs()
        .map((r) => r.ops
          .map((o) => [o.type, o.args.join(','), o.fillStyle, o.strokeStyle, o.lineWidth, o.text, o.font].join('|'))
          .join('\n'))
        .join('\n##\n');
      // The op recorder omits globalAlpha. SVG serializes the actual paint
      // opacity, while recorded ops retain transient crosshair behavior.
      return `${recorded}\n${chart.exportSVG()}`;
    },
  };
}

/** Every value key a control carries, each with a value it does not hold. */
function flipsFor(input: ChartSettingsInput, current: ChartSettingsValues): { key: string; value: ChartSettingsValue }[] {
  if (input.type === 'colorPair') {
    const out: { key: string; value: ChartSettingsValue }[] = [
      { key: input.up.key, value: '#123456' },
      { key: input.down.key, value: '#654321' },
    ];
    if (input.enabled !== undefined) {
      out.push({ key: input.enabled.key, value: current[input.enabled.key] !== true });
    }
    return out;
  }
  const key = input.key;
  const now = current[key];
  switch (input.type) {
    case 'text': return [{ key, value: now === 'Research' ? '' : 'Research' }];
    case 'boolean': return [{ key, value: now !== true }];
    case 'color': return [{ key, value: now === '#123456' ? '#654321' : '#123456' }];
    case 'select': {
      // The furthest option that differs, not the first. `precision` reads
      // "Default" and its first alternative is 0, which is the very precision
      // a whole-number price range already formats at: the flip would land on
      // an identical frame and a live control would be reported dead.
      const others = input.options.filter((o) => o.value !== now);
      const other = others[others.length - 1];
      return other === undefined ? [] : [{ key, value: other.value }];
    }
    case 'number': {
      const min = input.min ?? 0;
      const max = input.max ?? 100;
      const step = input.step ?? 1;
      const n = typeof now === 'number' ? now : min;
      const up = Math.min(max, n + step * 2);
      return [{ key, value: up !== n ? up : Math.max(min, n - step * 2) }];
    }
    default: return [];
  }
}

/**
 * Controls whose effect is real but is not on this chart's frame, each with the
 * reason and where it is covered instead. Nothing goes in here because it was
 * inconvenient: a key here is a claim that the option is consumed elsewhere.
 */
const OFF_FRAME: ReadonlyMap<string, string> = new Map([
  ['navigation.mousePan', 'pointer behavior is exercised by navigation-settings.test.ts'],
  ['navigation.panEnabled', 'user horizontal wheel behavior is asserted below with the navigator disabled'],
  ['navigation.zoomEnabled', 'user vertical wheel behavior is asserted below with the navigator disabled'],
  // The trade layer draws nothing until a position, order or execution exists,
  // and instantiating it is not what this file is measuring. chart-settings
  // covers the round-trip; trade-ui covers the colours reaching the marks.
  ['trading.longColor', 'trade layer draws nothing without a position'],
  ['trading.shortColor', 'trade layer draws nothing without a position'],
  ['trading.orderColor', 'trade layer draws nothing without an order'],
  ['trading.tpColor', 'trade layer draws nothing without a bracket'],
  ['trading.slColor', 'trade layer draws nothing without a bracket'],
  ['trading.buyColor', 'trade layer draws nothing without an execution'],
  ['trading.sellColor', 'trade layer draws nothing without an execution'],
  // Pinning the axis where it already sits is by definition the same picture.
  // The control is live: it stops the next data change from re-fitting, which
  // is asserted below rather than through the frame.
  ['scales.autoScale', 'pinning a fitted scale draws the same frame'],
  // Magnet snaps the cursor to the primary price series' OHLC. A chart whose
  // only series is a volume histogram or column has no price series at all, so
  // there is nothing to snap to. The control is chart-wide and live on every
  // chart that plots a price, which the other eleven types here prove.
  ['canvas.crosshairMode', 'nothing to snap to without a price series'],
  ['scales.priceOnly', 'no primary series exists on a standalone volume-only chart; price-only-autoscale.test.ts covers that case'],
  // A hollow candle's up bar IS its outline, so with Borders on (the default)
  // the up body colour is the border colour and `upColor` is not read. It is
  // read the moment Borders is switched off, asserted below.
  ['symbol.upColor', 'a hollow up candle takes its outline from the border colour'],
]);

/** Every built-in type a chart's primary series can be, plus a bare chart. */
/**
 * An exemption only holds for the types it was written about. `upColor` is
 * exempt on a hollow candle and nowhere else; the magnet is exempt only where
 * no price series exists. Everything else is exempt everywhere it appears.
 */
function exempt(type: SeriesType, key: string): boolean {
  if (key === 'symbol.upColor') return type === 'hollow-candle';
  if (key === 'canvas.crosshairMode' || key === 'scales.priceOnly') return type === 'histogram' || type === 'column';
  return true;
}

const TYPES: SeriesType[] = [
  'candlestick', 'hollow-candle', 'volume-candle',
  'bar', 'high-low',
  'line', 'line-markers', 'step',
  'area', 'hlc-area', 'baseline',
  'column', 'histogram',
];

describe('no settings control is dead', () => {
  beforeEach(() => vi.stubGlobal('window', {}));
  afterEach(() => vi.unstubAllGlobals());

  for (const type of TYPES) {
    it(`every control changes the frame on a ${type} chart`, () => {
      const dead: string[] = [];
      const schema = chartSettingsSchema(mount(type).chart);
      for (const tab of schema) {
        for (const input of tab.inputs) {
          const current = readChartSettings(mount(type).chart);
          for (const flip of flipsFor(input, current)) {
            if (OFF_FRAME.has(flip.key) && exempt(type, flip.key)) continue;
            const h = mount(type);
            // These preferences need a study row and a distinct overlay extent.
            if (flip.key === 'scales.priceOnly' || flip.key === 'statusLine.indicatorsCollapsed') {
              h.chart.addIndicator('settings-liveness-overlay');
            }
            const before = h.frame();
            applyChartSettings(h.chart, { [flip.key]: flip.value });
            if (h.frame() === before) dead.push(`${tab.id}/${flip.key} = ${String(flip.value)}`);
          }
        }
      }
      expect(dead).toEqual([]);
    });
  }

  it('every control reads back exactly what was written to it', () => {
    const drift: string[] = [];
    for (const type of TYPES) {
      const schema = chartSettingsSchema(mount(type).chart);
      for (const tab of schema) {
        for (const input of tab.inputs) {
          for (const flip of flipsFor(input, readChartSettings(mount(type).chart))) {
            const h = mount(type);
            applyChartSettings(h.chart, { [flip.key]: flip.value });
            const back = readChartSettings(h.chart)[flip.key];
            if (back !== flip.value) {
              drift.push(`${type}/${tab.id}/${flip.key}: wrote ${String(flip.value)}, read ${String(back)}`);
            }
          }
        }
      }
    }
    expect(drift).toEqual([]);
  });

  it('off-frame exemptions are bounded and each is justified', () => {
    // Guards the escape hatch: a key may only sit in OFF_FRAME with a reason,
    // and the list may not quietly grow to hide a genuinely dead control.
    for (const [, why] of OFF_FRAME) expect(why.length).toBeGreaterThan(10);
    expect(OFF_FRAME.size).toBe(14);
  });
});

describe('the off-frame controls, asserted where they do act', () => {
  beforeEach(() => vi.stubGlobal('window', {}));
  afterEach(() => vi.unstubAllGlobals());

  it.each(TYPES)('navigation controls gate gestures independently on a %s chart', type => {
    const h = mount(type);
    const wheel = (pan: boolean) => {
      const prevented = vi.fn(), before = h.chart.getVisibleLogicalRange();
      h.el.dispatch('wheel', { clientX: 400, clientY: 300, deltaX: pan ? 60 : 0,
        deltaY: pan ? 0 : -100, deltaMode: 0, preventDefault: prevented });
      return { changed: JSON.stringify(before) !== JSON.stringify(h.chart.getVisibleLogicalRange()), prevented: prevented.mock.calls.length };
    };
    for (const pan of [false, true]) for (const zoom of [false, true]) {
      applyChartSettings(h.chart, { 'navigation.panEnabled': pan, 'navigation.zoomEnabled': zoom });
      expect(wheel(true)).toEqual({ changed: pan, prevented: Number(pan) });
      expect(wheel(false)).toEqual({ changed: zoom, prevented: Number(zoom) });
    }
    h.chart.destroy();
  });

  it('keeps watermark styling dormant by default and applies it when enabled', () => {
    const h = mount('candlestick', false);
    expect(readChartSettings(h.chart)['watermark.visible']).toBe(false);
    const before = h.frame();
    const style = {
      'watermark.text': 'Research', 'watermark.color': '#123456',
      'watermark.opacity': 0.25, 'watermark.fontSize': 40,
    };
    applyChartSettings(h.chart, style);
    expect(readChartSettings(h.chart)).toMatchObject(style);
    expect(h.frame()).toBe(before);
    applyChartSettings(h.chart, { 'watermark.visible': true });
    expect(h.frame()).not.toBe(before);
    const svg = h.chart.exportSVG();
    expect(svg).toContain('>Research</text>');
    expect(svg).toContain('fill="#123456" opacity="0.25"');
    expect(svg).toContain('font-size="40"');
    applyChartSettings(h.chart, { 'watermark.visible': false });
    expect(h.frame()).toBe(before);
    h.chart.destroy();
  });

  it("a hollow candle's up colour is read the moment borders are off", () => {
    const h = mount('hollow-candle');
    applyChartSettings(h.chart, { 'symbol.borderVisible': false });
    const before = h.frame();
    applyChartSettings(h.chart, { 'symbol.upColor': '#123456' });
    expect(h.frame()).not.toBe(before);
  });

  it('magnet snaps the crosshair as soon as the chart plots a price', () => {
    const h = mount('histogram');
    // Same chart, now with a price series on it: the control that had nothing
    // to snap to has something.
    h.chart.addSeries('line').setData(BARS);
    const before = h.frame();
    applyChartSettings(h.chart, { 'canvas.crosshairMode': 'magnet' });
    expect(h.frame()).not.toBe(before);
  });

  it('turning auto-scale off stops the next bar from re-fitting the axis', () => {
    // A print far outside the fitted range: an auto scale moves to hold it, a
    // pinned one must not. That is what the control buys, and it is invisible
    // to a frame diff taken the instant it is switched.
    const far = { time: T0 + 40 * MIN, open: 400, high: 410, low: 390, close: 405 };

    const pinned = mount('candlestick');
    applyChartSettings(pinned.chart, { 'scales.autoScale': false });
    const pinnedBefore = pinned.chart.panes()[0].priceScale.priceRange();
    pinned.chart.primarySeries()?.update(far);
    pinned.frame();
    expect(pinned.chart.panes()[0].priceScale.priceRange()).toEqual(pinnedBefore);

    const auto = mount('candlestick');
    const autoBefore = auto.chart.panes()[0].priceScale.priceRange();
    auto.chart.primarySeries()?.update(far);
    auto.frame();
    expect(auto.chart.panes()[0].priceScale.priceRange()).not.toEqual(autoBefore);
  });
});
