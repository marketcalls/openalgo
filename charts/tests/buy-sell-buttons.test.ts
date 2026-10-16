import { describe, it, expect } from 'vitest';
import { darkTheme } from '../src/theme';
import { BuySellButtons } from '../src/primitives/buy-sell-buttons';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { makeCtx } from './helpers/fake-ctx';

function rc(overrides: Partial<PrimitiveRenderContext> = {}): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 80, max: 120 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(), plotWidth: 600, plotHeight: 400,
    priceAxisWidth: 56, dpr: 1, theme: darkTheme, ...overrides,
  };
}

describe('BuySellButtons', () => {
  it('hit-tests the sell / qty / buy zones and misses elsewhere', () => {
    const p = new BuySellButtons({ id: 'trade', position: 'top-left', margin: 12 });
    p.setMark(100);
    p.draw(makeCtx().ctx, rc());
    // panel docks at x=12,y=12; SELL 74w, qty 40w, BUY 74w, gaps 1
    expect(p.hitTest(30, 30, rc())!.externalId).toBe('trade:sell');
    expect(p.hitTest(12 + 74 + 20, 30, rc())!.externalId).toBe('trade:qty');
    expect(p.hitTest(12 + 74 + 40 + 40, 30, rc())!.externalId).toBe('trade:buy');
    expect(p.hitTest(30, 200, rc())).toBeNull(); // below the panel
    expect(p.hitTest(400, 30, rc())).toBeNull(); // right of the panel
  });

  it('cursor is pointer and z-order top (draws over series + lines)', () => {
    const p = new BuySellButtons();
    p.setMark(100);
    p.draw(makeCtx().ctx, rc());
    expect(p.zOrder()).toBe('top');
    expect(p.hitTest(30, 30, rc())!.cursor).toBe('pointer');
    expect(p.autoscaleInfo()).toBeNull();
  });

  it('renders distinct bid / ask prices and the qty chip', () => {
    const { ctx, rec } = makeCtx();
    const p = new BuySellButtons({ qty: 5 });
    p.setPrices(99.5, 100.5);
    p.draw(ctx, rc());
    // three filled shapes (sell button, qty chip, buy button) + text
    expect(rec.count('fill')).toBeGreaterThanOrEqual(3);
    expect(rec.count('fillText')).toBeGreaterThan(0);
  });

  it('supports each dock corner without overlapping the plot edge', () => {
    for (const position of ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'center'] as const) {
      const p = new BuySellButtons({ position });
      p.setMark(100);
      const { ctx } = makeCtx();
      expect(() => p.draw(ctx, rc())).not.toThrow();
      const hit = p.hitTest(-5, -5, rc());
      expect(hit).toBeNull(); // off-plot never hits
    }
  });

  it('setQty / setColors request a repaint via the host', () => {
    let updates = 0;
    const p = new BuySellButtons();
    p.attached({ requestUpdate: () => { updates++; } });
    p.setMark(100);
    p.setQty(3);
    p.setColors('#0af', '#f0a');
    expect(updates).toBe(3);
  });

  it('scales the whole panel, hit rects included', () => {
    // A dense layout needs these smaller so they do not crowd the legend rows;
    // the hit rects must shrink with the paint or clicks land off the button.
    const full = new BuySellButtons({ id: 't', margin: 10 });
    const half = new BuySellButtons({ id: 't', margin: 10, scale: 0.7 });
    full.draw(makeCtx().ctx, rc());
    half.draw(makeCtx().ctx, rc());
    expect(full.hitTest(12, 12, rc())).not.toBeNull();
    // Full panel spans x 10..200 and y 10..52; at 0.7 it is x 10..144, y 10..39.
    // Points inside the full box but outside the scaled one must miss.
    expect(half.hitTest(170, 20, rc())).toBeNull();
    expect(full.hitTest(170, 20, rc())).not.toBeNull();
    expect(half.hitTest(30, 48, rc())).toBeNull();
    expect(full.hitTest(30, 48, rc())).not.toBeNull();
  });

  it('keeps both text baselines inside the button at any scale', () => {
    // The price and label baselines were fixed px tuned for the 42px button, so
    // a scaled-down panel painted its label below its own box.
    for (const scale of [1, 0.72, 0.6]) {
      const p = new BuySellButtons({ id: 't', position: 'top-left', margin: 10, scale });
      p.setPrices(99, 101);
      const { ctx, rec } = makeCtx();
      p.draw(ctx, rc());
      const h = 42 * scale;
      const texts = rec.ops.filter((o) => o.type === 'fillText');
      expect(texts.length).toBeGreaterThan(0);
      for (const t of texts) {
        const y = t.args[1] as number;
        expect(y).toBeGreaterThanOrEqual(10);
        expect(y).toBeLessThanOrEqual(10 + h);
      }
    }
  });

  it('clamps an absurd scale rather than drawing something unusable', () => {
    const tiny = new BuySellButtons({ id: 't', margin: 10, scale: 0.01 });
    tiny.draw(makeCtx().ctx, rc());
    // Clamped to 0.6, so the button still covers its own top-left corner.
    expect(tiny.hitTest(12, 12, rc())).not.toBeNull();
  });
});
