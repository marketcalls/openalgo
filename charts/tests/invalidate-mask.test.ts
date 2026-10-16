import { describe, it, expect } from 'vitest';
import { InvalidateMask, InvalidationLevel } from '../src/core/invalidate-mask';

describe('InvalidateMask', () => {
  it('global level is monotonic (only increases)', () => {
    const m = new InvalidateMask();
    expect(m.globalLevel).toBe(InvalidationLevel.None);
    m.invalidateGlobal(InvalidationLevel.Light);
    expect(m.globalLevel).toBe(InvalidationLevel.Light);
    m.invalidateGlobal(InvalidationLevel.Cursor); // lower: ignored
    expect(m.globalLevel).toBe(InvalidationLevel.Light);
    m.invalidateGlobal(InvalidationLevel.Full);
    expect(m.globalLevel).toBe(InvalidationLevel.Full);
  });

  it('per-pane invalidation is independent and merges by max + OR', () => {
    const m = new InvalidateMask();
    m.invalidatePane(2, { level: InvalidationLevel.Cursor, autoScale: false });
    m.invalidatePane(2, { level: InvalidationLevel.Light, autoScale: true });
    expect(m.paneInvalidation(2)).toEqual({ level: InvalidationLevel.Light, autoScale: true });
    expect(m.paneInvalidation(0)).toBeUndefined(); // pane 0 untouched
    expect(m.globalLevel).toBe(InvalidationLevel.None); // per-pane doesn't raise global
  });

  it('queues time-scale ops in order', () => {
    const m = new InvalidateMask();
    m.addTimeScaleOp({ type: 'fitContent' });
    m.addTimeScaleOp({ type: 'applyBarSpacing', value: 8 });
    expect(m.timeScaleOps()).toEqual([
      { type: 'fitContent' },
      { type: 'applyBarSpacing', value: 8 },
    ]);
  });

  it('isEmpty reflects all three channels', () => {
    const m = new InvalidateMask();
    expect(m.isEmpty()).toBe(true);
    m.invalidatePane(0, { level: InvalidationLevel.Cursor, autoScale: false });
    expect(m.isEmpty()).toBe(false);
  });

  it('merge coalesces global, panes and ops', () => {
    const a = new InvalidateMask(InvalidationLevel.Cursor);
    a.invalidatePane(0, { level: InvalidationLevel.Light, autoScale: false });
    a.addTimeScaleOp({ type: 'reset' });

    const b = new InvalidateMask(InvalidationLevel.Full);
    b.invalidatePane(0, { level: InvalidationLevel.Cursor, autoScale: true });
    b.invalidatePane(1, { level: InvalidationLevel.Light, autoScale: false });
    b.addTimeScaleOp({ type: 'fitContent' });

    a.merge(b);
    expect(a.globalLevel).toBe(InvalidationLevel.Full);
    expect(a.paneInvalidation(0)).toEqual({ level: InvalidationLevel.Light, autoScale: true });
    expect(a.paneInvalidation(1)).toEqual({ level: InvalidationLevel.Light, autoScale: false });
    expect(a.timeScaleOps()).toEqual([{ type: 'reset' }, { type: 'fitContent' }]);
  });
});
