/**
 * What a paint of series markers costs, and what it may not skip to get there
 * (src/primitives/markers.ts).
 *
 * Markers repaint with their pane, which includes every live tick. Each paint
 * used to index the series' whole history to find the bar under each mark, so
 * the frame cost grew with the loaded history rather than with the marks in
 * view: a few milliseconds a frame at fifty thousand bars and tens at two
 * hundred thousand, whether one mark or five hundred was drawn. A paint now
 * reads the bar under each mark it draws and nothing else.
 */
import { describe, it, expect } from 'vitest';
import { SeriesMarkers, type SeriesMarker } from '../src/primitives/markers';
import { makeCtx, type Op } from './helpers/fake-ctx';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';

const T0 = 1_000;
const STEP = 60;
const at = (i: number): number => T0 + i * STEP;
const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c });

function makeRc(dl: DataLayer): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 80, max: 120 });
  const timeScale = new TimeScale({ barSpacing: 10, rightOffset: 0 });
  timeScale.setWidth(600);
  timeScale.setBaseIndex(dl.baseIndex);
  return { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
}

const mark = (time: number, position: SeriesMarker['position'] = 'aboveBar'): SeriesMarker =>
  ({ time, position, shape: 'arrowDown', size: 'small', color: '#e53935' });

/** The tip of each arrowDown glyph drawn, which sits `px / 2` below its centre. */
const tips = (ops: Op[]): number[] => ops.filter((o) => o.type === 'moveTo').map((o) => o.args[1]);

describe('series markers paint', () => {
  it('reads the bar under each drawn mark, not the whole history', () => {
    const n = 20_000;
    let reads = 0;
    const bars: Bar[] = [];
    for (let i = 0; i < n; i++) {
      const b = bar(at(i), 100);
      // Every lookup of a bar's price goes through `close` first, so counting
      // those reads counts the bars a paint touched.
      let close = b.close;
      Object.defineProperty(b, 'close', { get: () => { reads++; return close; }, set: (v: number) => { close = v; }, enumerable: true });
      bars.push(b);
    }
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const markers = new SeriesMarkers(id);
    markers.setMarkers([mark(at(n - 1)), mark(at(n - 5)), mark(at(n - 9)), mark(at(10))]);
    const { ctx, rec } = makeCtx();

    reads = 0;
    markers.draw(ctx, makeRc(dl));

    // Three marks are in view; the one at the far left of the history is not.
    expect(tips(rec.ops)).toHaveLength(3);
    expect(reads).toBeLessThan(50);
  });

  it('follows a live tick that replaces the bar under a mark', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [bar(at(0), 100), bar(at(1), 100), bar(at(2), 100)]);
    const rc = makeRc(dl);
    const markers = new SeriesMarkers(id);
    markers.setMarkers([mark(at(2))]);

    const first = makeCtx();
    markers.draw(first.ctx, rc);
    dl.update(id, bar(at(2), 110));
    const second = makeCtx();
    markers.draw(second.ctx, rc);

    const [before] = tips(first.rec.ops);
    const [after] = tips(second.rec.ops);
    // A higher high lifts an above-bar mark: nothing from the previous paint
    // may stand in for the bar as it is now.
    expect(after).toBeLessThan(before);
    expect(before - after).toBeCloseTo(rc.priceScale.priceToY(102) - rc.priceScale.priceToY(112), 6);
  });

  it('finds a fallback bar the host supplies out of time order', () => {
    const dl = new DataLayer();
    const instrument = [bar(at(0), 100), bar(at(1), 104), bar(at(2), 96), bar(at(3), 101)];
    dl.setSeriesData(dl.createSeries(), instrument);
    const plotId = dl.createSeries();
    // A plot with a gap at bars 1 and 2, the way a trend-coloured line has one.
    dl.setSeriesData(plotId, [bar(at(0), 100), bar(at(3), 101)]);
    const rc = makeRc(dl);
    const shuffled = [instrument[2], instrument[0], instrument[3], instrument[1]];
    const markers = new SeriesMarkers(plotId, () => shuffled);
    markers.setMarkers([mark(at(1)), mark(at(2))]);

    const { ctx, rec } = makeCtx();
    markers.draw(ctx, rc);

    const drawn = tips(rec.ops);
    expect(drawn).toHaveLength(2);
    // Each sits over its own instrument bar, so the higher bar's mark is higher.
    expect(drawn[0]).toBeLessThan(drawn[1]);
  });

  it('takes the last fallback bar of a repeated time, the live one', () => {
    // A host that appends the forming bar beside its fetched copy repeats that
    // time; the last copy is the live one, as the data layer itself keeps it.
    const tipOver = (fallback: Bar[]): number => {
      const dl = new DataLayer();
      dl.setSeriesData(dl.createSeries(), [bar(at(0), 100), bar(at(1), 110)]);
      const plotId = dl.createSeries();
      dl.setSeriesData(plotId, [bar(at(0), 100)]);
      const markers = new SeriesMarkers(plotId, () => fallback);
      markers.setMarkers([mark(at(1))]);
      const { ctx, rec } = makeCtx();
      markers.draw(ctx, makeRc(dl));
      const drawn = tips(rec.ops);
      expect(drawn).toHaveLength(1);
      return drawn[0];
    };
    const live = bar(at(1), 110);
    const stale = bar(at(1), 100);
    expect(tipOver([bar(at(0), 100), stale, live])).toBe(tipOver([bar(at(0), 100), live]));
  });
});
