/**
 * The pane shading layer (src/primitives/indicator-background.ts): the
 * full-height column a regime study paints behind its own pane, one colour per
 * bar. What has to hold is that it costs a run and not a bar, that it stays on
 * the bars it describes when history moves under it, and that it never paints
 * outside the plot.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorBackground } from '../src/primitives/indicator-background';
import type { PrimitiveHost, PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';
import { darkTheme } from '../src/theme';
import { makeCtx, type Op } from './helpers/fake-ctx';

// index i maps to time 1000 + i*60 and to x = i*10, so the band edge before
// bar i sits at (i - 0.5) * 10. `shift` stands in for a page of history: the
// same time then resolves to a later logical index.
const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => ({ time: 1000 + i * 60, open: 1, high: 1, low: 1, close: 1 }));

const rcOf = (opts: { dpr?: number; from?: number; to?: number; shift?: number } = {}): PrimitiveRenderContext => ({
  timeScale: {
    indexToX: (i: number) => i * 10,
    visibleRange: () => ({ from: opts.from ?? -5, to: opts.to ?? 100 }),
  },
  priceScale: { priceToY: (p: number) => 500 - p },
  dataLayer: { timeToIndexFloat: (t: number) => (t - 1000) / 60 + (opts.shift ?? 0) },
  plotWidth: 400, plotHeight: 300, priceAxisWidth: 60, dpr: opts.dpr ?? 1, theme: darkTheme,
} as unknown as PrimitiveRenderContext);

function run(colors: readonly (string | null)[], rc: PrimitiveRenderContext = rcOf()): Op[] {
  const bg = new IndicatorBackground();
  bg.setColors(colors, bars(colors.length));
  const { ctx, rec } = makeCtx();
  bg.draw(ctx, rc);
  return rec.ops;
}

const fills = (ops: Op[]): Op[] => ops.filter((o) => o.type === 'fillRect');

describe('IndicatorBackground', () => {
  it('paints one rect per run of a colour, not one per bar', () => {
    const ops = fills(run(['#f00', '#f00', '#f00', '#0f0']));
    expect(ops.map((o) => o.fillStyle)).toEqual(['#f00', '#0f0']);
    // Full pane height, and the runs abut exactly: 25 is both the red band's
    // right edge and the green band's left one.
    expect(ops.map((o) => o.args)).toEqual([[0, 0, 25, 300], [25, 0, 10, 300]]);
  });

  it('leaves a bar with no colour unshaded', () => {
    const ops = fills(run(['#f00', null, '#f00']));
    expect(ops.map((o) => o.args[0])).toEqual([0, 15]);
  });

  it('leaves the holes in an array built by index unshaded', () => {
    // A descriptor that assigns `colors[i]` only where it has a regime leaves
    // undefined slots. Canvas ignores an undefined fillStyle, so painting one
    // would silently repeat whatever colour was set last.
    const sparse: (string | null)[] = [];
    sparse.length = 3;
    sparse[2] = '#f00';
    const ops = fills(run(sparse));
    expect(ops).toHaveLength(1);
    expect(ops[0].args).toEqual([15, 0, 10, 300]);
  });

  it('costs nothing for history off the left and right of the view', () => {
    const ops = fills(run(['#001', '#002', '#003', '#004'], rcOf({ from: 1, to: 2 })));
    expect(ops.map((o) => o.fillStyle)).toEqual(['#002', '#003']);
  });

  it('clamps a band to the plot so it cannot reach the price axis', () => {
    const wide = new Array<string>(50).fill('#f00');
    const ops = fills(run(wide));
    expect(ops).toHaveLength(1);
    // Unclamped the run would end at x = 495, painting over the axis strip
    // that shares this canvas.
    expect(ops[0].args).toEqual([0, 0, 400, 300]);
  });

  it('stays on its own bars when a page of history shifts every index', () => {
    const ops = fills(run(['#f00', '#0f0'], rcOf({ shift: 5 })));
    expect(ops.map((o) => o.args)).toEqual([[45, 0, 10, 300], [55, 0, 10, 300]]);
  });

  it('draws in device pixels', () => {
    const ops = fills(run(['#f00'], rcOf({ dpr: 2 })));
    expect(ops[0].args).toEqual([0, 0, 10, 600]);
  });

  it('draws nothing while hidden', () => {
    const bg = new IndicatorBackground();
    bg.setColors(['#f00', '#f00'], bars(2));
    bg.setVisible(false);
    const { ctx, rec } = makeCtx();
    bg.draw(ctx, rcOf());
    expect(rec.ops).toHaveLength(0);
  });

  it('sits behind the series and contributes nothing to the pane scale', () => {
    const bg = new IndicatorBackground();
    expect(bg.zOrder()).toBe('bottom');
    expect(bg.autoscaleInfo()).toBeNull();
  });

  it('asks for a repaint when its colours or its visibility change', () => {
    let updates = 0;
    const host: PrimitiveHost = { requestUpdate: () => { updates += 1; } };
    const bg = new IndicatorBackground();
    bg.attached(host);
    bg.setColors(['#f00'], bars(1));
    bg.setVisible(false);
    expect(updates).toBe(2);
    bg.detached();
    bg.setColors(['#0f0'], bars(1)); // detached: nothing to ask
    expect(updates).toBe(2);
  });
});
