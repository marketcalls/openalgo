import { describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
vi.mock('../src/volume.js', async importOriginal => ({ ...await importOriginal(), volumeShown: vi.fn(() => true), setVolumeShown: vi.fn() }));
import { initMenus, openContextMenu, paneCollapseRow } from '../src/menus.js';

/** A chart that folds panes the way the engine does: pane 0 never folds. */
function foldingChart() {
  const folded = new Set();
  return {
    paneCollapsed: vi.fn(index => folded.has(index)),
    setPaneCollapsed: vi.fn((index, on) => {
      if (!(index > 0) || folded.has(index) === on) return false;
      if (on) folded.add(index); else folded.delete(index);
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
  // The session mark rows the page declares after Remove All.
  add('button', 'data-act', 'mark'); add('button', 'data-act', 'unmark');
  add('hr', 'data-sec', 'clip'); for (const act of ['copy', 'cut', 'paste']) add('button', 'data-act', act);
  add('hr', 'data-sec', 'ind'); add('button', 'data-act', 'indset');
  add('hr', 'data-sec', 'pane'); add('button', 'data-act', 'panecollapse');
  add('hr', 'data-sec', 'vol'); add('button', 'data-act', 'volshow').appendChild(document.createElement('em'));
  const request = { symbol: 'X', interval: '1d', period: '1y' };
  initMenus({ chart, chart2, req: request, p2: { ...request }, currentBars: [], draw: null });
  const open = (paneIndex, kind = 'empty', pane = 1) =>
    openContextMenu({ paneIndex, point: { x: 10, y: 10 }, price: null, index: null, target: { kind, id: null } }, pane);
  const row = () => menu.querySelector('[data-act="panecollapse"]');
  const rule = () => menu.querySelector('hr[data-sec="pane"]');
  // The second chart's menu is a popup built per open, not the static menu.
  const popupRow = () => [...document.body.querySelectorAll('.menu button')]
    .find(button => /(Collapse|Expand) pane/.test(button.innerHTML)) || null;
  return { open, row, rule, popupRow };
}

describe('reference host pane collapse', () => {
  it('offers a lower pane both ways from the right-click menu', () => {
    const chart = foldingChart();
    const rig = setup(chart);
    rig.open(2);
    expect(rig.row().hidden).toBe(false);
    expect(rig.rule().hidden).toBe(false);
    expect(rig.row().textContent).toBe('Collapse pane');
    rig.row().click();
    expect(chart.setPaneCollapsed).toHaveBeenLastCalledWith(2, true);
    rig.open(2);
    expect(rig.row().textContent).toBe('Expand pane');
    rig.row().click();
    expect(chart.setPaneCollapsed).toHaveBeenLastCalledWith(2, false);
    expect(chart.paneCollapsed(2)).toBe(false);
  });

  it('leaves the row out over the price pane and the time axis', () => {
    const rig = setup(foldingChart());
    rig.open(0);
    expect(rig.row().hidden).toBe(true);
    expect(rig.rule().hidden).toBe(true);
    rig.open(1, 'time-scale');
    expect(rig.row().hidden).toBe(true);
  });

  it('offers the split chart its own row, acting on that chart', () => {
    const main = foldingChart(), split = foldingChart();
    const rig = setup(main, split);
    rig.open(1, 'empty', 2);
    expect(rig.popupRow()?.innerHTML).toContain('Collapse pane');
    rig.popupRow().click();
    expect(split.setPaneCollapsed).toHaveBeenLastCalledWith(1, true);
    expect(main.setPaneCollapsed).not.toHaveBeenCalled();
    rig.open(1, 'empty', 2);
    expect(rig.popupRow()?.innerHTML).toContain('Expand pane');
    rig.popupRow().click();
    expect(split.paneCollapsed(1)).toBe(false);
    rig.open(1, 'time-scale', 2);
    expect(rig.popupRow()).toBeNull();
    rig.open(0, 'empty', 2);
    expect(rig.popupRow()).toBeNull();
  });

  it('stays out of the menu on an engine without pane collapse', () => {
    expect(paneCollapseRow({}, 1)).toBeNull();
    expect(paneCollapseRow(null, 1)).toBeNull();
    expect(paneCollapseRow(foldingChart(), 0)).toBeNull();
  });
});
