import { describe, expect, it, vi } from 'vitest';
import type { ContextMenuEvent } from 'openalgo-charts';
import type { WidgetContext } from '../src/widget/context';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';

type Side = 'left' | 'right' | 'hidden';
function setup(side: Side = 'left', order = 1) {
  let placement: { side: Side; order: number } | null = { side, order };
  let layout = ['right', 'overlay:selected', 'overlay:outer'].map((scaleId, index) => ({
    scaleId, side: side === 'hidden' ? 'left' as const : side, order: index, x: index * 56, width: 56,
  }));
  const chart = {
    priceAxisState: vi.fn(() => ({ paneIndex: 2, scaleId: 'overlay:selected', side: 'right',
      active: true, movable: false, autoFit: true, inverted: false, lockRatio: false, scaled: true, mode: 'linear' })),
    priceAxisPlacement: vi.fn(() => placement === null ? null : { ...placement }),
    priceAxisLayout: vi.fn(() => layout),
    setPriceAxisPlacement: vi.fn(() => true),
    movePriceAxis: vi.fn(() => true),
    setPriceAxisAutoFit: vi.fn(), setPriceAxisOptions: vi.fn(), setPriceAxisLockRatio: vi.fn(() => true),
  };
  const ctx = { chart, toast: vi.fn() } as unknown as WidgetContext;
  const event: ContextMenuEvent = { paneIndex: 2, point: { x: 100, y: 50 }, price: null, time: null, index: null,
    preventDefault: () => {},
    target: { kind: 'price-scale', id: null, side: 'right', scaleId: 'overlay:selected' },
  };
  const entries = () => contextMenuEntries(ctx, event).filter(entry => !entry.kind || entry.kind === 'item') as MenuItem[];
  return { chart, entries, ctx, by: (id: string) => entries().find(entry => entry.id === id)!,
    placement: (value: typeof placement) => { placement = value; },
    layout: (value: typeof layout) => { layout = value; } };
}

describe('widget stable price-axis placement menu', () => {
  it('moves an occupied-side axis by stable ID using its actual placement', () => {
    const rig = setup();
    const move = rig.by('axis-move');
    expect(move.label).toBe('Move the scale to the right');
    expect(move.disabled).toBe(false);
    move.run?.();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenCalledWith(2, 'overlay:selected', 'right');
    expect(rig.chart.movePriceAxis).not.toHaveBeenCalled();
  });

  it('offers closer and further actions within the actual side', () => {
    const rig = setup();
    expect(rig.by('axis-closer').disabled).toBe(false);
    expect(rig.by('axis-further').disabled).toBe(false);
    rig.by('axis-closer').run?.();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenLastCalledWith(2, 'overlay:selected', 'left', 0);
    rig.by('axis-further').run?.();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenLastCalledWith(2, 'overlay:selected', 'left', 2);
  });

  it('bounds reordering by visible neighbors, including gaps in configured order', () => {
    const rig = setup('right', 4);
    rig.layout([{ scaleId: 'left', side: 'left', order: 0, x: 0, width: 56 },
      { scaleId: 'right', side: 'right', order: 0, x: 600, width: 56 },
      { scaleId: 'overlay:selected', side: 'right', order: 4, x: 656, width: 56 }]);
    expect(rig.by('axis-further').disabled).toBe(true);
    rig.by('axis-closer').run?.();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenCalledWith(2, 'overlay:selected', 'right', 0);
    rig.layout([{ scaleId: 'overlay:selected', side: 'right', order: 0, x: 600, width: 56 }]);
    expect(rig.entries().some(entry => entry.id === 'axis-closer' || entry.id === 'axis-further')).toBe(false);
  });

  it('reads placement again before running a retained menu action', () => {
    const rig = setup(), move = rig.by('axis-move'), closer = rig.by('axis-closer');
    rig.placement({ side: 'right', order: 1 });
    move.run?.();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenCalledWith(2, 'overlay:selected', 'left');
    rig.chart.setPriceAxisPlacement.mockClear();
    rig.placement(null);
    move.run?.(); closer.run?.();
    expect(rig.chart.setPriceAxisPlacement).not.toHaveBeenCalled();
    expect(rig.chart.movePriceAxis).not.toHaveBeenCalled();
  });

  it('retains exact scale targeting for autofit, modes and ratio locks', () => {
    const rig = setup();
    rig.by('axis-autofit').run?.(); rig.by('axis-mode-logarithmic').run?.(); rig.by('axis-lock').run?.();
    expect(rig.chart.setPriceAxisAutoFit).toHaveBeenCalledWith(2, 'overlay:selected', false);
    expect(rig.chart.setPriceAxisOptions).toHaveBeenCalledWith(2, 'overlay:selected', { mode: 'logarithmic' });
    expect(rig.chart.setPriceAxisLockRatio).toHaveBeenCalledWith(2, 'overlay:selected', true);
  });

  it('does not offer placement actions for a hidden or unavailable axis', () => {
    const rig = setup('hidden');
    expect(rig.entries().some(entry => ['axis-move', 'axis-closer', 'axis-further'].includes(entry.id!))).toBe(false);
    rig.placement(null);
    expect(rig.entries().some(entry => ['axis-move', 'axis-closer', 'axis-further'].includes(entry.id!))).toBe(false);
  });
});
