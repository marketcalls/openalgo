import { describe, it, expect } from 'vitest';
import { RenderLoop } from '../src/core/render-loop';
import { computeGridLines } from '../src/render/grid';

describe('RenderLoop coalescing', () => {
  it('collapses many requestFrame calls into one onFrame', () => {
    const pending: Array<() => void> = [];
    let frames = 0;
    const loop = new RenderLoop(
      () => { frames++; },
      (cb) => { pending.push(cb); return pending.length; },
    );

    loop.requestFrame();
    loop.requestFrame();
    loop.requestFrame();
    expect(loop.scheduled).toBe(true);
    expect(pending).toHaveLength(1); // only one frame scheduled

    pending[0](); // run the frame
    expect(frames).toBe(1);
    expect(loop.scheduled).toBe(false);

    // a new request after the frame schedules again
    loop.requestFrame();
    expect(pending).toHaveLength(2);
  });

  it('stop() cancels a pending frame', () => {
    let cancelled = -1;
    const loop = new RenderLoop(
      () => {},
      () => 42,
      (h) => { cancelled = h; },
    );
    loop.requestFrame();
    expect(loop.scheduled).toBe(true);
    loop.stop();
    expect(loop.scheduled).toBe(false);
    expect(cancelled).toBe(42);
  });
});

describe('grid geometry', () => {
  it('never places a line on the 0 edge and stops before the far edge', () => {
    const lines = computeGridLines(120, 120, { spacing: 60 });
    expect(lines.verticals).toEqual([60]); // 0 excluded, 120 excluded
    expect(lines.horizontals).toEqual([60]);
  });

  it('handles tiny panes without infinite loops', () => {
    const lines = computeGridLines(10, 10, { spacing: 60 });
    expect(lines.verticals).toEqual([]);
    expect(lines.horizontals).toEqual([]);
  });
});
