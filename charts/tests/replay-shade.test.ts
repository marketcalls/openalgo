/**
 * The veil over the part of the session that has not happened yet.
 *
 * Picking a replay start means answering "from here, what happens next?", and
 * the question is only honest if the answer is hidden while it is asked. A user
 * who can see the next twenty bars while choosing where to start is choosing on
 * hindsight, which is the one thing replay exists to remove.
 */
import { describe, it, expect } from 'vitest';
import { ReplayShade } from '../src/primitives/replay-shade';
import { TimeScale } from '../src/scale/time-scale';
import { RecordingContext } from './helpers/fake-ctx';
import { fakeDocument } from './helpers/fake-dom';
import { Chart } from '../src/core/chart';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const PLOT_W = 800;
const PLOT_H = 400;
const SPACING = 10;

function context(dpr = 1): PrimitiveRenderContext {
  const ts = new TimeScale({ barSpacing: SPACING });
  ts.setWidth(PLOT_W);
  ts.setBaseIndex(99);
  ts.setRightOffset(0);
  return { timeScale: ts, plotWidth: PLOT_W, plotHeight: PLOT_H, dpr } as PrimitiveRenderContext;
}

function draw(shade: ReplayShade, dpr = 1): { rec: RecordingContext; rc: PrimitiveRenderContext } {
  const rec = new RecordingContext();
  const rc = context(dpr);
  shade.draw(rec as unknown as CanvasRenderingContext2D, rc);
  return { rec, rc };
}

const fills = (rec: RecordingContext) => rec.ops.filter((o) => o.type === 'fillRect');

describe('ReplayShade', () => {
  it('covers everything to the right of the chosen bar and nothing to its left', () => {
    const { rec, rc } = draw(new ReplayShade({ index: 60 }));
    const box = fills(rec)[0];
    expect(box).toBeDefined();
    // The cut sits on the chosen bar's right edge, so that bar stays visible:
    // it is the last one the user is allowed to have seen.
    const expected = Math.round(rc.timeScale.indexToX(60) + SPACING / 2);
    expect(box.args[0]).toBe(expected);
    expect(box.args[1]).toBe(0);
    expect(box.args[2]).toBe(PLOT_W - expected); // out to the right edge
    expect(box.args[3]).toBe(PLOT_H);
  });

  it('draws the divider at the cut, full height', () => {
    const { rec, rc } = draw(new ReplayShade({ index: 60 }));
    const moves = rec.ops.filter((o) => o.type === 'moveTo');
    const lines = rec.ops.filter((o) => o.type === 'lineTo');
    expect(moves).toHaveLength(1);
    const x = Math.round(rc.timeScale.indexToX(60) + SPACING / 2) + 0.5;
    expect(moves[0].args).toEqual([x, 0]);
    expect(lines[0].args).toEqual([x, PLOT_H]);
  });

  it('draws nothing when no bar is chosen, so one instance survives the mode', () => {
    expect(draw(new ReplayShade({ index: null })).rec.ops).toHaveLength(0);
  });

  it('draws nothing when the cut is off the right edge', () => {
    // Everything visible is in the past: there is no future to cover.
    expect(draw(new ReplayShade({ index: 500 })).rec.ops).toHaveLength(0);
  });

  it('still covers the whole plot when the cut is off the left edge', () => {
    const { rec } = draw(new ReplayShade({ index: -500 }));
    const box = fills(rec)[0];
    expect(box.args[0]).toBe(0);
    expect(box.args[2]).toBe(PLOT_W);
  });

  it('reports no hit, so the click that picks a bar reaches the chart', () => {
    expect(new ReplayShade({ index: 10 }).hitTest()).toBeNull();
  });

  it('draws over the series, because covering the future is the point', () => {
    expect(new ReplayShade({ index: 10 }).zOrder()).toBe('top');
  });

  it('leaves the context balanced', () => {
    const { rec } = draw(new ReplayShade({ index: 60 }));
    expect(rec.count('save')).toBe(rec.count('restore'));
  });

  it('scales the cut with device pixel ratio', () => {
    const one = draw(new ReplayShade({ index: 60 }), 1);
    const two = draw(new ReplayShade({ index: 60 }), 2);
    expect(fills(two.rec)[0].args[3]).toBe(fills(one.rec)[0].args[3] * 2);
  });

  it('can drop the divider and be restyled in place', () => {
    const shade = new ReplayShade({ index: 60, lineVisible: false });
    expect(draw(shade).rec.ops.filter((o) => o.type === 'moveTo')).toHaveLength(0);
    shade.setOptions({ index: null });
    expect(draw(shade).rec.ops).toHaveLength(0);
  });

  it('repaints the chart it is on when restyled, and stops asking once removed', () => {
    // A host moves the cut while picking a start and clears it on leaving the
    // mode. Neither may wait for something else to paint.
    const frames: (() => void)[] = [];
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      raf: { schedule: (cb) => { frames.push(cb); return frames.length; } },
      pixelRatio: () => 1,
      shortcuts: false,
    });
    chart.applySize(800, 400);
    const shade = new ReplayShade({ index: 10 });
    chart.addPrimitive(shade);
    for (const frame of frames.splice(0)) frame();
    expect(frames).toHaveLength(0);

    shade.setOptions({ index: 20 });
    expect(frames).toHaveLength(1);
    for (const frame of frames.splice(0)) frame();
    shade.setOptions({ index: null });
    expect(frames).toHaveLength(1);
    for (const frame of frames.splice(0)) frame();

    chart.removePrimitive(shade);
    for (const frame of frames.splice(0)) frame();
    shade.setOptions({ index: 30 });
    expect(frames).toHaveLength(0);
    chart.destroy();
  });
});
