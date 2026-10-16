import { describe, expect, it } from 'vitest';
import { registerBuiltinDrawingTools } from '../src/draw/tools';
import { registeredDrawingTools } from '../src/draw/registry';

const addedIds = [
  'disjoint-channel', 'flat-top-bottom', 'regression-channel',
  'pitchfork', 'schiff-pitchfork', 'modified-schiff-pitchfork', 'inside-pitchfork',
  'info-line', 'trend-angle', 'fib-extension-two-point', 'fib-speed-resistance-fan', 'icon-stamp',
  'trend-fib-time', 'fib-circles', 'fib-speed-resistance-arcs', 'fib-wedge', 'fib-spiral',
  'gann-square', 'dedekind-tessellation', 'sonic', 'supersonic', 'golden-sonic', 'golden-supersonic',
  'xabcd-pattern', 'abcd-pattern', 'elliott-impulse', 'elliott-correction', 'head-shoulders',
  'gartley', 'bat', 'butterfly', 'crab', 'shark', 'cypher',
];

describe('complete drawing catalog', () => {
  it('registers every additional drawing once without replacing existing tools', () => {
    registerBuiltinDrawingTools();
    registerBuiltinDrawingTools();
    const tools = registeredDrawingTools();
    const ids = tools.map(tool => tool.id);
    for (const id of addedIds) expect(ids, id).toContain(id);
    expect(new Set(ids).size).toBe(87);
    expect(ids.length).toBe(87);
    expect(ids).toContain('fib-fan');
    expect(ids).toContain('fib-extension');
  });

  it('includes interactive volume studies and leaves viewport tools outside the catalog', () => {
    registerBuiltinDrawingTools();
    const ids = registeredDrawingTools().map(tool => tool.id);
    expect(ids).toContain('anchored-vwap');
    expect(ids).toContain('fixed-range-volume-profile');
    expect(ids).not.toContain('magnifier');
  });
});
