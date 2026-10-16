import { describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
vi.mock('../src/volume.js', async importOriginal => ({ ...await importOriginal(), volumeShown: vi.fn(() => true), setVolumeShown: vi.fn() }));
import { initMenus, openContextMenu, paneCollapseRow, paneMoveRows } from '../src/menus.js';

/**
 * A three-pane stack that moves and folds panes the way the engine does: any
 * pane moves a slot, the price pane included, and the price pane never folds,
 * in whatever slot it sits.
 */
function stackChart(primary = 0) {
  const panes = ['a', 'b', 'c'];
  panes[primary] = 'price';
  let order = panes.slice();
  const folded = new Set();
  return {
    order: () => order.slice(),
    panes: () => order.map(name => ({ name })),
    primaryPaneIndex: vi.fn(() => order.indexOf('price')),
    movePane: vi.fn((index, direction) => {
      const target = index + direction;
      if (index < 0 || target < 0 || index >= order.length || target >= order.length) return false;
      order = order.slice();
      [order[index], order[target]] = [order[target], order[index]];
      return true;
    }),
    paneCollapsed: vi.fn(index => folded.has(order[index])),
    setPaneCollapsed: vi.fn((index, on) => {
      if (order[index] === 'price' || order[index] === undefined || folded.has(order[index]) === on) return false;
      if (on) folded.add(order[index]); else folded.delete(order[index]);
      return true;
    }),
    indicators: () => [],
    getDataContext: () => undefined,
  };
}

/** The right-click menu with the rows `openContextMenu` reads, in index.html's order. */
function setup(chart, chart2 = null) {
  const { document } = installDom();
  for (const id of ['ctxmenu', 'axmenu', 'axsub', 'chart', 'chart2', 'status', 'chartset', 'setmodal', 'volshow']) {
    const node = document.createElement('div'); node.id = id; node.hidden = id === 'axmenu' || id === 'axsub'; document.body.appendChild(node);
  }
  const menu = document.getElementById('ctxmenu');
  const add = (tag, attr, value) => {
    const node = document.createElement(tag);
    if (attr) node.setAttribute(attr, value);
    menu.appendChild(node);
    return node;
  };
  add('button', 'data-act', 'alert-create'); add('button', 'data-act', 'alert-list'); add('hr', 'data-sec', 'alerts');
  add('hr'); add('button', 'data-act', 'delsel'); add('button', 'data-act', 'delall');
  add('button', 'data-act', 'mark'); add('button', 'data-act', 'unmark');
  add('hr', 'data-sec', 'clip'); for (const act of ['copy', 'cut', 'paste']) add('button', 'data-act', act);
  add('hr', 'data-sec', 'ind'); add('button', 'data-act', 'indset');
  add('hr', 'data-sec', 'pane'); add('button', 'data-act', 'paneup'); add('button', 'data-act', 'panedown');
  add('button', 'data-act', 'panecollapse');
  add('hr', 'data-sec', 'vol'); add('button', 'data-act', 'volshow').appendChild(document.createElement('em'));
  const request = { symbol: 'X', interval: '1d', period: '1y' };
  initMenus({ chart, chart2, req: request, p2: { ...request }, currentBars: [], draw: null });
  const open = (paneIndex, kind = 'empty', pane = 1) =>
    openContextMenu({ paneIndex, point: { x: 10, y: 10 }, price: null, index: null, target: { kind, id: null } }, pane);
  const row = act => menu.querySelector(`[data-act="${act}"]`);
  const popupRow = pattern => [...document.body.querySelectorAll('.menu button')].find(button => pattern.test(button.innerHTML)) || null;
  return { open, row, rule: () => menu.querySelector('hr[data-sec="pane"]'), popupRow };
}

describe('reference host pane moves', () => {
  it('moves the price pane down to the bottom from the right-click menu and back up', () => {
    const chart = stackChart();
    const rig = setup(chart);
    rig.open(0);
    expect(rig.row('paneup').hidden).toBe(false);
    expect(rig.row('paneup').disabled).toBe(true);
    expect(rig.row('panedown').disabled).toBe(false);
    expect(rig.rule().hidden).toBe(false);
    // The price pane never folds, so the fold row stays out over it.
    expect(rig.row('panecollapse').hidden).toBe(true);
    rig.row('panedown').click();
    expect(chart.movePane).toHaveBeenLastCalledWith(0, 1);
    expect(chart.order()).toEqual(['b', 'price', 'c']);
    rig.open(1);
    rig.row('panedown').click();
    expect(chart.order()).toEqual(['b', 'c', 'price']);
    rig.open(2);
    expect(rig.row('panedown').disabled).toBe(true);
    expect(rig.row('panecollapse').hidden).toBe(true);
    rig.row('paneup').click();
    expect(chart.order()).toEqual(['b', 'price', 'c']);
  });

  it('folds the study pane that now sits at the top, and offers nothing over the time axis', () => {
    const chart = stackChart(2);
    const rig = setup(chart);
    rig.open(0);
    expect(rig.row('panecollapse').hidden).toBe(false);
    expect(rig.row('panecollapse').textContent).toBe('Collapse pane');
    rig.row('panecollapse').click();
    expect(chart.setPaneCollapsed).toHaveBeenLastCalledWith(0, true);
    rig.open(2, 'time-scale');
    expect(rig.row('paneup').hidden).toBe(true);
    expect(rig.row('panedown').hidden).toBe(true);
    expect(rig.row('panecollapse').hidden).toBe(true);
    expect(rig.rule().hidden).toBe(true);
  });

  it('gives the split chart its own move rows, acting on that chart', () => {
    const main = stackChart(), split = stackChart();
    const rig = setup(main, split);
    rig.open(0, 'empty', 2);
    const down = rig.popupRow(/Move pane down/);
    expect(down).not.toBeNull();
    down.click();
    expect(split.movePane).toHaveBeenLastCalledWith(0, 1);
    expect(main.movePane).not.toHaveBeenCalled();
    rig.open(1, 'empty', 2);
    expect(rig.popupRow(/Collapse pane/)).toBeNull();
  });

  it('describes the rows for any pane, and stays out of the menu on an engine that cannot move the price pane', () => {
    const chart = stackChart(1);
    expect(paneCollapseRow(chart, 1)).toBeNull();
    expect(paneCollapseRow(chart, 0)?.label).toBe('Collapse pane');
    const [up, down] = paneMoveRows(chart, 1);
    expect(up).toMatchObject({ label: 'Move pane up', disabled: false });
    expect(down).toMatchObject({ label: 'Move pane down', disabled: false });
    expect(paneMoveRows(chart, 0)[0].disabled).toBe(true);
    expect(paneMoveRows(chart, 2)[1].disabled).toBe(true);
    down.onSelect();
    expect(chart.movePane).toHaveBeenLastCalledWith(1, 1);
    expect(paneMoveRows({ movePane() {}, panes: () => [{}, {}] }, 0)).toEqual([]);
    expect(paneMoveRows(null, 0)).toEqual([]);
    expect(paneMoveRows(stackChart(), 5)).toEqual([]);
    // The price pane went down a slot, and the fold row follows it there.
    expect(paneCollapseRow(chart, 2)).toBeNull();
    expect(paneCollapseRow(chart, 1)?.label).toBe('Collapse pane');
  });

  it('greys the rows that would move a price pane the chart keeps pinned on top', () => {
    const chart = { ...stackChart(), movablePrimaryPane: () => false };
    const [topUp, topDown] = paneMoveRows(chart, 0);
    expect(topUp.disabled).toBe(true);
    expect(topDown).toMatchObject({ disabled: true, reason: 'The price pane stays on top on this chart' });
    const [studyUp, studyDown] = paneMoveRows(chart, 1);
    expect(studyUp).toMatchObject({ disabled: true, reason: 'The price pane stays on top on this chart' });
    expect(studyDown.disabled).toBe(false);
    const rig = setup(chart);
    rig.open(1);
    expect(rig.row('paneup').disabled).toBe(true);
    expect(rig.row('panedown').disabled).toBe(false);
  });
});
