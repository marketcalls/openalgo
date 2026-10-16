/**
 * Three things the legend row was getting wrong, all reported from a live chart.
 *
 * 1. **An invisible plot still reserved the width of its number.** A study that
 *    draws a column at zero alpha so a marker has a gapless series to anchor to
 *    is a normal thing to write, and the row printed its reading in a fully
 *    transparent colour: nothing visible, the full width of a price, sitting
 *    between the parameters and the first real value. From the outside that is
 *    a legend with a hole in it.
 * 2. **The action glyphs were sized from the text.** A 9px drawing adrift in a
 *    16px button, which reads as an afterthought rather than a control.
 * 3. **There was no way to see the code a study was written from.** The gear
 *    opens what it is set to; nothing opened what it is.
 *
 * The assertions are geometric rather than visual, because the row is canvas
 * and a screenshot is not a test. Every one of them fails against the behaviour
 * that shipped, which is the bar this repository sets for adding one.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { PaneLegend } from '../src/primitives/pane-legend';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';
import { isInvisible } from '../src/render/pill';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { IndicatorDescriptor, IndicatorPlot } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { LegendValue } from '../src/primitives/pane-legend';

function paint(legend: PaneLegend, width: number, hoverId?: string, dpr = 1): RecordingContext {
  const { ctx, rec } = makeCtx();
  const rc: PrimitiveRenderContext = {
    priceScale: new PriceScale(), timeScale: new TimeScale(), dataLayer: new DataLayer(),
    plotWidth: width, plotHeight: 200, priceAxisWidth: 60, dpr, theme: darkTheme, hoverId,
  };
  legend.draw(ctx, rc);
  return rec;
}

/** The buttons the last paint laid down, in media px. */
function buttonsOf(legend: PaneLegend): { id: string; x: number; y: number }[] {
  return (legend as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
}

// ── 1. an invisible reading ────────────────────────────────────────────────

/** A host that records what the legend was asked to print. */
function rig(source: Bar[]): { host: IndicatorHost; printed: LegendValue[][] } {
  const printed: LegendValue[][] = [];
  const host: IndicatorHost = {
    addIndicatorLegend: () =>
      ({ setOptions: () => {}, setValues: (v: LegendValue[]) => { printed.push(v); } }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    addIndicatorSeries: (): SeriesApi => ({
      setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
      applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
      createMarkers: () => ({ setMarkers: () => {} }) as never,
    }),
    addIndicatorLevel: () => ({}) as never,
    removeIndicatorLevel: () => {},
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    sourceBars: () => source,
    nextPaneIndex: () => 2,
    setPaneRange: () => {},
    tickSize: () => 0.05,
  };
  return { host, printed };
}

const bars = (closes: number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1000 + i * 60, open: c, high: c, low: c, close: c }));

/** Two constant columns, coloured by the caller, so only the colours differ. */
function twoPlots(id: string, colors: [string, string]): IndicatorDescriptor {
  const plot = (key: string, color: string): IndicatorPlot =>
    ({ key, type: 'line', title: key, style: { color } });
  return {
    id, name: id, placement: 'onchart', inputs: [],
    plots: [plot('anchor', colors[0]), plot('band', colors[1])],
    calc: (b) => ({ anchor: b.map(() => 101), band: b.map(() => 99) }),
  };
}

/** The readings one descriptor printed on its last legend update. */
function readings(id: string, colors: [string, string]): LegendValue[] {
  const { host, printed } = rig(bars([100, 101, 102]));
  const inst = new IndicatorInstance(host, twoPlots(id, colors));
  inst.recompute();
  inst.updateLegendValues();
  return printed[printed.length - 1] ?? [];
}

describe('a plot nobody can see has no number to read', () => {
  it('prints both readings when both plots are visible', () => {
    // The control. Without it, an implementation that printed nothing at all
    // would pass the test below and look like a fix.
    const out = readings('legend-visible-pair', ['#26a69a', '#ef5350']);
    expect(out.map((r) => r.text)).toEqual(['101.00', '99.00']);
  });

  it('drops the reading of a fully transparent plot', () => {
    // The reported shape: an invisible mid-body line declared first so markers
    // anchor to a series with a bar on every time, then the real band. What
    // shipped printed both, and the first was a price-width blank.
    const out = readings('legend-invisible-anchor', ['rgba(192,192,192,0)', '#ef5350']);
    expect(out.map((r) => r.text)).toEqual(['99.00']);
  });

  it('drops it however the transparency is spelled', () => {
    // Eight-digit hex is the other way a compiler emits alpha, and a check
    // written against `rgba(` only would let this one through.
    const out = readings('legend-invisible-hex', ['#c0c0c000', '#ef5350']);
    expect(out.map((r) => r.text)).toEqual(['99.00']);
  });

  it('keeps a reading whose colour cannot be parsed', () => {
    // `isInvisible` must answer "no" for a string it does not understand. A
    // named colour, a `color-mix()`, a custom property: treating an
    // unparseable colour as invisible would silently blank real readings, and
    // that is a worse failure than the one this fixes.
    const out = readings('legend-named-colour', ['rebeccapurple', '#ef5350']);
    expect(out.map((r) => r.text)).toEqual(['101.00', '99.00']);
    expect(isInvisible('rebeccapurple')).toBe(false);
    expect(isInvisible('var(--up)')).toBe(false);
    expect(isInvisible('rgba(0,0,0,0)')).toBe(true);
    expect(isInvisible('#00000000')).toBe(true);
    // Barely there is still there. Only zero is nothing.
    expect(isInvisible('rgba(0,0,0,0.01)')).toBe(false);
  });
});

// ── 2. the size of an action glyph ─────────────────────────────────────────

/** Every path point the frame laid down, which for a hovered row is the glyph. */
function glyphPoints(rec: RecordingContext): [number, number][] {
  const out: [number, number][] = [];
  for (const op of rec.ops) {
    if (op.type === 'moveTo' || op.type === 'lineTo') out.push([op.args[0], op.args[1]]);
    else if (op.type === 'quadraticCurveTo') out.push([op.args[0], op.args[1]], [op.args[2], op.args[3]]);
    else if (op.type === 'arc') {
      out.push([op.args[0] - op.args[2], op.args[1] - op.args[2]], [op.args[0] + op.args[2], op.args[1] + op.args[2]]);
    }
  }
  return out;
}

/** The bounding box of everything stroked between the hover plate and the end. */
function glyphExtent(rec: RecordingContext): { w: number; h: number } {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const op of rec.ops) {
    const pairs: [number, number][] =
      op.type === 'moveTo' || op.type === 'lineTo' ? [[op.args[0], op.args[1]]]
      : op.type === 'quadraticCurveTo' ? [[op.args[0], op.args[1]], [op.args[2], op.args[3]]]
      : op.type === 'arc' ? [[op.args[0] - op.args[2], op.args[1] - op.args[2]], [op.args[0] + op.args[2], op.args[1] + op.args[2]]]
      : [];
    for (const [x, y] of pairs) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  }
  return { w: maxX - minX, h: maxY - minY };
}

describe('an action glyph is sized from its button, not from the text', () => {
  it('draws a glyph larger than the text-derived one it replaced', () => {
    // What shipped was `font * 0.42` at font 11: a half-extent of 4.62, so a
    // 9.24px drawing in a 16px square. Anything still tied to the font fails
    // this, and so does anything that shrank.
    const legend = new PaneLegend({ id: 'study', title: 'S', actions: ['settings'] });
    const extent = glyphExtent(paint(legend, 400, 'study::row'));
    expect(extent.w).toBeGreaterThan(9.24);
    expect(extent.h).toBeGreaterThan(9.24);
    // And it still fits inside its button with clearance on both sides.
    expect(extent.w).toBeLessThanOrEqual(16);
  });

  it('leaves the glyph alone when only the font changes', () => {
    // The point of the move: the icon belongs to the box. Two rows at
    // different text sizes must draw the same control, or a compact legend
    // gets toy buttons. Against the old code these differ by a third.
    const small = new PaneLegend({ id: 'a', title: 'A', actions: ['settings'], font: 9 });
    const large = new PaneLegend({ id: 'b', title: 'B', actions: ['settings'], font: 15 });
    const a = glyphExtent(paint(small, 400, 'a::row'));
    const b = glyphExtent(paint(large, 400, 'b::row'));
    expect(b.w).toBeCloseTo(a.w, 6);
    expect(b.h).toBeCloseTo(a.h, 6);
  });

  it('grows the glyph, the button and the row together when the host asks', () => {
    const plain = new PaneLegend({ id: 'a', title: 'A', actions: ['settings'] });
    const big = new PaneLegend({ id: 'b', title: 'B', actions: ['settings'], iconSize: 24 });
    expect(glyphExtent(paint(big, 400, 'b::row')).w)
      .toBeGreaterThan(glyphExtent(paint(plain, 400, 'a::row')).w);

    // The hit box follows the drawing, or the button is bigger only to look at.
    const button = buttonsOf(big)[0];
    expect(big.hitTest(button.x + 22, button.y + 8)?.externalId).toBe('b::settings');
    expect(plain.hitTest(buttonsOf(plain)[0].x + 22, buttonsOf(plain)[0].y + 8)?.externalId)
      .not.toBe('a::settings');
  });

  it('stacks rows against the taller row so they cannot overlap', () => {
    // Row 1 of a chart with 24px buttons must clear row 0's buttons, not sit at
    // the default 18. Nothing outside the primitive knows the row height, so
    // if this is wrong two legends draw through each other.
    const row0 = new PaneLegend({ id: 'a', title: 'A', row: 0, iconSize: 24, actions: [] });
    const row1 = new PaneLegend({ id: 'b', title: 'B', row: 1, iconSize: 24, actions: [] });
    const titleY = (rec: RecordingContext): number =>
      rec.ops.filter((op) => op.type === 'fillText')[0].args[1];
    const first = titleY(paint(row0, 400));
    const second = titleY(paint(row1, 400));
    expect(second - first).toBeGreaterThanOrEqual(24);
    // And the two hit boxes do not meet.
    expect(row0.hitTest(10, second)).toBeNull();
  });

  it('refuses a size it cannot draw rather than drawing nonsense', () => {
    // A host reading a number off a stylesheet can hand this anything.
    for (const size of [0, -4, 5, 400, Number.NaN]) {
      const legend = new PaneLegend({ id: 'x', title: 'X', actions: ['settings'], iconSize: size });
      const rec = paint(legend, 400, 'x::row');
      const extent = glyphExtent(rec);
      expect(extent.w).toBeGreaterThan(0);
      expect(extent.w).toBeLessThanOrEqual(28);
      expect(buttonsOf(legend)).toHaveLength(1);
    }
  });
});

// ── 3. the source button ───────────────────────────────────────────────────

describe('the source button', () => {
  it('draws, hit-tests and sits beside the gear', () => {
    const legend = new PaneLegend({
      id: 'indicator:1', title: 'S', actions: ['hide', 'settings', 'source', 'close'],
    });
    paint(legend, 400, 'indicator:1::row');
    const ids = buttonsOf(legend).map((b) => b.id);
    expect(ids).toEqual([
      'indicator:1::hide', 'indicator:1::settings', 'indicator:1::source', 'indicator:1::close',
    ]);
    const button = buttonsOf(legend).find((b) => b.id.endsWith('::source'))!;
    expect(legend.hitTest(button.x + 8, button.y + 8)?.externalId).toBe('indicator:1::source');
  });

  it('draws a glyph of its own rather than reusing another', () => {
    // A `switch` with no arm for a new action falls through and strokes an
    // empty path: the button hit-tests, the row looks like it has a gap, and
    // nothing anywhere says why. That is exactly how this would ship broken.
    const source = new PaneLegend({ id: 'a', title: 'A', actions: ['source'] });
    const gear = new PaneLegend({ id: 'b', title: 'B', actions: ['settings'] });
    const drawn = glyphExtent(paint(source, 400, 'a::row'));
    expect(drawn.w).toBeGreaterThan(0);
    expect(drawn.h).toBeGreaterThan(0);
    // Two braces are wider than they are tall; a gear is square. Without this
    // the test above passes on a glyph copied from the wrong arm.
    expect(drawn.w).not.toBeCloseTo(glyphExtent(paint(gear, 400, 'b::row')).w, 6);
  });

  it('opens the braces the right way round', () => {
    // Drawn from a `side` of -1 and 1, and the hooks and the waist take
    // OPPOSITE signs from it: the hooks reach inward, the waist pinches
    // outward. Give them the same sign and the pair comes out mirrored, `} {`,
    // which is a mark that means nothing. That is what first shipped here, and
    // it is invisible to any assertion about the glyph's size, because a
    // mirrored pair is exactly as wide as a correct one.
    //
    // What tells them apart: on a correct `{`, the leftmost point of the whole
    // drawing is the waist, which sits at the vertical middle. On the mirrored
    // one it is a hook, at the top or the bottom.
    const legend = new PaneLegend({ id: 'a', title: 'A', actions: ['source'] });
    const points = glyphPoints(paint(legend, 400, 'a::row'));
    expect(points.length).toBeGreaterThan(0);
    const ys = points.map((p) => p[1]);
    const middle = (Math.min(...ys) + Math.max(...ys)) / 2;
    const height = Math.max(...ys) - Math.min(...ys);
    const leftmost = points.reduce((a, b) => (b[0] < a[0] ? b : a));
    const rightmost = points.reduce((a, b) => (b[0] > a[0] ? b : a));
    expect(Math.abs(leftmost[1] - middle)).toBeLessThan(height * 0.1);
    expect(Math.abs(rightmost[1] - middle)).toBeLessThan(height * 0.1);
  });

  it('is left out of a row that did not ask for one', () => {
    const legend = new PaneLegend({ id: 'plain', title: 'P' });
    paint(legend, 400, 'plain::row');
    expect(buttonsOf(legend).map((b) => b.id)).toEqual([
      'plain::hide', 'plain::settings', 'plain::close',
    ]);
  });
});

// ── 4. the chart decides who gets one, and what pressing it means ──────────

describe('a descriptor that says it has source gets a button that reaches the host', () => {
  const charts: Chart[] = [];
  afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

  const makeChart = (legendIconSize?: number): Chart => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 0 }, legendIconSize,
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(Array.from({ length: 60 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100 + i, high: 104 + i, low: 98 + i, close: 102 + i,
    })));
    charts.push(chart);
    return chart;
  };

  /** A minimal study, with or without source, registered under its own id. */
  const register = (id: string, hasSource: boolean): void => {
    registerIndicator({
      id, name: id, placement: 'onchart', hasSource, inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'V', style: { color: '#26a69a' } }],
      calc: (b) => ({ v: b.map((bar) => bar.close) }),
    });
  };

  /** The actions the legend of a freshly added indicator was given. */
  const actionsFor = (chart: Chart, id: string): readonly string[] => {
    const instance = chart.addIndicator(id);
    const legend = chart.panes()[instance.paneIndex].primitives()
      .find((p) => p instanceof PaneLegend && p.options().id === `indicator:${instance.id}`) as PaneLegend;
    return legend.options().actions ?? [];
  };

  it.each(['transparent', ' TRANSPARENT '])('omits a reading painted with %s', (color) => {
    const id = `css-transparent-${color.length}`;
    registerIndicator(twoPlots(id, [color, '#ef5350']));
    const chart = makeChart();
    const legend = chart.addIndicator(id).legend()!;
    const text = paint(legend, 800).ops.filter((op) => op.type === 'fillText').map((op) => op.text);
    expect(text).toContain('99.00');
    expect(text).not.toContain('101.00');
  });

  it.each(['constructor', 'setter'])('keeps later host rows clear of the %s button size', (via) => {
    const chart = makeChart(via === 'constructor' ? 28 : undefined);
    const first = new PaneLegend({ id: 'first-row', title: 'First' });
    chart.addPrimitive(first);
    if (via === 'setter') chart.setLegendIconSize(28);
    const second = new PaneLegend({ id: 'second-row', title: 'Second', iconSize: 16 });
    chart.addPrimitive(second);
    const firstY = paint(first, 800).ops.find((op) => op.type === 'fillText')!.args[1];
    const secondY = paint(second, 800).ops.find((op) => op.type === 'fillText')!.args[1];
    expect(secondY - firstY).toBeGreaterThanOrEqual(28);
    expect(first.hitTest(10, secondY)).toBeNull();
  });

  it.each([NaN, Infinity, -Infinity])('ignores a nonfinite initial button size: %s', (size) => {
    const chart = makeChart(size);
    const legend = new PaneLegend({ id: 'host-sized-row', title: 'Host', iconSize: 24 });
    chart.addPrimitive(legend);
    expect(chart.legendIconSize()).toBeUndefined();
    expect(legend.options().iconSize).toBe(24);
  });

  it('puts the button next to the gear, and only on a descriptor that asked', () => {
    register('has-source-study', true);
    register('no-source-study', false);
    const chart = makeChart();
    const withSource = actionsFor(chart, 'has-source-study');
    expect(withSource).toContain('source');
    // Beside the gear, not appended at the end next to delete: the two are the
    // same errand, and a source button sitting against the trash is a misclick
    // waiting to happen.
    expect(withSource.indexOf('source')).toBe(withSource.indexOf('settings') + 1);
    expect(actionsFor(chart, 'no-source-study')).not.toContain('source');
  });

  it('emits indicatorSource naming the instance, and swallows the click', () => {
    register('emitting-study', true);
    const chart = makeChart();
    const instance = chart.addIndicator('emitting-study');
    const seen: unknown[] = [];
    chart.on('indicatorSource', (p) => seen.push(p));
    const handled = (chart as unknown as { _handleLegendAction(id: string): boolean })
      ._handleLegendAction(`indicator:${instance.id}::source`);
    // Unhandled would fall through to the host as a phantom click id, which is
    // how a new action ships looking dead.
    expect(handled).toBe(true);
    expect(seen).toEqual([{
      instanceId: instance.id, indicatorId: 'emitting-study', paneIndex: instance.paneIndex,
    }]);
  });

  it('applies a chart-wide button size to the rows it already has and the next one', () => {
    register('sized-study', true);
    const chart = makeChart();
    const before = chart.addIndicator('sized-study');
    chart.setLegendIconSize(24);
    const after = chart.addIndicator('sized-study');
    const sizeOf = (instanceId: string): number | undefined => {
      const legend = chart.panes()[0].primitives()
        .find((p) => p instanceof PaneLegend && p.options().id === `indicator:${instanceId}`) as PaneLegend;
      return legend.options().iconSize;
    };
    // A row added after the call must obey it too, or the rows on one pane
    // stack against two different heights and draw through each other.
    expect(sizeOf(before.id)).toBe(24);
    expect(sizeOf(after.id)).toBe(24);
    expect(chart.legendIconSize()).toBe(24);
  });
});
