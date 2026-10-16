import { describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
import { initMenus, openAxisMenu, axisState } from '../src/menus.js';

function setup() {
  const { document } = installDom();
  for (const id of ['ctxmenu', 'axmenu', 'axsub', 'chart', 'status', 'chartset', 'setmodal']) {
    const node = document.createElement('div'); node.id = id; node.hidden = id !== 'chart'; document.body.appendChild(node);
  }
  let placement = { side: 'left', order: 1 };
  let layout = ['right', 'overlay:selected', 'overlay:outer'].map((scaleId, order) => ({ scaleId, side: 'left', order, x: order * 56, width: 56 }));
  const chart = {
    priceAxisState: vi.fn((paneIndex, scaleId) => ({ paneIndex, scaleId, side: 'right', movable: false,
      active: true, autoFit: true, inverted: false, scaled: true, lockRatio: false, mode: 'linear' })),
    priceAxisPlacement: vi.fn(() => placement === null ? null : { ...placement }),
    priceAxisLayout: vi.fn(() => layout),
    setPriceAxisPlacement: vi.fn((_pane, _id, side, order) => {
      placement = { side, order: order ?? 0 }; return true;
    }),
    movePriceAxis: vi.fn(() => true),
    setPriceAxisAutoFit: vi.fn(), setPriceAxisOptions: vi.fn(), setPriceAxisLockRatio: vi.fn(() => true),
  };
  initMenus({ chart });
  const open = () => openAxisMenu({ paneIndex: 2, point: { x: 30, y: 80 } }, { side: 'right', scaleId: 'overlay:selected' });
  open();
  const rows = () => document.getElementById('axmenu').querySelectorAll('button');
  const row = label => rows().find(button => button.querySelector('.axname').textContent === label);
  return { document, chart, row, rows, open, placement: value => { placement = value; }, layout: value => { layout = value; } };
}

describe('reference host stable price-axis placement menu', () => {
  it('moves the exact named scale onto an occupied side and keeps its menu target', () => {
    const rig = setup(), row = rig.row('Move the scale to the right');
    expect(row).toBeDefined(); expect(row.disabled).toBe(false); row.click();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenCalledWith(2, 'overlay:selected', 'right');
    expect(rig.chart.movePriceAxis).not.toHaveBeenCalled();
    expect(axisState().scaleId).toBe('overlay:selected');
    rig.row('Auto-fit to the data').click();
    expect(rig.chart.setPriceAxisAutoFit).toHaveBeenCalledWith(2, 'overlay:selected', false);
    expect(rig.row('Move the scale to the left')).toBeDefined();
  });

  it('moves toward adjacent visible columns and disables the outer edge', () => {
    const rig = setup();
    rig.row('Move the scale closer to the plot').click();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenLastCalledWith(2, 'overlay:selected', 'left', 0);
    rig.placement({ side: 'left', order: 1 }); rig.open();
    rig.row('Move the scale further from the plot').click();
    expect(rig.chart.setPriceAxisPlacement).toHaveBeenLastCalledWith(2, 'overlay:selected', 'left', 2);
    rig.layout([{ scaleId: 'right', side: 'left', order: 0, x: 0, width: 56 },
      { scaleId: 'overlay:selected', side: 'left', order: 2, x: 56, width: 56 }]); rig.open();
    expect(rig.row('Move the scale further from the plot').disabled).toBe(true);
  });

  it('does not retarget a retained move action when the named scale disappears', () => {
    const rig = setup(), row = rig.row('Move the scale to the right');
    expect(row).toBeDefined();
    rig.placement(null); row.click();
    expect(rig.chart.setPriceAxisPlacement).not.toHaveBeenCalled();
    expect(rig.chart.movePriceAxis).not.toHaveBeenCalled();
  });

  it('omits reorder actions for one visible column and all placement actions for a hidden scale', () => {
    const rig = setup();
    rig.layout([{ scaleId: 'overlay:selected', side: 'left', order: 0, x: 0, width: 56 }]); rig.open();
    expect(rig.row('Move the scale closer to the plot')).toBeUndefined();
    rig.placement({ side: 'hidden', order: 0 }); rig.open();
    expect(rig.rows().some(row => row.querySelector('.axname').textContent.startsWith('Move the scale'))).toBe(false);
  });
});
