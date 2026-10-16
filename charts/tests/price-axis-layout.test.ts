import { describe, expect, it } from 'vitest';
import { PriceAxisLayout, type PriceAxisPlacement, type PriceAxisSide } from '../src/model/price-axis-layout';
import type { PriceScaleId } from '../src/model/series';

function side(layout: PriceAxisLayout, value: PriceAxisSide): PriceScaleId[] {
  return layout.entries().filter(entry => entry.side === value)
    .sort((a, b) => a.order - b.order).map(entry => entry.scaleId);
}

describe('independent price axis placement', () => {
  it('starts with right and looks up defaults without creating unused scales', () => {
    const layout = new PriceAxisLayout();
    expect(layout.entries()).toEqual([{ scaleId: 'right', side: 'right', order: 0 }]);
    expect(layout.get('left')).toEqual({ side: 'left', order: 0 });
    expect(layout.get('overlay:one')).toEqual({ side: 'hidden', order: 0 });
    expect(layout.entries()).toHaveLength(1);
    layout.register('');
    expect(layout.get('overlay:one')).toEqual({ side: 'hidden', order: 1 });
    layout.register('overlay:one'); layout.register('left'); layout.register('');
    expect(layout.entries()).toEqual([
      { scaleId: 'right', side: 'right', order: 0 }, { scaleId: '', side: 'hidden', order: 0 },
      { scaleId: 'overlay:one', side: 'hidden', order: 1 }, { scaleId: 'left', side: 'left', order: 0 },
    ]);
  });

  it('inserts nearest the plot, shifts peers and appends on a side change', () => {
    const layout = new PriceAxisLayout();
    expect(layout.set('overlay:a', 'right')).toBe(true);
    expect(layout.set('overlay:b', 'right', 0)).toBe(true);
    expect(side(layout, 'right')).toEqual(['overlay:b', 'right', 'overlay:a']);
    expect(layout.get('right')).toEqual({ side: 'right', order: 1 });
    expect(layout.set('right', 'left')).toBe(true);
    expect(layout.set('overlay:a', 'left')).toBe(true);
    expect(side(layout, 'right')).toEqual(['overlay:b']);
    expect(side(layout, 'left')).toEqual(['right', 'overlay:a']);
    expect(layout.set('overlay:a', 'left', 0)).toBe(true);
    expect(side(layout, 'left')).toEqual(['overlay:a', 'right']);
  });

  it('clamps large safe orders, retains the same-side order and reports no-ops', () => {
    const layout = new PriceAxisLayout();
    layout.set('overlay:a', 'right'); layout.set('overlay:b', 'right');
    expect(layout.set('right', 'right', Number.MAX_SAFE_INTEGER)).toBe(true);
    expect(side(layout, 'right')).toEqual(['overlay:a', 'overlay:b', 'right']);
    expect(layout.set('right', 'right')).toBe(false);
    expect(layout.set('right', 'right', 900)).toBe(false);
    expect(layout.set('overlay:a', 'right', 0)).toBe(false);
    expect(layout.set('overlay:new', 'hidden')).toBe(false);
    expect(layout.entries()).toHaveLength(3);
  });

  it('keeps stable identities and side order when an owner is inactive', () => {
    const layout = new PriceAxisLayout();
    layout.set('overlay:vacant', 'right', 0); layout.set('overlay:active', 'right', 1);
    // Activity belongs to the pane, so asking for only active slots cannot erase a vacancy.
    expect(side(layout, 'right').filter(id => id !== 'overlay:vacant')).toEqual(['overlay:active', 'right']);
    expect(layout.get('overlay:vacant')).toEqual({ side: 'right', order: 0 });
    layout.register('overlay:vacant');
    expect(side(layout, 'right')).toEqual(['overlay:vacant', 'overlay:active', 'right']);
    expect(layout.entries().map(entry => entry.scaleId)).toEqual(['right', 'overlay:vacant', 'overlay:active']);
  });

  it('normalizes hidden order without changing scale identity', () => {
    const layout = new PriceAxisLayout();
    layout.register(''); layout.register('overlay:a');
    layout.set('right', 'hidden', 1);
    expect(side(layout, 'hidden')).toEqual(['', 'right', 'overlay:a']);
    layout.set('', 'left');
    expect(side(layout, 'hidden')).toEqual(['right', 'overlay:a']);
    expect(layout.get('overlay:a').order).toBe(1);
  });

  it.each([
    ['right', 'middle', undefined], ['right', 'left', -1], ['right', 'left', 1.5],
    ['right', 'left', NaN], ['right', 'left', Infinity], ['right', 'left', Number.MAX_SAFE_INTEGER + 1],
    ['right', 'left', '1'], ['right', 'left', null], ['custom', 'right', 0], [null, 'right', 0],
  ])('rejects invalid mutation atomically (%#)', (id, value, order) => {
    const layout = new PriceAxisLayout();
    layout.set('overlay:a', 'right');
    const before = layout.entries();
    expect(layout.set(id as PriceScaleId, value as PriceAxisSide, order as number | undefined)).toBe(false);
    expect(layout.entries()).toEqual(before);
  });

  it('does not register unknown identities when a mutation has invalid placement', () => {
    const layout = new PriceAxisLayout();
    expect(layout.set('overlay:new', 'left', -1)).toBe(false);
    layout.register('bad' as PriceScaleId);
    expect(layout.entries()).toEqual([{ scaleId: 'right', side: 'right', order: 0 }]);
  });

  it('returns detached placement snapshots', () => {
    const layout = new PriceAxisLayout();
    const value = layout.get('right'); value.side = 'hidden'; value.order = 9;
    const entries = layout.entries(); entries[0].side = 'left'; entries[0].order = 3;
    expect(layout.get('right')).toEqual({ side: 'right', order: 0 });
  });

  it('restores saved order independently of serialization order and retains ties stably', () => {
    const layout = new PriceAxisLayout();
    layout.register('left'); layout.register('overlay:a'); layout.register('overlay:b');
    layout.restore(new Map<PriceScaleId, PriceAxisPlacement>([
      ['overlay:b', { side: 'right', order: 2 }], ['right', { side: 'left', order: 1 }],
      ['overlay:a', { side: 'right', order: 0 }], ['left', { side: 'right', order: 2 }],
      ['overlay:new', { side: 'left', order: 0 }],
    ]));
    expect(side(layout, 'right')).toEqual(['overlay:a', 'left', 'overlay:b']);
    expect(side(layout, 'left')).toEqual(['overlay:new', 'right']);
    expect(layout.entries().map(entry => entry.scaleId)).toEqual(['right', 'left', 'overlay:a', 'overlay:b', 'overlay:new']);
    expect(layout.get('overlay:b')).toEqual({ side: 'right', order: 2 });
  });

  it('resets omitted placements to defaults and detaches supplied overrides', () => {
    const layout = new PriceAxisLayout();
    layout.register('left'); layout.set('overlay:a', 'right'); layout.set('overlay:b', 'left');
    const override: PriceAxisPlacement = { side: 'left', order: 0 };
    layout.restore(new Map([['overlay:a', override]]));
    override.side = 'right'; override.order = 9;
    expect(layout.get('right')).toEqual({ side: 'right', order: 0 });
    expect(side(layout, 'left')).toEqual(['left', 'overlay:a']);
    expect(layout.get('overlay:b')).toEqual({ side: 'hidden', order: 0 });
    layout.restore(new Map());
    expect(side(layout, 'hidden')).toEqual(['overlay:a', 'overlay:b']);
    expect(layout.get('left')).toEqual({ side: 'left', order: 0 });
  });

  it('supports existing empty and long overlay names without a fixed count limit', () => {
    const layout = new PriceAxisLayout();
    layout.register('overlay:'); layout.register(`overlay:${'x'.repeat(240)}`);
    for (let i = 0; i < 513; i++) layout.register(`overlay:${i}`);
    expect(layout.entries()).toHaveLength(516);
    expect(layout.get('overlay:512')).toEqual({ side: 'hidden', order: 514 });
  });
});
