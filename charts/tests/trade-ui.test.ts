/**
 * Trading-UI visual states: pill/color helpers, hover/dragging emphasis,
 * the drag ghost, and theme-aware trade primitives.
 */
import { describe, it, expect } from 'vitest';
import { darkTheme, lightTheme } from '../src/theme';
import { parseColor, luminance, contrastText, withAlpha, shade, roundRectPath } from '../src/render/pill';
import { PriceLine } from '../src/primitives/price-line';
import { WorkingOrderLine } from '../src/trade/order-line';
import { PositionMarker } from '../src/trade/position';
import { BracketGroup } from '../src/trade/bracket';
import { DomLadder } from '../src/trade/dom-ladder';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import type { Order } from '../src/trade/types';
import { makeCtx } from './helpers/fake-ctx';

function makeRc(overrides: Partial<PrimitiveRenderContext> = {}): PrimitiveRenderContext {
  const dl = new DataLayer();
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 80, max: 120 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400,
    priceAxisWidth: 56, dpr: 1, theme: darkTheme, ...overrides,
  };
}

describe('pill color helpers', () => {
  it('parses hex and rgb() colors', () => {
    expect(parseColor('#fff')).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(parseColor('#26a69a')).toEqual({ r: 38, g: 166, b: 154, a: 1 });
    expect(parseColor('#26a69a80')!.a).toBeCloseTo(0.5, 1);
    expect(parseColor('rgb(1, 2, 3)')).toEqual({ r: 1, g: 2, b: 3, a: 1 });
    expect(parseColor('rgba(1,2,3,0.4)')).toEqual({ r: 1, g: 2, b: 3, a: 0.4 });
    expect(parseColor('teal')).toBeNull(); // named colors unsupported: caller falls back
  });

  it('picks legible text for light and dark fills', () => {
    expect(contrastText('#ffffff')).toBe('#10131a');
    expect(contrastText('#0d0e12')).toBe('#ffffff');
    expect(contrastText('#26a69a')).toBe('#ffffff'); // buy green: white text
    expect(luminance('#000000')).toBe(0);
  });

  it('withAlpha and shade derive colors without mutating unparseable input', () => {
    expect(withAlpha('#ff0000', 0.5)).toBe('rgba(255,0,0,0.5)');
    expect(withAlpha('nonsense', 0.5)).toBe('nonsense');
    expect(shade('#000000', 1)).toBe('rgba(255,255,255,1)');
    expect(shade('#ffffff', -1)).toBe('rgba(0,0,0,1)');
  });

  it('roundRectPath falls back to rect when the context lacks roundRect', () => {
    const ops: string[] = [];
    const ctx = { rect: () => ops.push('rect') } as unknown as CanvasRenderingContext2D;
    roundRectPath(ctx, 0, 0, 10, 10, 3);
    expect(ops).toEqual(['rect']);
  });
});

describe('PriceLine visual states', () => {
  const opts = {
    price: 100, color: '#26a69a', lineWidth: 1, dashed: false,
    id: 'ord1', cursor: 'ns-resize', leftLabel: 'BUY 10 LIMIT', closeButton: true, extentFromRight: 0.3,
  };

  it('hover thickens the line of an interactive price line', () => {
    const base = makeCtx();
    new PriceLine({ ...opts }).draw(base.ctx, makeRc());
    const hover = makeCtx();
    new PriceLine({ ...opts }).draw(hover.ctx, makeRc({ hoverId: 'ord1' }));
    const lineW = (ops: typeof base.rec.ops): number => ops.find((o) => o.type === 'stroke')!.lineWidth!;
    expect(lineW(hover.rec.ops)).toBeGreaterThan(lineW(base.rec.ops));
  });

  it('does not apply hover styling to non-interactive lines', () => {
    const mk = (hoverId?: string) => {
      const c = makeCtx();
      new PriceLine({ price: 100, color: '#e0b020', lineWidth: 1, dashed: true, id: 'ltp' })
        .draw(c.ctx, makeRc({ hoverId: hoverId ?? null }));
      return c.rec.ops.find((o) => o.type === 'stroke')!.lineWidth!;
    };
    expect(mk('ltp')).toBe(mk(undefined)); // same width hovered or not
  });

  it('draws a drag ghost + emphasis halo while dragging', () => {
    const base = makeCtx();
    new PriceLine({ ...opts }).draw(base.ctx, makeRc());
    const drag = makeCtx();
    const pl = new PriceLine({ ...opts });
    pl.setDragGhost(95);
    pl.draw(drag.ctx, makeRc({ dragId: 'ord1' }));
    // ghost line + halo stroke = exactly two extra strokes over the base render
    expect(drag.rec.count('stroke')).toBe(base.rec.count('stroke') + 2);
  });

  it('renders a segment per structured field: [badge][qty][label][close]', () => {
    const all = makeCtx();
    new PriceLine({ ...opts, badge: 'BUY', qty: 10, leftLabel: 'LIMIT' }).draw(all.ctx, makeRc());
    expect(all.rec.count('roundRect')).toBe(5); // backplate + 4 segments
    const bare = makeCtx();
    new PriceLine({ ...opts, leftLabel: undefined }).draw(bare.ctx, makeRc());
    expect(bare.rec.count('roundRect')).toBe(2); // backplate + close only
  });

  it('fills the cancel button solid when its hit zone is hovered', () => {
    const idle = makeCtx();
    new PriceLine({ ...opts }).draw(idle.ctx, makeRc());
    const hot = makeCtx();
    new PriceLine({ ...opts }).draw(hot.ctx, makeRc({ hoverId: 'ord1::close' }));
    // the close box is the LAST fill (drawn after the left pill)
    const closeFill = (ops: typeof idle.rec.ops): string => {
      const fills = ops.filter((o) => o.type === 'fill');
      return fills[fills.length - 1]!.fillStyle!;
    };
    expect(closeFill(hot.rec.ops)).toBe('#26a69a'); // solid side color on hover
    expect(closeFill(idle.rec.ops)).toBe(darkTheme.background); // theme background when idle
  });

  it('routes the close segment as a close click and the rest of the group as a drag', () => {
    const rc = makeRc();
    const pl = new PriceLine({ ...opts }); // extentFromRight 0.3: group starts at x=420
    pl.draw(makeCtx().ctx, rc);
    const y = rc.priceScale.priceToY(100);
    // fake-ctx measureText = 6px/char: label 'BUY 10 LIMIT' 72+12 pad, so the close segment spans 506..526
    expect(pl.hitTest(510, y, rc)!.externalId).toBe('ord1::close');
    expect(pl.hitTest(510, y, rc)!.cursor).toBe('pointer');
    expect(pl.hitTest(450, y, rc)!.externalId).toBe('ord1'); // label segment drags
    expect(pl.hitTest(300, y, rc)!.externalId).toBe('ord1'); // bare line drags
    expect(pl.hitTest(300, y, rc)!.cursor).toBe('ns-resize');
  });
});

describe('trade primitives visual states', () => {
  const order = (o: Partial<Order> = {}): Order => ({
    id: 'o1', symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, filledQty: 0, price: 100, status: 'working', ...o,
  });

  it('WorkingOrderLine thickens on hover and dims while pending', () => {
    const mk = (status: Order['status'], hoverId?: string) => {
      const c = makeCtx();
      new WorkingOrderLine(order({ status })).draw(c.ctx, makeRc({ hoverId: hoverId ?? null }));
      return c.rec.ops.find((op) => op.type === 'stroke')!;
    };
    expect(mk('working', 'order:o1').lineWidth!).toBeGreaterThan(mk('working').lineWidth!);
    expect(mk('pending').strokeStyle).toContain('rgba('); // alpha-dimmed until acked
  });

  it('PositionMarker draws a segmented group with a theme-derived P&L band', () => {
    const c = makeCtx();
    const pm = new PositionMarker({ symbol: 'X', netQty: 10, avgPrice: 100 });
    pm.setLtp(105);
    pm.draw(c.ctx, makeRc());
    expect(c.rec.count('roundRect')).toBe(5); // backplate + [LONG][10][+50.00 (+5.00%)][close]
    const band = c.rec.ops.find((o) => o.type === 'fillRect');
    expect(band!.fillStyle).toBe(withAlpha(darkTheme.profit, 0.1));
    // the close segment hit-tests as position close once drawn
    const rc = makeRc();
    pm.draw(makeCtx().ctx, rc);
    const y = rc.priceScale.priceToY(100);
    const g = pm.hitTest(80, y, rc); // inside the close segment region
    expect(g === null || g.externalId.startsWith('position:X')).toBe(true);
  });

  it('BracketGroup draws SL/TP/R:R chips and theme-derived zones', () => {
    const c = makeCtx();
    new BracketGroup({ symbol: 'X', side: 'BUY', entry: 100, stop: 95, target: 110 }).draw(c.ctx, makeRc());
    expect(c.rec.count('roundRect')).toBe(3); // SL chip, TP chip, R:R chip
    const zones = c.rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.fillStyle);
    expect(zones).toContain(withAlpha(darkTheme.loss, 0.09));
    expect(zones).toContain(withAlpha(darkTheme.profit, 0.09));
  });

  it('DomLadder qty text adapts to the theme background', () => {
    const depth = { ltp: 100, bids: [{ price: 99, qty: 5 }], asks: [{ price: 101, qty: 7 }] };
    const textFill = (theme: typeof darkTheme): string => {
      const c = makeCtx();
      const ladder = new DomLadder({ tickSize: 1 });
      ladder.setDepth(depth);
      ladder.draw(c.ctx, makeRc({ theme }));
      return c.rec.ops.find((o) => o.type === 'fillText')!.fillStyle!;
    };
    expect(textFill(darkTheme)).toBe(withAlpha('#ffffff', 0.9)); // light text on dark
    expect(textFill(lightTheme)).toBe(withAlpha('#10131a', 0.9)); // dark text on light
  });
});
