import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import { bestHit, type PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceLine } from '../src/primitives/price-line';
import { SeriesMarkers, markerSizePx, effectiveMarkerPx } from '../src/primitives/markers';
import { EventMarkers } from '../src/primitives/event-markers';
import { ema, emaSeries } from '../src/indicators/ema';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import type { Bar } from '../src/model/bar';
import { makeCtx } from './helpers/fake-ctx';

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c });

function makeRc(): { rc: PrimitiveRenderContext; dl: DataLayer; seriesId: number } {
  const dl = new DataLayer();
  const seriesId = dl.createSeries();
  dl.setSeriesData(seriesId, [bar(100, 50), bar(200, 52), bar(300, 48)]);
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 40, max: 60 });
  const timeScale = new TimeScale({ barSpacing: 20, rightOffset: 0 });
  timeScale.setWidth(600);
  timeScale.setBaseIndex(dl.baseIndex);
  return {
    rc: { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme },
    dl,
    seriesId,
  };
}

describe('bestHit', () => {
  it('prefers nearest distance, then higher z-order', () => {
    expect(bestHit([null, null])).toBeNull();
    const a = { externalId: 'a', zOrder: 'normal' as const, distance: 5 };
    const b = { externalId: 'b', zOrder: 'top' as const, distance: 5 };
    const c = { externalId: 'c', zOrder: 'normal' as const, distance: 2 };
    expect(bestHit([a, b])!.externalId).toBe('b'); // tie: top wins
    expect(bestHit([a, b, c])!.externalId).toBe('c'); // nearest wins
  });
});

describe('PriceLine primitive', () => {
  it('contributes its price to autoscale', () => {
    const pl = new PriceLine({ price: 123.45, color: '#fff', lineWidth: 1, dashed: true, id: 'sl' });
    expect(pl.autoscaleInfo()).toEqual({ min: 123.45, max: 123.45 });
  });

  it('hit-tests near its line only', () => {
    const { rc } = makeRc();
    const pl = new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'order1', cursor: 'ns-resize' });
    const yAt50 = rc.priceScale.priceToY(50);
    expect(pl.hitTest(100, yAt50, rc)!.externalId).toBe('order1');
    expect(pl.hitTest(100, yAt50, rc)!.cursor).toBe('ns-resize');
    expect(pl.hitTest(100, yAt50 + 20, rc)).toBeNull(); // far away
  });

  it('setPrice requests a repaint via the host', () => {
    let updates = 0;
    const pl = new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'x' });
    pl.attached({ requestUpdate: () => { updates++; } });
    pl.setPrice(55);
    expect(pl.price).toBe(55);
    expect(updates).toBe(1);
  });

  it('setOptions restyles in place and repaints', () => {
    let updates = 0;
    const pl = new PriceLine({ price: 50, color: '#e0b020', lineWidth: 1, dashed: true, id: 'ltp' });
    pl.attached({ requestUpdate: () => { updates++; } });
    pl.setOptions({ color: '#26a69a' });
    expect(pl.options().color).toBe('#26a69a');
    expect(updates).toBe(1);
    // Untouched keys survive, and the id stays the hit-test handle.
    expect(pl.options().dashed).toBe(true);
    expect(pl.options().price).toBe(50);
    expect(pl.options().id).toBe('ltp');
  });

  it('setOptions colour reaches the canvas', () => {
    const { rc } = makeRc();
    const pl = new PriceLine({ price: 50, color: '#e0b020', lineWidth: 1, dashed: false, id: 'ltp' });
    pl.setOptions({ color: '#ef5350' });
    const { ctx, rec } = makeCtx();
    pl.draw(ctx, rc);
    expect(rec.ops.some((o) => o.strokeStyle === '#ef5350')).toBe(true);
    expect(rec.ops.some((o) => o.strokeStyle === '#e0b020')).toBe(false);
  });

  it('extentFromRight draws only the rightmost fraction; leftLabel adds an end tag', () => {
    const { rc } = makeRc(); // plotWidth 600, dpr 1
    const full = makeCtx();
    new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'a' }).draw(full.ctx, rc);
    expect(full.rec.ops.find((o) => o.type === 'moveTo')!.args[0]).toBe(0); // full width

    const partial = makeCtx();
    new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'b', extentFromRight: 0.3, leftLabel: 'BUY 100 LIMIT' })
      .draw(partial.ctx, rc);
    expect(partial.rec.ops.find((o) => o.type === 'moveTo')!.args[0]).toBe(420); // 600 * (1 - 0.3)
    expect(partial.rec.count('fillRect')).toBe(1); // right price tag
    expect(partial.rec.count('roundRect')).toBe(2); // group backplate + label segment
  });

  it('closeButton hit-tests as a click on the close segment; the rest of the line drags', () => {
    const { rc } = makeRc(); // plotWidth 600
    const pl = new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'order:7', cursor: 'ns-resize', closeButton: true });
    pl.draw(makeCtx().ctx, rc); // draw records the pill-group geometry
    const yAt50 = rc.priceScale.priceToY(50);
    const close = pl.hitTest(16, yAt50, rc); // inside the close segment (group starts at x=6, the close segment is 20 wide)
    expect(close!.externalId).toBe('order:7::close');
    expect(close!.cursor).toBe('pointer'); // click, not drag
    const drag = pl.hitTest(120, yAt50, rc); // elsewhere on the line
    expect(drag!.externalId).toBe('order:7');
    expect(drag!.cursor).toBe('ns-resize');
  });

  it('setLeftLabel updates the tag + repaints', () => {
    let updates = 0;
    const pl = new PriceLine({ price: 50, color: '#fff', lineWidth: 1, dashed: false, id: 'position' });
    pl.attached({ requestUpdate: () => { updates++; } });
    pl.setLeftLabel('LONG 100  +1,250');
    expect(pl.options().leftLabel).toBe('LONG 100  +1,250');
    expect(updates).toBe(1);
  });
});

describe('SeriesMarkers', () => {
  it('size ladder + bar-spacing clamp', () => {
    expect(markerSizePx('tiny')).toBe(6);
    expect(markerSizePx('big')).toBe(16);
    expect(effectiveMarkerPx('big', 8)).toBe(8); // clamped to bar spacing
    expect(effectiveMarkerPx('tiny', 50)).toBe(6); // not enlarged
  });

  it('draws one glyph per visible marker and hit-tests it', () => {
    const { rc, seriesId } = makeRc();
    const m = new SeriesMarkers(seriesId);
    m.setMarkers([
      { time: 200, position: 'belowBar', shape: 'arrowUp', size: 'medium', color: '#26a69a', text: 'BUY', id: 'sig1' },
    ]);
    const { ctx } = makeCtx();
    m.draw(ctx, rc);
    // the marker is at index 1 (time 200), so hit-test near its recorded position
    const x = rc.timeScale.indexToX(1);
    const yBelow = rc.priceScale.priceToY(rc.dataLayer.indexedBars(seriesId)[1].bar.low);
    const hit = m.hitTest(x, yBelow + 12); // near the below-bar glyph
    expect(hit?.externalId).toBe('sig1');
  });
});

describe('EventMarkers', () => {
  it('records a badge position and hit-tests it', () => {
    const { rc } = makeRc();
    const em = new EventMarkers();
    em.setEvents([{ time: 200, type: 'earnings', label: 'E', id: 'ev1' }]);
    const { ctx } = makeCtx();
    em.draw(ctx, rc);
    const x = rc.timeScale.indexToX(1);
    const y = rc.plotHeight - 8 - 4; // strip near bottom
    expect(em.hitTest(x, y)?.externalId).toBe('ev1');
  });
});

describe('EMA indicator', () => {
  it('seeds from the first value and smooths', () => {
    const out = ema([10, 20, 30, 40], 3); // k = 0.5
    expect(out[0]).toBe(10);
    expect(out[1]).toBeCloseTo(15); // 20*0.5 + 10*0.5
    expect(out[2]).toBeCloseTo(22.5);
    expect(out[3]).toBeCloseTo(31.25);
  });

  it('emaSeries returns plottable bars aligned to input times', () => {
    const bars = [bar(100, 10), bar(200, 20), bar(300, 30)];
    const e = emaSeries(bars, 2);
    expect(e).toHaveLength(3);
    expect(e[0].time).toBe(100);
    expect(e[0].close).toBe(e[0].open); // flat O=H=L=C at the EMA value
  });

  it('rejects non-positive periods', () => {
    expect(() => ema([1, 2, 3], 0)).toThrow();
  });
});
