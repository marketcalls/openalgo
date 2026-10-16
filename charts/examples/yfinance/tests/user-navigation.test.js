import { describe, expect, it, vi } from 'vitest';
import { zoomVisibleRange } from '../src/rail.js';

describe('host zoom policy', () => {
  it('checks the current policy before changing the visible range', () => {
    let enabled = false, range = { from: 10, to: 110 };
    const chart = {
      navigationOptions: () => ({ zoomEnabled: enabled }),
      getVisibleLogicalRange: () => ({ ...range }),
      setVisibleLogicalRange: vi.fn(next => { range = next; }),
      timeScale: { width: 800, constrainBarSpacing: value => value },
    };
    expect(zoomVisibleRange(chart, 0.8)).toBe(false);
    expect(range).toEqual({ from: 10, to: 110 });
    expect(chart.setVisibleLogicalRange).not.toHaveBeenCalled();
    enabled = true;
    expect(zoomVisibleRange(chart, 0.8)).toBe(true);
    expect(range).toEqual({ from: 20, to: 100 });
    enabled = false;
    expect(zoomVisibleRange(chart, 1.25)).toBe(false);
    expect(range).toEqual({ from: 20, to: 100 });
  });
});
