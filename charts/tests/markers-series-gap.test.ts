/**
 * A marker on a bar its own series has no point for (src/primitives/markers.ts).
 *
 * The layer is bound to one series, which decides the pane and the price scale
 * it lives on. The height of a mark, though, comes from the bar underneath it,
 * and those are not always the same row of data.
 *
 * An indicator that draws one coloured line while a trend is up and another
 * while it is down has a gap in each of them by construction. Its flip marks
 * land exactly in those gaps: the bar where the up line first appears is the
 * bar where the down line stops. Before this fix the mark was dropped, with no
 * warning anywhere, and the symptom was maddening to read: the buy mark of such
 * a study appeared and the sell mark never did, because only one of the two
 * flips fell on a bar the first plot happened to cover.
 */
import { afterEach, describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';
import { SeriesMarkers } from '../src/primitives/markers';
import { makeCtx, type Op } from './helpers/fake-ctx';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c });

/** Every bar the instrument has. */
const INSTRUMENT: Bar[] = [bar(100, 50), bar(200, 52), bar(300, 48), bar(400, 46)];

/** What a plot drawn only while the trend is up looks like: two of four bars. */
const GAPPED: Bar[] = [bar(100, 50), bar(200, 52)];

function makeRc(seriesBars: Bar[]): { rc: PrimitiveRenderContext; seriesId: number } {
  const dl = new DataLayer();
  // The instrument's own series goes in first, exactly as the chart has it.
  // The time axis is built from every series the layer holds, so without it a
  // bar the gapped plot skips would not be on the axis at all and the mark
  // would be discarded a step earlier, for a different reason.
  dl.setSeriesData(dl.createSeries(), INSTRUMENT);
  const seriesId = dl.createSeries();
  dl.setSeriesData(seriesId, seriesBars);
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 40, max: 60 });
  const timeScale = new TimeScale({ barSpacing: 20, rightOffset: 0 });
  timeScale.setWidth(600);
  timeScale.setBaseIndex(dl.baseIndex);
  return {
    rc: { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme },
    seriesId,
  };
}

const drawn = (ops: Op[]): string[] =>
  ops.filter((o) => o.type === 'fillText').map((o) => String(o.text));

describe('registered studies with real null plot gaps and independent scales', () => {
  const charts: Chart[] = [];
  afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });
  let nextId = 0;
  function setup(anchor?: 'price', placement: 'onchart' | 'pane' = 'onchart', left = false) {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 0 },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    const primary = chart.addSeries('candlestick', { priceScaleId: left ? 'left' : 'right' });
    primary.setData(INSTRUMENT);
    const id = `registered-gap-${++nextId}`;
    registerIndicator({
      id, name: id, placement, inputs: [], markerAnchor: anchor,
      plots: [{ key: 'up', type: 'line', title: 'Up' }, { key: 'down', type: 'line', title: 'Down' }],
      calc: () => ({ up: [10, 20, null, null], down: [null, null, 30, 40] }),
      markers: () => [{ time: 400, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'SELL' }],
    });
    const instance = chart.addIndicator(id);
    const pane = chart.panes()[instance.paneIndex];
    const { rc } = makeRc([]);
    rc.dataLayer = chart.dataLayer;
    rc.timeScale = chart.timeScale;
    rc.priceScale = pane.priceScale;
    rc.priceScale.setHeight(400);
    rc.priceScale.setPriceRange({ min: 0, max: 60 });
    primary.priceScale().setHeight(400);
    primary.priceScale().setPriceRange({ min: 40, max: 60 });
    const paint = () => {
      const { ctx, rec } = makeCtx();
      for (const p of pane.primitives()) if (p instanceof SeriesMarkers) p.draw(ctx, rc);
      return rec.ops.filter((o) => o.type === 'fillText');
    };
    return { chart, primary, instance, paint };
  }

  it('uses instrument bars through null columns on the price scale', () => {
    const { primary, paint } = setup();
    const marks = paint();
    expect(marks).toHaveLength(1);
    expect(marks[0].args[1]).toBe(primary.priceScale().priceToY(48) - 24);
  });

  it('uses the primary series scale when price is on the left', () => {
    const { primary, paint } = setup('price', 'onchart', true);
    expect(paint()[0].args[1]).toBe(primary.priceScale().priceToY(48) - 24);
  });

  it('does not substitute instrument prices into oscillator gaps', () => {
    expect(setup(undefined, 'pane').paint()).toEqual([]);
  });

  it('rebinds to a replacement primary series and its scale', () => {
    const { chart, primary, instance, paint } = setup('price');
    primary.remove();
    const replacement = chart.addSeries('candlestick', { priceScaleId: 'left' });
    replacement.setData(INSTRUMENT);
    replacement.priceScale().setHeight(400);
    replacement.priceScale().setPriceRange({ min: 40, max: 60 });
    instance.setSettings({});
    expect(paint()[0].args[1]).toBe(replacement.priceScale().priceToY(48) - 24);
  });

  it('follows the bound series when its price axis moves', () => {
    const { chart, primary, paint } = setup('price');
    chart.movePriceAxis(0, 'right', 'left');
    primary.priceScale().setPriceRange({ min: 40, max: 60 });
    expect(paint()[0].args[1]).toBe(primary.priceScale().priceToY(48) - 24);
  });

  it('stops price fallback when a replacement instrument uses another scale', () => {
    const { chart, primary, instance, paint } = setup();
    expect(paint()).toHaveLength(1);
    primary.remove();
    chart.addSeries('candlestick', { priceScaleId: 'left' }).setData(INSTRUMENT);
    instance.setSettings({});
    expect(paint()).toEqual([]);
  });
});

describe('a marker whose own series has no point at that time', () => {
  it('is dropped when nothing else can say where the bar is', () => {
    // The behaviour this fix does not change: with no fallback there is still
    // no bar to measure from, so there is still nothing to draw. Asserted so
    // the fix is known to be the fallback rather than a change to the rule.
    const { rc, seriesId } = makeRc(GAPPED);
    const { ctx, rec } = makeCtx();
    const m = new SeriesMarkers(seriesId);
    m.setMarkers([{ time: 400, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'SELL' }]);
    m.draw(ctx, rc);
    expect(drawn(rec.ops)).toEqual([]);
  });

  it('is drawn against the instrument bar when one is offered', () => {
    const { rc, seriesId } = makeRc(GAPPED);
    const { ctx, rec } = makeCtx();
    const m = new SeriesMarkers(seriesId, () => INSTRUMENT);
    m.setMarkers([{ time: 400, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'SELL' }]);
    m.draw(ctx, rc);
    expect(drawn(rec.ops)).toEqual(['SELL']);
  });

  it('draws both flips of a two-column study, which is the case that failed', () => {
    // Bar 200 is covered by the up column and bar 400 is not. Before the fix
    // exactly one of these two marks appeared, which reads as the study being
    // broken rather than the chart dropping one.
    const { rc, seriesId } = makeRc(GAPPED);
    const { ctx, rec } = makeCtx();
    const m = new SeriesMarkers(seriesId, () => INSTRUMENT);
    m.setMarkers([
      { time: 200, position: 'belowBar', shape: 'text', size: 'medium', color: '#0f0', text: 'BUY' },
      { time: 400, position: 'aboveBar', shape: 'text', size: 'medium', color: '#f00', text: 'SELL' },
    ]);
    m.draw(ctx, rc);
    expect(drawn(rec.ops)).toEqual(['BUY', 'SELL']);
  });
});

describe('the marker series still wins where it has a point', () => {
  it('measures from its own series, not the instrument, so nothing moves', () => {
    // The fallback must not change any existing geometry. The series here is
    // priced well away from the instrument, so a mark that switched to the
    // instrument's bar would land at a visibly different height.
    const own = [bar(100, 50), bar(200, 20)];
    const { rc, seriesId } = makeRc(own);

    const without = makeCtx();
    const a = new SeriesMarkers(seriesId);
    a.setMarkers([{ time: 200, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'X' }]);
    a.draw(without.ctx, rc);

    const with_ = makeCtx();
    const b = new SeriesMarkers(seriesId, () => INSTRUMENT);
    b.setMarkers([{ time: 200, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'X' }]);
    b.draw(with_.ctx, rc);

    const y = (r: { ops: Op[] }): number =>
      r.ops.filter((o) => o.type === 'fillText')[0]!.args[1] as number;
    expect(y(with_.rec)).toBe(y(without.rec));
  });
});
