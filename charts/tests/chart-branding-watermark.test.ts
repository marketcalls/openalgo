import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { Chart, type ChartOptions, type BrandingChangedEvent } from '../src/core/chart';
import { LogoWatermark } from '../src/primitives/watermark';
import { TextWatermark } from '../src/primitives/text-watermark';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { applyChartSettings, chartSettingsSchema, readChartSettings } from '../src/model/chart-settings';
import { DrawingController } from '../src/draw/index';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
beforeAll(() => { (globalThis as unknown as { window: unknown }).window ??= {}; });
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function mount(options: ChartOptions = {}) {
  const doc = fakeDocument();
  const opened: unknown[][] = [];
  Object.defineProperty(doc, 'defaultView', { value: { open: (...args: unknown[]) => opened.push(args) } });
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} }, ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData([
    { time: 1700000000, open: 100, high: 102, low: 99, close: 101 },
    { time: 1700000060, open: 101, high: 103, low: 100, close: 102 },
  ]);
  return { chart, el, opened };
}

const logos = (chart: Chart) => chart.panes().flatMap((p) => p.primitives()).filter((p) => p instanceof LogoWatermark);
const texts = (chart: Chart) => chart.panes().flatMap((p) => p.primitives()).filter((p) => p instanceof TextWatermark);
const click = (el: FakeElement, x = 28, y = 550, extra = {}) => {
  el.dispatch('pointerdown', pointer('down', x, y, extra));
  el.dispatch('pointerup', pointer('up', x, y, extra));
};

describe('owned chart branding', () => {
  it('paints one vector mark by default and leaves the text watermark off', () => {
    const { chart } = mount();
    expect(logos(chart)).toHaveLength(1);
    expect(texts(chart)).toHaveLength(0);
    expect(chart.exportSVG()).toContain('M367.5 255.5');
    expect(chart.exportSVG()).not.toContain('<image');
  });

  it('removes only its own mark and follows the visible bottom pane', () => {
    const { chart } = mount();
    const legacy = new LogoWatermark({ image: { width: 32, height: 32 } as never });
    chart.addPrimitive(legacy);
    const owned = logos(chart).find((p) => p !== legacy)!;
    expect(owned).toBeDefined();
    chart.addSeries('line', { paneIndex: 1 });
    expect(chart.panes()[1].hasPrimitive(owned)).toBe(true);
    chart.maximizePane(0);
    expect(chart.panes()[0].hasPrimitive(owned)).toBe(true);
    chart.setBranding(false);
    chart.maximizePane(0);
    expect(logos(chart)).toEqual([legacy]);
    chart.setBranding(true);
    chart.setBranding(true);
    expect(logos(chart)).toHaveLength(2);
  });

  it('opens a completed touch click once and consumes drawing and trading clicks', () => {
    const { chart, el, opened } = mount();
    let clicks = 0;
    chart.subscribeClick(() => { clicks++; });
    chart.on('click', () => { clicks++; });
    chart.setPlacementMode(true);
    click(el, 28, 550, { pointerType: 'touch' });
    expect(opened).toHaveLength(1);
    expect(opened[0][0]).toMatch(/^https:\/\/openalgo.in\?/);
    expect(opened[0].slice(1)).toEqual(['_blank', 'noopener,noreferrer']);
    expect(clicks).toBe(0);
  });

  it('does not activate a drag, cancelled pointer, secondary button, or unmatched release', () => {
    const { el, opened } = mount();
    el.dispatch('pointerdown', pointer('down', 28, 550));
    el.dispatch('pointermove', pointer('move', 120, 550));
    el.dispatch('pointerup', pointer('up', 28, 550));
    el.dispatch('pointerdown', pointer('down', 28, 550));
    el.dispatch('pointercancel', pointer('up', 28, 550));
    el.dispatch('pointerup', pointer('up', 28, 550));
    click(el, 28, 550, { button: 2, buttons: 2 });
    expect(opened).toEqual([]);
  });

  it('ignores a pen barrel button and accepts a normal pen tip click', () => {
    const { el, opened } = mount();
    click(el, 28, 550, { pointerType: 'pen', button: 2, buttons: 2 });
    expect(opened).toEqual([]);
    click(el, 28, 550, { pointerType: 'pen' });
    expect(opened).toHaveLength(1);
  });

  it('does not activate when the release moved without an intermediate move event', () => {
    const { el, opened } = mount();
    el.dispatch('pointerdown', pointer('down', 28, 550));
    el.dispatch('pointerup', pointer('up', 300, 550));
    expect(opened).toEqual([]);
  });

  it('recovers a missed mouse release without activating and leaves the next hover and drag usable', () => {
    const { chart, el, opened } = mount();
    let clicks = 0;
    let crosshair = 0;
    let pans = 0;
    chart.on('click', () => { clicks++; });
    chart.on('crosshair:move', () => { crosshair++; });
    chart.on('pan', () => { pans++; });
    el.dispatch('pointerdown', pointer('down', 28, 550));
    el.dispatch('pointermove', pointer('move', 28, 550, { buttons: 0 }));
    el.dispatch('pointermove', pointer('move', 200, 200, { buttons: 0 }));
    expect(opened).toEqual([]);
    expect(clicks).toBe(0);
    expect(crosshair).toBeGreaterThan(0);
    el.dispatch('pointerdown', pointer('down', 300, 300));
    el.dispatch('pointermove', pointer('move', 420, 300));
    expect(pans).toBeGreaterThan(0);
    el.dispatch('pointerup', pointer('up', 420, 300));
  });

  it('does not carry a pending link across a pinch or a branding replacement', () => {
    const { chart, el, opened } = mount();
    el.dispatch('pointerdown', pointer('down', 28, 550, { pointerType: 'touch' }));
    el.dispatch('pointerdown', pointer('down', 300, 300, { pointerType: 'touch', pointerId: 2 }));
    el.dispatch('pointerup', pointer('up', 300, 300, { pointerType: 'touch', pointerId: 2 }));
    el.dispatch('pointerup', pointer('up', 28, 550, { pointerType: 'touch' }));
    el.dispatch('pointerdown', pointer('down', 28, 550));
    chart.setBranding({ href: 'https://example.com' });
    el.dispatch('pointerup', pointer('up', 28, 550));
    expect(opened).toEqual([]);
  });

  it.each([[2, 1], [1, 2]])('consumes a complete branding pinch while placing, releasing pointers %s then %s', (first, last) => {
    const { chart, el, opened } = mount();
    chart.setPlacementMode(true);
    const clicks: unknown[] = [];
    chart.on('click', (event) => clicks.push(event));
    el.dispatch('pointerdown', pointer('down', 28, 550, { pointerType: 'touch', pointerId: 1 }));
    el.dispatch('pointerdown', pointer('down', 300, 300, { pointerType: 'touch', pointerId: 2 }));
    const release = (id: number) => el.dispatch('pointerup', pointer('up', id === 1 ? 28 : 300, id === 1 ? 550 : 300, { pointerType: 'touch', pointerId: id }));
    release(first);
    release(last);
    expect(opened).toEqual([]);
    expect(clicks).toEqual([]);
    click(el, 300, 200, { pointerType: 'touch' });
    expect(clicks).toHaveLength(1);
  });

  it('supports custom sources without persisting host branding or mutating returned options', () => {
    const { chart } = mount({ branding: { src: 'https://example.com/logo.png', href: 'https://example.com' } });
    const opts = chart.brandingOptions();
    expect(opts).toMatchObject({ src: 'https://example.com/logo.png' });
    if (opts) opts.href = 'https://changed.example';
    expect(chart.brandingOptions()).toMatchObject({ href: 'https://example.com' });
    expect(JSON.stringify(chart.getState())).not.toContain('example.com');
  });

  it('does not execute an unsafe custom href', () => {
    const { el, opened } = mount({ branding: { href: 'javascript:alert(1)' } });
    click(el);
    expect(opened).toEqual([]);
  });

  it('notifies host links synchronously with a defensive snapshot and supports cleanup', () => {
    const { chart } = mount();
    const seen: BrandingChangedEvent[] = [];
    const off = chart.on('branding:changed', (value) => {
      const options = value as BrandingChangedEvent;
      expect(chart.brandingOptions()).toEqual(options);
      seen.push(options);
    });
    chart.setBranding(false);
    expect(seen).toEqual([false]);
    chart.setBranding({ href: 'https://example.com', label: 'Research charts', padding: { x: 9, y: 8 } });
    expect(seen[1]).toMatchObject({ href: 'https://example.com', label: 'Research charts' });
    const received = seen[1];
    if (received) {
      received.href = 'https://changed.example';
      if (typeof received.padding === 'object') received.padding.x = 99;
    }
    expect(chart.brandingOptions()).toMatchObject({ href: 'https://example.com', padding: { x: 9, y: 8 } });
    off();
    chart.setBranding(true);
    expect(seen).toHaveLength(2);
  });

  it('keeps the navigator clear of a revealed corner label on a narrow chart', () => {
    const { chart, el } = mount({ timeNavigator: { fadeSeconds: 0 }, branding: { revealSeconds: 0 } });
    chart.applySize(320, 600);
    const nav = chart.panes()[0].primitives().find((p) => p instanceof TimeNavigator)! as TimeNavigator;
    el.dispatch('pointermove', pointer('move', 200, 550, { buttons: 0 }));
    expect(nav.hitTest(60, 550)).not.toBeNull();
    el.dispatch('pointermove', pointer('move', 28, 550, { buttons: 0 }));
    expect(nav.hitTest(60, 550)).toBeNull();
  });
});

describe('a drawing over the brand mark', () => {
  /**
   * The mark sits in a corner of the plot, which is also where a note gets
   * pinned to the screen. A press there is meant for whatever the user can
   * see and grab, and the mark is the one thing on the chart that never needs
   * to be: its link is a courtesy, a drawing is the user's work.
   */
  function withNote() {
    // Frames are not run: the mark's reveal asks for one frame after another,
    // which a synchronous frame source would answer recursively.
    const rig = mount({ raf: { schedule: () => 1, cancel: () => {} } });
    const draw = new DrawingController(rig.chart);
    const rect = rig.chart.plotRect(0)!;
    // Anchored just up and left of the mark's centre, so the note's box covers it.
    const note = draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 16 / rect.width, y: 540 / rect.height }], text: { value: 'Pinned over the corner mark' } });
    return { ...rig, draw, note };
  }

  it('takes a press and a drag meant for the drawing, not the link', () => {
    const { el, draw, note, opened } = withNote();
    const before = draw.get(note.id)!.viewportPoints![0];
    el.dispatch('pointermove', pointer('move', 28, 550, { buttons: 0 }));
    el.dispatch('pointerdown', pointer('down', 28, 550));
    for (let i = 1; i <= 5; i++) el.dispatch('pointermove', pointer('move', 28 + i * 30, 550 - i * 40));
    el.dispatch('pointerup', pointer('up', 178, 350));
    expect(opened).toEqual([]);
    const after = draw.get(note.id)!.viewportPoints![0];
    expect(after.x).toBeGreaterThan(before.x);
    expect(after.y).toBeLessThan(before.y);
  });

  it('selects the drawing on a click, lights it on hover and hands it the double click', () => {
    const { chart, el, draw, note, opened } = withNote();
    const hovered: unknown[] = [];
    chart.on('hover', event => hovered.push((event as { id: string | null }).id));
    el.dispatch('pointermove', pointer('move', 28, 550, { buttons: 0 }));
    expect(hovered[hovered.length - 1]).toBe(`draw:${note.id}`);
    click(el);
    expect(opened).toEqual([]);
    expect(draw.selection()).toEqual([note.id]);
    const doubles: unknown[] = [];
    chart.on('dblclick', event => doubles.push(event));
    el.dispatch('dblclick', { clientX: 28, clientY: 550, preventDefault() {}, stopPropagation() {} });
    expect(doubles).toHaveLength(1);
  });

  it('hands a press on a line crossing the mark to the line', () => {
    const { chart, el, opened } = mount({ raf: { schedule: () => 1, cancel: () => {} } });
    const clicks: string[] = [];
    chart.subscribeClick(id => clicks.push(id));
    chart.addPriceLine({ price: chart.coordinateToPrice(550, 0)!, id: 'order-line', color: '#2f6df6' });
    click(el);
    expect(opened).toEqual([]);
    expect(clicks).toEqual(['order-line']);
  });

  it('still opens the link where no drawing covers the mark', () => {
    const { el, draw, note, opened } = withNote();
    draw.remove(note.id);
    click(el);
    expect(opened).toHaveLength(1);
  });
});

describe('chart text watermark settings', () => {
  it('offers shared controls that render automatic context, custom text, and reset to off', () => {
    const { chart } = mount();
    const keys = chartSettingsSchema(chart).find((tab) => tab.id === 'appearance')!.inputs.map((i) => i.key);
    expect(keys).toEqual(expect.arrayContaining(['watermark.visible', 'watermark.text', 'watermark.color', 'watermark.opacity', 'watermark.fontSize']));
    chart.setDataContext({ symbol: 'NIFTY', interval: '5m' });
    applyChartSettings(chart, { 'watermark.visible': true });
    expect(chart.exportSVG()).toContain('>NIFTY 5m</text>');
    applyChartSettings(chart, { 'watermark.text': 'Research', 'watermark.color': '#123456', 'watermark.opacity': 0.25, 'watermark.fontSize': 40 });
    const svg = chart.exportSVG();
    expect(svg).toContain('>Research</text>');
    expect(svg).toContain('fill="#123456"');
    expect(svg).toContain('opacity="0.25"');
    expect(svg).toContain('font-size="40"');
    const defaults = Object.fromEntries(chartSettingsSchema(chart).flatMap((tab) => tab.inputs)
      .filter((input) => input.type !== 'colorPair').map((input) => [input.key, input.default]));
    applyChartSettings(chart, defaults);
    expect(texts(chart)).toHaveLength(0);
  });

  it('keeps visibility on partial updates and tracks context only while text is blank', () => {
    const { chart } = mount({ watermark: { visible: true } });
    chart.setDataContext({ symbol: 'NIFTY', interval: '5m' });
    expect(chart.exportSVG()).toContain('>NIFTY 5m</text>');
    chart.setDataContext({ symbol: 'INFY', interval: '1h' });
    expect(chart.exportSVG()).toContain('>INFY 1h</text>');
    chart.setWatermarkOptions({ text: 'Research' });
    chart.setDataContext({ symbol: 'RELIANCE', interval: '1d' });
    expect(chart.exportSVG()).toContain('>Research</text>');
    chart.setWatermarkOptions({ text: '  ' });
    expect(chart.exportSVG()).toContain('>RELIANCE 1d</text>');
    chart.setDataContext(undefined);
    expect(chart.exportSVG()).not.toContain('>RELIANCE 1d</text>');
    expect(chart.watermarkOptions().visible).toBe(true);
  });

  it('round trips preferences, validates restored values, and leaves old layouts off', () => {
    const { chart } = mount({ watermark: { visible: true, text: 'Research', color: '#abcdef', opacity: 0.3, fontSize: 48 } });
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    const { chart: restored } = mount();
    restored.restoreState(saved);
    expect(restored.exportSVG()).toContain('>Research</text>');
    expect(readChartSettings(restored)['watermark.fontSize']).toBe(48);
    restored.restoreState({ ...saved, watermark: { visible: 'yes', text: {}, opacity: Infinity, fontSize: -100, color: 3, unknown: () => {} } });
    expect(restored.watermarkOptions()).toMatchObject({ visible: true, text: 'Research', opacity: 0.3, fontSize: 10, color: '#abcdef' });
    expect(JSON.stringify(restored.getState())).not.toContain('unknown');
    const { chart: old } = mount();
    delete saved.watermark;
    old.restoreState(saved);
    expect(old.watermarkOptions().visible).toBe(false);
  });

  it('keeps Replay and host text primitives independent and follows maximization', () => {
    const { chart } = mount({ watermark: true });
    chart.setDataContext({ symbol: 'NIFTY', interval: '5m' });
    const replay = new TextWatermark({ text: 'Replay' });
    chart.addPrimitive(replay);
    const owned = texts(chart).find((p) => p !== replay)!;
    chart.addSeries('line', { paneIndex: 1 });
    chart.maximizePane(1);
    expect(chart.panes()[1].hasPrimitive(owned)).toBe(true);
    chart.setWatermarkOptions(false);
    expect(texts(chart)).toEqual([replay]);
  });
});
