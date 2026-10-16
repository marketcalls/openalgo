import { describe, it, expect } from 'vitest';
import { LogoWatermark, watermarkRect } from '../src/primitives/watermark';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx } from './helpers/fake-ctx';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';

describe('watermarkRect', () => {
  it('anchors to each corner and center', () => {
    const plotW = 800, plotH = 400, m = 10, w = 40, h = 20;
    expect(watermarkRect('top-left', m, w, h, plotW, plotH)).toMatchObject({ x: 10, y: 10 });
    expect(watermarkRect('top-right', m, w, h, plotW, plotH)).toMatchObject({ x: 750, y: 10 });
    expect(watermarkRect('bottom-left', m, w, h, plotW, plotH)).toMatchObject({ x: 10, y: 370 });
    expect(watermarkRect('bottom-right', m, w, h, plotW, plotH)).toMatchObject({ x: 750, y: 370 });
    expect(watermarkRect('center', m, w, h, plotW, plotH)).toMatchObject({ x: 380, y: 190 });
  });
});

describe('LogoWatermark', () => {
  const fakeImage = { width: 100, height: 50 } as unknown as CanvasImageSource & { width: number; height: number };

  function recorder() {
    const calls: Array<{ args: unknown[] }> = [];
    const ctx = {
      canvas: { ownerDocument: undefined },
      globalAlpha: 1,
      save() {}, restore() {},
      drawImage(...args: unknown[]) { calls.push({ args }); },
    } as unknown as CanvasRenderingContext2D;
    return { ctx, calls };
  }

  const rc = (dpr: number): PrimitiveRenderContext => ({
    plotWidth: 600, plotHeight: 300, priceAxisWidth: 0, dpr,
    // scales/dataLayer/theme are unused by the watermark
  } as unknown as PrimitiveRenderContext);

  it('draws a preloaded image at the bottom-right, scaled by dpr', () => {
    const wm = new LogoWatermark({ image: fakeImage, position: 'bottom-right', margin: 12, height: 30, opacity: 0.5 });
    const { ctx, calls } = recorder();
    wm.draw(ctx, rc(2));
    expect(calls).toHaveLength(1);
    // aspect 100/50 = 2 -> w = 60, h = 30; device px = *2
    const [img, dx, dy, dw, dh] = calls[0].args as [unknown, number, number, number, number];
    expect(img).toBe(fakeImage);
    expect(dw).toBe(120); // 60 * 2
    expect(dh).toBe(60);  // 30 * 2
    // bottom-right: x = 600 - 12 - 60 = 528 -> *2 = 1056 ; y = 300 - 12 - 30 = 258 -> *2 = 516
    expect(dx).toBe(1056);
    expect(dy).toBe(516);
  });

  it('does nothing until an image is ready', () => {
    const wm = new LogoWatermark({ src: 'about:blank' });
    const { ctx, calls } = recorder();
    wm.draw(ctx, rc(1));
    expect(calls).toHaveLength(0);
  });
});

describe('hover-revealed label', () => {
  const rc = (hoverId: string | null = null): PrimitiveRenderContext => ({
    timeScale: new TimeScale(), priceScale: new PriceScale(), dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme, hoverId,
  });
  const img = { width: 40, height: 20, naturalWidth: 40, naturalHeight: 20 } as never;

  it('does not hit-test at all without a label', () => {
    const w = new LogoWatermark({ image: img, position: 'bottom-left', margin: 10, height: 20 });
    w.draw(makeCtx().ctx, rc());
    // A plain mark is decoration; it must not swallow clicks meant for the chart.
    expect(w.hitTest(20, 375, rc())).toBeNull();
  });

  it('hit-tests the mark once it has a label to reveal', () => {
    const w = new LogoWatermark({ image: img, position: 'bottom-left', margin: 10, height: 20, label: 'OpenAlgo Charts' });
    w.draw(makeCtx().ctx, rc());
    expect(w.hitTest(20, 375, rc())?.externalId).toBe('watermark');
    expect(w.hitTest(500, 100, rc())).toBeNull();
  });

  it('draws no label at rest and text once hovered', () => {
    const w = new LogoWatermark({
      image: img, position: 'bottom-left', margin: 10, height: 20,
      label: 'OpenAlgo Charts', revealSeconds: 0,
    });
    const cold = makeCtx();
    w.draw(cold.ctx, rc());
    expect(cold.rec.ops.filter((o) => o.type === 'fillText')).toHaveLength(0);

    const hot = makeCtx();
    w.draw(hot.ctx, rc('watermark'));
    expect(hot.rec.ops.filter((o) => o.type === 'fillText')).toHaveLength(1);
  });

  it('eases rather than snapping, and asks for frames while moving', () => {
    let updates = 0;
    const w = new LogoWatermark({
      image: img, position: 'bottom-left', margin: 10, height: 20,
      label: 'OpenAlgo Charts', revealSeconds: 0.2,
    });
    w.attached({ requestUpdate: () => { updates += 1; } } as never);
    // Two frames in: still mid-reveal, so it must keep requesting frames.
    w.draw(makeCtx().ctx, rc('watermark'));
    w.draw(makeCtx().ctx, rc('watermark'));
    expect(updates).toBeGreaterThan(0);
  });
});

describe('plate padding', () => {
  // A square mark, so `height` sizes both axes: the shape the hosts use.
  const square = { width: 128, height: 128, naturalWidth: 128, naturalHeight: 128 } as never;

  const ctxFor = (dpr: number): PrimitiveRenderContext => ({
    timeScale: new TimeScale(), priceScale: new PriceScale(), dataLayer: new DataLayer(),
    plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr, theme: darkTheme, hoverId: null,
  } as PrimitiveRenderContext);

  /** The plate rect, in media px, as drawn. */
  function plate(padding: number | { x: number; y: number } | undefined, dpr: number) {
    const w = new LogoWatermark({
      image: square, position: 'bottom-left', margin: 10, height: 40,
      label: 'OpenAlgo Charts', padding,
    });
    const { ctx, rec } = makeCtx();
    w.draw(ctx, ctxFor(dpr));
    const op = rec.ops.find((o) => o.type === 'roundRect');
    if (!op) throw new Error('no plate drawn');
    return { w: op.args[2] / dpr, h: op.args[3] / dpr };
  }

  it('wraps a 40px mark in a 45x45 plate at padding 2.5', () => {
    expect(plate(2.5, 1)).toEqual({ w: 45, h: 45 });
  });

  it('holds that size across displays', () => {
    // Rounding the padding and doubling it gave 46 at dpr 1; snapping the
    // edges instead is what keeps it exactly 45.
    for (const dpr of [1, 2, 3]) expect(plate(2.5, dpr).h).toBe(45);
    // A fractional DPR cannot put 45 media px on a whole number of device
    // pixels, so one device pixel of slack is the best on offer.
    expect(Math.abs(plate(2.5, 1.5).h - 45)).toBeLessThanOrEqual(1 / 1.5);
  });

  it('accepts separate axes', () => {
    expect(plate({ x: 10, y: 2 }, 2)).toEqual({ w: 60, h: 44 });
  });

  it('defaults to 7 x 4, the pre-existing padding', () => {
    expect(plate(undefined, 2)).toEqual({ w: 54, h: 48 });
  });

  it('grows the hit box with the padding', () => {
    const rc = ctxFor(1);
    const w = new LogoWatermark({
      image: square, position: 'bottom-left', margin: 10, height: 40,
      label: 'X', padding: 12,
    });
    w.draw(makeCtx().ctx, rc);
    // Mark occupies x 10..50, y 350..390; 12px of plate extends that.
    expect(w.hitTest(0, 345, rc)).not.toBeNull();
    expect(w.hitTest(-6, 345, rc)).toBeNull();
  });
});

describe('link attribution', () => {
  const img = { width: 40, height: 20, naturalWidth: 40, naturalHeight: 20 } as never;

  it('appends utm parameters naming the embedding page', () => {
    const w = new LogoWatermark({ image: img, href: 'https://openalgo.in' });
    const href = w.href() as string;
    expect(href.startsWith('https://openalgo.in?')).toBe(true);
    expect(href).toContain('utm_medium=oac-link');
    expect(href).toContain('utm_campaign=oac-chart');
  });

  it('leaves a caller-composed query string alone', () => {
    const w = new LogoWatermark({ image: img, href: 'https://openalgo.in/?ref=mine' });
    expect(w.href()).toBe('https://openalgo.in/?ref=mine');
  });

  it('is not clickable without an href', () => {
    const w = new LogoWatermark({ image: img });
    expect(w.href()).toBeUndefined();
  });

  it('reports a pointer cursor only when it links somewhere', () => {
    const rc = {
      timeScale: new TimeScale(), priceScale: new PriceScale(), dataLayer: new DataLayer(),
      plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme, hoverId: null,
    } as PrimitiveRenderContext;
    const plain = new LogoWatermark({ image: img, position: 'bottom-left', margin: 10, height: 20, label: 'X' });
    const linked = new LogoWatermark({ image: img, position: 'bottom-left', margin: 10, height: 20, label: 'X', href: 'https://openalgo.in' });
    plain.draw(makeCtx().ctx, rc);
    linked.draw(makeCtx().ctx, rc);
    expect(plain.hitTest(20, 375, rc)?.cursor).toBe('default');
    expect(linked.hitTest(20, 375, rc)?.cursor).toBe('pointer');
  });
});

describe('built-in vector geometry', () => {
  const context = (plotWidth: number, plotHeight: number, dpr = 1): PrimitiveRenderContext => ({
    plotWidth, plotHeight, dpr, theme: darkTheme,
  }) as PrimitiveRenderContext;

  it('keeps a full touch target around the smaller narrow-chart mark', () => {
    const mark = new LogoWatermark({ position: 'bottom-left', margin: 14, padding: 8, href: 'https://openalgo.in' });
    const rc = context(320, 180);
    expect(mark.hitTest(4, 132, rc)).not.toBeNull();
    expect(mark.hitTest(48, 176, rc)).not.toBeNull();
    expect(mark.hitTest(3, 132, rc)).toBeNull();
    expect(mark.hitTest(-1, 150, rc)).toBeNull();
  });

  it('constrains oversized custom artwork and hover plates inside a small plot at every DPR', () => {
    for (const dpr of [1, 1.5, 2, 3]) {
      const mark = new LogoWatermark({
        image: { width: 1000, height: 100 } as never, position: 'bottom-right',
        height: 400, margin: 0, padding: 8, label: 'A long custom brand label', revealSeconds: 0,
      });
      const rc = { ...context(120, 60, dpr), hoverId: 'watermark' };
      const { ctx, rec } = makeCtx();
      mark.draw(ctx, rc);
      const [x, y, w, h] = rec.ops.find((op) => op.type === 'roundRect')!.args;
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(x + w).toBeLessThanOrEqual(120 * dpr);
      expect(y + h).toBeLessThanOrEqual(60 * dpr);
      expect(mark.hitTest(121, 30, rc)).toBeNull();
    }
  });
});
