/**
 * The tags a pane puts on its price axis, and which one wins where they meet.
 *
 * Reported on a live chart: a study pane's value tag carried the bar
 * countdown in a second row, a clock for a bar the pane does not draw, and
 * that doubled tag ran into the study's own level tags, which painted over it.
 * The countdown now rides only on the tag of the pane that shows the price
 * source, and the readout tag, which outranks a level's tag in
 * `AXIS_LABEL_PRIORITY`, is painted after the levels so it is not covered.
 */
import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart, type AxisChromeOptions } from '../src/core/chart';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import type { Op, RecordingContext } from './helpers/fake-ctx';
import type { SeriesStyle } from '../src/render/series-style';

const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach((chart) => chart.destroy()); });

/** Five-minute bars from a random walk that runs up into the close, so RSI ends high. */
function bars(count: number): { time: number; open: number; high: number; low: number; close: number }[] {
  let s = 4242, price = 1840, vol = 1.2;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  return Array.from({ length: count }, (_, i) => {
    vol = Math.max(0.4, Math.min(6, vol * (0.9 + rnd() * 0.22)));
    const open = price, close = open + (rnd() - 0.5) * 2 * vol + (i > count - 30 ? 1.1 : 0);
    price = close;
    return { time: 1_758_000_000 + i * 300, open, high: Math.max(open, close) + rnd() * vol, low: Math.min(open, close) - rnd() * vol, close };
  });
}

const BARS = bars(220);
const LAST = BARS[BARS.length - 1];

function mount(axisChrome?: AxisChromeOptions, style?: Partial<SeriesStyle>): Chart {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as HTMLElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, theme: darkTheme,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    axisChrome,
  });
  charts.push(chart);
  chart.applySize(900, 640);
  chart.addSeries('candlestick', style === undefined ? {} : { style }).setData(BARS);
  return chart;
}

const ops = (chart: Chart, pane: number): Op[] => (chart.panes()[pane].base.ctx as unknown as RecordingContext).ops;

/** Paint every pane afresh, recording only that frame. */
function repaint(chart: Chart): void {
  for (const pane of chart.panes()) (pane.base.ctx as unknown as RecordingContext).ops.length = 0;
  chart.invalidate((m) => m.invalidateGlobal(3));
}
const texts = (chart: Chart, pane: number): string[] => ops(chart, pane).filter((o) => o.type === 'fillText').map((o) => o.text ?? '');
const CLOCK = /^\d\d:\d\d:\d\d$/;
/** The fills in the axis strip of a pane `plotWidth` px wide: its tags. */
const tagFills = (chart: Chart, pane: number): Op[] =>
  ops(chart, pane).filter((o) => o.type === 'fillRect' && o.args[0] >= chart.timeScale.width);

describe('the bar countdown', () => {
  it('rides on the price pane tag and not on a study pane tag', () => {
    const chart = mount({ barCountdown: true, clock: () => LAST.time + 100 });
    chart.addIndicator('rsi');
    repaint(chart);
    expect(chart.panes().length).toBe(2);
    expect(texts(chart, 0)).toContain('00:03:20');
    expect(texts(chart, 1).some((t) => CLOCK.test(t))).toBe(false);
  });

  it('leaves a study pane tag one row tall', () => {
    const plain = mount();
    plain.addIndicator('rsi');
    const counting = mount({ barCountdown: true, clock: () => LAST.time + 100 });
    counting.addIndicator('rsi');
    for (const chart of [plain, counting]) repaint(chart);
    const heights = (chart: Chart): number[] => tagFills(chart, 1).map((o) => o.args[3]);
    expect(heights(counting)).toEqual(heights(plain));
    // The price pane's own tag still grows by the countdown's row.
    expect(Math.max(...tagFills(counting, 0).map((o) => o.args[3]))).toBeGreaterThan(Math.max(...tagFills(plain, 0).map((o) => o.args[3])));
  });

  it('stays off a host series in a pane of its own: it counts the price source bar', () => {
    const chart = mount({ barCountdown: true, clock: () => LAST.time + 100 });
    chart.addSeries('line', { paneIndex: 1 }).setData(BARS.map((b) => ({ time: b.time, value: b.close * 0.52 })));
    repaint(chart);
    expect(texts(chart, 0)).toContain('00:03:20');
    expect(texts(chart, 1).some((t) => CLOCK.test(t))).toBe(false);
  });
});

describe('the readout tag where a level tag meets it', () => {
  it('is painted after a price line tag on the price pane', () => {
    const chart = mount();
    chart.addPriceLine({ id: 'stop', price: LAST.close - 0.3, color: '#7e57c2' });
    repaint(chart);
    const fills = tagFills(chart, 0);
    const level = fills.findIndex((o) => o.fillStyle === '#7e57c2');
    const readout = fills.findIndex((o) => o.fillStyle === darkTheme.lastPriceUp || o.fillStyle === darkTheme.lastPriceDown);
    expect(level).toBeGreaterThanOrEqual(0);
    expect(readout).toBeGreaterThan(level);
  });

  it('is painted after the study levels on a study pane', () => {
    const chart = mount();
    chart.addIndicator('rsi');
    repaint(chart);
    const all = ops(chart, 1);
    const tagAt = (text: string): number => all.findIndex((o) => o.type === 'fillText' && o.text === text && o.args[0] >= chart.timeScale.width);
    const value = texts(chart, 1).find((t) => /^\d+\.\d\d$/.test(t) && !['70.00', '50.00', '30.00'].includes(t));
    expect(value).toBeDefined();
    expect(tagAt('70.00')).toBeGreaterThanOrEqual(0);
    expect(tagAt(value!)).toBeGreaterThan(tagAt('70.00'));
  });
});

describe('the second pass that paints the readout tag', () => {
  /** Clips in one frame of the price pane: one per strip for its ladder, then the tag's own. */
  const clips = (chart: Chart): number => {
    repaint(chart);
    return ops(chart, 0).filter((o) => o.type === 'clip').length;
  };

  it('clips only the strip that carries the tag', () => {
    const right = mount();
    const both = mount();
    both.addSeries('line', { priceScaleId: 'left' }).setData(BARS.map((b) => ({ time: b.time, value: b.close * 0.52 })));
    // The left strip adds its ladder's clip and nothing more: the tag is on the right.
    expect(clips(both) - clips(right)).toBe(1);
  });

  it('is skipped when the price series shows no tag', () => {
    const shown = mount();
    const hidden = mount(undefined, { lastValueVisible: false });
    expect(clips(shown) - clips(hidden)).toBe(1);
  });
});
